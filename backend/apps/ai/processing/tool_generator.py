# backend/apps/ai/processing/tool_generator.py
# 
# Tool definition generator for converting app skills to LLM tool definitions.
# This module handles the conversion of AppSkillDefinition from app.yml files
# into OpenAI function calling format tool definitions.

import logging
import os
from typing import Dict, Any, List, Optional, Set
import importlib
import inspect
from pydantic import BaseModel

from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition

logger = logging.getLogger(__name__)


def skill_definition_to_tool_definition(
    app_id: str,
    skill_def: AppSkillDefinition,
    preselected_skills: Optional[Set[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Converts an AppSkillDefinition to an LLM tool definition in OpenAI function calling format.
    
    Args:
        app_id: The ID of the app that owns this skill
        skill_def: The skill definition from app.yml
        preselected_skills: Optional set of preselected skill identifiers in format "app_id.skill_id"
                          If provided, only skills in this set will be included
    
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
    
    # Check preselection filter if provided
    skill_identifier = f"{app_id}.{skill_def.id}"
    if preselected_skills is not None and skill_identifier not in preselected_skills:
        logger.debug(f"Skipping skill '{skill_def.id}' from app '{app_id}' - not in preselected skills")
        return None
    
    # Generate tool name in format: {app_id}.{skill_id}
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
    
    # Create tool definition in OpenAI function calling format
    tool_definition = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": skill_def.description,
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
    
    Args:
        skill_def: The skill definition containing tool_schema
    
    Returns:
        JSON schema dict for the skill's parameters
    
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
    
    logger.debug(f"Using tool_schema from app.yml for skill '{skill_def.id}'")
    return skill_def.tool_schema


def generate_tools_from_apps(
    discovered_apps_metadata: Dict[str, AppYAML],
    assigned_app_ids: Optional[List[str]] = None,
    preselected_skills: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Generates tool definitions from discovered apps metadata.
    
    Args:
        discovered_apps_metadata: Dict mapping app_id to AppYAML metadata
        assigned_app_ids: Optional list of app IDs to include (if None, includes all apps)
        preselected_skills: Optional set of preselected skill identifiers in format "app_id.skill_id"
    
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
                preselected_skills=preselected_skills
            )
            
            if tool_def:
                tools.append(tool_def)
    
    # Log available skills for debugging
    skill_names = [tool["function"]["name"] for tool in tools]
    logger.info(f"Generated {len(tools)} tool definitions from {len(apps_to_process)} apps")
    logger.info(f"Available skills for LLM: {', '.join(skill_names) if skill_names else 'None'}")
    return tools

