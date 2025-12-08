# backend/shared/python_utils/url_normalizer.py
#
# URL normalization utilities for creator income tracking.
# Extracts normalized domains from URLs for privacy-preserving owner identification.

import logging
from urllib.parse import urlparse, urlunparse
from typing import Optional

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
