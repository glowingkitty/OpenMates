# backend/apps/uploads/routes/upload_route.py
#
# POST /v1/upload/file — the core upload endpoint.
#
# Full pipeline for image uploads (Phase 1):
#   1. Authenticate user via refresh token cookie (forwarded to core API)
#   2. Validate file size (100 MB limit) and MIME type whitelist
#   3. Compute SHA-256 hash → check deduplication via core API
#   4. ClamAV malware scan (blocks until result; 422 if threat detected)
#   5. [Images] SightEngine AI-generated detection (non-blocking; stores score as metadata)
#   6. [Images] Generate WEBP preview via Pillow
#   7. Generate random AES-256 key, encrypt file + preview with AES-256-GCM
#   8. Vault-wrap the AES key via core API internal endpoint
#   9. Upload encrypted bytes to S3 chatfiles bucket
#   10. Store upload record via core API internal endpoint
#   11. Return JSON with embed_id, S3 keys, AES key, vault_wrapped_aes_key
#
# Architecture (security isolation):
#   - This service has NO access to Directus, the main Vault, or any user data.
#   - All Directus and Vault operations are proxied through the core API's
#     internal endpoints (/internal/uploads/*), secured by INTERNAL_API_SHARED_TOKEN.
#   - The local Vault on this VM only stores S3 and SightEngine credentials.
#   - If this VM is compromised, the attacker cannot decrypt any existing files,
#     access user data, or reach the main Vault.
#
# Concurrent uploads: FastAPI's async event loop naturally handles multiple
# simultaneous requests. Blocking operations (ClamAV, Pillow) run in thread
# pools via asyncio.to_thread().

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict

import httpx
from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/upload", tags=["Upload"])

# ---------------------------------------------------------------------------
# File type configuration
# ---------------------------------------------------------------------------

# Allowed MIME types for Phase 1 (images only)
ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    "image/bmp",
    "image/tiff",
}

# Maximum upload size: 100 MB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

# ---------------------------------------------------------------------------
# Response models (Pydantic — auto-discovered by OpenAPI docs)
# ---------------------------------------------------------------------------


class FileVariantMetadata(BaseModel):
    """Metadata for one stored file variant (original or preview)."""
    s3_key: str = Field(..., description="S3 object key for this variant")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    size_bytes: int = Field(..., description="Encrypted file size in bytes")
    format: str = Field(..., description="Image format (webp)")


class AIDetectionMetadata(BaseModel):
    """SightEngine AI-generated content detection result."""
    ai_generated: float = Field(..., description="Probability (0.0–1.0) that image is AI-generated")
    provider: str = Field(default="sightengine", description="Detection provider name")


class UploadFileResponse(BaseModel):
    """Response returned after a successful file upload."""
    embed_id: str = Field(..., description="UUID used as embed_id in the embed system")
    filename: str = Field(..., description="Original uploaded filename")
    content_type: str = Field(..., description="Detected MIME type")
    content_hash: str = Field(..., description="SHA-256 hash of the original file content")
    files: Dict[str, FileVariantMetadata] = Field(..., description="Stored file variants (original, preview)")
    s3_base_url: str = Field(..., description="S3 base URL for constructing full file URLs")
    aes_key: str = Field(..., description="Base64 AES-256 key — include in embed TOON content for client-side decryption")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce shared across all encrypted variants")
    vault_wrapped_aes_key: str = Field(..., description="Vault-wrapped AES key — include in embed TOON content for server-side skill access")
    malware_scan: str = Field(..., description="ClamAV result: 'clean'")
    ai_detection: Optional[AIDetectionMetadata] = Field(None, description="AI-generated detection result (images only)")
    deduplicated: bool = Field(default=False, description="True if this file was already uploaded by this user")


# ---------------------------------------------------------------------------
# Auth dependency — reuse cookie-based auth via core API internal endpoint
# ---------------------------------------------------------------------------

