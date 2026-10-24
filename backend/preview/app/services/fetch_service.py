"""
Fetch Service

Handles fetching external resources (images, favicons, HTML) with:
- SSRF protection (blocks private/internal IPs)
- Content validation (size limits, content type checks)
- Timeout handling
- Direct HTTP fetching with no block-evasion retries
- Browser-like headers for better compatibility
"""

import logging
import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

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
    
    Uses direct HTTP requests and preserves source access failures.
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
    
    BROWSER_HEADERS = {"User-Agent": settings.user_agent, "Accept": "*/*"}

    def __init__(self):
        """Initialize the direct HTTP client."""
        # Configure direct HTTP client (for images, favicons, fallback)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            follow_redirects=True,
            max_redirects=5,
            headers=self.BROWSER_HEADERS
        )
        
    async def close(self):
        """Close all HTTP clients."""
        await self._client.aclose()
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
    
    async def _stream_image(
        self,
        client: httpx.AsyncClient,
        validated_url: str,
        headers: dict,
        max_size: int,
        min_size: int,
        client_name: str
    ) -> Tuple[bytes, str]:
        """
        Internal: stream an image from a URL using the given client and headers.

        Validates the upstream Content-Type and size constraints, then returns the
        raw bytes and content-type string.

        Args:
            client: httpx.AsyncClient to use for the request
            validated_url: Pre-validated image URL
            headers: HTTP headers to send with the request
            max_size: Maximum allowed response size in bytes
            min_size: Minimum required response size in bytes (0 = no minimum)
            client_name: Label used in log messages ("direct")

        Returns:
            Tuple of (image_bytes, content_type)

        Raises:
            FetchError: On HTTP error, unsupported content-type, or size violation
            httpx.TimeoutException: On request timeout
            httpx.RequestError: On network-level error
        """
        async with client.stream("GET", validated_url, headers=headers) as response:
            if response.status_code != 200:
                logger.warning(
                    f"[FetchService] Image fetch failed ({client_name}): "
                    f"{response.status_code} for {validated_url[:50]}..."
                )
                raise FetchError(
                    f"Failed to fetch image: HTTP {response.status_code}",
                    response.status_code
                )

            # Validate Content-Type before reading the body
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in settings.allowed_image_types:
                logger.warning(
                    f"[FetchService] Invalid content type ({client_name}): "
                    f"{content_type!r} for {validated_url[:50]}..."
                )
                raise FetchError(
                    f"Invalid content type: {content_type}",
                    415  # Unsupported Media Type
                )

            # Reject oversized images early via Content-Length header
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_size:
                logger.warning(
                    f"[FetchService] Image too large ({client_name}): "
                    f"{content_length} bytes for {validated_url[:50]}..."
                )
                raise FetchError(
                    f"Image too large: {content_length} bytes (max: {max_size})",
                    413
                )

            # Stream with a running size limit
            chunks = []
            total_size = 0

            async for chunk in response.aiter_bytes(chunk_size=8192):
                total_size += len(chunk)
                if total_size > max_size:
                    logger.warning(
                        f"[FetchService] Image exceeded size limit during download "
                        f"({client_name}): {validated_url[:50]}..."
                    )
                    raise FetchError(
                        f"Image too large: exceeded {max_size} bytes",
                        413
                    )
                chunks.append(chunk)

            image_data = b"".join(chunks)

            if min_size > 0 and len(image_data) < min_size:
                logger.warning(
                    f"[FetchService] Image too small ({client_name}): "
                    f"{len(image_data)} bytes (min: {min_size}) for {validated_url[:50]}..."
                )
                raise FetchError(
                    f"Image too small: {len(image_data)} bytes (min: {min_size})",
                    422
                )

            logger.debug(
                f"[FetchService] Fetched image ({client_name}): "
                f"{len(image_data)} bytes, {content_type} from {validated_url[:50]}..."
            )

            return image_data, content_type

    async def fetch_image(
        self,
        url: str,
        max_size: Optional[int] = None,
        min_size: int = 0
    ) -> Tuple[bytes, str]:
        """Fetch an image directly; source access failures remain visible."""
        max_size = max_size or settings.max_image_size_bytes

        # Validate URL first (SSRF protection)
        validated_url = await self._validate_url(url)

        # Use stable image headers without an origin-derived Referer.
        headers = self._get_image_headers(validated_url)

        try:
            return await self._stream_image(
                self._client, validated_url, headers, max_size, min_size, "direct"
            )
        except httpx.TimeoutException:
            logger.warning(f"[FetchService] Timeout fetching image (direct): {validated_url[:50]}...")
            raise FetchError("Request timeout", 504)
        except httpx.RequestError as e:
            logger.error(f"[FetchService] Request error fetching image (direct): {e}")
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
        """Return stable headers identifying the configured service client."""
        return {"User-Agent": settings.user_agent, "Accept": "text/html", "Accept-Language": "en"}

    def _get_image_headers(self, image_url: str) -> dict:
        """Request image data without impersonating a source-page browser."""
        return {"User-Agent": settings.user_agent, "Accept": "image/*"}

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
            client_name: Name for logging ("direct")
            
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
        
        Source access failures are returned without changing egress or retrying.

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
        
        # Use the configured service headers
        headers = self._get_randomized_headers()
        
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

