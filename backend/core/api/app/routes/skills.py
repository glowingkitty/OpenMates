# backend/core/api/app/routes/skills.py
#
# External API endpoints for accessing app skills with API key authentication
#
# SECURITY: This module includes ASCII smuggling protection via the text_sanitization module.
# ASCII smuggling attacks use invisible Unicode characters to embed hidden instructions
# that bypass prompt injection detection but are processed by LLMs.
# See: docs/architecture/prompt_injection_protection.md

import logging
import httpx
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Depends, Body
from pydantic import BaseModel

from backend.core.api.app.utils.api_key_auth import ApiKeyAuth
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.cache import CacheService

# Import comprehensive ASCII smuggling sanitization
# This module protects against invisible Unicode characters used to embed hidden instructions
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/skills", tags=["Skills API"])


# Request/Response models
class SkillRequest(BaseModel):
    """Request model for skill execution"""
    input_data: Dict[str, Any]
    parameters: Optional[Dict[str, Any]] = {}


class SkillResponse(BaseModel):
    """Response model for skill execution"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SkillMetadata(BaseModel):
    """Metadata for a skill"""
    id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    parameters_schema: Optional[Dict[str, Any]] = {}


class AppMetadata(BaseModel):
    """Metadata for an app"""
    id: str
    name: str
    description: str
    skills: List[SkillMetadata]


class AppsListResponse(BaseModel):
    """Response model for apps list"""
    apps: List[AppMetadata]


# Helper functions
async def get_cache_service(request: Request) -> CacheService:
    """Get cache service from app state"""
    return request.app.state.cache_service


def _sanitize_dict_recursively(data: Any, log_prefix: str = "") -> Any:
    """
    Recursively sanitize all string values in a dictionary or list for ASCII smuggling.
    
    This function walks through nested data structures (dicts, lists) and sanitizes
    all string values to remove invisible Unicode characters that could be used for
    ASCII smuggling attacks.
    
    SECURITY: This is critical for API endpoints where input_data can contain
    arbitrary nested structures with text that will be processed by LLMs.
    
    Args:
        data: The data structure to sanitize (dict, list, or primitive)
        log_prefix: Prefix for log messages
    
    Returns:
        A copy of the data with all strings sanitized
    """
    if isinstance(data, dict):
        return {key: _sanitize_dict_recursively(value, log_prefix) for key, value in data.items()}
    elif isinstance(data, list):
        return [_sanitize_dict_recursively(item, log_prefix) for item in data]
    elif isinstance(data, str):
        return sanitize_text_simple(data, log_prefix=log_prefix)
    else:
        # Primitives (int, float, bool, None) pass through unchanged
        return data


async def get_app_metadata(cache_service: CacheService) -> Dict[str, Any]:
    """Get app metadata from cache or internal API"""
    cache_key = "external_api:app_metadata"
    cached_data = await cache_service.get(cache_key)

    if cached_data:
        return cached_data

    try:
        # Call internal API to get app metadata
        async with httpx.AsyncClient() as client:
            response = await client.get("http://api:8000/v1/apps/metadata")
            if response.status_code == 200:
                data = response.json()
                # Cache for 5 minutes
                await cache_service.set(cache_key, data, ttl=300)
                return data
            else:
                logger.error(f"Failed to get app metadata: {response.status_code}")
                return {}
    except Exception as e:
        logger.error(f"Error getting app metadata: {e}")
        return {}


async def call_app_skill(
    app_id: str,
    skill_id: str,
    input_data: Dict[str, Any],
    parameters: Dict[str, Any],
    user_info: Dict[str, Any]
) -> Dict[str, Any]:
    """Call an app skill via internal service communication"""
    try:
        # Map app_id to internal service hostname
        app_hostnames = {
            'ai': 'app-ai',
            'web': 'app-web',
            'videos': 'app-videos',
            'news': 'app-news',
            'maps': 'app-maps',
            'travel': 'app-travel',
        }

        hostname = app_hostnames.get(app_id)
        if not hostname:
            raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")

        # Prepare request to internal app service
        skill_url = f"http://{hostname}:8000/skills/{skill_id}"

        headers = {
            'Content-Type': 'application/json',
            'X-External-User-ID': user_info['user_id'],
            'X-External-User-Email': user_info.get('email', ''),
            'X-API-Key-Name': user_info.get('api_key_name', ''),
        }

        request_payload = {
            'input_data': input_data,
            'parameters': parameters,
            'context': {
                'user_id': user_info['user_id'],
                'api_key_name': user_info.get('api_key_name'),
                'external_request': True
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                skill_url,
                json=request_payload,
                headers=headers
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found in app '{app_id}'")
            else:
                logger.error(f"App service error: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail="Internal service error")

    except httpx.TimeoutException:
        logger.error(f"Timeout calling skill {app_id}/{skill_id}")
        raise HTTPException(status_code=504, detail="Skill execution timeout")
    except httpx.RequestError as e:
        logger.error(f"Request error calling skill {app_id}/{skill_id}: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


# API Endpoints

@router.get("/apps", response_model=AppsListResponse)
@limiter.limit("60/minute")
async def list_apps(
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth,
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    List all available apps and their skills for external access.

    Requires API key authentication.
    """
    try:
        metadata = await get_app_metadata(cache_service)

        apps = []
        for app_id, app_data in metadata.get('apps', {}).items():
            skills = []
            for skill in app_data.get('skills', []):
                skills.append(SkillMetadata(
                    id=skill.get('id', ''),
                    name=skill.get('name', ''),
                    description=skill.get('description', ''),
                    input_schema=skill.get('input_schema', {}),
                    output_schema=skill.get('output_schema', {}),
                    parameters_schema=skill.get('parameters_schema', {})
                ))

            apps.append(AppMetadata(
                id=app_id,
                name=app_data.get('name', ''),
                description=app_data.get('description', ''),
                skills=skills
            ))

        return AppsListResponse(apps=apps)

    except Exception as e:
        logger.error(f"Error listing apps for user {user_info['user_id']}: {e}")
        raise HTTPException(status_code=500, detail="Failed to list apps")


