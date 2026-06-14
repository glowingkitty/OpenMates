# backend/apps/ai/utils/remotion_fences.py
#
# Small parsing helpers for Remotion video-create fences. Keeping this logic out
# of the Celery-backed stream consumer lets unit tests validate the product
# contract without importing worker-only dependencies.

from __future__ import annotations

from pathlib import PurePosixPath


REMOTION_FENCE_LANGUAGE = "remotion"
DEFAULT_REMOTION_FILENAME = "Composition.tsx"
REMOTION_SOURCE_EXTENSIONS = (".tsx", ".jsx", ".ts", ".js")


def normalize_remotion_filename(filename: str | None) -> str:
    raw = (filename or DEFAULT_REMOTION_FILENAME).strip().replace("\\", "/").lstrip("/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raw = DEFAULT_REMOTION_FILENAME
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return DEFAULT_REMOTION_FILENAME
    normalized = path.as_posix()
    if not normalized.endswith(REMOTION_SOURCE_EXTENSIONS):
        normalized = f"{normalized}.tsx"
    return normalized


def _is_remotion_video_fence(language: str | None, filename: str | None = None) -> bool:
    return (language or "").strip().lower() == REMOTION_FENCE_LANGUAGE


def _parse_remotion_fence_metadata(fence_content: str | None) -> dict[str, str] | None:
    raw = (fence_content or "").strip()
    if not raw:
        return None
    if ":" in raw:
        language, filename = raw.split(":", 1)
    else:
        language, filename = raw, DEFAULT_REMOTION_FILENAME
    if not _is_remotion_video_fence(language, filename):
        return None
    return {
        "language": REMOTION_FENCE_LANGUAGE,
        "filename": normalize_remotion_filename(filename),
    }
