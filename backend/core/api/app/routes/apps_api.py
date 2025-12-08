# backend/core/api/app/routes/apps_api.py
#
# External API endpoints for accessing apps and their skills with API key authentication
# This router provides a RESTful API for external clients to interact with app skills

import logging
import httpx
import hashlib
import os
import json
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Depends, Body, FastAPI
from pydantic import BaseModel, Field

from backend.core.api.app.utils.api_key_auth import ApiKeyAuth
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.shared.python_utils.billing_utils import calculate_total_credits, PricingConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/apps", tags=["Apps API"])

# Default internal port for app services
DEFAULT_APP_INTERNAL_PORT = 8000

# Internal API base URL for billing
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


# Request/Response models
class SkillRequest(BaseModel):
    """
    Request model for skill execution.
    
    The input_data field should contain the structure defined in the skill's tool_schema
    (e.g., for news search: {"requests": [{"id": 1, "query": "..."}]}).
    The parameters field is for additional skill-specific parameters (usually empty).
    """
    input_data: Dict[str, Any] = Field(
        ...,
        description="Input data matching the skill's tool_schema structure. For news search, this should be an object with a 'requests' array."
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default={},
        description="Additional skill-specific parameters (usually empty)."
    )


class SkillResponse(BaseModel):
    """Response model for skill execution"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    credits_charged: Optional[int] = None


class SkillMetadata(BaseModel):
    """Metadata for a skill including pricing information"""
    id: str
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    parameters_schema: Optional[Dict[str, Any]] = {}
    pricing: Optional[Dict[str, Any]] = None  # Pricing configuration if available


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


async def get_directus_service(request: Request) -> DirectusService:
    """Get directus service from app state"""
    return request.app.state.directus_service


async def get_encryption_service(request: Request) -> EncryptionService:
    """Get encryption service from app state"""
    return request.app.state.encryption_service


def get_discovered_apps(request: Request) -> Dict[str, AppYAML]:
    """
    Get discovered apps metadata from app state.
    Returns empty dict if not available.
    """
    if not hasattr(request.app.state, 'discovered_apps_metadata'):
        logger.warning("discovered_apps_metadata not found in app.state")
        return {}
    return request.app.state.discovered_apps_metadata


def get_translation_service(request: Request):
    """Get translation service from app state"""
    if hasattr(request.app.state, 'translation_service'):
        return request.app.state.translation_service
    return None


def resolve_translation(translation_service, translation_key: str, namespace: str, fallback: str = "") -> str:
    """
    Resolve a translation key using the translation service.
    Returns the translated text or fallback if translation service is not available.
    """
    if not translation_service or not translation_key:
        return fallback
    
    try:
        translations = translation_service.get_translations(lang="en")  # Default to English for API
        # Translation keys are typically in format "namespace.key"
        # We need to navigate the nested structure
        parts = translation_key.split(".")
        value = translations
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
                if value is None:
                    return fallback
            else:
                return fallback
        return value if isinstance(value, str) else fallback
    except Exception as e:
        logger.warning(f"Failed to resolve translation for key '{translation_key}': {e}")
        return fallback


async def call_app_skill(
    app_id: str,
    skill_id: str,
    input_data: Dict[str, Any],
    parameters: Dict[str, Any],
    user_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Call an app skill via internal service communication.
    
    Args:
        app_id: The ID of the app
        skill_id: The ID of the skill to execute
        input_data: Input data for the skill
        parameters: Parameters for the skill
        user_info: User information from API key authentication
        
    Returns:
        Dict containing the skill execution result
    """
    try:
        # Construct hostname by prepending "app-" to the app_id (standard pattern)
        hostname = f"app-{app_id}"
        
        # Prepare request to internal app service
        skill_url = f"http://{hostname}:{DEFAULT_APP_INTERNAL_PORT}/skills/{skill_id}"

        headers = {
            'Content-Type': 'application/json',
            'X-External-User-ID': user_info['user_id'],
            'X-API-Key-Name': user_info.get('api_key_encrypted_name', ''),  # Encrypted name (for logging, client decrypts)
        }

        # Send input_data directly as the request body to the skill
        # The skill expects the tool_schema structure directly (e.g., {"requests": [...]})
        # Context is added as metadata fields prefixed with _ so they don't interfere with the skill's schema
        request_payload = input_data.copy() if isinstance(input_data, dict) else input_data
        if not isinstance(request_payload, dict):
            request_payload = {}
        
        # Add context as metadata fields (prefixed with _)
        request_payload['_user_id'] = user_info['user_id']
        request_payload['_api_key_name'] = user_info.get('api_key_encrypted_name', '')
        request_payload['_external_request'] = True

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


