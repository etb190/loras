"""Local persistence for fetched Civitai metadata.

Everything lives under a single data directory (default ``<repo>/data``,
overridable with ``--data-dir`` or ``LORAS_DATA_DIR``):

- ``metadata/{modelId}.json`` - the full Civitai model document, enriched with
  ``_linkedVersionId``, ``_fetchedAt`` and ``_sourceUrls`` bookkeeping fields.
- ``settings.json`` - optional server-side Civitai token (gitignored).

No model files are ever stored here - only JSON metadata.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
METADATA_DIR = "metadata"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MetadataStore:
    """JSON-file-backed store for model metadata and settings."""

    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(os.path.expanduser(data_dir))
        self.metadata_dir = os.path.join(self.data_dir, METADATA_DIR)
        self.settings_path = os.path.join(self.data_dir, SETTINGS_FILE)
        self._lock = threading.Lock()
        os.makedirs(self.metadata_dir, exist_ok=True)

    # ------------------------------------------------------------------ paths

    def _model_path(self, model_id: int) -> str:
        return os.path.join(self.metadata_dir, f"{model_id}.json")

    # ---------------------------------------------------------------- settings

    def get_token(self) -> Optional[str]:
        settings = self._read_settings()
        token = settings.get("civitai_token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        return None

    def set_token(self, token: Optional[str]) -> None:
        with self._lock:
            settings = self._read_settings()
            if token is None or not token.strip():
                settings.pop("civitai_token", None)
            else:
                settings["civitai_token"] = token.strip()
            self._write_settings(settings)

    def _read_settings(self) -> Dict[str, Any]:
        try:
            with open(self.settings_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s: %s", self.settings_path, exc)
            return {}

    def _write_settings(self, settings: Dict[str, Any]) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        tmp_path = self.settings_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
        os.replace(tmp_path, self.settings_path)

    # ----------------------------------------------------------------- models

    def save_model(self, model: Dict[str, Any], source_url: str) -> Dict[str, Any]:
        """Persist a fetched model document, merging source-url bookkeeping."""

        model_id = model.get("id")
        if model_id is None:
            raise ValueError("Model document has no id")
        model_id = int(model_id)

        with self._lock:
            existing = self._read_model(model_id)
            source_urls: List[str] = []
            if existing:
                source_urls = list(existing.get("_sourceUrls") or [])
            if source_url and source_url not in source_urls:
                source_urls.append(source_url)

            model = dict(model)
            if model.get("_linkedVersionId") is None:
                # A plain model re-fetch must not clear a version link that an
                # earlier fetch established.
                model["_linkedVersionId"] = (existing or {}).get("_linkedVersionId")
            model["_sourceUrls"] = source_urls
            model["_fetchedAt"] = utc_now_iso()
            model.setdefault("_linkedVersionId", None)

            tmp_path = self._model_path(model_id) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(model, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._model_path(model_id))

        return model

    def _read_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        try:
            with open(self._model_path(model_id), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read metadata for %s: %s", model_id, exc)
            return None

    def get_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._read_model(model_id)

    def delete_model(self, model_id: int) -> bool:
        path = self._model_path(model_id)
        with self._lock:
            if not os.path.exists(path):
                return False
            os.remove(path)
        return True

    def list_models(self) -> List[Dict[str, Any]]:
        """Return summaries for every stored model, newest fetch first."""

        summaries: List[Dict[str, Any]] = []
        with self._lock:
            try:
                entries = sorted(os.listdir(self.metadata_dir))
            except OSError:
                entries = []
            for name in entries:
                if not name.endswith(".json"):
                    continue
                try:
                    model_id = int(name[: -len(".json")])
                except ValueError:
                    continue
                model = self._read_model(model_id)
                if model:
                    summaries.append(summarize_model(model))
        summaries.sort(key=lambda item: item.get("fetchedAt") or "", reverse=True)
        return summaries

    def export_all(self) -> Dict[str, Any]:
        with self._lock:
            payload: List[Dict[str, Any]] = []
            try:
                entries = sorted(os.listdir(self.metadata_dir))
            except OSError:
                entries = []
            for name in entries:
                if not name.endswith(".json"):
                    continue
                try:
                    with open(
                        os.path.join(self.metadata_dir, name), "r", encoding="utf-8"
                    ) as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        payload.append(data)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Skipping %s during export: %s", name, exc)
        payload.sort(key=lambda item: str(item.get("_fetchedAt") or ""))
        return {"exportedAt": utc_now_iso(), "models": payload}


# ----------------------------------------------------------------- summaries


def summarize_model(model: Dict[str, Any]) -> Dict[str, Any]:
    """Build the compact card/list representation of a stored model."""

    versions = model.get("modelVersions") or []
    linked_version_id = model.get("_linkedVersionId")
    linked_version = None
    if linked_version_id:
        linked_version = next(
            (v for v in versions if v.get("id") == linked_version_id), None
        )
    primary_version = linked_version or (versions[0] if versions else None)

    base_models: List[str] = []
    for version in versions:
        base = version.get("baseModel")
        if base and base not in base_models:
            base_models.append(base)

    cover_image = model.get("coverImage") or (
        (primary_version or {}).get("images") or [{}]
    )[0]

    stats = model.get("stats") or {}
    return {
        "id": model.get("id"),
        "name": model.get("name"),
        "type": model.get("type"),
        "creator": (model.get("creator") or {}).get("username"),
        "tags": model.get("tags") or [],
        "nsfw": bool(model.get("nsfw")),
        "nsfwLevel": model.get("nsfwLevel"),
        "baseModels": base_models,
        "coverImage": _image_payload(cover_image) if cover_image else None,
        "trainedWords": (primary_version or {}).get("trainedWords") or [],
        "versionCount": len(versions),
        "linkedVersionId": linked_version_id,
        "latestVersionId": (versions[0] or {}).get("id") if versions else None,
        "latestVersionName": (versions[0] or {}).get("name") if versions else None,
        "availability": model.get("availability"),
        "stats": {
            "thumbsUpCount": stats.get("thumbsUpCount"),
            "downloadCount": stats.get("downloadCount"),
            "commentCount": stats.get("commentCount"),
        },
        "fetchedAt": model.get("_fetchedAt"),
        "sourceUrls": model.get("_sourceUrls") or [],
        "pageUrl": f"https://civitai.com/models/{model.get('id')}",
    }


def _image_payload(image: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "url": image.get("url"),
        "width": image.get("width"),
        "height": image.get("height"),
        "type": image.get("type"),
        "nsfwLevel": image.get("nsfwLevel"),
    }
