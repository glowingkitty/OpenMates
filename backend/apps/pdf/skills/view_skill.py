# backend/apps/pdf/skills/view_skill.py
#
# pdf.view skill — vision analysis of PDF page screenshots via Gemini Flash.
#
# Architecture:
#   Mirrors the pattern from images/skills/view_skill.py:
#     1. Unwrap AES key via Vault Transit.
#     2. Download + decrypt page screenshot PNG from S3.
#     3. Base64-encode and pass to the AI model as a multimodal vision prompt.
#   Up to 5 pages can be viewed in a single call. Each page screenshot is
#   included as a separate image in the message.
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
    """Response model for the pdf.view skill."""

    success: bool = Field(default=False)
    embed_id: Optional[str] = Field(None)
    pages_viewed: List[int] = Field(default_factory=list)
    analysis: Optional[str] = Field(None)
    error: Optional[str] = Field(None)


class ViewSkill(BaseSkill):
    """
    Skill for visually analysing page screenshots from an uploaded PDF.

    Downloads and decrypts page screenshots from S3, then passes them to the
    Gemini Flash vision model for analysis. Follows the same decrypt+vision
    pattern as images.view.
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
    ) -> Dict[str, Any]:
        """
        Visually analyse page screenshots from a PDF.

        Steps:
        1. Resolve vault_key_id.
        2. Unwrap AES key via Vault.
        3. For each requested page (up to MAX_PAGES_PER_CALL):
           a. Download encrypted screenshot from S3.
           b. Decrypt with AES-256-GCM.
           c. Encode as base64.
        4. Pass all page images + query to vision AI model.
        """
        log_prefix = f"[pdf.view] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available")
            return ViewResponse(
                success=False,
                embed_id=embed_id,
                error="Cannot decrypt screenshots: vault key ID not available",
            ).dict()

        # Limit to MAX_PAGES_PER_CALL
        pages_to_view = pages[:MAX_PAGES_PER_CALL]
        if len(pages) > MAX_PAGES_PER_CALL:
            logger.warning(
                f"{log_prefix} Requested {len(pages)} pages; capping at {MAX_PAGES_PER_CALL}"
            )

        try:
            # Unwrap AES key once
            logger.info(f"{log_prefix} Unwrapping AES key")
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)
            nonce_bytes = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)

            # Build multimodal content for the AI call
            # Start with the text query, then add each page image
            multimodal_content: List[Dict[str, Any]] = [
                {"type": "text", "text": query},
            ]

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
                multimodal_content.append(
                    {
                        "type": "text",
                        "text": f"[Page {page_num}]",
                    }
                )
                multimodal_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{page_b64}",
                            "detail": "high",
                        },
                    }
                )
                pages_viewed.append(page_num)

            if not pages_viewed:
                return ViewResponse(
                    success=False,
                    embed_id=embed_id,
                    error="No valid screenshots found for the requested pages",
                ).dict()

            pages_label = ", ".join(str(p) for p in pages_viewed)
            system_prompt = (
                "You are an expert document analyst with strong visual analysis skills. "
                "You will be shown one or more pages from a PDF document. "
                f"The pages shown are: {pages_label}. "
                "Analyse the visual content carefully and respond to the user's query "
                "with accurate, detailed observations about diagrams, figures, tables, "
                "text layout, and any other visual elements present."
            )

            logger.info(
                f"{log_prefix} Calling vision model for {len(pages_viewed)} pages"
            )
            analysis = await self.call_provider(
                messages=[{"role": "user", "content": multimodal_content}],
                system_prompt=system_prompt,
                **kwargs,
            )

            return ViewResponse(
                success=True,
                embed_id=embed_id,
                pages_viewed=pages_viewed,
                analysis=analysis,
            ).dict()

        except Exception as e:
            logger.error(f"{log_prefix} pdf.view failed: {e}", exc_info=True)
            return ViewResponse(
                success=False,
                embed_id=embed_id,
                error=f"Vision analysis failed: {e}",
            ).dict()
