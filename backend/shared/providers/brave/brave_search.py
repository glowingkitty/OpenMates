# backend/shared/providers/brave/brave_search.py
#
# Brave Search API provider functions.
# Provides web search functionality using the Brave Search API.
#
# Documentation: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
#
# Health Check:
# - No dedicated /health endpoint available (verified via API documentation)
# - Health checks use test search requests (minimal: query "test" with count=1)
# - Checked every 5 minutes via Celery Beat task

import logging
import os
import httpx
from typing import Dict, Any, List, Optional
from urllib.parse import urlencode

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Vault path for Brave API key
BRAVE_SECRET_PATH = "kv/data/providers/brave"
BRAVE_API_KEY_NAME = "api_key"

# Brave Search API base URL
BRAVE_API_BASE_URL = "https://api.search.brave.com/res/v1"


async def _get_brave_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the Brave Search API key from Vault, with fallback to environment variables.
    
    Checks Vault first, then falls back to environment variables if Vault lookup fails.
    Supports both SECRET__BRAVE__API_KEY and SECRET__BRAVE_SEARCH__API_KEY for compatibility.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    # First, try to get the API key from Vault
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=BRAVE_SECRET_PATH,
            secret_key=BRAVE_API_KEY_NAME
        )
        
        if api_key:
            # Clean the API key (strip whitespace, remove quotes if present)
            api_key_clean = api_key.strip()
            if (api_key_clean.startswith('"') and api_key_clean.endswith('"')) or \
               (api_key_clean.startswith("'") and api_key_clean.endswith("'")):
                api_key_clean = api_key_clean[1:-1].strip()
            
            logger.debug(f"Successfully retrieved Brave Search API key from Vault (length: {len(api_key_clean)})")
            return api_key_clean
        
        logger.debug("Brave Search API key not found in Vault, checking environment variables")
    
    except Exception as e:
        logger.warning(f"Error retrieving Brave Search API key from Vault: {str(e)}, checking environment variables", exc_info=True)
    
    # Fallback to environment variables
    # Check both SECRET__BRAVE__API_KEY (standard pattern) and SECRET__BRAVE_SEARCH__API_KEY (legacy)
    env_var_names = ["SECRET__BRAVE__API_KEY", "SECRET__BRAVE_SEARCH__API_KEY"]
    
    for env_var_name in env_var_names:
        api_key = os.getenv(env_var_name)
        if api_key and api_key.strip():
            # Strip whitespace and ensure no hidden characters
            api_key_clean = api_key.strip()
            # Remove any potential quotes that might have been added
            if (api_key_clean.startswith('"') and api_key_clean.endswith('"')) or \
               (api_key_clean.startswith("'") and api_key_clean.endswith("'")):
                api_key_clean = api_key_clean[1:-1].strip()
            
            if api_key_clean:
                masked_key = f"{api_key_clean[:4]}****{api_key_clean[-4:]}" if len(api_key_clean) > 8 else "****"
                logger.info(f"Successfully retrieved Brave Search API key from environment variable '{env_var_name}': {masked_key} (length: {len(api_key_clean)})")
                return api_key_clean
    
    logger.error("Brave Search API key not found in Vault or environment variables. Please configure it in Vault or set SECRET__BRAVE__API_KEY environment variable.")
    return None


async def check_brave_search_health(secrets_manager: SecretsManager) -> tuple[bool, Optional[str]]:
    """
    Check Brave Search API health by performing a minimal test search request.
    
    Brave Search does not have a dedicated /health endpoint, so we perform
    a minimal search query to verify the API is operational.
    
    Uses search_web with sanitize_output=False to avoid triggering LLM sanitization
    during health checks (which would cause unnecessary Groq API calls).
    
    Args:
        secrets_manager: SecretsManager instance for retrieving API key
    
    Returns:
        Tuple of (is_healthy, error_message)
    """
    try:
        # Use search_web with sanitize_output=False to avoid LLM sanitization during health checks
        # This prevents unnecessary Groq API calls for test requests
        search_result = await search_web(
            query="test",
            secrets_manager=secrets_manager,
            count=1,  # Minimal: just 1 result
            sanitize_output=False  # Disable sanitization for health checks
        )
        
        # Check if search was successful
        if search_result.get("error"):
            return False, search_result["error"]
        
        # Verify we got valid results
        if "web" in search_result and search_result.get("results"):
            return True, None
        else:
            return False, "Invalid response structure"
    except Exception as e:
        return False, str(e)


