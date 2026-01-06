# backend/apps/ai/processing/url_validator.py
# URL extraction and validation for assistant responses.
# Validates URLs paragraph-by-paragraph as responses are streamed.
#
# Uses Webshare rotating residential proxy and random user agents to avoid
# datacenter IP blocking and bot detection by websites.

import re
import httpx
import asyncio
import logging
import random
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus

from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# URL validation timeout (seconds) - increased slightly to account for proxy routing
URL_VALIDATION_TIMEOUT = 8.0

# Check if user-agents library is available for dynamic User-Agent generation
try:
    from user_agents import UserAgent
    USER_AGENTS_AVAILABLE = True
except ImportError:
    USER_AGENTS_AVAILABLE = False
    logger.warning("user-agents library not available. Using static fallback User-Agents.")

# Fallback user agents list (updated periodically to match current browser versions)
# Used if user-agents library is not available or fails
FALLBACK_USER_AGENTS = [
    # Chrome on Windows (most common)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# Randomized Accept-Language headers to avoid fingerprinting
ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.8",
    "en-US,en;q=0.9,es;q=0.8",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.9,de;q=0.8",
    "de-DE,de;q=0.9,en;q=0.8",
]

# Localhost patterns to skip during URL validation
# These URLs are local development addresses that won't be accessible from the server
LOCALHOST_PATTERNS = [
    "localhost",
    "127.0.0.1",
    "127.0.0.0",
    "0.0.0.0",
    "::1",  # IPv6 localhost
    "[::1]",  # IPv6 localhost in URL format
]


def _is_localhost_url(url: str) -> bool:
    """
    Check if URL points to localhost or local network address.
    
    These URLs should be skipped during validation because:
    1. They won't be accessible from the server (local to user's machine)
    2. They're typically development/testing URLs
    3. Attempting to validate them would always fail or timeout
    
    Matches:
    - localhost (with any port)
    - 127.x.x.x (entire loopback range)
    - 0.0.0.0
    - ::1 (IPv6 localhost)
    
    Args:
        url: URL string to check
        
    Returns:
        True if URL is a localhost/local address, False otherwise
    """
    try:
        # Extract host from URL (handle both http:// and https://)
        # URL format: scheme://host:port/path
        url_lower = url.lower()
        
        # Remove scheme
        if url_lower.startswith("https://"):
            host_part = url_lower[8:]
        elif url_lower.startswith("http://"):
            host_part = url_lower[7:]
        else:
            # No scheme, assume it starts with host
            host_part = url_lower
        
        # Extract host (everything before first / or end of string)
        host_with_port = host_part.split("/")[0]
        
        # Remove port if present (host:port format)
        # Handle IPv6 format [::1]:port
        if host_with_port.startswith("["):
            # IPv6 address - find closing bracket
            bracket_end = host_with_port.find("]")
            if bracket_end != -1:
                host = host_with_port[:bracket_end + 1]
            else:
                host = host_with_port
        else:
            # IPv4 or hostname - split on last colon for port
            host = host_with_port.rsplit(":", 1)[0]
        
        # Check against localhost patterns
        for pattern in LOCALHOST_PATTERNS:
            if host == pattern:
                return True
        
        # Check for 127.x.x.x range (entire loopback block)
        if host.startswith("127."):
            return True
        
        return False
        
    except Exception as e:
        logger.debug(f"Error checking if URL is localhost: {url}, error: {e}")
        return False


def _generate_random_user_agent() -> str:
    """
    Generate a realistic, up-to-date User-Agent to avoid fingerprinting.
    
    Uses the user-agents library to generate current, realistic browser User-Agents
    that automatically stay up-to-date with actual browser versions and distributions.
    Falls back to hardcoded agents if library is unavailable.
    
    Returns:
        Random User-Agent string
    """
    if USER_AGENTS_AVAILABLE:
        try:
            # Generate a random UserAgent that mimics real browser distribution
            # This automatically includes current browser versions and realistic OS combinations
            user_agent = UserAgent()
            ua_string = user_agent.random
            logger.debug(f"Generated dynamic User-Agent: {ua_string[:50]}...")
            return ua_string
        except Exception as e:
            logger.warning(f"Failed to generate dynamic User-Agent: {e}. Falling back to static list.")
    
    # Fallback to static list if library fails or unavailable
    return random.choice(FALLBACK_USER_AGENTS)


