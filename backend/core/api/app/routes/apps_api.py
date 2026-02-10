# backend/core/api/app/routes/apps_api.py
#
# External API endpoints for accessing apps and their skills with API key authentication
# This router provides a RESTful API for external clients to interact with app skills
#
# SECURITY: This module includes ASCII smuggling protection via the text_sanitization module.
# ASCII smuggling attacks use invisible Unicode characters to embed hidden instructions
# that bypass prompt injection detection but are processed by LLMs.
# See: docs/architecture/prompt_injection_protection.md

import logging
import httpx
import hashlib
import os

from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Request, Depends, Body, FastAPI
from pydantic import BaseModel, Field

from backend.core.api.app.utils.api_key_auth import ApiKeyAuth
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.shared.python_utils.billing_utils import calculate_total_credits

# Import comprehensive ASCII smuggling sanitization
# This module protects against invisible Unicode characters used to embed hidden instructions
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple

# Import AI models for documentation purposes
# Use absolute imports to avoid circular dependencies
try:
    from backend.apps.ai.skills.ask_skill import OpenAICompletionResponse, OpenAIErrorResponse
except ImportError:
    # Fallback if not available yet
    OpenAICompletionResponse = Any
    OpenAIErrorResponse = Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/apps", tags=["Apps"])

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


class ProviderPricing(BaseModel):
    """Pricing information for a provider"""
    provider: str  # Provider ID (e.g., "brave", "firecrawl")
    name: str  # Provider display name from provider YAML (e.g., "Brave Search")
    description: str  # Provider description from provider YAML
    pricing: Dict[str, Any]  # Pricing configuration for this provider


class SkillMetadata(BaseModel):
    """Metadata for a skill including pricing information"""
    id: str
    name: str
    description: str
    providers: List[ProviderPricing] = []  # List of all providers with their pricing


class FocusModeMetadata(BaseModel):
    """Metadata for a focus mode"""
    id: str
    name: str
    description: str


class SettingsAndMemoryMetadata(BaseModel):
    """Metadata for a settings/memory field"""
    id: str
    name: str
    description: str


class AppMetadata(BaseModel):
    """Metadata for an app"""
    id: str
    name: str
    description: str
    skills: List[SkillMetadata]
    focus_modes: List[FocusModeMetadata] = []
    settings_and_memories: List[SettingsAndMemoryMetadata] = []


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


def get_config_manager(request: Request) -> ConfigManager:
    """Get config manager from app state"""
    if hasattr(request.app.state, 'config_manager'):
        return request.app.state.config_manager
    # Fallback to singleton instance if not in app state
    return ConfigManager()


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


def resolve_translation(translation_service, translation_key: str, namespace: str, fallback: str = "") -> str:
    """
    Resolve a translation key to its translated string value.
    
    Args:
        translation_service: TranslationService instance
        translation_key: Translation key (e.g., "web.text" or "web.search.text")
        namespace: Namespace prefix (e.g., "app_skills", "apps", "app_focus_modes", "app_settings_memories")
        fallback: Fallback value if translation not found
    
    Returns:
        Resolved translation string or fallback
    """
    if not translation_service:
        logger.debug(f"Translation service not available for key '{translation_key}', using fallback: '{fallback or translation_key}'")
        return fallback or translation_key
    
    if not translation_key:
        logger.debug(f"Translation key is empty, using fallback: '{fallback}'")
        return fallback
    
    # Normalize translation key: ensure it has namespace prefix if needed
    full_key = translation_key
    if not full_key.startswith(f"{namespace}."):
        full_key = f"{namespace}.{full_key}"
    
    try:
        # Get the full translation structure
        translations = translation_service.get_translations(lang="en")
        
        if not translations:
            logger.warning("No translations loaded for language 'en'")
            return fallback or translation_key
        
        # Check if namespace exists
        if namespace not in translations:
            logger.debug(f"Namespace '{namespace}' not found in translations. Available namespaces: {list(translations.keys())}")
            return fallback or translation_key
        
        # Navigate through nested keys: e.g., apps.web.text or app_skills.web.search.text
        keys = full_key.split('.')
        value = translations
        
        # First navigate to the namespace
        if namespace in value:
            value = value[namespace]
        else:
            logger.debug(f"Namespace '{namespace}' not found in translations for key '{full_key}'")
            return fallback or translation_key
        
        # Then navigate through the rest of the keys (skip namespace since we already navigated to it)
        remaining_keys = keys[1:] if keys[0] == namespace else keys
        for k in remaining_keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                logger.debug(f"Translation key '{full_key}' not found at key '{k}'. Available keys at this level: {list(value.keys()) if isinstance(value, dict) else 'N/A'}")
                return fallback or translation_key
        
        # Extract the text value
        # Translation values can be either:
        # 1. A string directly: "Web Search"
        # 2. A dict with a "text" key: {"text": "Web Search"}
        if isinstance(value, dict) and "text" in value:
            result = value["text"]
            logger.debug(f"Successfully resolved translation key '{full_key}' to: '{result}'")
            return result
        elif isinstance(value, str):
            logger.debug(f"Successfully resolved translation key '{full_key}' to string: '{value}'")
            return value
        else:
            logger.debug(f"Translation value for '{full_key}' is not a string or dict with 'text' key, got: {type(value)}, value: {value}")
            return fallback or translation_key
    except Exception as e:
        logger.warning(f"Error resolving translation key '{full_key}': {e}", exc_info=True)
        return fallback or translation_key


