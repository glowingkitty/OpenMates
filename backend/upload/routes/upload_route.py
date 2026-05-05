# backend/upload/routes/upload_route.py
#
# POST /v1/upload/file   — the core upload endpoint for chat files.
# POST /v1/upload/profile-image — profile image upload endpoint.
#
# Full pipeline for supported file types:
#
# Images pipeline (POST /v1/upload/file):
#   1. Authenticate user via refresh token cookie (forwarded to core API)
#   2. Validate file size (100 MB limit) and MIME type whitelist
#   3. Compute SHA-256 hash → check deduplication via core API
#   4. ClamAV malware scan (blocks until result; 422 if threat detected)
#   5. SightEngine content safety scan (nudity/violence/gore — BLOCKING; 422 if rejected)
#      If rejected: proxy rejection event to core API to track per-user reject count.
#      Account is deleted if user has 4+ rejections within 24h.
#   6. SightEngine AI-generated detection (non-blocking; stores score as metadata)
#   7. Generate WEBP preview via Pillow
#   8. Generate random AES-256 key, encrypt file + preview with AES-256-GCM
#   9. Vault-wrap the AES key via core API internal endpoint
#   10. Upload encrypted bytes to S3 chatfiles bucket
#   11. Store upload record via core API internal endpoint
#   12. Return JSON with embed_id, S3 keys, AES key, vault_wrapped_aes_key
#
# Profile image pipeline (POST /v1/upload/profile-image):
#   1. Authenticate user via refresh token cookie
#   2. Validate file size (300 KB limit) and MIME type (JPEG/PNG only)
#   3. ClamAV malware scan
#   4. SightEngine content safety scan (same thresholds as chat images)
#      Rejection proxied to core API for per-user tracking + account deletion.
#   5. Upload image bytes to S3 profile_images bucket (public-read, plaintext)
#   6. Proxy new image URL to core API for encryption + Directus update
#   7. Return JSON with url and result status
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
# Audio pipeline:
#   1. Authenticate user
#   2. Validate file size and MIME type
#   3. Compute SHA-256 hash → check deduplication
#   4. ClamAV malware scan
#   5. Encrypt audio bytes with AES-256-GCM (single 'original' variant — no preview)
#   6. Vault-wrap the AES key
#   7. Upload encrypted audio to S3
#   8. Store upload record
#   9. Return JSON with embed_id, S3 key, AES key
#      (Transcription is triggered separately by the frontend via app-audio/skills/transcribe)
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

# Allowed MIME types (images + PDFs + audio)
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
    # SVG — rasterized server-side by cairosvg in PreviewGeneratorService before
    # the Pillow pipeline runs.  This produces correct WEBP previews and enables
    # AI vision (images.view skill) for user-uploaded vector graphics.
    "image/svg+xml",
}

ALLOWED_PDF_MIMES = {
    "application/pdf",
}

# Audio MIME types accepted from browser MediaRecorder.
# Firefox iOS typically produces audio/ogg;codecs=opus, Chrome/Safari produce audio/webm.
# We also allow audio/mp4 (Safari fallback) and audio/mpeg for completeness.
ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/aac",
}

ALLOWED_MIMES = ALLOWED_IMAGE_MIMES | ALLOWED_PDF_MIMES | ALLOWED_AUDIO_MIMES

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


class ProfileImageUploadResponse(BaseModel):
    """Response returned after a successful profile image upload."""
    status: str = Field(..., description="'ok' on success, 'rejected' on content safety failure, 'account_deleted' if account was deleted")
    url: Optional[str] = Field(None, description="Public S3 URL of the uploaded profile image (only on status='ok')")
    reject_count: Optional[int] = Field(None, description="Cumulative rejection count for this user (only on status='rejected')")
    detail: Optional[str] = Field(None, description="Human-readable rejection reason")


# ---------------------------------------------------------------------------
# Target environment resolution — picks core API credentials based on which
# domain the request arrived on, as signalled by Caddy via X-Target-Env.
#
# There is only ONE upload server domain: upload.openmates.org
# Caddy sets X-Target-Env to "prod" or "dev" based on the Origin header of the request:
#   Origin: https://openmates.org     → X-Target-Env: prod → PROD_CORE_API_URL + PROD_INTERNAL_API_SHARED_TOKEN
#   Origin: https://dev.openmates.org → X-Target-Env: dev  → DEV_CORE_API_URL  + DEV_INTERNAL_API_SHARED_TOKEN
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