@router.get("/apps/{app_id}", response_model=AppMetadata)
@limiter.limit("60/minute")
async def get_app(
    app_id: str,
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth,
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Get metadata for a specific app.

    Requires API key authentication.
    """
    try:
        metadata = await get_app_metadata(cache_service)

        app_data = metadata.get('apps', {}).get(app_id)
        if not app_data:
            raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")

        skills = []
        for skill in app_data.get('skills', []):
            skills.append(SkillMetadata(
                id=skill.get('id', ''),
                name=skill.get('name', ''),
                description=skill.get('description', ''),
                input_schema=skill.get('input_schema', {}),
                output_schema=skill.get('output_schema', {}),
                parameters_schema=skill.get('parameters_schema', {})
            ))

        return AppMetadata(
            id=app_id,
            name=app_data.get('name', ''),
            description=app_data.get('description', ''),
            skills=skills
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting app {app_id} for user {user_info['user_id']}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get app metadata")


@router.post("/apps/{app_id}/skills/{skill_id}", response_model=SkillResponse)
@limiter.limit("30/minute")
async def execute_skill(
    app_id: str,
    skill_id: str,
    request_data: SkillRequest,
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth
):
    """
    Execute a skill from a specific app.

    Requires API key authentication.
    Rate limited to 30 requests per minute per API key.
    
    SECURITY: Input data is sanitized for ASCII smuggling attacks before processing.
    ASCII smuggling uses invisible Unicode characters to embed hidden instructions
    that bypass prompt injection detection but are processed by LLMs.
    See: docs/architecture/prompt_injection_protection.md
    """
    try:
        logger.info(f"External API: User {user_info['user_id']} executing {app_id}/{skill_id}")
        
        # SECURITY: Sanitize all text in input_data to prevent ASCII smuggling attacks
        # This removes invisible Unicode characters that could embed hidden instructions
        log_prefix = f"[API {app_id}/{skill_id}][User {user_info['user_id'][:8]}...] "
        sanitized_input_data = _sanitize_dict_recursively(request_data.input_data, log_prefix=log_prefix)
        sanitized_parameters = _sanitize_dict_recursively(request_data.parameters or {}, log_prefix=log_prefix)

        result = await call_app_skill(
            app_id=app_id,
            skill_id=skill_id,
            input_data=sanitized_input_data,
            parameters=sanitized_parameters,
            user_info=user_info
        )

        return SkillResponse(
            success=True,
            data=result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing skill {app_id}/{skill_id} for user {user_info['user_id']}: {e}")
        return SkillResponse(
            success=False,
            error=f"Skill execution failed: {str(e)}"
        )


@router.get("/apps/{app_id}/skills/{skill_id}", response_model=SkillMetadata)
@limiter.limit("60/minute")
async def get_skill_metadata(
    app_id: str,
    skill_id: str,
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth,
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Get metadata for a specific skill.

    Requires API key authentication.
    """
    try:
        metadata = await get_app_metadata(cache_service)

        app_data = metadata.get('apps', {}).get(app_id)
        if not app_data:
            raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")

        skill_data = None
        for skill in app_data.get('skills', []):
            if skill.get('id') == skill_id:
                skill_data = skill
                break

        if not skill_data:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found in app '{app_id}'")

        return SkillMetadata(
            id=skill_data.get('id', ''),
            name=skill_data.get('name', ''),
            description=skill_data.get('description', ''),
            input_schema=skill_data.get('input_schema', {}),
            output_schema=skill_data.get('output_schema', {}),
            parameters_schema=skill_data.get('parameters_schema', {})
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting skill {app_id}/{skill_id} for user {user_info['user_id']}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get skill metadata")