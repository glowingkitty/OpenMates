# backend/apps/ai/processing/url_validator.py
# URL extraction and validation for assistant responses.
# Validates URLs paragraph-by-paragraph as responses are streamed.

import re
import httpx
import asyncio
import logging
from typing import List, Dict, Any, Optional

from backend.shared.python_utils.url_normalizer import sanitize_url_remove_fragment

logger = logging.getLogger(__name__)

# URL validation timeout (seconds)
URL_VALIDATION_TIMEOUT = 5.0


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


async def check_url_status(url: str, timeout: float = URL_VALIDATION_TIMEOUT) -> Dict[str, Any]:
    """
    Check if URL is accessible. Returns status dict with:
    - is_valid: bool (True if 2xx status)
    - status_code: int or None
    - error_type: str ('404', '4xx', '5xx', 'timeout', 'connection_error', etc.)
    - is_temporary: bool (True for 5xx/timeouts - might be temporary)
    
    Uses HEAD request first (more efficient), falls back to GET if HEAD not supported.
    Includes User-Agent header to avoid bot detection/datacenter blocking.
    
    **Security**: URL fragments (#{text}) are removed before validation as a security measure.
    Fragments can contain malicious content and are not needed for URL validation.
    
    **Monitoring for Datacenter Blocking:**
    If broken URLs are not being removed from assistant responses, this may indicate
    that providers are blocking requests from datacenter IPs. In such cases:
    - Monitor logs for high rates of 'connection_error' or 'timeout' errors
    - Check if valid URLs are incorrectly marked as broken
    - Consider adding Oxylabs proxy support (similar to YouTube transcript skill)
      - See backend/apps/videos/skills/transcript_skill.py for Oxylabs implementation
      - HEAD requests work through Oxylabs proxy (standard HTTP method)
      - Traffic is minimal (~1.46 KB per URL with HEAD, ~129 MB/month for 30k messages)
      - Cost would be ~$0.08/month (datacenter) or ~$1/month (residential)
    
    Args:
        url: URL to check
        timeout: Timeout in seconds for the HTTP request
        
    Returns:
        Dict with validation results
    """
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
    
    try:
        # Use a user agent to appear more like a browser and avoid datacenter detection
        # Some providers block requests that look like bots/scrapers
        # If we notice broken URLs aren't being removed, this may indicate datacenter blocking
        # See docstring above for monitoring and Oxylabs proxy option
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; OpenMates/1.0; +https://openmates.org)'
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            # Use HEAD request first (faster), fallback to GET if HEAD not supported
            # HEAD is more efficient - only returns headers, not body
            # Fallback to GET only if HEAD returns 405 (Method Not Allowed) or 501 (Not Implemented)
            response = None
            try:
                # Note: follow_redirects is already set to True on the client (line 80)
                # so we don't need to pass it again, but removing allow_redirects which was incorrect
                response = await client.head(url)
                # If HEAD succeeds, use it (even if status is 404/500 - that's valid info)
            except httpx.HTTPStatusError as e:
                # HEAD returned an error status - check if it's because HEAD isn't supported
                if e.response.status_code in [405, 501]:
                    # HEAD method not allowed/implemented - fallback to GET
                    try:
                        # Note: follow_redirects is already set to True on the client (line 80)
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
    task_id: str
) -> List[Dict[str, Any]]:
    """
    Extract and validate all URLs from a paragraph in background.
    Returns list of validation results for each URL found.
    
    Args:
        paragraph: Paragraph text to validate URLs in
        task_id: Task ID for logging
        
    Returns:
        List of validation results, each containing URL info and validation status
    """
    urls = await extract_urls_from_markdown(paragraph)
    
    if not urls:
        return []
    
    logger.debug(f"[{task_id}] Validating {len(urls)} URL(s) in paragraph")
    
    # Check all URLs in parallel
    validation_tasks = [check_url_status(url_info['url']) for url_info in urls]
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
    
    # Log broken URLs
    broken_urls = [r for r in validation_results if not r.get('is_valid') and not r.get('is_temporary')]
    if broken_urls:
        logger.info(
            f"[{task_id}] Found {len(broken_urls)} broken URL(s) in paragraph: "
            f"{[r['url'] for r in broken_urls]}"
        )
    
    return validation_results