def _generate_randomized_headers() -> Dict[str, str]:
    """
    Generate randomized HTTP headers to avoid fingerprinting.
    
    Includes:
    - Random User-Agent (via user-agents library or fallback)
    - Random Accept-Language
    - Random DNT (Do Not Track) value
    - Standard browser headers
    
    Returns:
        Dict of HTTP headers
    """
    return {
        "User-Agent": _generate_random_user_agent(),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": random.choice(["1", "0"]),  # Do Not Track header variation
        "Upgrade-Insecure-Requests": "1",
        "Connection": "close",  # Force connection close to ensure IP rotation with proxy
    }


async def _get_webshare_proxy_url(secrets_manager: SecretsManager) -> Optional[str]:
    """
    Get Webshare proxy URL from secrets manager.
    
    Webshare uses rotating residential proxies to avoid IP blocks.
    The proxy automatically rotates through residential IP pool.
    
    Args:
        secrets_manager: SecretsManager instance to get Webshare credentials
        
    Returns:
        Proxy URL string (http://user:pass@host:port) if credentials available, None otherwise
    """
    try:
        # Get Webshare credentials from secrets manager
        ws_username = await secrets_manager.get_secret(
            secret_path="kv/data/providers/webshare",
            secret_key="proxy_username"
        )
        ws_password = await secrets_manager.get_secret(
            secret_path="kv/data/providers/webshare",
            secret_key="proxy_password"
        )
        
        if not ws_username or not ws_password:
            logger.debug("Webshare credentials not found - URL validation will use direct connection")
            return None
        
        # Webshare proxy endpoint (rotating residential)
        # Format: http://username:password@proxy.webshare.io:80
        proxy_url = f"http://{ws_username}:{ws_password}@proxy.webshare.io:80"
        logger.debug("Webshare proxy configured for URL validation")
        return proxy_url
        
    except Exception as e:
        logger.warning(f"Error getting Webshare proxy config: {e}")
        return None


async def extract_urls_from_markdown(markdown: str) -> List[Dict[str, str]]:
    """
    Extract all markdown links [text](url) from markdown text.
    
    Args:
        markdown: Markdown text to extract URLs from
        
    Returns:
        List of dicts with 'url', 'text', 'full_match', 'start_pos', and 'end_pos' keys
    """
    # Pattern matches [text](url) markdown links
    pattern = r'\[([^\]]+)\]\((https?://[^\s)]+)\)'
    matches = []
    
    for match in re.finditer(pattern, markdown):
        matches.append({
            'url': match.group(2),
            'text': match.group(1),
            'full_match': match.group(0),
            'start_pos': match.start(),
            'end_pos': match.end()
        })
    
    return matches


