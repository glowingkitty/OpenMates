# backend/apps/images/skills/search_skill.py
#
# Images search skill — finds images via text query or reverse image search.
#
# Architecture:
#   Two search modes:
#     1. Text query → Brave Search Images API (/res/v1/images/search)
#     2. Image input (embed_ref) → SerpAPI Google Lens reverse image search
#
#   For reverse image search with user-uploaded images:
#     - The image is stored encrypted on private S3.
#     - This skill downloads + decrypts the image server-side (same as view_skill).
#     - The plaintext bytes are temporarily uploaded to the public `temp_images` bucket
#       via the internal API route POST /internal/s3/upload-temp-image.
#     - The resulting public URL is passed to SerpAPI Google Lens.
#     - After the search completes, the temp image is deleted immediately.
#       The 1-day S3 lifecycle policy is a safety net for any failures.
#
#   For image search results (search-result child embeds):
#     - The child embed stores image_url (the external full-res URL) and thumbnail_url.
#     - The embed_ref for a search result resolves to an embed with `image_url` set.
#     - When the LLM calls this skill with the embed_ref of a result image, the skill
#       detects the `image_url` field in the resolved embed and passes it directly to
#       Google Lens — no temp upload needed since the URL is already public.
#
#   Output:
#     - Parent app_skill_use embed with child image_result embeds.
#     - Each child embed stores: title, image_url, thumbnail_url, source_page_url, source,
#       favicon_url (all external URLs — no S3 storage for search results).
#     - The frontend proxies thumbnails via preview.openmates.org to protect user IP.
#
#   See docs/architecture/app-skills.md for skill execution model details.
# Tests: backend/tests/apps/images/test_search_skill.py (TODO)

import base64
import json as json_lib
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Maximum number of image results per request
MAX_IMAGE_RESULTS = 20
# Default number of image results
DEFAULT_IMAGE_RESULTS = 10
# Maximum number of parallel search requests in a single skill call
MAX_PARALLEL_REQUESTS = 5
# Image content type returned by S3 decrypt (WEBP from our storage pipeline)
DECRYPTED_IMAGE_CONTENT_TYPE = "image/webp"
# Timeout for internal API calls (temp upload + delete)
INTERNAL_API_TIMEOUT_SECONDS = 30


# ── Pydantic models (auto-discovered by apps_api.py for OpenAPI docs) ────────

