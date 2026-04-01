# backend/shared/python_utils/url_normalizer.py
#
# URL normalization utilities for creator income tracking.
# Extracts normalized domains from URLs for privacy-preserving owner identification.

import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from typing import Optional
import re

logger = logging.getLogger(__name__)


def extract_domain_from_url(url: str) -> Optional[str]:
    """
    Extract and normalize domain from a URL for creator income tracking.
    
    Normalization steps:
    1. Parse URL and extract domain
    2. Convert to lowercase
    3. Remove 'www.' prefix
    4. Remove port numbers
    
    This normalized domain is used as the owner identifier for websites.
    
    Args:
        url: The URL to extract domain from
        
    Returns:
        Normalized domain string (e.g., 'example.com') or None if URL is invalid
        
    Example:
        >>> extract_domain_from_url("https://www.Example.com:443/article?utm_source=twitter")
        'example.com'
    """
    try:
        parsed = urlparse(url)
        
        if not parsed.netloc:
            logger.warning(f"URL has no netloc (domain): {url}")
            return None
        
        # Extract domain (netloc includes port, so we need to handle that)
        domain = parsed.netloc.lower()
        
        # Remove port number if present (e.g., 'example.com:443' -> 'example.com')
        if ':' in domain:
            domain = domain.split(':')[0]
        
        # Remove 'www.' prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        
        if not domain:
            logger.warning(f"Domain is empty after normalization: {url}")
            return None
        
        return domain
        
    except Exception as e:
        logger.error(f"Error extracting domain from URL '{url}': {e}", exc_info=True)
        return None


def sanitize_url_remove_fragment(url: str) -> Optional[str]:
    """
    Sanitize URL by removing fragment parameters (#{text}) as a security measure.
    
    URL fragments (hash parameters) are client-side only and not sent to servers.
    However, they can contain malicious content and are not needed for web scraping
    or video transcript fetching. Removing them prevents potential security issues
    and ensures clean URLs are passed to external APIs.
    
    This function preserves all other URL components (scheme, domain, path, query params)
    and only removes the fragment portion.
    
    Args:
        url: The URL to sanitize
        
    Returns:
        Sanitized URL string without fragment, or None if URL is invalid
        
    Example:
        >>> sanitize_url_remove_fragment("https://example.com/article?param=value#malicious-content")
        'https://example.com/article?param=value'
        >>> sanitize_url_remove_fragment("https://youtube.com/watch?v=123#section")
        'https://youtube.com/watch?v=123'
    """
    try:
        parsed = urlparse(url)
        
        if not parsed.netloc:
            logger.warning(f"URL has no netloc (domain): {url}")
            return None
        
        # Reconstruct URL without fragment (preserve everything else)
        sanitized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            ''  # fragment (removed for security)
        ))
        
        return sanitized
        
    except Exception as e:
        logger.error(f"Error sanitizing URL '{url}': {e}", exc_info=True)
        return None


# YouTube video ID: exactly 11 characters, alphanumeric + hyphen + underscore
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

# YouTube timestamp: integer seconds, or shorthand like 1h2m3s
_YOUTUBE_TIMESTAMP_PATTERN = re.compile(r"^(\d+[hms]?)+$")

# YouTube hostnames (with or without www.)
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}


def _is_youtube_watch_url(parsed: "urlparse") -> bool:
    """Check if a parsed URL is a YouTube watch page."""
    return parsed.netloc.lower() in _YOUTUBE_HOSTS and parsed.path == "/watch"


def _extract_youtube_safe_params(query_string: str) -> str:
    """
    Extract only safe YouTube params (v, t) from a query string.

    Validates:
    - v (video ID): must be exactly 11 chars, alphanumeric + hyphen + underscore
    - t (timestamp): must be digits or shorthand (e.g. 1h2m3s)

    All other params (si, utm_source, list, index, etc.) are stripped.
    """
    params = parse_qs(query_string, keep_blank_values=False)
    safe = {}

    # Video ID (required for the URL to work)
    video_ids = params.get("v", [])
    if video_ids and _YOUTUBE_VIDEO_ID_PATTERN.match(video_ids[0]):
        safe["v"] = video_ids[0]

    # Timestamp (optional)
    timestamps = params.get("t", [])
    if timestamps and _YOUTUBE_TIMESTAMP_PATTERN.match(timestamps[0]):
        safe["t"] = timestamps[0]

    return urlencode(safe) if safe else ""


