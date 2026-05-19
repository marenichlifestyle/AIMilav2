from __future__ import annotations

import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
VOICE_EXTENSIONS = (".oga", ".ogg", ".opus", ".mp3", ".m4a", ".wav")


def _extract_mime(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in [
        "file_mime",
        "fileMime",
        "mime",
        "mimetype",
        "content_type",
        "contentType",
        "mimeType",
    ]:
        value = payload.get(key)
        if value:
            return str(value).strip().lower()
    return ""


def detect_file_type(file_link: str | None, payload: dict[str, Any] | None) -> str:
    link = (file_link or "").lower()
    mime = _extract_mime(payload)

    if any(ext in link for ext in VOICE_EXTENSIONS) or "audio" in mime or "voice" in mime:
        return "voice"
    if any(ext in link for ext in IMAGE_EXTENSIONS) or "image" in mime:
        return "image"
    if file_link:
        return "other_file"
    return "text"


async def download_media(url: str, max_bytes: int, timeout: float = 20.0) -> tuple[bytes | None, str | None]:
    if not url:
        return None, None

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                content_type = response.headers.get("content-type")
                total = 0
                chunks: list[bytes] = []
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        logger.error("Media file is too large: %s bytes (limit %s)", total, max_bytes)
                        return None, content_type
                    chunks.append(chunk)

                return b"".join(chunks), content_type
    except Exception as exc:
        logger.error("Failed to download media %s: %s", url, exc)
        return None, None
