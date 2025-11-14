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


def resolve_translation(
    translation_service: Any,
    translation_key: str,
    namespace: str,
    fallback: str = ""
) -> str:
    """
    Resolve a translation key to its translated string value.
    
    Args:
        translation_service: TranslationService instance
        translation_key: Translation key (e.g., "web.search.text")
        namespace: Namespace prefix (e.g., "app_skills", "apps", "app_focus_modes", "app_settings_memories")
        fallback: Fallback value if translation not found
    
    Returns:
        Resolved translation string or fallback
    """
    if not translation_service:
        return fallback or translation_key
    
    # Normalize translation key: ensure it has namespace prefix if needed
    full_key = translation_key
    if not full_key.startswith(f"{namespace}."):
        full_key = f"{namespace}.{full_key}"
    
    try:
        # Get the full translation structure
        translations = translation_service.get_translations(lang="en")
        
        # Navigate through nested keys: e.g., app_skills.web.search.text
        keys = full_key.split('.')
        value = translations
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                logger.debug(f"Translation key '{full_key}' not found, using fallback")
                return fallback or translation_key
        
        # Extract the text value
        if isinstance(value, dict) and "text" in value:
            return value["text"]
        elif isinstance(value, str):
            return value
        else:
            logger.debug(f"Translation value for '{full_key}' is not a string or dict with 'text' key")
            return fallback or translation_key
    except Exception as e:
        logger.warning(f"Error resolving translation key '{full_key}': {e}")
        return fallback or translation_key


class AppMetadataResponse(BaseModel):
    """Response model for app metadata endpoint."""
    apps: Dict[str, AppMetadataItem]


class AppMetadataItem(BaseModel):
    """Individual app metadata item.
    
    All translations are resolved to actual strings (defaults to English).
    Translation keys are not included in the response.
    """
    id: str
    name: str  # Resolved translation string for app name
    description: str  # Resolved translation string for app description
    skills: List[SkillMetadataItem]
    focus_modes: List[FocusModeMetadataItem] = []
    settings_and_memories: List[Dict[str, str]] = []  # Only id, name, description (all resolved strings)


class SkillMetadataItem(BaseModel):
    """Skill metadata for API response.
    
    Includes resolved translation strings, not translation keys.
    """
    id: str
    name: str  # Resolved translation string for skill name
    description: str  # Resolved translation string for skill description


