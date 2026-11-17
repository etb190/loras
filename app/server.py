"""aiohttp web server: static UI + JSON API.

The API is intentionally small:

- ``POST /api/fetch``            - resolve Civitai links into metadata entries
- ``GET  /api/models``           - list stored entries (search/filter)
- ``GET  /api/models/{id}``     - full stored document
- ``DELETE /api/models/{id}``    - remove an entry
- ``POST /api/models/{id}/refresh`` - re-fetch from Civitai
- ``GET  /api/export``          - download the whole catalog as JSON
- ``GET/PUT/DELETE /api/token``  - manage the optional server-side token
- ``GET  /api/meta``            - filter options and counts
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from aiohttp import web

from .civitai import CivitaiClient, CivitaiError
from .store import MetadataStore, summarize_model
from .urls import parse_civitai_link, split_links

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def create_app(data_dir: str) -> web.Application:
    store = MetadataStore(data_dir)
    client = CivitaiClient()
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app["store"] = store
    app["civitai"] = client

    # ------------------------------------------------------------ static UI
    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(os.path.join(STATIC_DIR, "index.html"))

    app.router.add_get("/", index)
    app.router.add_static("/static/", STATIC_DIR)

    # -------------------------------------------------------------- health
    async def health(_request: web.Request) -> web.Response:
        summaries = store.list_models()
        return web.json_response(
            {"status": "ok", "models": len(summaries)}
        )

    app.router.add_get("/api/health", health)

    # --------------------------------------------------------------- token
    async def get_token(_request: web.Request) -> web.Response:
        return web.json_response({"hasToken": store.get_token() is not None})

    async def put_token(request: web.Request) -> web.Response:
        body = await _json_body(request)
        token = body.get("token")
        if token is not None and not isinstance(token, str):
            raise web.HTTPBadRequest(text="token must be a string")
        store.set_token(token)
        return web.json_response({"hasToken": store.get_token() is not None})

    async def delete_token(_request: web.Request) -> web.Response:
        store.set_token(None)
        return web.json_response({"hasToken": False})

    app.router.add_get("/api/token", get_token)
    app.router.add_put("/api/token", put_token)
    app.router.add_post("/api/token", put_token)
    app.router.add_delete("/api/token", delete_token)

    # --------------------------------------------------------------- fetch
    async def fetch_models(request: web.Request) -> web.Response:
        body = await _json_body(request)
        raw_links = body.get("urls")
        if isinstance(raw_links, str):
            raw_links = split_links(raw_links)
        if not isinstance(raw_links, list) or not raw_links:
            raise web.HTTPBadRequest(text="Provide a non-empty 'urls' list")
        # Normalize: each element may itself hold several links ("a, b") and
        # stray quotes; split_links flattens everything into clean candidates.
        normalized_links: list[str] = []
        for item in raw_links:
            normalized_links.extend(split_links(str(item)))
        raw_links = normalized_links
        if not raw_links:
            raise web.HTTPBadRequest(text="Provide a non-empty 'urls' list")

        token = body.get("token") or store.get_token()

        fetched: list[Dict[str, Any]] = []
        errors: list[Dict[str, Any]] = []
        seen_models: set[int] = set()
        seen_versions: set[int] = set()

        for raw in raw_links[:50]:  # hard cap to protect the API
            link = parse_civitai_link(str(raw))
            if link.is_empty:
                errors.append({"url": str(raw), "error": "Not a recognized Civitai link"})
                continue

            # Batch de-duplication: the whole model document (all versions) is
            # stored per model id, so one fetch covers the model. A version-only
            # duplicate just re-points the stored entry at that version.
            if link.model_id is not None and link.model_id in seen_models:
                if link.version_id is None or link.version_id in seen_versions:
                    continue
                stored = store.get_model(link.model_id)
                if stored is not None:
                    stored["_linkedVersionId"] = link.version_id
                    model = store.save_model(stored, source_url=link.page_url())
                    fetched.append(summarize_model(model))
                    seen_versions.add(link.version_id)
                    continue

            try:
                model = await client.resolve_link(
                    link.model_id, link.version_id, token
                )
                model = store.save_model(model, source_url=link.page_url())
                fetched.append(summarize_model(model))
                if model.get("id") is not None:
                    seen_models.add(int(model["id"]))
                if link.version_id is not None:
                    seen_versions.add(link.version_id)
                if model.get("_linkedVersionId") is not None:
                    seen_versions.add(int(model["_linkedVersionId"]))
            except CivitaiError as exc:
                errors.append({"url": link.page_url() or str(raw), "error": str(exc)})
            except Exception as exc:  # defensive: keep batch going
                logger.exception("Unexpected failure fetching %s", raw)
                errors.append({"url": str(raw), "error": f"Unexpected error: {exc}"})

        return web.json_response({"fetched": fetched, "errors": errors})

    app.router.add_post("/api/fetch", fetch_models)

    # -------------------------------------------------------------- models
    async def list_models(request: web.Request) -> web.Response:
        summaries = store.list_models()
        query = (request.query.get("q") or "").strip().lower()
        model_type = (request.query.get("type") or "").strip().lower()
        base_model = (request.query.get("baseModel") or "").strip().lower()

        def matches(summary: Dict[str, Any]) -> bool:
            if model_type and str(summary.get("type") or "").lower() != model_type:
                return False
            if base_model and base_model not in (
                b.lower() for b in summary.get("baseModels") or []
            ):
                return False
            if query:
                haystack = " ".join(
                    [
                        str(summary.get("name") or ""),
                        str(summary.get("creator") or ""),
                        " ".join(summary.get("tags") or []),
                        " ".join(summary.get("trainedWords") or []),
                        str(summary.get("id") or ""),
                    ]
                ).lower()
                if query not in haystack:
                    return False
            return True

        return web.json_response({"models": [s for s in summaries if matches(s)]})

    async def get_model(request: web.Request) -> web.Response:
        model = store.get_model(_int_arg(request))
        if model is None:
            raise web.HTTPNotFound(text="Model not found in catalog")
        return web.json_response(model)

    async def delete_model(request: web.Request) -> web.Response:
        if not store.delete_model(_int_arg(request)):
            raise web.HTTPNotFound(text="Model not found in catalog")
        return web.json_response({"deleted": True})

    async def refresh_model(request: web.Request) -> web.Response:
        model_id = _int_arg(request)
        existing = store.get_model(model_id)
        if existing is None:
            raise web.HTTPNotFound(text="Model not found in catalog")
        token = (await _json_body(request, required=False)).get("token") or store.get_token()
        try:
            model = await client.resolve_link(model_id, None, token)
            model["_sourceUrls"] = existing.get("_sourceUrls") or []
            model = store.save_model(model, source_url="")
            return web.json_response(summarize_model(model))
        except CivitaiError as exc:
            raise web.HTTPBadRequest(text=str(exc))

    app.router.add_get("/api/models", list_models)
    app.router.add_get(r"/api/models/{id:\d+}", get_model)
    app.router.add_delete(r"/api/models/{id:\d+}", delete_model)
    app.router.add_post(r"/api/models/{id:\d+}/refresh", refresh_model)

    # -------------------------------------------------------------- export
    async def export_all(_request: web.Request) -> web.Response:
        payload = store.export_all()
        response = web.json_response(payload)
        response.headers["Content-Disposition"] = "attachment; filename=loras-metadata-export.json"
        return response

    app.router.add_get("/api/export", export_all)

    # ---------------------------------------------------------------- meta
    async def meta(_request: web.Request) -> web.Response:
        summaries = store.list_models()
        types: Dict[str, int] = {}
        base_models: Dict[str, int] = {}
        for summary in summaries:
            model_type = summary.get("type") or "Unknown"
            types[model_type] = types.get(model_type, 0) + 1
            for base in summary.get("baseModels") or []:
                base_models[base] = base_models.get(base, 0) + 1
        return web.json_response(
            {
                "count": len(summaries),
                "hasToken": store.get_token() is not None,
                "types": dict(sorted(types.items())),
                "baseModels": dict(sorted(base_models.items())),
            }
        )

    app.router.add_get("/api/meta", meta)

    # ------------------------------------------------------------ shutdown
    async def on_shutdown(_app: web.Application) -> None:
        await client.close()

    app.on_shutdown.append(on_shutdown)
    return app


async def _json_body(request: web.Request, required: bool = True) -> Dict[str, Any]:
    if not required:
        if not request.can_read_body:
            return {}
        try:
            body = await request.json()
            return body if isinstance(body, dict) else {}
        except Exception:
            return {}
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Request body must be JSON")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Request body must be a JSON object")
    return body


def _int_arg(request: web.Request) -> int:
    try:
        return int(request.match_info["id"])
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(text="Model id must be numeric")
