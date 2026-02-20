# backend/apps/pdf/skills/search_skill.py
#
# pdf.search skill — text search across all OCR'd PDF page markdowns.
#
# Architecture:
#   Pure text search (no LLM required). The skill:
#     1. Unwraps the AES key via Vault Transit.
#     2. Downloads and decrypts the OCR JSON blob from S3.
#     3. Performs case-insensitive substring search across all pages.
#     4. Returns matching text blocks with surrounding context and page numbers.
#
#   This is intentionally dumb but fast — the LLM can then call pdf.read
#   on the relevant pages for deeper analysis.

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

DEFAULT_CONTEXT_CHARS = 200  # characters of surrounding context per match
MAX_MATCHES = 50              # cap on number of matches returned


class SearchRequest(BaseModel):
    """Request model for the pdf.search skill."""

    embed_id: str = Field(..., description="The embed_id of the uploaded PDF.")
    vault_wrapped_aes_key: str = Field(
        ..., description="Vault Transit-wrapped AES key from the embed metadata."
    )
    ocr_data_s3_key: str = Field(
        ..., description="S3 key for the encrypted OCR JSON blob."
    )
    s3_base_url: str = Field(..., description="S3 base URL for the file storage bucket.")
    aes_nonce: str = Field(..., description="Base64 AES-GCM nonce.")
    query: str = Field(..., description="The search query string (case-insensitive).")
    context_chars: Optional[int] = Field(
        DEFAULT_CONTEXT_CHARS,
        description="Number of surrounding characters to include per match (default: 200).",
    )
    vault_key_id: Optional[str] = Field(
        None, description="The user's Vault Transit key ID (resolved from context if omitted)."
    )


class SearchMatch(BaseModel):
    """A single search result match."""

    page_num: int = Field(..., description="1-indexed page number containing the match.")
    match_text: str = Field(..., description="The exact matched text snippet.")
    context: str = Field(..., description="Surrounding text context around the match.")
    char_offset: int = Field(..., description="Character offset of the match in the page markdown.")


class SearchResponse(BaseModel):
    """Response model for the pdf.search skill."""

    success: bool = Field(default=False)
    embed_id: Optional[str] = Field(None)
    query: Optional[str] = Field(None)
    total_matches: int = Field(default=0)
    matches: List[SearchMatch] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description="True if more than MAX_MATCHES results exist (only first MAX_MATCHES returned).",
    )
    error: Optional[str] = Field(None)


class SearchSkill(BaseSkill):
    """
    Skill for text searching across all OCR'd markdown in a PDF.

    No LLM call is made — this is a pure substring search, which is fast and
    predictable. The LLM can use the page numbers from results to call pdf.read
    for detailed content.
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

    async def _download_decrypt(
        self, s3_base_url: str, s3_key: str, aes_key: bytes, aes_nonce: str
    ) -> bytes:
        url = f"{s3_base_url.rstrip('/')}/{s3_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"S3 download failed for {s3_key}: HTTP {resp.status_code}")
        nonce = base64.b64decode(aes_nonce)
        aesgcm = AESGCM(aes_key)
        return aesgcm.decrypt(nonce, resp.content, None)

    def _search_page(
        self, page_num: int, text: str, query_lower: str, context_chars: int
    ) -> List[SearchMatch]:
        """
        Find all case-insensitive occurrences of query in text.

        Returns a list of SearchMatch objects for this page.
        """
        matches: List[SearchMatch] = []
        text_lower = text.lower()
        query_len = len(query_lower)
        start = 0

        while True:
            idx = text_lower.find(query_lower, start)
            if idx == -1:
                break

            # Extract context window
            ctx_start = max(0, idx - context_chars)
            ctx_end = min(len(text), idx + query_len + context_chars)
            ctx = text[ctx_start:ctx_end]

            # Prefix/suffix ellipsis if truncated
            if ctx_start > 0:
                ctx = "…" + ctx
            if ctx_end < len(text):
                ctx = ctx + "…"

            matches.append(
                SearchMatch(
                    page_num=page_num,
                    match_text=text[idx: idx + query_len],
                    context=ctx,
                    char_offset=idx,
                )
            )

            start = idx + query_len  # advance past this match

        return matches

    async def execute(
        self,
        embed_id: str,
        vault_wrapped_aes_key: str,
        ocr_data_s3_key: str,
        s3_base_url: str,
        aes_nonce: str,
        query: str,
        context_chars: Optional[int] = DEFAULT_CONTEXT_CHARS,
        vault_key_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Search all OCR'd pages for the given query string.

        Steps:
        1. Resolve vault_key_id.
        2. Unwrap AES key via Vault.
        3. Download + decrypt OCR JSON blob from S3.
        4. Search all pages case-insensitively for query.
        5. Return matches with context.
        """
        log_prefix = f"[pdf.search] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = vault_key_id or kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} vault_key_id not available")
            return SearchResponse(
                success=False,
                embed_id=embed_id,
                error="Cannot decrypt OCR data: vault key ID not available",
            ).dict()

        if not query or not query.strip():
            return SearchResponse(
                success=False,
                embed_id=embed_id,
                error="Search query cannot be empty",
            ).dict()

        ctx_chars = context_chars if context_chars and context_chars > 0 else DEFAULT_CONTEXT_CHARS

        try:
            # Step 1: Unwrap AES key
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)

            # Step 2: Download + decrypt OCR blob
            logger.info(f"{log_prefix} Downloading OCR blob for search: '{query}'")
            plaintext = await self._download_decrypt(
                s3_base_url, ocr_data_s3_key, aes_key_bytes, aes_nonce
            )
            ocr_data = json.loads(plaintext.decode("utf-8"))
            all_pages_data: Dict[str, Any] = ocr_data.get("pages", {})

            query_lower = query.lower().strip()
            all_matches: List[SearchMatch] = []
            truncated = False

            # Search pages in order
            for page_key in sorted(all_pages_data.keys(), key=lambda k: int(k)):
                page_num = int(page_key)
                markdown = all_pages_data[page_key].get("markdown", "")
                page_matches = self._search_page(page_num, markdown, query_lower, ctx_chars)
                all_matches.extend(page_matches)

                if len(all_matches) >= MAX_MATCHES:
                    truncated = True
                    break

            total = len(all_matches)
            returned = all_matches[:MAX_MATCHES]

            logger.info(
                f"{log_prefix} Search for '{query}' found {total} matches "
                f"({'truncated' if truncated else 'complete'})"
            )

            return SearchResponse(
                success=True,
                embed_id=embed_id,
                query=query,
                total_matches=total,
                matches=returned,
                truncated=truncated,
            ).dict()

        except Exception as e:
            logger.error(f"{log_prefix} pdf.search failed: {e}", exc_info=True)
            return SearchResponse(
                success=False,
                embed_id=embed_id,
                query=query,
                error=f"Search failed: {e}",
            ).dict()