def map_provider_name_to_id(provider_name: str, app_id: str) -> str:
    """
    Map provider name from app.yml to provider ID (provider YAML filename).
    
    Args:
        provider_name: Provider name from app.yml (e.g., "Brave", "Google", "Firecrawl")
        app_id: App ID for context (e.g., "maps" for Google Maps)
        
    Returns:
        Provider ID (lowercase, matches provider YAML filename)
    """
    # Handle special cases
    if provider_name == "Google" and app_id == "maps":
        return "google_maps"
    elif provider_name == "YouTube":
        return "youtube"
    elif provider_name == "Brave" or provider_name == "Brave Search":
        return "brave"
    # Most providers just need to be lowercased
    return provider_name.lower().strip()


def get_provider_api_key_env_vars(provider_id: str) -> List[str]:
    """
    Get the environment variable names for a provider's API key.
    
    Maps provider IDs to their required API key environment variable names.
    This function centralizes the mapping of providers to their API key requirements.
    
    Args:
        provider_id: Provider ID (e.g., "brave", "firecrawl", "youtube")
        
    Returns:
        List of environment variable names to check (in order of preference)
    """
    # Map provider IDs to their API key environment variable names
    # Format: SECRET__{PROVIDER}__API_KEY
    provider_key_map = {
        "brave": ["SECRET__BRAVE__API_KEY", "SECRET__BRAVE_SEARCH__API_KEY"],
        "firecrawl": ["SECRET__FIRECRAWL__API_KEY", "FIRECRAWL_API_KEY"],
        "youtube": ["SECRET__YOUTUBE__API_KEY", "SECRET__YOUTUBE__API_KEY"],
        "google_maps": ["SECRET__GOOGLE_MAPS__API_KEY"],
    }
    
    # Return mapped env vars or default pattern
    if provider_id in provider_key_map:
        return provider_key_map[provider_id]
    
    # Default pattern: SECRET__{PROVIDER_ID_UPPER}__API_KEY
    # Convert provider_id to uppercase and replace underscores with double underscores
    default_key = f"SECRET__{provider_id.upper().replace('_', '__')}__API_KEY"
    return [default_key]


async def check_provider_api_key_available(provider_id: str, secrets_manager: SecretsManager) -> bool:
    """
    Check if an API key is available for a provider.
    
    Checks both Vault and environment variables to determine if the API key is configured.
    This is used to determine if a skill should be shown as available.
    
    Args:
        provider_id: Provider ID (e.g., "brave", "firecrawl", "youtube")
        secrets_manager: SecretsManager instance for checking Vault
        
    Returns:
        True if API key is available, False otherwise
    """
    # Get the Vault path and key name for this provider
    # Standard pattern: kv/data/providers/{provider_id}
    vault_path = f"kv/data/providers/{provider_id}"
    vault_key = "api_key"
    
    # First, try to get from Vault
    try:
        if secrets_manager.vault_token and secrets_manager.vault_url:
            api_key = await secrets_manager.get_secret(
                secret_path=vault_path,
                secret_key=vault_key
            )
            if api_key and api_key.strip():
                logger.debug(f"API key found in Vault for provider '{provider_id}'")
                return True
    except Exception as e:
        logger.debug(f"Error checking Vault for provider '{provider_id}' API key: {e}")
    
    # Fallback to environment variables
    env_var_names = get_provider_api_key_env_vars(provider_id)
    for env_var_name in env_var_names:
        api_key = os.getenv(env_var_name)
        if api_key and api_key.strip():
            logger.debug(f"API key found in environment variable '{env_var_name}' for provider '{provider_id}'")
            return True
    
    logger.debug(f"No API key found for provider '{provider_id}' (checked Vault and env vars: {env_var_names})")
    return False


async def is_skill_available(skill: AppSkillDefinition, app_id: str, secrets_manager: SecretsManager) -> bool:
    """
    Check if a skill is available based on API key availability for its providers.
    
    A skill is considered available if at least one of its providers has a configured API key.
    If a skill has no providers, it's considered available (no API key required).
    
    Args:
        skill: The skill definition
        app_id: The app ID for provider name mapping
        secrets_manager: SecretsManager instance for checking API keys
        
    Returns:
        True if the skill is available (at least one provider has API key), False otherwise
    """
    # If skill has no providers, it's available (no API key required)
    if not skill.providers or len(skill.providers) == 0:
        logger.debug(f"Skill '{skill.id}' has no providers, considering it available")
        return True
    
    # Check if at least one provider has an available API key
    for provider_name in skill.providers:
        provider_id = map_provider_name_to_id(provider_name, app_id)
        is_available = await check_provider_api_key_available(provider_id, secrets_manager)
        if is_available:
            logger.debug(f"Skill '{skill.id}' is available - provider '{provider_id}' has API key configured")
            return True
    
    # No providers have API keys configured
    logger.debug(f"Skill '{skill.id}' is not available - no providers have API keys configured")
    return False