async def check_url_status(
    url: str,
    timeout: float = URL_VALIDATION_TIMEOUT,
    secrets_manager: Optional[SecretsManager] = None
) -> Dict[str, Any]:
    """
    Check if URL is accessible. Returns status dict with:
    - is_valid: bool (True if 2xx status)
    - status_code: int or None
    - error_type: str ('404', '4xx', '5xx', 'timeout', 'connection_error', etc.)
    - is_temporary: bool (True for 5xx/timeouts - might be temporary)
    
    Uses HEAD request first (more efficient), falls back to GET if HEAD not supported.
    
    **Anti-Detection Features:**
    - Random User-Agent generation (via 'user-agents' library for current browser versions)
    - Randomized HTTP headers (Accept-Language, DNT, etc.)
    - Webshare rotating residential proxy (if secrets_manager provided)
    - Each request gets fresh connection for IP rotation
    
    **Security**: URL fragments (#{text}) are removed before validation as a security measure.
    Fragments can contain malicious content and are not needed for URL validation.
    
    **Localhost URLs**: URLs pointing to localhost (127.0.0.1, localhost, ::1, etc.) are
    automatically treated as valid without making HTTP requests, since these are local
    development addresses that aren't accessible from the server.
    
    Args:
        url: URL to check
        timeout: Timeout in seconds for the HTTP request
        secrets_manager: Optional SecretsManager for Webshare proxy credentials
        
    Returns:
        Dict with validation results
    """
    # Skip localhost URLs - they're local development addresses that won't be accessible
    # from the server. Treat them as valid to avoid false positives.
    if _is_localhost_url(url):
        logger.debug(f"Skipping localhost URL validation (treating as valid): {url[:50]}...")
        return {
            'is_valid': True,
            'status_code': None,
            'error_type': None,
            'is_temporary': False
        }
    
    # Sanitize URL by removing fragment parameters (#{text}) as a security measure
    # Fragments can contain malicious content and are not needed for URL validation
    sanitized_url = sanitize_url_remove_fragment(url)
    if not sanitized_url:
        logger.warning(f"Failed to sanitize URL for validation: '{url}'")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'invalid_url',
            'is_temporary': False
        }
    
    # Use sanitized URL for validation
    url = sanitized_url
    
    # Get proxy URL if secrets_manager is available
    proxy_url = None
    if secrets_manager:
        proxy_url = await _get_webshare_proxy_url(secrets_manager)
    
    try:
        # Generate randomized headers to avoid fingerprinting
        headers = _generate_randomized_headers()
        
        # Configure httpx client with optional proxy
        # proxy parameter accepts a URL string for all requests
        client_kwargs = {
            "timeout": timeout,
            "follow_redirects": True,
            "headers": headers,
        }
        
        if proxy_url:
            # httpx uses 'proxy' parameter (single proxy for all protocols)
            client_kwargs["proxy"] = proxy_url
            logger.debug(f"URL validation using Webshare proxy for: {url[:50]}...")
        else:
            logger.debug(f"URL validation using direct connection for: {url[:50]}...")
        
        async with httpx.AsyncClient(**client_kwargs) as client:
            # Use HEAD request first (faster), fallback to GET if HEAD not supported
            # HEAD is more efficient - only returns headers, not body
            # Fallback to GET only if HEAD returns 405 (Method Not Allowed) or 501 (Not Implemented)
            response = None
            try:
                response = await client.head(url)
                # If HEAD succeeds, use it (even if status is 404/500 - that's valid info)
            except httpx.HTTPStatusError as e:
                # HEAD returned an error status - check if it's because HEAD isn't supported
                if e.response.status_code in [405, 501]:
                    # HEAD method not allowed/implemented - fallback to GET
                    try:
                        response = await client.get(url)
                    except Exception:
                        # If GET also fails, re-raise to be handled by outer handlers
                        raise
                else:
                    # HEAD worked but returned error status (404, 500, etc.) - use it
                    response = e.response
            # Don't catch TimeoutException, ConnectError, or other network errors here
            # Let them propagate to outer handlers
            
            status_code = response.status_code
            
            # Log the result for debugging
            logger.debug(f"URL validation result for {url[:50]}...: status={status_code}")
            
            # 2xx = valid
            if 200 <= status_code < 300:
                return {
                    'is_valid': True,
                    'status_code': status_code,
                    'error_type': None,
                    'is_temporary': False
                }
            
            # 4xx = broken (not found, forbidden, etc.)
            elif 400 <= status_code < 500:
                logger.info(f"URL validation: broken URL detected (status {status_code}): {url}")
                return {
                    'is_valid': False,
                    'status_code': status_code,
                    'error_type': '4xx',
                    'is_temporary': False
                }
            
            # 5xx = server error (might be temporary)
            elif 500 <= status_code < 600:
                return {
                    'is_valid': False,
                    'status_code': status_code,
                    'error_type': '5xx',
                    'is_temporary': True
                }
            
            # Other status codes (3xx redirects should be followed by httpx)
            else:
                return {
                    'is_valid': True,  # Treat as valid if we got a response
                    'status_code': status_code,
                    'error_type': None,
                    'is_temporary': False
                }
                
    except httpx.TimeoutException as e:
        logger.debug(f"Timeout checking URL {url}: {e}")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'timeout',
            'is_temporary': True  # Timeouts might be temporary
        }
    except httpx.ConnectError as e:
        logger.debug(f"Connection error checking URL {url}: {e}")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'connection_error',
            'is_temporary': True
        }
    except httpx.ProxyError as e:
        # Proxy-specific errors - log and treat as temporary
        logger.warning(f"Proxy error checking URL {url}: {e}")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'proxy_error',
            'is_temporary': True
        }
    except httpx.RequestError as e:
        # RequestError is a base class for request-related errors
        logger.warning(f"Request error checking URL {url}: {e}")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'connection_error',
            'is_temporary': True
        }
    except httpx.HTTPError as e:
        # Catch other httpx HTTP errors (like HTTPStatusError, etc.)
        logger.warning(f"HTTP error checking URL {url}: {e}")
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'connection_error',  # Treat other HTTP errors as connection issues
            'is_temporary': True
        }
    except Exception as e:
        # Log the actual exception type for debugging
        logger.warning(f"Unexpected error checking URL {url}: {type(e).__name__}: {e}", exc_info=True)
        return {
            'is_valid': False,
            'status_code': None,
            'error_type': 'unknown_error',
            'is_temporary': True
        }


