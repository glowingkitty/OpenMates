# backend/apps/ai/processing/tool_generator.py
# 
# Tool definition generator for converting app skills to LLM tool definitions.
# This module handles the conversion of AppSkillDefinition from app.yml files
# into OpenAI function calling format tool definitions.

import logging
import os
import copy
from typing import Dict, Any, List, Optional, Set, TYPE_CHECKING
import importlib
import inspect
from pydantic import BaseModel

from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition

# Type checking import to avoid circular dependencies
if TYPE_CHECKING:
    from backend.core.api.app.services.translations import TranslationService

logger = logging.getLogger(__name__)


def _resolve_translation(
    translation_service: Optional["TranslationService"],
    translation_key: str,
    namespace: str,
    fallback: str = ""
) -> str:
    """
    Resolve a translation key to its translated string value.
    
    This function is similar to resolve_translation in apps.py but kept here
    to avoid circular dependencies. It resolves translation keys for skill descriptions
    that are used in LLM tool definitions.
    
    Args:
        translation_service: TranslationService instance (can be None)
        translation_key: Translation key (e.g., "web.search.text")
        namespace: Namespace prefix (e.g., "app_skills")
        fallback: Fallback value if translation not found
    
    Returns:
        Resolved translation string or fallback
    """
    if not translation_service:
        logger.debug(f"TranslationService not available, using fallback for key '{translation_key}'")
        return fallback or translation_key
    
    # Normalize translation key: ensure it has namespace prefix if needed
    full_key = translation_key
    if not full_key.startswith(f"{namespace}."):
        full_key = f"{namespace}.{full_key}"
    
    try:
        # Get the full translation structure (defaults to English)
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


def skill_definition_to_tool_definition(
    app_id: str,
    skill_def: AppSkillDefinition,
    preselected_skills: Optional[Set[str]] = None,
    translation_service: Optional["TranslationService"] = None
) -> Optional[Dict[str, Any]]:
    """
    Converts an AppSkillDefinition to an LLM tool definition in OpenAI function calling format.
    
    Args:
        app_id: The ID of the app that owns this skill
        skill_def: The skill definition from app.yml
        preselected_skills: Optional set of preselected skill identifiers in format "app_id-skill_id"
                          If provided, only skills in this set will be included
        translation_service: Optional TranslationService instance for resolving skill descriptions
                            from translation keys. If not provided, will use fallback values.
    
    Returns:
        Tool definition dict in OpenAI function calling format, or None if skill should be excluded
    """
    # Exclude ai.ask from tool generation - it's the main processing entry point, not a tool
    if app_id == "ai" and skill_def.id == "ask":
        logger.debug(f"Skipping skill '{skill_def.id}' from app '{app_id}' - this is the main processing entry point, not a tool")
        return None
    
    # Filter skills by stage based on SERVER_ENVIRONMENT
    # Development: Include both "development" and "production" stage skills
    # Production: Only include "production" stage skills
    server_environment = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    
    if server_environment == "production":
        # Production server: Only include production-stage skills
        if skill_def.stage != "production":
            logger.debug(f"Skipping skill '{skill_def.id}' from app '{app_id}' - stage is '{skill_def.stage}', but production server requires 'production' stage")
            return None
    else:
        # Development server: Include both development and production stage skills
        # Only exclude planning stage (or invalid stages)
        if skill_def.stage not in ["development", "production"]:
            logger.debug(f"Skipping skill '{skill_def.id}' from app '{app_id}' - stage is '{skill_def.stage}', not 'development' or 'production'")
            return None
    
    # Check preselection filter (architecture: only preselected skills are forwarded)
    # Use hyphen separator for LLM provider compatibility (Cerebras and others don't allow dots in function names)
    skill_identifier = f"{app_id}-{skill_def.id}"
    # preselected_skills can be:
    # - None: Should not occur (error case), but we'll treat as empty set (no skills)
    # - Empty set: No skills preselected (valid - means no tools should be provided)
    # - Non-empty set: Only skills in this set should be included
    if preselected_skills is None:
        # None should not occur - this is an error case
        # Architecture violation: we should always have preselected_skills (even if empty)
        logger.warning(f"preselected_skills is None for skill '{skill_def.id}' from app '{app_id}' - this violates architecture. Treating as empty set (no skills).")
        return None  # Exclude all skills when None (error case)
    elif skill_identifier not in preselected_skills:
        # Skill not in preselected set - exclude it (architecture: only preselected skills are forwarded)
        logger.debug(f"Skipping skill '{skill_def.id}' from app '{app_id}' - not in preselected skills")
        return None
    
    # Generate tool name in format: {app_id}-{skill_id} (using hyphen for LLM provider compatibility)
    tool_name = skill_identifier
    
    # Extract parameters schema from skill's tool_schema field
    try:
        parameters_schema = _extract_skill_parameters_schema(skill_def)
    except (ValueError, KeyError) as e:
        logger.error(f"Failed to extract tool schema for skill '{skill_def.id}': {e}")
        return None  # Skip this skill if schema is invalid
    
    # Log the schema for debugging
    schema_properties = parameters_schema.get("properties", {})
    if schema_properties:
        param_names = list(schema_properties.keys())
        required_fields = parameters_schema.get("required", [])
        logger.info(
            f"Generated tool definition for '{tool_name}' with {len(param_names)} parameters: {', '.join(param_names)}"
            + (f" (required: {', '.join(required_fields)})" if required_fields else "")
        )
    else:
        logger.warning(f"Generated tool definition for '{tool_name}' with no properties in schema")
    
    # Resolve skill description from translation key
    # AppSkillDefinition uses description_translation_key, not description
    skill_description = ""
    if skill_def.description_translation_key:
        skill_description = _resolve_translation(
            translation_service=translation_service,
            translation_key=skill_def.description_translation_key,
            namespace="app_skills",
            fallback=f"Skill {skill_def.id} from app {app_id}"
        )
    else:
        logger.warning(f"Skill '{skill_def.id}' from app '{app_id}' is missing description_translation_key, using fallback")
        skill_description = f"Skill {skill_def.id} from app {app_id}"
    
    # Create tool definition in OpenAI function calling format
    tool_definition = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": skill_description,
            "parameters": parameters_schema
        }
    }
    
    logger.debug(f"Generated tool definition for '{tool_name}': {tool_definition['function']['name']}")
    return tool_definition


