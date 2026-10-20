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
#     - The plaintext bytes are temporarily uploaded to the PRIVATE `temp_images`
#       bucket via the internal API route POST /internal/s3/upload-temp-image.
#     - That route returns a short-lived (15 min) presigned URL which is passed
#       to SerpAPI Google Lens — SerpAPI fetches the object exactly once.
#     - After the search completes, the temp image is deleted immediately.
#       The 1-day S3 lifecycle policy is a safety net for any failures.
#     - Prior to GDPR audit finding C6 (fixed 2026-04-08 / OPE-372) this bucket
#       was public-read and the URL was a plain public S3 URL, which exposed
#       decrypted user images to anyone holding the URL for up to 24h.
#       See docs/architecture/compliance/gdpr-audit.md.
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
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from backend.shared.python_utils.app_skill_helpers import sanitize_long_text_fields_in_payload
from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.encrypted_embed_images import (
    MAX_IMAGE_INPUT_BYTES, ResolvedEncryptedImage, decode_image_record_content, resolve_encrypted_image_embed,
)
from backend.shared.python_utils.image_reference_resolver import image_reference_id, load_owned_image_record
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Maximum number of image results per request
MAX_IMAGE_RESULTS = 20
# Default number of image results
DEFAULT_IMAGE_RESULTS = 10
# Maximum number of parallel search requests in a single skill call
MAX_PARALLEL_REQUESTS = 5
# Timeout for internal API calls (temp upload + delete)
INTERNAL_API_TIMEOUT_SECONDS = 30
E2E_IMAGE_FIXTURE_QUERY_TOKEN = "openmates_e2e_image_fixture_sunset"
E2E_IMAGE_FIXTURE_RESULTS = [
    {
        "type": "image_result",
        "title": "Sunset ocean fixture",
        "source_page_url": "https://app.dev.openmates.org/store-examples/generate-1.webp",
        "image_url": "https://app.dev.openmates.org/store-examples/generate-1.webp",
        "thumbnail_url": "https://app.dev.openmates.org/store-examples/generate-1.webp",
        "source": "app.dev.openmates.org",
        "favicon_url": "https://app.dev.openmates.org/favicon.png",
    },
    {
        "type": "image_result",
        "title": "Ocean image fixture",
        "source_page_url": "https://app.dev.openmates.org/store-examples/generate-2.webp",
        "image_url": "https://app.dev.openmates.org/store-examples/generate-2.webp",
        "thumbnail_url": "https://app.dev.openmates.org/store-examples/generate-2.webp",
        "source": "app.dev.openmates.org",
        "favicon_url": "https://app.dev.openmates.org/favicon.png",
    },
]


def _is_e2e_image_fixture_query(query: str) -> bool:
    """Return True for the explicit non-production E2E images search fixture token."""
    return (
        os.getenv("SERVER_ENVIRONMENT", "production") != "production"
        and E2E_IMAGE_FIXTURE_QUERY_TOKEN in query.lower()
    )


