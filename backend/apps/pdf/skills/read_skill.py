# backend/apps/pdf/skills/read_skill.py
#
# pdf.read skill — loads specific pages from an OCR'd PDF as raw markdown.
#
# Architecture:
#   The LLM invokes this skill with file_path (the original filename, e.g. "report.pdf").
#   The skill then:
#     1. Resolves file_path → embed_id via the file_path_index injected by main_processor.py
#     2. Looks up the embed's encrypted content from the Redis cache (embed:{embed_id})
#     3. Decrypts the embed content using the user's Vault Transit key
#     4. Extracts vault_wrapped_aes_key, ocr_data_s3_key, aes_nonce from the
#        decrypted embed content (these fields are NEVER exposed to the LLM)
#     5. Unwraps the AES key via Vault Transit
#     6. Downloads and decrypts the OCR JSON blob from S3
#     7. Returns the requested pages' markdown, self-limiting to 50K tokens.
#        If the requested pages exceed the budget, it returns what fits and
#        instructs the LLM to call again for the remaining pages.
#
# Token estimation: 1 token ≈ 4 characters (rough approximation).
#
# The OCR JSON blob structure:
#   { "pages": { "1": {"markdown": "...", "images": [...], ...}, "2": {...}, ... } }

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote as url_quote

import httpx
import redis.asyncio as aioredis
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field
from toon_format import decode as toon_decode

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# Maximum output tokens the skill will return in a single call.
# Leaves room for conversation history in the LLM's context window.
MAX_OUTPUT_TOKENS = 50_000
CHARS_PER_TOKEN = 4  # rough approximation


class ReadRequest(BaseModel):
    """
    Request model for the pdf.read skill.
    The LLM provides only the original filename (file_path / embed_ref) — all cryptographic
    and storage details are resolved server-side from the embed cache via the file_path_index.
    """

    file_path: str = Field(
        ...,
        description=(
            "The original filename of the PDF to read (e.g. 'report.pdf'). "
            "Use the exact embed_ref value from the toon block."
        ),
    )
    pages: Optional[List[int]] = Field(
        None,
        description=(
            "1-indexed page numbers to read (e.g. [1, 2, 3]). "
            "If omitted, reads from page 1 onwards up to the token budget."
        ),
    )


class ReadResponse(BaseModel):
    """Response model for the pdf.read skill."""

    success: bool = Field(default=False)
    file_path: Optional[str] = Field(None)
    pages_returned: List[int] = Field(default_factory=list)
    pages_skipped: List[int] = Field(
        default_factory=list,
        description="Pages that were requested but not returned due to the token budget.",
    )
    content: Optional[str] = Field(
        None,
        description="Concatenated markdown content for the returned pages.",
    )
    total_chars: int = Field(default=0)
    continuation_hint: Optional[str] = Field(
        None,
        description=(
            "If pages were skipped, a hint instructing the LLM to call again "
            "with the remaining page numbers."
        ),
    )
    error: Optional[str] = Field(None)


class ReadSkill(BaseSkill):
    """
    Skill for reading markdown text content from specific PDF pages.

    The LLM calls this with file_path (the original filename / embed_ref, e.g. "report.pdf").
    The skill resolves file_path → embed_id UUID via the file_path_index injected by
    main_processor.py, then resolves all crypto and storage details server-side by looking
    up the embed from the Redis cache and decrypting its content via Vault Transit.

    Downloads and decrypts the per-page OCR data from S3, then returns the
    requested pages' markdown capped at MAX_OUTPUT_TOKENS to avoid overwhelming
    the LLM's context window.
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
            ocr_data_s3_key, aes_nonce, etc.).

        Raises:
            RuntimeError: If the embed is not found in cache, has no encrypted
                content, or decryption/decoding fails.
        """
        log_prefix = f"[pdf.read] [embed:{embed_id[:8]}...]"

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

    async def _unwrap_aes_key(
        self, vault_wrapped_aes_key: str, vault_key_id: str
    ) -> bytes:
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
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(
                download_url,
                params={"bucket_key": "chatfiles", "s3_key": s3_key},
                headers={"Authorization": f"Bearer {shared_token}"},
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"S3 download failed for {s3_key}: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        return resp.content

    async def execute(
        self,
        file_path: str,
        pages: Optional[List[int]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Read OCR'd markdown for the requested PDF pages.

        The LLM provides file_path (the original filename / embed_ref, e.g. "report.pdf").
        All cryptographic and storage details are resolved server-side from the Redis cache.

        Steps:
        1. Resolve file_path → embed_id via file_path_index (injected by main_processor).
        2. Look up all crypto fields from the Redis embed cache.
        3. Unwrap AES key via Vault.
        4. Download + decrypt OCR JSON blob from S3.
        5. Return requested pages, self-limiting to MAX_OUTPUT_TOKENS.
        """
        log_prefix = f"[pdf.read] [file_path:{file_path!r}]"

        # --- Step 1: Resolve file_path → embed_id via file_path_index ---
        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}
        embed_id = file_path_index.get(file_path)
        if not embed_id:
            logger.error(
                f"{log_prefix} No embed found for file_path. "
                f"Available keys: {list(file_path_index.keys())}"
            )
            return ReadResponse(
                success=False,
                file_path=file_path,
                error=(
                    f"No PDF embed found for '{file_path}'. "
                    f"Available: {list(file_path_index.keys())}"
                ),
            ).dict()

        log_prefix = f"[pdf.read] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} user_vault_key_id not available")
            return ReadResponse(
                success=False,
                file_path=file_path,
                error="Cannot decrypt PDF data: vault key ID not available",
            ).dict()

        try:
            # --- Step 2: Look up all crypto fields from Redis embed cache ---
            logger.info(f"{log_prefix} Looking up embed content from cache")
            embed_content = await self._lookup_embed_content(embed_id, resolved_vault_key_id)

            vault_wrapped_aes_key = embed_content.get("vault_wrapped_aes_key")
            ocr_data_s3_key = embed_content.get("ocr_data_s3_key")
            aes_nonce = embed_content.get("aes_nonce")

            if not vault_wrapped_aes_key:
                raise RuntimeError("PDF embed cache missing vault_wrapped_aes_key")
            if not ocr_data_s3_key:
                raise RuntimeError("PDF embed cache missing ocr_data_s3_key")
            if not aes_nonce:
                raise RuntimeError("PDF embed cache missing aes_nonce")

            # --- Step 3: Unwrap AES key ---
            logger.info(f"{log_prefix} Unwrapping AES key")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)

            # --- Step 4: Download + decrypt OCR blob ---
            logger.info(f"{log_prefix} Downloading OCR blob: {ocr_data_s3_key}")
            encrypted = await self._download_from_s3(ocr_data_s3_key)
            nonce = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)
            plaintext = aesgcm.decrypt(nonce, encrypted, None)
            ocr_data = json.loads(plaintext.decode("utf-8"))

            # OCR data format: { "pages": { "1": {...}, "2": {...}, ... } }
            all_pages_data: Dict[str, Any] = ocr_data.get("pages", {})

            # Determine which pages to read
            if pages:
                requested = sorted(set(pages))
            else:
                # Default: read from page 1 onwards (let token budget limit output)
                requested = sorted(int(k) for k in all_pages_data.keys())

            # Build output respecting the token budget
            pages_returned: List[int] = []
            pages_skipped: List[int] = []
            content_parts: List[str] = []
            total_chars = 0
            token_budget_chars = MAX_OUTPUT_TOKENS * CHARS_PER_TOKEN

            for page_num in requested:
                page_key = str(page_num)
                page_data = all_pages_data.get(page_key)
                if not page_data:
                    logger.warning(f"{log_prefix} Page {page_num} not found in OCR data")
                    pages_skipped.append(page_num)
                    continue

                md = page_data.get("markdown", "").strip()
                page_text = f"### Page {page_num}\n\n{md}"
                page_chars = len(page_text)

                if total_chars + page_chars > token_budget_chars:
                    # Budget exceeded — skip remaining pages
                    pages_skipped.append(page_num)
                else:
                    content_parts.append(page_text)
                    pages_returned.append(page_num)
                    total_chars += page_chars

            # Pages after the first skipped page are also skipped
            if pages_skipped:
                first_skip = pages_skipped[0]
                for pn in requested:
                    if pn > first_skip and pn not in pages_skipped and pn not in pages_returned:
                        pages_skipped.append(pn)

            content = "\n\n---\n\n".join(content_parts) if content_parts else None

            continuation_hint = None
            if pages_skipped:
                continuation_hint = (
                    f"Token budget reached. Pages not returned: {sorted(pages_skipped)}. "
                    f"Call pdf.read again with pages={sorted(pages_skipped)} to read them."
                )

            logger.info(
                f"{log_prefix} Returning {len(pages_returned)} pages, "
                f"{len(pages_skipped)} skipped, {total_chars} chars"
            )

            return ReadResponse(
                success=True,
                file_path=file_path,
                pages_returned=pages_returned,
                pages_skipped=sorted(pages_skipped),
                content=content,
                total_chars=total_chars,
                continuation_hint=continuation_hint,
            ).dict()

        except Exception as e:
            logger.error(f"{log_prefix} pdf.read failed: {e}", exc_info=True)
            return ReadResponse(
                success=False,
                file_path=file_path,
                error=f"Failed to read PDF pages: {e}",
            ).dict()
