"""
Fetch Service

Handles fetching external resources (images, favicons, HTML) with:
- SSRF protection (blocks private/internal IPs)
- Content validation (size limits, content type checks)
- Timeout handling
- Webshare proxy support for metadata fetching (avoids IP blocks)
- Browser-like headers for better compatibility
"""

import logging
import ipaddress
import socket
import random
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# ===========================================
# User-Agent Generation (Anti-Detection)
# ===========================================

# Check if user-agents library is available for dynamic User-Agent generation
try:
    from user_agents import UserAgent
    USER_AGENTS_AVAILABLE = True
except ImportError:
    USER_AGENTS_AVAILABLE = False
    logger.warning(
        "[FetchService] user-agents library not available. "
        "Using static fallback User-Agents. Install with: pip install user-agents"
    )

# Fallback user agents list (updated periodically to match current browser versions)
FALLBACK_USER_AGENTS = [
    # Chrome on Windows (most common)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]


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
            user_agent = UserAgent()
            ua_string = user_agent.random
            logger.debug(f"[FetchService] Generated dynamic User-Agent: {ua_string[:50]}...")
            return ua_string
        except Exception as e:
            logger.warning(f"[FetchService] Failed to generate dynamic User-Agent: {e}. Falling back to static list.")
    
    # Fallback to static list if library fails or unavailable
    return random.choice(FALLBACK_USER_AGENTS)


class FetchError(Exception):
    """Custom exception for fetch errors with status codes."""
    
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class FetchService:
    """
    Service for fetching external resources securely.
    
    Implements security measures to prevent SSRF attacks and
    validates content before returning.
    
    Supports optional Webshare proxy for reliable metadata fetching
    from sites that block direct server requests.
    """
    
    # Private IP ranges to block (SSRF protection)
    PRIVATE_IP_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),  # Link-local
        ipaddress.ip_network("::1/128"),  # IPv6 localhost
        ipaddress.ip_network("fc00::/7"),  # IPv6 private
        ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ]
    
    # Browser-like headers for better compatibility
    # NOTE: Don't set Accept-Encoding manually - httpx handles it automatically
    # and will only advertise encodings it can decode (gzip, deflate, br if brotli installed)
    BROWSER_HEADERS = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    
    def __init__(self):
        """Initialize fetch service with HTTP clients (direct and proxied)."""
        # Configure direct HTTP client (for images, favicons, fallback)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            follow_redirects=True,
            max_redirects=5,
            headers=self.BROWSER_HEADERS
        )
        
        # Configure proxied HTTP client (for HTML/metadata fetching)
        self._proxy_client: Optional[httpx.AsyncClient] = None
        if settings.webshare_proxy_url:
            self._proxy_client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.request_timeout_seconds + 5),  # Extra time for proxy
                follow_redirects=True,
                max_redirects=5,
                headers=self.BROWSER_HEADERS,
                proxy=settings.webshare_proxy_url
            )
            logger.info("[FetchService] Initialized with Webshare proxy")
        else:
            logger.warning(
                "[FetchService] No proxy configured. Set SECRET__WEBSHARE__PROXY_USERNAME "
                "and SECRET__WEBSHARE__PROXY_PASSWORD env vars. "
                "Metadata fetching may fail on sites that block direct requests."
            )
    
    async def close(self):
        """Close all HTTP clients."""
        await self._client.aclose()
        if self._proxy_client:
            await self._proxy_client.aclose()
        logger.info("[FetchService] HTTP clients closed")
    
    def _is_private_ip(self, ip_str: str) -> bool:
        """
        Check if an IP address is private/internal.
        
        Args:
            ip_str: IP address string
            
        Returns:
            True if IP is private/internal, False otherwise
        """
        try:
            ip = ipaddress.ip_address(ip_str)
            for private_range in self.PRIVATE_IP_RANGES:
                if ip in private_range:
                    return True
            return False
        except ValueError:
            # Invalid IP address format
            return True  # Block by default
    
    async def _validate_url(self, url: str) -> str:
        """
        Validate and sanitize URL for fetching.
        
        Performs:
        - URL parsing validation
        - Scheme validation (only http/https)
        - DNS resolution to check for private IPs
        
        Args:
            url: URL to validate
            
        Returns:
            Validated URL
            
        Raises:
            FetchError: If URL is invalid or points to private IP
        """
        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            logger.warning(f"[FetchService] Invalid URL format: {url} - {e}")
            raise FetchError(f"Invalid URL format: {e}", 400)
        
        # Validate scheme
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"[FetchService] Invalid URL scheme: {parsed.scheme}")
            raise FetchError(f"Invalid URL scheme: {parsed.scheme}. Only http/https allowed.", 400)
        
        # Validate hostname exists
        if not parsed.hostname:
            logger.warning(f"[FetchService] Missing hostname in URL: {url}")
            raise FetchError("Missing hostname in URL", 400)
        
        # SSRF protection: resolve hostname and check if it's a private IP
        if settings.block_private_ips:
            try:
                # Get all IPs for the hostname
                addr_info = socket.getaddrinfo(parsed.hostname, None)
                for info in addr_info:
                    ip = info[4][0]
                    if self._is_private_ip(ip):
                        logger.warning(
                            f"[FetchService] SSRF blocked: {parsed.hostname} "
                            f"resolves to private IP {ip}"
                        )
                        raise FetchError(
                            "Access to internal/private networks is not allowed",
                            403
                        )
            except socket.gaierror as e:
                logger.warning(f"[FetchService] DNS resolution failed for {parsed.hostname}: {e}")
                raise FetchError(f"Cannot resolve hostname: {parsed.hostname}", 400)
        
        return url
    
    async def fetch_image(
        self,
        url: str,
        max_size: Optional[int] = None,
        min_size: int = 0
    ) -> Tuple[bytes, str]:
        """
        Fetch an image from URL.
        
        Args:
            url: Image URL
            max_size: Maximum allowed size in bytes (uses default if not provided)
            min_size: Minimum required size in bytes (default: 0, no minimum)
            
        Returns:
            Tuple of (image_bytes, content_type)
            
        Raises:
            FetchError: If fetch fails or validation fails
        """
        max_size = max_size or settings.max_image_size_bytes
        
        # Validate URL first
        validated_url = await self._validate_url(url)
        
        try:
            # Use streaming to check size before downloading full content
            async with self._client.stream("GET", validated_url) as response:
                # Check status code
                if response.status_code != 200:
                    logger.warning(
                        f"[FetchService] Image fetch failed: {response.status_code} for {url[:50]}..."
                    )
                    raise FetchError(
                        f"Failed to fetch image: HTTP {response.status_code}",
                        response.status_code
                    )
                
                # Check content type
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type not in settings.allowed_image_types:
                    logger.warning(
                        f"[FetchService] Invalid content type: {content_type} for {url[:50]}..."
                    )
                    raise FetchError(
                        f"Invalid content type: {content_type}",
                        415  # Unsupported Media Type
                    )
                
                # Check content length if provided
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    logger.warning(
                        f"[FetchService] Image too large: {content_length} bytes for {url[:50]}..."
                    )
                    raise FetchError(
                        f"Image too large: {content_length} bytes (max: {max_size})",
                        413  # Payload Too Large
                    )
                
                # Download content with size limit
                chunks = []
                total_size = 0
                
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    total_size += len(chunk)
                    if total_size > max_size:
                        logger.warning(
                            f"[FetchService] Image exceeded size limit during download: {url[:50]}..."
                        )
                        raise FetchError(
                            f"Image too large: exceeded {max_size} bytes",
                            413
                        )
                    chunks.append(chunk)
                
                image_data = b"".join(chunks)
                
                # Check minimum size requirement
                if min_size > 0 and len(image_data) < min_size:
                    logger.warning(
                        f"[FetchService] Image too small: {len(image_data)} bytes "
                        f"(min: {min_size}) for {url[:50]}..."
                    )
                    raise FetchError(
                        f"Image too small: {len(image_data)} bytes (min: {min_size})",
                        422  # Unprocessable Entity
                    )
                
                logger.debug(
                    f"[FetchService] Fetched image ({len(image_data)} bytes, {content_type}) "
                    f"from {url[:50]}..."
                )
                
                return image_data, content_type
                
        except httpx.TimeoutException:
            logger.warning(f"[FetchService] Timeout fetching image: {url[:50]}...")
            raise FetchError("Request timeout", 504)
        except httpx.RequestError as e:
            logger.error(f"[FetchService] Request error fetching image: {e}")
            raise FetchError(f"Request failed: {str(e)}", 502)
    
    async def fetch_favicon(self, url: str) -> Tuple[bytes, str]:
        """
        Fetch favicon for a website.
        
        Tries multiple sources in order:
        1. /favicon.ico at root
        2. Google Favicon Service (fallback)
        
        Args:
            url: Website URL (not favicon URL)
            
        Returns:
            Tuple of (favicon_bytes, content_type)
            
        Raises:
            FetchError: If all fetch attempts fail
        """
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try direct favicon.ico first
        favicon_urls = [
            f"{base_url}/favicon.ico",
            # Google Favicon Service as reliable fallback
            f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"
        ]
        
        last_error = None
        for favicon_url in favicon_urls:
            try:
                logger.debug(f"[FetchService] Trying favicon URL: {favicon_url}")
                return await self.fetch_image(
                    favicon_url,
                    max_size=settings.max_favicon_size_bytes,
                    min_size=settings.min_favicon_size_bytes
                )
            except FetchError as e:
                last_error = e
                logger.debug(f"[FetchService] Favicon fetch failed: {e.message}")
                continue
        
        # All attempts failed
        raise FetchError(
            f"Could not fetch favicon for {parsed.netloc}: {last_error.message if last_error else 'Unknown error'}",
            404
        )
    
    def _get_randomized_headers(self) -> dict:
        """
        Generate randomized HTTP headers to avoid fingerprinting.
        
        Similar to url_validator.py pattern - randomizes User-Agent,
        Accept-Language, and other headers to look like different browsers.
        Each call generates a fresh random User-Agent for better anti-detection.
        
        Returns:
            Dict of HTTP headers
        """
        accept_languages = [
            "en-US,en;q=0.9",
            "en-US,en;q=0.8",
            "en-US,en;q=0.9,es;q=0.8",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,de;q=0.8",
            "de-DE,de;q=0.9,en;q=0.8",
        ]
        
        # Generate fresh random User-Agent for each request
        user_agent = _generate_random_user_agent()
        
        # NOTE: Don't set Accept-Encoding manually - httpx handles it automatically
        # and will only advertise encodings it can decode (gzip, deflate, br if brotli installed)
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": random.choice(accept_languages),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": random.choice(["1", "0"]),
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Connection": "close",  # Force connection close for IP rotation with proxy
        }
    
    async def _fetch_html_with_client(
        self, 
        client: httpx.AsyncClient, 
        url: str, 
        headers: dict, 
        max_size: int,
        client_name: str
    ) -> str:
        """
        Internal method to fetch HTML with a specific client.
        
        Args:
            client: HTTP client to use
            url: Validated URL to fetch
            headers: HTTP headers to send
            max_size: Maximum HTML size in bytes
            client_name: Name for logging (e.g., "proxy", "direct")
            
        Returns:
            HTML content as string
            
        Raises:
            httpx.TimeoutException: On timeout
            httpx.RequestError: On network error
            FetchError: On HTTP error or size limit
        """
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                logger.warning(
                    f"[FetchService] HTML fetch failed ({client_name}): "
                    f"{response.status_code} for {url[:50]}..."
                )
                raise FetchError(
                    f"Failed to fetch page: HTTP {response.status_code}",
                    response.status_code
                )
            
            # Check content length
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_size:
                logger.warning(f"[FetchService] HTML too large: {content_length} bytes")
                raise FetchError(f"Page too large: {content_length} bytes", 413)
            
            # Download with size limit
            chunks = []
            total_size = 0
            
            async for chunk in response.aiter_bytes(chunk_size=8192):
                total_size += len(chunk)
                if total_size > max_size:
                    # For HTML, we can still use partial content
                    break
                chunks.append(chunk)
            
            # Decode HTML
            content = b"".join(chunks)
            
            # Try to detect encoding from response or default to utf-8
            encoding = response.encoding or "utf-8"
            try:
                html = content.decode(encoding)
            except UnicodeDecodeError:
                # Fallback to utf-8 with error handling
                html = content.decode("utf-8", errors="replace")
            
            logger.debug(
                f"[FetchService] Fetched HTML ({len(html)} chars, {client_name}) from {url[:50]}..."
            )
            
            return html
    
    async def fetch_html(self, url: str, max_size: int = 5 * 1024 * 1024) -> str:
        """
        Fetch HTML content from URL for metadata extraction.
        
        Uses Webshare proxy if configured (recommended for reliable fetching).
        Falls back to direct connection if proxy fails with network errors.
        Randomizes headers to avoid bot detection.
        
        Args:
            url: Website URL
            max_size: Maximum HTML size in bytes (default: 5MB)
            
        Returns:
            HTML content as string
            
        Raises:
            FetchError: If fetch fails
        """
        # Validate URL first
        validated_url = await self._validate_url(url)
        
        # Use randomized headers for each request
        headers = self._get_randomized_headers()
        
        # Try proxy first if configured
        use_proxy = settings.use_proxy_for_metadata and self._proxy_client is not None
        
        if use_proxy:
            logger.debug(f"[FetchService] Trying Webshare proxy for HTML fetch: {url[:50]}...")
            try:
                return await self._fetch_html_with_client(
                    self._proxy_client, validated_url, headers, max_size, "proxy"
                )
            except httpx.TimeoutException:
                logger.warning(
                    f"[FetchService] Proxy timeout for {url[:50]}... falling back to direct"
                )
            except httpx.RequestError as e:
                logger.warning(
                    f"[FetchService] Proxy request error for {url[:50]}...: {e}. "
                    f"Falling back to direct connection"
                )
            except FetchError as e:
                # For HTTP errors (4xx/5xx), also try direct - the proxy might be causing issues
                if e.status_code >= 400 and e.status_code < 500:
                    logger.warning(
                        f"[FetchService] Proxy returned HTTP {e.status_code} for {url[:50]}... "
                        f"falling back to direct"
                    )
                else:
                    # For server errors (5xx), re-raise
                    raise
        
        # Direct connection (either as primary or fallback)
        logger.debug(f"[FetchService] Using direct connection for HTML fetch: {url[:50]}...")
        try:
            return await self._fetch_html_with_client(
                self._client, validated_url, headers, max_size, "direct"
            )
        except httpx.TimeoutException:
            logger.warning(f"[FetchService] Timeout fetching HTML: {url[:50]}...")
            raise FetchError("Request timeout", 504)
        except httpx.RequestError as e:
            logger.error(f"[FetchService] Request error fetching HTML: {e}")
            raise FetchError(f"Request failed: {str(e)}", 502)


# Global fetch service instance
fetch_service = FetchService()

