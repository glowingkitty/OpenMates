"""
Metadata Service

Extracts Open Graph and other metadata from websites.
Handles parsing of HTML to extract:
- Title (og:title, twitter:title, <title>)
- Description (og:description, twitter:description, meta description)
- Image (og:image, twitter:image)
- Favicon (link rel="icon", rel="shortcut icon")
- Site name (og:site_name)
- URL (og:url, canonical)

SECURITY: Text fields (title, description, site_name) are sanitized for prompt
injection attacks before being returned. This protects against malicious websites
that embed injection attempts in their metadata to manipulate LLMs.

Two-layer defense:
1. ASCII smuggling protection (character-level)
2. LLM-based prompt injection detection (semantic-level)

See: docs/architecture/prompt_injection_protection.md
"""

import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch_service import fetch_service
from .cache_service import cache_service
from .content_sanitization import sanitize_metadata_text

logger = logging.getLogger(__name__)


class MetadataService:
    """
    Service for extracting and caching website metadata.
    
    Extracts Open Graph, Twitter Card, and standard HTML metadata
    to provide rich previews for URLs.
    """
    
    async def get_metadata(self, url: str, use_cache: bool = True) -> dict:
        """
        Get metadata for a URL.
        
        Checks cache first, then fetches, parses, and sanitizes if not cached.
        
        SECURITY: Text fields (title, description, site_name) are sanitized for
        prompt injection attacks before caching and returning. This protects
        against malicious websites embedding injection attempts in their metadata.
        
        Args:
            url: Website URL
            use_cache: Whether to use cached metadata (default: True)
            
        Returns:
            Metadata dictionary with keys:
            - url: Canonical URL
            - title: Page title (sanitized)
            - description: Page description (sanitized)
            - image: Preview image URL
            - favicon: Favicon URL
            - site_name: Site name (sanitized)
            
        Raises:
            FetchError: If fetching the page fails
        """
        # Normalize URL for consistent caching
        normalized_url = self._normalize_url(url)
        log_prefix = f"[MetadataService][{normalized_url[:50]}] "
        
        # Check cache first
        # Cached metadata is already sanitized (sanitization happens before caching)
        if use_cache:
            cached = cache_service.get_metadata(normalized_url)
            if cached:
                logger.info(f"{log_prefix}CACHE_HIT")
                return cached
        
        # Cache miss - fetch HTML content
        logger.info(f"{log_prefix}CACHE_MISS - fetching...")
        html = await fetch_service.fetch_html(normalized_url)
        
        # Parse metadata from HTML
        metadata = self._parse_metadata(html, normalized_url)
        
        # =======================================================================
        # SECURITY: Sanitize text fields for prompt injection protection
        # =======================================================================
        # Title, description, and site_name could contain malicious instructions
        # targeting LLMs. We sanitize these fields before caching/returning.
        # Image URLs and favicon URLs are NOT sanitized (they're URLs, not text
        # that will be processed by LLMs).
        # =======================================================================
        
        logger.info(f"{log_prefix}Sanitizing text fields for prompt injection protection...")
        
        # Sanitize title
        if metadata.get("title"):
            metadata["title"] = await sanitize_metadata_text(
                metadata["title"],
                field_name="title",
                log_prefix=log_prefix
            )
        
        # Sanitize description
        if metadata.get("description"):
            metadata["description"] = await sanitize_metadata_text(
                metadata["description"],
                field_name="description",
                log_prefix=log_prefix
            )
        
        # Sanitize site_name
        if metadata.get("site_name"):
            metadata["site_name"] = await sanitize_metadata_text(
                metadata["site_name"],
                field_name="site_name",
                log_prefix=log_prefix
            )
        
        # Cache the sanitized result
        cache_service.set_metadata(normalized_url, metadata)
        
        logger.info(
            f"{log_prefix}Extracted, sanitized, and cached: "
            f"title={(metadata.get('title') or 'N/A')[:30]}..."
        )
        
        return metadata
    
    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL for consistent caching.
        
        - Adds https:// if no scheme
        - Removes trailing slashes
        - Lowercases hostname
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL
        """
        # Add scheme if missing
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        parsed = urlparse(url)
        
        # Lowercase hostname
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        
        # Reconstruct URL with normalized parts
        port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        path = parsed.path.rstrip("/") or "/"
        query = f"?{parsed.query}" if parsed.query else ""
        
        return f"{parsed.scheme}://{hostname}{port}{path}{query}"
    
    def _parse_metadata(self, html: str, url: str) -> dict:
        """
        Parse metadata from HTML content.
        
        Extracts metadata from:
        1. Open Graph tags (og:*)
        2. Twitter Card tags (twitter:*)
        3. Standard HTML meta tags
        4. HTML title tag
        5. Link tags for favicon
        
        Args:
            html: HTML content
            url: Base URL for resolving relative URLs
            
        Returns:
            Metadata dictionary
        """
        soup = BeautifulSoup(html, "lxml")
        
        metadata = {
            "url": url,
            "title": None,
            "description": None,
            "image": None,
            "favicon": None,
            "site_name": None,
        }
        
        # ===========================================
        # Title extraction (priority order)
        # ===========================================
        
        # 1. og:title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            metadata["title"] = og_title["content"].strip()
        
        # 2. twitter:title
        if not metadata["title"]:
            twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
            if twitter_title and twitter_title.get("content"):
                metadata["title"] = twitter_title["content"].strip()
        
        # 3. <title> tag
        if not metadata["title"]:
            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                metadata["title"] = title_tag.string.strip()
        
        # ===========================================
        # Description extraction (priority order)
        # ===========================================
        
        # 1. og:description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            metadata["description"] = og_desc["content"].strip()
        
        # 2. twitter:description
        if not metadata["description"]:
            twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
            if twitter_desc and twitter_desc.get("content"):
                metadata["description"] = twitter_desc["content"].strip()
        
        # 3. meta description
        if not metadata["description"]:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                metadata["description"] = meta_desc["content"].strip()
        
        # ===========================================
        # Image extraction (priority order)
        # ===========================================
        
        # 1. og:image
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            metadata["image"] = self._resolve_url(og_image["content"], url)
        
        # 2. twitter:image
        if not metadata["image"]:
            twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_image and twitter_image.get("content"):
                metadata["image"] = self._resolve_url(twitter_image["content"], url)
        
        # 3. twitter:image:src (alternative)
        if not metadata["image"]:
            twitter_image_src = soup.find("meta", attrs={"name": "twitter:image:src"})
            if twitter_image_src and twitter_image_src.get("content"):
                metadata["image"] = self._resolve_url(twitter_image_src["content"], url)
        
        # ===========================================
        # Favicon extraction (priority order)
        # ===========================================
        
        # Look for various favicon link tags
        favicon_selectors = [
            {"rel": "icon"},
            {"rel": "shortcut icon"},
            {"rel": "apple-touch-icon"},
            {"rel": "apple-touch-icon-precomposed"},
        ]
        
        for selector in favicon_selectors:
            link = soup.find("link", rel=lambda x: x and selector["rel"] in (x if isinstance(x, list) else [x]))
            if link and link.get("href"):
                metadata["favicon"] = self._resolve_url(link["href"], url)
                break
        
        # Fallback: try /favicon.ico
        if not metadata["favicon"]:
            parsed = urlparse(url)
            metadata["favicon"] = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        
        # ===========================================
        # Site name extraction
        # ===========================================
        
        og_site_name = soup.find("meta", property="og:site_name")
        if og_site_name and og_site_name.get("content"):
            metadata["site_name"] = og_site_name["content"].strip()
        
        # Fallback: use hostname
        if not metadata["site_name"]:
            parsed = urlparse(url)
            metadata["site_name"] = parsed.netloc
        
        # ===========================================
        # Canonical URL
        # ===========================================
        
        # Check for og:url
        og_url = soup.find("meta", property="og:url")
        if og_url and og_url.get("content"):
            metadata["url"] = og_url["content"]
        else:
            # Check for canonical link
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                metadata["url"] = canonical["href"]
        
        return metadata
    
    def _resolve_url(self, url: str, base_url: str) -> str:
        """
        Resolve a potentially relative URL against a base URL.
        
        Args:
            url: URL to resolve (may be relative)
            base_url: Base URL for resolution
            
        Returns:
            Absolute URL
        """
        if not url:
            return ""
        
        # Already absolute
        if url.startswith(("http://", "https://", "//")):
            # Handle protocol-relative URLs
            if url.startswith("//"):
                parsed_base = urlparse(base_url)
                return f"{parsed_base.scheme}:{url}"
            return url
        
        # Relative URL - resolve against base
        return urljoin(base_url, url)


# Global metadata service instance
metadata_service = MetadataService()

