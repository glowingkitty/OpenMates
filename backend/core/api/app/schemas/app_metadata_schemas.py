# backend/core/api/app/schemas/app_metadata_schemas.py
#
# This module defines Pydantic models related to application metadata,
# primarily for parsing app.yml configurations and for service discovery.
# These models are used by the main API service to understand the structure
# of metadata provided by individual app services.

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, validator, Field

class IconColorGradient(BaseModel):
    """Defines the start and end colors for an icon gradient."""
    start: str = Field(..., pattern=r'^#[0-9a-fA-F]{6}$') # Validate as hex color
    end: str = Field(..., pattern=r'^#[0-9a-fA-F]{6}$')   # Validate as hex color

class AppPricing(BaseModel):
    """Defines pricing structure for a skill if it's self-contained."""
    tokens: Optional[Dict[str, Dict[str, int]]] = None # e.g., {"input": {"per_credit_unit": 1000}}
    per_unit: Optional[Dict[str, Any]] = None # e.g., {"credits": 1, "unit_name": "image"}
    per_minute: Optional[int] = None # credits per minute
    fixed: Optional[int] = None # fixed credits per call

class AppSkillDefinition(BaseModel):
    """Defines the structure for a skill within an app's metadata."""
    id: str
    name: str
    description: str
    class_path: str # e.g., "apps.ai.skills.ask_skill.AskSkill"
    stage: str = Field(default="development", pattern="^(development|production)$")
    pricing: Optional[AppPricing] = None
    default_config: Optional[Dict[str, Any]] = None

class AppFocusDefinition(BaseModel):
    """Defines the structure for a focus mode within an app's metadata."""
    id: str
    name: str
    description: str
    system_prompt: str = Field(alias="systemprompt") # Allow 'systemprompt' in YAML

class AppMemoryFieldDefinition(BaseModel):
    """Defines the structure for a memory field within an app's metadata."""
    id: str
    name: str
    description: str
    type: str # e.g., "string", "number", "boolean", "json_object", "list_of_strings"
    schema_definition: Optional[Dict[str, Any]] = Field(default=None, alias="schema") # Optional JSON schema

class AppYAML(BaseModel):
    """
    Pydantic model representing the structure of an app.yml file.
    This is used for validating app configurations and for service discovery.
    """
    id: Optional[str] = None # Made id optional, will be derived if not present
    name: str
    description: str
    icon_image: Optional[str] = Field(default=None, pattern=r'.+\.svg$') # Filename ending with .svg
    icon_colorgradient: Optional[IconColorGradient] = None
    skills: List[AppSkillDefinition] = []
    focuses: List[AppFocusDefinition] = Field(default=[], alias="focus_modes") # Allow 'focus_modes' as alias
    memory_fields: List[AppMemoryFieldDefinition] = Field(default=[], alias="memory") # Allow 'memory' as alias

    @validator('focuses', pre=True, always=True)
    def set_focuses_default(cls, v, values):
        """Ensures focuses list is initialized even if 'focus_modes' is missing or None."""
        return v if v is not None else values.get('focus_modes', [])

    @validator('memory_fields', pre=True, always=True)
    def set_memory_fields_default(cls, v, values):
        """Ensures memory_fields list is initialized even if 'memory' is missing or None."""
        return v if v is not None else values.get('memory', [])
    
    class Config:
        validate_by_name = True # Allows using 'system_prompt' for 'systemprompt' etc.