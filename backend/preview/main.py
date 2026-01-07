"""
OpenMates Preview Server

FastAPI application for image/favicon proxying and URL metadata extraction.

This server provides:
- /api/v1/favicon - Favicon proxy with caching
- /api/v1/image - Image proxy with resizing and caching
- /api/v1/metadata - Open Graph metadata extraction
- /health - Health check endpoints

Key features:
- SSRF protection (blocks private/internal IPs)
- Disk-based caching with LRU eviction
- Image resizing and quality optimization
- CORS support for frontend integration

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes import favicon_router, image_router, metadata_router, health_router
from app.services import fetch_service, cache_service

# ===========================================
# Logging Configuration
# ===========================================

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ===========================================
# Application Lifespan (startup/shutdown)
# ===========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown tasks:
    - Startup: Log configuration, verify cache directories
    - Shutdown: Close HTTP clients, close cache connections
    """
    # Startup
    logger.info("=" * 60)
    logger.info("OpenMates Preview Server Starting")
    logger.info("=" * 60)
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Cache directory: {settings.cache_dir}")
    logger.info(f"Image cache size: {settings.cache_max_size_mb}MB")
    logger.info(f"Metadata cache size: {settings.metadata_cache_max_size_mb}MB")
    logger.info(f"Max image dimensions: {settings.max_image_width}x{settings.max_image_height}")
    logger.info(f"SSRF protection: {'enabled' if settings.block_private_ips else 'disabled'}")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Preview Server...")
    await fetch_service.close()
    cache_service.close()
    logger.info("Preview Server stopped")


# ===========================================
# FastAPI Application
# ===========================================

app = FastAPI(
    title="OpenMates Preview Server",
    description=(
        "Image and favicon proxy with caching, plus URL metadata extraction. "
        "Provides privacy-preserving content proxying for the OpenMates platform."
    ),
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,  # Disable docs in production
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan
)


# ===========================================
# CORS Middleware with Dynamic Origin Support
# ===========================================

def is_allowed_origin(origin: str) -> bool:
    """
    Check if an origin is allowed for CORS.
    
    Supports:
    - Exact matches from cors_origins_list
    - Wildcard subdomain pattern: *.openmates.org
    - Localhost with any port
    
    Args:
        origin: The Origin header value
        
    Returns:
        True if the origin is allowed
    """
    import re
    
    if not origin:
        return False
    
    # Check exact matches first
    if origin in settings.cors_origins_list:
        return True
    
    # Allow all origins if "*" is in the list
    if "*" in settings.cors_origins_list:
        return True
    
    # Allow any *.openmates.org subdomain
    if re.match(r'^https://([a-zA-Z0-9-]+\.)*openmates\.org$', origin):
        return True
    
    # Allow localhost with any port (for development)
    if re.match(r'^http://localhost:\d+$', origin):
        return True
    
    return False


# Use custom CORS middleware that supports wildcard subdomains
# The standard CORSMiddleware doesn't support patterns like *.openmates.org
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """
    Custom CORS middleware with dynamic origin checking.
    
    Supports wildcard subdomains (*.openmates.org) which the standard
    CORSMiddleware doesn't handle.
    """
    origin = request.headers.get("origin", "")
    
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        if is_allowed_origin(origin):
            return JSONResponse(
                content={},
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Expose-Headers": "X-Cache, X-Processed, X-Original-Size, X-Processed-Size",
                    "Access-Control-Max-Age": "86400",  # Cache preflight for 24 hours
                }
            )
        else:
            # Origin not allowed - return 403 for preflight
            logger.warning(f"[CORS] Blocked preflight from unauthorized origin: {origin}")
            return JSONResponse(
                content={"detail": "Origin not allowed"},
                status_code=403
            )
    
    # Handle actual requests
    response = await call_next(request)
    
    # Add CORS headers if origin is allowed
    if is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "X-Cache, X-Processed, X-Original-Size, X-Processed-Size"
    
    return response


# ===========================================
# Global Exception Handler
# ===========================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for unhandled errors.
    
    Logs the error and returns a generic 500 response.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# ===========================================
# Referer Validation Middleware
# ===========================================

def _match_referer_pattern(referer: str, pattern: str) -> bool:
    """
    Match a referer against a pattern with wildcard support.
    
    Supports:
    - Exact match: "https://openmates.org/page"
    - Wildcard subdomains: "https://*.openmates.org/*"
    - Wildcard paths: "https://openmates.org/*"
    - Localhost with any port: "http://localhost:*/*"
    
    Args:
        referer: The actual Referer header value
        pattern: The pattern to match against
        
    Returns:
        True if referer matches pattern
    """
    import fnmatch
    
    # Normalize both to lowercase for comparison
    referer_lower = referer.lower()
    pattern_lower = pattern.lower()
    
    # Use fnmatch for glob-style matching
    return fnmatch.fnmatch(referer_lower, pattern_lower)


if settings.validate_referer:
    @app.middleware("http")
    async def referer_validation_middleware(request: Request, call_next):
        """
        Validate Referer header to ensure requests come from allowed domains.
        
        This provides defense against hotlinking and unauthorized use.
        Note: Referer can be spoofed by non-browser clients, so this is
        a deterrent, not absolute protection. Combine with rate limiting.
        
        Allowed cases:
        - Empty/missing Referer (privacy settings, direct navigation)
        - Referer matching one of the allowed patterns
        - Health check endpoints (always allowed)
        """
        # Always allow health checks
        if request.url.path.startswith("/health"):
            return await call_next(request)
        
        # Get Referer header
        referer = request.headers.get("referer", "")
        
        # Handle empty referer based on configuration
        # When allow_empty_referer is False (webapp-only mode), block empty referers
        if not referer:
            if settings.allow_empty_referer:
                return await call_next(request)
            else:
                logger.warning(
                    f"[RefererValidation] Blocked request with empty referer for path: {request.url.path}"
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Access denied: Referer header required"}
                )
        
        # Check against allowed patterns
        for pattern in settings.allowed_referers_list:
            if _match_referer_pattern(referer, pattern):
                return await call_next(request)
        
        # Log blocked request (for monitoring hotlinking attempts)
        logger.warning(
            f"[RefererValidation] Blocked request from unauthorized referer: {referer[:100]} "
            f"for path: {request.url.path}"
        )
        
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied: unauthorized referer"}
        )
    
    logger.info(f"Referer validation enabled. Allowed: {settings.allowed_referers_list}")


# ===========================================
# API Key Authentication (Optional)
# ===========================================

if settings.api_key:
    from fastapi.security import APIKeyHeader
    
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)  # noqa: F841
    
    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        """
        Validate API key if configured.
        
        Skips validation for health check endpoints.
        """
        # Skip auth for health checks
        if request.url.path.startswith("/health"):
            return await call_next(request)
        
        api_key = request.headers.get("X-API-Key")
        if api_key != settings.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )
        
        return await call_next(request)
    
    logger.info("API key authentication enabled")


# ===========================================
# Register Routers
# ===========================================

app.include_router(health_router)
app.include_router(favicon_router)
app.include_router(image_router)
app.include_router(metadata_router)


# ===========================================
# Root Endpoint
# ===========================================

@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint - redirects to health check."""
    return {
        "service": "OpenMates Preview Server",
        "version": "1.0.0",
        "docs": "/docs" if settings.debug else "disabled",
        "health": "/health"
    }


# ===========================================
# Main Entry Point
# ===========================================

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )

