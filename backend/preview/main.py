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
from fastapi.middleware.cors import CORSMiddleware
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
# CORS Middleware
# ===========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "X-Processed", "X-Original-Size", "X-Processed-Size"]
)


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
        
        # Allow empty referer (privacy settings, direct navigation in some browsers)
        if not referer:
            return await call_next(request)
        
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

