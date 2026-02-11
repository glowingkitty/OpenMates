# backend/core/api/app/routes/embeds_api.py
#
# External API endpoints for accessing embed files (images, PDFs, etc.).
# This router provides a unified endpoint for downloading files from embeds.
#
# Architecture:
# - Embeds can contain file references (e.g., generated images with S3 keys)
# - This endpoint decrypts the embed content using Vault, extracts file data,
#   and returns the decrypted file to the client
# - Used by both REST API clients and web app for downloading generated content
# - See docs/architecture/apps/images.md for image generation flow

import logging
import base64
import os
import io
import json
import re
import hashlib
from fastapi import APIRouter, HTTPException, Request, Depends, Query
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

router = APIRouter(prefix="/v1/embeds", tags=["Embeds"])


# --- Dependencies to get services from app.state ---

def get_directus_service(request: Request) -> DirectusService:
    """Get DirectusService from app state."""
    if not hasattr(request.app.state, 'directus_service'):
        logger.error("DirectusService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    """Get EncryptionService from app state."""
    if not hasattr(request.app.state, 'encryption_service'):
        logger.error("EncryptionService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.encryption_service


def get_s3_service(request: Request) -> S3UploadService:
    """Get S3UploadService from app state."""
    if not hasattr(request.app.state, 's3_service'):
        logger.error("S3UploadService not found in app.state")
        raise HTTPException(status_code=500, detail="Internal configuration error")
    return request.app.state.s3_service


def _hash_value(value: str) -> str:
    """Create SHA256 hash of a value for privacy protection."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _generate_filename_from_prompt(prompt: str | None, extension: str = "png") -> str:
    """
    Generate a clean, human-readable filename from an image generation prompt.

    Rules:
    - Lowercase, words separated by underscores
    - Only alphanumeric characters and underscores
    - Truncated to ~60 characters at a word boundary
    - Prefixed with "openmates_" for brand recognition
    - Falls back to "openmates_generated_image" if prompt is empty

    Args:
        prompt: The image generation prompt text
        extension: File extension without dot (e.g. "png", "webp")

    Returns:
        A sanitized filename string like "openmates_a_cat_sitting_on_a_windowsill.png"
    """
    if not prompt or not prompt.strip():
        return f"openmates_generated_image.{extension}"

    # Normalize: lowercase, replace non-alphanumeric with spaces, collapse whitespace
    slug = re.sub(r'[^a-z0-9\s]', ' ', prompt.lower())
    slug = re.sub(r'\s+', ' ', slug).strip()

    # Truncate to ~60 chars at a word boundary
    if len(slug) > 60:
        slug = slug[:60]
        last_space = slug.rfind(' ')
        if last_space > 20:
            slug = slug[:last_space]

    # Replace spaces with underscores, remove trailing underscores
    slug = slug.replace(' ', '_').rstrip('_')

    if not slug:
        return f"openmates_generated_image.{extension}"

    return f"openmates_{slug}.{extension}"


@router.get("/{embed_id}/file")
@limiter.limit("60/minute")
async def download_embed_file(
    embed_id: str,
    request: Request,
    format: str = Query("preview", description="File format to download: preview, full, or original"),
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    s3_service: S3UploadService = Depends(get_s3_service)
):
    """
    Download a file from an embed.
    
    This endpoint is used to download files from embeds, such as generated images.
    The server decrypts the file using Vault and returns the plaintext content.
    
    Args:
        embed_id: The unique identifier of the embed
        format: The file format to download (preview, full, or original)
                - preview: Scaled-down version for thumbnails (600x400)
                - full: Full-resolution WEBP for web display
                - original: Original PNG from provider
    
    Returns:
        StreamingResponse with the decrypted file content
    
    Raises:
        404: Embed not found or user doesn't have access
        400: Invalid format or embed doesn't contain files
        500: Decryption or download error
    """
    user_id = current_user.id
    hashed_user_id = _hash_value(user_id)
    log_prefix = f"[Embed: {embed_id[:8]}...]"
    
    logger.info(f"{log_prefix} Download request for format '{format}' by user {user_id[:8]}...")
    
    # Validate format parameter
    valid_formats = {"preview", "full", "original"}
    if format not in valid_formats:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid format '{format}'. Must be one of: {', '.join(valid_formats)}"
        )
    
    try:
        # 1. Fetch embed from Directus
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed:
            logger.warning(f"{log_prefix} Embed not found")
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 2. Verify user ownership
        embed_hashed_user_id = embed.get("hashed_user_id")
        if embed_hashed_user_id != hashed_user_id:
            logger.warning(f"{log_prefix} Access denied: user hash mismatch")
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 3. Check encryption mode
        encryption_mode = embed.get("encryption_mode", "client")
        if encryption_mode != "vault":
            # For client-encrypted embeds, the server CANNOT decrypt the content.
            # (Note: Standard file uploads use a different flow, this router is for server-side files)
            raise HTTPException(
                status_code=400, 
                detail="This embed is client-side encrypted. The server cannot decrypt its files."
            )
        
        # 4. Get user's vault_key_id for decryption
        # Prefer the ID stored in the embed itself, fallback to user profile
        vault_key_id = embed.get("vault_key_id")
        if not vault_key_id:
            # get_user_profile returns (success, data, error_msg)
            success, user_profile, error_msg = await directus_service.get_user_profile(user_id)
            if not success or not user_profile:
                logger.error(f"{log_prefix} User profile not found: {error_msg}")
                raise HTTPException(status_code=500, detail="User profile not found")
            vault_key_id = user_profile.get("vault_key_id")
            
        if not vault_key_id:
            logger.error(f"{log_prefix} Vault key ID not found for user")
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # 5. Decrypt embed content using Vault
        encrypted_content = embed.get("encrypted_content")
        if not encrypted_content:
            logger.warning(f"{log_prefix} Embed has no encrypted_content")
            raise HTTPException(status_code=400, detail="Embed does not contain file data")
        
        decrypted_content_str = await encryption_service.decrypt_with_user_key(
            encrypted_content, vault_key_id
        )
        if not decrypted_content_str:
            logger.error(f"{log_prefix} Failed to decrypt embed content")
            raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
        
        # 5. Parse embed content JSON
        try:
            embed_content = json.loads(decrypted_content_str)
        except json.JSONDecodeError as e:
            logger.error(f"{log_prefix} Failed to parse embed content JSON: {e}")
            raise HTTPException(status_code=500, detail="Invalid embed content format")
        
        # 6. Verify this is a file-containing embed
        embed_type = embed_content.get("type")
        if embed_type != "image":
            logger.warning(f"{log_prefix} Embed type '{embed_type}' does not support file downloads")
            raise HTTPException(status_code=400, detail="This embed type does not contain downloadable files")
        
        files = embed_content.get("files")
        if not files:
            logger.warning(f"{log_prefix} Embed has no files metadata")
            raise HTTPException(status_code=400, detail="Embed does not contain file data")
        
        # 7. Get file metadata for requested format
        file_metadata = files.get(format)
        if not file_metadata:
            available_formats = list(files.keys())
            logger.warning(f"{log_prefix} Format '{format}' not found. Available: {available_formats}")
            raise HTTPException(
                status_code=400, 
                detail=f"Format '{format}' not available. Available formats: {', '.join(available_formats)}"
            )
        
        s3_key = file_metadata.get("s3_key")
        file_format = file_metadata.get("format", "webp")
        
        if not s3_key:
            logger.error(f"{log_prefix} No S3 key in file metadata for format '{format}'")
            raise HTTPException(status_code=500, detail="File storage reference missing")
        
        # 8. Get AES key and nonce for file decryption
        encrypted_aes_key = embed_content.get("encrypted_aes_key")
        aes_nonce_b64 = embed_content.get("aes_nonce")
        
        if not encrypted_aes_key or not aes_nonce_b64:
            logger.error(f"{log_prefix} Missing AES encryption data in embed content")
            raise HTTPException(status_code=500, detail="File encryption data missing")
        
        # 9. Decrypt AES key using Vault
        aes_key_b64 = await encryption_service.decrypt_with_user_key(
            encrypted_aes_key, vault_key_id
        )
        if not aes_key_b64:
            logger.error(f"{log_prefix} Failed to decrypt AES key")
            raise HTTPException(status_code=500, detail="Failed to decrypt file access key")
        
        # 10. Download encrypted file from S3
        bucket_name = get_bucket_name('chatfiles', os.getenv('SERVER_ENVIRONMENT', 'development'))
        logger.info(f"{log_prefix} Downloading from S3: {s3_key}")
        
        encrypted_data = await s3_service.get_file(bucket_name=bucket_name, object_key=s3_key)
        if not encrypted_data:
            logger.error(f"{log_prefix} File not found in S3: {s3_key}")
            raise HTTPException(status_code=404, detail="File not found in storage")
        
        # 11. Decrypt file content
        try:
            aes_key = base64.b64decode(aes_key_b64)
            nonce = base64.b64decode(aes_nonce_b64)
            aesgcm = AESGCM(aes_key)
            decrypted_content = aesgcm.decrypt(nonce, encrypted_data, None)
        except Exception as e:
            logger.error(f"{log_prefix} File decryption failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to decrypt file content")
        
        # 12. Determine content type and filename
        content_type = "image/png" if file_format == "png" else "image/webp"
        
        # Generate a human-readable filename from the prompt (if available in embed content)
        embed_prompt = embed_content.get("prompt")
        filename = _generate_filename_from_prompt(embed_prompt, file_format)
        
        logger.info(f"{log_prefix} Successfully decrypted {len(decrypted_content)} bytes, serving as {content_type}")
        
        # 13. Stream response to client
        # Use "attachment" disposition so browsers trigger a download with the proper filename.
        # Quote the filename per RFC 6266 for safety with special characters.
        return StreamingResponse(
            io.BytesIO(decrypted_content),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, max-age=3600"  # Cache for 1 hour
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error during file download: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during file download")


@router.get("/{embed_id}/content")
@limiter.limit("60/minute")
async def get_embed_content(
    embed_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service)
):
    """
    Get the decrypted content (metadata) of an embed.
    
    For embeds with encryption_mode='vault', this endpoint allows the client to
    fetch the decrypted JSON metadata (like the prompt for a generated image).
    
    Args:
        embed_id: The unique identifier of the embed
        
    Returns:
        The decrypted embed content as a JSON object
    """
    user_id = current_user.id
    hashed_user_id = _hash_value(user_id)
    log_prefix = f"[Embed: {embed_id[:8]}...]"
    
    try:
        # 1. Fetch embed from Directus
        embed = await directus_service.embed.get_embed_by_id(embed_id)
        if not embed:
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 2. Verify user ownership
        if embed.get("hashed_user_id") != hashed_user_id:
            raise HTTPException(status_code=404, detail="Embed not found")
        
        # 3. Check encryption mode
        encryption_mode = embed.get("encryption_mode", "client")
        if encryption_mode != "vault":
            # For client-encrypted embeds, the server CANNOT decrypt the content.
            # The client must use the embed_key from the embed_keys collection.
            raise HTTPException(
                status_code=400, 
                detail="This embed is client-side encrypted. The server cannot decrypt its content."
            )
        
        # 4. Get user's vault_key_id for decryption
        # Prefer the ID stored in the embed itself, fallback to user profile
        vault_key_id = embed.get("vault_key_id")
        if not vault_key_id:
            success, user_profile, error_msg = await directus_service.get_user_profile(user_id)
            if not success or not user_profile:
                logger.error(f"{log_prefix} User profile not found: {error_msg}")
                raise HTTPException(status_code=500, detail="User profile not found")
            vault_key_id = user_profile.get("vault_key_id")
            
        if not vault_key_id:
            raise HTTPException(status_code=500, detail="User encryption key not found")
        
        # 5. Decrypt embed content using Vault
        encrypted_content = embed.get("encrypted_content")
        if not encrypted_content:
            raise HTTPException(status_code=400, detail="Embed does not contain content")
        
        decrypted_content_str = await encryption_service.decrypt_with_user_key(
            encrypted_content, vault_key_id
        )
        if not decrypted_content_str:
            raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
        
        # 6. Parse and return
        try:
            return json.loads(decrypted_content_str)
        except json.JSONDecodeError:
            return {"raw_content": decrypted_content_str}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{log_prefix} Error getting decrypted embed content: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to decrypt embed content")