async def validate_urls_in_paragraph(
    paragraph: str,
    task_id: str,
    secrets_manager: Optional[SecretsManager] = None
) -> List[Dict[str, Any]]:
    """
    Extract and validate all URLs from a paragraph in background.
    Returns list of validation results for each URL found.
    
    Uses Webshare proxy and random user agents for anti-detection if secrets_manager
    is provided.
    
    Args:
        paragraph: Paragraph text to validate URLs in
        task_id: Task ID for logging
        secrets_manager: Optional SecretsManager for Webshare proxy credentials
        
    Returns:
        List of validation results, each containing URL info and validation status
    """
    urls = await extract_urls_from_markdown(paragraph)
    
    if not urls:
        return []
    
    logger.debug(f"[{task_id}] Validating {len(urls)} URL(s) in paragraph")
    
    # Check all URLs in parallel, passing secrets_manager for proxy support
    validation_tasks = [
        check_url_status(url_info['url'], secrets_manager=secrets_manager) 
        for url_info in urls
    ]
    results = await asyncio.gather(*validation_tasks, return_exceptions=True)
    
    # Combine URL info with validation results
    validation_results = []
    for url_info, result in zip(urls, results):
        if isinstance(result, Exception):
            logger.warning(f"[{task_id}] Exception validating URL {url_info['url']}: {result}")
            validation_results.append({
                **url_info,
                'is_valid': False,
                'status_code': None,
                'error_type': 'exception',
                'is_temporary': True,
                'error': str(result)
            })
        else:
            validation_results.append({
                **url_info,
                **result
            })
    
    # Log broken URLs (4xx errors, not temporary)
    broken_urls = [r for r in validation_results if not r.get('is_valid') and not r.get('is_temporary')]
    if broken_urls:
        logger.info(
            f"[{task_id}] Found {len(broken_urls)} broken URL(s) in paragraph: "
            f"{[r['url'] for r in broken_urls]}"
        )
    
    return validation_results


def replace_broken_urls_with_search(
    response: str,
    broken_urls: List[Dict[str, Any]]
) -> str:
    """
    Replace broken URLs in response with Brave search URLs.
    
    This is a simple, reliable approach that:
    - Preserves the original link text so user sees what was intended
    - Replaces the broken URL with a Brave search for that topic
    - No LLM call needed (zero cost, zero latency, can't fail)
    
    Example:
        Before: [Python docs](https://broken-link.com/python)
        After:  [Python docs](https://search.brave.com/search?q=Python%20docs)
    
    Args:
        response: Original response text with markdown links
        broken_urls: List of broken URL info dicts (must contain 'full_match' and 'text' keys)
        
    Returns:
        Response with broken URLs replaced with Brave search URLs
    """
    corrected = response
    replacements_made = 0
    
    for url_info in broken_urls:
        full_match = url_info.get('full_match', '')
        link_text = url_info.get('text', '')
        original_url = url_info.get('url', '')
        
        if not full_match or not link_text:
            logger.warning(f"Skipping broken URL replacement - missing full_match or text: {url_info}")
            continue
        
        if full_match not in corrected:
            logger.debug(f"Broken URL not found in response (may have been in different chunk): {full_match[:50]}...")
            continue
        
        # Create Brave search URL from the link text
        # URL encode the search query to handle special characters
        search_query = quote_plus(link_text)
        brave_search_url = f"https://search.brave.com/search?q={search_query}"
        
        # Create new markdown link with Brave search URL
        new_link = f"[{link_text}]({brave_search_url})"
        
        # Replace the broken link with the search link
        corrected = corrected.replace(full_match, new_link)
        replacements_made += 1
        
        logger.info(
            f"Replaced broken URL with Brave search: "
            f"'{original_url[:50]}...' -> search for '{link_text}'"
        )
    
    if replacements_made > 0:
        logger.info(f"Replaced {replacements_made} broken URL(s) with Brave search links")
    
    return corrected
