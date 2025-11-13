# backend/core/api/app/routes/apps.py
# 
# REST API endpoints for app discovery and metadata.
# Provides access to discovered apps, their skills, focus modes, and settings/memories.

from __future__ import annotations  # Enable postponed evaluation of annotations for forward references

import logging
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from backend.shared.python_schemas.app_metadata_schemas import AppYAML
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.internal_api import get_directus_service, get_cache_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/apps", tags=["Apps"])


class AppMetadataResponse(BaseModel):
    """Response model for app metadata endpoint."""
    apps: Dict[str, AppMetadataItem]


class AppMetadataItem(BaseModel):
    """Individual app metadata item."""
    id: str
    name: str
    description: str
    skills: List[SkillMetadataItem]
    focus_modes: List[FocusModeMetadataItem] = []
    settings_and_memories: List[Dict[str, str]] = []  # Only id, name, description


class SkillMetadataItem(BaseModel):
    """Skill metadata for API response.
    
    Only includes basic information (id, name, description).
    """
    id: str
    name: str
    description: str


class FocusModeMetadataItem(BaseModel):
    """Focus mode metadata for API response.
    
    Note: Only production-stage focus modes are included in the response.
    Development focus modes are only available on development servers, not production servers.
    """
    id: str
    name: str
    description: str


class MostUsedAppItem(BaseModel):
    """Individual most used app item."""
    app_id: str
    usage_count: int
    rank: int


class MostUsedAppsResponse(BaseModel):
    """Response model for most used apps endpoint."""
    apps: List[MostUsedAppItem]
    last_updated: int  # Unix timestamp
    period_days: int = 30  # Indicate the time window


@router.get("/metadata", response_model=AppMetadataResponse)
async def get_apps_metadata(request: Request):
    """
    Get metadata for all discovered apps.
    
    Returns the metadata that each app's Docker container registered during startup.
    Each app exposes a /metadata endpoint that returns its AppYAML configuration.
    The core API discovers these during startup and stores them in app.state.discovered_apps_metadata.
    
    This endpoint simply returns what was discovered - no transformation or filtering.
    If an app is missing, it means either:
    - The app container is not running
    - The app's /metadata endpoint is not responding
    - The app is not in the enabled_apps list in backend_config.yml
    
    **Implementation**: 
    - App discovery: `backend/core/api/main.py:discover_apps()` 
    - App metadata endpoint: `backend/apps/base_app.py:_register_default_routes()` -> `/metadata`
    - App metadata schemas: `backend/shared/python_schemas/app_metadata_schemas.py`
    
    **Reference**: 
    - App Store UI: `frontend/packages/ui/src/components/settings/SettingsApps.svelte`
    """
    # Get discovered apps from app state (populated during startup)
    if not hasattr(request.app.state, 'discovered_apps_metadata'):
        logger.warning("discovered_apps_metadata not found in app.state - apps may not have been discovered during startup")
        return AppMetadataResponse(apps={})
    
    discovered_apps: Dict[str, AppYAML] = request.app.state.discovered_apps_metadata
    
    if not discovered_apps:
        logger.info("No apps discovered during startup, returning empty metadata")
        return AppMetadataResponse(apps={})
    
    logger.info(f"Returning metadata for {len(discovered_apps)} discovered apps: {list(discovered_apps.keys())}")
    
    # Convert AppYAML to API response format
    # Simply transform the discovered AppYAML objects to the API response format
    apps_metadata: Dict[str, AppMetadataItem] = {}
    
    for app_id, app_metadata in discovered_apps.items():
        # Log what we're processing for debugging
        logger.info(f"Processing app '{app_id}': {len(app_metadata.skills)} skills, {len(app_metadata.focuses)} focus modes, {len(app_metadata.memory_fields) if app_metadata.memory_fields else 0} memory fields")
        # Convert skills - include all skills (both production and development)
        # Only include id, name, description (no pricing or other details)
        skills = [
            SkillMetadataItem(
                id=skill.id,
                name=skill.name,
                description=skill.description
            )
            for skill in app_metadata.skills
        ]
        
        # Convert focus modes - include all focus modes
        focus_modes = [
            FocusModeMetadataItem(
                id=focus.id,
                name=focus.name,
                description=focus.description
            )
            for focus in app_metadata.focuses
        ]
        
        # Convert settings_and_memories (mapped from memory_fields during AppYAML parsing)
        # Only include id, name, description (no schema or type details)
        settings_and_memories = []
        if app_metadata.memory_fields:
            settings_and_memories = [
                {
                    "id": field.id,
                    "name": field.name,
                    "description": field.description
                }
                for field in app_metadata.memory_fields
            ]
        
        apps_metadata[app_id] = AppMetadataItem(
            id=app_id,
            name=app_metadata.name,
            description=app_metadata.description,
            skills=skills,
            focus_modes=focus_modes,
            settings_and_memories=settings_and_memories
        )
    
    logger.info(f"Returning metadata for {len(apps_metadata)} apps")
    return AppMetadataResponse(apps=apps_metadata)


