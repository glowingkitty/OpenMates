# Text image search via the supported Brave Search Images API.

import logging
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.shared.python_utils.app_skill_helpers import sanitize_long_text_fields_in_payload
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
    """A text image search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: Optional[str] = Field(
        default=None,
        description="Text description of images to search for (e.g. 'sunset over mountains'). "
        "Reverse image search is unavailable.",
    )
    file_path: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="Legacy field; reverse image search is unavailable and this input is rejected.",
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
    Each supported request contains a text 'query'.
    """
    requests: List[ImageSearchRequestItem] = Field(
        ...,
        description=(
            "Array of text image search request objects, each containing 'query'. "
            "Optional: 'count' (default 6, max 20), "
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
    """Search for images by text through Brave Search Images API."""

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

    # ── Single-request processor ─────────────────────────────────────────────

    async def _process_single_request(
        self,
        req: Dict[str, Any],
        request_id: Any,
        secrets_manager: SecretsManager,
        cache_service: Optional[Any] = None,
    ) -> tuple[Any, List[Dict[str, Any]], str, Optional[str]]:
        """
        Process one search request and return (request_id, results, provider, error_msg).

        """
        query: Optional[str] = req.get("query")
        if req.get("file_path") is not None:
            return request_id, [], "", "Reverse image search is unavailable. Use a text query to search for images."
        count: int = min(int(req.get("count", DEFAULT_IMAGE_RESULTS)), MAX_IMAGE_RESULTS)
        country: str = req.get("country", "us")
        search_lang: str = req.get("search_lang", "en")

        log_prefix = f"[images.search] [req:{request_id}]"

        try:
            if query:
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
                raise ValueError("Each request must contain a text 'query'")

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
                     a text 'query'.
            secrets_manager: Injected by BaseApp for provider API key resolution.
            **kwargs: Pipeline context, including cache_service.
        """
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

        # Reject legacy image inputs without reading secrets, resolving embeds, or uploading data.
        if any(req.get("file_path") is None and req.get("query") for req in requests_as_dicts):
            # Get or create SecretsManager using BaseSkill helper (loads API keys from Vault)
            secrets_manager, error_response = await self._get_or_create_secrets_manager(
                secrets_manager=secrets_manager,
                skill_name="ImagesSearchSkill",
                error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
                logger=logger
            )
            if error_response:
                return error_response

        default_provider = "Brave Search"
        cache_service = kwargs.get("cache_service")

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
                cache_service=cache_service,
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
