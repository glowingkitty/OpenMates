# backend/apps/pdf/tasks/process_task.py
#
# Celery task: background PDF processing pipeline.
#
# Architecture:
#   Triggered by the uploads server via POST /internal/pdf/process after a PDF
#   has been uploaded and stored in S3. This task:
#
#   1. Downloads and decrypts the PDF from S3.
#   2. Runs Mistral OCR (mistral-ocr-latest) to extract per-page markdown + images.
#   3. Renders page screenshots at 150 DPI using pymupdf.
#   4. Detects TOC (Groq gpt-oss-20b, batches of 3, up to 12 pages).
#   5. Detects legend (Groq gpt-oss-20b, last 5 pages).
#   6. Encrypts and uploads:
#      - Page screenshots (one S3 object per page).
#      - Extracted OCR images (one S3 object each).
#      - Full OCR JSON blob (all per-page markdown + metadata).
#   7. Builds per-page token counts (len(markdown) // 4).
#   8. Constructs the embed TOON content structure (visible to LLM).
#   9. Updates the embed via WebSocket (embed_update event).
#
# Retry policy:
#   - Retries up to 3 times with exponential backoff.
#   - On final failure: refunds credits, deletes all S3 objects,
#     updates embed status to "error", sends critical notification.
#
# TOON content structure stored in embed (always visible to LLM):
#   {
#     "type": "pdf",
#     "filename": "report.pdf",
#     "page_count": 42,
#     "total_tokens_estimated": 95000,
#     "per_page_tokens": {"1": 1600, "2": 1600, ...},
#     "toc": {"detected": true, "source_pages": [4, 5], "chapters": [...]},
#     "legend": {"detected": true, "source_pages": [41, 42], "content": "..."},
#     "ocr_data_s3_key": "chatfiles/...",
#     "screenshot_s3_keys": {"1": "chatfiles/...", "2": "chatfiles/...", ...},
#     "extracted_image_s3_keys": ["chatfiles/...", ...]
#   }

import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask

logger = logging.getLogger(__name__)

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN", "")

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 60  # seconds

# S3 bucket for all PDF artefacts
PDF_S3_BUCKET = "chatfiles"


