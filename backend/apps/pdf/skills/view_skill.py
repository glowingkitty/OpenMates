# backend/apps/pdf/skills/view_skill.py
#
# pdf.view skill — returns PDF page screenshots as multimodal content blocks.
#
# Architecture:
#   Mirrors the pattern from images/skills/view_skill.py:
#     1. Unwrap AES key via Vault Transit.
#     2. Download + decrypt page screenshot PNGs from S3.
#     3. Return a list of content blocks (text labels + image_url blocks)
#        so the MAIN inference model sees the page screenshots directly.
#
#   Key architectural change from previous approach:
#     - Previously: skill called Gemini Flash internally and returned a text
#       analysis string. The main model never saw the page images.
#     - Now: skill returns multimodal content blocks. The framework
#       (llm_utils.py + provider adapters) passes them to the main LLM.
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
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

MAX_PAGES_PER_CALL = 5  # Vision calls with too many images get slow/expensive


class ViewRequest(BaseModel):
    """Request model for the pdf.view skill."""

    embed_id: str = Field(..., description="The embed_id of the uploaded PDF.")
    vault_wrapped_aes_key: str = Field(
        ..., description="Vault Transit-wrapped AES key from the embed metadata."
    )
    screenshot_s3_keys: Dict[str, str] = Field(
        ...,
        description=(
            "Map of 1-indexed page numbers (as strings) to S3 keys for encrypted page screenshots. "
            'Example: {"1": "chatfiles/.../page_1.bin"}'
        ),
    )
    s3_base_url: str = Field(..., description="S3 base URL for the file storage bucket.")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce.")
    pages: List[int] = Field(
        ..., description=f"1-indexed page numbers to view (max {MAX_PAGES_PER_CALL})."
    )
    query: str = Field(..., description="The user's question or instruction about the page(s).")
    vault_key_id: Optional[str] = Field(
        None, description="The user's Vault Transit key ID (resolved from context if omitted)."
    )


class ViewResponse(BaseModel):
    """
    Response model for the pdf.view skill (for OpenAPI docs).

    At runtime, execute() returns a List of content blocks (not this model),
    which the framework forwards as a multimodal tool result to the main LLM.
    This model exists only to document the skill's output shape in the REST API.
    """

    success: bool = Field(default=False)
    embed_id: Optional[str] = Field(None)
    pages_viewed: List[int] = Field(default_factory=list)
    error: Optional[str] = Field(None)


class ViewSkill(BaseSkill):
    """
    Skill for loading page screenshots from an uploaded PDF and returning
    them as multimodal content blocks so the main inference model can see them.

    Downloads and decrypts page screenshots from S3, then returns them as
    image_url blocks (with page labels) in a content list. The framework's
    llm_utils.py passes the list through to the provider adapters unchanged.
    """

    VAULT_TOKEN_PATH: str = "/vault-data/api.token"

    def _load_vault_token(self) -> str:
        with open(self.VAULT_TOKEN_PATH) as f:
            token = f.read().strip()
        if not token:
            raise RuntimeError("Vault token file is empty")
        return token

    async def _unwrap_aes_key(self, vault_wrapped_aes_key: str, vault_key_id: str) -> bytes:
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

    async def _download_from_s3(self, s3_base_url: str, s3_key: str) -> bytes:
        url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"S3 download failed for {s3_key}: HTTP {resp.status_code}")
        return resp.content

    async def execute(
        self,
        embed_id: str,
        vault_wrapped_aes_key: str,
        screenshot_s3_keys: Dict[str, str],
        s3_base_url: str,
        aes_nonce: str,
        pages: List[int],
        query: str,
        vault_key_id: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Load page screenshots from a PDF and return them as a multimodal content list.

        Returns a list of content blocks that will become the tool result
        passed directly to the main inference model:
          [
            {"type": "text", "text": "PDF pages 1, 2 from: <filename>"},
            {"type": "text", "text": "[Page 1 of 12]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            {"type": "text", "text": "[Page 2 of 12]"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ...
          ]

        Steps:
        1. Resolve vault_key_id.
        2. Unwrap AES key via Vault.
        3. For each requested page (up to MAX_PAGES_PER_CALL):
           a. Download encrypted screenshot from S3.
           b. Decrypt with AES-256-GCM.
           c. Encode as base64 and add to content blocks.
        4. Return the content list.

        Args:
            embed_id: Embed ID of the PDF.
            vault_wrapped_aes_key: Vault-wrapped AES key from embed content.
            screenshot_s3_keys: Map of page number strings → S3 keys.
            s3_base_url: S3 bucket base URL.
            aes_nonce: Base64 AES-GCM nonce.
            pages: 1-indexed page numbers to view (capped at MAX_PAGES_PER_CALL).
            query: The user's question about the pages (not used here — the
                   main LLM processes it after seeing the pages in the tool result).
            vault_key_id: Optional Vault key ID; falls back to kwargs['user_vault_key_id'].
            **kwargs: Additional context (user_id, user_vault_key_id, filename, etc.).

        Returns:
            List of content blocks for multimodal tool result, or error message block.
        """
        log_prefix = f"[pdf.view] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available")
            return [{"type": "text", "text": f"Error: Cannot view PDF {embed_id} — vault key ID not available."}]

        # Limit to MAX_PAGES_PER_CALL
        pages_to_view = pages[:MAX_PAGES_PER_CALL]
        if len(pages) > MAX_PAGES_PER_CALL:
            logger.warning(
                f"{log_prefix} Requested {len(pages)} pages; capping at {MAX_PAGES_PER_CALL}"
            )

        # Determine total page count for labels (from screenshot_s3_keys keys)
        total_pages = len(screenshot_s3_keys)

        try:
            # Unwrap AES key once
            logger.info(f"{log_prefix} Unwrapping AES key")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)
            nonce_bytes = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)

            # Build multimodal content blocks
            content_blocks: List[Dict[str, Any]] = []
            pages_viewed: List[int] = []

            for page_num in pages_to_view:
                s3_key = screenshot_s3_keys.get(str(page_num))
                if not s3_key:
                    logger.warning(f"{log_prefix} No screenshot S3 key for page {page_num}")
                    continue

                logger.info(f"{log_prefix} Downloading screenshot for page {page_num}")
                encrypted = await self._download_from_s3(s3_base_url, s3_key)
                plaintext = aesgcm.decrypt(nonce_bytes, encrypted, None)

                page_b64 = base64.b64encode(plaintext).decode("utf-8")

                # Page label so LLM knows which page it is looking at
                content_blocks.append({
                    "type": "text",
                    "text": f"[Page {page_num} of {total_pages}]",
                })
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{page_b64}",
                        "detail": "high",
                    },
                })
                pages_viewed.append(page_num)

            if not pages_viewed:
                return [{"type": "text", "text": f"Error: No valid screenshots found for the requested pages in PDF {embed_id}."}]

            # Prepend a summary text block so the LLM has context
            filename = kwargs.get("filename") or embed_id
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
            return [{"type": "text", "text": f"Error: Failed to load PDF screenshots for {embed_id} — {e}"}]