def _extract_skill_parameters_schema(skill_def: AppSkillDefinition) -> Dict[str, Any]:
    """
    Extracts parameter schema from the skill's tool_schema field in app.yml.
    
    Skills used as tools must define tool_schema in their app.yml file.
    Entry-point skills (like ai.ask) don't need tool_schema.
    
    This function automatically injects the 'id' field into any schema that has a
    'requests' array with object items, ensuring consistency across all skills that
    support multiple requests per call.
    
    Args:
        skill_def: The skill definition containing tool_schema
    
    Returns:
        JSON schema dict for the skill's parameters (with 'id' field automatically injected if needed)
    
    Raises:
        ValueError: If tool_schema is missing or invalid (for skills that should have it)
    """
    if not skill_def.tool_schema:
        error_msg = f"Skill '{skill_def.id}' is missing required 'tool_schema' field in app.yml. All skills used as tools must define tool_schema."
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Validate it's a proper JSON schema
    if not isinstance(skill_def.tool_schema, dict):
        error_msg = f"Skill '{skill_def.id}' has invalid tool_schema (must be a dict)"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    # Validate it has a type field (standard JSON Schema requirement)
    if "type" not in skill_def.tool_schema:
        logger.warning(f"Skill '{skill_def.id}' tool_schema missing 'type' field, assuming 'object'")
        # Don't fail, but log warning - some schemas might be valid without explicit type
    
    # Deep copy the schema to avoid mutating the original
    schema = copy.deepcopy(skill_def.tool_schema)
    
    # Automatically inject 'id' field into schemas with 'requests' arrays
    # This ensures all skills that support multiple requests have consistent 'id' field definitions
    schema = _inject_id_field_if_needed(schema, skill_def.id)
    
    logger.debug(f"Using tool_schema from app.yml for skill '{skill_def.id}' (with automatic 'id' field injection if needed)")
    return schema