@app.task(
    bind=True,
    name="apps.pdf.tasks.process_pdf",
    base=BaseServiceTask,
    queue="app_pdf",
    soft_time_limit=600,    # 10 minutes soft limit
    time_limit=660,          # 11 minutes hard limit
    max_retries=MAX_RETRIES,
)
def process_pdf_task(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task for background PDF processing.

    Arguments (passed from /internal/pdf/process):
      - embed_id (str)
      - user_id (str)
      - vault_key_id (str)
      - s3_key (str): S3 key of the encrypted original PDF
      - s3_base_url (str)
      - vault_wrapped_aes_key (str): Vault-wrapped AES key for the PDF
      - aes_nonce (str): Base64 nonce for the PDF
      - filename (str): Original filename
      - page_count (int)
      - credits_charged (int): Credits already charged upfront (for refund on failure)
      - user_id_hash (str): SHA256 hash of user_id for billing
    """
    return asyncio.run(_async_process_pdf(self, arguments))


async def _async_process_pdf(task: BaseServiceTask, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main async implementation of the PDF processing pipeline.
    All steps wrapped in retry-aware error handling.
    """
    task_id = task.request.id
    embed_id = arguments.get("embed_id", "unknown")
    log_prefix = f"[pdf.process] [task:{task_id[:8]}] [embed:{embed_id[:8]}]"

    logger.info(f"{log_prefix} Starting PDF processing pipeline")

    # Extract arguments
    user_id: str = arguments["user_id"]
    vault_key_id: str = arguments["vault_key_id"]
    s3_key: str = arguments["s3_key"]
    s3_base_url: str = arguments["s3_base_url"]
    vault_wrapped_aes_key: str = arguments["vault_wrapped_aes_key"]
    aes_nonce: str = arguments["aes_nonce"]
    filename: str = arguments.get("filename", "document.pdf")
    page_count: int = arguments["page_count"]
    credits_charged: int = arguments.get("credits_charged", 0)
    user_id_hash: str = arguments.get("user_id_hash", "")

    # Track all S3 objects created during this run (for cleanup on failure)
    created_s3_keys: List[str] = []

    try:
        await task.initialize_services()

        # -----------------------------------------------------------------------
        # Step 1: Download and decrypt the PDF from S3
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 1: Downloading PDF from S3: {s3_key}")
        pdf_bytes = await _download_decrypt_pdf(
            s3_base_url=s3_base_url,
            s3_key=s3_key,
            vault_wrapped_aes_key=vault_wrapped_aes_key,
            aes_nonce=aes_nonce,
            vault_key_id=vault_key_id,
            log_prefix=log_prefix,
        )
        logger.info(f"{log_prefix} PDF decrypted: {len(pdf_bytes)} bytes")

        # -----------------------------------------------------------------------
        # Step 2: Generate a new per-artefact AES key for outputs
        # -----------------------------------------------------------------------
        # We generate a fresh AES key for the OCR outputs (screenshots, OCR JSON,
        # extracted images). This key is Vault-wrapped with the user's transit key,
        # stored in the embed content, and used by the skill to decrypt artefacts.
        output_aes_key = os.urandom(32)
        output_nonce = os.urandom(12)
        output_aesgcm = AESGCM(output_aes_key)
        output_aes_key_b64 = base64.b64encode(output_aes_key).decode("ascii")
        output_nonce_b64 = base64.b64encode(output_nonce).decode("ascii")

        # Vault-wrap the output AES key
        output_vault_wrapped_key = await _wrap_key_via_vault(
            aes_key_b64=output_aes_key_b64,
            vault_key_id=vault_key_id,
            log_prefix=log_prefix,
        )
        logger.info(f"{log_prefix} Output AES key generated and Vault-wrapped")

        # -----------------------------------------------------------------------
        # Step 3: Run Mistral OCR
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 3: Running Mistral OCR")
        from backend.apps.pdf.services.ocr_service import run_mistral_ocr

        ocr_pages = await run_mistral_ocr(
            pdf_bytes=pdf_bytes,
            secrets_manager=task._secrets_manager,
            log_prefix=log_prefix,
        )
        logger.info(f"{log_prefix} OCR complete: {len(ocr_pages)} pages")

        # -----------------------------------------------------------------------
        # Step 4: Render page screenshots via pymupdf (in thread to avoid blocking)
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 4: Rendering page screenshots")
        from backend.apps.pdf.services.screenshot_service import render_pdf_pages

        screenshots: Dict[int, bytes] = await asyncio.to_thread(
            render_pdf_pages, pdf_bytes, log_prefix
        )
        logger.info(f"{log_prefix} Rendered {len(screenshots)} page screenshots")

        # -----------------------------------------------------------------------
        # Step 5: Detect TOC and legend (parallel calls to Groq)
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 5: Detecting TOC and legend")
        from backend.apps.pdf.services.toc_detector import detect_toc, detect_legend

        toc_result, legend_result = await asyncio.gather(
            detect_toc(ocr_pages, task._secrets_manager, log_prefix),
            detect_legend(ocr_pages, task._secrets_manager, log_prefix),
        )
        logger.info(
            f"{log_prefix} TOC detected={toc_result['detected']}, "
            f"legend detected={legend_result['detected']}"
        )

        # -----------------------------------------------------------------------
        # Step 6: Encrypt and upload page screenshots to S3
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 6: Uploading {len(screenshots)} page screenshots")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        screenshot_s3_keys: Dict[str, str] = {}

        for page_num, png_bytes in sorted(screenshots.items()):
            encrypted = output_aesgcm.encrypt(output_nonce, png_bytes, None)
            s3_screenshot_key = (
                f"chatfiles/{user_id}/{timestamp}_{unique_id}_pdf_{embed_id[:8]}_p{page_num}.png.bin"
            )
            await task._s3_service.upload_file(
                bucket_key=PDF_S3_BUCKET,
                file_key=s3_screenshot_key,
                content=encrypted,
                content_type="application/octet-stream",
            )
            screenshot_s3_keys[str(page_num)] = s3_screenshot_key
            created_s3_keys.append(s3_screenshot_key)

        logger.info(f"{log_prefix} All screenshots uploaded")

        # -----------------------------------------------------------------------
        # Step 7: Encrypt and upload extracted OCR images
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 7: Uploading extracted OCR images")
        extracted_image_s3_keys: List[str] = []

        for page in ocr_pages:
            page_num = page["page_num"]
            for img_idx, img in enumerate(page.get("images", [])):
                img_b64 = img.get("base64", "")
                if not img_b64:
                    continue
                try:
                    img_bytes = base64.b64decode(img_b64)
                    encrypted_img = output_aesgcm.encrypt(output_nonce, img_bytes, None)
                    img_s3_key = (
                        f"chatfiles/{user_id}/{timestamp}_{unique_id}_"
                        f"pdf_{embed_id[:8]}_p{page_num}_img{img_idx}.bin"
                    )
                    await task._s3_service.upload_file(
                        bucket_key=PDF_S3_BUCKET,
                        file_key=img_s3_key,
                        content=encrypted_img,
                        content_type="application/octet-stream",
                    )
                    extracted_image_s3_keys.append(img_s3_key)
                    created_s3_keys.append(img_s3_key)
                except Exception as e:
                    logger.warning(
                        f"{log_prefix} Failed to upload extracted image p{page_num}/img{img_idx}: {e}"
                    )

        logger.info(f"{log_prefix} Uploaded {len(extracted_image_s3_keys)} extracted images")

        # -----------------------------------------------------------------------
        # Step 8: Build per-page token estimates + OCR JSON blob, upload to S3
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 8: Building OCR JSON blob")

        per_page_tokens: Dict[str, int] = {}
        ocr_blob_pages: Dict[str, Any] = {}

        for page in ocr_pages:
            pn = page["page_num"]
            md = page.get("markdown", "")
            # Rough token estimate: 1 token ≈ 4 characters
            token_count = max(1, len(md) // 4)
            per_page_tokens[str(pn)] = token_count

            ocr_blob_pages[str(pn)] = {
                "markdown": md,
                "header": page.get("header"),
                "footer": page.get("footer"),
                "tables": page.get("tables", []),
                "image_count": len(page.get("images", [])),
                "width": page.get("width", 0),
                "height": page.get("height", 0),
            }

        total_tokens = sum(per_page_tokens.values())

        ocr_blob = {"pages": ocr_blob_pages}
        ocr_blob_bytes = json.dumps(ocr_blob, ensure_ascii=False).encode("utf-8")
        encrypted_ocr_blob = output_aesgcm.encrypt(output_nonce, ocr_blob_bytes, None)

        ocr_s3_key = (
            f"chatfiles/{user_id}/{timestamp}_{unique_id}_pdf_{embed_id[:8]}_ocr.json.bin"
        )
        await task._s3_service.upload_file(
            bucket_key=PDF_S3_BUCKET,
            file_key=ocr_s3_key,
            content=encrypted_ocr_blob,
            content_type="application/octet-stream",
        )
        created_s3_keys.append(ocr_s3_key)
        logger.info(
            f"{log_prefix} OCR blob uploaded: {len(ocr_blob_bytes)} bytes → {ocr_s3_key}"
        )

        # -----------------------------------------------------------------------
        # Step 9: Build embed TOON content and send to client via WebSocket
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 9: Building embed TOON content")

        embed_content = {
            "type": "pdf",
            "filename": filename,
            "page_count": page_count,
            "total_tokens_estimated": total_tokens,
            "per_page_tokens": per_page_tokens,
            "toc": {
                "detected": toc_result["detected"],
                "source_pages": toc_result["source_pages"],
                "chapters": toc_result["chapters"],
            },
            "legend": {
                "detected": legend_result["detected"],
                "source_pages": legend_result["source_pages"],
                "content": legend_result["content"],
            },
            # S3 keys for skills to access artefacts
            "ocr_data_s3_key": ocr_s3_key,
            "screenshot_s3_keys": screenshot_s3_keys,
            "extracted_image_s3_keys": extracted_image_s3_keys,
            # Encryption metadata for skill decryption
            "vault_wrapped_aes_key": output_vault_wrapped_key,
            "aes_nonce": output_nonce_b64,
            "s3_base_url": s3_base_url,
            # Embed status
            "app_id": "pdf",
            "status": "finished",
        }

        from toon_format import encode as toon_encode  # type: ignore[import]

        content_toon = toon_encode(embed_content)
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
            chat_id=arguments.get("chat_id"),
            message_id=arguments.get("message_id"),
            user_id=user_id,
            user_id_hash=user_id_hash,
            status="finished",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=log_prefix,
            check_cache_status=False,
        )

        logger.info(
            f"{log_prefix} PDF processing complete. "
            f"pages={page_count}, tokens={total_tokens}, "
            f"screenshots={len(screenshot_s3_keys)}, images={len(extracted_image_s3_keys)}"
        )

        return {
            "embed_id": embed_id,
            "status": "finished",
            "page_count": page_count,
            "total_tokens_estimated": total_tokens,
        }

    except Exception as exc:
        logger.error(f"{log_prefix} PDF processing failed: {exc}", exc_info=True)

        retries_remaining = MAX_RETRIES - task.request.retries
        if retries_remaining > 0:
            countdown = RETRY_BACKOFF_BASE * (2 ** task.request.retries)
            logger.warning(
                f"{log_prefix} Retrying in {countdown}s "
                f"(attempt {task.request.retries + 1}/{MAX_RETRIES})"
            )
            raise task.retry(exc=exc, countdown=countdown)
        else:
            # Final failure: refund credits + cleanup S3 + notify
            logger.error(
                f"{log_prefix} All retries exhausted. Refunding {credits_charged} credits "
                f"and cleaning up {len(created_s3_keys)} S3 objects."
            )
            await _handle_final_failure(
                embed_id=embed_id,
                user_id=user_id,
                user_id_hash=user_id_hash,
                credits_charged=credits_charged,
                created_s3_keys=created_s3_keys,
                s3_base_url=s3_base_url,
                error_msg=str(exc),
                task=task,
                arguments=arguments,
                log_prefix=log_prefix,
            )
            raise

    finally:
        await task.cleanup_services()


async def _download_decrypt_pdf(
    s3_base_url: str,
    s3_key: str,
    vault_wrapped_aes_key: str,
    aes_nonce: str,
    vault_key_id: str,
    log_prefix: str,
) -> bytes:
    """
    Download encrypted PDF from S3 and decrypt using Vault-unwrapped AES key.

    Returns raw PDF bytes.
    """
    vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
    vault_token_path = "/vault-data/api.token"

    # Load Vault token
    with open(vault_token_path) as f:
        vault_token = f.read().strip()

    # Unwrap AES key from Vault
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{vault_url}/v1/transit/decrypt/{vault_key_id}",
            json={"ciphertext": vault_wrapped_aes_key},
            headers={"X-Vault-Token": vault_token},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Vault transit decrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    aes_key_bytes = base64.b64decode(resp.json()["data"]["plaintext"])

    # Download encrypted PDF from S3
    url = f"{s3_base_url.rstrip('/')}/{s3_key}"
    logger.info(f"{log_prefix} Downloading PDF from: {url}")
    async with httpx.AsyncClient(timeout=300) as client:
        dl_resp = await client.get(url)
    if dl_resp.status_code != 200:
        raise RuntimeError(f"S3 download failed for {s3_key}: HTTP {dl_resp.status_code}")

    # Decrypt
    nonce = base64.b64decode(aes_nonce)
    aesgcm = AESGCM(aes_key_bytes)
    return aesgcm.decrypt(nonce, dl_resp.content, None)


async def _wrap_key_via_vault(
    aes_key_b64: str,
    vault_key_id: str,
    log_prefix: str,
) -> str:
    """
    Wrap an AES key (base64) using Vault Transit encryption.

    Returns Vault-wrapped ciphertext string.
    """
    vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
    with open("/vault-data/api.token") as f:
        vault_token = f.read().strip()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{vault_url}/v1/transit/encrypt/{vault_key_id}",
            json={"plaintext": aes_key_b64},
            headers={"X-Vault-Token": vault_token},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Vault transit encrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    return resp.json()["data"]["ciphertext"]


async def _handle_final_failure(
    embed_id: str,
    user_id: str,
    user_id_hash: str,
    credits_charged: int,
    created_s3_keys: List[str],
    s3_base_url: str,
    error_msg: str,
    task: BaseServiceTask,
    arguments: Dict[str, Any],
    log_prefix: str,
) -> None:
    """
    On final task failure after all retries:
    1. Refund credits via internal billing API.
    2. Delete all S3 objects created during this run.
    3. Update embed status to "error" and notify client.
    """
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN,
    }

    # 1. Refund credits
    if credits_charged > 0:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{INTERNAL_API_BASE_URL}/internal/billing/refund",
                    json={
                        "user_id": user_id,
                        "user_id_hash": user_id_hash,
                        "credits": credits_charged,
                        "reason": f"PDF processing failed for embed {embed_id}: {error_msg[:200]}",
                        "app_id": "pdf",
                        "skill_id": "process",
                    },
                    headers=headers,
                )
            if resp.status_code in (200, 201):
                logger.info(f"{log_prefix} Refunded {credits_charged} credits to user {user_id[:8]}")
            else:
                logger.error(
                    f"{log_prefix} Credit refund failed: {resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            logger.error(f"{log_prefix} Credit refund request failed: {e}", exc_info=True)

    # 2. Delete S3 objects created during this run
    for s3_obj_key in created_s3_keys:
        try:
            await task._s3_service.delete_file(bucket_key=PDF_S3_BUCKET, file_key=s3_obj_key)
            logger.info(f"{log_prefix} Deleted S3 object: {s3_obj_key}")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to delete S3 object {s3_obj_key}: {e}")

    # 3. Notify client of failure via embed update
    try:
        from toon_format import encode as toon_encode  # type: ignore[import]
        from backend.core.api.app.services.embed_service import EmbedService

        error_content = {
            "type": "pdf",
            "app_id": "pdf",
            "status": "error",
            "filename": arguments.get("filename", "document.pdf"),
            "page_count": arguments.get("page_count", 0),
            "error": "PDF processing failed after multiple retries. Your credits have been refunded.",
        }
        content_toon = toon_encode(error_content)
        now_ts = int(datetime.now(timezone.utc).timestamp())

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )

        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="app_skill_use",
            content_toon=content_toon,
            chat_id=arguments.get("chat_id"),
            message_id=arguments.get("message_id"),
            user_id=user_id,
            user_id_hash=user_id_hash,
            status="error",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=f"{log_prefix} [ERROR_EMBED]",
            check_cache_status=False,
        )
        logger.info(f"{log_prefix} Error embed sent to client")
    except Exception as e:
        logger.error(f"{log_prefix} Failed to send error embed: {e}", exc_info=True)
