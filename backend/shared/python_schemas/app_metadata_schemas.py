# backend/shared/python_schemas/app_metadata_schemas.py
#
# This module defines Pydantic models related to application metadata,
# primarily for parsing app.yml configurations and for service discovery.
# These models are shared across different backend services.

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, field_validator, model_validator, Field, ConfigDict

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

class AppSkillApiConfig(BaseModel):
    """
    REST API configuration for a skill.
    
    Controls how the skill is exposed in the public REST API (/v1/apps/{app_id}/skills/{skill_id}).
    By default, skills expose both GET (metadata) and POST (execute) endpoints.
    Use this to restrict visibility (e.g., POST-only for write-only skills).
    """
    expose_get: bool = Field(default=True, description="Whether to expose a GET endpoint for skill metadata. Set to false for skills that should only accept POST requests (e.g., write-only anonymous data collection).")


class AppSkillDefinition(BaseModel):
    """Defines the structure for a skill within an app's metadata."""
    id: str
    name_translation_key: str  # Required: Translation key for skill name (e.g., "app_translations.web.skills.search.name")
    description_translation_key: str  # Required: Translation key for skill description (e.g., "app_translations.web.skills.search.description")
    class_path: Optional[str] = None  # e.g., "apps.ai.skills.ask_skill.AskSkill" - optional for planning stage skills
    stage: Optional[str] = Field(default="development", description="Stage of the skill: 'planning', 'development', or 'production'. Components with stage='planning' are excluded from API responses.")
    pricing: Optional[AppPricing] = None
    providers: Optional[List[str]] = None  # Optional list of provider names (e.g., ["Brave"]) - used for provider-level pricing lookup
    full_model_reference: Optional[str] = Field(default=None, description="Optional full model reference (e.g., 'google/gemini-3-pro-image-preview') used for model-specific pricing.")
    default_config: Optional[Dict[str, Any]] = Field(default=None, alias="skill_config")
    tool_schema: Optional[Dict[str, Any]] = None  # Optional: Tool schema in JSON Schema format for function calling (required for skills used as tools, optional for entry-point skills like ai.ask)
    # Fields to exclude from LLM inference (but keep in full results for UI rendering)
    # Supports dot notation for nested fields (e.g., "meta_url.favicon", "thumbnail.original")
    exclude_fields_for_llm: Optional[List[str]] = Field(default=None, description="List of field paths to exclude from LLM inference. Full data is kept in chat history for UI rendering.")
    # Brief LLM-facing hint for the preprocessor describing when to select this skill.
    # Included alongside the skill identifier in the preprocessing prompt so the LLM can
    # make informed skill selection decisions without hardcoded guidance in base_instructions.yml.
    preprocessor_hint: Optional[str] = Field(default=None, description="Brief hint for the preprocessing LLM describing when to select this skill (1-3 sentences).")
    # REST API configuration — controls how the skill is exposed in the public API docs
    api_config: Optional[AppSkillApiConfig] = Field(default=None, description="REST API configuration for this skill. Controls GET/POST endpoint exposure in /docs.")

class AppFocusDefinition(BaseModel):
    """Defines the structure for a focus mode within an app's metadata."""
    id: str
    name_translation_key: str  # Required: Translation key for focus mode name (e.g., "app_translations.web.focus_modes.research.name")
    description_translation_key: str  # Required: Translation key for focus mode description (e.g., "app_translations.web.focus_modes.research.description")
    system_prompt: Optional[str] = Field(default=None, alias="systemprompt")  # Allow 'systemprompt' in YAML - optional for planning stage focuses
    process: Optional[List[str]] = Field(default=None, description="Optional list of process steps for the focus mode")
    stage: Optional[str] = Field(default=None, description="Stage of the focus mode: 'planning', 'development', or 'production'. Components with stage='planning' are excluded from API responses.")
    # Brief LLM-facing hint for the preprocessor describing when to select this focus mode.
    # Included alongside the focus mode identifier in the preprocessing prompt so the LLM can
    # make informed focus mode selection decisions (same pattern as skill preprocessor_hint).
    preprocessor_hint: Optional[str] = Field(default=None, description="Brief hint for the preprocessing LLM describing when to select this focus mode (1-3 sentences).")

