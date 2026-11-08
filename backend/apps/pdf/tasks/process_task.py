# backend/apps/pdf/tasks/process_task.py
#
# Celery task: background PDF processing pipeline.
#
# Architecture:
#   Triggered by the uploads server via POST /internal/pdf/process after a PDF
#   has been uploaded and stored in S3. This task:
#
#   1. Downloads and decrypts the PDF from S3.
#   2. Runs the v2 pipeline (services/pdf_pipeline.py): per-page triage, text layer or chunked
#      OCR, Jev prompt-injection scores and image decisions, outline/Jev table of contents,
#      encrypted page blob, page-1 preview. Other page renders happen on demand.
#   3. Constructs the embed TOON content (visible to the LLM) and delivers it only when every
#      page is final (the assistant is held until then).
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
from datetime import datetime, timezone
from typing import Any, Dict, List

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


PDF_PROCESS_LOCK_TTL_SECONDS = 900  # above the 660s Celery hard limit


async def _claim_pdf_processing(cache_service: Any, embed_id: str, task_id: str) -> bool:
    """Single-flight per embed. A Celery retry keeps its task id and may re-enter.

    Without a reachable cache the claim cannot be arbitrated; processing then
    proceeds, because losing a user's PDF is worse than a duplicate OCR run.
    """
    client = await cache_service.client
    if client is None:
        return True
    key = f"pdf:{embed_id}:process:lock"
    if await client.set(key, task_id, nx=True, ex=PDF_PROCESS_LOCK_TTL_SECONDS):
        return True
    holder = await client.get(key)
    if isinstance(holder, bytes):
        holder = holder.decode("utf-8")
    return holder == task_id


