# backend/core/api/app/routes/apps.py
# 
# REST API endpoints for app discovery and metadata.
# Provides access to discovered apps, their skills, focus modes, and settings/memories.

from __future__ import annotations  # Enable postponed evaluation of annotations for forward references

import logging
import os
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition, ProviderRef
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.routes.internal_api import get_directus_service, get_cache_service
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import ConfigManager
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user_optional,
    get_encryption_service,
)
from backend.shared.python_utils.provider_health import map_provider_name_to_id, is_provider_healthy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/apps", tags=["Apps"])

EDAMAM_PROVIDER_ID = "edamam"
EDAMAM_VAULT_SECRET_KEYS = ("app_id", "app_key")
EDAMAM_ENV_SECRET_KEYS = ("SECRET__EDAMAM__APP_ID", "SECRET__EDAMAM__APP_KEY")
IMPORTED_TO_VAULT_PLACEHOLDER = "IMPORTED_TO_VAULT"


def _has_secret_value(value: Optional[str]) -> bool:
    return bool(value and value.strip() and value.strip() != IMPORTED_TO_VAULT_PLACEHOLDER)


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
        "mistral": ["SECRET__MISTRAL_AI__API_KEY", "SECRET__MISTRAL__API_KEY"],
        "mistral_ai": ["SECRET__MISTRAL_AI__API_KEY"],
        "google_ai_studio": ["SECRET__GOOGLE_AI_STUDIO__API_KEY"],
        "google_vertex": ["GOOGLE_VERTEX_PROJECT_ID", "GOOGLE_VERTEX_SERVICE_ACCOUNT_JSON"],
        "firecrawl": ["SECRET__FIRECRAWL__API_KEY", "FIRECRAWL_API_KEY"],
        "youtube": ["SECRET__YOUTUBE__API_KEY", "SECRET__YOUTUBE__API_KEY"],
        "google_maps": ["SECRET__GOOGLE_MAPS__API_KEY"],
        "protonmail": ["SECRET__PROTONMAIL__BRIDGE_PASSWORD"],
        "serpapi": ["SECRET__SERPAPI__API_KEY"],
    }
    
    # Return mapped env vars or default pattern
    if provider_id in provider_key_map:
        return provider_key_map[provider_id]
    
    # Default pattern: SECRET__{PROVIDER_ID_UPPER}__API_KEY
    # Convert provider_id to uppercase and replace underscores with double underscores
    default_key = f"SECRET__{provider_id.upper().replace('_', '__')}__API_KEY"
    return [default_key]


def _provider_requires_no_key(provider_id: str, provider_configs: Dict[str, Dict[str, Any]]) -> bool:
    config = provider_configs.get(provider_id) or {}
    return config.get("no_api_key") is True


def _model_server_ids(provider_id: str, model: Dict[str, Any]) -> set[str]:
    server_ids = {provider_id}
    default_server = model.get("default_server")
    if isinstance(default_server, str) and default_server.strip():
        server_ids.add(default_server.strip())
    for server in model.get("servers") or []:
        if isinstance(server, dict) and isinstance(server.get("id"), str) and server["id"].strip():
            server_ids.add(server["id"].strip())
    return server_ids