class AppMemoryFieldDefinition(BaseModel):
    """Defines the structure for a memory field within an app's metadata."""
    id: str
    name_translation_key: str  # Required: Translation key for memory field name (e.g., "app_translations.web.settings_memories.bookmarks.name")
    description_translation_key: str  # Required: Translation key for memory field description (e.g., "app_translations.web.settings_memories.bookmarks.description")
    type: str # e.g., "string", "number", "boolean", "json_object", "list_of_strings"
    schema_definition: Optional[Dict[str, Any]] = Field(default=None, alias="schema") # Optional JSON schema
    stage: Optional[str] = Field(default=None, description="Stage of the memory field: 'planning', 'development', or 'production'. Components with stage='planning' are excluded from API responses.")

    @model_validator(mode='after')
    def inject_added_date(self):
        """
        Automatically injects 'added_date' into every settings/memories schema.
        
        added_date is a universal field that records when a user created an entry.
        It's auto_generated (hidden from UI forms, auto-populated by the client)
        and converted to human-readable format before being included in LLM prompts.
        
        This removes the need to define added_date in every app.yml file,
        preventing misconfiguration (e.g., forgetting auto_generated: true).
        """
        if self.schema_definition is not None:
            properties = self.schema_definition.get("properties", {})
            if "added_date" not in properties:
                properties["added_date"] = {
                    "type": "integer",
                    "description": "Unix timestamp when added",
                    "auto_generated": True
                }
                self.schema_definition["properties"] = properties
        return self


class AppInstructionDefinition(BaseModel):
    """
    Defines the structure for app-specific instructions that are dynamically loaded
    into the system prompt ONLY when the app is available.
    
    This prevents the AI from being instructed about capabilities that don't exist
    (e.g., instructing about web search when the web app is unavailable).
    """
    instruction: str  # The actual instruction text to inject into the system prompt
    categories: Optional[List[str]] = Field(
        default=None,
        description="Optional list of categories where this instruction is most relevant. If provided, the instruction is only injected when the conversation category matches."
    )

class AppYAML(BaseModel):
    """
    Pydantic model representing the structure of an app.yml file.
    This is used for validating app configurations and for service discovery.
    """
    id: Optional[str] = None # Made id optional, will be derived if not present
    name_translation_key: str # Translation key for app name (e.g., "app_translations.web") - required
    description_translation_key: str # Translation key for app description (e.g., "apps.web.description") - required (no backwards compatibility)
    icon_image: Optional[str] = Field(default=None, pattern=r'.+\.svg$') # Filename ending with .svg
    icon_colorgradient: Optional[IconColorGradient] = None
    skills: List[AppSkillDefinition] = []
    focuses: List[AppFocusDefinition] = Field(default=[], alias="focus_modes") # Allow 'focus_modes' as alias
    memory_fields: List[AppMemoryFieldDefinition] = Field(default=[], alias="memory") # Allow 'memory' as alias
    # App-specific instructions that are dynamically loaded into the system prompt
    # ONLY when this app is available. This prevents the AI from being instructed about
    # capabilities that don't exist (e.g., instructing about web search when web app is down)
    instructions: List[AppInstructionDefinition] = Field(default=[], description="App-specific instructions to inject into system prompt when this app is available")
    
    @model_validator(mode='after')
    def validate_description(self):
        """
        Validates that 'description_translation_key' is provided.
        No backwards compatibility - description_translation_key is required.
        """
        if not self.description_translation_key:
            raise ValueError("'description_translation_key' is required (no backwards compatibility with 'description' field)")
        
        return self

    @field_validator('focuses', mode='before')
    @classmethod
    def set_focuses_default(cls, v):
        """Ensures focuses list is initialized even if 'focus_modes' is missing or None."""
        # Return the value if it's not None, otherwise return empty list
        # The alias 'focus_modes' is handled by the Field definition
        return v if v is not None else []

    @model_validator(mode='before')
    @classmethod
    def map_aliases(cls, values):
        """
        Maps various field aliases from app.yml for compatibility.
        - Maps 'settings_and_memories' to 'memory' if 'memory'/'memory_fields' don't exist
        - Ensures 'focus_modes' is mapped to 'focuses' field
        - Ensures 'memory' is available for 'memory_fields' field
        """
        if isinstance(values, dict):
            # Map 'settings_and_memories' to 'memory' if needed
            if 'settings_and_memories' in values and 'memory_fields' not in values and 'memory' not in values:
                values['memory'] = values['settings_and_memories']
            
            # Ensure 'focus_modes' alias is handled (Pydantic will handle this via Field alias, but ensure it's present)
            if 'focus_modes' in values and 'focuses' not in values:
                # The alias will be handled by Field, but we ensure the value is there
                pass
            
            # Ensure 'memory' alias is handled for 'memory_fields'
            if 'memory' in values and 'memory_fields' not in values:
                # The alias will be handled by Field, but we ensure the value is there
                pass
        return values


    @field_validator('memory_fields', mode='before')
    @classmethod
    def set_memory_fields_default(cls, v):
        """Ensures memory_fields list is initialized even if 'memory' is missing or None."""
        # Return the value if it's not None, otherwise return empty list
        # The alias 'memory' is handled by the Field definition
        return v if v is not None else []
    
    @field_validator('instructions', mode='before')
    @classmethod
    def set_instructions_default(cls, v):
        """Ensures instructions list is initialized even if missing or None."""
        return v if v is not None else []
    
    # Pydantic v2 configuration: allows using field names and aliases interchangeably
    # This enables using 'system_prompt' for 'systemprompt', 'focus_modes' for 'focuses', etc.
    model_config = ConfigDict(validate_by_name=True)
