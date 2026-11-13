# backend/apps/pdf/skills/view_skill.py
#
# pdf.view skill — returns PDF page screenshots as multimodal content blocks.
#
# Architecture:
#   The LLM calls this skill with file_path (the original filename, e.g. "report.pdf").
#   The skill then:
#     1. Resolves file_path → embed_id via the file_path_index injected by main_processor.py
#     2. Looks up the embed's encrypted content from the Redis cache (embed:{embed_id})
#     3. Decrypts the embed content using the user's Vault Transit key
#     4. Extracts vault_wrapped_aes_key, screenshot_s3_keys, aes_nonce from the
#        decrypted embed content (these fields are NEVER exposed to the LLM)
#     5. Unwraps the AES key via Vault Transit
#     6. Downloads + decrypts page screenshot PNGs from S3
#     7. Returns a list of content blocks (text labels + image_url blocks)
#        so the MAIN inference model sees the page screenshots directly.
#
#   Up to 5 pages can be viewed in a single call. Each page screenshot is
#   included as a separate image block preceded by a "[Page N of M]" label
#   so the LLM knows which page it is looking at.
#
#   Use cases:
#   - Diagrams, charts, figures that OCR may misrepresent.
#   - Visual layout questions.
#   - Mathematical notation or handwritten text.
#   - Tables with complex formatting.

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote as url_quote

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel, Field
from toon_format import decode as toon_decode

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.pdf_ocr_readiness import wait_for_pdf_artefacts

logger = logging.getLogger(__name__)

MAX_PAGES_PER_CALL = 5  # Vision calls with too many images get slow/expensive


class ViewRequest(BaseModel):
    """
    Request model for the pdf.view skill.
    The LLM provides the original filename (file_path / embed_ref) — all cryptographic and
    storage details are resolved server-side from the embed cache via the file_path_index.
    """

    file_path: str = Field(
        ...,
        description=(
            "The original filename of the PDF to view (e.g. 'report.pdf'). "
            "Use the exact embed_ref value from the toon block."
        ),
    )
    pages: List[int] = Field(
        ..., description=f"1-indexed page numbers to view (max {MAX_PAGES_PER_CALL})."
    )
    query: str = Field(..., description="The user's question or instruction about the page(s).")


class ViewResponse(BaseModel):
    """
    Response model for the pdf.view skill (for OpenAPI docs).

    At runtime, execute() returns a List of content blocks (not this model),
    which the framework forwards as a multimodal tool result to the main LLM.
    This model exists only to document the skill's output shape in the REST API.
    """

    success: bool = Field(default=False)
    file_path: Optional[str] = Field(None)
    pages_viewed: List[int] = Field(default_factory=list)
    error: Optional[str] = Field(None)


