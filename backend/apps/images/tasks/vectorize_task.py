# backend/apps/images/tasks/vectorize_task.py
#
# Celery task for image vectorization (raster PNG/JPG/WEBP → SVG).
# Uses the Recraft /v1/images/vectorize endpoint ($0.01/request, 15 credits charged).
#
# Architecture:
# - Receives an embed_id pointing to a user-uploaded raster image
# - Decrypts the source image from embed cache (same pipeline as generate_task.py)
# - Calls Recraft vectorize API to convert raster → SVG
# - Stores the SVG result as a new embed (same encryption + S3 pipeline as generate)
# - Charges 15 credits via the billing internal API
# - Sends the finished embed to the client via WebSocket

import logging
import asyncio
import uuid
import json
import hashlib
import base64
import os
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
from io import BytesIO

import httpx
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.utils.image_processing import process_svg_for_storage
from backend.shared.providers.recraft.recraft import vectorize_image_recraft
from backend.core.api.app.services.s3.config import get_bucket_name

logger = logging.getLogger(__name__)

# Internal API configuration for billing calls
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


def _hash_value(value: str) -> str:
    """Create SHA256 hash of a value for privacy protection."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _charge_vectorize_credits(
    user_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    model_ref: str,
    chat_id: Optional[str],
    message_id: Optional[str],
    log_prefix: str,
) -> None:
    """
    Charge a flat per-image credit fee for a successful vectorization.

    Fetches the provider pricing config via internal API and charges 1 unit
    (= 1 image). Pricing is defined in recraft.yml as 15 credits for
    recraft/vectorize.

    Billing is non-blocking: failures are logged but don't break SVG delivery.
    """
    try:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN

        # Fetch provider model pricing via internal API
        pricing_config = None
        if model_ref and "/" in model_ref:
            provider_id, model_suffix = model_ref.split("/", 1)
            endpoint = (
                f"{INTERNAL_API_BASE_URL}/internal/config/"
                f"provider_model_pricing/{provider_id}/{model_suffix}"
            )

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint, headers=headers)
                if response.status_code == 200:
                    pricing_config = response.json()
                    logger.info(
                        f"{log_prefix} Fetched pricing config for '{model_ref}': {pricing_config}"
                    )
                else:
                    logger.warning(
                        f"{log_prefix} Failed to fetch pricing for '{model_ref}': "
                        f"{response.status_code}"
                    )

        # Calculate credits: flat fee per image (1 unit = 1 image)
        from backend.shared.python_utils.billing_utils import (
            calculate_total_credits,
            MINIMUM_CREDITS_CHARGED,
        )

        if pricing_config:
            credits_charged = calculate_total_credits(
                pricing_config=pricing_config, units_processed=1
            )
        else:
            credits_charged = MINIMUM_CREDITS_CHARGED
            logger.warning(
                f"{log_prefix} No pricing config for '{model_ref}', "
                f"using minimum charge: {credits_charged}"
            )

        if credits_charged <= 0:
            logger.debug(f"{log_prefix} Calculated credits is 0, skipping billing.")
            return

        # Resolve provider info (name + region) for usage tracking
        resolved_provider_name = None
        resolved_region = None
        if model_ref and "/" in model_ref:
            try:
                info_provider_id = model_ref.split("/", 1)[0]
                model_ref_param = f"?model_ref={model_ref}"
                info_url = (
                    f"{INTERNAL_API_BASE_URL}/internal/config/"
                    f"provider_info/{info_provider_id}{model_ref_param}"
                )
                async with httpx.AsyncClient(timeout=10.0) as info_client:
                    info_resp = await info_client.get(info_url, headers=headers)
                    if info_resp.status_code == 200:
                        provider_info = info_resp.json()
                        resolved_provider_name = provider_info.get("name")
                        resolved_region = provider_info.get("region")
            except Exception as e:
                logger.warning(
                    f"{log_prefix} Failed to fetch provider info for '{model_ref}': {e}"
                )

        charge_payload = {
            "user_id": user_id,
            "user_id_hash": user_id_hash,
            "credits": credits_charged,
            "skill_id": skill_id,
            "app_id": app_id,
            "usage_details": {
                "chat_id": chat_id,
                "message_id": message_id,
                "units_processed": 1,
                "model_used": model_ref,
                "server_provider": resolved_provider_name,
                "server_region": resolved_region,
            },
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            logger.info(
                f"{log_prefix} Charging {credits_charged} credits for "
                f"'{app_id}.{skill_id}' (model: {model_ref})"
            )
            response = await client.post(url, json=charge_payload, headers=headers)
            response.raise_for_status()
            logger.info(
                f"{log_prefix} Successfully charged {credits_charged} credits "
                f"for '{app_id}.{skill_id}'"
            )

    except httpx.HTTPStatusError as e:
        logger.error(
            f"{log_prefix} HTTP error charging credits for '{app_id}.{skill_id}': "
            f"{e.response.status_code} - {e.response.text}",
            exc_info=True,
        )
        # Don't raise — billing failure shouldn't break SVG delivery
    except Exception as e:
        logger.error(
            f"{log_prefix} Error charging credits for '{app_id}.{skill_id}': {e}",
            exc_info=True,
        )
        # Don't raise — billing failure shouldn't break SVG delivery


async def _decrypt_source_image(
    embed_id: str,
    user_vault_key_id: str,
    log_prefix: str,
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Fetch and decrypt a source image from the Redis embed cache.

    Replicates the same decryption pipeline used in generate_task.py's
    _decrypt_reference_images, but for a single image. Returns the decrypted
    image bytes and detected MIME type.

    Args:
        embed_id:          UUID of the embed containing the source image.
        user_vault_key_id: The user's Vault Transit key ID for decryption.
        log_prefix:        Log prefix for contextual logging.

    Returns:
        Tuple of (image_bytes, mime_type). Both are None if decryption fails.
    """
    from urllib.parse import quote as url_quote
    from toon_format import decode as toon_decode
    import redis.asyncio as aioredis

    vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
    vault_token_path = "/vault-data/api.token"
    try:
        with open(vault_token_path, "r") as f:
            vault_token = f.read().strip()
    except Exception as e:
        logger.error(f"{log_prefix} Failed to read Vault token: {e}", exc_info=True)
        return None, None

    redis_password = os.environ.get("DRAGONFLY_PASSWORD", "")
    redis_url = f"redis://default:{url_quote(redis_password, safe='')}@cache:6379/0"
    redis_client = aioredis.from_url(redis_url, decode_responses=True)

    embed_log = f"{log_prefix} [source_embed:{embed_id[:8]}...]"

    try:
        # Step 1: Fetch embed JSON from Redis
        embed_json = await redis_client.get(f"embed:{embed_id}")
        if not embed_json:
            logger.warning(
                f"{embed_log} Source embed not found in cache — "
                "it may have expired (24h TTL)."
            )
            return None, None

        embed_data = json.loads(embed_json)
        encrypted_content = embed_data.get("encrypted_content")
        if not encrypted_content:
            logger.warning(f"{embed_log} Source embed has no encrypted_content.")
            return None, None

        # Step 2: Decrypt embed content via Vault Transit
        context = base64.b64encode(user_vault_key_id.encode()).decode("utf-8")
        decrypt_url = f"{vault_url}/v1/transit/decrypt/{user_vault_key_id}"
        payload = {"ciphertext": encrypted_content, "context": context}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                decrypt_url,
                json=payload,
                headers={"X-Vault-Token": vault_token},
            )

        if resp.status_code != 200:
            logger.warning(
                f"{embed_log} Vault decrypt failed: HTTP {resp.status_code}."
            )
            return None, None

        plaintext_b64 = resp.json()["data"]["plaintext"]
        plaintext_toon = base64.b64decode(plaintext_b64).decode("utf-8")

        # Step 3: Decode TOON → content dict
        content = toon_decode(plaintext_toon)
        if not isinstance(content, dict):
            logger.warning(f"{embed_log} TOON decoded to unexpected type.")
            return None, None

        vault_wrapped_aes_key = content.get("vault_wrapped_aes_key")
        s3_base_url = content.get("s3_base_url")
        aes_nonce_b64 = content.get("aes_nonce")
        files = content.get("files", {})

        if not vault_wrapped_aes_key or not s3_base_url or not aes_nonce_b64:
            logger.warning(
                f"{embed_log} Source embed missing required encryption fields."
            )
            return None, None

        # Step 3b: Unwrap AES key via Vault Transit
        unwrap_payload = {
            "ciphertext": vault_wrapped_aes_key,
            "context": context,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            unwrap_resp = await client.post(
                decrypt_url,
                json=unwrap_payload,
                headers={"X-Vault-Token": vault_token},
            )

        if unwrap_resp.status_code != 200:
            logger.warning(
                f"{embed_log} Vault AES key unwrap failed: HTTP {unwrap_resp.status_code}."
            )
            return None, None

        # Double-decode: Vault plaintext = base64(aes_key_b64)
        aes_key_b64 = base64.b64decode(
            unwrap_resp.json()["data"]["plaintext"]
        ).decode("utf-8")
        aes_key_bytes = base64.b64decode(aes_key_b64)

        # Step 4: Select best variant for vectorization input.
        # Prefer "original" (highest quality) for vectorization since accuracy matters.
        # Fall back through full → preview if original isn't available.
        s3_key = None
        detected_format = "png"
        for variant_name in ("original", "full", "preview"):
            variant = files.get(variant_name)
            if variant and variant.get("s3_key"):
                s3_key = variant["s3_key"]
                detected_format = variant.get("format", "png")
                logger.info(
                    f"{embed_log} Using '{variant_name}' variant: {s3_key}"
                )
                break

        if not s3_key:
            logger.warning(f"{embed_log} No file variant found for source embed.")
            return None, None

        # Step 4b: Download encrypted image from S3
        full_url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        async with httpx.AsyncClient(timeout=60) as client:
            s3_resp = await client.get(full_url)

        if s3_resp.status_code != 200:
            logger.warning(
                f"{embed_log} S3 download failed: HTTP {s3_resp.status_code}."
            )
            return None, None

        # Step 5: AES-256-GCM decrypt
        nonce_bytes = base64.b64decode(aes_nonce_b64)
        aesgcm = AESGCM(aes_key_bytes)
        plaintext_bytes = aesgcm.decrypt(nonce_bytes, s3_resp.content, None)

        # Map format to MIME type
        format_to_mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }
        mime_type = format_to_mime.get(detected_format, "image/png")

        logger.info(
            f"{embed_log} Decrypted source image: {len(plaintext_bytes)} bytes "
            f"(MIME: {mime_type})"
        )
        return plaintext_bytes, mime_type

    except Exception as e:
        logger.error(
            f"{embed_log} Failed to decrypt source image: {e}",
            exc_info=True,
        )
        return None, None
    finally:
        await redis_client.aclose()