def _build_e2e_image_fixture_results(requested_count: int | None) -> List[Dict[str, Any]]:
    result_count = max(1, min(int(requested_count or DEFAULT_IMAGE_RESULTS), len(E2E_IMAGE_FIXTURE_RESULTS)))
    return [dict(result) for result in E2E_IMAGE_FIXTURE_RESULTS[:result_count]]


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
        description="One exact image embed_ref from the conversation, or an authenticated caller's "
        "upload UUID, to reverse-search directly without images.view. Mutually exclusive with query.",
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

    async def _resolve_image_input(self, file_path: str, context: Dict[str, Any]) -> tuple[Optional[str], Optional[ResolvedEncryptedImage]]:
        """Resolve owned metadata directly, without an images.view prerequisite."""
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.core.api.app.services.s3.service import S3UploadService
        from backend.core.api.app.services.s3.config import get_bucket_name

        cache = context.get("cache_service") or CacheService()
        encryption = context.get("encryption_service") or EncryptionService(cache_service=cache)
        directus = context.get("directus_service") or DirectusService(cache_service=cache, encryption_service=encryption)
        embed_id = image_reference_id(file_path, context.get("file_path_index") or {})
        user_id = context.get("user_id")
        record = await load_owned_image_record(
            embed_id=embed_id, user_id=user_id, cache_client=cache, directus_service=directus,
            request_internal=context.get("internal_api_request"))
        vault_key = context.get("user_vault_key_id") or await cache.get_user_vault_key_id(user_id)
        if not vault_key:
            profile_result = await directus.users.get_user_profile(user_id)
            profile = profile_result[1] if profile_result else None
            vault_key = profile.get("vault_key_id") if isinstance(profile, dict) else None
        if not vault_key:
            raise ValueError("Reference image key is unavailable to this caller")
        content = await decode_image_record_content(
            record=record, user_vault_key_id=vault_key, encryption_service=encryption)
        public_url = content.get("image_url")
        if isinstance(public_url, str) and public_url:
            return public_url, None
        storage = context.get("s3_service") or S3UploadService(
            secrets_manager=context.get("secrets_manager"), directus_service=directus)
        if not context.get("s3_service"):
            await storage.initialize(configure_buckets=False)

        class BoundedStorage:
            async def get_file(self, *, bucket_name: str, object_key: str):
                return await storage.get_file(bucket_name=bucket_name, object_key=object_key,
                                              max_bytes=MAX_IMAGE_INPUT_BYTES + 32)

        image = await resolve_encrypted_image_embed(
            embed_id=embed_id, user_vault_key_id=vault_key, cache_client=cache,
            directus_service=directus, encryption_service=encryption,
            s3_service=BoundedStorage(), bucket_name=get_bucket_name("chatfiles", storage.environment),
            preloaded_records={embed_id: content})
        return None, image

    async def _upload_temp_image(
        self, image_bytes: bytes, content_type: str
    ) -> tuple[str, str]:
        """
        Upload plaintext image bytes to the temporary (private) S3 bucket and
        obtain a short-lived presigned URL for SerpAPI Google Lens.

        Returns (image_url, s3_key) — a 15-minute presigned URL that SerpAPI
        can fetch once, and the S3 key needed to delete the file after the
        search completes.

        The temp_images bucket is private with a 1-day lifecycle safety net;
        immediate cleanup is done via `_delete_temp_image` in the finally block
        of the caller. Before GDPR audit finding C6 this bucket was public-read
        and the returned URL was a plain public S3 URL — see
        docs/architecture/compliance/gdpr-audit.md.
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
        return data["image_url"], data["s3_key"]

    async def _delete_temp_image(self, s3_key: str) -> None:
        """Delete a previously uploaded temporary image. Best-effort — never raises."""
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
        if _is_e2e_image_fixture_query(query):
            logger.info("[images.search] Using dev/test fixture results for query '%s'", query)
            return _build_e2e_image_fixture_results(count), "OpenMates Test Fixture"

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
        cache_service: Optional[Any] = None,
        reference_context: Optional[Dict[str, Any]] = None,
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
                context = {**(reference_context or {}), "file_path_index": file_path_index,
                           "user_vault_key_id": user_vault_key_id, "cache_service": cache_service,
                           "secrets_manager": secrets_manager}
                image_url_field, resolved_image = await self._resolve_image_input(file_path, context)
                if image_url_field:
                    results, provider = await self._reverse_image_search(
                        image_url=str(image_url_field),
                        secrets_manager=secrets_manager,
                        query=query,
                        count=count,
                    )
                else:
                    # Uploaded/generated image — decrypt from private S3,
                    # upload to private temp bucket, get a short-lived presigned URL,
                    # call Google Lens, delete temp file.
                    logger.info(
                        "%s Decrypting uploaded image for reverse search", log_prefix
                    )
                    image_url, temp_s3_key = await self._upload_temp_image(
                        resolved_image.content, resolved_image.mime_type)
                    try:
                        results, provider = await self._reverse_image_search(
                            image_url=image_url,
                            secrets_manager=secrets_manager,
                            query=query,
                            count=count,
                        )
                    finally:
                        # Always clean up the temp file, even on error
                        await self._delete_temp_image(temp_s3_key)

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

            results = await sanitize_long_text_fields_in_payload(
                payload=results,
                task_id=f"images_search_{request_id}",
                secrets_manager=secrets_manager,
                cache_service=cache_service,
                min_chars=40,
                max_parallel=3,
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
        cache_service = kwargs.get("cache_service")
        reference_context = dict(kwargs)
        if not reference_context.get("internal_api_request"):
            reference_context["internal_api_request"] = getattr(getattr(self, "app", None), "_make_internal_api_request", None)

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
                cache_service=cache_service,
                reference_context=reference_context,
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
