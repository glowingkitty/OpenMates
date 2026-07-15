# backend/apps/models3d/storage.py
#
# Dependency-free metadata helpers for models3d encrypted artifacts. Keeping
# these pure lets storage contracts run without loading Celery or web services.

from __future__ import annotations

from typing import Any

from backend.shared.python_utils.generated_assets import CHUNKED_MODEL_ENCRYPTION


def build_master_variant_metadata(s3_key: str, size_bytes: int) -> dict[str, Any]:
    """Return the durable, versioned metadata for an encrypted GLB master."""
    return {
        "s3_key": s3_key,
        "size_bytes": size_bytes,
        "format": "glb",
        "mime_type": "model/gltf-binary",
        "encryption": CHUNKED_MODEL_ENCRYPTION,
    }


def build_poster_variant_metadata(s3_key: str, size_bytes: int, mime_type: str) -> dict[str, Any]:
    """Return metadata for the bounded, provider-generated poster image."""
    file_format = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime_type)
    if not file_format:
        raise ValueError("Unsupported model poster MIME type")
    return {
        "s3_key": s3_key,
        "size_bytes": size_bytes,
        "format": file_format,
        "mime_type": mime_type,
    }


def build_preview_variant_metadata(
    s3_key: str,
    size_bytes: int,
    nonce_b64: str,
    *,
    optimized: bool = True,
) -> dict[str, Any]:
    """Return metadata for the bounded, separately encrypted interactive GLB."""
    if not nonce_b64:
        raise ValueError("Interactive model preview requires an encryption nonce")
    metadata: dict[str, Any] = {
        "s3_key": s3_key,
        "size_bytes": size_bytes,
        "format": "glb",
        "mime_type": "model/gltf-binary",
        "aes_nonce": nonce_b64,
        "optimized": optimized,
    }
    if optimized:
        metadata["compression"] = {"geometry": "meshopt", "textures": "webp"}
    else:
        metadata["fallback_reason"] = "preview_optimization_failed"
    return metadata
