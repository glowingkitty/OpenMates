# backend/upload/routes/upload_route.py
#
# POST /v1/upload/file — the core upload endpoint.
#
# Full pipeline for supported file types:
#
# Images pipeline:
#   1. Authenticate user via refresh token cookie (forwarded to core API)
#   2. Validate file size (100 MB limit) and MIME type whitelist
#   3. Compute SHA-256 hash → check deduplication via core API
#   4. ClamAV malware scan (blocks until result; 422 if threat detected)
#   5. SightEngine AI-generated detection (non-blocking; stores score as metadata)
#   6. Generate WEBP preview via Pillow
#   7. Generate random AES-256 key, encrypt file + preview with AES-256-GCM
#   8. Vault-wrap the AES key via core API internal endpoint
#   9. Upload encrypted bytes to S3 chatfiles bucket
#   10. Store upload record via core API internal endpoint
#   11. Return JSON with embed_id, S3 keys, AES key, vault_wrapped_aes_key
#
# PDF pipeline:
#   1. Authenticate user
#   2. Validate file size and MIME type
#   3. Compute SHA-256 hash → check deduplication
#   4. ClamAV malware scan
#   5. Extract page count via pymupdf (quick, no rendering)
#   6. Charge user 3 credits/page upfront via core API billing
#   7. Encrypt PDF bytes with AES-256-GCM
#   8. Vault-wrap the AES key
#   9. Upload encrypted PDF to S3
#   10. Store upload record
#   11. Trigger background OCR processing via POST /internal/pdf/process (fire-and-forget)
#   12. Return JSON with embed_id, page_count, S3 key, AES key
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
# simultaneous requests. Blocking operations (ClamAV, Pillow, pymupdf) run in
# thread pools via asyncio.to_thread().

import hashlib
import logging
import os
import time
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

# Allowed MIME types (images + PDFs)
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

ALLOWED_PDF_MIMES = {
    "application/pdf",
}

ALLOWED_MIMES = ALLOWED_IMAGE_MIMES | ALLOWED_PDF_MIMES

# Maximum PDF page count (1000 pages max)
MAX_PDF_PAGES = 1000

# Credits charged per PDF page (3 credits/page)
PDF_CREDITS_PER_PAGE = 3

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
    # PDF-specific fields (only set when content_type is application/pdf)
    page_count: Optional[int] = Field(None, description="Number of pages in the PDF (set for PDFs only)")


# ---------------------------------------------------------------------------
# Target environment resolution — picks core API credentials based on which
# domain the request arrived on, as signalled by Caddy via X-Target-Env.
#
# Caddy sets X-Target-Env to "prod" or "dev" based on the incoming domain:
#   upload.openmates.org     → X-Target-Env: prod → PROD_CORE_API_URL + PROD_INTERNAL_API_SHARED_TOKEN
#   upload.dev.openmates.org → X-Target-Env: dev  → DEV_CORE_API_URL  + DEV_INTERNAL_API_SHARED_TOKEN
#
# This header is injected by Caddy (trusted proxy) and is never forwarded from
# the client — it is stripped by the reverse_proxy block in the Caddyfile and
# replaced with the server-set value, so it cannot be spoofed.
# ---------------------------------------------------------------------------

