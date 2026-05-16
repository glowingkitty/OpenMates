# backend/shared/python_utils/url_normalizer.py
#
# URL normalization utilities for creator income tracking.
# Extracts normalized domains from URLs for privacy-preserving owner identification.

import logging
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from typing import Any, Optional
import re

from backend.shared.python_utils.markdown_links import MarkdownLink, iter_markdown_links

logger = logging.getLogger(__name__)
PLAIN_URL_PATTERN = re.compile(r"https?://[^\s<>()]+")
URL_TRAILING_PUNCTUATION = ",.;:!?)]}\"'`"


def _get_safeguard_client():
    """Lazy-load the optional Groq dependency only for model-backed URL checks."""
    from backend.shared.providers.groq.safeguard import get_safeguard_client

    return get_safeguard_client()


def _strip_url_trailing_punctuation(token: str) -> tuple[str, str]:
    """Split punctuation that is adjacent to, but not part of, a URL token."""
    trailing = ""
    while token and token[-1] in URL_TRAILING_PUNCTUATION:
        trailing = token[-1] + trailing
        token = token[:-1]
    return token, trailing


def extract_urls_from_text(text: str) -> set[str]:
    """Extract exact HTTP(S) URL tokens from text."""
    if not isinstance(text, str) or not text:
        return set()

    urls: set[str] = set()
    markdown_links = list(iter_markdown_links(text))
    for link in markdown_links:
        if not link.href.startswith(("http://", "https://")):
            continue
        urls.add(link.href)

    for segment in _text_segments_outside_markdown_links(text, markdown_links):
        for match in PLAIN_URL_PATTERN.finditer(segment):
            url, _trailing = _strip_url_trailing_punctuation(match.group(0))
            if url:
                urls.add(url)

    return urls


def _text_segments_outside_markdown_links(text: str, links: list[MarkdownLink]) -> list[str]:
    """Return text segments that are outside full markdown link spans."""
    segments: list[str] = []
    cursor = 0
    for link in links:
        if cursor < link.full_start:
            segments.append(text[cursor:link.full_start])
        cursor = max(cursor, link.full_end)
    if cursor < len(text):
        segments.append(text[cursor:])
    return segments


def extract_urls_from_content(value: Any) -> set[str]:
    """Recursively extract exact HTTP(S) URLs from source content objects."""
    if isinstance(value, str):
        return extract_urls_from_text(value)
    if isinstance(value, dict):
        urls: set[str] = set()
        for item in value.values():
            urls.update(extract_urls_from_content(item))
        return urls
    if isinstance(value, (list, tuple, set)):
        urls: set[str] = set()
        for item in value:
            urls.update(extract_urls_from_content(item))
        return urls
    return set()


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

    This deterministic helper is kept for URL normalization call sites that need
    a stable URL without arbitrary query/fragment payloads. Path/domain remain.

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


async def sanitize_text_urls_with_safeguard(
    text: str,
    *,
    secrets_manager: Optional[Any] = None,
    log_prefix: str = "",
    allowed_source_urls: Optional[set[str]] = None,
) -> str:
    """
    Process all HTTP(S) URLs through gpt-oss-safeguard.

    The model can only keep an exact URL token that already exists in the
    caller-provided source URL set. Any assistant-created URL absent from the
    source corpus is removed before model safety processing.
    """
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else str(text)

    response_urls = extract_urls_from_text(text)
    if not response_urls:
        return text

    safeguard = _get_safeguard_client()
    if secrets_manager:
        await safeguard.initialize(secrets_manager)

    source_urls = allowed_source_urls if allowed_source_urls is not None else extract_urls_from_text(text)
    source_backed_urls = response_urls & source_urls
    malicious_urls: set[str] = set(source_backed_urls)
    if source_backed_urls:
        verdict = await safeguard.report_malicious_urls(
            urls=sorted(source_backed_urls),
            assistant_response=text,
        )
        malicious_urls = verdict.malicious_urls
        if verdict.error:
            logger.warning(
                f"{log_prefix} URL safety batch failed closed: {verdict.error}"
            )

    async def _clean_url_token(
        token: str,
        *,
        markdown_label: Optional[str] = None,
        strip_trailing: bool = True,
    ) -> str:
        trailing = ""
        if strip_trailing:
            token, trailing = _strip_url_trailing_punctuation(token)

        if token not in source_urls:
            logger.warning(
                f"{log_prefix} URL safety rejected assistant-created link not present in source content: {token}"
            )
            return markdown_label if markdown_label else "[link removed]" + trailing

        if token in malicious_urls:
            logger.info(f"{log_prefix} URL safety removed malicious link")
            return markdown_label if markdown_label else "[link removed]" + trailing
        return token + trailing

    markdown_links = list(iter_markdown_links(text))
    if not markdown_links:
        return await _sanitize_plain_url_segment(text, _clean_url_token)

    parts: list[str] = []
    cursor = 0
    for link in markdown_links:
        segment = text[cursor:link.full_start]
        parts.append(await _sanitize_plain_url_segment(segment, _clean_url_token))
        if link.href.startswith(("http://", "https://")):
            cleaned_url = await _clean_url_token(
                link.href,
                markdown_label=link.label,
                strip_trailing=False,
            )
            parts.append(link.label if cleaned_url == link.label else f"[{link.label}]({cleaned_url})")
        else:
            parts.append(text[link.full_start:link.full_end])
        cursor = link.full_end
    parts.append(await _sanitize_plain_url_segment(text[cursor:], _clean_url_token))
    return "".join(parts)


async def _sanitize_plain_url_segment(segment: str, clean_url_token: Any) -> str:
    """Sanitize plain URLs inside a segment that contains no markdown links."""
    parts: list[str] = []
    cursor = 0
    for match in PLAIN_URL_PATTERN.finditer(segment):
        parts.append(segment[cursor:match.start()])
        parts.append(await clean_url_token(match.group(0)))
        cursor = match.end()
    parts.append(segment[cursor:])
    return "".join(parts)


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
