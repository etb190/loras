"""Minimal async client for the public Civitai REST API.

Only metadata endpoints are used. The client never downloads model files;
it performs plain JSON GET requests against ``https://civitai.com/api/v1``
and attaches a ``Bearer`` token when one is configured (required for
mature/hidden models and useful against anonymous rate limits).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

API_BASE = "https://civitai.com/api/v1"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=45)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0

REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "LorasMetadataManager/1.0 (standalone metadata catalog)",
}


class CivitaiError(Exception):
    """Raised when a Civitai API request fails in a way the UI should show."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class CivitaiClient:
    """Small aiohttp-backed client for the Civitai metadata endpoints."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=DEFAULT_TIMEOUT, headers=REQUEST_HEADERS
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _get_json(self, url: str, token: Optional[str]) -> Dict[str, Any]:
        """GET a JSON document with retries for transient failures."""

        headers: Dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        last_error: CivitaiError = CivitaiError("Request did not complete")
        for attempt in range(MAX_RETRIES):
            session = await self._get_session()
            try:
                async with session.get(url, headers=headers) as response:
                    status = response.status
                    if status in (200, 304):
                        payload = await response.json(content_type=None)
                        if isinstance(payload, dict):
                            return payload
                        raise CivitaiError("Unexpected response payload", status=status)
                    if status in (401, 403):
                        detail = await response.text()
                        raise CivitaiError(
                            _auth_error_message(status, detail), status=status
                        )
                    if status == 404:
                        raise CivitaiError(
                            "Not found on Civitai. If this is a mature model, "
                            "configure a Civitai token that can view it.",
                            status=status,
                        )
                    if status == 429:
                        raise CivitaiError(
                            "Civitai rate limit reached. Wait a moment and try again.",
                            status=status,
                        )
                    # 5xx and other codes: retry with backoff.
                    last_error = CivitaiError(
                        f"Civitai responded with HTTP {status}", status=status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = CivitaiError(f"Network error: {exc}")
            except CivitaiError as exc:
                # 401/403/404/429 are terminal - do not retry.
                if exc.status in (401, 403, 404, 429):
                    raise
                last_error = exc

            if attempt + 1 < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise last_error

    async def fetch_model(self, model_id: int, token: Optional[str] = None) -> Dict[str, Any]:
        """Fetch the full model document (includes all versions)."""

        return await self._get_json(f"{API_BASE}/models/{model_id}", token)

    async def fetch_version(self, version_id: int, token: Optional[str] = None) -> Dict[str, Any]:
        """Fetch a single model version document (includes ``modelId``)."""

        return await self._get_json(f"{API_BASE}/model-versions/{version_id}", token)

    async def resolve_link(
        self, model_id: Optional[int], version_id: Optional[int], token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve a parsed link to a full model document.

        When only a version id is known the version is fetched first, then its
        parent model document; ``linked_version_id`` in the result records
        which version the user actually pointed at.
        """

        linked_version_id = version_id
        if model_id is None and version_id is not None:
            version = await self.fetch_version(version_id, token)
            model_id = version.get("modelId")
            if not model_id:
                raise CivitaiError(
                    f"Version {version_id} did not report a parent model id"
                )
            model = await self.fetch_model(int(model_id), token)
            model["_linkedVersionId"] = linked_version_id
            return model

        model = await self.fetch_model(int(model_id), token)  # type: ignore[arg-type]
        model["_linkedVersionId"] = linked_version_id
        return model


def _auth_error_message(status: int, detail: str) -> str:
    if "token" in detail.lower() or status == 401:
        return "Civitai rejected the token (HTTP 401). Check that the API key is valid."
    return (
        "Civitai refused the request (HTTP 403). This usually means the model "
        "requires a token with access to it, or the host blocked the request."
    )