async def _available_provider_ids(
    *,
    provider_configs: Dict[str, Dict[str, Any]],
    secrets_manager: SecretsManager,
) -> set[str]:
    available: set[str] = set()
    candidate_ids = set(provider_configs.keys())
    for provider_id, provider in provider_configs.items():
        for model in provider.get("models", []):
            if isinstance(model, dict):
                candidate_ids.update(_model_server_ids(provider_id, model))

    for provider_id in sorted(candidate_ids):
        if _provider_requires_no_key(provider_id, provider_configs):
            available.add(provider_id)
            continue
        if await check_provider_api_key_available(provider_id, secrets_manager):
            available.add(provider_id)
    return available


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
    if provider_id == EDAMAM_PROVIDER_ID:
        try:
            if secrets_manager.vault_token and secrets_manager.vault_url:
                vault_values = [
                    await secrets_manager.get_secret(
                        secret_path="kv/data/providers/edamam",
                        secret_key=secret_key,
                    )
                    for secret_key in EDAMAM_VAULT_SECRET_KEYS
                ]
                if all(_has_secret_value(value) for value in vault_values):
                    logger.debug("Edamam app ID and app key found in Vault")
                    return True
        except Exception as e:
            logger.debug(f"Error checking Vault for provider '{provider_id}' app credentials: {e}")

        env_values = [os.getenv(env_var_name) for env_var_name in EDAMAM_ENV_SECRET_KEYS]
        if all(_has_secret_value(value) for value in env_values):
            logger.debug("Edamam app ID and app key found in environment")
            return True

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
            if _has_secret_value(api_key):
                logger.debug(f"API key found in Vault for provider '{provider_id}'")
                return True
    except Exception as e:
        logger.debug(f"Error checking Vault for provider '{provider_id}' API key: {e}")
    
    # Fallback to environment variables
    env_var_names = get_provider_api_key_env_vars(provider_id)
    for env_var_name in env_var_names:
        api_key = os.getenv(env_var_name)
        if _has_secret_value(api_key):
            logger.debug(f"API key found in environment variable '{env_var_name}' for provider '{provider_id}'")
            return True

    # Google Lyria uses Vertex AI service-account credentials instead of an API key.
    if provider_id == "google":
        vertex_project_id = os.getenv("GOOGLE_VERTEX_PROJECT_ID")
        vertex_service_account = os.getenv("GOOGLE_VERTEX_SERVICE_ACCOUNT_JSON")
        try:
            if secrets_manager.vault_token and secrets_manager.vault_url:
                vertex_project_id = vertex_project_id or await secrets_manager.get_secret(
                    secret_path=vault_path,
                    secret_key="project_id",
                )
                vertex_service_account = vertex_service_account or await secrets_manager.get_secret(
                    secret_path=vault_path,
                    secret_key="service_account_json",
                )
        except Exception as e:
            logger.debug(f"Error checking Vault for provider '{provider_id}' Vertex credentials: {e}")

        if (
            vertex_project_id
            and vertex_project_id.strip()
            and vertex_service_account
            and vertex_service_account.strip()
        ):
            logger.debug("Google Vertex credentials found for provider 'google'")
            return True
    
    logger.debug(f"No API key found for provider '{provider_id}' (checked Vault and env vars: {env_var_names})")
    return False


async def is_skill_available(
    skill: AppSkillDefinition,
    app_id: str,
    secrets_manager: SecretsManager,
    cache_service: Optional[CacheService] = None,
) -> bool:
    """
    Check if a skill is available based on API key availability AND provider health.

    A skill is considered available if at least one of its providers:
    1. Has a configured API key OR is marked with no_api_key=True, AND
    2. Is healthy according to the cached health check (fail-open if no data).

    If a skill has no providers, it's considered available (no API key required).

    Args:
        skill: The skill definition
        app_id: The app ID for provider name mapping
        secrets_manager: SecretsManager instance for checking API keys
        cache_service: Optional CacheService for checking provider health status

    Returns:
        True if the skill is available (at least one provider is configured and healthy), False otherwise
    """
    # If skill has no providers, it's available (no API key required)
    if not skill.providers or len(skill.providers) == 0:
        logger.debug(f"Skill '{skill.id}' has no providers, considering it available")
        return True

    # Check if at least one provider is configured AND healthy
    for provider_ref in skill.providers:
        provider_id = map_provider_name_to_id(provider_ref.name, app_id)

        # Check configuration: API key available or no_api_key flag
        if provider_ref.no_api_key:
            is_configured = True
        else:
            is_configured = await check_provider_api_key_available(provider_id, secrets_manager)

        if not is_configured:
            continue

        # Check health: provider must also be healthy (fail-open if no health data)
        if not await is_provider_healthy(provider_id, cache_service):
            logger.debug(f"Skill '{skill.id}' - provider '{provider_id}' is configured but unhealthy, skipping")
            continue

        logger.debug(f"Skill '{skill.id}' is available - provider '{provider_id}' is configured and healthy")
        return True

    # No providers are both configured and healthy
    logger.debug(f"Skill '{skill.id}' is not available - no providers are configured and healthy")
    return False