def sanitize_url_remove_query_and_fragment(url: str) -> Optional[str]:
    """
    Sanitize URL by removing both query parameters and fragment.

    This is used for user/assistant message content to prevent data leakage via
    URL parameters and fragment payloads. Path and domain are preserved.

    Exception: YouTube URLs need the ``v`` parameter (video ID) and optionally
    ``t`` (timestamp) to function. These are preserved after validation while
    all other parameters (tracking, analytics) are stripped.
    """
    try:
        parsed = urlparse(url)

        if not parsed.netloc:
            logger.warning(f"URL has no netloc (domain): {url}")
            return None

        # YouTube exception: preserve video ID (v) and timestamp (t) parameters
        preserved_query = ""
        if _is_youtube_watch_url(parsed):
            preserved_query = _extract_youtube_safe_params(parsed.query)

        sanitized = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                preserved_query,
                "",
            )
        )
        return sanitized

    except Exception as e:
        logger.error(f"Error sanitizing URL '{url}': {e}", exc_info=True)
        return None


def sanitize_text_urls_remove_query_and_fragment(text: str) -> str:
    """
    Remove query parameters and fragments from all HTTP(S) URLs in text.

    Works for markdown links and plain URLs. Leaves non-URL text unchanged.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else str(text)

    markdown_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
    plain_url_pattern = re.compile(r"https?://[^\s<>()]+")

    def _sanitize_url_token(token: str) -> str:
        trailing = ""
        while token and token[-1] in ",.;:!?)]}\"'":
            trailing = token[-1] + trailing
            token = token[:-1]
        cleaned = sanitize_url_remove_query_and_fragment(token)
        if not cleaned:
            return token + trailing
        return cleaned + trailing

    def _replace_markdown(match: re.Match[str]) -> str:
        label = match.group(1)
        url = match.group(2)
        return f"[{label}]({_sanitize_url_token(url)})"

    sanitized = markdown_pattern.sub(_replace_markdown, text)

    def _replace_plain(match: re.Match[str]) -> str:
        return _sanitize_url_token(match.group(0))

    sanitized = plain_url_pattern.sub(_replace_plain, sanitized)
    return sanitized


def normalize_url_for_content_id(url: str) -> Optional[str]:
    """
    Normalize URL for content ID hashing (removes query params and fragments).
    
    This is used to create a consistent content identifier for the same page,
    regardless of tracking parameters or hash fragments.
    
    Normalization steps:
    1. Remove query parameters (e.g., ?utm_source=...)
    2. Remove hash fragments (e.g., #section)
    3. Normalize domain (lowercase, remove www, remove port)
    4. Remove trailing slashes (except for root URL)
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL string or None if URL is invalid
        
    Example:
        >>> normalize_url_for_content_id("https://www.Example.com/article?utm_source=twitter&ref=123#section")
        'https://example.com/article'
    """
    try:
        parsed = urlparse(url)
        
        if not parsed.netloc:
            logger.warning(f"URL has no netloc (domain): {url}")
            return None
        
        # Normalize domain
        domain = parsed.netloc.lower()
        
        # Remove port number if present
        if ':' in domain:
            domain = domain.split(':')[0]
        
        # Remove 'www.' prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        
        if not domain:
            logger.warning(f"Domain is empty after normalization: {url}")
            return None
        
        # Normalize path: remove trailing slash (except for root)
        path = parsed.path.rstrip('/') or '/'
        
        # Reconstruct URL without query and fragment
        normalized = urlunparse((
            parsed.scheme,
            domain,
            path,
            '',  # params
            '',  # query (removed)
            ''   # fragment (removed)
        ))
        
        return normalized
        
    except Exception as e:
        logger.error(f"Error normalizing URL '{url}': {e}", exc_info=True)
        return None