async def calculate_skill_credits(
    app_metadata: AppYAML,
    skill_id: str,
    input_data: Dict[str, Any],
    result_data: Optional[Dict[str, Any]] = None
) -> int:
    """
    Calculate credits to charge for a skill execution based on pricing configuration.
    
    Uses the same billing logic as main_processor.py:
    1. Checks for explicit pricing in skill's app.yml
    2. If not found, fetches provider pricing from provider YAML files
    3. Calculates credits based on units_processed (number of requests)
    
    Args:
        app_metadata: The app metadata containing skill definitions
        skill_id: The ID of the skill that was executed
        input_data: Input data that was sent to the skill (should contain 'requests' array)
        result_data: Optional result data from skill execution (for token-based pricing)
        
    Returns:
        Number of credits to charge
    """
    # Find the skill definition
    skill_def: Optional[AppSkillDefinition] = None
    for skill in app_metadata.skills or []:
        if skill.id == skill_id:
            skill_def = skill
            break
    
    if not skill_def:
        logger.warning(f"Skill '{skill_id}' not found in app '{app_metadata.id}' metadata. Cannot calculate credits.")
        return 0
    
    # Get pricing config - check skill-level first, then provider-level
    pricing_config = None
    if skill_def.pricing:
        # Skill has explicit pricing in app.yml - use it
        pricing_config = skill_def.pricing.model_dump(exclude_none=True)
        logger.debug(f"Using skill-level pricing from app.yml for '{app_metadata.id}.{skill_id}'")
    elif skill_def.providers and len(skill_def.providers) > 0:
        # Skill doesn't have explicit pricing, but has providers - try to get provider-level pricing
        # Use the first provider (most skills will have one primary provider)
        provider_name = skill_def.providers[0]
        # Normalize provider name to lowercase (provider IDs in YAML are lowercase, e.g., "brave")
        provider_id = provider_name.lower()
        
        # Map provider names to provider IDs (handles cases like "Google" -> "google_maps" for maps app)
        if provider_name == "Google" and app_metadata.id == "maps":
            provider_id = "google_maps"
        elif provider_name == "Brave" or provider_name == "Brave Search":
            provider_id = "brave"
        
        logger.debug(f"Skill '{app_metadata.id}.{skill_id}' has no explicit pricing, attempting to fetch provider-level pricing from '{provider_id}' (mapped from '{provider_name}')")
        
        try:
            # Fetch provider pricing via internal API
            headers = {"Content-Type": "application/json"}
            if INTERNAL_API_SHARED_TOKEN:
                headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
            
            endpoint = f"internal/config/provider_pricing/{provider_id}"
            url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                provider_pricing = response.json()
            
            if provider_pricing and isinstance(provider_pricing, dict):
                # Convert provider pricing format to billing format
                # Provider pricing may have formats like:
                # - per_request_credits: 10 (Brave)
                # - per_unit: { credits: X } (already in correct format)
                
                if "per_request_credits" in provider_pricing:
                    # Convert per_request_credits to per_unit.credits format
                    credits_per_request = provider_pricing["per_request_credits"]
                    pricing_config = {
                        "per_unit": {
                            "credits": credits_per_request
                        }
                    }
                    logger.debug(f"Converted provider pricing: per_request_credits={credits_per_request} -> per_unit.credits={credits_per_request}")
                elif "per_unit" in provider_pricing:
                    # Provider already uses per_unit format
                    pricing_config = {"per_unit": provider_pricing["per_unit"]}
                    logger.debug(f"Using provider pricing per_unit format: {provider_pricing['per_unit']}")
                else:
                    logger.warning(f"Provider '{provider_id}' has pricing but unsupported format: {list(provider_pricing.keys())}. Using minimum charge.")
            else:
                logger.warning(f"Could not retrieve valid provider pricing for '{provider_id}'. Response: {provider_pricing}")
        except Exception as e:
            logger.warning(f"Error fetching provider pricing for '{provider_id}': {e}. Using minimum charge.")
    
    # Calculate units_processed from input_data (number of requests)
    # All skills use 'requests' array format - charge per request
    units_processed = None
    if "requests" in input_data and isinstance(input_data["requests"], list):
        # Count number of requests in the requests array
        units_processed = len(input_data["requests"])
        logger.debug(f"Skill '{app_metadata.id}.{skill_id}' executed with {units_processed} request(s) in requests array")
    else:
        # Fallback: if no requests array found, charge for single execution
        units_processed = 1
        logger.debug(f"Skill '{app_metadata.id}.{skill_id}' has no 'requests' array, charging for single execution")
    
    # Calculate credits
    if pricing_config:
        # PricingConfig is a type alias for Dict[str, Any], so we can pass the dict directly
        credits_charged = calculate_total_credits(
            pricing_config=pricing_config,  # Pass dict directly (PricingConfig = Dict[str, Any])
            units_processed=units_processed
        )
    else:
        # Default to minimum charge if no pricing config
        MINIMUM_CREDITS_CHARGED = 1
        credits_charged = MINIMUM_CREDITS_CHARGED
        logger.info(f"No pricing config for skill '{app_metadata.id}.{skill_id}', using minimum charge: {credits_charged}")
    
    logger.info(f"Calculated {credits_charged} credits for skill '{app_metadata.id}.{skill_id}' (units_processed={units_processed})")
    return credits_charged


