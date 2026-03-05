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
from typing import Optional, TYPE_CHECKING

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