async def _report_content_safety_rejection_via_api(
    core_api_url: str,
    internal_token: str,
    user_id: str,
    filename: str,
    rejection_reason: str,
    upload_type: str = "chat_image",
) -> Dict[str, Any]:
    """
    Report a content safety rejection to the core API.

    The core API tracks per-user rejection counts in Redis (24h TTL) and
    deletes accounts that repeatedly upload policy-violating content.

    Called after SightEngine rejects an image upload (content safety check).
    The core API handles all user data and Directus operations — this service
    never writes user data directly.

    Args:
        core_api_url: Core API base URL.
        internal_token: Internal service token for authentication.
        user_id: ID of the user who uploaded the rejected image.
        filename: Original filename (used for logging, not stored).
        rejection_reason: Short reason string from SightEngine (e.g. "sexual_activity=0.95").
        upload_type: "chat_image" or "profile_image" — used for tracking separate counters.

    Returns:
        Dict with "result": "tracked" | "account_deleted" and optional "reject_count".
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{core_api_url}/internal/uploads/content-safety-reject",
                json={
                    "user_id": user_id,
                    "rejection_reason": rejection_reason,
                    "upload_type": upload_type,
                },
                headers={"X-Internal-Service-Token": internal_token},
            )
        if resp.status_code in (200, 201):
            return resp.json()
        logger.warning(
            f"[Upload ContentSafety] Reject report returned HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )
        # Non-fatal for the rejection tracking, but we still reject the upload
        return {"result": "tracking_failed"}
    except Exception as e:
        logger.warning(
            f"[Upload ContentSafety] Failed to report rejection to core API "
            f"(non-fatal for rejection): {e}"
        )
        return {"result": "tracking_failed"}


async def _cache_embed_via_api(
    core_api_url: str,
    internal_token: str,
    embed_id: str,
    user_id: str,
    vault_wrapped_aes_key: str,
    aes_nonce: str,
    s3_base_url: str,
    files_metadata: Dict[str, Any],
    content_type: str,
    original_filename: str,
    ai_detection: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Cache an upload embed in Redis via the core API's /internal/uploads/cache-embed endpoint.

    This is a non-fatal fire-and-forget call.  Without it, app skills such as
    images-view and pdf-read fail with "Embed not found in cache" because the
    upload pipeline never wrote the embed into Redis (only AI-generated embeds
    had Redis entries).  The core API's endpoint writes `embed:{embed_id}` with
    a 72-hour TTL, matching the structure expected by view_skill / read_skill.
    """
    try:
        payload: Dict[str, Any] = {
            "embed_id": embed_id,
            "user_id": user_id,
            "vault_wrapped_aes_key": vault_wrapped_aes_key,
            "aes_nonce": aes_nonce,
            "s3_base_url": s3_base_url,
            "files": files_metadata,
            "content_type": content_type,
            "original_filename": original_filename,
            "ai_detection": ai_detection,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{core_api_url}/internal/uploads/cache-embed",
                json=payload,
                headers={"X-Internal-Service-Token": internal_token},
            )
        if resp.status_code not in (200, 201):
            logger.warning(
                f"[Upload CacheEmbed] Failed to cache embed {embed_id[:8]}...: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        else:
            logger.info(f"[Upload CacheEmbed] Embed {embed_id[:8]}... cached in Redis: OK")
    except Exception as e:
        # Non-fatal: upload succeeds; skills will just fail with "not found in cache"
        # rather than the upload itself failing.
        logger.warning(f"[Upload CacheEmbed] Failed to cache embed (non-fatal): {e}")


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
    # Audio: check both detected MIME and declared Content-Type because python-magic
    # may not distinguish audio/ogg;codecs=opus from plain audio/ogg.
    # We strip codec parameters (e.g. "audio/ogg;codecs=opus" → "audio/ogg") before checking.
    declared_audio_base = content_type.split(";")[0].strip()
    detected_audio_base = detected_mime.split(";")[0].strip()
    is_audio = (
        detected_audio_base in ALLOWED_AUDIO_MIMES
        or declared_audio_base in ALLOWED_AUDIO_MIMES
    )

    if not is_image and not is_pdf and not is_audio:
        logger.warning(
            f"{log_prefix} [3/13] REJECTED — unsupported MIME type "
            f"detected={detected_mime!r} declared={content_type!r}"
        )
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type: {detected_mime}. "
                "Supported: images (JPEG, PNG, WEBP, GIF, HEIC, SVG), PDFs, and audio (WebM, OGG, MP4)."
            ),
        )

    # Use the detected MIME type (more reliable than Content-Type header).
    # For audio, prefer the declared Content-Type with codec info stripped — python-magic
    # maps many audio formats to generic types (e.g. audio/ogg regardless of codec).
    if is_audio:
        content_type = declared_audio_base if declared_audio_base in ALLOWED_AUDIO_MIMES else detected_audio_base
    else:
        content_type = detected_mime
    file_kind = "image" if is_image else ("PDF" if is_pdf else "audio")
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

        elif is_pdf:
            # ── Safe PDF dedup: reuse S3 object but create fresh embed_id ──
            # NEVER reuse the old embed_id — it has stale encryption keys from
            # a previous session. Instead, pass the existing S3 data to the PDF
            # upload handler so it can skip S3 upload + encryption + credit charge
            # but still create a fresh embed_id and trigger fresh OCR processing.
            # See OPE-485 for the full rationale.
            logger.info(
                f"{log_prefix} [5/13] PDF duplicate — reusing S3 object with fresh embed_id "
                f"(old_embed={existing_record.get('embed_id')})"
            )
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
                reuse_s3_data=existing_record,
            )

        else:
            # ── Standard dedup for images/audio: return existing embed_id ──
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
    # AUDIO BRANCH: encrypt + upload raw bytes, no preview or AI detection.
    # Transcription is triggered separately by the frontend via app-audio.
    # ===========================================================================
    if is_audio:
        return await _handle_audio_upload(
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

    # --- 7. [Images] SightEngine combined check (content safety + AI detection, ONE request) ---
    # Single API call with models=nudity-2.0,offensive,gore,genai replaces the previous
    # two sequential calls, saving one full HTTP round-trip to the SightEngine API.
    #
    # Safety check (nudity/violence/gore) is BLOCKING — rejects on violation.
    # AI detection (genai) is NON-BLOCKING — result stored as metadata only.
    #
    # If the image fails safety, we report the rejection to the core API (for per-user
    # tracking + account deletion) and return 422 to the client.
    sightengine = request.app.state.sightengine
    ai_detection_result = None
    if is_image and sightengine.is_enabled:
        logger.info(
            f"{log_prefix} [7/13] SightEngine combined check: "
            f"nudity/violence/gore + AI detection (single request)..."
        )
        sightengine_start = time.monotonic()
        safety_result, ai_result = await sightengine.check_all(file_bytes, filename=filename)
        sightengine_elapsed = (time.monotonic() - sightengine_start) * 1000

        if not safety_result.is_safe:
            logger.warning(
                f"{log_prefix} [7/13] Content safety REJECTED — "
                f"reason: {safety_result.reason} ({sightengine_elapsed:.0f} ms)"
            )

            # safety_service_unavailable means the SightEngine API itself is down/erroring.
            # Do NOT report this as a user violation — the user did nothing wrong.
            # Return a clear "try again later" message instead.
            if safety_result.reason == "safety_service_unavailable":
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "safety_service_unavailable",
                        "message": "Safety processing failed. Try again later.",
                    },
                )

            # Report rejection to core API (tracks reject count, handles account deletion)
            rejection_report = await _report_content_safety_rejection_via_api(
                core_api_url=core_api_url,
                internal_token=internal_token,
                user_id=user_id,
                filename=filename,
                rejection_reason=safety_result.reason or "content_safety_violation",
                upload_type="chat_image",
            )
            rejection_result = rejection_report.get("result", "tracked")
            reject_count = rejection_report.get("reject_count", 0)

            # If the account was deleted (repeated violations), return special status
            if rejection_result == "account_deleted":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "account_deleted",
                        "message": "Account deleted due to repeated policy violations",
                    },
                )

            raise HTTPException(
                status_code=422,
                detail={
                    "code": "content_rejected",
                    "message": "Image rejected: content violates community guidelines (nudity, violence, or gore)",
                    "reject_count": reject_count,
                },
            )
        else:
            logger.info(
                f"{log_prefix} [7/13] Content safety: PASSED ✓ ({sightengine_elapsed:.0f} ms)"
            )

        if ai_result is not None:
            ai_detection_result = AIDetectionMetadata(
                ai_generated=ai_result.ai_generated,
                provider=ai_result.provider,
            )
            logger.info(
                f"{log_prefix} [7/13] AI detection: score={ai_result.ai_generated:.3f} "
                f"(included in same request, no extra round-trip)"
            )
        else:
            logger.warning(
                f"{log_prefix} [7/13] AI detection: SightEngine returned None "
                f"(non-fatal, upload continues without score)"
            )
    elif is_image:
        logger.info(
            f"{log_prefix} [7/13] SightEngine checks: SKIPPED "
            f"(SightEngine not configured — set SECRET__SIGHTENGINE__* to enable)"
        )
    else:
        logger.info(f"{log_prefix} [7/13] SightEngine checks: SKIPPED (non-image file)")

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

    # Cache embed in Redis so that app skills (images-view, etc.) can retrieve
    # the embed data server-side.  AI-generated embeds are cached by generate_task.py;
    # user-uploaded embeds were never cached, causing "Embed not found in cache" errors.
    await _cache_embed_via_api(
        core_api_url=core_api_url,
        internal_token=internal_token,
        embed_id=embed_id,
        user_id=user_id,
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        aes_nonce=nonce_b64,
        s3_base_url=s3_base_url,
        files_metadata={k: v.model_dump() for k, v in files_metadata.items()},
        content_type=content_type,
        original_filename=filename,
        ai_detection=ai_detection_dict,
    )

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
# PDF upload helpers
# ---------------------------------------------------------------------------


