# backend/shared/providers/brave/brave_search.py
#
# Brave Search API provider functions.
# Provides web search functionality using the Brave Search API.
#
# Documentation: https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
#
# Health Check:
# - No dedicated /health endpoint available (verified via API documentation)
# - Health checks verify API key configuration and endpoint connectivity (HEAD request)
# - Does NOT perform actual search requests to avoid billing costs
# - Checked every 5 minutes via Celery Beat task

import logging
import os
import httpx
from typing import Dict, Any, Optional

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
    Check Brave Search API health by verifying API key configuration and endpoint connectivity.
    
    This health check does NOT perform actual search requests to avoid billing costs.
    Instead, it:
    1. Verifies the API key is configured (in Vault or environment variables)
    2. Checks if the API base URL is reachable via HEAD request (no billing)
    
    Brave Search does not have a dedicated /health endpoint, and performing test searches
    would incur billing costs, so we use this lightweight connectivity check instead.
    
    Args:
        secrets_manager: SecretsManager instance for retrieving API key
    
    Returns:
        Tuple of (is_healthy, error_message)
        - is_healthy: True if API key is configured and endpoint is reachable
        - error_message: None if healthy, error description if unhealthy
    """
    try:
        # Step 1: Verify API key is configured
        api_key = await _get_brave_api_key(secrets_manager)
        if not api_key:
            return False, "API key not configured (not found in Vault or environment variables)"
        
        # Step 2: Check if API base URL is reachable via HEAD request (no billing)
        # HEAD request to base URL to verify connectivity without making a search request
        # We accept any HTTP response (even 404/405 errors) as proof the service is online
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Use HEAD request to check connectivity without triggering billing
                # Note: This may return 404, 405 (method not allowed), or other errors
                # Any response means the endpoint is reachable and the service is online
                response = await client.head(BRAVE_API_BASE_URL)
                logger.debug(f"Brave Search API connectivity check: {response.status_code} - endpoint is reachable")
                return True, None
        except httpx.TimeoutException:
            return False, "API endpoint timeout (endpoint not reachable)"
        except httpx.ConnectError as e:
            return False, f"API endpoint connection error: {str(e)}"
        except httpx.HTTPStatusError as e:
            # Even if we get an error status (404, 405, etc.), the endpoint is reachable
            # This means the service is online - we got a response from their servers
            # This is much better than nothing and doesn't cost anything
            logger.debug(f"Brave Search API returned status {e.response.status_code}, but endpoint is reachable (service is online)")
            return True, None
        except httpx.RequestError as e:
            return False, f"API request error: {str(e)}"
            
    except Exception as e:
        logger.error(f"Unexpected error in Brave Search health check: {str(e)}", exc_info=True)
        return False, f"Unexpected error: {str(e)}"


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
            # For web search, results are always in web.results
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
                
                # Extract page_age from 'age' field (human-readable string like "2 days ago")
                # Note: Brave Search does not always return 'age' for all results - it's optional metadata
                page_age = result.get("age", "")
                
                # INFO log to track all metadata fields (for debugging thumbnail/favicon issues)
                logger.info(
                    f"[BRAVE_DEBUG] Result for '{result.get('url', '')[:60]}': "
                    f"raw_meta_url_type={type(result.get('meta_url')).__name__}, "
                    f"raw_meta_url_keys={list(result.get('meta_url', {}).keys()) if isinstance(result.get('meta_url'), dict) else 'N/A'}, "
                    f"extracted_favicon={favicon[:80] if favicon else None}, "
                    f"raw_thumbnail_type={type(result.get('thumbnail')).__name__}, "
                    f"raw_thumbnail_keys={list(result.get('thumbnail', {}).keys()) if isinstance(result.get('thumbnail'), dict) else 'N/A'}, "
                    f"extracted_thumbnail_original={thumbnail_original[:80] if thumbnail_original else None}"
                )
                
                formatted_result = {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", ""),
                    "page_age": page_age,  # When the page was indexed (human-readable, e.g., "2 days ago")
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


async def search_videos(
    query: str,
    secrets_manager: SecretsManager,
    count: int = 10,
    country: str = "us",
    search_lang: str = "en",
    safesearch: str = "moderate",
    offset: int = 0,
    freshness: Optional[str] = None,
    sanitize_output: bool = True
) -> Dict[str, Any]:
    """
    Performs a video search using the Brave Search Videos API.
    
    Uses the dedicated /videos/search endpoint instead of web/search with result_filter.
    
    Args:
        query: The search query string
        secrets_manager: SecretsManager instance for retrieving API key
        count: Number of results to return (default: 10, max: 50)
        country: Country code for localized results (default: "us")
        search_lang: Language code for search (default: "en")
        safesearch: Safe search level - "off", "moderate", or "strict" (default: "moderate")
        offset: Offset for pagination (default: 0)
        freshness: Filter by freshness - "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year)
        sanitize_output: Whether to sanitize output via LLM (default: True). Set to False for health checks and testing to avoid triggering LLM sanitization.
    
    Returns:
        Dict containing search results with the following structure:
        {
            "query": str,
            "results": List[Dict],  # List of video result objects
            "web": Dict,  # Search results metadata (for consistency with search_web)
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
        "count": min(count, 50),  # Videos API max is 50
        "country": country,
        "search_lang": search_lang,
        "safesearch": safesearch,
        "offset": offset,
        "spellcheck": "1"
    }
    
    # Add optional parameters
    if freshness:
        params["freshness"] = freshness
    
    # Build full URL - use dedicated videos endpoint
    url = f"{BRAVE_API_BASE_URL}/videos/search"
    
    # Set up headers
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    
    # Log API key info for debugging (masked)
    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(f"Performing Brave video search: query='{query}', count={count}, country={country}, api_key_length={len(api_key)}, api_key_preview={masked_key}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            result_data = response.json()
            
            # Extract and format results
            # Videos API returns results directly in "results" array (not nested in "videos.results")
            video_results = result_data.get("results", [])
            
            # Format results for consistent structure
            formatted_results = []
            for result in video_results:
                # Extract meta_url
                meta_url = result.get("meta_url", {})
                
                # Extract thumbnail
                thumbnail = result.get("thumbnail", {})
                thumbnail_original = None
                if isinstance(thumbnail, dict):
                    thumbnail_original = thumbnail.get("original")
                
                # Extract video metadata
                video_data = result.get("video", {})
                
                formatted_result = {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", ""),
                    "page_age": result.get("age", "") or result.get("page_age", ""),  # Support both "age" and "page_age"
                    "meta_url": meta_url,  # Full meta_url object
                    "language": result.get("language", ""),
                    "family_friendly": result.get("family_friendly", True),
                    "thumbnail": {
                        "original": thumbnail_original
                    } if thumbnail_original else None,
                    "video": video_data if video_data else None,
                    "extra_snippets": []  # Videos API doesn't support extra_snippets
                }
                formatted_results.append(formatted_result)
            
            logger.info(f"Brave video search completed: found {len(formatted_results)} results for query '{query}'")
            
            # Get total from extra object if available
            extra = result_data.get("extra", {})
            total_results = extra.get("total", len(formatted_results)) if isinstance(extra, dict) else len(formatted_results)
            
            return {
                "query": query,
                "results": formatted_results,
                "web": {
                    "total_results": total_results,
                    "count": len(formatted_results)
                },
                "error": None,
                "sanitize_output": sanitize_output  # Pass through sanitize_output flag
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"Brave Video Search API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except httpx.RequestError as e:
        error_msg = f"Brave Video Search API request error: {str(e)}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except Exception as e:
        error_msg = f"Unexpected error in Brave video search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }


async def search_news(
    query: str,
    secrets_manager: SecretsManager,
    count: int = 10,
    country: str = "us",
    search_lang: str = "en",
    safesearch: str = "moderate",
    offset: int = 0,
    freshness: Optional[str] = None,
    extra_snippets: bool = False,
    sanitize_output: bool = True
) -> Dict[str, Any]:
    """
    Performs a news search using the Brave Search News API.
    
    Uses the dedicated /news/search endpoint instead of web/search with result_filter.
    
    Args:
        query: The search query string
        secrets_manager: SecretsManager instance for retrieving API key
        count: Number of results to return (default: 10, max: 50)
        country: Country code for localized results (default: "us")
        search_lang: Language code for search (default: "en")
        safesearch: Safe search level - "off", "moderate", or "strict" (default: "moderate")
        offset: Offset for pagination (default: 0)
        freshness: Filter by freshness - "pd" (past day), "pw" (past week), "pm" (past month), "py" (past year)
        extra_snippets: Whether to include extra snippets in results (default: False)
        sanitize_output: Whether to sanitize output via LLM (default: True). Set to False for health checks and testing to avoid triggering LLM sanitization.
    
    Returns:
        Dict containing search results with the following structure:
        {
            "query": str,
            "results": List[Dict],  # List of news result objects
            "web": Dict,  # Search results metadata (for consistency with search_web)
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
        "count": min(count, 50),  # News API max is 50
        "country": country,
        "search_lang": search_lang,
        "safesearch": safesearch,
        "offset": offset,
        "spellcheck": "1"
    }
    
    # Add optional parameters
    if freshness:
        params["freshness"] = freshness
    if extra_snippets:
        params["extra_snippets"] = "1"
    
    # Build full URL - use dedicated news endpoint
    url = f"{BRAVE_API_BASE_URL}/news/search"
    
    # Set up headers
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    
    # Log API key info for debugging (masked)
    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(f"Performing Brave news search: query='{query}', count={count}, country={country}, api_key_length={len(api_key)}, api_key_preview={masked_key}")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            result_data = response.json()
            
            # Extract and format results
            # News API returns results directly in "results" array (not nested in "news.results")
            news_results = result_data.get("results", [])
            
            # Format results for consistent structure
            formatted_results = []
            for result in news_results:
                # Extract meta_url
                meta_url = result.get("meta_url", {})
                
                # Extract thumbnail
                thumbnail = result.get("thumbnail", {})
                thumbnail_original = None
                if isinstance(thumbnail, dict):
                    thumbnail_original = thumbnail.get("original")
                
                # Extract extra_snippets (array of additional snippets)
                extra_snippets_list = result.get("extra_snippets", [])
                if not isinstance(extra_snippets_list, list):
                    extra_snippets_list = []
                
                formatted_result = {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "description": result.get("description", ""),
                    "page_age": result.get("age", "") or result.get("page_age", ""),  # Support both "age" and "page_age"
                    "meta_url": meta_url,  # Full meta_url object
                    "language": result.get("language", ""),
                    "family_friendly": result.get("family_friendly", True),
                    "thumbnail": {
                        "original": thumbnail_original
                    } if thumbnail_original else None,
                    "extra_snippets": extra_snippets_list,
                    "breaking": result.get("breaking", False)  # News-specific field
                }
                formatted_results.append(formatted_result)
            
            logger.info(f"Brave news search completed: found {len(formatted_results)} results for query '{query}'")
            
            # News API doesn't provide total count in response, use result count
            total_results = len(formatted_results)
            
            return {
                "query": query,
                "results": formatted_results,
                "web": {
                    "total_results": total_results,
                    "count": len(formatted_results)
                },
                "error": None,
                "sanitize_output": sanitize_output  # Pass through sanitize_output flag
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"Brave News Search API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except httpx.RequestError as e:
        error_msg = f"Brave News Search API request error: {str(e)}"
        logger.error(error_msg)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except Exception as e:
        error_msg = f"Unexpected error in Brave news search: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "query": query,
            "results": [],
            "web": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }

