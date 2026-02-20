# backend/apps/pdf/skills/read_skill.py
#
# pdf.read skill — loads specific pages from an OCR'd PDF as raw markdown.
#
# Architecture:
#   The LLM invokes this skill when it wants to read the text content of
#   specific PDF pages. The skill:
#     1. Unwraps the AES key via Vault Transit.
#     2. Downloads and decrypts the OCR JSON blob from S3.
#     3. Returns the requested pages' markdown, self-limiting to 50K tokens.
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

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

# Maximum output tokens the skill will return in a single call.
# Leaves room for conversation history in the LLM's context window.
MAX_OUTPUT_TOKENS = 50_000
CHARS_PER_TOKEN = 4  # rough approximation


class ReadRequest(BaseModel):
    """Request model for the pdf.read skill."""

    embed_id: str = Field(..., description="The embed_id of the uploaded PDF.")
    vault_wrapped_aes_key: str = Field(
        ...,
        description="Vault Transit-wrapped AES key from the embed metadata.",
    )
    ocr_data_s3_key: str = Field(
        ...,
        description="S3 key for the encrypted OCR JSON blob produced during background processing.",
    )
    s3_base_url: str = Field(..., description="S3 base URL for the file storage bucket.")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce.")
    pages: Optional[List[int]] = Field(
        None,
        description=(
            "1-indexed page numbers to read (e.g. [1, 2, 3]). "
            "If omitted, reads from page 1 onwards up to the token budget."
        ),
    )
    vault_key_id: Optional[str] = Field(
        None,
        description="The user's Vault Transit key ID (resolved from context if omitted).",
    )


class ReadResponse(BaseModel):
    """Response model for the pdf.read skill."""

    success: bool = Field(default=False)
    embed_id: Optional[str] = Field(None)
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

    async def _unwrap_aes_key(
        self, vault_wrapped_aes_key: str, vault_key_id: str
    ) -> bytes:
        """Unwrap AES key via Vault Transit."""
        vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        token = self._load_vault_token()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{vault_url}/v1/transit/decrypt/{vault_key_id}",
                json={"ciphertext": vault_wrapped_aes_key},
                headers={"X-Vault-Token": token},
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Vault transit decrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        return base64.b64decode(resp.json()["data"]["plaintext"])

    async def _download_decrypt(
        self, s3_base_url: str, s3_key: str, aes_key: bytes, aes_nonce: str
    ) -> bytes:
        """Download and decrypt an S3 object."""
        url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"S3 download failed for {s3_key}: HTTP {resp.status_code}")
        nonce = base64.b64decode(aes_nonce)
        aesgcm = AESGCM(aes_key)
        return aesgcm.decrypt(nonce, resp.content, None)

    async def execute(
        self,
        embed_id: str,
        vault_wrapped_aes_key: str,
        ocr_data_s3_key: str,
        s3_base_url: str,
        aes_nonce: str,
        pages: Optional[List[int]] = None,
        vault_key_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Read OCR'd markdown for the requested PDF pages.

        Steps:
        1. Resolve vault_key_id.
        2. Unwrap AES key via Vault.
        3. Download + decrypt OCR JSON blob from S3.
        4. Return requested pages, self-limiting to MAX_OUTPUT_TOKENS.
        """
        log_prefix = f"[pdf.read] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available")
            return ReadResponse(
                success=False,
                embed_id=embed_id,
                error="Cannot decrypt OCR data: vault key ID not available",
            ).dict()

        try:
            # Step 1: Unwrap AES key
            logger.info(f"{log_prefix} Unwrapping AES key")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)

            # Step 2: Download + decrypt OCR blob
            logger.info(f"{log_prefix} Downloading OCR blob: {ocr_data_s3_key}")
            plaintext = await self._download_decrypt(
                s3_base_url, ocr_data_s3_key, aes_key_bytes, aes_nonce
            )
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

            # Pages after first skipped page are also skipped
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
                embed_id=embed_id,
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
                embed_id=embed_id,
                error=f"Failed to read PDF pages: {e}",
            ).dict()