@router.get("/{app_id}/metadata")
async def get_app_metadata(app_id: str, request: Request):
    """
    Get metadata for a specific app.
    
    **Reference**: See `get_apps_metadata()` for implementation details.
    """
    if not hasattr(request.app.state, 'discovered_apps_metadata'):
        raise HTTPException(status_code=404, detail="App not found")
    
    discovered_apps: Dict[str, AppYAML] = request.app.state.discovered_apps_metadata
    app_metadata = discovered_apps.get(app_id)
    
    if not app_metadata:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")
    
    # Convert skills - include all skills (both production and development)
    # Only include id, name, description (no pricing or other details)
    skills = [
        SkillMetadataItem(
            id=skill.id,
            name=skill.name,
            description=skill.description
        )
        for skill in app_metadata.skills
    ]
    
    # Convert focus modes - include all focus modes
    focus_modes = [
        FocusModeMetadataItem(
            id=focus.id,
            name=focus.name,
            description=focus.description
        )
        for focus in app_metadata.focuses
    ]
    
    # Convert settings_and_memories (mapped from memory_fields during AppYAML parsing)
    # Only include id, name, description (no schema or type details)
    settings_and_memories = []
    if app_metadata.memory_fields:
        settings_and_memories = [
            {
                "id": field.id,
                "name": field.name,
                "description": field.description
            }
            for field in app_metadata.memory_fields
        ]
    
    return AppMetadataItem(
        id=app_id,
        name=app_metadata.name,
        description=app_metadata.description,
        skills=skills,
        focus_modes=focus_modes,
        settings_and_memories=settings_and_memories
    )


@router.get("/most-used", response_model=MostUsedAppsResponse)
@limiter.limit("30/minute")  # Rate limit for public endpoint
async def get_most_used_apps(
    request: Request,
    limit: int = 10,  # Default to top 10, max 20
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service)
):
    """
    Get most used apps in the last 30 days (public endpoint, no auth required).
    
    Returns top N apps sorted by usage count from the last 30 days.
    Used by App Store to display "Most used" section.
    
    If no analytics data is available, returns a default list of popular apps:
    ai, web, videos, travel, maps
    
    Data is cached for 1 hour to reduce Directus query load.
    Results are aggregated from anonymous analytics data (no user-specific information).
    
    Args:
        request: FastAPI request object (for rate limiting)
        limit: Maximum number of apps to return (default 10, max 20)
        cache_service: CacheService instance for caching
        directus_service: DirectusService instance for database queries
    
    Returns:
        MostUsedAppsResponse with list of apps, usage counts, and metadata
    """
    # Validate limit
    if limit > 20:
        limit = 20
    if limit < 1:
        limit = 10
    
    # Default list of most used apps (fallback when no analytics data available)
    DEFAULT_MOST_USED_APPS = ["ai", "web", "videos", "travel", "maps"]
    
    try:
        # Get from cache or Directus
        apps = await cache_service.get_most_used_apps_cached(
            directus_service=directus_service,
            limit=limit
        )
        
        # If no analytics data available, use default list
        if not apps or len(apps) == 0:
            logger.info("No analytics data available, returning default most used apps")
            apps = [
                {"app_id": app_id, "usage_count": 1000 - idx * 100}  # Decreasing counts for ranking
                for idx, app_id in enumerate(DEFAULT_MOST_USED_APPS[:limit])
            ]
        
        # Format response with ranks
        ranked_apps = [
            MostUsedAppItem(
                app_id=app["app_id"],
                usage_count=app["usage_count"],
                rank=idx + 1
            )
            for idx, app in enumerate(apps)
        ]
        
        return MostUsedAppsResponse(
            apps=ranked_apps,
            last_updated=int(time.time()),
            period_days=30
        )
    except Exception as e:
        logger.error(f"Error getting most used apps: {e}", exc_info=True)
        # Return default list on error rather than empty response
        default_apps = [
            MostUsedAppItem(
                app_id=app_id,
                usage_count=1000 - idx * 100,
                rank=idx + 1
            )
            for idx, app_id in enumerate(DEFAULT_MOST_USED_APPS[:limit])
        ]
        return MostUsedAppsResponse(
            apps=default_apps,
            last_updated=int(time.time()),
            period_days=30
        )