async def search_web(
    query: str,
    secrets_manager: SecretsManager,
    count: int = 10,
    country: str = "us",
    search_lang: str = "en",
    safesearch: str = "moderate",
    offset: int = 0,
    extra_snippets: bool = False,
    text_decorations: bool = True,
    freshness: Optional[str] = None,
    result_filter: Optional[str] = None,
    sanitize_output: bool = True
) -> Dict[str, Any]:
    """
    Performs a web search using the Brave Search API.
    
    Args:
        query: The search query string
        secrets_manager: SecretsManager instance for retrieving API key
        count: Number of results to return (default: 10, max: 20)
        country: Country code for localized results (default: "us")
        search_lang: Language code for search (default: "en")
        safesearch: Safe search level - "off", "moderate", or "strict" (default: "moderate")
        offset: Offset for pagination (default: 0)
        extra_snippets: Whether to include extra snippets in results (default: False)
        text_decorations: Whether to include text decorations (bold, etc.) (default: True)
        freshness: Filter by freshness - "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year)
        result_filter: Filter results - "news", "discussions", "videos", etc.
        sanitize_output: Whether to sanitize output via LLM (default: True). Set to False for health checks and testing to avoid triggering LLM sanitization.
    
    Returns:
        Dict containing search results with the following structure:
        {
            "query": str,
            "results": List[Dict],  # List of search result objects
            "web": Dict,  # Web search results metadata
            "error": Optional[str],  # Error message if request failed
            "sanitize_output": bool  # Whether output should be sanitized (passed through from parameter)
        }
    
    Raises:
        ValueError: If API key is not available
        httpx.HTTPStatusError: If the API request fails
    """
    # Get API key from Vault or environment variables
    api_key = await _get_brave_api_key(secrets_manager)
    if not api_key:
        raise ValueError("Brave Search API key not available. Please configure it in Vault or set SECRET__BRAVE__API_KEY environment variable.")
    
    # Build query parameters
    params = {
        "q": query,
        "count": min(count, 20),  # Brave API max is 20
        "country": country,
        "search_lang": search_lang,
        "safesearch": safesearch,
        "offset": offset,
        "extra_snippets": "1" if extra_snippets else "0",
        "text_decorations": "1" if text_decorations else "0"
    }
    
    # Add optional parameters
    if freshness:
        params["freshness"] = freshness
    if result_filter:
        params["result_filter"] = result_filter
    
    # Build full URL
    url = f"{BRAVE_API_BASE_URL}/web/search"
    
    # Set up headers
    # Note: Brave API requires X-Subscription-Token header (case-sensitive per their docs)
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    
    # Log API key info for debugging (masked)
    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(f"Performing Brave web search: query='{query}', count={count}, country={country}, api_key_length={len(api_key)}, api_key_preview={masked_key}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            result_data = response.json()
            
            # Extract and format results
            web_results = result_data.get("web", {}).get("results", [])
            
            # Format results for consistent structure
            # Include all fields: title, url, description, page_age, profile.name, meta_url.favicon, thumbnail.original, extra_snippets
            formatted_results = []
            for result in web_results:
                # Extract profile name if available
                profile_name = None
                if "profile" in result and isinstance(result["profile"], dict):
                    profile_name = result["profile"].get("name")
                
                # Extract meta_url and favicon
                meta_url = result.get("meta_url", {})
                favicon = None
                if isinstance(meta_url, dict):
                    favicon = meta_url.get("favicon")
                
                # Extract thumbnail
                thumbnail = result.get("thumbnail", {})
                thumbnail_original = None
                if isinstance(thumbnail, dict):
                    thumbnail_original = thumbnail.get("original")
                
                # Extract extra_snippets (array of additional snippets)
                extra_snippets = result.get("extra_snippets", [])
                if not isinstance(extra_snippets, list):
                    extra_snippets = []
                
                formatted_result = {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", ""),
                    "page_age": result.get("age", ""),  # When the page was indexed (renamed from "age" to "page_age")
                    "meta_url": meta_url,  # Full meta_url object
                    "language": result.get("language", ""),
                    "family_friendly": result.get("family_friendly", True),
                    "profile": {
                        "name": profile_name
                    } if profile_name else None,
                    "thumbnail": {
                        "original": thumbnail_original
                    } if thumbnail_original else None,
                    "extra_snippets": extra_snippets
                }
                formatted_results.append(formatted_result)
            
            logger.info(f"Brave web search completed: found {len(formatted_results)} results for query '{query}'")
            
            return {
                "query": query,
                "results": formatted_results,
                "web": {
                    "total_results": result_data.get("web", {}).get("total", 0),
                    "count": len(formatted_results)
                },
                "error": None,
                "sanitize_output": sanitize_output  # Pass through sanitize_output flag
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"Brave Search API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except httpx.RequestError as e:
        error_msg = f"Brave Search API request error: {str(e)}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except Exception as e:
        error_msg = f"Unexpected error in Brave web search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }

