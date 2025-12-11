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
    # Note: preprocessing_fallbacks are now resolved automatically from provider config (e.g., mistral.yml)
    # No need to configure them in app.yml anymore - they're derived from the servers list in provider YAML files
    main_processing_simple: str
    main_processing_simple_name: Optional[str] = None # Added
    main_processing_complex: str
    main_processing_complex_name: Optional[str] = None # Added

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
    chat_has_title: bool = Field(default=False, description="Whether the chat already has a title. Used to determine if metadata (title, category, icon) should be generated.")
    is_incognito: bool = Field(default=False, description="Whether this is an incognito chat. Incognito chats skip post-processing and use 'incognito' as chat_id for billing.")
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
                 app,  # BaseApp instance - required by BaseSkill
                 app_id: str,
                 skill_id: str,
                 skill_name: str,  # Changed from 'name' to match BaseSkill
                 skill_description: str,  # Changed from 'description' to match BaseSkill
                 stage: str = "development",
                 full_model_reference: Optional[str] = None, # From skill's app.yml definition
                 pricing_config: Optional[Dict[str, Any]] = None,    # From skill's app.yml definition
                 celery_producer: Optional[Celery] = None,  # Added to match BaseSkill
                 # This is for AskSkill's specific operational defaults from its 'default_config' block in app.yml
                 skill_operational_defaults: Optional[Dict[str, Any]] = None
                 ):
        # Call BaseSkill constructor with all required parameters
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer
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

        # Prepare task arguments matching the expected signature:
        # process_ai_skill_ask_task(self, request_data_dict: dict, skill_config_dict: dict)
        request_data_dict = request.model_dump(exclude_none=True)
        skill_config_dict = self.parsed_default_config.model_dump() if self.parsed_default_config else {}

        if not self.celery_producer:
            logger.error(f"Celery producer not available in AskSkill '{self.skill_name}'. Cannot dispatch task.")
            raise HTTPException(status_code=500, detail="AI processing service (Celery producer) is not configured correctly.")

        try:
            # Use the shared Celery app from celery_config and import the task directly
            # This ensures we use the registered task object, which is more reliable than send_task
            from backend.core.api.app.tasks.celery_config import app as celery_app
            from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task
            
            # Use apply_async on the registered task object instead of send_task
            # This is the recommended approach per Celery docs when you have access to the task object
            # It ensures proper routing and task registration
            # Explicitly set exchange and routing_key to match the queue declaration in celery_config.py
            # This ensures the task is routed to the correct queue and consumed by app-ai-worker, not app-web-worker
            task_signature = process_ai_skill_ask_task.apply_async(
                kwargs={
                    "request_data_dict": request_data_dict,
                    "skill_config_dict": skill_config_dict
                },
                queue="app_ai",  # Route to the 'app_ai' queue, as configured in celery_config.py
                exchange="app_ai",  # Match the exchange declared in celery_config.py task_queues
                routing_key="app_ai"  # Match the routing_key declared in celery_config.py task_queues
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
