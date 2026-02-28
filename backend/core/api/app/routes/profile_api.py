# backend/core/api/app/routes/profile_api.py
#
# Public API endpoint for serving user profile images.
#
# Architecture:
#   - New profile images are stored as AES-256-GCM encrypted blobs in a
#     private S3 bucket ('profile_images_private').
#   - This endpoint decrypts the image server-side and streams the plaintext
#     bytes to the authenticated caller.
#   - Legacy profile images (uploaded before this feature) are stored as
#     plaintext in the old public-read S3 bucket.  For those users,
#     get_user_profile() still returns a direct public URL — this endpoint
#     is not reached for them (the frontend uses the URL directly).
#
# Security model:
#   - Authentication required (cookie session or Bearer API key).
#   - Access control: any authenticated user can view any profile image
#     (same behaviour as the old public-read images, but now gated by auth).
#     This will be tightened when group chats are built.
#   - The endpoint does NOT expose the AES key — it only decrypts in-memory
#     and streams the plaintext image bytes.
#   - HTTP response is Cache-Control: private, max-age=300 (5 min).
#     The browser can cache the image for 5 minutes without re-authenticating.
#
# See docs/architecture/ for full encryption flow.

import logging
import base64
import io
import os

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key
from backend.core.api.app.models.user import User
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.s3.service import S3UploadService
from backend.core.api.app.services.s3.config import get_bucket_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users", tags=["Users"])


# --- Dependency helpers (mirrors pattern from embeds_api.py) ---

def get_directus_service(request: Request) -> DirectusService:
    """Get DirectusService from app state."""
    if not hasattr(request.app.state, "directus_service"):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    """Get EncryptionService from app state."""
    if not hasattr(request.app.state, "encryption_service"):
        logger.error("EncryptionService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.encryption_service


def get_s3_service(request: Request) -> S3UploadService:
    """Get S3UploadService from app state."""
    if not hasattr(request.app.state, "s3_service"):
        logger.error("S3UploadService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.s3_service


# ---------------------------------------------------------------------------
# GET /v1/users/{user_id}/profile-image
# ---------------------------------------------------------------------------

@router.get("/{user_id}/profile-image")
@limiter.limit("120/minute")
async def get_profile_image(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service),
) -> StreamingResponse:
    """
    Serve an AES-256-GCM encrypted profile image for any authenticated user.

    The server:
    1. Fetches profile_image_s3_key, encrypted_profile_image_aes_key,
       profile_image_aes_nonce, and vault_key_id from Directus.
    2. Vault-unwraps the AES key using the *owner's* vault Transit key.
    3. Downloads the encrypted blob from the private S3 bucket.
    4. AES-GCM decrypts the blob in memory.
    5. Streams the plaintext JPEG/PNG bytes to the caller.

    Security:
    - Authentication required (session cookie or Bearer API key).
    - Access: any authenticated user may view any profile image.
    - Response is Cache-Control: private, max-age=300 (5 min browser cache).
    - If profile_image_s3_key is null (legacy user), returns 404 — the frontend
      should fall back to the legacy public URL stored in the user profile.

    Rate limit: 120 requests/minute per IP.
    """
    log_prefix = f"[ProfileImageServe] [owner:{user_id[:8]}...] [caller:{current_user.id[:8]}...]"

    try:
        # 1. Fetch the owner's profile fields directly from Directus (bypass cache
        #    because profile_image_s3_key is not stored in the Redis cache).
        environment = os.getenv("SERVER_ENVIRONMENT", "development")
        url = (
            f"{directus_service.base_url}/users/{user_id}"
            "?fields=vault_key_id,profile_image_s3_key,"
            "encrypted_profile_image_aes_key,profile_image_aes_nonce"
        )
        response = await directus_service._make_api_request("GET", url)  # noqa: SLF001

        if response.status_code == 404:
            logger.warning(f"{log_prefix} User not found in Directus")
            raise HTTPException(status_code=404, detail="User not found")

        if response.status_code != 200:
            logger.error(
                f"{log_prefix} Directus returned HTTP {response.status_code}"
            )
            raise HTTPException(status_code=500, detail="Failed to fetch user profile")

        user_data = response.json().get("data", {})

        s3_key: str | None = user_data.get("profile_image_s3_key")
        wrapped_aes_key: str | None = user_data.get("encrypted_profile_image_aes_key")
        nonce_b64: str | None = user_data.get("profile_image_aes_nonce")
        vault_key_id: str | None = user_data.get("vault_key_id")

        if not s3_key:
            # Legacy user — no encrypted profile image exists yet.
            # The frontend should use the legacy public URL.
            logger.info(f"{log_prefix} No profile_image_s3_key — legacy user, returning 404")
            raise HTTPException(
                status_code=404,
                detail="No encrypted profile image found for this user",
            )

        if not wrapped_aes_key or not nonce_b64:
            logger.error(f"{log_prefix} profile_image_s3_key present but AES fields missing")
            raise HTTPException(status_code=500, detail="Profile image encryption data incomplete")

        if not vault_key_id:
            logger.error(f"{log_prefix} vault_key_id missing for profile image owner")
            raise HTTPException(status_code=500, detail="User encryption key not found")

        # 2. Vault-unwrap the AES key using the image owner's Transit key.
        aes_key_b64: str | None = await encryption_service.decrypt_with_user_key(
            wrapped_aes_key, vault_key_id
        )
        if not aes_key_b64:
            logger.error(f"{log_prefix} Vault Transit key-unwrap returned empty result")
            raise HTTPException(status_code=500, detail="Failed to unwrap profile image key")

        # 3. Download the encrypted blob from the private S3 bucket.
        bucket_name = get_bucket_name("profile_images_private", environment)
        logger.info(f"{log_prefix} Downloading encrypted blob from S3: {s3_key}")
        encrypted_data = await s3_service.get_file(bucket_name=bucket_name, object_key=s3_key)

        if not encrypted_data:
            logger.error(f"{log_prefix} Encrypted blob not found in S3: {s3_key}")
            raise HTTPException(status_code=404, detail="Profile image not found in storage")

        # 4. AES-256-GCM decrypt in memory.
        try:
            aes_key = base64.b64decode(aes_key_b64)
            nonce = base64.b64decode(nonce_b64)
            aesgcm = AESGCM(aes_key)
            image_bytes = aesgcm.decrypt(nonce, encrypted_data, None)
        except Exception as e:
            logger.error(f"{log_prefix} AES-GCM decryption failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to decrypt profile image")

        # 5. Stream plaintext bytes to caller.
        # Profile images are JPEG (340x340) uploaded via the browser canvas.
        logger.info(
            f"{log_prefix} Serving decrypted profile image "
            f"({len(image_bytes) / 1024:.1f} KB)"
        )
        return StreamingResponse(
            io.BytesIO(image_bytes),
            media_type="image/jpeg",
            headers={
                # Private: browser may cache for 5 min; CDNs/proxies must not share.
                "Cache-Control": "private, max-age=300",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