class ImageSearchRequestItem(BaseModel):
    """A single image search request (text or reverse image search)."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: Optional[str] = Field(
        default=None,
        description="Text description of images to search for (e.g. 'sunset over mountains'). "
        "Mutually exclusive with file_path.",
    )
    file_path: Optional[str] = Field(
        default=None,
        description="The original filename (embed_ref) of an image in the conversation to "
        "reverse-search. Mutually exclusive with query.",
    )
    count: int = Field(default=6, description="Number of image results to return (default 6, max 20).")
    country: str = Field(default="us", description="Country code for localised results (default 'us').")
    search_lang: str = Field(default="en", description="Language code for search (default 'en').")
    size: Optional[str] = Field(
        default=None,
        description="Filter by image size: 'small', 'medium', 'large', 'wallpaper'.",
    )
    image_type: Optional[str] = Field(
        default=None,
        description="Filter by image type: 'photo', 'clipart', 'gif', 'transparent', 'line'.",
    )
    color: Optional[str] = Field(
        default=None,
        description="Filter by dominant color: 'red', 'orange', 'yellow', 'green', 'blue', "
        "'purple', 'pink', 'brown', 'black', 'gray', 'white', 'coloronly', 'monochrome'.",
    )


class SearchRequest(BaseModel):
    """
    Request model for the images.search skill.
    Always uses 'requests' array for parallel processing consistency.
    Each request must have either 'query' (text search) or 'file_path' (reverse image search).
    """
    requests: List[ImageSearchRequestItem] = Field(
        ...,
        description=(
            "Array of image search request objects. Each object must contain either "
            "'query' (text image search) or 'file_path' (reverse image search using an "
            "uploaded image's embed_ref). Optional: 'count' (default 6, max 20), "
            "'country' (default 'us'), 'search_lang' (default 'en')."
        ),
    )


class SearchResponse(BaseModel):
    """Response model for the images.search skill."""
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of result groups. Each entry has 'id' and 'results' array.",
    )
    provider: str = Field(
        default="Brave Search",
        description="The search provider used.",
    )
    error: Optional[str] = Field(None, description="Error message if search failed.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "thumbnail_url",
            "favicon_url",
            "image_width",
            "image_height",
            "thumbnail_width",
            "thumbnail_height",
        ],
        description="Fields stripped before LLM sees the results (URLs / dimensions).",
    )


# ── Skill implementation ─────────────────────────────────────────────────────

class SearchSkill(BaseSkill):
    """
    Skill that searches for images either by text query or by reverse image search.

    Text mode: Calls Brave Search Images API for the given text query.
    Reverse mode: Decrypts the referenced image server-side, uploads it temporarily to
                  a public S3 bucket, calls SerpAPI Google Lens, then deletes the temp file.

    Results are returned as child embeds (has_children=true in app.yml) so the frontend
    renders a parent card with a scrollable image grid fullscreen.
    """

    # ── Shared infrastructure helpers ────────────────────────────────────────

    VAULT_TOKEN_PATH: str = "/vault-data/api.token"

    def _load_vault_token(self) -> str:
        """Load the Vault service token from the mounted token file."""
        with open(self.VAULT_TOKEN_PATH, "r") as f:
            token = f.read().strip()
        if not token:
            raise RuntimeError("Vault token file is empty")
        return token

    async def _resolve_embed_content(
        self, embed_id: str, user_vault_key_id: str
    ) -> Dict[str, Any]:
        """
        Look up and decrypt an embed's content from the Redis cache.

        Identical flow to view_skill._lookup_embed_content — decrypt via Vault Transit,
        TOON-decode, return the content dict.
        """
        import redis.asyncio as aioredis
        from toon_format import decode as toon_decode
        from urllib.parse import quote as url_quote

        redis_password = os.environ.get("DRAGONFLY_PASSWORD", "")
        redis_url = f"redis://default:{url_quote(redis_password, safe='')}@cache:6379/0"
        redis_client = aioredis.from_url(redis_url, decode_responses=True)

        try:
            cache_key = f"embed:{embed_id}"
            embed_json = await redis_client.get(cache_key)
            if not embed_json:
                raise RuntimeError(
                    f"Embed {embed_id} not found in cache. "
                    "Please re-upload the image or perform a new image search."
                )

            embed_data = json_lib.loads(embed_json)
            encrypted_content = embed_data.get("encrypted_content")
            if not encrypted_content:
                raise RuntimeError(f"Embed {embed_id} has no encrypted_content in cache")

            vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
            token = self._load_vault_token()
            decrypt_url = f"{vault_url}/v1/transit/decrypt/{user_vault_key_id}"
            context = base64.b64encode(user_vault_key_id.encode()).decode("utf-8")
            payload = {"ciphertext": encrypted_content, "context": context}

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    decrypt_url,
                    json=payload,
                    headers={"X-Vault-Token": token},
                )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Vault transit decrypt failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )

            plaintext_b64 = resp.json()["data"]["plaintext"]
            plaintext_toon = base64.b64decode(plaintext_b64).decode("utf-8")
            decoded = toon_decode(plaintext_toon)
            if not isinstance(decoded, dict):
                raise RuntimeError(
                    f"Embed content decoded to {type(decoded).__name__}, expected dict"
                )
            return decoded

        finally:
            await redis_client.aclose()

    async def _unwrap_aes_key(self, vault_wrapped_aes_key: str, vault_key_id: str) -> bytes:
        """Unwrap a Vault Transit-wrapped AES key to recover the raw key bytes."""
        vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        token = self._load_vault_token()
        decrypt_url = f"{vault_url}/v1/transit/decrypt/{vault_key_id}"
        context = base64.b64encode(vault_key_id.encode()).decode("utf-8")
        payload = {"ciphertext": vault_wrapped_aes_key, "context": context}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                decrypt_url, json=payload, headers={"X-Vault-Token": token}
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Vault transit decrypt failed for key {vault_key_id}: "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )

        aes_key_b64 = base64.b64decode(resp.json()["data"]["plaintext"]).decode("utf-8")
        return base64.b64decode(aes_key_b64)

    async def _download_from_s3(self, s3_base_url: str, s3_key: str) -> bytes:
        """Download an encrypted file from S3 via the internal API."""
        download_url = (
            f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}"
            "/internal/s3/download"
        )
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

    async def _decrypt_image_bytes(
        self,
        embed_content: Dict[str, Any],
        user_vault_key_id: str,
    ) -> bytes:
        """
        Decrypt an uploaded image from S3 and return the plaintext bytes.

        Uses the vault_wrapped_aes_key in embed_content to unwrap the AES key,
        downloads the encrypted blob from S3, and decrypts with AES-256-GCM.
        Prefers 'full' variant (highest quality without being the raw original).
        """
        vault_wrapped_aes_key = embed_content.get("vault_wrapped_aes_key")
        s3_base_url = embed_content.get("s3_base_url")
        aes_nonce = embed_content.get("aes_nonce")
        files = embed_content.get("files", {})

        if not vault_wrapped_aes_key:
            raise RuntimeError("Embed content missing vault_wrapped_aes_key")
        if not s3_base_url:
            raise RuntimeError("Embed content missing s3_base_url")
        if not aes_nonce:
            raise RuntimeError("Embed content missing aes_nonce")

        s3_key = None
        for variant_name in ("full", "original", "preview"):
            variant = files.get(variant_name)
            if variant and variant.get("s3_key"):
                s3_key = variant["s3_key"]
                logger.info("[images.search] Using '%s' variant: %s", variant_name, s3_key)
                break

        if not s3_key:
            raise RuntimeError(
                f"Embed content has no file variants with s3_key "
                f"(available: {list(files.keys())})"
            )

        aes_key_bytes = await self._unwrap_aes_key(vault_wrapped_aes_key, user_vault_key_id)
        encrypted_bytes = await self._download_from_s3(s3_base_url, s3_key)
        nonce_bytes = base64.b64decode(aes_nonce)
        aesgcm = AESGCM(aes_key_bytes)
        return aesgcm.decrypt(nonce_bytes, encrypted_bytes, None)

    async def _upload_temp_public_image(
        self, image_bytes: bytes, content_type: str
    ) -> tuple[str, str]:
        """
        Upload plaintext image bytes to the temporary public S3 bucket.

        Returns (public_url, s3_key) — the public URL for Google Lens and the
        S3 key needed to delete the file after the search.

        The temp_images bucket is public-read with a 1-day lifecycle policy.
        The s3_key uses a random UUID prefix so the URL cannot be guessed.
        """
        ext_map = {
            "image/webp": "webp",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
        }
        ext = ext_map.get(content_type, "webp")
        filename = f"{uuid.uuid4().hex[:16]}.{ext}"

        upload_url = (
            f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}"
            "/internal/s3/upload-temp-image"
        )
        shared_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")

        payload = {
            "image_bytes_b64": base64.b64encode(image_bytes).decode("utf-8"),
            "content_type": content_type,
            "filename": filename,
        }

        async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                upload_url,
                json=payload,
                headers={"X-Internal-Service-Token": shared_token},
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Temp image upload failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )

        data = resp.json()
        return data["public_url"], data["s3_key"]

    async def _delete_temp_public_image(self, s3_key: str) -> None:
        """Delete a previously uploaded temporary public image. Best-effort — never raises."""
        delete_url = (
            f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}"
            "/internal/s3/temp-image"
        )
        shared_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
        try:
            async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT_SECONDS) as client:
                resp = await client.delete(
                    delete_url,
                    params={"s3_key": s3_key},
                    headers={"X-Internal-Service-Token": shared_token},
                )
            if resp.status_code not in (200, 204):
                logger.warning(
                    "[images.search] Temp image delete returned %d for key %s",
                    resp.status_code, s3_key,
                )
        except Exception as exc:
            # Best-effort cleanup — the 1-day lifecycle policy is the safety net
            logger.warning(
                "[images.search] Failed to delete temp image %s: %s", s3_key, exc
            )

    # ── Search mode implementations ─────────────────────────────────────────

    async def _text_search(
        self,
        query: str,
        secrets_manager: SecretsManager,
        count: int = DEFAULT_IMAGE_RESULTS,
        country: str = "us",
        search_lang: str = "en",
        size: Optional[str] = None,
        image_type: Optional[str] = None,
        color: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Search for images via Brave Search Images API.

        Returns (results_list, provider_name).
        """
        from backend.shared.providers.brave.brave_search import search_images

        response = await search_images(
            query=query,
            secrets_manager=secrets_manager,
            count=min(count, MAX_IMAGE_RESULTS),
            country=country,
            search_lang=search_lang,
            size=size,
            image_type=image_type,
            color=color,
        )

        if response.get("error"):
            raise RuntimeError(f"Brave image search failed: {response['error']}")

        return response.get("results", []), "Brave Search"

    async def _reverse_image_search(
        self,
        image_url: str,
        secrets_manager: SecretsManager,
        query: Optional[str] = None,
        count: int = DEFAULT_IMAGE_RESULTS,
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Reverse-search an image via SerpAPI Google Lens.

        image_url must be a publicly accessible URL.
        Returns (results_list, provider_name).
        """
        from backend.shared.providers.serpapi import google_lens_reverse_search

        response = await google_lens_reverse_search(
            image_url=image_url,
            secrets_manager=secrets_manager,
            query=query,
            max_results=min(count, MAX_IMAGE_RESULTS),
        )

        if response.get("error"):
            raise RuntimeError(f"Google Lens reverse search failed: {response['error']}")

        return response.get("results", []), "Google Lens"

    # ── Single-request processor ─────────────────────────────────────────────

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        file_path_index: Dict[str, str],
        user_vault_key_id: Optional[str],
    ) -> tuple[Any, List[Dict[str, Any]], str, Optional[str]]:
        """
        Process one search request and return (request_id, results, provider, error_msg).

        Routing:
        - 'file_path' present → resolve embed → check if it has 'image_url' (search result)
          or S3 files (uploaded image) → reverse image search via Google Lens.
        - 'query' only → text image search via Brave.
        """
        query: Optional[str] = req.get("query")
        file_path: Optional[str] = req.get("file_path")
        count: int = min(int(req.get("count", DEFAULT_IMAGE_RESULTS)), MAX_IMAGE_RESULTS)
        country: str = req.get("country", "us")
        search_lang: str = req.get("search_lang", "en")

        log_prefix = f"[images.search] [req:{request_id}]"

        try:
            if file_path:
                # ── Reverse image search ──────────────────────────────────────
                if not user_vault_key_id:
                    raise RuntimeError(
                        "user_vault_key_id not available — cannot resolve image embed for reverse search"
                    )

                embed_id = file_path_index.get(file_path)
                if not embed_id:
                    raise RuntimeError(
                        f"file_path '{file_path}' not found in file_path_index "
                        f"(available: {list(file_path_index.keys())})"
                    )

                logger.info(
                    "%s Resolving embed %s for reverse image search", log_prefix, embed_id[:8]
                )
                embed_content = await self._resolve_embed_content(embed_id, user_vault_key_id)

                # Determine if this embed is a search-result child (has image_url field)
                # or an uploaded/generated image (has S3 files + AES keys).
                image_url_field = embed_content.get("image_url")

                if image_url_field:
                    # Search result child embed — image_url is already a public URL
                    logger.info(
                        "%s Using public image_url from search result embed: %s",
                        log_prefix, str(image_url_field)[:80],
                    )
                    results, provider = await self._reverse_image_search(
                        image_url=str(image_url_field),
                        secrets_manager=secrets_manager,
                        query=query,
                        count=count,
                    )
                else:
                    # Uploaded/generated image — decrypt from private S3,
                    # upload to temp public bucket, call Google Lens, delete temp file.
                    logger.info(
                        "%s Decrypting uploaded image for reverse search", log_prefix
                    )
                    image_bytes = await self._decrypt_image_bytes(
                        embed_content, user_vault_key_id
                    )
                    logger.info(
                        "%s Uploading %d bytes to temp public bucket", log_prefix, len(image_bytes)
                    )
                    public_url, temp_s3_key = await self._upload_temp_public_image(
                        image_bytes, DECRYPTED_IMAGE_CONTENT_TYPE
                    )
                    logger.info(
                        "%s Calling Google Lens with temp URL: %s", log_prefix, public_url[:80]
                    )
                    try:
                        results, provider = await self._reverse_image_search(
                            image_url=public_url,
                            secrets_manager=secrets_manager,
                            query=query,
                            count=count,
                        )
                    finally:
                        # Always clean up the temp file, even on error
                        await self._delete_temp_public_image(temp_s3_key)

            elif query:
                # ── Text image search ────────────────────────────────────────
                logger.info("%s Text image search: '%s'", log_prefix, query[:80])
                results, provider = await self._text_search(
                    query=query,
                    secrets_manager=secrets_manager,
                    count=count,
                    country=country,
                    search_lang=search_lang,
                    size=req.get("size"),
                    image_type=req.get("image_type"),
                    color=req.get("color"),
                )
            else:
                raise ValueError("Each request must have either 'query' or 'file_path'")

            # Inject result hashes for dedup tracking
            for result in results:
                if not result.get("hash"):
                    result["hash"] = self._generate_result_hash(
                        result.get("image_url") or result.get("source_page_url") or ""
                    )

            logger.info(
                "%s Completed: %d results via %s", log_prefix, len(results), provider
            )
            return request_id, results, provider, None

        except Exception as exc:
            logger.error(
                "%s Search failed: %s", log_prefix, exc, exc_info=True
            )
            return request_id, [], "Unknown", str(exc)

    # ── Main execute ─────────────────────────────────────────────────────────

    async def execute(
        self,
        request: SearchRequest,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs: Any,
    ) -> SearchResponse:
        """
        Execute the images search skill.

        Processes all requests in parallel (up to MAX_PARALLEL_REQUESTS = 5).
        Returns a SearchResponse with results grouped by request ID.

        Args:
            request: SearchRequest with 'requests' array. Each element must have
                     'query' (text search) or 'file_path' (reverse image search).
            secrets_manager: Injected by BaseApp for provider API key resolution.
            **kwargs: Pipeline context (file_path_index, user_vault_key_id, etc.).
        """
        # Get or create SecretsManager using BaseSkill helper (loads API keys from Vault)
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="ImagesSearchSkill",
            error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
            logger=logger
        )
        if error_response:
            return error_response

        requests_list = request.requests
        if not requests_list:
            return SearchResponse(results=[], provider="Brave Search", error="No requests provided")

        # Clamp to max parallel requests
        requests_list = requests_list[:MAX_PARALLEL_REQUESTS]

        # Normalise to dicts — items may arrive as Pydantic models (via BaseApp
        # validation) or plain dicts (from other code paths).
        requests_as_dicts: List[Dict[str, Any]] = [
            r.model_dump() if hasattr(r, "model_dump") else r
            for r in requests_list
        ]

        # Determine provider string from first request (for the response header)
        first_has_file_path = bool(requests_as_dicts[0].get("file_path"))
        default_provider = "Google Lens" if first_has_file_path else "Brave Search"

        file_path_index: Dict[str, str] = kwargs.get("file_path_index") or {}
        user_vault_key_id: Optional[str] = kwargs.get("user_vault_key_id")

        # Normalise request IDs (use provided id or index+1)
        normalised: List[tuple[Any, Dict[str, Any]]] = []
        for idx, req in enumerate(requests_as_dicts):
            req_id = req.get("id") or (idx + 1)
            normalised.append((req_id, req))

        # Run all requests concurrently
        import asyncio
        tasks = [
            self._process_single_request(
                req=req,
                request_id=req_id,
                secrets_manager=secrets_manager,
                file_path_index=file_path_index,
                user_vault_key_id=user_vault_key_id,
            )
            for req_id, req in normalised
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=False)

        # Build grouped response structure
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []
        providers: set = set()

        for req_id, results, provider, error_msg in outcomes:
            providers.add(provider)
            if error_msg:
                errors.append(f"Request {req_id}: {error_msg}")
            grouped_results.append({"id": req_id, "results": results})

        provider_str = " / ".join(sorted(providers)) if providers else default_provider
        error_str = "; ".join(errors) if errors else None

        return SearchResponse(
            results=grouped_results,
            provider=provider_str,
            error=error_str,
        )