def _get_core_api_credentials(request: Request) -> tuple[str, str]:
    """
    Return the (core_api_url, internal_token) pair for this request.

    Reads the X-Target-Env header set by Caddy:
      - "prod" → PROD_CORE_API_URL + PROD_INTERNAL_API_SHARED_TOKEN
      - "dev"  → DEV_CORE_API_URL  + DEV_INTERNAL_API_SHARED_TOKEN
      - missing/other → falls back to PROD (safest default)
    """
    target_env = request.headers.get("X-Target-Env", "prod").lower()

    if target_env == "dev":
        core_api_url = os.environ.get("DEV_CORE_API_URL", "")
        internal_token = os.environ.get("DEV_INTERNAL_API_SHARED_TOKEN", "")
        if not core_api_url:
            logger.error("[Upload] X-Target-Env=dev but DEV_CORE_API_URL is not set")
            raise HTTPException(status_code=503, detail="Dev core API not configured")
    else:
        core_api_url = os.environ.get("PROD_CORE_API_URL", "http://api:8000")
        internal_token = os.environ.get("PROD_INTERNAL_API_SHARED_TOKEN", "")

    return core_api_url, internal_token


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

    core_api_url, internal_token = _get_core_api_credentials(request)

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

    # Core API connection details — selected based on X-Target-Env header set by Caddy
    core_api_url, internal_token = _get_core_api_credentials(request)

    # Determine which S3 bucket to use (dev vs prod) based on the same header.
    # This ensures the s3_base_url in the response points to the correct bucket
    # for the requesting environment (prevents CORS failures on dev).
    target_env = request.headers.get("X-Target-Env", "prod").lower()

    upload_start = time.monotonic()

    # --- 1. Read file bytes ---
    file_bytes = await file.read()
    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"

    logger.info(
        f"{log_prefix} ── Upload started ──────────────────────────────────"
    )
    logger.info(
        f"{log_prefix} [1/13] File received: {filename!r} "
        f"({len(file_bytes) / 1024:.1f} KB, declared type: {content_type})"
    )

    # --- 2. Size validation ---
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        logger.warning(
            f"{log_prefix} [2/13] REJECTED — file too large: "
            f"{len(file_bytes) / (1024*1024):.1f} MB > {MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit"
        )
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )
    logger.info(
        f"{log_prefix} [2/13] Size check: OK ({len(file_bytes) / 1024:.1f} KB ≤ 100 MB limit)"
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
    is_pdf = detected_mime in ALLOWED_PDF_MIMES or content_type in ALLOWED_PDF_MIMES

    if not is_image and not is_pdf:
        logger.warning(
            f"{log_prefix} [3/13] REJECTED — unsupported MIME type "
            f"detected={detected_mime!r} declared={content_type!r}"
        )
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type: {detected_mime}. "
                "Supported: images (JPEG, PNG, WEBP, GIF, HEIC) and PDFs."
            ),
        )

    # Use the detected MIME type (more reliable than Content-Type header)
    content_type = detected_mime
    file_kind = "image" if is_image else "PDF"
    logger.info(
        f"{log_prefix} [3/13] MIME check: OK — detected {detected_mime!r} ({file_kind})"
    )

    # --- 4. SHA-256 hash for deduplication ---
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    logger.info(f"{log_prefix} [4/13] SHA-256 hash: {content_hash[:16]}...{content_hash[-8:]}")

    # --- 5. Deduplication check (via core API → Directus) ---
    logger.info(f"{log_prefix} [5/13] Checking for duplicate (content hash lookup)...")
    existing_record = await _check_duplicate_via_api(
        core_api_url, internal_token, user_id, content_hash
    )
    if existing_record:
        # Validate that the referenced S3 objects actually exist before returning
        # the cached record. Records can be stale if a previous upload failed
        # mid-way (e.g. bucket misconfiguration) — silently falling back to a
        # fresh upload is safer than returning a broken embed that cannot decrypt.
        files_data = existing_record.get("files_metadata", {})
        sample_key = next(
            (v.get("s3_key") for v in files_data.values() if v.get("s3_key")),
            None,
        )
        s3_service = request.app.state.s3
        logger.info(f"{log_prefix} [5/13] Duplicate found — verifying S3 object exists: {sample_key!r}")
        s3_ok = await s3_service.check_file_exists(sample_key, target_env=target_env) if sample_key else False

        if not s3_ok:
            logger.warning(
                f"{log_prefix} [5/13] Duplicate record found but S3 object MISSING "
                f"(key={sample_key!r}) — discarding stale record, proceeding with fresh upload"
            )
            existing_record = None  # Fall through to fresh upload below
        else:
            elapsed = time.monotonic() - upload_start
            logger.info(
                f"{log_prefix} [5/13] Duplicate confirmed — S3 object exists. "
                f"Returning cached embed_id={existing_record.get('embed_id')} "
                f"({elapsed*1000:.0f} ms total)"
            )
            # Reconstruct response from stored record.
            # Always recompute s3_base_url from the current target_env rather
            # than trusting the stored value — old records may have the wrong
            # bucket URL due to the shared-service bucket bug.
            s3_service_for_dedup = request.app.state.s3
            dedup_s3_base_url = s3_service_for_dedup.get_base_url(target_env=target_env)
            return UploadFileResponse(
                embed_id=existing_record["embed_id"],
                filename=existing_record.get("original_filename", filename),
                content_type=existing_record.get("content_type", content_type),
                content_hash=content_hash,
                files={
                    k: FileVariantMetadata(**v)
                    for k, v in files_data.items()
                },
                s3_base_url=dedup_s3_base_url,
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
                page_count=existing_record.get("page_count"),
            )
    else:
        logger.info(f"{log_prefix} [5/13] No duplicate found — proceeding with fresh upload")

    # --- 6. ClamAV malware scan ---
    logger.info(f"{log_prefix} [6/13] Starting ClamAV malware scan ({len(file_bytes) / 1024:.1f} KB)...")
    scan_start = time.monotonic()
    malware_service = request.app.state.malware_scanner
    try:
        scan_result = await malware_service.scan(file_bytes)
    except RuntimeError as e:
        logger.error(f"{log_prefix} [6/13] ClamAV scan FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Malware scanning service unavailable")

    scan_elapsed = (time.monotonic() - scan_start) * 1000
    if not scan_result.is_clean:
        logger.warning(
            f"{log_prefix} [6/13] MALWARE DETECTED in {filename!r}: "
            f"{scan_result.threat_name} (scanned in {scan_elapsed:.0f} ms)"
        )
        raise HTTPException(
            status_code=422,
            detail=f"File rejected: threat detected ({scan_result.threat_name})",
        )
    logger.info(f"{log_prefix} [6/13] ClamAV scan: CLEAN ✓ ({scan_elapsed:.0f} ms)")

    # ===========================================================================
    # PDF BRANCH: separate processing pipeline for PDFs
    # ===========================================================================
    if is_pdf:
        return await _handle_pdf_upload(
            request=request,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            content_hash=content_hash,
            user_id=user_id,
            vault_key_id=vault_key_id,
            core_api_url=core_api_url,
            internal_token=internal_token,
            log_prefix=log_prefix,
            target_env=target_env,
        )

    # ===========================================================================
    # IMAGE BRANCH: original pipeline continues below
    # ===========================================================================

    # --- 7. [Images] SightEngine AI detection (non-blocking — never rejects upload) ---
    ai_detection_result = None
    if is_image:
        sightengine = request.app.state.sightengine
        if sightengine.is_enabled:
            logger.info(f"{log_prefix} [7/13] AI detection: running SightEngine genai check...")
            ai_start = time.monotonic()
            ai_result = await sightengine.check_image(file_bytes, filename=filename)
            ai_elapsed = (time.monotonic() - ai_start) * 1000
            if ai_result is not None:
                ai_detection_result = AIDetectionMetadata(
                    ai_generated=ai_result.ai_generated,
                    provider=ai_result.provider,
                )
                label = "LIKELY AI-GENERATED" if ai_result.ai_generated > 0.7 else (
                    "possibly AI" if ai_result.ai_generated > 0.4 else "likely real/photo"
                )
                logger.info(
                    f"{log_prefix} [7/13] AI detection: score={ai_result.ai_generated:.3f} "
                    f"→ {label} ({ai_elapsed:.0f} ms)"
                )
            else:
                logger.warning(
                    f"{log_prefix} [7/13] AI detection: SightEngine returned None "
                    f"(non-fatal, upload continues without score) ({ai_elapsed:.0f} ms)"
                )
        else:
            logger.info(
                f"{log_prefix} [7/13] AI detection: SKIPPED "
                f"(SightEngine not configured — set SECRET__SIGHTENGINE__* to enable)"
            )
    else:
        logger.info(f"{log_prefix} [7/13] AI detection: SKIPPED (PDFs are not checked)")

    # --- 8. [Images] Preview generation ---
    logger.info(f"{log_prefix} [8/13] Generating WEBP previews (original + full + preview variants)...")
    preview_start = time.monotonic()
    preview_service = request.app.state.preview_generator
    preview_result = await preview_service.generate_image_preview(file_bytes)
    preview_elapsed = (time.monotonic() - preview_start) * 1000
    logger.info(
        f"{log_prefix} [8/13] Previews generated ({preview_elapsed:.0f} ms): "
        f"original={preview_result.original_width}x{preview_result.original_height} "
        f"({len(preview_result.original_bytes)/1024:.1f} KB), "
        f"full={preview_result.full_width}x{preview_result.full_height} "
        f"({len(preview_result.full_webp_bytes)/1024:.1f} KB), "
        f"preview={preview_result.preview_width}x{preview_result.preview_height} "
        f"({len(preview_result.preview_webp_bytes)/1024:.1f} KB)"
    )

    # --- 9. AES-256-GCM encryption ---
    # All three variants share the same AES key and nonce, matching generate_task.py.
    logger.info(f"{log_prefix} [9/13] Encrypting 3 variants with AES-256-GCM (random key per file)...")
    encrypt_start = time.monotonic()
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
    encrypt_elapsed = (time.monotonic() - encrypt_start) * 1000
    total_encrypted_kb = (len(encrypted_original) + len(encrypted_full) + len(encrypted_preview)) / 1024
    logger.info(
        f"{log_prefix} [9/13] Encryption done ({encrypt_elapsed:.0f} ms): "
        f"total encrypted size {total_encrypted_kb:.1f} KB across 3 variants"
    )

    # --- 10. Vault-wrap the AES key via core API (never touches main Vault directly) ---
    logger.info(f"{log_prefix} [10/13] Vault-wrapping AES key via core API Transit proxy...")
    vault_start = time.monotonic()
    try:
        vault_wrapped_aes_key = await _wrap_key_via_api(
            core_api_url, internal_token, aes_key_b64, vault_key_id
        )
        vault_elapsed = (time.monotonic() - vault_start) * 1000
        logger.info(
            f"{log_prefix} [10/13] Vault key wrap: OK "
            f"(vault_key_id={vault_key_id[:8]}..., {vault_elapsed:.0f} ms)"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [10/13] Vault key wrap FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Encryption service unavailable")

    # --- 11. S3 upload — three variants (original, full, preview) ---
    embed_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_prefix = f"{user_id}/{content_hash}"

    s3_service = request.app.state.s3
    original_s3_key = f"{s3_prefix}/{timestamp}_original.bin"
    full_s3_key = f"{s3_prefix}/{timestamp}_full.bin"
    preview_s3_key = f"{s3_prefix}/{timestamp}_preview.bin"

    logger.info(
        f"{log_prefix} [11/13] Uploading 3 encrypted variants to S3 "
        f"(embed_id={embed_id})..."
    )
    s3_start = time.monotonic()
    try:
        await s3_service.upload_file(
            s3_key=original_s3_key,
            content=encrypted_original,
            target_env=target_env,
        )
        await s3_service.upload_file(
            s3_key=full_s3_key,
            content=encrypted_full,
            target_env=target_env,
        )
        await s3_service.upload_file(
            s3_key=preview_s3_key,
            content=encrypted_preview,
            target_env=target_env,
        )
        s3_elapsed = (time.monotonic() - s3_start) * 1000
        logger.info(
            f"{log_prefix} [11/13] S3 upload: OK ({s3_elapsed:.0f} ms) — "
            f"keys: original={original_s3_key}, full={full_s3_key}, preview={preview_s3_key}"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [11/13] S3 upload FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="File storage service unavailable")

    s3_base_url = s3_service.get_base_url(target_env=target_env)

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
    logger.info(f"{log_prefix} [13/13] Storing upload record in Directus (via core API)...")
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

    total_elapsed = (time.monotonic() - upload_start) * 1000
    ai_score_str = f"{ai_detection_result.ai_generated:.3f}" if ai_detection_result else "n/a (skipped)"
    logger.info(
        f"{log_prefix} ── Upload COMPLETE ─────────────────────────────────"
    )
    logger.info(
        f"{log_prefix} embed_id={embed_id} | hash={content_hash[:16]}... | "
        f"type={content_type} | size={len(file_bytes)/1024:.1f} KB | "
        f"ai_score={ai_score_str} | total={total_elapsed:.0f} ms"
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


# ---------------------------------------------------------------------------
# PDF upload helper
# ---------------------------------------------------------------------------

async def _handle_pdf_upload(
    request: Any,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    content_hash: str,
    user_id: str,
    vault_key_id: str,
    core_api_url: str,
    internal_token: str,
    log_prefix: str,
    target_env: str = "prod",
) -> UploadFileResponse:
    """
    Handle the PDF-specific upload pipeline:
      1. Extract page count via pymupdf (no rendering)
      2. Charge credits upfront (3 credits/page) via core API billing
      3. Encrypt PDF with AES-256-GCM
      4. Vault-wrap the AES key
      5. Upload to S3
      6. Store upload record
      7. Trigger background OCR processing (fire-and-forget)

    Returns UploadFileResponse with page_count set.
    """
    import asyncio

    pdf_start = time.monotonic()
    logger.info(
        f"{log_prefix} ── PDF Upload started ──────────────────────────────"
    )
    logger.info(
        f"{log_prefix} [PDF-1/7] Extracting page count via pymupdf "
        f"({len(file_bytes)/1024:.1f} KB)..."
    )

    # --- PDF 1. Extract page count via pymupdf ---
    try:
        import fitz  # type: ignore[import]  # pymupdf

        def _count_pages(pdf_bytes: bytes) -> int:
            """Count pages in PDF bytes synchronously (runs in threadpool)."""
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            count = len(doc)
            doc.close()
            return count

        page_count = await asyncio.to_thread(_count_pages, file_bytes)
        logger.info(f"{log_prefix} [PDF-1/7] Page count: {page_count} pages")
    except ImportError:
        logger.error(f"{log_prefix} [PDF-1/7] FAILED — pymupdf (fitz) not installed")
        raise HTTPException(status_code=500, detail="PDF processing library not available")
    except Exception as e:
        logger.error(f"{log_prefix} [PDF-1/7] FAILED — invalid or corrupt PDF: {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Invalid or corrupt PDF file: {e}")

    if page_count > MAX_PDF_PAGES:
        logger.warning(
            f"{log_prefix} [PDF-1/7] REJECTED — {page_count} pages exceeds {MAX_PDF_PAGES} page limit"
        )
        raise HTTPException(
            status_code=422,
            detail=f"PDF too large: {page_count} pages. Maximum allowed is {MAX_PDF_PAGES} pages.",
        )
    if page_count == 0:
        logger.warning(f"{log_prefix} [PDF-1/7] REJECTED — PDF has no pages")
        raise HTTPException(status_code=422, detail="PDF has no pages.")

    # --- PDF 2. Charge credits upfront (3 credits/page) ---
    import hashlib as _hashlib
    credits_to_charge = page_count * PDF_CREDITS_PER_PAGE
    user_id_hash = _hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    logger.info(
        f"{log_prefix} [PDF-2/7] Charging {credits_to_charge} credits "
        f"({page_count} pages × {PDF_CREDITS_PER_PAGE} credits/page)..."
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            charge_resp = await client.post(
                f"{core_api_url}/internal/billing/charge",
                json={
                    "user_id": user_id,
                    "user_id_hash": user_id_hash,
                    "credits": credits_to_charge,
                    "skill_id": "process",
                    "app_id": "pdf",
                    "usage_details": {
                        "page_count": page_count,
                        "credits_per_page": PDF_CREDITS_PER_PAGE,
                        "filename": filename,
                    },
                },
                headers={"X-Internal-Service-Token": internal_token},
            )
        if charge_resp.status_code == 402:
            logger.warning(
                f"{log_prefix} [PDF-2/7] REJECTED — insufficient credits: "
                f"need {credits_to_charge} for {page_count}-page PDF"
            )
            raise HTTPException(status_code=402, detail="Insufficient credits for PDF processing")
        elif charge_resp.status_code not in (200, 201):
            logger.error(
                f"{log_prefix} [PDF-2/7] Billing charge FAILED: "
                f"HTTP {charge_resp.status_code} — {charge_resp.text[:200]}"
            )
            raise HTTPException(status_code=503, detail="Billing service unavailable")
        logger.info(
            f"{log_prefix} [PDF-2/7] Credits charged: OK — "
            f"{credits_to_charge} credits deducted"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} [PDF-2/7] Credit charge request FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Billing service unavailable")

    # --- PDF 3. AES-256-GCM encryption ---
    logger.info(
        f"{log_prefix} [PDF-3/7] Encrypting PDF with AES-256-GCM "
        f"({len(file_bytes)/1024:.1f} KB)..."
    )
    encrypt_start = time.monotonic()
    crypto_service = request.app.state.file_encryption
    encrypted_pdf, aes_key_b64, nonce_b64 = crypto_service.encrypt_bytes(file_bytes)
    encrypt_elapsed = (time.monotonic() - encrypt_start) * 1000
    logger.info(
        f"{log_prefix} [PDF-3/7] Encryption done ({encrypt_elapsed:.0f} ms): "
        f"{len(encrypted_pdf)/1024:.1f} KB encrypted"
    )

    # --- PDF 4. Vault-wrap the AES key ---
    logger.info(
        f"{log_prefix} [PDF-4/7] Vault-wrapping AES key via core API Transit proxy..."
    )
    vault_start = time.monotonic()
    try:
        vault_wrapped_aes_key = await _wrap_key_via_api(
            core_api_url, internal_token, aes_key_b64, vault_key_id
        )
        vault_elapsed = (time.monotonic() - vault_start) * 1000
        logger.info(
            f"{log_prefix} [PDF-4/7] Vault key wrap: OK "
            f"(vault_key_id={vault_key_id[:8]}..., {vault_elapsed:.0f} ms)"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [PDF-4/7] Vault key wrap FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Encryption service unavailable")

    # --- PDF 5. Upload to S3 ---
    embed_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_prefix = f"{user_id}/{content_hash}"
    s3_service = request.app.state.s3
    pdf_s3_key = f"{s3_prefix}/{timestamp}_original.bin"

    logger.info(
        f"{log_prefix} [PDF-5/7] Uploading encrypted PDF to S3 "
        f"(embed_id={embed_id}, key={pdf_s3_key})..."
    )
    s3_start = time.monotonic()
    try:
        await s3_service.upload_file(s3_key=pdf_s3_key, content=encrypted_pdf, target_env=target_env)
        s3_elapsed = (time.monotonic() - s3_start) * 1000
        logger.info(
            f"{log_prefix} [PDF-5/7] S3 upload: OK ({s3_elapsed:.0f} ms) — "
            f"{len(encrypted_pdf)/1024:.1f} KB → {pdf_s3_key}"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [PDF-5/7] S3 upload FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="File storage service unavailable")

    s3_base_url = s3_service.get_base_url(target_env=target_env)

    # --- PDF 6. Build files metadata and store upload record ---
    files_metadata = {
        "original": FileVariantMetadata(
            s3_key=pdf_s3_key,
            width=0,  # Not applicable for PDFs
            height=0,
            size_bytes=len(encrypted_pdf),
            format="pdf",
        ),
    }

    logger.info(
        f"{log_prefix} [PDF-6/7] Storing upload record in Directus (via core API)..."
    )
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
        "ai_detection": None,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        # PDF-specific metadata
        "page_count": page_count,
    }
    await _store_record_via_api(core_api_url, internal_token, upload_record)
    logger.info(f"{log_prefix} [PDF-6/7] Record stored: OK")

    # --- PDF 7. Trigger background OCR processing (fire-and-forget) ---
    logger.info(
        f"{log_prefix} [PDF-7/7] Triggering background OCR processing "
        f"(fire-and-forget, non-blocking)..."
    )
    async def _trigger_pdf_processing() -> None:
        """Fire background OCR task via core API internal endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{core_api_url}/internal/pdf/process",
                    json={
                        "embed_id": embed_id,
                        "user_id": user_id,
                        "vault_key_id": vault_key_id,
                        "s3_key": pdf_s3_key,
                        "s3_base_url": s3_base_url,
                        "vault_wrapped_aes_key": vault_wrapped_aes_key,
                        "aes_nonce": nonce_b64,
                        "filename": filename,
                        "page_count": page_count,
                        "credits_charged": credits_to_charge,
                        "user_id_hash": user_id_hash,
                    },
                    headers={"X-Internal-Service-Token": internal_token},
                )
            if resp.status_code not in (200, 201, 202):
                logger.warning(
                    f"{log_prefix} [PDF-7/7] OCR trigger returned HTTP "
                    f"{resp.status_code}: {resp.text[:200]}"
                )
            else:
                logger.info(f"{log_prefix} [PDF-7/7] OCR processing triggered: OK")
        except Exception as exc:
            # Non-fatal: processing will be retried or user will see un-OCR'd embed
            logger.warning(
                f"{log_prefix} [PDF-7/7] OCR trigger FAILED (non-fatal): {exc}"
            )

    import asyncio as _asyncio
    _asyncio.create_task(_trigger_pdf_processing())

    total_elapsed = (time.monotonic() - pdf_start) * 1000
    logger.info(
        f"{log_prefix} ── PDF Upload COMPLETE ──────────────────────────────"
    )
    logger.info(
        f"{log_prefix} embed_id={embed_id} | pages={page_count} | "
        f"hash={content_hash[:16]}... | size={len(file_bytes)/1024:.1f} KB | "
        f"credits={credits_to_charge} | total={total_elapsed:.0f} ms"
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
        ai_detection=None,
        deduplicated=False,
        page_count=page_count,
    )
