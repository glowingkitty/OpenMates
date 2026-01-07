"""
Preview Server Configuration

Manages all configuration settings for the preview server including:
- Cache settings (size limits, TTL)
- Security settings (allowed domains, rate limits)
- Storage paths
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, AliasChoices


class Settings(BaseSettings):
    """
    Preview server configuration settings.
    
    Environment variables can override these defaults.
    Prefix: PREVIEW_ (e.g., PREVIEW_CACHE_MAX_SIZE_MB)
    """
    
    # ===========================================
    # Server Settings
    # ===========================================
    
    # Server host and port
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8080, description="Server port")
    
    # Environment (development, staging, production)
    environment: str = Field(default="development", description="Server environment")
    
    # Debug mode (enables extra logging)
    debug: bool = Field(default=False, description="Enable debug mode")
    
    # ===========================================
    # Cache Settings
    # ===========================================
    
    # Maximum cache size in MB (default: 10GB for images, 500MB for metadata)
    cache_max_size_mb: int = Field(default=10240, description="Max image cache size in MB (10GB)")
    metadata_cache_max_size_mb: int = Field(default=500, description="Max metadata cache size in MB (500MB)")
    
    # Cache directory path
    cache_dir: str = Field(default="/app/cache", description="Cache directory path")
    
    # Cache TTL in seconds (default: 7 days for images, 24 hours for metadata)
    image_cache_ttl_seconds: int = Field(default=604800, description="Image cache TTL (7 days)")
    favicon_cache_ttl_seconds: int = Field(default=604800, description="Favicon cache TTL (7 days)")
    metadata_cache_ttl_seconds: int = Field(default=86400, description="Metadata cache TTL (24 hours)")
    
    # ===========================================
    # Image Settings
    # ===========================================
    
    # Maximum image size to fetch (in bytes, default: 10MB)
    max_image_size_bytes: int = Field(default=10485760, description="Max image size to fetch")
    
    # Maximum favicon size to fetch (in bytes, default: 1MB)
    max_favicon_size_bytes: int = Field(default=1048576, description="Max favicon size to fetch")
    
    # Minimum favicon size to accept (in bytes, default: 50 bytes)
    # Favicons smaller than this are treated as invalid and skipped
    min_favicon_size_bytes: int = Field(default=50, description="Min favicon size to accept")
    
    # Image resizing (0 = no resize, otherwise max width/height)
    max_image_width: int = Field(default=1920, description="Max image width (0 = no resize)")
    max_image_height: int = Field(default=1080, description="Max image height (0 = no resize)")
    
    # JPEG quality for resized images (1-100)
    jpeg_quality: int = Field(default=85, description="JPEG quality for resized images")
    
    # ===========================================
    # Proxy Settings (Webshare)
    # ===========================================
    # Reuses the same env var names as the main backend for consistency.
    # These are the same credentials defined in .env.example lines 71-72.
    
    # Webshare credentials for rotating residential proxy
    # Used to fetch website metadata from sites that block datacenter IPs
    # Accepts both: SECRET__WEBSHARE__PROXY_USERNAME (main backend) or PREVIEW_WEBSHARE_USERNAME
    webshare_username: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "SECRET__WEBSHARE__PROXY_USERNAME",  # Main backend format (shared .env)
            "PREVIEW_WEBSHARE_USERNAME"  # Preview-specific with env_prefix
        ),
        description="Webshare proxy username (same as main backend)"
    )
    webshare_password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "SECRET__WEBSHARE__PROXY_PASSWORD",  # Main backend format (shared .env)
            "PREVIEW_WEBSHARE_PASSWORD"  # Preview-specific with env_prefix  
        ),
        description="Webshare proxy password (same as main backend)"
    )
    
    # Webshare proxy host (default is their rotating residential proxy endpoint)
    webshare_proxy_host: str = Field(
        default="proxy.webshare.io",
        description="Webshare proxy host"
    )
    webshare_proxy_port: int = Field(
        default=80,
        description="Webshare proxy port"
    )
    
    # Whether to use proxy for HTML/metadata fetching (recommended: True)
    use_proxy_for_metadata: bool = Field(
        default=True,
        description="Use proxy for metadata/HTML fetching"
    )
    
    # Whether to use proxy for image fetching (can be False to save proxy bandwidth)
    use_proxy_for_images: bool = Field(
        default=False,
        description="Use proxy for image fetching"
    )
    
    @property
    def webshare_proxy_url(self) -> Optional[str]:
        """Build Webshare proxy URL from credentials if available."""
        if self.webshare_username and self.webshare_password:
            return f"http://{self.webshare_username}:{self.webshare_password}@{self.webshare_proxy_host}:{self.webshare_proxy_port}"
        return None
    
    # ===========================================
    # Security Settings
    # ===========================================
    
    # Request timeout in seconds
    request_timeout_seconds: int = Field(default=10, description="External request timeout")
    
    # User agent for outgoing requests (use a realistic browser UA for better compatibility)
    user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        description="User agent for outgoing requests"
    )
    
    # Rate limiting (requests per minute per IP, 0 = disabled)
    rate_limit_per_minute: int = Field(default=60, description="Rate limit per IP (0 = disabled)")
    
    # Block private/internal IP addresses (SSRF protection)
    block_private_ips: bool = Field(default=True, description="Block requests to private IPs")
    
    # Allowed image content types
    allowed_image_types: list[str] = Field(
        default=[
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            "image/x-icon",
            "image/vnd.microsoft.icon"
        ],
        description="Allowed image content types"
    )
    
    # ===========================================
    # CORS Settings
    # ===========================================
    
    # Allowed origins for CORS (comma-separated or "*")
    cors_origins: str = Field(
        default="https://openmates.org,https://app.openmates.org,http://localhost:5173,http://localhost:3000",
        description="Allowed CORS origins"
    )
    
    # ===========================================
    # Referer Validation Settings
    # ===========================================
    
    # Enable Referer header validation (blocks requests from other domains)
    # Note: Referer can be spoofed by non-browser clients, use with rate limiting
    validate_referer: bool = Field(default=True, description="Enable Referer header validation")
    
    # Allow empty Referer header (for direct navigation, privacy settings)
    # Set to False for webapp-only access (browsers always send Referer from webapp)
    allow_empty_referer: bool = Field(default=False, description="Allow requests with empty Referer header")
    
    # Allowed Referer patterns (comma-separated, supports wildcards with *)
    allowed_referers: str = Field(
        default="https://openmates.org/*,https://*.openmates.org/*",
        description="Allowed Referer patterns (comma-separated)"
    )
    
    # ===========================================
    # Logging Settings
    # ===========================================
    
    # Log level (DEBUG, INFO, WARNING, ERROR)
    log_level: str = Field(default="INFO", description="Log level")
    
    # ===========================================
    # Optional: API Key Authentication
    # ===========================================
    
    # If set, requires this API key in X-API-Key header
    # Leave empty for public access (with rate limiting)
    api_key: Optional[str] = Field(default=None, description="Optional API key for authentication")
    
    class Config:
        """Pydantic config for environment variable prefix."""
        env_prefix = "PREVIEW_"
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins string into list."""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
    
    @property
    def allowed_referers_list(self) -> list[str]:
        """Parse allowed referers string into list of patterns."""
        return [ref.strip() for ref in self.allowed_referers.split(",") if ref.strip()]
    
    @property
    def cache_max_size_bytes(self) -> int:
        """Get cache max size in bytes."""
        return self.cache_max_size_mb * 1024 * 1024
    
    @property
    def metadata_cache_max_size_bytes(self) -> int:
        """Get metadata cache max size in bytes."""
        return self.metadata_cache_max_size_mb * 1024 * 1024


# Global settings instance
settings = Settings()

