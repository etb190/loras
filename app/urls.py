"""Civitai link parsing.

Supports the same link shapes as ComfyUI-Lora-Manager (which this project is
derived from):

- https://civitai.com/models/{id}
- https://civitai.com/models/{id}/{slug}
- https://civitai.com/models/{id}?modelVersionId={versionId}
- https://civitai.com/models/{id}/{slug}?modelVersionId={versionId}
- https://civitai.com/model-versions/{versionId}
- bare numeric ids (treated as model ids)

The hosts ``civitai.com``, ``civitai.red`` and ``civitai.green`` are all
accepted (``www.`` prefixes are normalized away).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

SUPPORTED_HOSTS = frozenset({"civitai.com", "civitai.red", "civitai.green"})
DEFAULT_HOST = "civitai.com"


@dataclass(frozen=True)
class CivitaiLink:
    """A parsed Civitai reference extracted from user input."""

    model_id: Optional[int] = None
    version_id: Optional[int] = None
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return self.model_id is None and self.version_id is None

    def page_url(self) -> str:
        """Canonical civitai.com page URL for this reference."""

        if self.model_id is not None:
            url = f"https://{DEFAULT_HOST}/models/{self.model_id}"
            if self.version_id is not None:
                url += f"?modelVersionId={self.version_id}"
            return url
        if self.version_id is not None:
            return f"https://{DEFAULT_HOST}/model-versions/{self.version_id}"
        return self.raw


def _strip_www(hostname: str) -> str:
    return hostname[4:] if hostname.startswith("www.") else hostname


def is_supported_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    return _strip_www(hostname.lower()) in SUPPORTED_HOSTS


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value.isdigit():
        return None
    return int(value)


def parse_civitai_link(raw: str) -> CivitaiLink:
    """Parse one user-supplied link into a :class:`CivitaiLink`.

    Anything that does not look like a Civitai reference yields a
    ``CivitaiLink`` with both ids unset (``is_empty``); callers should report
    that as an invalid-input error rather than raising.
    """

    if not raw:
        return CivitaiLink(raw="")

    text = raw.strip()
    if not text:
        return CivitaiLink(raw=text)

    # Bare id ("12345"), or a "modelId/versionId" shorthand ("12345/67890").
    if text.isdigit():
        return CivitaiLink(model_id=int(text), raw=text)

    if text.count("/") == 1 and all(p.isdigit() for p in text.split("/") if p):
        left, _, right = text.partition("/")
        return CivitaiLink(model_id=int(left), version_id=int(right), raw=text)

    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        # Tolerate scheme-less input such as "civitai.com/models/123".
        if not scheme and _looks_like_civitai_host(text):
            parsed = urlparse(f"https://{text}")
        else:
            return CivitaiLink(raw=text)

    hostname = (parsed.hostname or "").lower()
    if not is_supported_host(hostname):
        return CivitaiLink(raw=text)

    path = parsed.path or ""

    version_id = _match_segment(path, "model-versions")
    if version_id is not None:
        return CivitaiLink(version_id=version_id, raw=text)

    model_id = _match_segment(path, "models")
    if model_id is not None:
        query = parse_qs(parsed.query or "")
        version_id = _to_int((query.get("modelVersionId") or [None])[0])
        return CivitaiLink(model_id=model_id, version_id=version_id, raw=text)

    return CivitaiLink(raw=text)


def _looks_like_civitai_host(text: str) -> bool:
    hostname = text.split("/", 1)[0].split("?", 1)[0].lower()
    return is_supported_host(hostname)


def _match_segment(path: str, segment: str) -> Optional[int]:
    """Return the numeric id following ``/{segment}/`` at the start of ``path``."""

    prefix = f"/{segment}/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    token = rest.split("/", 1)[0]
    return _to_int(token)


def split_links(text: str) -> list[str]:
    """Split free-form user input into individual link candidates.

    Accepts one link per line, whitespace or comma separated input, and
    ignores surrounding quotes.
    """

    if not text:
        return []
    normalized = text.replace('"', " ").replace("'", " ")
    tokens: list[str] = []
    for chunk in normalized.replace(",", "\n").splitlines():
        for token in chunk.split():
            if token:
                tokens.append(token)
    return tokens