async def _get_secret_or_env(
    *,
    secrets_manager: SecretsManager,
    secret_key: str,
    env_var: str,
    default: str = "",
) -> str:
    try:
        value = await secrets_manager.get_secret(
            secret_path="kv/data/providers/protonmail",
            secret_key=secret_key,
        )
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return (os.getenv(env_var, default) or "").strip()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _is_enabled_flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def _is_protonmail_user_allowed(
    *,
    current_user: Optional[User],
    encryption_service: EncryptionService,
    secrets_manager: SecretsManager,
) -> bool:
    if not current_user:
        return False

    enabled_raw = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="enabled",
        env_var="SECRET__PROTONMAIL__ENABLED",
        default="false",
    )
    if not _is_enabled_flag(enabled_raw):
        return False

    required_fields = [
        ("bridge_host", "SECRET__PROTONMAIL__BRIDGE_HOST"),
        ("bridge_imap_port", "SECRET__PROTONMAIL__BRIDGE_IMAP_PORT"),
        ("bridge_username", "SECRET__PROTONMAIL__BRIDGE_USERNAME"),
        ("bridge_password", "SECRET__PROTONMAIL__BRIDGE_PASSWORD"),
    ]
    for key_name, env_name in required_fields:
        value = await _get_secret_or_env(
            secrets_manager=secrets_manager,
            secret_key=key_name,
            env_var=env_name,
        )
        if not value:
            return False

    allowed_email_raw = await _get_secret_or_env(
        secrets_manager=secrets_manager,
        secret_key="allowed_openmates_email",
        env_var="SECRET__PROTONMAIL__ALLOWED_OPENMATES_EMAIL",
    )
    allowed_email = _normalize_email(allowed_email_raw)
    if not allowed_email:
        return False

    if not current_user.encrypted_email_address or not current_user.vault_key_id:
        return False

    try:
        decrypted_email = await encryption_service.decrypt_with_user_key(
            current_user.encrypted_email_address,
            current_user.vault_key_id,
        )
    except Exception:
        return False

    if not decrypted_email:
        return False

    return _normalize_email(decrypted_email) == allowed_email


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
        translation_key: Translation key (e.g., "web.search")
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


class ProviderMetadataItem(BaseModel):
    """Public provider details needed by native Apps settings."""

    id: str
    name: str
    description: str = ""
    logo_svg: Optional[str] = None
    country: Optional[str] = None
    privacy_policy: Optional[str] = None


class ModelMetadataItem(BaseModel):
    """Public model details for a specific app skill."""

    id: str
    name: str
    description: str = ""
    provider_id: str
    provider_name: str
    pricing: Optional[Dict[str, Any]] = None


class MemoryMetadataItem(BaseModel):
    """Browsable memory category metadata; user entries are never included."""

    id: str
    name: str
    description: str
    icon_image: Optional[str] = None
    type: str = ""
    example_translation_keys: List[str] = Field(default_factory=list)


class ContentMetadataItem(BaseModel):
    """Browsable durable content metadata from the shared embed catalog source."""

    id: str
    content_type_id: str
    frontend_type: str
    backend_type: str
    skill_id: Optional[str] = None
    name: str
    description: str
    icon: Optional[str] = None
    example_key: str
    order: int = 0


class AppMetadataItem(BaseModel):
    """Individual app metadata item.
    
    All translations are resolved to actual strings (defaults to English).
    Translation keys are not included in the response.
    """
    id: str
    name: str  # Resolved translation string for app name
    description: str  # Resolved translation string for app description
    category: Optional[str] = None
    icon_image: Optional[str] = None
    providers: List[ProviderMetadataItem] = Field(default_factory=list)
    provider_display_order: List[str] = Field(default_factory=list)
    last_updated: Optional[str] = None
    skills: List[SkillMetadataItem]
    focus_modes: List[FocusModeMetadataItem] = Field(default_factory=list)
    settings_and_memories: List[MemoryMetadataItem] = Field(default_factory=list)
    content_types: List[ContentMetadataItem] = Field(default_factory=list)