async def _load_upload_billing(cache_service: Any, embed_id: str, user_id: str) -> Dict[str, Any]:
    """The charge and page routes recorded when the PDF was uploaded, or {} when none exist.

    The upload route and the message handler can both dispatch processing; only the upload route
    knows what was charged. The record is trusted only for the user who uploaded the embed.
    """
    client = await cache_service.client
    if client is None:
        return {}
    raw = await client.get(f"pdf:{embed_id}:billing")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not raw:
        return {}
    try:
        record = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[pdf.process] [embed:%s] Ignoring unreadable upload billing record", embed_id[:8])
        return {}
    if not isinstance(record, dict) or record.get("user_id") != user_id:
        return {}
    credits = record.get("credits_charged")
    routes = record.get("page_routes")
    return {
        "credits_charged": credits if isinstance(credits, int) and credits >= 0 else 0,
        "page_routes": routes if isinstance(routes, list) else None,
    }


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

        # The upload route and the message handler can both dispatch this task
        # for one embed. A second concurrent run would repeat the paid OCR calls
        # and race the first run's writes, so only one run per embed proceeds.
        if not await _claim_pdf_processing(task._cache_service, embed_id, task_id):
            logger.info(f"{log_prefix} Another task already processes this embed — skipping duplicate dispatch")
            return {"embed_id": embed_id, "status": "duplicate_skipped"}

        # A dispatch from the message handler carries no charge or routes; take what the upload
        # recorded so the refund and price adjustment do not depend on which dispatch won.
        if not credits_charged and not arguments.get("page_routes"):
            recorded = await _load_upload_billing(task._cache_service, embed_id, user_id)
            if recorded:
                credits_charged = recorded["credits_charged"]
                arguments = {**arguments, "credits_charged": credits_charged, "page_routes": recorded["page_routes"]}
                logger.info(f"{log_prefix} Upload billing record applied: {credits_charged} credits charged")

        # -----------------------------------------------------------------------
        # Dedup shortcut: if source_embed_id is provided, try to copy the OCR
        # cache from the original embed instead of re-running OCR. This saves
        # the expensive OCR API call when the same PDF is uploaded again within
        # the 72h cache TTL.  See OPE-485 for architecture details.
        # -----------------------------------------------------------------------
        source_embed_id = arguments.get("source_embed_id")
        if source_embed_id:
            copied = await _try_copy_ocr_cache(
                source_embed_id=source_embed_id,
                target_embed_id=embed_id,
                user_id=user_id,
                user_id_hash=user_id_hash,
                vault_key_id=vault_key_id,
                chat_id=arguments.get("chat_id", ""),
                embed_service=task._embed_service,
                encryption_service=task._encryption_service,
                log_prefix=log_prefix,
            )
            if copied:
                logger.info(f"{log_prefix} OCR cache copied from {source_embed_id[:8]} — skipping OCR")
                return {
                    "embed_id": embed_id,
                    "status": "finished",
                    "page_count": page_count,
                    "ocr_skipped": True,
                    "source_embed_id": source_embed_id,
                }
            else:
                logger.info(f"{log_prefix} OCR cache miss for {source_embed_id[:8]} — running full OCR")

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
        output_aesgcm = AESGCM(output_aes_key)
        output_aes_key_b64 = base64.b64encode(output_aes_key).decode("ascii")
        # Note: output_nonce is NOT generated here. Each artefact (screenshot, OCR image,
        # OCR blob) generates its own nonce via os.urandom(12) immediately before encryption
        # to prevent AES-GCM nonce reuse across multiple plaintexts with the same key.

        # Vault-wrap the output AES key
        output_vault_wrapped_key = await _wrap_key_via_vault(
            aes_key_b64=output_aes_key_b64,
            vault_key_id=vault_key_id,
            log_prefix=log_prefix,
        )
        logger.info(f"{log_prefix} Output AES key generated and Vault-wrapped")

        # -----------------------------------------------------------------------
        # Step 3: PDF processing v2 pipeline (triage → text/OCR/images → Jev safety + TOC →
        # encrypted artefacts). The embed only becomes "finished" below, after every page is
        # final, so the assistant is held until then (readiness.complete-before-answer).
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 3: Running v2 pipeline")
        from backend.apps.pdf.services.pdf_pipeline import run_pipeline

        pipeline = await run_pipeline(
            pdf_bytes=pdf_bytes,
            secrets_manager=task._secrets_manager,
            s3_service=task._s3_service,
            output_aesgcm=output_aesgcm,
            user_id=user_id,
            embed_id=embed_id,
            page_routes=arguments.get("page_routes"),
            created_s3_keys=created_s3_keys,
            log_prefix=log_prefix,
        )
        total_tokens = pipeline.total_tokens
        page_count = pipeline.embed_fields["page_count"]
        # Pages billed as OCR at upload that the decision model proved to be text-layer are refunded,
        # so the final price is exactly 2 + 2 per page that really went through OCR.
        if arguments.get("page_routes") and credits_charged > pipeline.price_credits:
            try:
                await _refund_credits(
                    user_id=user_id, user_id_hash=user_id_hash,
                    credits=credits_charged - pipeline.price_credits,
                    reason=f"PDF price adjusted to {pipeline.price_credits} credits for embed {embed_id}",
                    idempotency_key=f"pdf:{embed_id}:process:price-adjust",
                    log_prefix=log_prefix,
                )
            except (httpx.HTTPError, RuntimeError) as refund_err:
                # The PDF is processed; losing it over a refund hiccup would be worse. The
                # idempotency key makes a manual or later retry safe.
                logger.error(f"{log_prefix} Price-adjustment refund failed: {refund_err}", exc_info=True)
        screenshot_s3_keys = pipeline.embed_fields["screenshot_s3_keys"]
        extracted_image_s3_keys = pipeline.embed_fields["extracted_image_s3_keys"]

        # -----------------------------------------------------------------------
        # Step 4: Build embed TOON content and send to client via WebSocket
        # -----------------------------------------------------------------------
        logger.info(f"{log_prefix} Step 4: Building embed TOON content")

        embed_content = {
            "type": "pdf",
            "filename": filename,
            "embed_ref": arguments.get("embed_ref") or filename,
            **pipeline.embed_fields,
            # Plaintext AES key for CLIENT-SIDE decryption of screenshots. The embed TOON content is
            # itself encrypted with the chat's master key (stored only in IndexedDB), so storing the
            # plaintext key here is safe (same pattern as images.generate). aes_nonce is omitted: each
            # S3 artefact carries its own nonce in its first 12 bytes.
            "aes_key": output_aes_key_b64,
            "aes_nonce": "",
            # Vault-wrapped key for SERVER-SIDE skill decryption (pdf.read / pdf.view / pdf.search).
            "vault_wrapped_aes_key": output_vault_wrapped_key,
            "s3_base_url": s3_base_url,
            # The original PDF, so pages can be rendered on demand (pdf.view, fullscreen).
            "original_s3_key": s3_key,
            "original_vault_wrapped_aes_key": vault_wrapped_aes_key,
            "original_aes_nonce": aes_nonce,
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

        # -----------------------------------------------------------------------
        # Cache the PDF embed in Redis so the pdf.read / pdf.view / pdf.search
        # skills can resolve file_path → embed_id → crypto fields server-side,
        # without the LLM ever seeing vault_wrapped_aes_key, ocr_data_s3_key, etc.
        #
        # This mirrors the pattern from the images upload server which calls
        # `/internal/uploads/cache-embed` after processing. For PDFs processed by
        # the Celery worker, we call _cache_embed() directly here.
        #
        # The embed content is Vault-encrypted before storage so that any Redis
        # dump is opaque to attackers (same security model as images embeds).
        # -----------------------------------------------------------------------
        try:
            encrypted_toon, _ = await task._encryption_service.encrypt_with_user_key(
                content_toon, vault_key_id
            )
            if encrypted_toon:
                cache_embed_data = {
                    "embed_id": embed_id,
                    "type": "pdf",
                    "status": "finished",
                    "encrypted_content": encrypted_toon,
                    "vault_key_id": vault_key_id,
                    "user_id": user_id,
                }
                await embed_service._cache_embed(
                    embed_id=embed_id,
                    embed_data=cache_embed_data,
                    chat_id=arguments.get("chat_id") or "",
                    user_id_hash=user_id_hash,
                    user_vault_key_id=vault_key_id,
                    user_id=user_id,
                )
                logger.info(
                    f"{log_prefix} PDF embed cached in Redis for skill lookup "
                    f"(embed:{embed_id[:8]}...)"
                )
            else:
                logger.error(
                    f"{log_prefix} Failed to Vault-encrypt embed content for Redis cache "
                    f"— pdf.read/pdf.view/pdf.search will not be able to look up this embed"
                )
        except Exception as cache_err:
            # Non-fatal: PDF was processed successfully; skills may degrade gracefully.
            # Log as error because it prevents pdf.read/pdf.view/pdf.search from working.
            logger.error(
                f"{log_prefix} Redis cache of PDF embed failed: {cache_err}",
                exc_info=True,
            )

        chat_id = arguments.get("chat_id")
        message_id = arguments.get("message_id")
        await embed_service.send_embed_data_to_client(
            embed_id=embed_id,
            embed_type="pdf",
            content_toon=content_toon,
            chat_id=chat_id or "",
            message_id=message_id or "",
            user_id=user_id,
            user_id_hash=user_id_hash,
            status="finished",
            encryption_mode="client",
            created_at=now_ts,
            updated_at=now_ts,
            log_prefix=log_prefix,
            check_cache_status=False,
        )
        if not (chat_id and message_id):
            logger.info(
                f"{log_prefix} PDF processed without chat/message context; "
                "sent draft completion event without client persistence context"
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

        from backend.apps.pdf.services.pdf_pipeline import PdfRejectedError

        rejected = isinstance(exc, PdfRejectedError)
        retries_remaining = 0 if rejected else MAX_RETRIES - task.request.retries
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
                rejected=rejected,
                task=task,
                arguments=arguments,
                log_prefix=log_prefix,
            )
            raise

    finally:
        await task.cleanup_services()


async def _try_copy_ocr_cache(
    source_embed_id: str,
    target_embed_id: str,
    user_id: str,
    user_id_hash: str,
    vault_key_id: str,
    chat_id: str,
    embed_service: Any,
    encryption_service: Any,
    log_prefix: str,
) -> bool:
    """
    Try to copy OCR cache from source_embed_id to target_embed_id.

    Returns True if the cache was successfully copied and send_embed_data
    was fired for the new embed_id. Returns False if the source cache is
    cold (expired) and full OCR must run instead.
    """
    try:
        cache_service = embed_service.cache_service
        client = await cache_service.client
        if not client:
            return False

        source_key = f"embed:{source_embed_id}"
        cached_json = await client.get(source_key)
        if not cached_json:
            logger.info(f"{log_prefix} Source cache miss: {source_key}")
            return False

        import json as json_lib
        cached_data = json_lib.loads(cached_json)

        # The cached entry must have vault-encrypted TOON content with OCR data.
        # Upload-only cache entries (no encrypted_content) can't be copied.
        if not cached_data.get("encrypted_content"):
            logger.info(f"{log_prefix} Source cache has no encrypted_content — not an OCR result")
            return False

        # Copy: write the same vault-encrypted TOON under the new embed_id's key.
        # The TOON content (screenshot S3 keys, OCR text blob key, AES credentials)
        # is identical because it was derived from the same S3 object.
        target_data = dict(cached_data)
        target_data["embed_id"] = target_embed_id

        target_key = f"embed:{target_embed_id}"
        await client.set(target_key, json_lib.dumps(target_data), ex=259200)  # 72h

        # Add to chat embed index
        if chat_id:
            chat_index_key = f"chat:{chat_id}:embed_ids"
            await client.sadd(chat_index_key, target_embed_id)
            await client.expire(chat_index_key, 259200)

        logger.info(f"{log_prefix} OCR cache copied: {source_key} → {target_key}")

        # Decrypt the TOON from vault to get the plaintext content for send_embed_data.
        # The client needs plaintext TOON to encrypt with its own session keys.
        encrypted_content = cached_data["encrypted_content"]
        content_toon = await encryption_service.vault_decrypt(
            encrypted_content, vault_key_id
        )

        if content_toon:
            await embed_service.send_embed_data_to_client(
                embed_id=target_embed_id,
                embed_type="app_skill_use",
                content_toon=content_toon,
                chat_id=chat_id,
                message_id="",
                user_id=user_id,
                user_id_hash=user_id_hash,
                status="finished",
                log_prefix=f"{log_prefix} [dedup-copy]",
            )
            logger.info(f"{log_prefix} send_embed_data fired for copied embed {target_embed_id[:8]}")

        return True

    except Exception as exc:
        logger.warning(f"{log_prefix} OCR cache copy failed (non-fatal): {exc}", exc_info=True)
        return False


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

    # Unwrap AES key from Vault. User keys are derived — must pass context = base64(key_id).
    context = base64.b64encode(vault_key_id.encode()).decode("utf-8")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{vault_url}/v1/transit/decrypt/{vault_key_id}",
            json={"ciphertext": vault_wrapped_aes_key, "context": context},
            headers={"X-Vault-Token": vault_token},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Vault transit decrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    # Double-decode: encrypt_with_user_key does base64(aes_key_b64) before sending to Vault,
    # so Vault's plaintext = base64(aes_key_b64). Decode twice to get raw AES key bytes.
    aes_key_b64 = base64.b64decode(resp.json()["data"]["plaintext"]).decode("utf-8")
    aes_key_bytes = base64.b64decode(aes_key_b64)

    # Download encrypted PDF from S3 via internal API (chatfiles bucket is private).
    internal_api_base = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
    shared_token = os.getenv("INTERNAL_API_SHARED_TOKEN", "")
    download_url = f"{internal_api_base}/internal/s3/download"
    logger.info(f"{log_prefix} Downloading PDF from private S3 via internal API: {s3_key}")
    async with httpx.AsyncClient(timeout=300) as client:
        dl_resp = await client.get(
            download_url,
            params={"bucket_key": "chatfiles", "s3_key": s3_key},
            headers={"X-Internal-Service-Token": shared_token},
        )
    if dl_resp.status_code != 200:
        raise RuntimeError(f"S3 download failed for {s3_key}: HTTP {dl_resp.status_code} — {dl_resp.text[:200]}")

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

    The user's Transit key is derived (created with derived=true), so every
    encrypt/decrypt call MUST include ``context = base64(vault_key_id)``.
    Without context, Vault returns HTTP 400 "missing 'context' for key derivation".

    IMPORTANT: Vault Transit requires the plaintext to be base64-encoded.
    EncryptionService.encrypt() (called by the upload server via encrypt_with_user_key)
    applies an extra base64 layer: it does base64(aes_key_b64.encode()) before sending
    to Vault, so Vault stores base64(base64(raw_key_bytes)).
    The pdf.read / pdf.view / pdf.search skills all use a double-decode to unwrap:
      base64.b64decode(vault_response).decode("utf-8") → aes_key_b64
      base64.b64decode(aes_key_b64) → raw AES key bytes
    We MUST apply the same extra encode here so the skills' double-decode works.

    Returns Vault-wrapped ciphertext string.
    """
    vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
    with open("/vault-data/api.token") as f:
        vault_token = f.read().strip()

    # Derived keys require context = base64(key_id) — same pattern as _download_decrypt_pdf().
    context = base64.b64encode(vault_key_id.encode()).decode("utf-8")

    # Match EncryptionService.encrypt() which does base64(plaintext.encode()) before Vault.
    # Without this extra layer the skills' double-decode would fail with UnicodeDecodeError
    # because the first b64decode would yield raw AES bytes (not a valid UTF-8 string).
    encoded_plaintext = base64.b64encode(aes_key_b64.encode()).decode("utf-8")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{vault_url}/v1/transit/encrypt/{vault_key_id}",
            json={"plaintext": encoded_plaintext, "context": context},
            headers={"X-Vault-Token": vault_token},
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Vault transit encrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    return resp.json()["data"]["ciphertext"]


async def _refund_credits(
    *, user_id: str, user_id_hash: str, credits: int, reason: str, idempotency_key: str, log_prefix: str
) -> bool:
    """Refund credits through the internal billing API. Returns True when the refund was booked."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{INTERNAL_API_BASE_URL}/internal/billing/refund",
            json={
                "user_id": user_id,
                "user_id_hash": user_id_hash,
                "credits": credits,
                "reason": reason[:300],
                "app_id": "pdf",
                "skill_id": "process",
                "idempotency_key": idempotency_key,
            },
            headers={"Content-Type": "application/json", "X-Internal-Service-Token": INTERNAL_API_SHARED_TOKEN},
        )
    if resp.status_code in (200, 201):
        logger.info(f"{log_prefix} Refunded {credits} credits ({reason[:80]})")
        return True
    raise RuntimeError(f"Credit refund failed: HTTP {resp.status_code} {resp.text[:200]}")


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
    rejected: bool = False,
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
                        "idempotency_key": f"pdf:{embed_id}:process:refund",
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
            "error": (
                "This PDF was rejected because it contains content that violates the community guidelines. "
                "Your credits have been refunded."
                if rejected
                else "PDF processing failed after multiple retries. Your credits have been refunded."
            ),
        }
        content_toon = toon_encode(error_content)
        now_ts = int(datetime.now(timezone.utc).timestamp())

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )

        # Mark the cached embed as failed so a held chat turn ends with an explicit failure
        # message instead of waiting (readiness.complete-before-answer).
        encrypted_error, _ = await task._encryption_service.encrypt_with_user_key(
            content_toon, arguments["vault_key_id"]
        )
        if encrypted_error:
            await embed_service._cache_embed(
                embed_id=embed_id,
                embed_data={
                    "embed_id": embed_id, "type": "pdf", "status": "error",
                    "encrypted_content": encrypted_error, "vault_key_id": arguments["vault_key_id"],
                    "user_id": user_id,
                },
                chat_id=arguments.get("chat_id") or "",
                user_id_hash=user_id_hash,
                user_vault_key_id=arguments["vault_key_id"],
                user_id=user_id,
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
