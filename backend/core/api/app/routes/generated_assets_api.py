# backend/core/api/app/routes/generated_assets_api.py
#
# REST download endpoint for generated media assets. Files remain encrypted in
# private S3; this endpoint validates a short-lived signed URL, decrypts the
# requested variant in memory, and streams plaintext to API consumers.

import base64
import logging
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.service import S3UploadService
from backend.shared.python_utils.generated_assets import validate_download_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/generated-assets", tags=["Generated Assets"])


def get_directus_service(request: Request) -> DirectusService:
    if not hasattr(request.app.state, "directus_service"):
        raise HTTPException(status_code=500, detail="Directus service unavailable")
    return request.app.state.directus_service


def get_s3_service(request: Request) -> S3UploadService:
    if not hasattr(request.app.state, "s3_service"):
        raise HTTPException(status_code=500, detail="S3 service unavailable")
    return request.app.state.s3_service


def _content_type_for_variant(record_content_type: str, variant: Dict[str, Any]) -> str:
    mime_type = str(variant.get("mime_type") or "").strip()
    if mime_type:
        return mime_type
    file_format = str(variant.get("format") or "").lower()
    if file_format == "webp":
        return "image/webp"
    if file_format == "png":
        return "image/png"
    if file_format in {"jpg", "jpeg"}:
        return "image/jpeg"
    if file_format == "svg":
        return "image/svg+xml"
    if file_format == "mp4":
        return "video/mp4"
    if file_format == "mp3":
        return "audio/mpeg"
    if file_format == "wav":
        return "audio/wav"
    return record_content_type or "application/octet-stream"


@router.get("/{asset_id}/files/{variant}/download")
@limiter.limit("120/minute")
async def download_generated_asset(
    asset_id: str,
    variant: str,
    request: Request,
    token: str = Query(..., description="Short-lived signed generated asset download token"),
    directus_service: DirectusService = Depends(get_directus_service),
    s3_service: S3UploadService = Depends(get_s3_service),
) -> Response:
    """Stream a decrypted generated asset variant from encrypted S3 storage."""
    log_prefix = f"[GeneratedAssetDownload] [asset:{asset_id[:8]}] [variant:{variant}]"
    try:
        payload = validate_download_token(token)
    except ValueError:
        logger.warning("%s Invalid or expired download token", log_prefix)
        raise HTTPException(status_code=403, detail="Invalid or expired download token")

    if payload.get("asset_id") != asset_id or payload.get("variant") != variant:
        raise HTTPException(status_code=403, detail="Download token does not match requested file")

    records = await directus_service.get_items(
        "upload_files",
        params={
            "filter": {"embed_id": {"_eq": asset_id}, "user_id": {"_eq": payload.get("user_id")}},
            "fields": "id,content_type,files_metadata,aes_key,aes_nonce,original_filename",
            "limit": 1,
        },
        no_cache=True,
    )
    if not records or not isinstance(records, list):
        raise HTTPException(status_code=404, detail="Generated asset not found")

    record = records[0]
    files_metadata: Dict[str, Any] = record.get("files_metadata") or {}
    variant_meta: Optional[Dict[str, Any]] = files_metadata.get(variant)
    if not variant_meta or not isinstance(variant_meta, dict) or not variant_meta.get("s3_key"):
        raise HTTPException(status_code=404, detail="Generated asset variant not found")

    try:
        encrypted_bytes = await s3_service.get_file(
            bucket_name=get_bucket_name("chatfiles", s3_service.environment),
            object_key=variant_meta["s3_key"],
        )
        if not encrypted_bytes:
            raise HTTPException(status_code=404, detail="Generated asset file missing")
        aes_key = base64.b64decode(record.get("aes_key") or "")
        aes_nonce = base64.b64decode(record.get("aes_nonce") or "")
        plaintext = AESGCM(aes_key).decrypt(aes_nonce, encrypted_bytes, None)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("%s Failed to decrypt generated asset: %s", log_prefix, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to decrypt generated asset")

    media_type = _content_type_for_variant(str(record.get("content_type") or ""), variant_meta)
    filename = str(record.get("original_filename") or f"openmates_generated_{asset_id}")
    return Response(
        content=plaintext,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