class SkillMetadataItem(BaseModel):
    """Skill metadata for API response.
    
    Includes resolved translation strings, not translation keys.
    """
    id: str
    name: str  # Resolved translation string for skill name
    description: str  # Resolved translation string for skill description
    icon_image: Optional[str] = None
    pricing: Optional[Dict[str, Any]] = None
    providers: Optional[List[ProviderRef]] = None
    provider_details: List[ProviderMetadataItem] = Field(default_factory=list)
    models: List[ModelMetadataItem] = Field(default_factory=list)
    how_to_use: List[str] = Field(default_factory=list)


class FocusModeMetadataItem(BaseModel):
    """Focus mode metadata for API response.
    
    Includes resolved translation strings, not translation keys.
    """
    id: str
    name: str  # Resolved translation string for focus mode name
    description: str  # Resolved translation string for focus mode description
    icon_image: Optional[str] = None
    process: List[str] = Field(default_factory=list)
    system_prompt: Optional[str] = None
    how_to_use: List[str] = Field(default_factory=list)


def _provider_metadata(
    *,
    provider_name: str,
    display_name: Optional[str],
    app_id: str,
    provider_configs: Dict[str, Dict[str, Any]],
) -> ProviderMetadataItem:
    provider_id = map_provider_name_to_id(provider_name, app_id)
    config = provider_configs.get(provider_id) or {}
    return ProviderMetadataItem(
        id=provider_id,
        name=display_name or config.get("name") or provider_name,
        description=config.get("description") or "",
        logo_svg=config.get("logo_svg"),
        country=config.get("country") or config.get("region"),
        privacy_policy=config.get("privacy_policy"),
    )


def _skill_models(
    *,
    app_id: str,
    skill_id: str,
    provider_configs: Dict[str, Dict[str, Any]],
    available_provider_ids: Optional[set[str]] = None,
) -> List[ModelMetadataItem]:
    skill_key = f"{app_id}.{skill_id}"
    models: List[ModelMetadataItem] = []
    for provider_id, provider in provider_configs.items():
        for model in provider.get("models", []):
            if not isinstance(model, dict) or model.get("for_app_skill") != skill_key:
                continue
            model_id = model.get("id")
            if not model_id:
                continue
            if available_provider_ids is not None and _model_server_ids(provider_id, model).isdisjoint(available_provider_ids):
                continue
            models.append(ModelMetadataItem(
                id=model_id,
                name=model.get("name") or model_id,
                description=model.get("description") or "",
                provider_id=provider_id,
                provider_name=provider.get("name") or provider_id,
                pricing=model.get("pricing"),
            ))
    return sorted(models, key=lambda model: (model.provider_name.lower(), model.name.lower()))