async def _handle_pdf_dedup(
    request: Any,
    reuse_s3_data: Dict[str, Any],
    page_count: int,
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
    Safe PDF dedup: reuse existing S3 object with a fresh embed_id.

    Skips encryption, vault wrap, and S3 upload. Credits are always charged
    (every PDF upload costs credits regardless of dedup). Creates a new upload
    record and triggers OCR with the existing S3 key so the new embed_id gets
    its own OCR cache entry.  See OPE-485 for architecture rationale.
    """
    import hashlib as _hashlib

    files_data = reuse_s3_data.get("files_metadata", {})
    pdf_s3_key = next(
        (v.get("s3_key") for v in files_data.values() if v.get("s3_key")),
        None,
    )
    if not pdf_s3_key:
        logger.error(f"{log_prefix} [PDF-dedup] No S3 key in reuse data — falling back to fresh upload")
        raise HTTPException(status_code=500, detail="PDF dedup failed: missing S3 key")

    aes_key_b64 = reuse_s3_data["aes_key"]
    nonce_b64 = reuse_s3_data["aes_nonce"]
    vault_wrapped_aes_key = reuse_s3_data["vault_wrapped_aes_key"]

    s3_service = request.app.state.s3
    s3_base_url = s3_service.get_base_url(target_env=target_env)

    # Fresh embed_id — never reuse the old one (stale encryption keys)
    embed_id = str(uuid.uuid4())
    user_id_hash = _hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    # Always charge credits — every PDF upload costs credits regardless of dedup.
    # The OCR cache copy is our internal cost optimization, not a user discount.
    credits_to_charge = page_count * PDF_CREDITS_PER_PAGE
    logger.info(
        f"{log_prefix} [PDF-dedup] Fresh embed_id={embed_id} | "
        f"reusing S3 key={pdf_s3_key} | pages={page_count} | "
        f"credits={credits_to_charge}"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as _client:
            charge_resp = await _client.post(
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
                        "deduplicated": True,
                    },
                },
                headers={"X-Internal-Service-Token": internal_token},
            )
        if charge_resp.status_code == 402:
            logger.warning(f"{log_prefix} [PDF-dedup] Insufficient credits for {page_count}-page PDF")
            raise HTTPException(status_code=402, detail="Insufficient credits for PDF processing")
        elif charge_resp.status_code not in (200, 201):
            logger.error(f"{log_prefix} [PDF-dedup] Billing charge failed: HTTP {charge_resp.status_code}")
            raise HTTPException(status_code=503, detail="Billing service unavailable")
        logger.info(f"{log_prefix} [PDF-dedup] Credits charged: {credits_to_charge}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} [PDF-dedup] Credit charge failed: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Billing service unavailable")

    # Build files metadata from existing record
    files_metadata = {
        k: FileVariantMetadata(**v) for k, v in files_data.items()
    }

    # Store new upload record pointing to the same S3 object
    upload_record = {
        "embed_id": embed_id,
        "user_id": user_id,
        "content_hash": content_hash,
        "original_filename": filename,
        "content_type": content_type,
        "file_size_bytes": reuse_s3_data.get("file_size_bytes", 0),
        "s3_base_url": s3_base_url,
        "files_metadata": {k: v.model_dump() for k, v in files_metadata.items()},
        "aes_key": aes_key_b64,
        "aes_nonce": nonce_b64,
        "vault_wrapped_aes_key": vault_wrapped_aes_key,
        "malware_scan": "clean",
        "ai_detection": None,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "page_count": page_count,
    }
    await _store_record_via_api(core_api_url, internal_token, upload_record)
    logger.info(f"{log_prefix} [PDF-dedup] Upload record stored")

    # Cache embed in Redis
    await _cache_embed_via_api(
        core_api_url=core_api_url,
        internal_token=internal_token,
        embed_id=embed_id,
        user_id=user_id,
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        aes_nonce=nonce_b64,
        s3_base_url=s3_base_url,
        files_metadata={k: v.model_dump() for k, v in files_metadata.items()},
        content_type=content_type,
        original_filename=filename,
        ai_detection=None,
    )

    # Trigger OCR for the new embed_id (always — even if the old embed's OCR
    # cache is still warm, we need a cache entry keyed to the new embed_id).
    async def _trigger_dedup_ocr() -> None:
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
                        # Pass old embed_id so OCR task can copy cache instead of re-running
                        "source_embed_id": reuse_s3_data.get("embed_id"),
                    },
                    headers={"X-Internal-Service-Token": internal_token},
                )
            if resp.status_code not in (200, 201, 202):
                logger.warning(
                    f"{log_prefix} [PDF-dedup] OCR trigger returned HTTP {resp.status_code}"
                )
            else:
                logger.info(f"{log_prefix} [PDF-dedup] OCR processing triggered for {embed_id}")
        except Exception as exc:
            logger.warning(f"{log_prefix} [PDF-dedup] OCR trigger failed (non-fatal): {exc}")

    import asyncio as _asyncio_dedup
    _asyncio_dedup.create_task(_trigger_dedup_ocr())

    logger.info(f"{log_prefix} [PDF-dedup] Complete — fresh embed_id={embed_id}")

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
        deduplicated=True,
        page_count=page_count,
    )


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
    reuse_s3_data: Optional[Dict[str, Any]] = None,
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

    When reuse_s3_data is provided (safe PDF dedup), steps 2-5 are skipped:
    the same S3 object is reused but a fresh embed_id is created. Credits
    are not re-charged (already paid on the original upload). OCR always
    runs to ensure a fresh cache entry for the new embed_id.

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

    # ── Safe PDF dedup shortcut: reuse S3 object, fresh embed_id ──
    # When reuse_s3_data is provided, the S3 object already exists. Skip
    # encryption, vault wrap, S3 upload, and credit charging. Just create
    # a new embed record + trigger OCR with the existing S3 key.
    if reuse_s3_data:
        return await _handle_pdf_dedup(
            request=request,
            reuse_s3_data=reuse_s3_data,
            page_count=page_count,
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

    # Cache embed in Redis so that pdf-read skill can retrieve it server-side.
    await _cache_embed_via_api(
        core_api_url=core_api_url,
        internal_token=internal_token,
        embed_id=embed_id,
        user_id=user_id,
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        aes_nonce=nonce_b64,
        s3_base_url=s3_base_url,
        files_metadata={k: v.model_dump() for k, v in files_metadata.items()},
        content_type=content_type,
        original_filename=filename,
        ai_detection=None,
    )

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


# ---------------------------------------------------------------------------
# Audio upload helper
# ---------------------------------------------------------------------------

async def _handle_audio_upload(
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
    Handle the audio upload pipeline.

    Audio files require no preview generation or AI-generated-content detection.
    The pipeline is:
      1. Encrypt the raw audio bytes with AES-256-GCM (single 'original' variant)
      2. Vault-wrap the AES key via core API Transit proxy
      3. Upload the encrypted audio to S3
      4. Store the upload record via core API
      5. Return UploadFileResponse

    Transcription is NOT triggered here — the frontend calls
    POST /v1/apps/audio/skills/transcribe separately after receiving this response.
    """
    audio_start = time.monotonic()
    logger.info(
        f"{log_prefix} ── Audio Upload started ─────────────────────────────"
    )
    logger.info(
        f"{log_prefix} [Audio-1/4] Encrypting audio with AES-256-GCM "
        f"({len(file_bytes)/1024:.1f} KB, type={content_type!r})..."
    )

    # --- Audio 1. AES-256-GCM encryption (single original variant) ---
    encrypt_start = time.monotonic()
    crypto_service = request.app.state.file_encryption
    encrypted_audio, aes_key_b64, nonce_b64 = crypto_service.encrypt_bytes(file_bytes)
    encrypt_elapsed = (time.monotonic() - encrypt_start) * 1000
    logger.info(
        f"{log_prefix} [Audio-1/4] Encryption done ({encrypt_elapsed:.0f} ms): "
        f"{len(encrypted_audio)/1024:.1f} KB encrypted"
    )

    # --- Audio 2. Vault-wrap the AES key ---
    logger.info(
        f"{log_prefix} [Audio-2/4] Vault-wrapping AES key via core API Transit proxy..."
    )
    vault_start = time.monotonic()
    try:
        vault_wrapped_aes_key = await _wrap_key_via_api(
            core_api_url, internal_token, aes_key_b64, vault_key_id
        )
        vault_elapsed = (time.monotonic() - vault_start) * 1000
        logger.info(
            f"{log_prefix} [Audio-2/4] Vault key wrap: OK "
            f"(vault_key_id={vault_key_id[:8]}..., {vault_elapsed:.0f} ms)"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [Audio-2/4] Vault key wrap FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Encryption service unavailable")

    # --- Audio 3. Upload encrypted audio to S3 ---
    embed_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_prefix = f"{user_id}/{content_hash}"
    s3_service = request.app.state.s3
    audio_s3_key = f"{s3_prefix}/{timestamp}_original.bin"

    logger.info(
        f"{log_prefix} [Audio-3/4] Uploading encrypted audio to S3 "
        f"(embed_id={embed_id}, key={audio_s3_key})..."
    )
    s3_start = time.monotonic()
    try:
        await s3_service.upload_file(
            s3_key=audio_s3_key, content=encrypted_audio, target_env=target_env
        )
        s3_elapsed = (time.monotonic() - s3_start) * 1000
        logger.info(
            f"{log_prefix} [Audio-3/4] S3 upload: OK ({s3_elapsed:.0f} ms) — "
            f"{len(encrypted_audio)/1024:.1f} KB → {audio_s3_key}"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [Audio-3/4] S3 upload FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="File storage service unavailable")

    s3_base_url = s3_service.get_base_url(target_env=target_env)

    # --- Audio 4. Build files metadata and store upload record ---
    files_metadata = {
        "original": FileVariantMetadata(
            s3_key=audio_s3_key,
            width=0,   # Not applicable for audio
            height=0,
            size_bytes=len(encrypted_audio),
            format=content_type.split("/")[-1].split(";")[0],  # e.g. "webm", "ogg"
        ),
    }

    logger.info(
        f"{log_prefix} [Audio-4/4] Storing upload record in Directus (via core API)..."
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
    }
    await _store_record_via_api(core_api_url, internal_token, upload_record)
    logger.info(f"{log_prefix} [Audio-4/4] Record stored: OK")

    total_elapsed = (time.monotonic() - audio_start) * 1000
    logger.info(
        f"{log_prefix} ── Audio Upload COMPLETE ────────────────────────────"
    )
    logger.info(
        f"{log_prefix} embed_id={embed_id} | type={content_type} | "
        f"hash={content_hash[:16]}... | size={len(file_bytes)/1024:.1f} KB | "
        f"total={total_elapsed:.0f} ms"
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
    )


# ---------------------------------------------------------------------------
# Profile image upload endpoint
# ---------------------------------------------------------------------------

# Allowed MIME types for profile images (JPEG/PNG only — browser pre-processes to JPEG anyway)
PROFILE_IMAGE_ALLOWED_MIMES = {"image/jpeg", "image/jpg", "image/png"}

# Max size: 300 KB (images are pre-processed to 340×340 JPEG by the browser)
PROFILE_IMAGE_MAX_SIZE_BYTES = 300 * 1024  # 300 KB


@router.post("/profile-image", response_model=ProfileImageUploadResponse)
async def upload_profile_image(
    request: Request,
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_authenticated_user),
) -> ProfileImageUploadResponse:
    """
    Upload or replace the authenticated user's profile image.

    Pipeline:
      1. Validate file size (≤ 300 KB) and MIME type (JPEG/PNG only)
      2. ClamAV malware scan (blocking — 422 on threat)
      3. SightEngine content safety scan (nudity/violence/gore — BLOCKING)
         Rejected images proxy a rejection event to the core API for
         per-user tracking and account deletion on repeated violations.
      4. AES-256-GCM encrypt image bytes and upload to private S3 bucket
      5. Proxy s3_key + AES metadata to core API for Vault key-wrapping + Directus update
      6. Return status + proxy URL (/v1/users/{user_id}/profile-image)

    The browser pre-processes the image to 340×340 JPEG before sending, so
    we receive a small, square, already-cropped image file.

    **Rate limit:** 10 uploads per minute per user.
    """
    user_id: str = user["user_id"]
    log_prefix = f"[ProfileUpload] [user:{user_id[:8]}...]"
    upload_start = time.monotonic()

    core_api_url, internal_token = _get_core_api_credentials(request)
    target_env = request.headers.get("X-Target-Env", "prod").lower()

    # --- 1. Read file bytes ---
    file_bytes = await file.read()
    filename = file.filename or "profile.jpg"
    content_type = file.content_type or "image/jpeg"

    logger.info(
        f"{log_prefix} ── Profile image upload started ───────────────────────"
    )
    logger.info(
        f"{log_prefix} [1/5] File received: {filename!r} "
        f"({len(file_bytes) / 1024:.1f} KB, declared type: {content_type})"
    )

    # --- 1a. Size validation ---
    if len(file_bytes) > PROFILE_IMAGE_MAX_SIZE_BYTES:
        logger.warning(
            f"{log_prefix} [1/5] REJECTED — file too large: "
            f"{len(file_bytes) / 1024:.1f} KB > {PROFILE_IMAGE_MAX_SIZE_BYTES // 1024} KB limit"
        )
        raise HTTPException(
            status_code=413,
            detail=(
                f"Profile image too large. Maximum allowed size is "
                f"{PROFILE_IMAGE_MAX_SIZE_BYTES // 1024} KB"
            ),
        )

    # --- 1b. MIME type validation (whitelist + python-magic verification) ---
    try:
        import magic  # type: ignore[import]
        detected_mime = magic.from_buffer(file_bytes, mime=True)
    except ImportError:
        logger.warning("[ProfileUpload] python-magic not available, using Content-Type header only")
        detected_mime = content_type
    except Exception as e:
        logger.warning(f"[ProfileUpload] MIME detection failed: {e}, using Content-Type header")
        detected_mime = content_type

    if detected_mime not in PROFILE_IMAGE_ALLOWED_MIMES and content_type not in PROFILE_IMAGE_ALLOWED_MIMES:
        logger.warning(
            f"{log_prefix} [1/5] REJECTED — unsupported MIME type "
            f"detected={detected_mime!r} declared={content_type!r}"
        )
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Profile images must be JPEG or PNG.",
        )

    # Use detected MIME (more reliable)
    if detected_mime in PROFILE_IMAGE_ALLOWED_MIMES:
        content_type = detected_mime

    logger.info(
        f"{log_prefix} [1/5] Validation: OK — "
        f"{len(file_bytes) / 1024:.1f} KB, type={content_type!r}"
    )

    # --- 2. ClamAV malware scan ---
    logger.info(f"{log_prefix} [2/5] ClamAV malware scan ({len(file_bytes) / 1024:.1f} KB)...")
    scan_start = time.monotonic()
    malware_service = request.app.state.malware_scanner
    try:
        scan_result = await malware_service.scan(file_bytes)
    except RuntimeError as e:
        logger.error(f"{log_prefix} [2/5] ClamAV scan FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Malware scanning service unavailable")

    scan_elapsed = (time.monotonic() - scan_start) * 1000
    if not scan_result.is_clean:
        logger.warning(
            f"{log_prefix} [2/5] MALWARE DETECTED in {filename!r}: "
            f"{scan_result.threat_name} ({scan_elapsed:.0f} ms)"
        )
        raise HTTPException(
            status_code=422,
            detail=f"File rejected: threat detected ({scan_result.threat_name})",
        )
    logger.info(f"{log_prefix} [2/5] ClamAV scan: CLEAN ✓ ({scan_elapsed:.0f} ms)")

    # --- 3. SightEngine content safety scan (BLOCKING) ---
    sightengine = request.app.state.sightengine
    if sightengine.is_enabled:
        logger.info(
            f"{log_prefix} [3/5] Content safety: running SightEngine nudity/violence/gore check..."
        )
        safety_start = time.monotonic()
        safety_result = await sightengine.check_content_safety(file_bytes, filename=filename)
        safety_elapsed = (time.monotonic() - safety_start) * 1000

        if not safety_result.is_safe:
            logger.warning(
                f"{log_prefix} [3/5] Content safety REJECTED — "
                f"reason: {safety_result.reason} ({safety_elapsed:.0f} ms)"
            )
            # Report rejection to core API for per-user tracking + account deletion
            rejection_report = await _report_content_safety_rejection_via_api(
                core_api_url=core_api_url,
                internal_token=internal_token,
                user_id=user_id,
                filename=filename,
                rejection_reason=safety_result.reason or "content_safety_violation",
                upload_type="profile_image",
            )
            rejection_result = rejection_report.get("result", "tracked")
            reject_count = rejection_report.get("reject_count", 0)

            if rejection_result == "account_deleted":
                return ProfileImageUploadResponse(
                    status="account_deleted",
                    detail="Account deleted due to repeated policy violations",
                )

            return ProfileImageUploadResponse(
                status="rejected",
                reject_count=reject_count,
                detail="Image rejected: content violates community guidelines (nudity, violence, or gore)",
            )
        else:
            logger.info(
                f"{log_prefix} [3/5] Content safety: PASSED ✓ ({safety_elapsed:.0f} ms)"
            )
    else:
        logger.info(
            f"{log_prefix} [3/5] Content safety: SKIPPED "
            f"(SightEngine not configured — set SECRET__SIGHTENGINE__* to enable)"
        )

    # --- 4. Encrypt bytes (AES-256-GCM) and upload to private S3 bucket ---
    # New profile images are encrypted server-side before S3 storage.
    # The private bucket has no public-read ACL; images are served by the core
    # API via GET /v1/users/{user_id}/profile-image (authenticated proxy).
    import random as _random
    import string as _string
    random_suffix = "".join(_random.choices(_string.ascii_lowercase + _string.digits, k=8))
    # Use .enc extension to signal encrypted content in S3
    profile_s3_key = f"{user_id}-{int(time.time())}-{random_suffix}.enc"

    logger.info(
        f"{log_prefix} [4/5] Encrypting profile image bytes with AES-256-GCM..."
    )
    encryption_service = request.app.state.file_encryption
    encrypted_bytes, aes_key_b64, nonce_b64 = encryption_service.encrypt_bytes(file_bytes)
    logger.info(
        f"{log_prefix} [4/5] Encrypted: {len(file_bytes) / 1024:.1f} KB → "
        f"{len(encrypted_bytes) / 1024:.1f} KB ciphertext"
    )

    logger.info(
        f"{log_prefix} [4/5] Uploading to private S3 profile bucket "
        f"(key={profile_s3_key})..."
    )
    s3_start = time.monotonic()
    s3_service = request.app.state.s3
    try:
        await s3_service.upload_profile_image_private(
            s3_key=profile_s3_key,
            content=encrypted_bytes,
            target_env=target_env,
        )
        s3_elapsed = (time.monotonic() - s3_start) * 1000
        logger.info(
            f"{log_prefix} [4/5] S3 private upload: OK ({s3_elapsed:.0f} ms) — "
            f"{len(encrypted_bytes) / 1024:.1f} KB → {profile_s3_key}"
        )
    except RuntimeError as e:
        logger.error(f"{log_prefix} [4/5] S3 private upload FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="File storage service unavailable")

    # --- 5. Proxy s3_key + AES fields to core API for Vault key-wrapping + Directus update ---
    # The core API will:
    #   - Vault-wrap the plaintext AES key using the user's Transit key
    #   - Read and delete the old profile_image_s3_key from Directus (old object cleanup)
    #   - Write profile_image_s3_key, encrypted_profile_image_aes_key, profile_image_aes_nonce
    #   - Update Redis cache with the proxy URL /v1/users/{user_id}/profile-image
    proxy_url = f"/v1/users/{user_id}/profile-image"
    logger.info(
        f"{log_prefix} [5/5] Proxying s3_key and AES metadata to core API "
        f"for Vault key-wrapping and Directus update..."
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{core_api_url}/internal/profile-image/process",
                json={
                    "user_id": user_id,
                    "s3_key": profile_s3_key,
                    "aes_key_b64": aes_key_b64,
                    "nonce_b64": nonce_b64,
                    "target_env": target_env,
                },
                headers={"X-Internal-Service-Token": internal_token},
            )

        if resp.status_code == 200:
            total_elapsed = (time.monotonic() - upload_start) * 1000
            logger.info(
                f"{log_prefix} ── Profile image upload COMPLETE ─────────────────"
            )
            logger.info(
                f"{log_prefix} s3_key={profile_s3_key} | total={total_elapsed:.0f} ms"
            )
            return ProfileImageUploadResponse(
                status="ok",
                url=proxy_url,
            )
        elif resp.status_code == 422:
            # The core API reports a content safety rejection (defensive: should not happen
            # since we check before uploading)
            process_data = resp.json()
            return ProfileImageUploadResponse(
                status="rejected",
                reject_count=process_data.get("reject_count", 0),
                detail=process_data.get("detail", "Image not allowed"),
            )
        else:
            logger.error(
                f"{log_prefix} [5/5] Core API process endpoint returned "
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
            raise HTTPException(status_code=503, detail="Profile image processing service unavailable")

    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.error(f"{log_prefix} [5/5] Core API process endpoint timed out")
        raise HTTPException(status_code=503, detail="Profile image processing service timeout")
    except Exception as e:
        logger.error(
            f"{log_prefix} [5/5] Core API process endpoint request failed: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Profile image processing failed")