class FocusModeMetadataItem(BaseModel):
    """Focus mode metadata for API response.
    
    Includes resolved translation strings, not translation keys.
    Note: Only production-stage focus modes are included in the response.
    Development focus modes are only available on development servers, not production servers.
    """
    id: str
    name: str  # Resolved translation string for focus mode name
    description: str  # Resolved translation string for focus mode description


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
    
    # Get translation service from app state (initialized during startup)
    translation_service = None
    if hasattr(request.app.state, 'translation_service'):
        translation_service = request.app.state.translation_service
    else:
        logger.warning("TranslationService not found in app.state - translations will not be resolved")
    
    # Convert AppYAML to API response format
    # Transform the discovered AppYAML objects to the API response format with resolved translations
    apps_metadata: Dict[str, AppMetadataItem] = {}
    
    for app_id, app_metadata in discovered_apps.items():
        # Log what we're processing for debugging
        logger.info(f"Processing app '{app_id}': {len(app_metadata.skills)} skills, {len(app_metadata.focuses)} focus modes, {len(app_metadata.memory_fields) if app_metadata.memory_fields else 0} memory fields")
        
        # Resolve app name and description translations
        if not app_metadata.description_translation_key:
            logger.error(f"App '{app_id}' is missing required description_translation_key, skipping")
            continue
        
        resolved_name = resolve_translation(
            translation_service,
            app_metadata.name_translation_key,
            namespace="apps",
            fallback=app_id
        )
        
        resolved_description = resolve_translation(
            translation_service,
            app_metadata.description_translation_key,
            namespace="apps",
            fallback=""
        )
        
        # Convert skills - resolve all translations
        skills = []
        for skill in app_metadata.skills:
            skill_name = resolve_translation(
                translation_service,
                skill.name_translation_key,
                namespace="app_skills",
                fallback=skill.id
            )
            skill_description = resolve_translation(
                translation_service,
                skill.description_translation_key,
                namespace="app_skills",
                fallback=""
            )
            skills.append(SkillMetadataItem(
                id=skill.id,
                name=skill_name,
                description=skill_description
            ))
        
        # Convert focus modes - resolve all translations
        focus_modes = []
        for focus in app_metadata.focuses:
            focus_name = resolve_translation(
                translation_service,
                focus.name_translation_key,
                namespace="app_focus_modes",
                fallback=focus.id
            )
            focus_description = resolve_translation(
                translation_service,
                focus.description_translation_key,
                namespace="app_focus_modes",
                fallback=""
            )
            focus_modes.append(FocusModeMetadataItem(
                id=focus.id,
                name=focus_name,
                description=focus_description
            ))
        
        # Convert settings_and_memories - resolve all translations
        settings_and_memories = []
        if app_metadata.memory_fields:
            for field in app_metadata.memory_fields:
                field_name = resolve_translation(
                    translation_service,
                    field.name_translation_key,
                    namespace="app_settings_memories",
                    fallback=field.id
                )
                field_description = resolve_translation(
                    translation_service,
                    field.description_translation_key,
                    namespace="app_settings_memories",
                    fallback=""
                )
                settings_and_memories.append({
                    "id": field.id,
                    "name": field_name,
                    "description": field_description
                })
        
        apps_metadata[app_id] = AppMetadataItem(
            id=app_id,
            name=resolved_name,
            description=resolved_description,
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
    
    # description_translation_key is required (no backwards compatibility)
    if not app_metadata.description_translation_key:
        raise HTTPException(status_code=500, detail=f"App '{app_id}' is missing required description_translation_key")
    
    # Get translation service from app state (initialized during startup)
    translation_service = None
    if hasattr(request.app.state, 'translation_service'):
        translation_service = request.app.state.translation_service
    
    # Resolve app name and description translations
    resolved_name = resolve_translation(
        translation_service,
        app_metadata.name_translation_key,
        namespace="apps",
        fallback=app_id
    )
    
    resolved_description = resolve_translation(
        translation_service,
        app_metadata.description_translation_key,
        namespace="apps",
        fallback=""
    )
    
    # Convert skills - resolve all translations
    skills = []
    for skill in app_metadata.skills:
        skill_name = resolve_translation(
            translation_service,
            skill.name_translation_key,
            namespace="app_skills",
            fallback=skill.id
        )
        skill_description = resolve_translation(
            translation_service,
            skill.description_translation_key,
            namespace="app_skills",
            fallback=""
        )
        skills.append(SkillMetadataItem(
            id=skill.id,
            name=skill_name,
            description=skill_description
        ))
    
    # Convert focus modes - resolve all translations
    focus_modes = []
    for focus in app_metadata.focuses:
        focus_name = resolve_translation(
            translation_service,
            focus.name_translation_key,
            namespace="app_focus_modes",
            fallback=focus.id
        )
        focus_description = resolve_translation(
            translation_service,
            focus.description_translation_key,
            namespace="app_focus_modes",
            fallback=""
        )
        focus_modes.append(FocusModeMetadataItem(
            id=focus.id,
            name=focus_name,
            description=focus_description
        ))
    
    # Convert settings_and_memories - resolve all translations
    settings_and_memories = []
    if app_metadata.memory_fields:
        for field in app_metadata.memory_fields:
            field_name = resolve_translation(
                translation_service,
                field.name_translation_key,
                namespace="app_settings_memories",
                fallback=field.id
            )
            field_description = resolve_translation(
                translation_service,
                field.description_translation_key,
                namespace="app_settings_memories",
                fallback=""
            )
            settings_and_memories.append({
                "id": field.id,
                "name": field_name,
                "description": field_description
            })
    
    return AppMetadataItem(
        id=app_id,
        name=resolved_name,
        description=resolved_description,
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

