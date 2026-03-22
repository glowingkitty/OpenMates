"""
Shared SerpAPI credential utilities.

Provides one canonical Vault/env lookup path for SerpAPI API keys so multiple
apps (travel, shopping, etc.) can reuse the same logic without duplicating
credential code.

Architecture: shared provider auth helper for app providers.
See docs/architecture/app-skills.md for app/provider boundaries.
Tests: N/A (covered indirectly by provider integration tests).
"""

import logging
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search"
SERPAPI_VAULT_PATH = "kv/data/providers/serpapi"
SERPAPI_VAULT_KEY = "api_key"

_serpapi_api_key_cache: Optional[str] = None


async def get_serpapi_key_async(
    secrets_manager: Optional["SecretsManager"] = None,
) -> Optional[str]:
    """
    Retrieve the SerpAPI key, preferring Vault (via SecretsManager) over env vars.

    Falls back to SECRET__SERPAPI__API_KEY only if Vault lookup is unavailable
    or fails. Caches the key in-process for subsequent calls.
    """
    global _serpapi_api_key_cache

    if _serpapi_api_key_cache:
        return _serpapi_api_key_cache

    if secrets_manager:
        try:
            key = await secrets_manager.get_secret(
                secret_path=SERPAPI_VAULT_PATH,
                secret_key=SERPAPI_VAULT_KEY,
            )
            if key and key.strip():
                _serpapi_api_key_cache = key.strip()
                logger.info("Successfully retrieved SerpAPI key from Vault")
                return _serpapi_api_key_cache

            logger.warning(
                "SerpAPI key not found in Vault at path '%s' with key '%s'. "
                "Falling back to env var.",
                SERPAPI_VAULT_PATH,
                SERPAPI_VAULT_KEY,
            )
        except Exception as exc:
            logger.warning(
                "Failed to retrieve SerpAPI key from Vault: %s. Falling back to env var.",
                exc,
            )

    env_key = os.getenv("SECRET__SERPAPI__API_KEY")
    if env_key and env_key.strip() and env_key.strip() != "IMPORTED_TO_VAULT":
        _serpapi_api_key_cache = env_key.strip()
        logger.debug("Retrieved SerpAPI key from environment variable")
        return _serpapi_api_key_cache

    logger.error(
        "SerpAPI key not found in Vault or environment variables. "
        "Ensure the key is stored in Vault at '%s' with key '%s', or set "
        "SECRET__SERPAPI__API_KEY in .env. Get a key from: "
        "https://serpapi.com/manage-api-key",
        SERPAPI_VAULT_PATH,
        SERPAPI_VAULT_KEY,
    )
    return None


async def google_lens_reverse_search(
    image_url: str,
    secrets_manager: Optional["SecretsManager"] = None,
    query: Optional[str] = None,
    max_results: int = 20,
) -> Dict[str, Any]:
    """
    Reverse-image-search via SerpAPI's Google Lens engine.

    Sends ``image_url`` to ``https://lens.google.com/uploadbyurl`` via SerpAPI and
    returns the ``visual_matches`` array — a ranked list of pages where the same (or
    visually similar) image appears.

    Args:
        image_url: A **publicly accessible** URL of the image to reverse-search.
                   The URL must be reachable by Google's crawlers (no auth, no private nets).
        secrets_manager: Optional SecretsManager for Vault-based key lookup.
        query: Optional text refinement query sent alongside the image.
        max_results: Maximum number of visual matches to return (default 20, max 100).

    Returns:
        Dict with structure:
        {
            "image_url": str,
            "results": List[Dict],   # visual_matches items
            "error": Optional[str],
        }
        Each result contains: title, source_page_url, image_url, thumbnail_url, source,
        image_width, image_height, thumbnail_width, thumbnail_height.
    """
    import httpx as _httpx

    api_key = await get_serpapi_key_async(secrets_manager)
    if not api_key:
        raise ValueError(
            "SerpAPI key not available. "
            "Please configure it in Vault at '%s' or set SECRET__SERPAPI__API_KEY.",
        )

    params: Dict[str, Any] = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": api_key,
        "num": min(max_results, 100),
    }
    if query:
        params["q"] = query

    logger.debug(
        "Performing Google Lens reverse image search: image_url='%s'",
        image_url[:80],
    )

    try:
        async with _httpx.AsyncClient(timeout=45.0) as client:
            response = await client.get(SERPAPI_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        raw_matches = data.get("visual_matches", [])
        formatted: List[Dict[str, Any]] = []
        for item in raw_matches[:max_results]:
            formatted.append({
                "type": "image_result",
                "title": item.get("title", ""),
                "source_page_url": item.get("link", ""),
                "image_url": item.get("image", ""),
                "thumbnail_url": item.get("thumbnail", ""),
                "source": item.get("source", ""),
                "favicon_url": item.get("source_icon", ""),
                "image_width": item.get("image_width"),
                "image_height": item.get("image_height"),
                "thumbnail_width": item.get("thumbnail_width"),
                "thumbnail_height": item.get("thumbnail_height"),
            })

        logger.info(
            "Google Lens reverse search completed: %d visual matches", len(formatted)
        )
        return {"image_url": image_url, "results": formatted, "error": None}

    except _httpx.HTTPStatusError as e:
        error_msg = (
            f"SerpAPI Google Lens error: {e.response.status_code} — {e.response.text[:200]}"
        )
        logger.error(error_msg)
        return {"image_url": image_url, "results": [], "error": error_msg}
    except _httpx.RequestError as e:
        error_msg = f"SerpAPI Google Lens request error: {str(e)}"
        logger.error(error_msg)
        return {"image_url": image_url, "results": [], "error": error_msg}
    except Exception as e:
        error_msg = f"Unexpected error in Google Lens reverse search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"image_url": image_url, "results": [], "error": error_msg}