class ViewSkill(BaseSkill):
    """
    Skill for loading page screenshots from an uploaded PDF and returning
    them as multimodal content blocks so the main inference model can see them.

    The LLM calls this with file_path (the original filename / embed_ref, e.g. "report.pdf").
    The skill resolves file_path → embed_id UUID via the file_path_index injected by
    main_processor.py, then resolves all crypto and storage details server-side by looking
    up the embed from the Redis cache and decrypting its content via Vault Transit.

    Returns the page screenshots as image_url blocks. The framework's
    llm_utils.py passes the list through unchanged to the provider adapters.
    """

    VAULT_TOKEN_PATH: str = "/vault-data/api.token"

    def _load_vault_token(self) -> str:
        with open(self.VAULT_TOKEN_PATH) as f:
            token = f.read().strip()
        if not token:
            raise RuntimeError("Vault token file is empty")
        return token

    async def _lookup_embed_content(
        self, embed_id: str, user_vault_key_id: str
    ) -> Dict[str, Any]:
        """
        Look up an embed's decrypted content from the Redis cache.

        The embed is stored in Redis at key ``embed:{embed_id}`` as a JSON dict
        with an ``encrypted_content`` field that holds a Vault Transit-encrypted
        TOON string. This method decrypts the content using the user's Vault key
        and decodes the TOON to return the raw content dict.

        Args:
            embed_id: The embed ID to look up.
            user_vault_key_id: The user's Vault Transit key ID for decryption.

        Returns:
            Decoded embed content dict (contains vault_wrapped_aes_key,
            screenshot_s3_keys, aes_nonce, etc.).

        Raises:
            RuntimeError: If the embed is not found in cache, has no encrypted
                content, or decryption/decoding fails.
        """
        log_prefix = f"[pdf.view] [embed:{embed_id[:8]}...]"

        redis_password = os.environ.get("DRAGONFLY_PASSWORD", "")
        redis_url = f"redis://default:{url_quote(redis_password, safe='')}@cache:6379/0"
        redis_client = aioredis.from_url(redis_url, decode_responses=True)

        try:
            embed_json = await redis_client.get(f"embed:{embed_id}")
            if not embed_json:
                raise RuntimeError(
                    f"PDF embed {embed_id} not found in cache (72h TTL). "
                    "Please ask the user to re-upload the PDF."
                )

            embed_data = json.loads(embed_json)
            encrypted_content = embed_data.get("encrypted_content")
            if not encrypted_content:
                raise RuntimeError(
                    f"PDF embed {embed_id} has no encrypted_content in cache"
                )

            # Decrypt the embed content using Vault Transit.
            # User keys are derived — must pass context = base64(key_id) to match encryption.
            vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
            token = self._load_vault_token()
            context = base64.b64encode(user_vault_key_id.encode()).decode("utf-8")

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{vault_url}/v1/transit/decrypt/{user_vault_key_id}",
                    json={"ciphertext": encrypted_content, "context": context},
                    headers={"X-Vault-Token": token},
                )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Vault decrypt failed for embed content: "
                    f"HTTP {resp.status_code} — {resp.text[:200]}"
                )

            plaintext_b64 = resp.json()["data"]["plaintext"]
            plaintext_toon = base64.b64decode(plaintext_b64).decode("utf-8")

            decoded = toon_decode(plaintext_toon)
            if not isinstance(decoded, dict):
                raise RuntimeError(
                    f"PDF embed {embed_id} TOON decoded to "
                    f"{type(decoded).__name__}, expected dict"
                )

            logger.info(
                f"{log_prefix} Successfully looked up embed from cache "
                f"(keys: {list(decoded.keys())})"
            )
            return decoded

        finally:
            await redis_client.aclose()

    async def _unwrap_aes_key(self, vault_wrapped_aes_key: str, vault_key_id: str) -> bytes:
        """Unwrap AES key via Vault Transit."""
        vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        token = self._load_vault_token()
        # User keys are derived — must pass context = base64(key_id) to match encryption.
        context = base64.b64encode(vault_key_id.encode()).decode("utf-8")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{vault_url}/v1/transit/decrypt/{vault_key_id}",
                json={"ciphertext": vault_wrapped_aes_key, "context": context},
                headers={"X-Vault-Token": token},
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Vault transit decrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        # Double-decode: encrypt_with_user_key does base64(aes_key_b64) before sending to Vault,
        # so Vault's plaintext = base64(aes_key_b64). Decode twice to get raw AES key bytes.
        aes_key_b64 = base64.b64decode(resp.json()["data"]["plaintext"]).decode("utf-8")
        return base64.b64decode(aes_key_b64)

    async def _download_from_s3(self, s3_key: str) -> bytes:
        """
        Download an encrypted file from S3 via the internal API's S3 service.

        The chatfiles bucket is private — direct HTTP GET is not allowed.
        This method calls the core API's internal S3 download endpoint which
        uses boto3 get_object (server-side credentials, no presigned URL needed).

        Args:
            s3_key: Object key within the bucket.

        Returns:
            Encrypted file bytes.

        Raises:
            RuntimeError: If the download fails.
        """
        download_url = f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}/internal/s3/download"
        shared_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                download_url,
                params={"bucket_key": "chatfiles", "s3_key": s3_key},
                headers={"X-Internal-Service-Token": shared_token},
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"S3 download failed for {s3_key}: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        return resp.content

    async def _upload_artefact(self, s3_key: str, content: bytes) -> None:
        """Store an already-encrypted page render through the internal S3 upload endpoint."""
        url = f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}/internal/s3/upload-pdf-artefact"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.put(
                url, params={"s3_key": s3_key}, content=content,
                headers={"X-Internal-Service-Token": os.environ.get("INTERNAL_API_SHARED_TOKEN", "")},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"S3 artefact upload failed for {s3_key}: HTTP {resp.status_code} — {resp.text[:200]}")

    async def _record_screenshot_key(
        self, embed_id: str, vault_key_id: str, page_number: int, s3_key: str
    ) -> None:
        """Remember a rendered page in the cached embed so later requests reuse it."""
        from toon_format import encode as toon_encode

        content = await self._lookup_embed_content(embed_id, vault_key_id)
        keys = dict(content.get("screenshot_s3_keys") or {})
        keys[str(page_number)] = s3_key
        content["screenshot_s3_keys"] = keys
        token = self._load_vault_token()
        vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        context = base64.b64encode(vault_key_id.encode()).decode("utf-8")
        plaintext = base64.b64encode(toon_encode(content).encode("utf-8")).decode("utf-8")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{vault_url}/v1/transit/encrypt/{vault_key_id}",
                json={"plaintext": plaintext, "context": context},
                headers={"X-Vault-Token": token},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Vault encrypt failed for embed update: HTTP {resp.status_code}")
        ciphertext = resp.json()["data"]["ciphertext"]
        redis_password = os.environ.get("DRAGONFLY_PASSWORD", "")
        redis_client = aioredis.from_url(
            f"redis://default:{url_quote(redis_password, safe='')}@cache:6379/0", decode_responses=True
        )
        try:
            raw = await redis_client.get(f"embed:{embed_id}")
            if not raw:
                return
            data = json.loads(raw)
            data["encrypted_content"] = ciphertext
            await redis_client.set(f"embed:{embed_id}", json.dumps(data), keepttl=True)
        finally:
            await redis_client.aclose()

    async def execute(
        self,
        file_path: str,
        pages: List[int],
        query: str,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Load page screenshots from a PDF and return them as a multimodal content list.

        The LLM provides file_path (the original filename / embed_ref, e.g. "report.pdf").
        All cryptographic and storage details are resolved server-side from the Redis cache.

        Returns a list of content blocks that will become the tool result
        passed directly to the main inference model:
          [
            {"type": "text", "text": "PDF pages 1, 2 from: report.pdf"},
            {"type": "text", "text": "[Page 1 of 12]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            {"type": "text", "text": "[Page 2 of 12]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ...
          ]

        Steps:
        1. Resolve file_path → embed_id via file_path_index (injected by main_processor).
        2. Look up all crypto fields from the Redis embed cache.
        3. Unwrap AES key via Vault.
        4. For each requested page (up to MAX_PAGES_PER_CALL):
           a. Download encrypted screenshot from S3.
           b. Decrypt with AES-256-GCM.
           c. Encode as base64 and add to content blocks.
        5. Return the content list.

        Args:
            file_path: Original filename of the PDF (embed_ref, e.g. "report.pdf").
            pages: 1-indexed page numbers to view (capped at MAX_PAGES_PER_CALL).
            query: The user's question about the pages (not used here — the
                   main LLM processes it after seeing the pages in the tool result).
            **kwargs: Context injected by the pipeline (user_vault_key_id, file_path_index, etc.).

        Returns:
            List of content blocks for multimodal tool result, or error message block.
        """
        log_prefix = f"[pdf.view] [file_path:{file_path!r}]"

        # --- Step 1: Resolve file_path → embed_id via file_path_index ---
        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}
        embed_id = file_path_index.get(file_path)
        if not embed_id:
            logger.error(
                f"{log_prefix} No embed found for file_path. "
                f"Available keys: {list(file_path_index.keys())}"
            )
            return [{"type": "text", "text": (
                f"Error: No PDF embed found for '{file_path}'. "
                f"Available: {list(file_path_index.keys())}"
            )}]

        log_prefix = f"[pdf.view] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} user_vault_key_id not available")
            return [{"type": "text", "text": f"Error: Cannot view PDF '{file_path}' — vault key ID not available."}]

        # Limit to MAX_PAGES_PER_CALL
        pages_to_view = pages[:MAX_PAGES_PER_CALL]
        if len(pages) > MAX_PAGES_PER_CALL:
            logger.warning(
                f"{log_prefix} Requested {len(pages)} pages; capping at {MAX_PAGES_PER_CALL}"
            )

        try:
            # --- Step 2: Look up all crypto fields from Redis embed cache ---
            logger.info(f"{log_prefix} Looking up embed content from cache")
            embed_content = await self._lookup_embed_content(embed_id, resolved_vault_key_id)
            # The assistant's turn is held until processing is final; this only guards a stale lookup.
            embed_content = await wait_for_pdf_artefacts(
                lambda: self._lookup_embed_content(embed_id, resolved_vault_key_id),
                ("vault_wrapped_aes_key", "ocr_data_s3_key"),
                initial=embed_content,
                log_prefix=log_prefix,
            )

            filename = embed_content.get("filename") or file_path
            total_pages = int(embed_content.get("page_count") or len(embed_content.get("screenshot_s3_keys") or {}))
            if not embed_content.get("vault_wrapped_aes_key"):
                raise RuntimeError("PDF embed cache missing vault_wrapped_aes_key")

            from backend.apps.pdf.services.page_render_service import get_page_render

            secrets_manager, _ = await self._get_or_create_secrets_manager(
                secrets_manager=kwargs.get("secrets_manager"),
                skill_name="pdf.view",
                error_response_factory=lambda message: message,
                logger=logger,
            )
            if secrets_manager is None:
                raise RuntimeError("Secrets manager unavailable for the page safety check")

            async def _unwrap(wrapped: str) -> bytes:
                return await self._unwrap_aes_key(wrapped, resolved_vault_key_id)

            async def _upload(s3_key: str, content: bytes) -> None:
                await self._upload_artefact(s3_key, content)

            async def _record(page_number: int, s3_key: str) -> None:
                await self._record_screenshot_key(embed_id, resolved_vault_key_id, page_number, s3_key)

            content_blocks: List[Dict[str, Any]] = []
            pages_viewed: List[int] = []
            withheld_pages: List[int] = []

            for page_num in pages_to_view:
                if not 1 <= page_num <= max(total_pages, 1):
                    logger.warning(f"{log_prefix} Page {page_num} is outside the document")
                    continue
                render = await get_page_render(
                    embed_content=embed_content,
                    page_number=page_num,
                    unwrap_key=_unwrap,
                    download=self._download_from_s3,
                    upload=_upload,
                    record_key=_record,
                    secrets_manager=secrets_manager,
                    user_id=str(kwargs.get("user_id") or ""),
                    embed_id=embed_id,
                    log_prefix=log_prefix,
                )
                if render.status != "ok" or render.png is None:
                    withheld_pages.append(page_num)
                    continue
                page_b64 = base64.b64encode(render.png).decode("utf-8")
                content_blocks.append({"type": "text", "text": f"[Page {page_num} of {total_pages}]"})
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{page_b64}", "detail": "high"},
                })
                pages_viewed.append(page_num)

            if withheld_pages:
                content_blocks.append({"type": "text", "text": (
                    f"Pages {', '.join(str(p) for p in withheld_pages)} could not be shown: their image safety "
                    "check was not passed or could not be completed. Use pdf.read for their text."
                )})

            if not pages_viewed:
                return [{"type": "text", "text": f"Error: No valid screenshots found for the requested pages in PDF '{file_path}'."}]

            # Prepend a summary text block so the LLM has context
            pages_label = ", ".join(str(p) for p in pages_viewed)
            summary_block: Dict[str, Any] = {
                "type": "text",
                "text": f"PDF pages {pages_label} from: {filename}",
            }
            content_blocks.insert(0, summary_block)

            logger.info(
                f"{log_prefix} Returning {len(pages_viewed)} page screenshot(s) as multimodal content"
            )
            return content_blocks

        except Exception as e:
            logger.error(f"{log_prefix} pdf.view failed: {e}", exc_info=True)
            return [{"type": "text", "text": f"Error: Failed to load PDF screenshots for '{file_path}' — {e}"}]
