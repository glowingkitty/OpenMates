# backend/core/api/app/routes/pdf_pages.py
#
# First-party endpoint that prepares one page image of an uploaded PDF on demand (PDF processing v2,
# assertion pdf-processing.view.on-demand-render).
#
# Only the page-1 preview is rendered while a PDF is processed. When the web fullscreen scrolls to
# another page it calls this route; the page is rendered from the encrypted original, judged by the
# Jev image decision (fail closed), encrypted with the embed's output key, stored, and its S3 key is
# remembered in the cached embed so later requests reuse it. The response carries only the S3 key
# and a status: the client downloads the ciphertext and decrypts it with the embed key it already
# holds, so no plaintext page leaves the server.
#
# API surface classification: first-party client surface only (session auth). The embed is client
# encrypted data, so the route is not part of the public developer API.
# Auth: current session user must own the cached embed. Rate limit: 120/minute per user.
# Credits: none (the page-render cost is part of the PDF's 2 credits per file).

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel
from toon_format import decode as toon_decode
from toon_format import encode as toon_encode

from backend.apps.pdf.services.page_render_service import get_page_render
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.s3.config import get_bucket_name
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/embeds", tags=["Embeds"])

class PdfPageRenderResponse(BaseModel):
    page_number: int
    status: Literal["ok", "withheld", "rejected", "unavailable"]
    s3_key: str | None = None


def _cache(request: Request) -> CacheService:
    return request.app.state.cache_service


def _encryption(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def _s3(request: Request) -> S3UploadService:
    return request.app.state.s3_service


def _secrets(request: Request) -> SecretsManager | None:
    return getattr(request.app.state, "secrets_manager", None)


def _bucket() -> str:
    return get_bucket_name("chatfiles", os.getenv("SERVER_ENVIRONMENT", "development"))


async def _load_owned_pdf_embed(
    embed_id: str, current_user: User, cache_service: CacheService, encryption_service: EncryptionService
) -> tuple[dict[str, Any], dict[str, Any], str]:
    embed = await cache_service.get_embed_from_cache(embed_id)
    if not embed:
        raise HTTPException(status_code=404, detail="PDF is no longer available for page rendering")
    if embed.get("user_id") != current_user.id:
        raise HTTPException(status_code=404, detail="PDF is no longer available for page rendering")
    vault_key_id = embed.get("vault_key_id") or current_user.vault_key_id
    encrypted = embed.get("encrypted_content")
    if not vault_key_id or not isinstance(encrypted, str) or not encrypted:
        raise HTTPException(status_code=422, detail="PDF embed has no readable content")
    plaintext = await encryption_service.decrypt_with_user_key(encrypted, vault_key_id)
    content = toon_decode(plaintext) if plaintext else None
    if not isinstance(content, dict) or content.get("type") != "pdf":
        raise HTTPException(status_code=422, detail="Target embed is not a PDF")
    if content.get("status") == "error" or not content.get("vault_wrapped_aes_key"):
        raise HTTPException(status_code=409, detail="PDF processing has not finished")
    return embed, content, vault_key_id


@router.post("/{embed_id}/pdf-pages/{page_number}/render", response_model=PdfPageRenderResponse)
@limiter.limit("120/minute")
async def render_pdf_page(
    request: Request,
    embed_id: str,
    page_number: int = Path(..., ge=1, le=100000),
    current_user: User = Depends(get_current_user),
) -> PdfPageRenderResponse:
    cache_service = _cache(request)
    encryption_service = _encryption(request)
    s3_service = _s3(request)
    secrets_manager = _secrets(request)
    if secrets_manager is None:
        raise HTTPException(status_code=503, detail="Page safety check is unavailable")

    embed, content, vault_key_id = await _load_owned_pdf_embed(
        embed_id, current_user, cache_service, encryption_service
    )
    if page_number > int(content.get("page_count") or 0):
        raise HTTPException(status_code=404, detail="Page is outside the document")

    existing = (content.get("screenshot_s3_keys") or {}).get(str(page_number))
    if existing:
        return PdfPageRenderResponse(page_number=page_number, status="ok", s3_key=existing)

    async def unwrap(wrapped: str) -> bytes:
        aes_key_b64 = await encryption_service.decrypt_with_user_key(wrapped, vault_key_id)
        if not aes_key_b64:
            raise HTTPException(status_code=500, detail="Could not unwrap the PDF key")
        return base64.b64decode(aes_key_b64)

    async def download(s3_key: str) -> bytes:
        data = await s3_service.get_file(bucket_name=_bucket(), object_key=s3_key)
        if data is None:
            raise HTTPException(status_code=404, detail="PDF artefact not found")
        return data

    async def upload(s3_key: str, data: bytes) -> None:
        await s3_service.upload_file(
            bucket_key="chatfiles", file_key=s3_key, content=data, content_type="application/octet-stream"
        )

    async def record(page: int, s3_key: str) -> None:
        keys = dict(content.get("screenshot_s3_keys") or {})
        keys[str(page)] = s3_key
        content["screenshot_s3_keys"] = keys
        ciphertext, _version = await encryption_service.encrypt_with_user_key(toon_encode(content), vault_key_id)
        if not ciphertext:
            raise HTTPException(status_code=500, detail="Could not store the rendered page")
        embed["encrypted_content"] = ciphertext
        client = await cache_service.client
        if client:
            await client.set(cache_service._get_embed_cache_key(embed_id), json.dumps(embed), keepttl=True)

    render = await get_page_render(
        embed_content=content,
        page_number=page_number,
        unwrap_key=unwrap,
        download=download,
        upload=upload,
        record_key=record,
        secrets_manager=secrets_manager,
        user_id=current_user.id,
        embed_id=embed_id,
        log_prefix=f"[pdf.page-render] [embed:{embed_id[:8]}]",
    )
    return PdfPageRenderResponse(page_number=page_number, status=render.status, s3_key=render.s3_key)
