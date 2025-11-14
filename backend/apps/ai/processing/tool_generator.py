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
    
    # Try to extract parameters schema from skill class
    parameters_schema = _extract_skill_parameters_schema(skill_def)
    
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
    Attempts to extract parameter schema from the skill class's execute method.
    If the skill class has a Pydantic model for its request, use that.
    Otherwise, returns a generic schema.
    
    Args:
        skill_def: The skill definition containing class_path
    
    Returns:
        JSON schema dict for the skill's parameters
    """
    try:
        # Parse the class path
        module_path, class_name = skill_def.class_path.rsplit('.', 1)
        
        # Import the module and get the class
        module = importlib.import_module(module_path)
        skill_class = getattr(module, class_name)
        
        # Check if the execute method has type hints
        if hasattr(skill_class, 'execute'):
            execute_method = getattr(skill_class, 'execute')
            sig = inspect.signature(execute_method)
            
            # Look for a Pydantic BaseModel parameter (excluding self)
            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue
                
                param_type = param.annotation
                
                # Check if it's a Pydantic BaseModel
                if inspect.isclass(param_type) and issubclass(param_type, BaseModel):
                    # Convert Pydantic model to JSON schema
                    try:
                        json_schema = param_type.model_json_schema()
                        # Remove title and description from root if present (OpenAI format doesn't need them)
                        json_schema.pop('title', None)
                        json_schema.pop('description', None)
                        logger.debug(f"Extracted parameter schema from Pydantic model for skill '{skill_def.id}': {param_type.__name__}")
                        return json_schema
                    except Exception as e:
                        logger.warning(f"Failed to convert Pydantic model to JSON schema for skill '{skill_def.id}': {e}")
                        break
        
        logger.debug(f"Could not find Pydantic model parameter in execute method for skill '{skill_def.id}', using generic schema")
    except Exception as e:
        logger.warning(f"Error extracting parameter schema from skill class '{skill_def.class_path}': {e}")
    
    # Fallback to generic schema
    # This allows any object with any properties
    return {
        "type": "object",
        "properties": {},
        "additionalProperties": True
    }


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
    
    logger.info(f"Generated {len(tools)} tool definitions from {len(apps_to_process)} apps")
    return tools