@app.task(
    bind=True,
    name="apps.images.tasks.skill_vectorize",
    base=BaseServiceTask,
    queue="app_images",
    soft_time_limit=180,
    time_limit=210,
)
def vectorize_image_task(
    self, app_id: str, skill_id: str, arguments: Dict[str, Any]
):
    """
    Celery task for raster-to-SVG image vectorization via Recraft.
    """
    return asyncio.run(_async_vectorize_image(self, app_id, skill_id, arguments))


async def _async_vectorize_image(
    task: BaseServiceTask,
    app_id: str,
    skill_id: str,
    arguments: Dict[str, Any],
):
    """
    Async implementation of the vectorize task.

    Flow:
    1. Decrypt the source image from the referenced embed
    2. Call Recraft vectorize API (raster → SVG)
    3. Process + encrypt the SVG result
    4. Upload to S3
    5. Charge 15 credits
    6. Send the finished embed to the client via WebSocket
    """
    task_id = task.request.id
    log_prefix = f"[Task ID: {task_id}]"
    logger.info(f"{log_prefix} Starting vectorize task for {app_id}/{skill_id}")

    try:
        # 1. Initialize services (S3, Secrets, Encryption, Directus)
        await task.initialize_services()

        # 2. Extract arguments
        user_id = arguments.get("user_id")
        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        source_image_embed_id = arguments.get("source_image_embed_id")
        user_vault_key_id: Optional[str] = arguments.get("user_vault_key_id")

        if not user_id:
            raise ValueError("Missing required argument: user_id")
        if not source_image_embed_id:
            raise ValueError("Missing required argument: source_image_embed_id")
        if not user_vault_key_id:
            raise ValueError(
                "Missing required argument: user_vault_key_id "
                "(needed to decrypt the source image)"
            )

        # 3. Get or generate embed_id for the result
        embed_id = arguments.get("embed_id") or str(uuid.uuid4())
        logger.info(f"{log_prefix} Using result embed_id: {embed_id}")

        # 4. Decrypt the source image from the embed cache
        logger.info(
            f"{log_prefix} Decrypting source image from embed {source_image_embed_id[:8]}..."
        )
        image_bytes, mime_type = await _decrypt_source_image(
            embed_id=source_image_embed_id,
            user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )

        if not image_bytes:
            raise Exception(
                f"Failed to decrypt source image from embed {source_image_embed_id}. "
                "The image may have expired from cache (24h TTL)."
            )

        logger.info(
            f"{log_prefix} Source image decrypted: {len(image_bytes)} bytes ({mime_type})"
        )

        # 5. Call Recraft vectorize API
        logger.info(f"{log_prefix} Calling Recraft vectorize API...")
        svg_bytes = await vectorize_image_recraft(
            image_bytes=image_bytes,
            secrets_manager=task._secrets_manager,
            mime_type=mime_type or "image/png",
        )

        if not svg_bytes:
            raise Exception("Recraft vectorize API returned empty SVG data")

        logger.info(
            f"{log_prefix} Vectorization complete: {len(svg_bytes)} bytes SVG"
        )

        # 6. Charge credits (15 credits per vectorization)
        model_ref = "recraft/vectorize"
        hashed_user_id = _hash_value(user_id)
        await _charge_vectorize_credits(
            user_id=user_id,
            user_id_hash=hashed_user_id,
            app_id=app_id,
            skill_id=skill_id,
            model_ref=model_ref,
            chat_id=chat_id,
            message_id=message_id,
            log_prefix=log_prefix,
        )

        # 7. Process SVG into storage formats (original SVG + preview WEBP rasterization)
        labeling_metadata = {
            "prompt": "Vectorized from raster image",
            "model": "Recraft Vectorize",
            "software": "OpenMates",
            "source": "OpenMates AI",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        processed_images = process_svg_for_storage(svg_bytes, metadata=labeling_metadata)

        # 8. Hybrid encryption setup — same flow as generate_task.py
        result = await task._directus_service.get_user_profile(user_id)

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
            success = True
            user_profile = result

        if not success or not user_profile or not isinstance(user_profile, dict):
            raise Exception(
                f"User profile not found or invalid for {user_id}: {error_msg}"
            )

        vault_key_id = user_profile.get("vault_key_id")
        if not vault_key_id:
            raise Exception(f"Vault key ID not found for user {user_id}")

        # Generate local symmetric key for this set of images
        aes_key = os.urandom(32)  # AES-256
        nonce = os.urandom(12)  # GCM nonce
        aesgcm = AESGCM(aes_key)

        # Wrap the local AES key using Vault
        aes_key_b64 = base64.b64encode(aes_key).decode("utf-8")
        encrypted_aes_key_vault, _ = (
            await task._encryption_service.encrypt_with_user_key(
                aes_key_b64, vault_key_id
            )
        )
        if not encrypted_aes_key_vault:
            raise Exception("Failed to wrap AES key with Vault")

        nonce_b64 = base64.b64encode(nonce).decode("utf-8")

        # 9. Encrypt and upload each version to S3
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        files_metadata: Dict[str, Any] = {}

        format_mapping = {
            "original": "original",
            "full_webp": "full",
            "preview_webp": "preview",
        }

        for format_key, content in processed_images.items():
            encrypted_payload = aesgcm.encrypt(nonce, content, None)

            if format_key == "original":
                ext = "svg"
            else:
                ext = "webp"
            file_key = f"{user_id}/{timestamp}_{unique_id}_{format_key}.{ext}"

            logger.info(
                f"{log_prefix} Uploading {format_key} version to S3 (chatfiles): {file_key}"
            )

            upload_result = await task._s3_service.upload_file(
                bucket_key="chatfiles",
                file_key=file_key,
                content=encrypted_payload,
                content_type="application/octet-stream",
            )

            if not upload_result.get("url"):
                raise Exception(f"Failed to upload {format_key} image to S3")

            # Get dimensions for this format (SVG returns 0,0 which is correct)
            try:
                img = Image.open(BytesIO(content))
                width, height = img.size
            except Exception:
                width, height = 0, 0

            public_format = format_mapping.get(format_key, format_key)
            stored_format = "svg" if format_key == "original" else "webp"
            files_metadata[public_format] = {
                "s3_key": file_key,
                "width": width,
                "height": height,
                "size_bytes": len(content),
                "format": stored_format,
            }

        # 10. Prepare embed content
        generated_at = datetime.now(timezone.utc).isoformat()
        chatfiles_bucket = get_bucket_name("chatfiles")
        s3_base_url = f"https://{chatfiles_bucket}.{task._s3_service.base_domain}"

        embed_content = {
            "app_id": "images",
            "skill_id": skill_id,
            "type": "image",
            "status": "finished",
            "files": files_metadata,
            "s3_base_url": s3_base_url,
            "aes_key": aes_key_b64,
            "aes_nonce": nonce_b64,
            "vault_wrapped_aes_key": encrypted_aes_key_vault,
            "prompt": "Vectorized from raster image",
            "model": "vectorize",
            "aspect_ratio": "1:1",  # Preserves source aspect, but metadata field required
            "output_filetype": "svg",
            "generated_at": generated_at,
        }

        # 10b. Cache S3 file keys for server-side cleanup
        s3_file_keys = [
            {"bucket": "chatfiles", "key": meta["s3_key"]}
            for meta in files_metadata.values()
        ]

        try:
            client = await task._cache_service.client
            if client:
                s3_keys_cache_key = f"embed:{embed_id}:s3_file_keys"
                await client.set(
                    s3_keys_cache_key, json.dumps(s3_file_keys), ex=3600
                )
                logger.info(
                    f"{log_prefix} Cached {len(s3_file_keys)} S3 file keys "
                    f"for embed {embed_id}"
                )
        except Exception as e:
            logger.warning(
                f"{log_prefix} Failed to cache S3 file keys for embed {embed_id}: {e}"
            )

        # 11. Encode embed content as TOON and send to client via WebSocket
        from toon_format import encode as toon_encode

        content_toon = toon_encode(embed_content)
        logger.info(
            f"{log_prefix} TOON-encoded embed content: {len(content_toon)} chars"
        )

        now_ts = int(datetime.now(timezone.utc).timestamp())

        from backend.core.api.app.services.embed_service import EmbedService

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )

        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="app_skill_use",
            content_toon=content_toon,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=hashed_user_id,
            status="finished",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=log_prefix,
            check_cache_status=False,
        )

        # 12. Prepare result for API response / task polling
        result_data = {
            "embed_id": embed_id,
            "type": "image",
            "status": "finished",
            "files": {
                format_name: {
                    "width": meta["width"],
                    "height": meta["height"],
                    "size_bytes": meta["size_bytes"],
                    "format": meta["format"],
                }
                for format_name, meta in files_metadata.items()
            },
            "prompt": "Vectorized from raster image",
            "model": "vectorize",
            "output_filetype": "svg",
            "generated_at": generated_at,
        }

        logger.info(
            f"{log_prefix} Vectorize task completed successfully. "
            f"Embed ID: {embed_id}"
        )
        return result_data

    except Exception as e:
        logger.error(
            f"{log_prefix} Vectorize task failed: {e}", exc_info=True
        )

        # Send error embed to client (best-effort, same pattern as generate_task.py)
        try:
            _embed_id = arguments.get("embed_id")
            _user_id = arguments.get("user_id")
            _chat_id = arguments.get("chat_id")
            _message_id = arguments.get("message_id")

            if _embed_id and _user_id and _chat_id and _message_id:
                from toon_format import encode as toon_encode
                from backend.core.api.app.services.embed_service import EmbedService

                _hashed_user_id = _hash_value(_user_id)

                error_str = str(e)
                if "500 INTERNAL" in error_str or "ServerError" in error_str:
                    user_error = (
                        "The vectorization service is temporarily unavailable. "
                        "Please try again."
                    )
                elif "expired" in error_str.lower() or "not found in cache" in error_str.lower():
                    user_error = (
                        "The source image has expired from cache. "
                        "Please re-upload the image and try again."
                    )
                elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
                    user_error = "Image vectorization timed out. Please try again."
                elif "5 MB" in error_str:
                    user_error = (
                        "The image is too large for vectorization (max 5 MB). "
                        "Please use a smaller image."
                    )
                else:
                    user_error = "Image vectorization failed. Please try again."

                error_content = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "type": "image",
                    "status": "error",
                    "error": user_error,
                    "prompt": "Vectorize image",
                    "model": "vectorize",
                }

                content_toon = toon_encode(error_content)
                now_ts = int(datetime.now(timezone.utc).timestamp())

                try:
                    await task.initialize_services()
                except Exception:
                    pass  # Services may already be initialized

                embed_service = EmbedService(
                    cache_service=task._cache_service,
                    directus_service=task._directus_service,
                    encryption_service=task._encryption_service,
                )

                await embed_service.send_embed_data_to_client(
                    embed_id=_embed_id,
                    embed_type="app_skill_use",
                    content_toon=content_toon,
                    chat_id=str(_chat_id),
                    message_id=str(_message_id),
                    user_id=_user_id,
                    user_id_hash=_hashed_user_id,
                    status="error",
                    encryption_mode="client",
                    created_at=now_ts,
                    updated_at=now_ts,
                    log_prefix=f"{log_prefix} [ERROR_EMBED]",
                    check_cache_status=False,
                )

                logger.info(
                    f"{log_prefix} Sent error embed status for embed "
                    f"{_embed_id}: {user_error}"
                )
            else:
                logger.warning(
                    f"{log_prefix} Cannot send error embed — missing required arguments"
                )
        except Exception as embed_error:
            logger.error(
                f"{log_prefix} Failed to send error embed status: {embed_error}",
                exc_info=True,
            )

        raise
    finally:
        await task.cleanup_services()
