# backend/shared/providers/firecrawl/firecrawl_scrape.py
#
# Firecrawl API provider functions.
# Provides web scraping functionality using the Firecrawl API.
#
# Documentation: https://docs.firecrawl.dev/api-reference/endpoint/scrape
#
# Health Check:
# - No dedicated /health endpoint available (verified via API documentation)
# - Health checks verify API key configuration and endpoint connectivity (HEAD request)
# - Does NOT perform actual scrape requests to avoid billing costs
# - Checked every 5 minutes via Celery Beat task

import logging
import os
import httpx
from typing import Dict, Any, Optional

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Vault path for Firecrawl API key
FIRECRAWL_SECRET_PATH = "kv/data/providers/firecrawl"
FIRECRAWL_API_KEY_NAME = "api_key"

# Firecrawl API base URL
FIRECRAWL_API_BASE_URL = "https://api.firecrawl.dev/v2"


async def _get_firecrawl_api_key(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Retrieves the Firecrawl API key from Vault, with fallback to environment variables.
    
    Checks Vault first, then falls back to environment variables if Vault lookup fails.
    Supports both SECRET__FIRECRAWL__API_KEY and SECRET__FIRECRAWL__API_KEY for compatibility.
    
    Args:
        secrets_manager: The SecretsManager instance to use
        
    Returns:
        The API key if found, None otherwise
    """
    # First, try to get the API key from Vault
    try:
        api_key = await secrets_manager.get_secret(
            secret_path=FIRECRAWL_SECRET_PATH,
            secret_key=FIRECRAWL_API_KEY_NAME
        )
        
        if api_key:
            # Clean the API key (strip whitespace, remove quotes if present)
            api_key_clean = api_key.strip()
            if (api_key_clean.startswith('"') and api_key_clean.endswith('"')) or \
               (api_key_clean.startswith("'") and api_key_clean.endswith("'")):
                api_key_clean = api_key_clean[1:-1].strip()
            
            logger.debug(f"Successfully retrieved Firecrawl API key from Vault (length: {len(api_key_clean)})")
            return api_key_clean
        
        logger.debug("Firecrawl API key not found in Vault, checking environment variables")
    
    except Exception as e:
        logger.warning(f"Error retrieving Firecrawl API key from Vault: {str(e)}, checking environment variables", exc_info=True)
    
    # Fallback to environment variables
    # Check both SECRET__FIRECRAWL__API_KEY (standard pattern) and FIRECRAWL_API_KEY (legacy)
    env_var_names = ["SECRET__FIRECRAWL__API_KEY", "FIRECRAWL_API_KEY"]
    
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
                logger.info(f"Successfully retrieved Firecrawl API key from environment variable '{env_var_name}': {masked_key} (length: {len(api_key_clean)})")
                return api_key_clean
    
    logger.error("Firecrawl API key not found in Vault or environment variables. Please configure it in Vault or set SECRET__FIRECRAWL__API_KEY environment variable.")
    return None


async def check_firecrawl_health(secrets_manager: SecretsManager) -> tuple[bool, Optional[str]]:
    """
    Check Firecrawl API health by verifying API key configuration and endpoint connectivity.
    
    This health check does NOT perform actual scrape requests to avoid billing costs.
    Instead, it:
    1. Verifies the API key is configured (in Vault or environment variables)
    2. Checks if the API base URL is reachable via HEAD request (no billing)
    
    Firecrawl does not have a dedicated /health endpoint, and performing test scrapes
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
        api_key = await _get_firecrawl_api_key(secrets_manager)
        if not api_key:
            return False, "API key not configured (not found in Vault or environment variables)"
        
        # Step 2: Check if API base URL is reachable via HEAD request (no billing)
        # HEAD request to base URL to verify connectivity without making a scrape request
        # We accept any HTTP response (even 404/405 errors) as proof the service is online
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Use HEAD request to check connectivity without triggering billing
                # Note: This may return 404, 405 (method not allowed), or other errors
                # Any response means the endpoint is reachable and the service is online
                response = await client.head(FIRECRAWL_API_BASE_URL)
                logger.debug(f"Firecrawl API connectivity check: {response.status_code} - endpoint is reachable")
                return True, None
        except httpx.TimeoutException:
            return False, "API endpoint timeout (endpoint not reachable)"
        except httpx.ConnectError as e:
            return False, f"API endpoint connection error: {str(e)}"
        except httpx.HTTPStatusError as e:
            # Even if we get an error status (404, 405, etc.), the endpoint is reachable
            # This means the service is online - we got a response from their servers
            # This is much better than nothing and doesn't cost anything
            logger.debug(f"Firecrawl API returned status {e.response.status_code}, but endpoint is reachable (service is online)")
            return True, None
        except httpx.RequestError as e:
            return False, f"API request error: {str(e)}"
            
    except Exception as e:
        logger.error(f"Unexpected error in Firecrawl health check: {str(e)}", exc_info=True)
        return False, f"Unexpected error: {str(e)}"


async def scrape_url(
    url: str,
    secrets_manager: SecretsManager,
    formats: Optional[list] = None,
    only_main_content: bool = True,
    max_age: Optional[int] = None,
    timeout: Optional[int] = None,
    sanitize_output: bool = True,
    wait_for: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scrapes a single URL using the Firecrawl API.
    
    Args:
        url: The URL to scrape
        secrets_manager: SecretsManager instance for retrieving API key
        formats: List of output formats to include (default: ["markdown"])
                 Options: "markdown", "html", "rawHtml", "summary", "links", "images", "screenshot", etc.
        only_main_content: Whether to return only main content (default: True)
        max_age: Cache age in milliseconds (default: 172800000 = 2 days)
        timeout: Timeout in milliseconds for the request (default: None)
        sanitize_output: Whether to sanitize output via LLM (default: True). Set to False for health checks and testing.
        wait_for: Time in milliseconds to wait for JavaScript to execute before scraping (default: None)
                  Useful for SPAs that load content dynamically. E.g., 5000 for 5 seconds.
    
    Returns:
        Dict containing scrape results with the following structure:
        {
            "url": str,
            "data": Dict,  # Scraped data (markdown, html, metadata, etc.)
            "error": Optional[str],  # Error message if request failed
            "sanitize_output": bool  # Whether output should be sanitized (passed through from parameter)
        }
    
    Raises:
        ValueError: If API key is not available
        httpx.HTTPStatusError: If the API request fails
    """
    # Get API key from Vault or environment variables
    api_key = await _get_firecrawl_api_key(secrets_manager)
    if not api_key:
        raise ValueError("Firecrawl API key not available. Please configure it in Vault or set SECRET__FIRECRAWL__API_KEY environment variable.")
    
    # Default formats to markdown if not specified
    if formats is None:
        formats = ["markdown"]
    
    # Build request payload
    payload = {
        "url": url,
        "formats": formats,
        "onlyMainContent": only_main_content,
        "blockAds": True,  # Default: block ads
        "skipTlsVerification": True,  # Default: skip TLS verification
        "removeBase64Images": True,  # Default: remove base64 images
        "storeInCache": True,  # Default: store in cache
    }
    
    # Add optional parameters
    if max_age is not None:
        payload["maxAge"] = max_age
    if timeout is not None:
        payload["timeout"] = timeout
    if wait_for is not None:
        payload["waitFor"] = wait_for
    
    # Build full URL
    endpoint_url = f"{FIRECRAWL_API_BASE_URL}/scrape"
    
    # Set up headers
    # Firecrawl API requires Authorization header with Bearer token
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Log API key info for debugging (masked)
    masked_key = f"{api_key[:4]}****{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.debug(f"Performing Firecrawl scrape: url='{url}', formats={formats}, api_key_length={len(api_key)}, api_key_preview={masked_key}")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(endpoint_url, json=payload, headers=headers)
            response.raise_for_status()
            
            result_data = response.json()
            
            # Check if the response indicates success
            success = result_data.get("success", False)
            data = result_data.get("data", {})
            
            if not success:
                error_msg = data.get("error") or "Unknown error from Firecrawl API"
                logger.error(f"Firecrawl scrape failed for URL '{url}': {error_msg}")
                return {
                    "url": url,
                    "data": {},
                    "error": error_msg,
                    "sanitize_output": sanitize_output
                }
            
            logger.info(f"Firecrawl scrape completed: successfully scraped URL '{url}'")
            
            return {
                "url": url,
                "data": data,
                "error": None,
                "sanitize_output": sanitize_output  # Pass through sanitize_output flag
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"Firecrawl API error: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return {
            "url": url,
            "data": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except httpx.RequestError as e:
        error_msg = f"Firecrawl API request error: {str(e)}"
        logger.error(error_msg)
        return {
            "url": url,
            "data": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }
    except Exception as e:
        error_msg = f"Unexpected error in Firecrawl scrape: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "url": url,
            "data": {},
            "error": error_msg,
            "sanitize_output": sanitize_output  # Pass through sanitize_output flag
        }

