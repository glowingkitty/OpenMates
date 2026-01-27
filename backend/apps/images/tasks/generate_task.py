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

        # 9. Prepare embed content (will be stored Vault-encrypted in Directus)
        # This content contains all data needed for the download endpoint
        embed_content = {
            "type": "image",
            "files": files_metadata,
            "encrypted_aes_key": encrypted_aes_key_vault,
            "aes_nonce": nonce_b64,
            "prompt": prompt,
            "model": model_ref,
            "aspect_ratio": aspect_ratio,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # 10. Encrypt embed content with Vault for storage
        embed_content_json = json.dumps(embed_content)
        encrypted_content, _ = await task._encryption_service.encrypt_with_user_key(
            embed_content_json, vault_key_id
        )
        if not encrypted_content:
            raise Exception("Failed to encrypt embed content with Vault")
        
        # 11. Create embed in Directus
        now_ts = int(datetime.now(timezone.utc).timestamp())
        hashed_user_id = _hash_value(user_id)
        hashed_task_id = _hash_value(task_id)
        
        embed_data = {
            "embed_id": embed_id,
            "hashed_user_id": hashed_user_id,
            "hashed_task_id": hashed_task_id,
            "status": "finished",
            "encrypted_content": encrypted_content,
            # encrypted_type is normally client-encrypted, but for server-generated
            # embeds we store it Vault-encrypted.
            "encrypted_type": await _encrypt_type_with_vault(task, "image", vault_key_id),
            "encryption_mode": "vault",
            "vault_key_id": vault_key_id,
            "is_private": False,
            "is_shared": False,
            "created_at": now_ts,
            "updated_at": now_ts
        }
        
        # Add chat/message context if available (for web app flow)
        if chat_id:
            embed_data["hashed_chat_id"] = _hash_value(chat_id)
        if message_id:
            embed_data["hashed_message_id"] = _hash_value(message_id)
        
        created_embed = await task._directus_service.embed.create_embed(embed_data)
        if not created_embed:
            raise Exception("Failed to create embed in Directus")
        
        logger.info(f"{log_prefix} Created embed {embed_id} in Directus")
        
        # 12. Notify client via WebSocket (for web app flow)
        # For Vault-encrypted embeds, we send the decrypted content so the client
        # can render the preview immediately without calling the /content endpoint
        await task.publish_websocket_event(
            user_id_hash=hashed_user_id,
            event="send_embed_data",
            payload={
                "embed_id": embed_id,
                "type": "image",
                "content": json.dumps(embed_content),  # Convert to JSON string
                "status": "finished",
                "chat_id": chat_id,
                "message_id": message_id,
                "user_id": user_id,
                "encryption_mode": "vault",
                "vault_key_id": vault_key_id,
                "createdAt": now_ts,
                "updatedAt": now_ts
            }
        )

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
            "generated_at": embed_content["generated_at"]
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
