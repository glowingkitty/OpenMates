# backend/apps/pdf/skills/search_skill.py
#
# pdf.search skill — text search across all OCR'd PDF page markdowns.
#
# Architecture:
#   The LLM calls this skill with file_path (the original filename, e.g. "report.pdf").
#   The skill then:
#     1. Resolves file_path → embed_id via the file_path_index injected by main_processor.py
#     2. Looks up the embed's encrypted content from the Redis cache (embed:{embed_id})
#     3. Decrypts the embed content using the user's Vault Transit key
#     4. Extracts vault_wrapped_aes_key, ocr_data_s3_key, aes_nonce from the
#        decrypted embed content (these fields are NEVER exposed to the LLM)
#     5. Unwraps the AES key via Vault Transit
#     6. Downloads and decrypts the OCR JSON blob from S3
#     7. Performs case-insensitive substring search across all pages
#     8. Returns matching text blocks with surrounding context and page numbers
#
#   This is intentionally dumb but fast — the LLM can then call pdf.read
#   on the relevant pages for deeper analysis.

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

DEFAULT_CONTEXT_CHARS = 200  # characters of surrounding context per match
MAX_MATCHES = 50              # cap on number of matches returned


class SearchRequest(BaseModel):
    """
    Request model for the pdf.search skill.
    The LLM provides only the original filename (file_path / embed_ref) — all cryptographic
    and storage details are resolved server-side from the embed cache via the file_path_index.
    """

    file_path: str = Field(
        ...,
        description=(
            "The original filename of the PDF to search (e.g. 'report.pdf'). "
            "Use the exact embed_ref value from the toon block."
        ),
    )
    query: str = Field(..., description="The search query string (case-insensitive).")
    context_chars: Optional[int] = Field(
        DEFAULT_CONTEXT_CHARS,
        description="Number of surrounding characters to include per match (default: 200).",
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
    file_path: Optional[str] = Field(None)
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

    The LLM calls this with file_path (the original filename / embed_ref, e.g. "report.pdf").
    The skill resolves file_path → embed_id UUID via the file_path_index injected by
    main_processor.py, then resolves all crypto and storage details server-side by looking
    up the embed from the Redis cache and decrypting its content via Vault Transit.

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
        log_prefix = f"[pdf.search] [embed:{embed_id[:8]}...]"

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
        async with httpx.AsyncClient(timeout=120) as client:
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
        file_path: str,
        query: str,
        context_chars: Optional[int] = DEFAULT_CONTEXT_CHARS,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Search all OCR'd pages for the given query string.

        The LLM provides file_path (the original filename / embed_ref, e.g. "report.pdf").
        All cryptographic and storage details are resolved server-side from the Redis cache.

        Steps:
        1. Resolve file_path → embed_id via file_path_index (injected by main_processor).
        2. Look up all crypto fields from the Redis embed cache.
        3. Unwrap AES key via Vault.
        4. Download + decrypt OCR JSON blob from S3.
        5. Search all pages case-insensitively for query.
        6. Return matches with context.
        """
        log_prefix = f"[pdf.search] [file_path:{file_path!r}]"

        # --- Step 1: Resolve file_path → embed_id via file_path_index ---
        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}
        embed_id = file_path_index.get(file_path)
        if not embed_id:
            logger.error(
                f"{log_prefix} No embed found for file_path. "
                f"Available keys: {list(file_path_index.keys())}"
            )
            return SearchResponse(
                success=False,
                file_path=file_path,
                query=query,
                error=(
                    f"No PDF embed found for '{file_path}'. "
                    f"Available: {list(file_path_index.keys())}"
                ),
            ).dict()

        log_prefix = f"[pdf.search] [embed:{embed_id[:8]}...]"

        resolved_vault_key_id = kwargs.get("user_vault_key_id")
        if not resolved_vault_key_id:
            logger.error(f"{log_prefix} user_vault_key_id not available")
            return SearchResponse(
                success=False,
                file_path=file_path,
                query=query,
                error="Cannot decrypt PDF data: vault key ID not available",
            ).dict()

        if not query or not query.strip():
            return SearchResponse(
                success=False,
                file_path=file_path,
                query=query,
                error="Search query cannot be empty",
            ).dict()

        ctx_chars = context_chars if context_chars and context_chars > 0 else DEFAULT_CONTEXT_CHARS

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
            aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, resolved_vault_key_id)

            # --- Step 4: Download + decrypt OCR blob ---
            logger.info(f"{log_prefix} Downloading OCR blob for search: '{query}'")
            encrypted = await self._download_from_s3(ocr_data_s3_key)
            nonce = base64.b64decode(aes_nonce)
            aesgcm = AESGCM(aes_key_bytes)
            plaintext = aesgcm.decrypt(nonce, encrypted, None)
            ocr_data = json.loads(plaintext.decode("utf-8"))
            all_pages_data: Dict[str, Any] = ocr_data.get("pages", {})

            query_lower = query.lower().strip()
            all_matches: List[SearchMatch] = []
            truncated = False

            # --- Step 5: Search pages in order ---
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
                file_path=file_path,
                query=query,
                total_matches=total,
                matches=returned,
                truncated=truncated,
            ).dict()

        except Exception as e:
            logger.error(f"{log_prefix} pdf.search failed: {e}", exc_info=True)
            return SearchResponse(
                success=False,
                file_path=file_path,
                query=query,
                error=f"Search failed: {e}",
            ).dict()