def _inject_id_field_if_needed(schema: Dict[str, Any], skill_id: str) -> Dict[str, Any]:
    """
    Automatically injects the 'id' field into tool schemas that have a 'requests' array.
    
    All skills that support multiple requests per call (via a 'requests' array) need
    an 'id' field in each request object to match responses to requests. This function
    ensures the 'id' field is automatically added to the schema if it's missing.
    
    The 'id' field is defined as:
    - Type: string or integer (supports both numbers and UUID strings)
    - Description: Unique identifier for matching responses to requests
    - Required: Only for multi-request calls (single requests auto-generate id=1)
    
    Args:
        schema: The tool schema dictionary (will be modified in place)
        skill_id: The skill ID (for logging purposes)
    
    Returns:
        The schema dictionary with 'id' field injected if needed
    """
    # Check if schema has a 'requests' property
    properties = schema.get("properties", {})
    requests_prop = properties.get("requests")
    
    if not requests_prop:
        # No 'requests' property - nothing to inject
        return schema
    
    # Check if 'requests' is an array type
    if requests_prop.get("type") != "array":
        # 'requests' exists but is not an array - nothing to inject
        return schema
    
    # Check if array has 'items' that is an object
    items = requests_prop.get("items")
    if not items or items.get("type") != "object":
        # 'requests' array doesn't have object items - nothing to inject
        return schema
    
    # Check if 'id' field already exists in items properties
    items_properties = items.get("properties", {})
    if "id" in items_properties:
        # 'id' field already exists - don't override it (allows skills to customize if needed)
        logger.debug(f"Skill '{skill_id}' already has 'id' field in requests items - keeping existing definition")
        return schema
    
    # Inject 'id' field into items properties
    # This matches the definition from web/app.yml but is now automatically added
    items_properties["id"] = {
        "type": ["string", "integer"],
        "description": "Unique identifier for this request (number or UUID string). Must be unique within a single skill call. For single requests, this is optional and will default to 1. For multiple requests, this is required to match responses to requests."
    }
    
    # Ensure 'properties' dict exists in items
    if "properties" not in items:
        items["properties"] = items_properties
    else:
        items["properties"] = items_properties
    
    # Update the schema with modified items
    requests_prop["items"] = items
    properties["requests"] = requests_prop
    schema["properties"] = properties
    
    logger.debug(f"Injected 'id' field into requests items for skill '{skill_id}'")
    return schema


def generate_tools_from_apps(
    discovered_apps_metadata: Dict[str, AppYAML],
    assigned_app_ids: Optional[List[str]] = None,
    preselected_skills: Optional[Set[str]] = None,
    translation_service: Optional["TranslationService"] = None
) -> List[Dict[str, Any]]:
    """
    Generates tool definitions from discovered apps metadata.
    
    Args:
        discovered_apps_metadata: Dict mapping app_id to AppYAML metadata
        assigned_app_ids: Optional list of app IDs to include (if None, includes all apps)
        preselected_skills: Optional set of preselected skill identifiers in format "app_id-skill_id"
        translation_service: Optional TranslationService instance for resolving skill descriptions
                            from translation keys. If not provided, will use fallback values.
    
    Returns:
        List of tool definitions in OpenAI function calling format
    """
    tools: List[Dict[str, Any]] = []
    
    # Determine which apps to process
    apps_to_process = assigned_app_ids if assigned_app_ids else list(discovered_apps_metadata.keys())
    
    for app_id in apps_to_process:
        app_metadata = discovered_apps_metadata.get(app_id)
        if not app_metadata or not app_metadata.skills:
            continue
        
        logger.debug(f"Processing {len(app_metadata.skills)} skills from app '{app_id}'")
        
        for skill_def in app_metadata.skills:
            tool_def = skill_definition_to_tool_definition(
                app_id=app_id,
                skill_def=skill_def,
                preselected_skills=preselected_skills,
                translation_service=translation_service
            )
            
            if tool_def:
                tools.append(tool_def)
    
    # Log available skills for debugging
    skill_names = [tool["function"]["name"] for tool in tools]
    logger.info(f"Generated {len(tools)} tool definitions from {len(apps_to_process)} apps")
    logger.info(f"Available skills for LLM: {', '.join(skill_names) if skill_names else 'None'}")
    return tools