def _skill_pricing(
    *,
    skill: AppSkillDefinition,
    app_id: str,
    provider_configs: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if skill.pricing:
        return skill.pricing.model_dump(exclude_none=True)
    for provider in skill.providers or []:
        provider_id = map_provider_name_to_id(provider.name, app_id)
        pricing = (provider_configs.get(provider_id) or {}).get("pricing")
        if not isinstance(pricing, dict):
            continue
        if pricing.get("per_request_credits") is not None:
            return {"fixed": pricing["per_request_credits"]}
        public_pricing = {
            key: pricing[key]
            for key in ("tokens", "per_unit", "per_minute", "per_second", "fixed")
            if pricing.get(key) is not None
        }
        if public_pricing:
            return public_pricing
    return None


def _translated_examples(
    *,
    translation_service: Any,
    base_key: str,
    namespace: str,
) -> List[str]:
    examples: List[str] = []
    for index in range(1, 4):
        key = f"{base_key}.how_to_use.{index}"
        translated = resolve_translation(translation_service, key, namespace=namespace, fallback=key)
        if translated not in {key, f"{namespace}.{key}"}:
            examples.append(translated)
    return examples


def build_app_metadata_item(
    *,
    app_id: str,
    app_metadata: AppYAML,
    translation_service: Any,
    provider_configs: Dict[str, Dict[str, Any]],
    available_provider_ids: Optional[set[str]] = None,
) -> AppMetadataItem:
    """Build the shared rich metadata contract consumed by web-adjacent clients."""
    resolved_name = resolve_translation(
        translation_service, app_metadata.name_translation_key, namespace="apps", fallback=app_id
    )
    resolved_description = resolve_translation(
        translation_service, app_metadata.description_translation_key, namespace="apps", fallback=""
    )

    skills: List[SkillMetadataItem] = []
    app_provider_names: List[str] = []
    for skill in app_metadata.skills:
        provider_refs = skill.providers or []
        available_provider_refs = [
            provider
            for provider in provider_refs
            if available_provider_ids is None
            or provider.no_api_key
            or map_provider_name_to_id(provider.name, app_id) in available_provider_ids
        ]
        provider_details = [
            _provider_metadata(
                provider_name=provider.name,
                display_name=provider.display_name,
                app_id=app_id,
                provider_configs=provider_configs,
            )
            for provider in available_provider_refs
        ]
        app_provider_names.extend(provider.name for provider in provider_details)
        skills.append(SkillMetadataItem(
            id=skill.id,
            name=resolve_translation(
                translation_service, skill.name_translation_key, namespace="app_skills", fallback=skill.id
            ),
            description=resolve_translation(
                translation_service, skill.description_translation_key, namespace="app_skills", fallback=""
            ),
            icon_image=skill.icon_image,
            pricing=_skill_pricing(
                skill=skill,
                app_id=app_id,
                provider_configs=provider_configs,
            ),
            providers=available_provider_refs,
            provider_details=provider_details,
            models=_skill_models(
                app_id=app_id,
                skill_id=skill.id,
                provider_configs=provider_configs,
                available_provider_ids=available_provider_ids,
            ),
            how_to_use=_translated_examples(
                translation_service=translation_service,
                base_key=skill.name_translation_key,
                namespace="app_skills",
            ),
        ))

    focus_modes: List[FocusModeMetadataItem] = []
    for focus in app_metadata.focuses:
        process = focus.process or []
        if not process and focus.process_translation_key:
            process_text = resolve_translation(
                translation_service,
                focus.process_translation_key,
                namespace="focus_modes",
                fallback=focus.process_translation_key,
            )
            if process_text not in {focus.process_translation_key, f"focus_modes.{focus.process_translation_key}"}:
                process = [
                    line.removeprefix("- ").strip()
                    for line in process_text.splitlines()
                    if line.strip().startswith("- ")
                ]
        system_prompt = focus.system_prompt
        if not system_prompt and focus.systemprompt_translation_key:
            translated_prompt = resolve_translation(
                translation_service,
                focus.systemprompt_translation_key,
                namespace="focus_modes",
                fallback=focus.systemprompt_translation_key,
            )
            if translated_prompt not in {
                focus.systemprompt_translation_key,
                f"focus_modes.{focus.systemprompt_translation_key}",
            }:
                system_prompt = translated_prompt
        focus_modes.append(FocusModeMetadataItem(
            id=focus.id,
            name=resolve_translation(
                translation_service, focus.name_translation_key, namespace="app_focus_modes", fallback=focus.id
            ),
            description=resolve_translation(
                translation_service, focus.description_translation_key, namespace="app_focus_modes", fallback=""
            ),
            icon_image=focus.icon_image,
            process=process,
            system_prompt=system_prompt,
            how_to_use=focus.how_to_use or _translated_examples(
                translation_service=translation_service,
                base_key=focus.name_translation_key,
                namespace="app_focus_modes",
            ),
        ))

    memories = [
        MemoryMetadataItem(
            id=field.id,
            name=resolve_translation(
                translation_service,
                field.name_translation_key,
                namespace="app_settings_memories",
                fallback=field.id,
            ),
            description=resolve_translation(
                translation_service,
                field.description_translation_key,
                namespace="app_settings_memories",
                fallback="",
            ),
            icon_image=field.icon_image,
            type=field.type,
            example_translation_keys=field.example_translation_keys or [],
        )
        for field in app_metadata.memory_fields
    ]

    content_types: List[ContentMetadataItem] = []
    for embed in app_metadata.embed_types:
        catalog = embed.content_catalog or {}
        if catalog.get("enabled") is not True:
            continue
        content_type_id = catalog.get("content_type_id") or embed.id
        content_types.append(ContentMetadataItem(
            id=f"{app_id}.{content_type_id}",
            content_type_id=content_type_id,
            frontend_type=embed.frontend_type,
            backend_type=embed.backend_type,
            skill_id=embed.skill_id,
            name=catalog.get("name") or content_type_id,
            description=catalog.get("description") or "",
            icon=catalog.get("icon") or embed.icon,
            example_key=catalog.get("example_key") or f"{app_id}.{content_type_id}",
            order=int(catalog.get("order") or 0),
        ))

    ordered_provider_names = list(dict.fromkeys(
        (app_metadata.provider_display_order or []) + app_provider_names
    ))
    providers_by_name = {
        provider.name: provider
        for skill in skills
        for provider in skill.provider_details
    }
    return AppMetadataItem(
        id=app_id,
        name=resolved_name,
        description=resolved_description,
        category=app_metadata.category,
        icon_image=app_metadata.icon_image.strip() if app_metadata.icon_image else None,
        providers=[providers_by_name[name] for name in ordered_provider_names if name in providers_by_name],
        provider_display_order=ordered_provider_names,
        last_updated=app_metadata.last_updated,
        skills=skills,
        focus_modes=focus_modes,
        settings_and_memories=memories,
        content_types=sorted(content_types, key=lambda content: (content.order, content.name.lower())),
    )


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
async def get_apps_metadata(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    include_unavailable: bool = False,
):
    """
    Get metadata for all discovered apps.
    
    Returns the metadata that each app's Docker container registered during startup.
    Each app exposes a /metadata endpoint that returns its AppYAML configuration.
    The core API discovers these during startup and stores them in app.state.discovered_apps_metadata.
    
    Feature availability and implementation filtering happen during app discovery.
    
    If an app is missing, it means either:
    - The app container is not running
    - The app's /metadata endpoint is not responding
    - The app is disabled by feature availability or has no implemented components
    
    **Implementation**: 
    - App discovery: `backend/core/api/main.py:discover_apps()` 
    - App metadata endpoint: `backend/apps/base_app.py:_register_default_routes()` -> `/metadata`
    - App metadata schemas: `backend/shared/python_schemas/app_metadata_schemas.py`
    
    **Reference**: 
    - Apps UI: `frontend/packages/ui/src/components/settings/SettingsAppStore.svelte`
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
    
    # Get cache service for secrets manager
    cache_service = None
    if hasattr(request.app.state, 'cache_service'):
        cache_service = request.app.state.cache_service
    
    # Initialize secrets manager for API key availability checks
    secrets_manager = SecretsManager(cache_service=cache_service)
    await secrets_manager.initialize()

    protonmail_user_allowed = await _is_protonmail_user_allowed(
        current_user=current_user,
        encryption_service=encryption_service,
        secrets_manager=secrets_manager,
    )

    config_manager = getattr(request.app.state, "config_manager", None)
    provider_configs = (
        config_manager.get_provider_configs()
        if isinstance(config_manager, ConfigManager)
        else {}
    )
    if config_manager is None:
        logger.warning("ConfigManager not found in app.state - provider and model details will be empty")
    available_provider_ids = None if include_unavailable else await _available_provider_ids(
        provider_configs=provider_configs,
        secrets_manager=secrets_manager,
    )
    
    # Convert AppYAML to API response format
    # Transform the discovered AppYAML objects to the API response format with resolved translations
    apps_metadata: Dict[str, AppMetadataItem] = {}
    
    for app_id, app_metadata in discovered_apps.items():
        # Log what we're processing for debugging
        logger.info(f"Processing app '{app_id}': {len(app_metadata.skills)} skills, {len(app_metadata.focuses)} focus modes, {len(app_metadata.memory_fields) if app_metadata.memory_fields else 0} memory fields")
        
        if not app_metadata.description_translation_key:
            logger.error(f"App '{app_id}' is missing required description_translation_key, skipping")
            continue

        available_skill_ids: set[str] = set()
        for skill in app_metadata.skills:
            if skill.internal:
                continue
            # Check if skill is available based on API key configuration.
            # When include_unavailable=True (used by CLI to match the web app's
            # build-time static metadata), skip provider availability checks so
            # all discovered skills are returned regardless of API keys.
            if not include_unavailable:
                skill_available = await is_skill_available(skill, app_id, secrets_manager, cache_service)
                if not skill_available:
                    logger.debug(f"Skipping skill '{skill.id}' from app '{app_id}' - no API keys configured for providers")
                    continue

                if not skill.providers and _skill_models(
                    app_id=app_id,
                    skill_id=skill.id,
                    provider_configs=provider_configs,
                ) and not _skill_models(
                    app_id=app_id,
                    skill_id=skill.id,
                    provider_configs=provider_configs,
                    available_provider_ids=available_provider_ids,
                ):
                    logger.debug(f"Skipping skill '{skill.id}' from app '{app_id}' - no configured model providers")
                    continue

                # Proton Mail Bridge is intentionally single-account: only the explicitly
                # configured OpenMates user should see and execute the mail.search skill.
                if app_id == "mail" and skill.id == "search" and not protonmail_user_allowed:
                    logger.debug("Skipping mail/search skill for current user (not ProtonMail-allowed)")
                    continue
            
            available_skill_ids.add(skill.id)

        item = build_app_metadata_item(
            app_id=app_id,
            app_metadata=app_metadata,
            translation_service=translation_service,
            provider_configs=provider_configs,
            available_provider_ids=available_provider_ids,
        )
        item.skills = [skill for skill in item.skills if skill.id in available_skill_ids]

        # Only include app if it has at least one valid component (skill, focus mode, or memory field)
        if item.skills or item.focus_modes or item.settings_and_memories or item.content_types:
            apps_metadata[app_id] = item
        else:
            logger.debug(f"Skipping app '{app_id}' - no available components after provider and permission checks")
    
    logger.info(f"Returning metadata for {len(apps_metadata)} apps")
    return AppMetadataResponse(apps=apps_metadata)


@router.get("/{app_id}/metadata")
async def get_app_metadata(app_id: str, request: Request, include_unavailable: bool = False):
    """
    Get metadata for a specific app.
    
    Feature availability and implementation filtering happen during app discovery.
    
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
    
    # Get cache service for secrets manager
    cache_service = None
    if hasattr(request.app.state, 'cache_service'):
        cache_service = request.app.state.cache_service
    
    # Initialize secrets manager for API key availability checks
    secrets_manager = SecretsManager(cache_service=cache_service)
    await secrets_manager.initialize()
    
    config_manager = getattr(request.app.state, "config_manager", None)
    provider_configs = (
        config_manager.get_provider_configs()
        if isinstance(config_manager, ConfigManager)
        else {}
    )
    available_provider_ids = None if include_unavailable else await _available_provider_ids(
        provider_configs=provider_configs,
        secrets_manager=secrets_manager,
    )

    available_skill_ids: set[str] = set()
    for skill in app_metadata.skills:
        if not include_unavailable:
            skill_available = await is_skill_available(skill, app_id, secrets_manager)
            if not skill_available:
                logger.debug(f"Skipping skill '{skill.id}' from app '{app_id}' - no API keys configured for providers")
                continue
        available_skill_ids.add(skill.id)

    item = build_app_metadata_item(
        app_id=app_id,
        app_metadata=app_metadata,
        translation_service=translation_service,
        provider_configs=provider_configs,
        available_provider_ids=available_provider_ids,
    )
    item.skills = [skill for skill in item.skills if skill.id in available_skill_ids]
    return item


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
    Used by Apps to display "Most used" section.
    
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