async def charge_credits_via_internal_api(
    user_id: str,
    user_id_hash: str,
    credits: int,
    app_id: str,
    skill_id: str,
    usage_details: Optional[Dict[str, Any]] = None,
    api_key_hash: Optional[str] = None,  # SHA-256 hash of API key for tracking
    device_hash: Optional[str] = None,  # SHA-256 hash of device for tracking
) -> None:
    """
    Charge credits via the internal billing API.
    This creates a usage entry and deducts credits from the user's account.
    
    Args:
        user_id: Actual user ID
        user_id_hash: Hashed user ID for privacy
        credits: Number of credits to charge
        app_id: ID of the app that executed the skill
        skill_id: ID of the skill that was executed
        usage_details: Optional additional usage metadata
        api_key_hash: Optional SHA-256 hash of the API key that created this usage entry
        device_hash: Optional SHA-256 hash of the device that created this usage entry
    """
    if credits <= 0:
        logger.debug(f"Skipping credit charge for user {user_id} - credits is {credits}")
        return
    
    charge_payload = {
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "credits": credits,
        "skill_id": skill_id,
        "app_id": app_id,
        "usage_details": usage_details or {},
        "api_key_hash": api_key_hash,  # API key hash for tracking
        "device_hash": device_hash,  # Device hash for tracking
    }
    
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            logger.info(f"Charging {credits} credits for skill '{app_id}.{skill_id}' via internal API")
            response = await client.post(url, json=charge_payload, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully charged {credits} credits for skill '{app_id}.{skill_id}'")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error charging credits for skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution response
    except Exception as e:
        logger.error(f"Error charging credits for skill '{app_id}.{skill_id}': {e}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution response


# API Endpoints

@router.get(
    "",
    response_model=AppsListResponse,
    dependencies=[ApiKeyAuth],  # Mark endpoint as requiring API key
    summary="List all available apps",
    description="List all available apps and their skills. Requires API key authentication."
)
@limiter.limit("60/minute")
async def list_apps(
    request: Request,
    user_info: Dict[str, Any] = ApiKeyAuth,
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    List all available apps and their skills.
    
    Requires API key authentication.
    Returns apps that are discovered and available on the server.
    """
    try:
        discovered_apps = get_discovered_apps(request)
        translation_service = get_translation_service(request)
        
        if not discovered_apps:
            logger.info("No apps discovered, returning empty list")
            return AppsListResponse(apps=[])
        
        # Get server environment for stage filtering
        server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
        allowed_stages = ["production"] if server_environment == "production" else ["development", "production"]
        
        apps = []
        for app_id, app_metadata in discovered_apps.items():
            # Resolve app name and description
            app_name = resolve_translation(
                translation_service,
                app_metadata.name_translation_key,
                namespace="apps",
                fallback=app_id
            )
            app_description = resolve_translation(
                translation_service,
                app_metadata.description_translation_key,
                namespace="apps",
                fallback=""
            )
            
            # Convert skills - filter by stage
            skills = []
            for skill in app_metadata.skills or []:
                skill_stage = getattr(skill, 'stage', 'development').lower()
                if skill_stage not in allowed_stages:
                    continue
                
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
                
                # Get input/output schemas from tool_schema if available
                input_schema = {}
                output_schema = {}
                parameters_schema = {}
                
                if skill.tool_schema:
                    # Extract input schema from tool_schema
                    input_schema = skill.tool_schema.get('parameters', {}).get('properties', {})
                    # Output schema is typically not in tool_schema, use empty dict
                    output_schema = {}
                    # Parameters schema could be the same as input schema for now
                    parameters_schema = {}
                
                # Convert pricing to dict if available
                pricing_dict = None
                if skill.pricing:
                    pricing_dict = {}
                    if skill.pricing.tokens:
                        pricing_dict['tokens'] = skill.pricing.tokens
                    if skill.pricing.per_unit:
                        pricing_dict['per_unit'] = skill.pricing.per_unit
                    if skill.pricing.per_minute:
                        pricing_dict['per_minute'] = skill.pricing.per_minute
                    if skill.pricing.fixed:
                        pricing_dict['fixed'] = skill.pricing.fixed
                
                skills.append(SkillMetadata(
                    id=skill.id,
                    name=skill_name,
                    description=skill_description,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    parameters_schema=parameters_schema,
                    pricing=pricing_dict
                ))
            
            if skills:  # Only include apps that have at least one skill
                apps.append(AppMetadata(
                    id=app_id,
                    name=app_name,
                    description=app_description,
                    skills=skills
                ))
        
        return AppsListResponse(apps=apps)
        
    except Exception as e:
        logger.error(f"Error listing apps for user {user_info['user_id']}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list apps")


def register_app_and_skill_routes(app: FastAPI, discovered_apps: Dict[str, AppYAML]):
    """
    Dynamically register explicit routes for each app and each skill.
    
    This creates explicit endpoints like:
    - GET /v1/apps/web
    - GET /v1/apps/web/skills/search
    - POST /v1/apps/web/skills/search
    
    Args:
        app: The FastAPI application instance
        discovered_apps: Dictionary of discovered app metadata
    """
    translation_service = None
    if hasattr(app.state, 'translation_service'):
        translation_service = app.state.translation_service
    
    # Get server environment for stage filtering
    server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    allowed_stages = ["production"] if server_environment == "production" else ["development", "production"]
    
    for app_id, app_metadata in discovered_apps.items():
        # Resolve app name and description
        app_name = resolve_translation(
            translation_service,
            app_metadata.name_translation_key,
            namespace="apps",
            fallback=app_id
        )
        app_description = resolve_translation(
            translation_service,
            app_metadata.description_translation_key,
            namespace="apps",
            fallback=""
        )
        
        # Create route handler for GET /v1/apps/{app_id}
        # Use closure to capture app_id and app_metadata
        def create_get_app_handler(captured_app_id: str, captured_app_metadata: AppYAML):
            async def get_app_handler(
                request: Request,
                user_info: Dict[str, Any] = ApiKeyAuth  # This will be injected by Security()
            ) -> AppMetadata:
                """Get metadata for a specific app. Requires API key authentication."""
                try:
                    # Get server environment for stage filtering
                    server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
                    allowed = ["production"] if server_env == "production" else ["development", "production"]
                    
                    trans_service = get_translation_service(request)
                    
                    # Resolve app name and description
                    resolved_name = resolve_translation(
                        trans_service,
                        captured_app_metadata.name_translation_key,
                        namespace="apps",
                        fallback=captured_app_id
                    )
                    resolved_description = resolve_translation(
                        trans_service,
                        captured_app_metadata.description_translation_key,
                        namespace="apps",
                        fallback=""
                    )
                    
                    # Convert skills - filter by stage
                    skills = []
                    for skill in captured_app_metadata.skills or []:
                        skill_stage = getattr(skill, 'stage', 'development').lower()
                        if skill_stage not in allowed:
                            continue
                        
                        skill_name = resolve_translation(
                            trans_service,
                            skill.name_translation_key,
                            namespace="app_skills",
                            fallback=skill.id
                        )
                        skill_description = resolve_translation(
                            trans_service,
                            skill.description_translation_key,
                            namespace="app_skills",
                            fallback=""
                        )
                        
                        # Get input/output schemas from tool_schema if available
                        input_schema = {}
                        output_schema = {}
                        parameters_schema = {}
                        
                        if skill.tool_schema:
                            input_schema = skill.tool_schema.get('parameters', {}).get('properties', {})
                            output_schema = {}
                            parameters_schema = {}
                        
                        # Convert pricing to dict if available
                        pricing_dict = None
                        if skill.pricing:
                            pricing_dict = {}
                            if skill.pricing.tokens:
                                pricing_dict['tokens'] = skill.pricing.tokens
                            if skill.pricing.per_unit:
                                pricing_dict['per_unit'] = skill.pricing.per_unit
                            if skill.pricing.per_minute:
                                pricing_dict['per_minute'] = skill.pricing.per_minute
                            if skill.pricing.fixed:
                                pricing_dict['fixed'] = skill.pricing.fixed
                        
                        skills.append(SkillMetadata(
                            id=skill.id,
                            name=skill_name,
                            description=skill_description,
                            input_schema=input_schema,
                            output_schema=output_schema,
                            parameters_schema=parameters_schema,
                            pricing=pricing_dict
                        ))
                    
                    return AppMetadata(
                        id=captured_app_id,
                        name=resolved_name,
                        description=resolved_description,
                        skills=skills
                    )
                    
                except Exception as e:
                    logger.error(f"Error getting app {captured_app_id} for user {user_info['user_id']}: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail="Failed to get app metadata")
            
            return get_app_handler
        
        # Register GET /v1/apps/{app_id} endpoint
        handler = create_get_app_handler(app_id, app_metadata)
        # Apply rate limiting and add security requirement
        limited_handler = limiter.limit("60/minute")(handler)
        app.add_api_route(
            path=f"/v1/apps/{app_id}",
            endpoint=limited_handler,
            methods=["GET"],
            response_model=AppMetadata,
            tags=["Apps API"],
            name=f"get_app_{app_id}",
            summary=f"Get metadata for {app_name}",
            description=f"Get metadata for the {app_name} app including all available skills. Requires API key authentication.",
            dependencies=[ApiKeyAuth]  # Mark endpoint as requiring API key
        )
        
        # Register routes for each skill in the app
        for skill in app_metadata.skills or []:
            skill_stage = getattr(skill, 'stage', 'development').lower()
            if skill_stage not in allowed_stages:
                continue
            
            # Resolve skill name for documentation
            skill_name = resolve_translation(
                translation_service,
                skill.name_translation_key,
                namespace="app_skills",
                fallback=skill.id
            )
            
            # Create GET handler for skill metadata
            def create_get_skill_handler(captured_app_id: str, captured_skill: AppSkillDefinition, captured_app_metadata: AppYAML):
                async def get_skill_handler(
                    request: Request,
                    user_info: Dict[str, Any] = ApiKeyAuth  # This will be injected by Security()
                ) -> SkillMetadata:
                    """Get metadata for a specific skill including pricing information. Requires API key authentication."""
                    try:
                        trans_service = get_translation_service(request)
                        
                        # Resolve skill name and description
                        resolved_name = resolve_translation(
                            trans_service,
                            captured_skill.name_translation_key,
                            namespace="app_skills",
                            fallback=captured_skill.id
                        )
                        resolved_description = resolve_translation(
                            trans_service,
                            captured_skill.description_translation_key,
                            namespace="app_skills",
                            fallback=""
                        )
                        
                        # Get input/output schemas from tool_schema if available
                        input_schema = {}
                        output_schema = {}
                        parameters_schema = {}
                        
                        if captured_skill.tool_schema:
                            input_schema = captured_skill.tool_schema.get('parameters', {}).get('properties', {})
                            output_schema = {}
                            parameters_schema = {}
                        
                        # Convert pricing to dict if available
                        pricing_dict = None
                        if captured_skill.pricing:
                            pricing_dict = {}
                            if captured_skill.pricing.tokens:
                                pricing_dict['tokens'] = captured_skill.pricing.tokens
                            if captured_skill.pricing.per_unit:
                                pricing_dict['per_unit'] = captured_skill.pricing.per_unit
                            if captured_skill.pricing.per_minute:
                                pricing_dict['per_minute'] = captured_skill.pricing.per_minute
                            if captured_skill.pricing.fixed:
                                pricing_dict['fixed'] = captured_skill.pricing.fixed
                        
                        return SkillMetadata(
                            id=captured_skill.id,
                            name=resolved_name,
                            description=resolved_description,
                            input_schema=input_schema,
                            output_schema=output_schema,
                            parameters_schema=parameters_schema,
                            pricing=pricing_dict
                        )
                        
                    except Exception as e:
                        logger.error(f"Error getting skill {captured_app_id}/{captured_skill.id} for user {user_info['user_id']}: {e}", exc_info=True)
                        raise HTTPException(status_code=500, detail="Failed to get skill metadata")
                
                return get_skill_handler
            
            # Create POST handler for skill execution
            def create_post_skill_handler(captured_app_id: str, captured_skill: AppSkillDefinition, captured_app_metadata: AppYAML):
                # Try to import the skill's request/response models directly from the skill module
                # This ensures FastAPI generates correct OpenAPI schema automatically
                SkillRequestModel = None
                SkillResponseModel = None
                
                if captured_skill.tool_schema and captured_skill.class_path:
                    try:
                        import importlib
                        # Import the skill module to get its models
                        module_path, class_name = captured_skill.class_path.rsplit('.', 1)
                        skill_module = importlib.import_module(module_path)
                        
                        # Look for Request and Response models in the module
                        # Common patterns: SearchRequest/SearchResponse, ReadRequest/ReadResponse, etc.
                        for model_name in ['SearchRequest', 'ReadRequest', 'TranscriptRequest', 'Request']:
                            if hasattr(skill_module, model_name):
                                SkillRequestModel = getattr(skill_module, model_name)
                                logger.debug(f"Found request model '{model_name}' for skill {captured_app_id}/{captured_skill.id}")
                                break
                        
                        for model_name in ['SearchResponse', 'ReadResponse', 'TranscriptResponse', 'Response']:
                            if hasattr(skill_module, model_name):
                                SkillResponseModel = getattr(skill_module, model_name)
                                logger.debug(f"Found response model '{model_name}' for skill {captured_app_id}/{captured_skill.id}")
                                break
                                
                    except Exception as e:
                        logger.warning(f"Could not import models from skill module {captured_skill.class_path}: {e}")
                
                # If we found the models, enhance them with proper structure from tool_schema
                if SkillRequestModel and SkillResponseModel and captured_skill.tool_schema:
                    # Create an enhanced request model that properly defines the requests array items
                    # The original SearchRequest uses List[Dict[str, Any]] which doesn't show structure
                    # We'll create a new model based on the tool_schema
                    from pydantic import create_model
                    import copy
                    
                    tool_schema = copy.deepcopy(captured_skill.tool_schema)
                    
                    # Inject 'id' field into requests items if missing (same logic as tool_generator)
                    if "properties" in tool_schema and "requests" in tool_schema["properties"]:
                        requests_prop = tool_schema["properties"]["requests"]
                        if requests_prop.get("type") == "array" and "items" in requests_prop:
                            items = requests_prop["items"]
                            if items.get("type") == "object":
                                items_properties = items.get("properties", {})
                                if "id" not in items_properties:
                                    # Inject 'id' field (optional, can be string or integer)
                                    items_properties["id"] = {
                                        "type": ["string", "integer"],
                                        "description": "Unique identifier for this request (number or UUID string). Optional for single requests (defaults to 1), required for multiple requests."
                                    }
                                    if "properties" not in items:
                                        items["properties"] = items_properties
                                    else:
                                        items["properties"] = items_properties
                    
                    # Extract the requests array items schema
                    requests_items_schema = None
                    if "properties" in tool_schema and "requests" in tool_schema["properties"]:
                        requests_prop = tool_schema["properties"]["requests"]
                        if requests_prop.get("type") == "array" and "items" in requests_prop:
                            requests_items_schema = requests_prop["items"]
                    
                    # Create a proper model for request items if we have the schema
                    RequestItemModel = None
                    if requests_items_schema and requests_items_schema.get("type") == "object":
                        # Build field definitions from the items schema
                        field_definitions = {}
                        if "properties" in requests_items_schema:
                            for prop_name, prop_schema in requests_items_schema["properties"].items():
                                # Determine Python type from JSON schema type
                                prop_type = Any
                                schema_type = prop_schema.get("type")
                                
                                # Handle union types (e.g., ["string", "integer"] for 'id' field)
                                if isinstance(schema_type, list):
                                    # For union types, use the first type or Union if multiple
                                    if len(schema_type) > 1:
                                        from typing import Union
                                        # Try to determine the union type
                                        types = []
                                        if "string" in schema_type:
                                            types.append(str)
                                        if "integer" in schema_type:
                                            types.append(int)
                                        if types:
                                            prop_type = Union[tuple(types)] if len(types) > 1 else types[0]
                                        else:
                                            prop_type = Any
                                    else:
                                        schema_type = schema_type[0]
                                
                                if schema_type == "string":
                                    prop_type = str
                                elif schema_type == "integer":
                                    prop_type = int
                                elif schema_type == "boolean":
                                    prop_type = bool
                                elif schema_type == "array":
                                    prop_type = List[Any]
                                
                                # Check if field is required
                                is_required = prop_name in requests_items_schema.get("required", [])
                                
                                # Get default value if available
                                default_value = prop_schema.get("default")
                                if default_value is not None:
                                    field_definitions[prop_name] = (prop_type, Field(default=default_value, description=prop_schema.get("description", "")))
                                elif not is_required:
                                    field_definitions[prop_name] = (Optional[prop_type], Field(default=None, description=prop_schema.get("description", "")))
                                else:
                                    field_definitions[prop_name] = (prop_type, Field(..., description=prop_schema.get("description", "")))
                        
                        # Create the request item model
                        if field_definitions:
                            RequestItemModel = create_model(
                                f"RequestItem_{captured_app_id}_{captured_skill.id}",
                                **field_definitions
                            )
                    
                    # Create enhanced request model with proper typing
                    if RequestItemModel:
                        # Create a new request model with properly typed requests array
                        EnhancedRequestModel = create_model(
                            f"EnhancedRequest_{captured_app_id}_{captured_skill.id}",
                            requests=(List[RequestItemModel], Field(..., description=tool_schema.get("properties", {}).get("requests", {}).get("description", "Array of search request objects")))
                        )
                        
                        # Override the model's JSON schema to use the tool_schema directly
                        # This ensures FastAPI shows the correct structure in OpenAPI docs
                        def custom_json_schema():
                            return tool_schema
                        
                        EnhancedRequestModel.model_json_schema = staticmethod(custom_json_schema)
                        
                        SkillRequestModel = EnhancedRequestModel
                        logger.debug(f"Created enhanced request model with typed request items for {captured_app_id}/{captured_skill.id}")
                    else:
                        # Fallback: override the original model's JSON schema
                        def custom_json_schema():
                            return tool_schema
                        SkillRequestModel.model_json_schema = staticmethod(custom_json_schema)
                        logger.debug(f"Overrode JSON schema for {captured_app_id}/{captured_skill.id} request model")
                    
                    # Create a wrapper response model that includes the skill response in 'data'
                    class WrappedSkillResponse(BaseModel):
                        """Response wrapper for skill execution"""
                        success: bool
                        data: Optional[SkillResponseModel] = Field(None, description="The skill execution result (only present when success=True)")
                        error: Optional[str] = Field(None, description="Error message if execution failed")
                        credits_charged: Optional[int] = Field(None, description="Credits charged for this execution")
                    
                    async def post_skill_handler(
                        request_body: SkillRequestModel,
                        request: Request = None,
                        user_info: Dict[str, Any] = ApiKeyAuth,  # This will be injected by Security()
                        cache_service: CacheService = Depends(get_cache_service),
                        directus_service: DirectusService = Depends(get_directus_service)
                    ) -> WrappedSkillResponse:
                        """
                        Execute a skill from a specific app.
                        
                        Requires API key authentication.
                        The skill will be executed, billed, and a usage entry will be created automatically.
                        Rate limited to 30 requests per minute per API key.
                        
                        The request body should match the skill's tool_schema structure directly.
                        For news search, this means providing a 'requests' array with search queries.
                        """
                        try:
                            logger.info(f"External API: User {user_info['user_id']} executing {captured_app_id}/{captured_skill.id}")
                            
                            # Convert Pydantic model to dict for skill execution
                            request_dict = request_body.model_dump() if hasattr(request_body, 'model_dump') else dict(request_body)
                            
                            # Execute the skill - pass request_dict directly (it matches tool_schema)
                            result = await call_app_skill(
                                app_id=captured_app_id,
                                skill_id=captured_skill.id,
                                input_data=request_dict,  # Pass tool_schema structure directly
                                parameters={},  # No separate parameters for skills with tool_schema
                                user_info=user_info
                            )
                            
                            # Calculate credits to charge based on pricing
                            # This uses the same logic as main_processor.py: checks skill pricing, then provider pricing
                            credits_charged = await calculate_skill_credits(
                                app_metadata=captured_app_metadata,
                                skill_id=captured_skill.id,
                                input_data=request_dict,  # Use request_dict for credit calculation (contains 'requests' array)
                                result_data=result
                            )
                            
                            # Calculate units_processed for usage tracking
                            units_processed = None
                            if isinstance(request_dict, dict) and "requests" in request_dict and isinstance(request_dict["requests"], list):
                                units_processed = len(request_dict["requests"])
                            else:
                                units_processed = 1
                            
                            # Charge credits via internal API (this also creates usage entry)
                            if credits_charged > 0:
                                # Create user_id_hash for privacy
                                user_id_hash = hashlib.sha256(user_info['user_id'].encode()).hexdigest()
                                
                                # Create usage details (matching format from main_processor.py)
                                usage_details = {
                                    "api_key_name": user_info.get('api_key_name'),
                                    "external_request": True,
                                    "units_processed": units_processed  # Number of requests processed
                                }
                                
                                # Charge credits (this happens asynchronously and won't block the response)
                                await charge_credits_via_internal_api(
                                    user_id=user_info['user_id'],
                                    user_id_hash=user_id_hash,
                                    credits=credits_charged,
                                    app_id=captured_app_id,
                                    skill_id=captured_skill.id,
                                    usage_details=usage_details,
                                    api_key_hash=user_info.get('api_key_hash'),  # API key hash for tracking
                                    device_hash=user_info.get('device_hash'),  # Device hash for tracking
                                )
                            
                            # Parse result into the skill's response model for proper typing
                            try:
                                skill_response = SkillResponseModel(**result) if isinstance(result, dict) else result
                            except Exception as e:
                                logger.warning(f"Could not parse result into {SkillResponseModel.__name__}: {e}, using raw result")
                                skill_response = result
                            
                            return WrappedSkillResponse(
                                success=True,
                                data=skill_response,
                                credits_charged=credits_charged
                            )
                            
                        except HTTPException:
                            raise
                        except Exception as e:
                            logger.error(f"Error executing skill {captured_app_id}/{captured_skill.id} for user {user_info['user_id']}: {e}", exc_info=True)
                            return WrappedSkillResponse(
                                success=False,
                                error=f"Skill execution failed: {str(e)}"
                            )
                    
                    return post_skill_handler
                
                # Fallback: if we couldn't import models, use tool_schema approach
                elif captured_skill.tool_schema:
                    import copy
                    tool_schema = copy.deepcopy(captured_skill.tool_schema)
                    
                    async def post_skill_handler(
                        request_body: Dict[str, Any] = Body(
                            ...,
                            description=f"Request body matching the skill's tool_schema. For {skill_name}, this should be an object with a 'requests' array.",
                            example=tool_schema.get('example', {})
                        ),
                        request: Request = None,
                        user_info: Dict[str, Any] = ApiKeyAuth,
                        cache_service: CacheService = Depends(get_cache_service),
                        directus_service: DirectusService = Depends(get_directus_service)
                    ) -> SkillResponse:
                        """Execute a skill from a specific app. Fallback handler when models can't be imported."""
                        try:
                            logger.info(f"External API: User {user_info['user_id']} executing {captured_app_id}/{captured_skill.id}")
                            
                            result = await call_app_skill(
                                app_id=captured_app_id,
                                skill_id=captured_skill.id,
                                input_data=request_body,
                                parameters={},
                                user_info=user_info
                            )
                            
                            # Calculate credits to charge based on pricing
                            # This uses the same logic as main_processor.py: checks skill pricing, then provider pricing
                            credits_charged = await calculate_skill_credits(
                                app_metadata=captured_app_metadata,
                                skill_id=captured_skill.id,
                                input_data=request_body,  # Contains 'requests' array
                                result_data=result
                            )
                            
                            # Calculate units_processed for usage tracking
                            units_processed = None
                            if isinstance(request_body, dict) and "requests" in request_body and isinstance(request_body["requests"], list):
                                units_processed = len(request_body["requests"])
                            else:
                                units_processed = 1
                            
                            if credits_charged > 0:
                                user_id_hash = hashlib.sha256(user_info['user_id'].encode()).hexdigest()
                                usage_details = {
                                    "api_key_name": user_info.get('api_key_name'),
                                    "external_request": True,
                                    "units_processed": units_processed  # Number of requests processed
                                }
                                await charge_credits_via_internal_api(
                                    user_id=user_info['user_id'],
                                    user_id_hash=user_id_hash,
                                    credits=credits_charged,
                                    app_id=captured_app_id,
                                    skill_id=captured_skill.id,
                                    usage_details=usage_details,
                                    api_key_hash=user_info.get('api_key_hash'),  # API key hash for tracking
                                    device_hash=user_info.get('device_hash'),  # Device hash for tracking
                                )
                            
                            return SkillResponse(
                                success=True,
                                data=result,
                                credits_charged=credits_charged
                            )
                        except HTTPException:
                            raise
                        except Exception as e:
                            logger.error(f"Error executing skill {captured_app_id}/{captured_skill.id}: {e}", exc_info=True)
                            return SkillResponse(success=False, error=f"Skill execution failed: {str(e)}")
                    
                    return post_skill_handler
                else:
                    # Fallback for skills without tool_schema - use generic SkillRequest
                    async def post_skill_handler(
                        request_data: SkillRequest,
                        request: Request = None,
                        user_info: Dict[str, Any] = ApiKeyAuth,  # This will be injected by Security()
                        cache_service: CacheService = Depends(get_cache_service),
                        directus_service: DirectusService = Depends(get_directus_service)
                    ) -> SkillResponse:
                        """
                        Execute a skill from a specific app.
                        
                        Requires API key authentication.
                        The skill will be executed, billed, and a usage entry will be created automatically.
                        Rate limited to 30 requests per minute per API key.
                        """
                        try:
                            logger.info(f"External API: User {user_info['user_id']} executing {captured_app_id}/{captured_skill.id}")
                            
                            # Execute the skill
                            result = await call_app_skill(
                                app_id=captured_app_id,
                                skill_id=captured_skill.id,
                                input_data=request_data.input_data,
                                parameters=request_data.parameters or {},
                                user_info=user_info
                            )
                            
                            # Calculate credits to charge based on pricing
                            # This uses the same logic as main_processor.py: checks skill pricing, then provider pricing
                            credits_charged = await calculate_skill_credits(
                                app_metadata=captured_app_metadata,
                                skill_id=captured_skill.id,
                                input_data=request_data.input_data,  # Contains 'requests' array
                                result_data=result
                            )
                            
                            # Calculate units_processed for usage tracking
                            units_processed = None
                            if isinstance(request_data.input_data, dict) and "requests" in request_data.input_data and isinstance(request_data.input_data["requests"], list):
                                units_processed = len(request_data.input_data["requests"])
                            else:
                                units_processed = 1
                            
                            # Charge credits via internal API (this also creates usage entry)
                            if credits_charged > 0:
                                # Create user_id_hash for privacy
                                user_id_hash = hashlib.sha256(user_info['user_id'].encode()).hexdigest()
                                
                                # Create usage details (matching format from main_processor.py)
                                usage_details = {
                                    "api_key_name": user_info.get('api_key_name'),
                                    "external_request": True,
                                    "units_processed": units_processed  # Number of requests processed
                                }
                                
                                # Charge credits (this happens asynchronously and won't block the response)
                                await charge_credits_via_internal_api(
                                    user_id=user_info['user_id'],
                                    user_id_hash=user_id_hash,
                                    credits=credits_charged,
                                    app_id=captured_app_id,
                                    skill_id=captured_skill.id,
                                    usage_details=usage_details,
                                    api_key_hash=user_info.get('api_key_hash'),  # API key hash for tracking
                                    device_hash=user_info.get('device_hash'),  # Device hash for tracking
                                )
                            
                            return SkillResponse(
                                success=True,
                                data=result,
                                credits_charged=credits_charged
                            )
                            
                        except HTTPException:
                            raise
                        except Exception as e:
                            logger.error(f"Error executing skill {captured_app_id}/{captured_skill.id} for user {user_info['user_id']}: {e}", exc_info=True)
                            return SkillResponse(
                                success=False,
                                error=f"Skill execution failed: {str(e)}"
                            )
                
                return post_skill_handler
            
            # Register GET /v1/apps/{app_id}/skills/{skill_id} endpoint
            get_handler = create_get_skill_handler(app_id, skill, app_metadata)
            app.add_api_route(
                path=f"/v1/apps/{app_id}/skills/{skill.id}",
                endpoint=limiter.limit("60/minute")(get_handler),
                methods=["GET"],
                response_model=SkillMetadata,
                tags=["Apps API"],
                name=f"get_skill_{app_id}_{skill.id}",
                summary=f"Get metadata for {skill_name}",
                description=f"Get metadata for the {skill_name} skill including pricing information. Requires API key authentication.",
                dependencies=[ApiKeyAuth]  # Mark endpoint as requiring API key
            )
            
            # Register POST /v1/apps/{app_id}/skills/{skill_id} endpoint
            post_handler = create_post_skill_handler(app_id, skill, app_metadata)
            
            # Determine response model - check if handler uses a custom response model
            # by inspecting its return type annotation
            import inspect
            response_model = SkillResponse  # Default
            sig = inspect.signature(post_handler)
            if sig.return_annotation and sig.return_annotation != inspect.Signature.empty:
                # Check if it's a custom model (not the default SkillResponse)
                if hasattr(sig.return_annotation, '__name__') and sig.return_annotation.__name__ != 'SkillResponse':
                    response_model = sig.return_annotation
            
            app.add_api_route(
                path=f"/v1/apps/{app_id}/skills/{skill.id}",
                endpoint=limiter.limit("30/minute")(post_handler),
                methods=["POST"],
                response_model=response_model,
                tags=["Apps API"],
                name=f"execute_skill_{app_id}_{skill.id}",
                summary=f"Execute {skill_name}",
                description=f"Execute the {skill_name} skill. The skill will be executed, billed, and a usage entry will be created automatically. Requires API key authentication.",
                dependencies=[ApiKeyAuth]  # Mark endpoint as requiring API key
            )
            
            logger.info(f"Registered routes for skill: GET/POST /v1/apps/{app_id}/skills/{skill.id}")
        
        logger.info(f"Registered routes for app: GET /v1/apps/{app_id}")