async def get_authenticated_user(
    request: Request,
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token"),
) -> Dict[str, Any]:
    """
    Authenticate the uploading user by forwarding the refresh token cookie
    to the core API's internal auth endpoint.

    The uploads service calls the core API to validate the token and retrieve
    user data (user_id, vault_key_id). This avoids duplicating auth logic and
    ensures single-source-of-truth for user sessions.

    Returns:
        Dict containing user_id and vault_key_id.

    Raises:
        HTTPException(401): If token is missing or invalid.
    """
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated: Missing token")

    core_api_url = os.environ.get("CORE_API_URL", "http://api:8000")
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{core_api_url}/internal/validate-token",
                headers={
                    "X-Internal-Service-Token": internal_token,
                    "X-Refresh-Token": refresh_token,
                },
            )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        else:
            logger.error(f"[Upload Auth] Core API returned {resp.status_code}: {resp.text[:200]}")
            raise HTTPException(status_code=502, detail="Authentication service unavailable")
    except httpx.TimeoutException:
        logger.error("[Upload Auth] Core API token validation timed out")
        raise HTTPException(status_code=503, detail="Authentication service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload Auth] Unexpected auth error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Authentication failed")


# ---------------------------------------------------------------------------
# Core API proxy helpers (replace direct Directus/Vault calls)
# ---------------------------------------------------------------------------

async def _check_duplicate_via_api(
    core_api_url: str,
    internal_token: str,
    user_id: str,
    content_hash: str,
) -> Optional[Dict[str, Any]]:
    """
    Check whether this user has already uploaded a file with the same content hash.
    Calls the core API's /internal/uploads/check-duplicate endpoint, which
    queries Directus internally. This service never touches Directus directly.

    Returns the existing upload record or None.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{core_api_url}/internal/uploads/check-duplicate",
                json={"user_id": user_id, "content_hash": content_hash},
                headers={"X-Internal-Service-Token": internal_token},
            )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("duplicate"):
                return data.get("record")
            return None
        logger.warning(f"[Upload Dedup] Core API returned {resp.status_code} for dedup check")
        return None
    except Exception as e:
        logger.warning(f"[Upload Dedup] Dedup check failed (non-fatal): {e}")
        return None


async def _wrap_key_via_api(
    core_api_url: str,
    internal_token: str,
    aes_key_b64: str,
    vault_key_id: str,
) -> str:
    """
    Wrap a plaintext AES key using the user's Vault Transit key via the core API.
    Calls /internal/uploads/wrap-key, which uses the main Vault's Transit engine.
    This service never touches the main Vault directly.

    Returns the vault-wrapped ciphertext string (vault:v1:...).
    Raises RuntimeError on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{core_api_url}/internal/uploads/wrap-key",
                json={"aes_key_b64": aes_key_b64, "vault_key_id": vault_key_id},
                headers={"X-Internal-Service-Token": internal_token},
            )
        if resp.status_code == 200:
            return resp.json()["vault_wrapped_aes_key"]
        logger.error(
            f"[Upload WrapKey] Core API returned {resp.status_code}: {resp.text[:200]}"
        )
        raise RuntimeError(f"Vault key wrapping failed: HTTP {resp.status_code}")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[Upload WrapKey] Key wrapping request failed: {e}", exc_info=True)
        raise RuntimeError(f"Vault key wrapping request failed: {e}") from e


