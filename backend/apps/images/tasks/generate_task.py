# backend/apps/images/tasks/generate_task.py
#
# Celery task for image generation.
# Handles provider API calls, image processing, encryption, S3 upload, and embed creation.
#
# Architecture:
# - Every generated image is stored as an embed (see docs/architecture/apps/images.md)
# - Embed content contains S3 references, Vault-wrapped AES key, and metadata
# - Download via GET /v1/embeds/{embed_id}/file?format=preview|full|original
# - Server decrypts using Vault and streams plaintext image to client

import logging
import asyncio
import uuid
import json
import hashlib
import base64
import os
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from io import BytesIO

from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.image_processing import process_image_for_storage
from backend.shared.providers.google.gemini_image import generate_image_google
from backend.shared.providers.fal.flux import generate_image_fal_flux
from backend.core.api.app.services.s3.config import get_bucket_name

logger = logging.getLogger(__name__)


def _get_image_dimensions(image_bytes: bytes) -> Tuple[int, int]:
    """Extract width and height from image bytes using PIL."""
    try:
        img = Image.open(BytesIO(image_bytes))
        return img.size  # Returns (width, height)
    except Exception as e:
        logger.warning(f"Failed to get image dimensions: {e}")
        return (0, 0)


def _hash_value(value: str) -> str:
    """Create SHA256 hash of a value for privacy protection."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@app.task(
    bind=True,
    name="apps.images.tasks.skill_generate",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=180,
    time_limit=210
)
def generate_image_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    """
    Celery task for high-end image generation.
    """
    return asyncio.run(_async_generate_image(self, app_id, skill_id, arguments))


@app.task(
    bind=True,
    name="apps.images.tasks.skill_generate_draft",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=180,
    time_limit=210
)
def generate_image_draft_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    """
    Celery task for draft image generation.
    """
    return asyncio.run(_async_generate_image(self, app_id, skill_id, arguments))


async def _async_generate_image(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]):
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    logger.info(f"{log_prefix} Starting image generation task for {app_id}/{skill_id}")
    
    try:
        # 1. Initialize services (S3, Secrets, Encryption, Directus)
        await task.initialize_services()
        
        # 2. Extract arguments
        prompt = arguments.get("prompt")
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        aspect_ratio = arguments.get("aspect_ratio", "1:1")
        model_ref = arguments.get("full_model_reference")
        
        if not prompt or not user_id:
            raise ValueError(f"Missing required arguments: prompt={bool(prompt)}, user_id={bool(user_id)}")

        # 3. Get embed_id from arguments (passed by the skill) or generate new one
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        logger.info(f"{log_prefix} Using embed_id: {embed_id}")

        # 4. Call Provider API
        logger.info(f"{log_prefix} Calling provider for model: {model_ref}")
        image_bytes = None
        actual_model = model_ref or "Unknown AI"
        
        if model_ref and "google" in model_ref:
            model_id = model_ref.split('/')[-1] if "/" in model_ref else model_ref
            image_bytes = await generate_image_google(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                aspect_ratio=aspect_ratio,
                model_id=model_id
            )
            actual_model = f"Google {model_id}"
        elif model_ref and ("bfl" in model_ref or "flux" in model_ref):
            # Map model ref to fal.ai model ID
            # bfl/flux-schnell -> fal-ai/flux-2/klein/9b/base
            fal_model_id = "fal-ai/flux-2/klein/9b/base" 
            if "pro" in model_ref:
                fal_model_id = "fal-ai/flux-pro/v1.1"
                
            image_bytes = await generate_image_fal_flux(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=fal_model_id
            )
            actual_model = f"fal.ai {fal_model_id}"
        else:
            # Fallback to draft if not specified or unknown
            logger.warning(f"{log_prefix} Unknown or missing model reference '{model_ref}', falling back to FLUX.2 Klein")
            fal_model_id = "fal-ai/flux-2/klein/9b/base"
            image_bytes = await generate_image_fal_flux(
                prompt=prompt,
                secrets_manager=task._secrets_manager,
                model_id=fal_model_id
            )
            actual_model = f"fal.ai {fal_model_id} (fallback)"

        if not image_bytes:
            raise Exception("Provider returned empty image data")

        # Update model_ref to the actual model used for the rest of the task
        model_ref = actual_model

        # 5. Get original image dimensions
        original_width, original_height = _get_image_dimensions(image_bytes)
        logger.info(f"{log_prefix} Original image dimensions: {original_width}x{original_height}")

        # 6. Process image (Original + Full WEBP + Preview WEBP)
        logger.info(f"{log_prefix} Processing image into multiple formats...")
        
        # Prepare metadata for labeling (no visible text, just invisible standard metadata)
        labeling_metadata = {
            "prompt": prompt,
            "model": model_ref,
            "software": "OpenMates",
            "source": "OpenMates AI",
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        processed_images = process_image_for_storage(image_bytes, metadata=labeling_metadata)
        
        # 7. Hybrid Encryption Setup
        # Fetch user profile to get vault_key_id
        # get_user_profile returns (success, data, error_msg)
        result = await task._directus_service.get_user_profile(user_id)
        
        # Robust unpacking of (success, data, error_msg)
        success = False
        user_profile = None
        error_msg = "Unknown error"
        
        if isinstance(result, tuple):
            if len(result) >= 2:
                success = result[0]
                user_profile = result[1]
            if len(result) >= 3:
                error_msg = result[2]
        else:
            # Fallback if it somehow returned just the profile
            success = True
            user_profile = result
            
        if not success or not user_profile or not isinstance(user_profile, dict):
            raise Exception(f"User profile not found or invalid for {user_id}: {error_msg}")
            
        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            raise Exception(f"Vault key ID not found for user {user_id}")
            
        # Generate local symmetric key for this set of images
        aes_key = os.urandom(32)  # AES-256
        nonce = os.urandom(12)    # GCM nonce
        aesgcm = AESGCM(aes_key)
        
        # Wrap the local AES key using Vault
        aes_key_b64 = base64.b64encode(aes_key).decode('utf-8')
        encrypted_aes_key_vault, _ = await task._encryption_service.encrypt_with_user_key(
            aes_key_b64, vault_key_id
        )
        if not encrypted_aes_key_vault:
            raise Exception("Failed to wrap AES key with Vault")
            
        nonce_b64 = base64.b64encode(nonce).decode('utf-8')
        
        # 8. Encrypt and Upload each version to S3, collect file metadata
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        files_metadata = {}
        
        # Map internal format keys to public format names
        format_mapping = {
            "original": "original",
            "full_webp": "full",
            "preview_webp": "preview"
        }
        
        for format_key, content in processed_images.items():
            # Encrypt content locally using the same key/nonce for all versions
            encrypted_payload = aesgcm.encrypt(nonce, content, None)
            
            # Generate S3 key: user_id/timestamp_id_format.ext
            ext = "png" if format_key == "original" else "webp"
            file_key = f"{user_id}/{timestamp}_{unique_id}_{format_key}.{ext}"
            
            logger.info(f"{log_prefix} Uploading {format_key} version to S3 (chatfiles): {file_key}")
            
            # Upload to 'chatfiles' bucket
            upload_result = await task._s3_service.upload_file(
                bucket_key='chatfiles',
                file_key=file_key,
                content=encrypted_payload,
                content_type='application/octet-stream'
            )
            
            if not upload_result.get('url'):
                raise Exception(f"Failed to upload {format_key} image to S3")
            
            # Get dimensions for this format
            width, height = _get_image_dimensions(content)
            
            # Store file metadata with public format name
            public_format = format_mapping.get(format_key, format_key)
            files_metadata[public_format] = {
                "s3_key": file_key,
                "width": width,
                "height": height,
                "size_bytes": len(content),
                "format": "png" if format_key == "original" else "webp"
            }

        # 9. Prepare embed content for client-side storage
        # 
        # HYBRID ENCRYPTION MODEL:
        # - The embed CONTENT (below) is sent as PLAINTEXT TOON via WebSocket.
        #   The client encrypts it with the chat's master key before storing (standard flow).
        # - The AES key for S3 image decryption is included IN the embed content (plaintext).
        #   Since embed content is client-encrypted, the AES key is protected at rest.
        # - The Vault-wrapped AES key is stored separately for server-side LLM vision inference.
        #   The server can unwrap it via Vault to decrypt images when needed for vision LLMs.
        #
        # CLIENT FLOW:
        # 1. Client receives send_embed_data with plaintext TOON content
        # 2. Client encrypts content with chat master key and stores in IndexedDB
        # 3. To render image: client decodes TOON → extracts aes_key + s3_key →
        #    fetches encrypted blob from S3 → decrypts with AES-256-GCM → renders
        generated_at = datetime.now(timezone.utc).isoformat()
        
        # Build S3 base URL for the chatfiles bucket so the frontend can construct full URLs
        # Format: https://{bucket_name}.{region}.your-objectstorage.com
        chatfiles_bucket = get_bucket_name('chatfiles')
        s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"
        
        embed_content = {
            "app_id": "images",
            "skill_id": skill_id,
            "type": "image",
            "status": "finished",
            "files": files_metadata,
            "s3_base_url": s3_base_url,     # Base URL for constructing full S3 file URLs
            "aes_key": aes_key_b64,         # Plaintext AES key for client-side S3 decryption
            "aes_nonce": nonce_b64,          # GCM nonce shared across all image formats
            "vault_wrapped_aes_key": encrypted_aes_key_vault,  # For server-side LLM vision access
            "prompt": prompt,
            "model": model_ref,
            "aspect_ratio": aspect_ratio,
            "generated_at": generated_at
        }
        
        # 9b. Cache S3 file keys for server-side cleanup (S3 deletion on chat/embed deletion)
        # Since embed content is client-encrypted (zero-knowledge), the server can't extract
        # S3 keys from encrypted_content. We cache them here so that store_embed_handler
        # can persist them as server-accessible metadata on the Directus embed record.
        s3_file_keys = [
            {"bucket": "chatfiles", "key": meta["s3_key"]}
            for meta in files_metadata.values()
        ]
        
        try:
            client = await task._cache_service.client
            if client:
                s3_keys_cache_key = f"embed:{embed_id}:s3_file_keys"
                await client.set(s3_keys_cache_key, json.dumps(s3_file_keys), ex=3600)  # 1 hour TTL
                logger.info(f"{log_prefix} Cached {len(s3_file_keys)} S3 file keys for embed {embed_id}")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to cache S3 file keys for embed {embed_id}: {e}")
        
        # 10. Encode embed content as TOON for WebSocket delivery
        # TOON is the standard format used by the embed system for efficient encoding
        from toon_format import encode as toon_encode
        content_toon = toon_encode(embed_content)
        logger.info(f"{log_prefix} TOON-encoded embed content: {len(content_toon)} chars")
        
        # 11. Send embed data to client via WebSocket (standard client-encryption flow)
        # The client will:
        # 1. Receive plaintext TOON content
        # 2. Encrypt with chat master key (AES-256-GCM)
        # 3. Store encrypted in IndexedDB
        # 4. Send encrypted version back to server for Directus persistence
        now_ts = int(datetime.now(timezone.utc).timestamp())
        hashed_user_id = _hash_value(user_id)
        
        # Use EmbedService.send_embed_data_to_client for standard WebSocket delivery
        from backend.core.api.app.services.embed_service import EmbedService
        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service
        )
        
        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="app_skill_use",  # Standard embed type for skill results
            content_toon=content_toon,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=hashed_user_id,
            status="finished",
            encryption_mode="client",  # Client-side encryption (standard flow)
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=log_prefix,
            check_cache_status=False  # Skip dedup check - we know this is the first "finished" event
        )
        
        # 12. NOTE: embed_update event is NO LONGER published here.
        # The send_embed_data_to_client() call above (step 11) already delivers all content
        # the frontend needs (plaintext TOON for client-side encryption, status, metadata).
        # Publishing an additional embed_update causes the frontend to process the same embed
        # twice, resulting in "DUPLICATE DETECTED" warnings and redundant work.
        # The frontend's handleSendEmbedDataImpl handles the processing -> finished transition.

        # 13. Prepare result for API response
        # This is what gets returned via task polling and REST API
        result_data = {
            "embed_id": embed_id,
            "type": "image",
            "status": "finished",
            "files": {
                # Return file metadata without S3 keys (clients use embed_id to download)
                format_name: {
                    "width": meta["width"],
                    "height": meta["height"],
                    "size_bytes": meta["size_bytes"],
                    "format": meta["format"]
                }
                for format_name, meta in files_metadata.items()
            },
            "prompt": prompt,
            "model": model_ref,
            "aspect_ratio": aspect_ratio,
            "generated_at": generated_at
        }
        
        logger.info(f"{log_prefix} Image generation task completed successfully. Embed ID: {embed_id}")
        return result_data

    except Exception as e:
        logger.error(f"{log_prefix} Image generation task failed: {e}", exc_info=True)
        # Re-raising allows Celery to mark the task as FAILED
        raise
    finally:
        # CRITICAL: Always cleanup services to close httpx client and prevent event loop issues
        await task.cleanup_services()


async def _encrypt_type_with_vault(task: BaseServiceTask, embed_type: str, vault_key_id: str) -> str:
    """
    Encrypt the embed type using Vault.
    
    For server-generated embeds, the type is Vault-encrypted rather than client-encrypted.
    The download endpoint knows to decrypt with Vault for these embeds.
    """
    encrypted_type, _ = await task._encryption_service.encrypt_with_user_key(
        embed_type, vault_key_id
    )
    if not encrypted_type:
        raise Exception("Failed to encrypt embed type with Vault")
    return encrypted_type
