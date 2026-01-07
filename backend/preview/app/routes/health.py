"""
Health Check Endpoints

Provides health and status endpoints for monitoring and load balancers.
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from ..services.cache_service import cache_service
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """
    Basic health check endpoint.
    
    Returns simple OK status for load balancer health checks.
    """
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.get("/health/detailed")
async def detailed_health_check() -> dict:
    """
    Detailed health check with cache statistics.
    
    Returns comprehensive status including:
    - Cache sizes and counts
    - Configuration summary
    - Uptime information
    """
    cache_stats = cache_service.get_stats()
    
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.environment,
        "cache": cache_stats,
        "config": {
            "max_image_size_mb": settings.max_image_size_bytes // (1024 * 1024),
            "max_image_width": settings.max_image_width,
            "max_image_height": settings.max_image_height,
            "jpeg_quality": settings.jpeg_quality,
            "image_cache_ttl_hours": settings.image_cache_ttl_seconds // 3600,
            "metadata_cache_ttl_hours": settings.metadata_cache_ttl_seconds // 3600,
        }
    }


@router.get("/health/cache")
async def cache_status() -> dict:
    """
    Get cache statistics only.
    
    Returns detailed cache information for monitoring dashboards.
    """
    stats = cache_service.get_stats()
    
    # Calculate usage percentages
    for cache_name, cache_stats in stats.items():
        if cache_stats["size_limit_bytes"] > 0:
            cache_stats["usage_percent"] = round(
                cache_stats["size_bytes"] / cache_stats["size_limit_bytes"] * 100,
                2
            )
        else:
            cache_stats["usage_percent"] = 0
        
        # Convert bytes to MB for readability
        cache_stats["size_mb"] = round(cache_stats["size_bytes"] / (1024 * 1024), 2)
        cache_stats["size_limit_mb"] = round(cache_stats["size_limit_bytes"] / (1024 * 1024), 2)
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "caches": stats
    }