async def _store_record_via_api(
    core_api_url: str,
    internal_token: str,
    record: Dict[str, Any],
) -> None:
    """
    Store an upload record via the core API's /internal/uploads/store-record endpoint.
    The core API writes to Directus internally. This service never touches Directus directly.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{core_api_url}/internal/uploads/store-record",
                json=record,
                headers={"X-Internal-Service-Token": internal_token},
            )
        if resp.status_code not in (200, 201):
            logger.warning(
                f"[Upload Store] Failed to store upload record: {resp.status_code} {resp.text[:200]}"
            )
    except Exception as e:
        logger.warning(f"[Upload Store] Failed to store upload record (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Main upload endpoint
# ---------------------------------------------------------------------------

@router.post("/file", response_model=UploadFileResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_authenticated_user),
) -> UploadFileResponse:
    """
    Upload a file (Phase 1: images only).

    Performs malware scanning, AI detection (images), preview generation,
    AES-256-GCM encryption, Vault key wrapping (via core API), and S3 upload.
    Returns all data the client needs to construct the embed TOON content.

    **Security model:**
    - Files are scanned in plaintext before encryption
    - Encrypted with a random AES-256 key (per file)
    - The AES key is Vault-wrapped via the core API's internal endpoint
      (this service never touches the main Vault) AND returned to the
      client (for local rendering) — both stored inside client-encrypted
      embed content at rest (zero-knowledge in Directus)
    - Plaintext file bytes exist only transiently in this process during processing

    **Rate limit:** 20 uploads per minute per user.
    """
    user_id: str = user["user_id"]
    vault_key_id: str = user["vault_key_id"]
    log_prefix = f"[Upload] [user:{user_id[:8]}...]"

    # Core API connection details (used for all internal API calls)
    core_api_url = os.environ.get("CORE_API_URL", "http://api:8000")
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")

    # --- 1. Read file bytes ---
    file_bytes = await file.read()
    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"

    logger.info(
        f"{log_prefix} Received upload: {filename!r} "
        f"({len(file_bytes)} bytes, {content_type})"
    )

    # --- 2. Size validation ---
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )

    # --- 3. MIME type validation (whitelist) ---
    # Also verify using python-magic for safety (don't trust Content-Type header alone)
    try:
        import magic  # type: ignore[import]
        detected_mime = magic.from_buffer(file_bytes, mime=True)
    except ImportError:
        logger.warning("[Upload] python-magic not available, using Content-Type header only")
        detected_mime = content_type
    except Exception as e:
        logger.warning(f"[Upload] MIME detection failed: {e}, using Content-Type header")
        detected_mime = content_type

    is_image = detected_mime in ALLOWED_IMAGE_MIMES or content_type in ALLOWED_IMAGE_MIMES

    if not is_image:
        logger.warning(
            f"{log_prefix} Rejected: unsupported MIME type detected={detected_mime!r}, "
            f"declared={content_type!r}"
        )
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {detected_mime}. Supported: images (JPEG, PNG, WEBP, GIF, HEIC)",
        )

    # Use the detected MIME type (more reliable than Content-Type header)
    content_type = detected_mime

    # --- 4. SHA-256 hash for deduplication ---
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.debug(f"{log_prefix} Content hash: {content_hash}")

    # --- 5. Deduplication check (via core API → Directus) ---
    existing_record = await _check_duplicate_via_api(
        core_api_url, internal_token, user_id, content_hash
    )
    if existing_record:
        logger.info(
            f"{log_prefix} Duplicate detected (content_hash={content_hash[:16]}...) — "
            f"returning existing embed_id: {existing_record.get('embed_id')}"
        )
        # Reconstruct response from stored record
        files_data = existing_record.get("files_metadata", {})
        return UploadFileResponse(
            embed_id=existing_record["embed_id"],
            filename=existing_record.get("original_filename", filename),
            content_type=existing_record.get("content_type", content_type),
            content_hash=content_hash,
            files={
                k: FileVariantMetadata(**v)
                for k, v in files_data.items()
            },
            s3_base_url=existing_record["s3_base_url"],
            aes_key=existing_record["aes_key"],
            aes_nonce=existing_record["aes_nonce"],
            vault_wrapped_aes_key=existing_record["vault_wrapped_aes_key"],
            malware_scan="clean",
            ai_detection=(
                AIDetectionMetadata(**existing_record["ai_detection"])
                if existing_record.get("ai_detection")
                else None
            ),
            deduplicated=True,
        )

    # --- 6. ClamAV malware scan ---
    malware_service = request.app.state.malware_scanner
    try:
        scan_result = await malware_service.scan(file_bytes)
    except RuntimeError as e:
        logger.error(f"{log_prefix} ClamAV scan failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Malware scanning service unavailable")

    if not scan_result.is_clean:
        logger.warning(
            f"{log_prefix} MALWARE DETECTED in {filename!r}: {scan_result.threat_name}"
        )
        raise HTTPException(
            status_code=422,
            detail=f"File rejected: threat detected ({scan_result.threat_name})",
        )
    logger.info(f"{log_prefix} ClamAV scan: clean")

    # --- 7. [Images] SightEngine AI detection (non-blocking — never rejects upload) ---
    ai_detection_result = None
    if is_image:
        sightengine = request.app.state.sightengine
        ai_result = await sightengine.check_image(file_bytes, filename=filename)
        if ai_result is not None:
            ai_detection_result = AIDetectionMetadata(
                ai_generated=ai_result.ai_generated,
                provider=ai_result.provider,
            )
            logger.info(
                f"{log_prefix} AI detection: {ai_result.ai_generated:.3f} "
                f"({'likely AI' if ai_result.ai_generated > 0.7 else 'likely real'})"
            )

    # --- 8. [Images] Preview generation ---
    preview_service = request.app.state.preview_generator
    preview_result = await preview_service.generate_image_preview(file_bytes)
    logger.info(
        f"{log_prefix} Preview generated: "
        f"original {preview_result.original_width}x{preview_result.original_height}, "
        f"full {preview_result.full_width}x{preview_result.full_height}, "
        f"preview {preview_result.preview_width}x{preview_result.preview_height}"
    )

    # --- 9. AES-256-GCM encryption ---
    # All three variants share the same AES key and nonce, matching generate_task.py.
    crypto_service = request.app.state.file_encryption

    # Encrypt original (re-encoded bytes)
    encrypted_original, aes_key_b64, nonce_b64 = crypto_service.encrypt_bytes(
        preview_result.original_bytes
    )
    # Encrypt full and preview using the SAME key+nonce
    encrypted_full = crypto_service.encrypt_bytes_with_key(
        preview_result.full_webp_bytes, aes_key_b64, nonce_b64
    )
    encrypted_preview = crypto_service.encrypt_bytes_with_key(
        preview_result.preview_webp_bytes, aes_key_b64, nonce_b64
    )

    # --- 10. Vault-wrap the AES key via core API (never touches main Vault directly) ---
    try:
        vault_wrapped_aes_key = await _wrap_key_via_api(
            core_api_url, internal_token, aes_key_b64, vault_key_id
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} Vault key wrap failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Encryption service unavailable")

    # --- 11. S3 upload — three variants (original, full, preview) ---
    embed_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_prefix = f"{user_id}/{content_hash}"

    s3_service = request.app.state.s3
    original_s3_key = f"{s3_prefix}/{timestamp}_original.bin"
    full_s3_key = f"{s3_prefix}/{timestamp}_full.bin"
    preview_s3_key = f"{s3_prefix}/{timestamp}_preview.bin"

    try:
        await s3_service.upload_file(
            s3_key=original_s3_key,
            content=encrypted_original,
        )
        await s3_service.upload_file(
            s3_key=full_s3_key,
            content=encrypted_full,
        )
        await s3_service.upload_file(
            s3_key=preview_s3_key,
            content=encrypted_preview,
        )
        logger.info(
            f"{log_prefix} Uploaded to S3: original={original_s3_key}, "
            f"full={full_s3_key}, preview={preview_s3_key}"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} S3 upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="File storage service unavailable")

    s3_base_url = s3_service.get_base_url()

    # --- 12. Build files metadata dict (matches generate_task.py structure) ---
    files_metadata = {
        "original": FileVariantMetadata(
            s3_key=original_s3_key,
            width=preview_result.original_width,
            height=preview_result.original_height,
            size_bytes=len(encrypted_original),
            format="webp",
        ),
        "full": FileVariantMetadata(
            s3_key=full_s3_key,
            width=preview_result.full_width,
            height=preview_result.full_height,
            size_bytes=len(encrypted_full),
            format="webp",
        ),
        "preview": FileVariantMetadata(
            s3_key=preview_s3_key,
            width=preview_result.preview_width,
            height=preview_result.preview_height,
            size_bytes=len(encrypted_preview),
            format="webp",
        ),
    }

    # --- 13. Store upload record via core API (never touches Directus directly) ---
    ai_detection_dict = ai_detection_result.model_dump() if ai_detection_result else None
    upload_record = {
        "embed_id": embed_id,
        "user_id": user_id,
        "content_hash": content_hash,
        "original_filename": filename,
        "content_type": content_type,
        "file_size_bytes": len(file_bytes),
        "s3_base_url": s3_base_url,
        "files_metadata": {k: v.model_dump() for k, v in files_metadata.items()},
        "aes_key": aes_key_b64,
        "aes_nonce": nonce_b64,
        "vault_wrapped_aes_key": vault_wrapped_aes_key,
        "malware_scan": "clean",
        "ai_detection": ai_detection_dict,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
    await _store_record_via_api(core_api_url, internal_token, upload_record)

    logger.info(
        f"{log_prefix} Upload complete — embed_id={embed_id}, "
        f"hash={content_hash[:16]}..., ai_generated="
        f"{ai_detection_result.ai_generated if ai_detection_result else 'n/a'}"
    )

    return UploadFileResponse(
        embed_id=embed_id,
        filename=filename,
        content_type=content_type,
        content_hash=content_hash,
        files=files_metadata,
        s3_base_url=s3_base_url,
        aes_key=aes_key_b64,
        aes_nonce=nonce_b64,
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        malware_scan="clean",
        ai_detection=ai_detection_result,
        deduplicated=False,
    )