async def fetch_provider_pricing(provider_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch provider-level pricing from internal API.
    
    Args:
        provider_id: Provider ID (e.g., "brave", "firecrawl")
        
    Returns:
        Provider pricing dict or None if not found
    """
    try:
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
            # Convert provider pricing format to billing format if needed
            # Provider pricing may have formats like:
            # - per_request_credits: 10 (Brave)
            # - per_unit: { credits: X } (already in correct format)
            
            if "per_request_credits" in provider_pricing:
                # Convert per_request_credits to per_unit.credits format
                credits_per_request = provider_pricing["per_request_credits"]
                return {
                    "per_unit": {
                        "credits": credits_per_request
                    }
                }
            elif "per_unit" in provider_pricing:
                # Provider already uses per_unit format
                return {"per_unit": provider_pricing["per_unit"]}
            else:
                # Return as-is if it's already in a valid format
                return provider_pricing
        else:
            logger.warning(f"Could not retrieve valid provider pricing for '{provider_id}'. Response: {provider_pricing}")
            return None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.debug(f"Provider pricing not found for '{provider_id}' (404)")
            return None
        logger.warning(f"HTTP error fetching provider pricing for '{provider_id}': {e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"Error fetching provider pricing for '{provider_id}': {e}")
        return None


async def get_skill_providers_with_pricing(
    skill: AppSkillDefinition,
    app_id: str,
    config_manager: ConfigManager
) -> List[ProviderPricing]:
    """
    Get all providers with their pricing, name, and description for a skill.
    
    Args:
        skill: The skill definition
        app_id: The app ID for provider name mapping
        config_manager: ConfigManager instance to fetch provider metadata
        
    Returns:
        List of ProviderPricing objects with name and description from provider YAML files
    """
    providers_list = []
    
    # First, check if skill has explicit pricing (not provider-specific)
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
        
        if pricing_dict:
            # Skill-level pricing applies to all providers or no specific provider
            # We'll add it as a generic provider entry
            providers_list.append(ProviderPricing(
                provider="skill",
                name="Skill-level pricing",
                description="Pricing defined at the skill level",
                pricing=pricing_dict
            ))
    
    # Then, fetch pricing and metadata for each provider listed in the skill
    if skill.providers:
        for provider_name in skill.providers:
            provider_id = map_provider_name_to_id(provider_name, app_id)
            
            # Get provider config to extract name and description
            provider_config = config_manager.get_provider_config(provider_id)
            provider_display_name = provider_name  # Fallback to provider_name from app.yml
            provider_description = ""  # Default empty description
            
            if provider_config:
                # Use name and description from provider YAML file if available
                provider_display_name = provider_config.get("name", provider_name)
                provider_description = provider_config.get("description", "")
            else:
                logger.debug(f"Provider config not found for '{provider_id}', using fallback name '{provider_name}'")
            
            # Fetch pricing for this provider
            provider_pricing = await fetch_provider_pricing(provider_id)
            
            if provider_pricing:
                providers_list.append(ProviderPricing(
                    provider=provider_id,  # Use provider_id for consistency
                    name=provider_display_name,
                    description=provider_description,
                    pricing=provider_pricing
                ))
            else:
                # Still include provider even if pricing fetch failed
                # This ensures all providers are listed with their metadata
                providers_list.append(ProviderPricing(
                    provider=provider_id,
                    name=provider_display_name,
                    description=provider_description,
                    pricing={}
                ))
    
    return providers_list


async def call_app_skill(
    app_id: str,
    skill_id: str,
    input_data: Dict[str, Any],
    parameters: Dict[str, Any],
    user_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Call an app skill via internal service communication.
    
    SECURITY: Input data is sanitized for ASCII smuggling attacks before processing.
    ASCII smuggling uses invisible Unicode characters to embed hidden instructions
    that bypass prompt injection detection but are processed by LLMs.
    See: docs/architecture/prompt_injection_protection.md
    
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
        
        # SECURITY: Sanitize all text in input_data to prevent ASCII smuggling attacks
        # This removes invisible Unicode characters that could embed hidden instructions
        user_id_short = user_info['user_id'][:8] if user_info.get('user_id') else 'unknown'
        log_prefix = f"[API {app_id}/{skill_id}][User {user_id_short}...] "
        sanitized_input_data = _sanitize_dict_recursively(input_data, log_prefix=log_prefix)
        # Note: parameters are also sanitized but currently not passed separately to skills
        # They're merged into the payload via context fields. If parameters are added as
        # separate payload in the future, use _sanitize_dict_recursively(parameters, log_prefix)

        # Send sanitized input_data directly as the request body to the skill
        # The skill expects the tool_schema structure directly (e.g., {"requests": [...]})
        # Context is added as metadata fields prefixed with _ so they don't interfere with the skill's schema
        request_payload = sanitized_input_data.copy() if isinstance(sanitized_input_data, dict) else sanitized_input_data
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


def is_skill_execution_successful(result: Dict[str, Any]) -> bool:
    """
    Check if a skill execution was successful by examining the result structure.
    
    A skill execution is considered successful if:
    1. There is no top-level error field (or it's None/empty)
    2. There is no error in the data.error field
    3. At least one result in data.results has actual results (not just errors)
    
    Args:
        result: The result dictionary returned from skill execution
        
    Returns:
        True if execution was successful, False if there were errors
    """
    if not isinstance(result, dict):
        # If result is not a dict, we can't determine success - assume failure to be safe
        logger.debug("Skill execution result is not a dictionary, marking as failed")
        return False
    
    # Check for top-level error (must be non-empty string to indicate failure)
    top_level_error = result.get("error")
    if top_level_error and isinstance(top_level_error, str) and top_level_error.strip():
        logger.debug("Skill execution has top-level error, marking as failed")
        return False
    
    # Check for error in data.error field
    # The result might be the data directly, or wrapped in a "data" field
    data = result.get("data", result)  # If no "data" field, use result itself
    
    if isinstance(data, dict):
        # Check for error field in data
        data_error = data.get("error")
        if data_error and isinstance(data_error, str) and data_error.strip():
            logger.debug("Skill execution has error in data.error field, marking as failed")
            return False
        
        # Check results array - if all results have errors or are empty, execution failed
        results = data.get("results", [])
        if isinstance(results, list) and len(results) > 0:
            # Check if all results have errors or empty results arrays
            all_failed = True
            for result_item in results:
                if isinstance(result_item, dict):
                    # Check if this result item has actual results (not just errors)
                    item_results = result_item.get("results", [])
                    item_error = result_item.get("error")
                    
                    # If there are actual results (non-empty list), execution was at least partially successful
                    if isinstance(item_results, list) and len(item_results) > 0:
                        all_failed = False
                        break
                    # If there's no error and no results, might be a valid empty result
                    # But we need at least one successful result to consider it successful
                    elif not item_error or (isinstance(item_error, str) and not item_error.strip()):
                        # Empty result without error might be valid (depends on skill)
                        # But we still need at least one result with actual data
                        pass
            
            # If all results failed (all have errors and empty results arrays), mark as failed
            if all_failed:
                logger.debug("All skill execution results have errors or are empty, marking as failed")
                return False
    
    # If we get here, execution was successful (or at least partially successful)
    return True


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
    elif skill_def.full_model_reference:
        # Skill has a full model reference - try to get model-specific pricing
        try:
            # Parse provider and model from full_model_reference (e.g., "google/gemini-3-pro-image-preview")
            if "/" in skill_def.full_model_reference:
                provider_id, model_suffix = skill_def.full_model_reference.split("/", 1)
                
                # Fetch model-specific pricing via internal API
                headers = {"Content-Type": "application/json"}
                if INTERNAL_API_SHARED_TOKEN:
                    headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
                
                endpoint = f"internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
                url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    pricing_config = response.json()
                    logger.debug(f"Using model-specific pricing for '{skill_def.full_model_reference}': {pricing_config}")
            else:
                logger.warning(f"Invalid full_model_reference format: '{skill_def.full_model_reference}'. Expected 'provider/model'.")
        except Exception as e:
            logger.warning(f"Error fetching model-specific pricing for '{skill_def.full_model_reference}': {e}")
            
    if not pricing_config and skill_def.providers and len(skill_def.providers) > 0:
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
    tags=["Apps"],  # Use "Apps" tag (not "Apps API")
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
        config_manager = get_config_manager(request)
        
        # Initialize secrets manager for API key availability checks
        secrets_manager = SecretsManager(cache_service=cache_service)
        await secrets_manager.initialize()
        
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
            
            # Convert skills - filter by stage and API key availability
            skills = []
            for skill in app_metadata.skills or []:
                skill_stage = getattr(skill, 'stage', 'development').lower()
                if skill_stage not in allowed_stages:
                    continue
                
                # Check if skill is available based on API key configuration
                skill_available = await is_skill_available(skill, app_id, secrets_manager)
                if not skill_available:
                    logger.debug(f"Skipping skill '{skill.id}' from app '{app_id}' - no API keys configured for providers")
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
                
                # Get all providers with their pricing, name, and description
                providers = await get_skill_providers_with_pricing(skill, app_id, config_manager)
                
                skills.append(SkillMetadata(
                    id=skill.id,
                    name=skill_name,
                    description=skill_description,
                    providers=providers
                ))
            
            # Convert focus modes - filter by stage
            focus_modes = []
            for focus in app_metadata.focuses or []:
                focus_stage = getattr(focus, 'stage', 'development').lower()
                if focus_stage not in allowed_stages:
                    continue
                
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
                focus_modes.append(FocusModeMetadata(
                    id=focus.id,
                    name=focus_name,
                    description=focus_description
                ))
            
            # Convert settings_and_memories - filter by stage
            settings_and_memories = []
            if app_metadata.memory_fields:
                for field in app_metadata.memory_fields:
                    field_stage = getattr(field, 'stage', 'development').lower()
                    if field_stage not in allowed_stages:
                        continue
                    
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
                    settings_and_memories.append(SettingsAndMemoryMetadata(
                        id=field.id,
                        name=field_name,
                        description=field_description
                    ))
            
            # Include app if it has at least one skill, focus mode, or settings_and_memories
            if skills or focus_modes or settings_and_memories:
                apps.append(AppMetadata(
                    id=app_id,
                    name=app_name,
                    description=app_description,
                    skills=skills,
                    focus_modes=focus_modes,
                    settings_and_memories=settings_and_memories
                ))
        
        return AppsListResponse(apps=apps)
        
    except Exception as e:
        logger.error(f"Error listing apps for user {user_info['user_id']}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list apps")


# ---------------------------------------------------------------------------
# Travel app custom routes (non-skill endpoints)
# ---------------------------------------------------------------------------

class BookingLinkRequest(BaseModel):
    """Request for on-demand booking URL lookup via SerpAPI."""
    booking_token: str = Field(
        ...,
        description="The booking_token from a flight search result (from search_connections skill output)."
    )
    booking_context: Optional[Dict[str, str]] = Field(
        None,
        description="Original SerpAPI search parameters needed for booking_token lookup. "
        "Keys: departure_id, arrival_id, outbound_date, return_date, type, currency, gl, adults, travel_class."
    )


class BookingLinkResponse(BaseModel):
    """Response containing the resolved booking URL and provider name."""
    success: bool
    booking_url: Optional[str] = Field(
        None,
        description="Direct clickable booking URL (e.g., airline website or OTA). None if no booking link found."
    )
    booking_provider: Optional[str] = Field(
        None,
        description="Name of the booking provider (e.g., 'Lufthansa', 'Kayak'). None if no booking link found."
    )
    credits_charged: Optional[int] = Field(
        None,
        description="Credits charged for this lookup (25 credits = 1 SerpAPI credit)."
    )
    error: Optional[str] = Field(None, description="Error message if lookup failed.")


def _register_travel_custom_routes(app: FastAPI, app_name: str) -> None:
    """
    Register travel-specific REST endpoints that are not standard skills.

    Currently registers:
    - POST /v1/apps/travel/booking-link — On-demand booking URL lookup using
      a booking_token from a previous flight search. Costs 25 credits (1 SerpAPI credit).

    Supports both session auth (web app) and API key auth (external clients).
    """
    from backend.apps.travel.providers.serpapi_provider import lookup_booking_url
    from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user_or_api_key

    async def booking_link_handler(
        request_body: BookingLinkRequest,
        request: Request = None,
        user=Depends(get_current_user_or_api_key),
        cache_service: CacheService = Depends(get_cache_service),
        directus_service: DirectusService = Depends(get_directus_service),
    ) -> BookingLinkResponse:
        """
        Look up a booking URL for a flight using the booking_token from search results.

        When a user searches for flights via the search_connections skill, each result
        includes a `booking_token`. This endpoint uses that token to fetch a direct
        booking URL from SerpAPI (costs 1 SerpAPI credit = 25 OpenMates credits).

        This avoids spending credits on booking lookups during the initial search,
        only charging when the user actually wants to book a specific flight.

        Supports both session authentication (web app) and API key authentication.
        """
        # Extract user_id from the User object (works for both session and API key auth)
        user_id = user.id if hasattr(user, 'id') else str(user)

        try:
            logger.info(
                f"Travel booking-link: User {user_id} requesting "
                f"booking URL (token: {request_body.booking_token[:20]}...)"
            )

            result = await lookup_booking_url(
                request_body.booking_token,
                booking_context=request_body.booking_context,
            )

            # Only charge credits if we successfully got a booking URL
            credits_charged = 0
            if result.get("booking_url"):
                credits_charged = 25
                user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
                usage_details = {
                    "external_request": False,
                    "units_processed": 1,
                }
                await charge_credits_via_internal_api(
                    user_id=user_id,
                    user_id_hash=user_id_hash,
                    credits=credits_charged,
                    app_id="travel",
                    skill_id="booking_link",
                    usage_details=usage_details,
                )

            return BookingLinkResponse(
                success=True,
                booking_url=result.get("booking_url"),
                booking_provider=result.get("booking_provider"),
                credits_charged=credits_charged,
            )

        except ValueError as e:
            logger.error(f"Travel booking-link config error: {e}")
            return BookingLinkResponse(
                success=False,
                error="Booking service not configured",
            )
        except Exception as e:
            logger.error(
                f"Travel booking-link error for user {user_id}: {e}",
                exc_info=True,
            )
            return BookingLinkResponse(
                success=False,
                error=f"Booking lookup failed: {str(e)}",
            )

    # Register the endpoint — no ApiKeyAuth dependency since we use
    # get_current_user_or_api_key which handles both auth methods
    app.add_api_route(
        path="/v1/apps/travel/booking-link",
        endpoint=limiter.limit("30/minute")(booking_link_handler),
        methods=["POST"],
        response_model=BookingLinkResponse,
        tags=[f"Apps | {app_name.capitalize()}"],
        name="travel_booking_link",
        summary="Look up booking URL for a flight",
        description=(
            "Look up a direct booking URL for a flight using the booking_token "
            "from a previous search_connections result. Costs 25 credits per "
            "successful lookup (1 SerpAPI credit). Returns the best booking "
            "option (preferring direct airline over OTA). "
            "Supports both session and API key authentication."
        ),
    )
    logger.info("Registered custom route: POST /v1/apps/travel/booking-link")


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
                    config_mgr = get_config_manager(request)
                    
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
                        
                        # Get all providers with their pricing, name, and description
                        providers = await get_skill_providers_with_pricing(skill, captured_app_id, config_mgr)
                        
                        skills.append(SkillMetadata(
                            id=skill.id,
                            name=skill_name,
                            description=skill_description,
                            providers=providers
                        ))
                    
                    # Convert focus modes - filter by stage
                    focus_modes = []
                    for focus in captured_app_metadata.focuses or []:
                        focus_stage = getattr(focus, 'stage', 'development').lower()
                        if focus_stage not in allowed:
                            continue
                        
                        focus_name = resolve_translation(
                            trans_service,
                            focus.name_translation_key,
                            namespace="app_focus_modes",
                            fallback=focus.id
                        )
                        focus_description = resolve_translation(
                            trans_service,
                            focus.description_translation_key,
                            namespace="app_focus_modes",
                            fallback=""
                        )
                        focus_modes.append(FocusModeMetadata(
                            id=focus.id,
                            name=focus_name,
                            description=focus_description
                        ))
                    
                    # Convert settings_and_memories - filter by stage
                    settings_and_memories = []
                    if captured_app_metadata.memory_fields:
                        for field in captured_app_metadata.memory_fields:
                            field_stage = getattr(field, 'stage', 'development').lower()
                            if field_stage not in allowed:
                                continue
                            
                            field_name = resolve_translation(
                                trans_service,
                                field.name_translation_key,
                                namespace="app_settings_memories",
                                fallback=field.id
                            )
                            field_description = resolve_translation(
                                trans_service,
                                field.description_translation_key,
                                namespace="app_settings_memories",
                                fallback=""
                            )
                            settings_and_memories.append(SettingsAndMemoryMetadata(
                                id=field.id,
                                name=field_name,
                                description=field_description
                            ))
                    
                    return AppMetadata(
                        id=captured_app_id,
                        name=resolved_name,
                        description=resolved_description,
                        skills=skills,
                        focus_modes=focus_modes,
                        settings_and_memories=settings_and_memories
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
            tags=[f"Apps | {app_name.capitalize()}"],  # Use "Apps | {AppName}" tag for better organization (capitalized)
            name=f"get_app_{app_id}",
            summary=f"Get metadata for {app_name}",
            description=f"Get metadata for the {app_name} app. {app_description}".strip(),
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
                        config_mgr = get_config_manager(request)
                        
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
                        
                        # Get all providers with their pricing, name, and description
                        providers = await get_skill_providers_with_pricing(captured_skill, captured_app_id, config_mgr)
                        
                        return SkillMetadata(
                            id=captured_skill.id,
                            name=resolved_name,
                            description=resolved_description,
                            providers=providers
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
                
                # Try to import models from the skill module if class_path exists
                # This works for skills both with and without tool_schema
                if captured_skill.class_path:
                    try:
                        import importlib
                        # Import the skill module to get its models
                        # class_path is relative to backend/apps (e.g., "ai.skills.ask_skill.AskSkill")
                        # We need to convert to full module path: "backend.apps.ai.skills.ask_skill"
                        module_path, class_name = captured_skill.class_path.rsplit('.', 1)
                        if not module_path.startswith('backend.'):
                            full_module_path = f"backend.apps.{module_path}"
                        else:
                            full_module_path = module_path
                        skill_module = importlib.import_module(full_module_path)
                        
                        # Look for Request and Response models in the module
                        # Common patterns: SearchRequest/SearchResponse, ReadRequest/ReadResponse, etc.
                        # Include skill-specific names like GetDocsRequest for get_docs skill
                        # Also include AI-specific models: AskSkillRequest, OpenAICompletionRequest
                        for model_name in ['OpenAICompletionRequest', 'AskSkillRequest', 'SearchRequest', 'ReadRequest', 'TranscriptRequest', 'GetDocsRequest', 'ImageGenerationRequest', 'Request']:
                            if hasattr(skill_module, model_name):
                                SkillRequestModel = getattr(skill_module, model_name)
                                logger.debug(f"Found request model '{model_name}' for skill {captured_app_id}/{captured_skill.id}")
                                break
                        
                        for model_name in ['OpenAICompletionResponse', 'AskSkillResponse', 'SearchResponse', 'ReadResponse', 'TranscriptResponse', 'GetDocsResponse', 'ImageGenerationResponse', 'Response']:
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
                            
                            # Check if skill execution was successful before charging credits
                            # Only charge credits if the execution was successful (no errors in result)
                            execution_successful = is_skill_execution_successful(result)
                            
                            if not execution_successful:
                                logger.info(f"Skill execution failed for {captured_app_id}/{captured_skill.id}, not charging credits")
                                credits_charged = 0
                            else:
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
                                        "api_key_name": user_info.get('api_key_encrypted_name'),
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
                
                # Skills with request/response models but no tool_schema (e.g., AI ask skill)
                # These skills define their own Pydantic models directly in the skill module
                elif SkillRequestModel and SkillResponseModel and not captured_skill.tool_schema:
                    # Check if this is the AI ask skill which needs special handling for streaming
                    is_ai_ask_skill = (captured_app_id == "ai" and captured_skill.id == "ask")
                    
                    if is_ai_ask_skill:
                        # Special handler for AI ask skill that supports streaming and non-streaming modes
                        # Import StreamingResponse for SSE streaming
                        from fastapi.responses import StreamingResponse as FastAPIStreamingResponse
                        
                        async def ai_ask_skill_handler(
                            request_body: SkillRequestModel,
                            request: Request = None,
                            user_info: Dict[str, Any] = ApiKeyAuth,
                            cache_service: CacheService = Depends(get_cache_service),
                            directus_service: DirectusService = Depends(get_directus_service)
                        ) -> Any:
                            """
                            Execute the AI Ask skill with full streaming and non-streaming support.
                            
                            - If stream=true: Returns Server-Sent Events (SSE) stream with real-time response chunks
                            - If stream=false: Returns complete OpenAI-compatible response after processing
                            
                            Requires API key authentication.
                            The skill will be executed, billed, and a usage entry will be created automatically.
                            """
                            try:
                                # Convert Pydantic model to dict
                                request_dict = request_body.model_dump() if hasattr(request_body, 'model_dump') else dict(request_body)
                                
                                # Determine if streaming is requested
                                is_streaming = request_dict.get('stream', False)
                                
                                logger.info(f"External API: User {user_info['user_id']} executing ai/ask (streaming={is_streaming})")
                                
                                # Construct skill URL
                                hostname = f"app-{captured_app_id}"
                                skill_url = f"http://{hostname}:{DEFAULT_APP_INTERNAL_PORT}/skills/{captured_skill.id}"
                                
                                # Prepare headers
                                headers = {
                                    'Content-Type': 'application/json',
                                    'X-External-User-ID': user_info['user_id'],
                                    'X-API-Key-Name': user_info.get('api_key_encrypted_name', ''),
                                }
                                
                                # Sanitize input data
                                user_id_short = user_info['user_id'][:8] if user_info.get('user_id') else 'unknown'
                                log_prefix = f"[API ai/ask][User {user_id_short}...] "
                                sanitized_input = _sanitize_dict_recursively(request_dict, log_prefix=log_prefix)
                                
                                # Add context metadata
                                request_payload = sanitized_input.copy() if isinstance(sanitized_input, dict) else {}
                                request_payload['_user_id'] = user_info['user_id']
                                request_payload['_api_key_name'] = user_info.get('api_key_encrypted_name', '')
                                request_payload['_api_key_hash'] = user_info.get('api_key_hash')
                                request_payload['_device_hash'] = user_info.get('device_hash')
                                request_payload['_external_request'] = True
                                
                                if is_streaming:
                                    # STREAMING MODE: Proxy SSE stream from app-ai service
                                    async def stream_generator():
                                        """Generator that proxies the SSE stream from the AI service."""
                                        try:
                                            # Use a longer timeout for streaming (5 minutes)
                                            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                                                async with client.stream(
                                                    'POST',
                                                    skill_url,
                                                    json=request_payload,
                                                    headers=headers
                                                ) as response:
                                                    if response.status_code != 200:
                                                        error_text = await response.aread()
                                                        logger.error(f"AI skill streaming error: {response.status_code} - {error_text}")
                                                        yield f'data: {{"error": "Service error: {response.status_code}"}}\n\n'
                                                        yield 'data: [DONE]\n\n'
                                                        return
                                                    
                                                    # Stream the response chunks as-is (they're already in SSE format)
                                                    async for line in response.aiter_lines():
                                                        if line:
                                                            yield f"{line}\n"
                                                        else:
                                                            yield "\n"
                                        except httpx.TimeoutException:
                                            logger.error("AI skill streaming timeout")
                                            yield 'data: {"error": "Request timeout"}\n\n'
                                            yield 'data: [DONE]\n\n'
                                        except Exception as e:
                                            logger.error(f"AI skill streaming error: {e}", exc_info=True)
                                            yield f'data: {{"error": "{str(e)}"}}\n\n'
                                            yield 'data: [DONE]\n\n'

                                    return FastAPIStreamingResponse(
                                        stream_generator(),
                                        media_type="text/event-stream",
                                        headers={
                                            "Cache-Control": "no-cache",
                                            "Connection": "keep-alive",
                                            "X-Accel-Buffering": "no"  # Disable nginx buffering
                                        }
                                    )
                                else:
                                    # NON-STREAMING MODE: Wait for complete response
                                    # Use a longer timeout (5 minutes) for AI processing
                                    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                                        response = await client.post(
                                            skill_url,
                                            json=request_payload,
                                            headers=headers
                                        )
                                        
                                        if response.status_code != 200:
                                            logger.error(f"AI skill error: {response.status_code} - {response.text}")
                                            raise HTTPException(
                                                status_code=response.status_code,
                                                detail=f"AI skill error: {response.text}"
                                            )
                                        
                                        # Parse the OpenAI-compatible response
                                        result = response.json()
                                        
                                        # Return the result directly (it's already in OpenAI format)
                                        # Clean up None fields if it's a dict
                                        if isinstance(result, dict):
                                            # Recursively remove None values to be fully compliant with OpenAI standard
                                            def remove_none(obj):
                                                if isinstance(obj, list):
                                                    return [remove_none(x) for x in obj if x is not None]
                                                elif isinstance(obj, dict):
                                                    return {k: remove_none(v) for k, v in obj.items() if v is not None}
                                                return obj
                                            return remove_none(result)
                                        
                                        return result
                                        
                            except HTTPException:
                                raise
                            except httpx.TimeoutException:
                                logger.error("AI skill timeout")
                                raise HTTPException(status_code=504, detail="AI processing timeout. Please try again.")
                            except Exception as e:
                                logger.error(f"Error executing AI ask skill: {e}", exc_info=True)
                                raise HTTPException(status_code=500, detail=f"AI skill error: {str(e)}")
                        
                        return ai_ask_skill_handler
                    
                    # Standard handler for other skills with models but no tool_schema
                    class WrappedSkillResponse(BaseModel):
                        """Response wrapper for skill execution"""
                        success: bool
                        data: Optional[SkillResponseModel] = Field(None, description="The skill execution result (only present when success=True)")
                        error: Optional[str] = Field(None, description="Error message if execution failed")
                        credits_charged: Optional[int] = Field(None, description="Credits charged for this execution")
                    
                    async def post_skill_handler(
                        request_body: SkillRequestModel,
                        request: Request = None,
                        user_info: Dict[str, Any] = ApiKeyAuth,
                        cache_service: CacheService = Depends(get_cache_service),
                        directus_service: DirectusService = Depends(get_directus_service)
                    ) -> WrappedSkillResponse:
                        """
                        Execute a skill from a specific app.
                        
                        Requires API key authentication.
                        The skill will be executed, billed, and a usage entry will be created automatically.
                        Rate limited to 30 requests per minute per API key.
                        
                        The request body should match the skill's Pydantic model structure directly.
                        """
                        try:
                            logger.info(f"External API: User {user_info['user_id']} executing {captured_app_id}/{captured_skill.id} (direct model)")
                            
                            # Convert Pydantic model to dict for skill execution
                            request_dict = request_body.model_dump() if hasattr(request_body, 'model_dump') else dict(request_body)
                            
                            # Execute the skill - pass request_dict directly
                            result = await call_app_skill(
                                app_id=captured_app_id,
                                skill_id=captured_skill.id,
                                input_data=request_dict,
                                parameters={},
                                user_info=user_info
                            )
                            
                            # Check if skill execution was successful before charging credits
                            execution_successful = is_skill_execution_successful(result)
                            
                            if not execution_successful:
                                logger.info(f"Skill execution failed for {captured_app_id}/{captured_skill.id}, not charging credits")
                                credits_charged = 0
                            else:
                                # Calculate credits to charge based on pricing
                                credits_charged = await calculate_skill_credits(
                                    app_metadata=captured_app_metadata,
                                    skill_id=captured_skill.id,
                                    input_data=request_dict,
                                    result_data=result
                                )
                                
                                if credits_charged > 0:
                                    user_id_hash = hashlib.sha256(user_info['user_id'].encode()).hexdigest()
                                    usage_details = {
                                        "api_key_name": user_info.get('api_key_encrypted_name'),
                                        "external_request": True,
                                        "units_processed": 1
                                    }
                                    await charge_credits_via_internal_api(
                                        user_id=user_info['user_id'],
                                        user_id_hash=user_id_hash,
                                        credits=credits_charged,
                                        app_id=captured_app_id,
                                        skill_id=captured_skill.id,
                                        usage_details=usage_details,
                                        api_key_hash=user_info.get('api_key_hash'),
                                        device_hash=user_info.get('device_hash'),
                                    )
                            
                            # Parse result into response model if possible
                            skill_response = None
                            if result and execution_successful:
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
                            
                            # Check if skill execution was successful before charging credits
                            # Only charge credits if the execution was successful (no errors in result)
                            execution_successful = is_skill_execution_successful(result)
                            
                            if not execution_successful:
                                logger.info(f"Skill execution failed for {captured_app_id}/{captured_skill.id}, not charging credits")
                                credits_charged = 0
                            else:
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
                                        "api_key_name": user_info.get('api_key_encrypted_name'),
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
                            
                            # Check if skill execution was successful before charging credits
                            # Only charge credits if the execution was successful (no errors in result)
                            execution_successful = is_skill_execution_successful(result)
                            
                            if not execution_successful:
                                logger.info(f"Skill execution failed for {captured_app_id}/{captured_skill.id}, not charging credits")
                                credits_charged = 0
                            else:
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
                                        "api_key_name": user_info.get('api_key_encrypted_name'),
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
                tags=[f"Apps | {app_name.capitalize()}"],  # Use "Apps | {AppName}" tag for better organization (capitalized)
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
            
            # SPECIAL CASE: AI Ask skill returns raw OpenAI response or stream
            extra_responses = {}
            if app_id == "ai" and skill.id == "ask":
                response_model = None # Disable response validation for this dynamic union type (JSON or Stream)
                # Document the possible responses for better auto-generated documentation
                extra_responses = {
                    200: {
                        "model": OpenAICompletionResponse,
                        "description": "Successful non-streaming response",
                    },
                    400: {"model": OpenAIErrorResponse, "description": "Invalid request"},
                    401: {"model": OpenAIErrorResponse, "description": "Authentication error"},
                    402: {"model": OpenAIErrorResponse, "description": "Insufficient credits"},
                    429: {"model": OpenAIErrorResponse, "description": "Rate limit exceeded"},
                }
            else:
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
                responses=extra_responses, # Add explicit documentation for AI responses
                tags=[f"Apps | {app_name.capitalize()}"],  # Use "Apps | {AppName}" tag for better organization (capitalized)
                name=f"execute_skill_{app_id}_{skill.id}",
                summary=f"Execute {skill_name}",
                description=f"Execute the {skill_name} skill. The skill will be executed, billed, and a usage entry will be created automatically. Requires API key authentication.",
                dependencies=[ApiKeyAuth]  # Mark endpoint as requiring API key
            )
            
            logger.info(f"Registered routes for skill: GET/POST /v1/apps/{app_id}/skills/{skill.id}")
        
        # Register app-specific custom endpoints (non-skill routes)
        if app_id == "travel":
            _register_travel_custom_routes(app, app_name)
        
        logger.info(f"Registered routes for app: GET /v1/apps/{app_id}")
