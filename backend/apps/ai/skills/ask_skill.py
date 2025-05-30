# backend/apps/ai/skills/ask_skill.py
# Defines the AskSkill for the AI App, which handles user queries.

import logging
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from pydantic import BaseModel, Field
import os # For environment variables
from celery import Celery # For sending tasks

from backend.apps.base_skill import BaseSkill # Adjusted import path
from backend.core.api.app.schemas.chat import AIHistoryMessage # Import the message model

logger = logging.getLogger(__name__)

# The Celery producer instance (self.celery_producer) is now expected to be passed
# by BaseApp during skill instantiation and stored in BaseSkill.
# No need to define a module-level producer here.

# --- Configuration Models for AskSkill (from backend.core.api.app.yml) ---
class SkillDefaultLLMsConfig(BaseModel):
    preprocessing_model: str
    main_processing_simple: str
    main_processing_complex: str

class SkillPreprocessingThresholdsConfig(BaseModel):
    harmful_content_score: int
    misuse_risk_score: int

class AskSkillDefaultConfig(BaseModel):
    """Pydantic model for ask skill's specific default configurations from backend.core.api.app.yml."""
    default_llms: Optional[SkillDefaultLLMsConfig] = None
    preprocessing_thresholds: Optional[SkillPreprocessingThresholdsConfig] = None


# --- Pydantic models for the /skill/ask endpoint (request/response) ---
class AskSkillRequest(BaseModel):
    chat_id: str = Field(..., description="The ID of the chat session.")
    message_id: str = Field(..., description="The ID of the user's most recent message in the history.") # Clarified
    user_id: str = Field(..., description="Actual ID of the user.")
    user_id_hash: str = Field(..., description="Hashed ID of the user.")
    message_history: List[AIHistoryMessage] = Field(..., description="The complete history of messages in the chat, ordered chronologically. Each message is an AIHistoryMessage model. The last message is the current one.") # Emphasized completeness and order, and specified model type
    current_chat_title: Optional[str] = Field(default=None, description="The current title of the chat, if one exists.")
    mate_id: Optional[str] = Field(default=None, description="The ID of the Mate to use. If None, AI will select.")
    active_focus_id: Optional[str] = Field(default=None, description="The ID of the currently active focus, if any.")
    user_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="User-specific preferences.")

class AskSkillResponse(BaseModel):
    task_id: str = Field(..., description="The ID of the Celery task processing the request.")
    status: str = Field(default="processing", description="The initial status of the request.")
    message: str = Field(default="Request received and is being processed.", description="A message to the user.")


class AskSkill(BaseSkill):
    """
    The core skill for the AI App that processes user messages and queries.
    It initiates a Celery task for asynchronous processing.
    """

    # The skill_id, name, description etc. will be loaded from backend.core.api.app.yml by BaseApp.
    # The skill-specific 'default_config' from backend.core.api.app.yml will be passed to the constructor.
    
    def __init__(self,
                 app_id: str,
                 skill_id: str,
                 name: str,
                 description: str,
                 stage: str,
                 # Parameters for BaseSkill constructor, passed by BaseApp from backend.core.api.app.yml
                 full_model_reference: Optional[str] = None, # From skill's app.yml definition
                 pricing_config: Optional[Dict[str, Any]] = None,    # From skill's app.yml definition
                 # This is for AskSkill's specific operational defaults from its 'default_config' block in app.yml
                 skill_operational_defaults: Optional[Dict[str, Any]] = None
                 ):
        super().__init__(
            app_id=app_id,
            skill_id=skill_id,
            skill_name=name,
            skill_description=description,
            stage=stage,
            full_model_reference=full_model_reference, # Passed to BaseSkill
            pricing_config=pricing_config             # Passed to BaseSkill
        )
        
        self.parsed_default_config: Optional[AskSkillDefaultConfig] = None
        if skill_operational_defaults:
            try:
                self.parsed_default_config = AskSkillDefaultConfig(**skill_operational_defaults)
                logger.info(f"AskSkill '{self.skill_name}' loaded with specific operational_defaults: {self.parsed_default_config.model_dump_json(indent=2)}")
            except Exception as e:
                logger.error(f"Error parsing skill_operational_defaults for AskSkill '{self.skill_name}': {e}. Config was: {skill_operational_defaults}", exc_info=True)
                # Decide if this should be a fatal error for the skill
        
        # Example of accessing parsed config:
        # if self.parsed_default_config and self.parsed_default_config.default_llms:
        #     logger.debug(f"AskSkill preprocessing model: {self.parsed_default_config.default_llms.preprocessing_model}")


    async def execute(self, request: AskSkillRequest) -> AskSkillResponse:
        """
        Handles a user's request to the AI, initiating asynchronous processing.
        This method is called when the /skill/ask endpoint is hit.
        """
        logger.info(f"AskSkill executed for chat_id: {request.chat_id}, message_id: {request.message_id}")

        task_kwargs = request.model_dump(exclude_none=True)
        # Pass the skill's app_id and skill_id to the Celery task for context
        task_kwargs['app_id_for_skill'] = self.app_id
        task_kwargs['skill_id_for_skill'] = self.skill_id
        # The skill's own pricing and fixed model ref are already part of self (BaseSkill instance)
        # The Celery task will need to fetch the AppSkillDefinition if it needs the skill's own pricing.
        # For now, we pass skill_operational_defaults (parsed_default_config) to the task.
        task_kwargs['skill_operational_defaults'] = self.parsed_default_config.model_dump() if self.parsed_default_config else {}


        if not self.celery_producer:
            logger.error(f"Celery producer not available in AskSkill '{self.skill_name}'. Cannot dispatch task.")
            raise HTTPException(status_code=500, detail="AI processing service (Celery producer) is not configured correctly.")

        try:
            task_signature = self.celery_producer.send_task(
                name="apps.ai.tasks.skill_ask",  # Registered name of the task in ai.tasks
                kwargs=task_kwargs,
                queue="app_ai"  # Route to the 'app_ai' queue, as configured in celery_config.py
            )
            task_id = task_signature.id
            logger.info(f"Celery task 'apps.ai.tasks.skill_ask' dispatched by AskSkill with ID: {task_id} for message_id: {request.message_id} to queue 'app_ai'.")
        except Exception as e:
            logger.error(f"AskSkill failed to dispatch Celery task 'apps.ai.tasks.skill_ask': {e}", exc_info=True)
            # It's important to ensure the broker is reachable from the app-ai container.
            # Check CELERY_BROKER_URL env var in app-ai's docker-compose service definition.
            raise HTTPException(status_code=500, detail="Failed to initiate AI processing via AskSkill. Ensure Celery broker is reachable.")

        return AskSkillResponse(task_id=task_id)

    # Override get_metadata if you need to customize what BaseSkill provides,
    # or to add skill-specific metadata not covered by app.yml fields.
    # For now, the default BaseSkill.get_metadata() should be sufficient if app.yml is well-defined.
