# backend/apps/ai/skills/ask_skill.py
# Defines the AskSkill for the AI App, which handles user queries.

import logging
from typing import List, Dict, Any, Optional, Union
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import time
import uuid
import hashlib
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
    # Always-include skills configuration - these skills are ALWAYS available to the main LLM
    # regardless of preprocessing preselection. This ensures critical skills like web-search
    # are available even if the preprocessing LLM fails to preselect them for follow-up queries.
    # Format: List of skill identifiers like ["web-search", "web-read"]
    always_include_skills: Optional[List[str]] = None


# --- Pydantic models for the /skill/ask endpoint (request/response) ---
class AskSkillRequest(BaseModel):
    chat_id: str = Field(..., description="The ID of the chat session.")
    message_id: str = Field(..., description="The ID of the user's most recent message in the history.") # Clarified
    user_id: str = Field(..., description="Actual ID of the user.")
    user_id_hash: str = Field(..., description="Hashed ID of the user.")
    message_history: List[AIHistoryMessage] = Field(..., description="The complete history of messages in the chat, ordered chronologically. Each message is an AIHistoryMessage model. The last message is the current one.") # Emphasized completeness and order, and specified model type
    chat_has_title: bool = Field(default=False, description="Whether the chat already has a title. Used to determine if metadata (title, category, icon) should be generated.")
    is_incognito: bool = Field(default=False, description="Whether this is an incognito chat. Incognito chats skip post-processing and use 'incognito' as chat_id for billing.")
    is_external: bool = Field(default=False, description="Whether this is an external API request. External requests skip cache warming, vault lookup, and storage.")
    mate_id: Optional[str] = Field(default=None, description="The ID of the Mate to use. If None, AI will select.")
    active_focus_id: Optional[str] = Field(default=None, description="The ID of the currently active focus, if any.")
    user_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="User-specific preferences.")
    app_settings_memories_metadata: Optional[List[str]] = Field(default=None, description="List of available app settings/memories keys from client in 'app_id-item_type' format (e.g., ['code-preferred_technologies', 'travel-trips']). Client is source of truth since only client can decrypt.")
    is_app_settings_memories_continuation: bool = Field(default=False, description="True if this task is a continuation after app settings/memories confirmation/rejection. Prevents infinite loops by skipping pending context storage if data is still missing.")
    api_key_hash: Optional[str] = Field(default=None, alias="_api_key_hash", description="SHA-256 hash of the API key for usage tracking.")
    device_hash: Optional[str] = Field(default=None, alias="_device_hash", description="SHA-256 hash of the device for usage tracking.")
    api_key_name: Optional[str] = Field(default=None, alias="_api_key_name", description="Encrypted name of the API key.")
    
    # Allow populating by name even with aliases
    model_config = {"populate_by_name": True}

class AskSkillResponse(BaseModel):
    task_id: str = Field(..., description="The ID of the Celery task processing the request.")
    status: str = Field(default="processing", description="The initial status of the request.")
    message: str = Field(default="Request received and is being processed.", description="A message to the user.")


# --- OpenAI-compatible Pydantic models for ChatGPT-like API ---
class OpenAIMessage(BaseModel):
    role: str = Field(..., description="The role of the message author (user, assistant, or system).")
    content: str = Field(..., description="The content of the message.")
    name: Optional[str] = Field(default=None, description="The name of the author of this message.")
    embeds: Optional[List[Dict[str, Any]]] = Field(default=None, description="Embedded content resolved for API users.")
    
    # Exclude null fields from JSON output for better standard compliance
    model_config = {"extra": "allow", "populate_by_name": True, "from_attributes": True}

class OpenAICompletionRequest(BaseModel):
    messages: List[OpenAIMessage] = Field(..., description="A list of messages comprising the conversation so far.")
    model: Optional[str] = Field(default=None, description="ID of the model to use. If None, AI will select based on complexity.")
    stream: Optional[bool] = Field(default=False, description="Whether to stream back partial progress.")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature between 0 and 2.")
    max_tokens: Optional[int] = Field(default=None, description="Maximum number of tokens to generate.")
    top_p: Optional[float] = Field(default=None, description="Nucleus sampling parameter.")
    frequency_penalty: Optional[float] = Field(default=None, description="Frequency penalty parameter.")
    presence_penalty: Optional[float] = Field(default=None, description="Presence penalty parameter.")
    stop: Optional[List[str]] = Field(default=None, description="Up to 4 sequences where the API will stop generating.")

    # OpenMates-specific extensions
    apps_enabled: Optional[bool] = Field(default=True, description="Whether to enable app skills (tools).")
    allowed_apps: Optional[List[str]] = Field(default=None, description="List of app IDs to allow. If None, all apps are allowed.")
    mate_id: Optional[str] = Field(default=None, description="ID of the Mate to use. If None, AI will select.")
    provider: Optional[str] = Field(default=None, description="Preferred provider (e.g., 'openai', 'cerebras', 'anthropic').")
    focus_mode: Optional[str] = Field(default=None, description="Focus mode ID to use.")
    is_incognito: Optional[bool] = Field(default=False, description="Whether this is an incognito request (no storage/billing).")
    
    # Context metadata fields injected by the external API handler from API key authentication
    # These allow the skill to use the real authenticated user for proper cache lookups and billing
    # Using aliases to accept underscore-prefixed field names from the API while storing without underscores
    ctx_user_id: Optional[str] = Field(default=None, alias="_user_id", description="Real user ID from API key authentication (injected by API)")
    ctx_api_key_name: Optional[str] = Field(default=None, alias="_api_key_name", description="Encrypted API key name (injected by API)")
    ctx_external_request: Optional[bool] = Field(default=False, alias="_external_request", description="Flag indicating this is an external API request (injected by API)")
    ctx_api_key_hash: Optional[str] = Field(default=None, alias="_api_key_hash", description="SHA-256 hash of API key (injected by API)")
    ctx_device_hash: Optional[str] = Field(default=None, alias="_device_hash", description="SHA-256 hash of device (injected by API)")
    ctx_api_key_encrypted_name: Optional[str] = Field(default=None, alias="_api_key_name", description="Encrypted name of API key (injected by API)")
    
    # Allow extra fields to be passed through (for future context metadata) and populate by field name
    model_config = {"extra": "allow", "populate_by_name": True}

class OpenAIChoice(BaseModel):
    index: int = Field(..., description="The index of the choice.")
    message: OpenAIMessage = Field(..., description="The message generated by the model.")
    finish_reason: Optional[str] = Field(default=None, description="The reason the model stopped generating tokens.")
    
    # Exclude null fields from JSON output
    model_config = {"from_attributes": True}

class OpenAIUsage(BaseModel):
    prompt_tokens: int = Field(..., description="Number of tokens in the prompt.")
    completion_tokens: int = Field(..., description="Number of tokens in the completion.")
    total_tokens: int = Field(..., description="Total number of tokens used.")
    user_input_tokens: int = Field(default=0, description="Number of tokens from user messages (OpenMates extension).")
    system_prompt_tokens: int = Field(default=0, description="Number of tokens from system prompts (OpenMates extension).")
    total_credits: Optional[int] = Field(default=None, description="Total credits charged for the request (OpenMates extension).")
    
    # Exclude null fields from JSON output
    model_config = {"from_attributes": True}

class OpenAICompletionResponse(BaseModel):
    id: str = Field(..., description="A unique identifier for the completion.")
    object: str = Field(default="chat.completion", description="The object type.")
    created: int = Field(..., description="The Unix timestamp when the completion was created.")
    model: str = Field(..., description="The model used for completion.")
    category: Optional[str] = Field(default=None, description="The category of the request (OpenMates extension).")
    choices: List[OpenAIChoice] = Field(..., description="A list of completion choices.")
    usage: Optional[OpenAIUsage] = Field(default=None, description="Usage statistics for the completion request.")
    
    # Exclude null fields from JSON output
    model_config = {"from_attributes": True}

class OpenAIDelta(BaseModel):
    role: Optional[str] = Field(default=None, description="The role of the author of this message.")
    content: Optional[str] = Field(default=None, description="The contents of the chunk message.")
    embeds: Optional[List[Dict[str, Any]]] = Field(default=None, description="Embedded content resolved for streaming API users.")
    
    # Exclude null fields from JSON output
    model_config = {"extra": "allow", "populate_by_name": True}

class OpenAIStreamChoice(BaseModel):
    index: int = Field(..., description="The index of the choice.")
    delta: OpenAIDelta = Field(..., description="A chat completion delta generated by streamed model responses.")
    finish_reason: Optional[str] = Field(default=None, description="The reason the model stopped generating tokens.")
    
    # Exclude null fields from JSON output
    model_config = {"from_attributes": True}

class OpenAIStreamResponse(BaseModel):
    id: str = Field(..., description="A unique identifier for the completion.")
    object: str = Field(default="chat.completion.chunk", description="The object type.")
    created: int = Field(..., description="The Unix timestamp when the completion was created.")
    model: str = Field(..., description="The model used for completion.")
    choices: List[OpenAIStreamChoice] = Field(..., description="A list of completion choices.")
    usage: Optional[OpenAIUsage] = Field(default=None, description="Usage statistics for the completion request (only in final chunk).")
    
    # Exclude null fields from JSON output
    model_config = {"from_attributes": True}


# --- OpenAI-compatible error response model ---
# OpenAI returns errors as HTTP 4xx/5xx with a JSON body containing an "error" object
# This follows the OpenAI API error format specification:
# https://platform.openai.com/docs/guides/error-codes
class OpenAIErrorDetail(BaseModel):
    """The detail object within an OpenAI error response."""
    message: str = Field(..., description="A human-readable description of what went wrong.")
    type: str = Field(..., description="The high-level classification of error (e.g., 'invalid_request_error', 'authentication_error', 'server_error').")
    param: Optional[str] = Field(default=None, description="The parameter (request field) that triggered the error, if applicable.")
    code: Optional[str] = Field(default=None, description="Optional specific error code for finer detail.")

class OpenAIErrorResponse(BaseModel):
    """OpenAI-compatible error response structure."""
    error: OpenAIErrorDetail = Field(..., description="The error details.")


# --- Union request type for supporting both formats ---
UnifiedAskRequest = Union[AskSkillRequest, OpenAICompletionRequest]


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


    async def execute(self, request: UnifiedAskRequest) -> Union[AskSkillResponse, StreamingResponse, OpenAICompletionResponse]:
        """
        Handles a user's request to the AI, initiating asynchronous processing.
        This method supports both internal format (AskSkillRequest) and OpenAI format (OpenAICompletionRequest).
        """
        # Detect request format and handle accordingly
        if isinstance(request, OpenAICompletionRequest):
            logger.info(f"AskSkill executed with OpenAI format: {len(request.messages)} messages, stream={request.stream}")
            return await self._handle_openai_request(request)
        elif isinstance(request, AskSkillRequest):
            logger.info(f"AskSkill executed with internal format for chat_id: {request.chat_id}, message_id: {request.message_id}")
            return await self._handle_internal_request(request)
        else:
            logger.error(f"AskSkill received unknown request type: {type(request)}")
            raise HTTPException(status_code=400, detail="Invalid request format. Expected AskSkillRequest or OpenAICompletionRequest.")

    async def _handle_internal_request(self, request: AskSkillRequest) -> AskSkillResponse:
        """
        Handle requests in the original internal format (from WebSocket/web app).
        """
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

    async def _handle_openai_request(self, request: OpenAICompletionRequest) -> Union[StreamingResponse, OpenAICompletionResponse]:
        """
        Handle requests in OpenAI format (from REST API/CLI).
        Transform to internal format and process, then return OpenAI-compatible response.
        """
        # Log the incoming request context fields for debugging
        logger.info(f"[HANDLE_OPENAI] ctx_user_id={request.ctx_user_id}, ctx_external_request={request.ctx_external_request}")
        if hasattr(request, 'model_extra') and request.model_extra:
            logger.info(f"[HANDLE_OPENAI] model_extra keys: {list(request.model_extra.keys())}")
        
        # Transform OpenAI request to internal AskSkillRequest format
        internal_request = await self._transform_openai_to_internal(request)

        if request.stream:
            # Handle streaming response
            return StreamingResponse(
                self._stream_openai_response(internal_request, request),
                media_type="text/plain",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
        else:
            # Handle non-streaming response
            return await self._handle_openai_sync_response(internal_request, request)

    async def _transform_openai_to_internal(self, openai_request: OpenAICompletionRequest) -> AskSkillRequest:
        """
        Transform OpenAI-compatible request to internal AskSkillRequest format.
        Generates required IDs and converts message format.
        
        If _user_id is provided (from API key authentication), uses the real user ID
        for proper cache lookups and billing. Otherwise falls back to synthetic user.
        """
        # Generate required IDs for stateless operation
        chat_id = f"openai-{uuid.uuid4()}" if not openai_request.is_incognito else "incognito"
        message_id = f"msg-{uuid.uuid4()}"
        
        # Use real user ID from API authentication if available, otherwise use synthetic user
        # The _user_id is injected by the external API handler from the API key's authenticated user
        # We check multiple ways to access it: via the aliased field and via model_extra
        api_user_id = openai_request.ctx_user_id
        
        # Also check model_extra in case the alias didn't work (Pydantic v2 behavior can vary)
        if not api_user_id and hasattr(openai_request, 'model_extra') and openai_request.model_extra:
            api_user_id = openai_request.model_extra.get('_user_id')
            logger.info(f"[TRANSFORM] Retrieved _user_id from model_extra: {api_user_id}")
        
        # Log what we found for debugging
        extra_keys = list(openai_request.model_extra.keys()) if hasattr(openai_request, 'model_extra') and openai_request.model_extra else []
        logger.info(f"[TRANSFORM] ctx_user_id={openai_request.ctx_user_id}, model_extra keys={extra_keys}")
        
        if api_user_id:
            user_id = api_user_id
            logger.info(f"[TRANSFORM] Using authenticated user_id from API key: {user_id[:8]}...")
        else:
            user_id = "openai-api-user"  # Fallback for internal calls without API key context
            logger.info("[TRANSFORM] Using synthetic user_id (no API authentication context)")
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()

        # Extract API key and device hashes if available
        api_key_hash = openai_request.ctx_api_key_hash
        device_hash = openai_request.ctx_device_hash
        api_key_name = openai_request.ctx_api_key_encrypted_name
        
        if not api_key_hash and hasattr(openai_request, 'model_extra') and openai_request.model_extra:
            api_key_hash = openai_request.model_extra.get('_api_key_hash')
        if not device_hash and hasattr(openai_request, 'model_extra') and openai_request.model_extra:
            device_hash = openai_request.model_extra.get('_device_hash')
        if not api_key_name and hasattr(openai_request, 'model_extra') and openai_request.model_extra:
            api_key_name = openai_request.model_extra.get('_api_key_name')

        # Convert OpenAI messages to internal message history format
        message_history = []
        current_time = int(time.time())

        for msg in openai_request.messages:
            ai_message = AIHistoryMessage(
                role=msg.role,
                content=msg.content,
                created_at=current_time,
                sender_name=msg.name or msg.role,
                category=None
            )
            message_history.append(ai_message)

        # Build internal request
        internal_request = AskSkillRequest(
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            message_history=message_history,
            chat_has_title=False,  # Always generate new metadata for API requests
            is_incognito=openai_request.is_incognito or False,
            is_external=True,  # This is an external OpenAI-compatible request
            mate_id=openai_request.mate_id,
            active_focus_id=openai_request.focus_mode,
            api_key_hash=api_key_hash,
            device_hash=device_hash,
            api_key_name=api_key_name,
            user_preferences={
                "model": openai_request.model,
                "provider": openai_request.provider,
                "temperature": openai_request.temperature,
                "max_tokens": openai_request.max_tokens,
                "top_p": openai_request.top_p,
                "frequency_penalty": openai_request.frequency_penalty,
                "presence_penalty": openai_request.presence_penalty,
                "stop": openai_request.stop,
                "apps_enabled": openai_request.apps_enabled,
                "allowed_apps": openai_request.allowed_apps
            }
        )

        return internal_request

    async def _stream_openai_response(self, internal_request: AskSkillRequest, openai_request: OpenAICompletionRequest):
        """
        Generator function for streaming OpenAI-compatible responses.
        Uses the existing Redis streaming infrastructure to provide real streaming.
        """
        completion_id = f"chatcmpl-{uuid.uuid4()}"
        created_timestamp = int(time.time())
        model_name = openai_request.model or "openmates-ai"

        try:
            # Execute the internal request (this dispatches to Celery)
            internal_response = await self._handle_internal_request(internal_request)
            task_id = internal_response.task_id

            # Send initial streaming response
            initial_chunk = OpenAIStreamResponse(
                id=completion_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    OpenAIStreamChoice(
                        index=0,
                        delta=OpenAIDelta(role="assistant", content=""),
                        finish_reason=None
                    )
                ]
            )

            yield f"data: {initial_chunk.model_dump_json(exclude_none=True)}\n\n"

            # Subscribe to Redis stream for real-time updates
            redis_channel = f"chat_stream::{internal_request.chat_id}"

            # Import cache service
            from backend.core.api.app.services.cache import CacheService
            cache_service = CacheService()

            # Pre-fetch user_vault_key_id for embed resolution later
            user_vault_key_id = await cache_service.get_user_vault_key_id(internal_request.user_id)
            if not user_vault_key_id:
                logger.warning(f"Could not fetch vault_key_id for user {internal_request.user_id} during stream. Embeds will be unresolved.")

            # Collect all content to extract embeds at the end
            full_response_content = ""

            # Listen to Redis stream
            async for chunk_info in self._listen_to_redis_stream(cache_service, redis_channel, task_id):
                if chunk_info["type"] == "content":
                    chunk_data = chunk_info["content"]
                    # Track full content for embed extraction
                    full_response_content += chunk_data

                    # Text content chunk
                    content_chunk = OpenAIStreamResponse(
                        id=completion_id,
                        created=created_timestamp,
                        model=chunk_info.get("model_name") or model_name,
                        choices=[
                            OpenAIStreamChoice(
                                index=0,
                                delta=OpenAIDelta(content=chunk_data),
                                finish_reason=None
                            )
                        ]
                    )
                    yield f"data: {content_chunk.model_dump_json(exclude_none=True)}\n\n"
                
                elif chunk_info["type"] in ["final", "error"]:
                    # Final chunk or error marker
                    is_error = chunk_info["type"] == "error"
                    actual_model_name = chunk_info.get("model_name") or model_name

                    # Extract embeds after streaming is complete
                    embeds_content = await self._extract_and_resolve_embeds(full_response_content, internal_request.chat_id, user_vault_key_id)

                    # Send embeds as additional data if found
                    if embeds_content:
                        embed_chunk = OpenAIStreamResponse(
                            id=completion_id,
                            created=created_timestamp,
                            model=actual_model_name,
                            choices=[
                                OpenAIStreamChoice(
                                    index=0,
                                    delta=OpenAIDelta(embeds=embeds_content),
                                    finish_reason=None
                                )
                            ]
                        )
                        yield f"data: {embed_chunk.model_dump_json(exclude_none=True)}\n\n"

                    # Send final chunk with stop reason and usage
                    prompt_tokens = chunk_info.get("prompt_tokens")
                    completion_tokens = chunk_info.get("completion_tokens")
                    user_input_tokens = chunk_info.get("user_input_tokens") or 0
                    system_prompt_tokens = chunk_info.get("system_prompt_tokens") or 0
                    total_credits = chunk_info.get("total_credits")
                    
                    usage_data = None
                    if prompt_tokens is not None and completion_tokens is not None:
                        # CRITICAL: Ensure consistency between prompt_tokens and breakdown
                        # We adjust system_prompt_tokens (not user_input_tokens) to absorb overhead
                        # because users can see their input but not the system prompt, so keeping
                        # user_input_tokens close to what they typed is more intuitive.
                        if prompt_tokens > 0:
                            calculated_sum = user_input_tokens + system_prompt_tokens
                            if calculated_sum != prompt_tokens:
                                old_system_prompt = system_prompt_tokens
                                system_prompt_tokens = max(0, prompt_tokens - user_input_tokens)
                                logger.info(f"OPENAI_STREAM: Adjusted system_prompt_tokens from {old_system_prompt} to {system_prompt_tokens} to match prompt_tokens {prompt_tokens} (user_input={user_input_tokens})")

                        usage_data = OpenAIUsage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=prompt_tokens + completion_tokens,
                            user_input_tokens=user_input_tokens,
                            system_prompt_tokens=system_prompt_tokens,
                            total_credits=total_credits
                        )

                    final_chunk = OpenAIStreamResponse(
                        id=completion_id,
                        created=created_timestamp,
                        model=actual_model_name,
                        choices=[
                            OpenAIStreamChoice(
                                index=0,
                                delta=OpenAIDelta(),
                                finish_reason="error" if is_error else "stop"
                            )
                        ],
                        usage=usage_data
                    )
                    yield f"data: {final_chunk.model_dump_json(exclude_none=True)}\n\n"
                    yield "data: [DONE]\n\n"
                    break

        except Exception as e:
            logger.error(f"Error in OpenAI streaming response: {e}", exc_info=True)
            error_chunk = OpenAIStreamResponse(
                id=completion_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    OpenAIStreamChoice(
                        index=0,
                        delta=OpenAIDelta(content=f"Error: {str(e)}"),
                        finish_reason="error"
                    )
                ]
            )
            yield f"data: {error_chunk.model_dump_json(exclude_none=True)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Error in OpenAI streaming response: {e}", exc_info=True)
            error_chunk = OpenAIStreamResponse(
                id=completion_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    OpenAIStreamChoice(
                        index=0,
                        delta=OpenAIDelta(content=f"Error: {str(e)}"),
                        finish_reason="error"
                    )
                ]
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

    async def _listen_to_redis_stream(self, cache_service, redis_channel: str, task_id: str):
        """
        Listen to Redis stream for real-time updates from the Celery task.
        Uses the same infrastructure as WebSocket streaming.
        Yields chunk dictionaries as they arrive and monitors task completion.
        """
        import json

        logger.info(f"DEBUG_STREAM: Listening to Redis stream: {redis_channel} for task: {task_id}")

        # Track task completion and content
        task_completed = False
        last_content_length = 0
        full_content = ""

        try:
            # Subscribe to the specific channel using the same pattern as WebSocket handler
            async for message in cache_service.subscribe_to_channel(redis_channel):
                if message is None:
                    continue

                try:
                    # Parse the Redis message
                    data = message.get("data", {})
                    if not isinstance(data, dict):
                        try:
                            data = json.loads(data) if isinstance(data, str) else data
                        except Exception:
                            pass

                    if isinstance(data, dict):
                        # Use standardized keys from stream_consumer.py
                        message_task_id = data.get("task_id", "")
                        
                        # Only process messages for our specific task
                        if message_task_id == task_id:
                            # Extract full content so far (standardized key in stream_consumer.py)
                            current_full_content = data.get("full_content_so_far", "")
                            # Use standardized final marker key from stream_consumer.py
                            is_final = data.get("is_final_chunk", False)
                            is_error = data.get("error", False)
                            
                            logger.info(f"DEBUG_STREAM: Received chunk for task {task_id}. Length: {len(current_full_content)}, Final: {is_final}, Error: {is_error}")
                            
                            # Calculate and yield the delta (new content) if available
                            if current_full_content and len(current_full_content) > last_content_length:
                                new_chunk = current_full_content[last_content_length:]
                                yield {"type": "content", "content": new_chunk}
                                last_content_length = len(current_full_content)
                                full_content = current_full_content

                            if is_final or is_error:
                                logger.info(f"DEBUG_STREAM: Received {'error' if is_error else 'final'} marker for task: {task_id}. Total length: {len(full_content)}")
                                yield {
                                    "type": "final" if is_final else "error",
                                    "full_content": full_content,
                                    "model_name": data.get("model_name"),
                                    "prompt_tokens": data.get("prompt_tokens"),
                                    "completion_tokens": data.get("completion_tokens"),
                                    "user_input_tokens": data.get("user_input_tokens"),
                                    "system_prompt_tokens": data.get("system_prompt_tokens"),
                                    "total_credits": data.get("total_credits"),
                                    "category": data.get("category")
                                }
                                task_completed = True
                                break

                except Exception as parse_e:
                    logger.debug(f"Redis message parse error: {parse_e}")
                    continue

                if task_completed:
                    break

        except Exception as e:
            logger.error(f"Error in Redis stream listener: {e}", exc_info=True)

        logger.info(f"DEBUG_STREAM: Finished listening to Redis stream for task: {task_id}, received {len(full_content)} characters")

    async def _handle_openai_sync_response(self, internal_request: AskSkillRequest, openai_request: OpenAICompletionRequest) -> OpenAICompletionResponse:
        """
        Handle non-streaming OpenAI-compatible response.
        Waits for the Celery task to complete the main response via Redis stream.
        
        For errors, raises HTTPException with OpenAI-compatible error format:
        {
            "error": {
                "message": "Error description",
                "type": "error_type",
                "param": null,
                "code": "error_code"
            }
        }
        """
        logger.info(f"OPENAI_SYNC: Starting sync response for chat {internal_request.chat_id}")
        completion_id = f"chatcmpl-{uuid.uuid4()}"
        created_timestamp = int(time.time())
        model_name = openai_request.model or "openmates-ai"

        try:
            # Execute the internal request (this dispatches to Celery)
            internal_response = await self._handle_internal_request(internal_request)
            task_id = internal_response.task_id
            logger.info(f"OPENAI_SYNC: Task dispatched with ID {task_id}")

            # Collect all content by listening to the Redis stream
            redis_channel = f"chat_stream::{internal_request.chat_id}"

            # Import cache service
            from backend.core.api.app.services.cache import CacheService
            cache_service = CacheService()

            # Collect the full response content and usage metadata
            response_content = ""
            final_metadata = {}
            
            # Listen to Redis stream and return as soon as main processing is done
            logger.info(f"OPENAI_SYNC: Starting to listen to Redis channel {redis_channel}")
            async for chunk_info in self._listen_to_redis_stream(cache_service, redis_channel, task_id):
                if chunk_info["type"] == "content":
                    chunk_data = chunk_info["content"]
                    logger.info(f"OPENAI_SYNC: Received chunk data (len: {len(chunk_data)})")
                    response_content += chunk_data
                elif chunk_info["type"] in ["final", "error"]:
                    final_metadata = chunk_info
                    # response_content was already accumulated from chunks

            logger.info(f"OPENAI_SYNC: Finished listening. Total content length: {len(response_content)}")

            # Pre-fetch user_vault_key_id for embed resolution
            user_vault_key_id = await cache_service.get_user_vault_key_id(internal_request.user_id)
            if not user_vault_key_id:
                logger.warning(f"OPENAI_SYNC: Could not fetch vault_key_id for user {internal_request.user_id}. Embeds will be unresolved.")

            # Use actual model name from worker if available
            actual_model_name = final_metadata.get("model_name") or model_name

            # Detect and handle errors in the response content
            # Error messages from the task are prefixed with "Error:" and are sent via Redis stream
            # These should be returned as proper OpenAI error responses, not as assistant messages
            error_content = response_content.strip()
            if error_content.startswith("Error:"):
                # Extract the error message (remove "Error: " prefix)
                error_message = error_content[6:].strip() if len(error_content) > 6 else "An unexpected error occurred"
                logger.warning(f"OPENAI_SYNC: Detected error in response content: {error_message}")
                
                # Determine error type and code based on the error message
                # Map common error patterns to OpenAI error types
                error_type = "server_error"
                error_code = "internal_error"
                status_code = 500
                
                if "credit" in error_message.lower() or "balance" in error_message.lower():
                    error_type = "insufficient_quota"
                    error_code = "insufficient_credits"
                    status_code = 402  # Payment Required
                elif "user" in error_message.lower() and ("not found" in error_message.lower() or "identification" in error_message.lower()):
                    error_type = "authentication_error"
                    error_code = "user_not_found"
                    status_code = 401  # Unauthorized
                elif "rate limit" in error_message.lower():
                    error_type = "rate_limit_error"
                    error_code = "rate_limit_exceeded"
                    status_code = 429  # Too Many Requests
                elif "invalid" in error_message.lower():
                    error_type = "invalid_request_error"
                    error_code = "invalid_request"
                    status_code = 400  # Bad Request
                
                # Raise HTTPException with OpenAI-compatible error detail format
                # FastAPI will serialize this as JSON automatically
                raise HTTPException(
                    status_code=status_code,
                    detail={
                        "error": {
                            "message": error_message,
                            "type": error_type,
                            "param": None,
                            "code": error_code
                        }
                    }
                )

            # If no content was collected, provide a fallback message
            if not response_content.strip():
                logger.warning("OPENAI_SYNC: No content collected from stream!")
                response_content = "I'm processing your request. Please try again or check the task status if this persists."

            # Extract and resolve embed content for CLI/API users
            embeds_content = await self._extract_and_resolve_embeds(response_content, internal_request.chat_id, user_vault_key_id)

            # Create the assistant message
            assistant_message = OpenAIMessage(
                role="assistant",
                content=response_content
            )

            # Add embeds if any (OpenMates extension)
            if embeds_content:
                assistant_message.embeds = embeds_content

            # Calculate token counts - use actual counts from worker if available,
            # otherwise fallback to split-based estimation
            prompt_tokens = final_metadata.get("prompt_tokens")
            if prompt_tokens is None:
                prompt_tokens = sum(len(msg.content.split()) for msg in openai_request.messages)
            
            completion_tokens = final_metadata.get("completion_tokens")
            if completion_tokens is None:
                completion_tokens = len(response_content.split())
            
            total_credits = final_metadata.get("total_credits")
            user_input_tokens = final_metadata.get("user_input_tokens") or 0
            system_prompt_tokens = final_metadata.get("system_prompt_tokens") or 0
            category = final_metadata.get("category")

            # CRITICAL: Ensure that prompt_tokens matches user_input_tokens + system_prompt_tokens
            # Since prompt_tokens from the LLM provider is the absolute source of truth for total input,
            # and system_prompt_tokens/user_input_tokens are estimates, we adjust system_prompt_tokens
            # to absorb any difference (like tool definitions or formatting overhead).
            # We keep user_input_tokens close to the actual user input because users can see what
            # they typed but cannot see the system prompt, making this more intuitive.
            if prompt_tokens is not None and prompt_tokens > 0:
                calculated_sum = user_input_tokens + system_prompt_tokens
                if calculated_sum != prompt_tokens:
                    # Adjust system_prompt_tokens to absorb overhead (provider formatting, tool schemas, etc.)
                    # This keeps user_input_tokens close to what the user actually typed
                    old_system_prompt = system_prompt_tokens
                    system_prompt_tokens = max(0, prompt_tokens - user_input_tokens)
                    logger.info(f"OPENAI_SYNC: Adjusted system_prompt_tokens from {old_system_prompt} to {system_prompt_tokens} to match prompt_tokens {prompt_tokens} (user_input={user_input_tokens})")

            return OpenAICompletionResponse(
                id=completion_id,
                created=created_timestamp,
                model=actual_model_name,
                choices=[
                    OpenAIChoice(
                        index=0,
                        message=assistant_message,
                        finish_reason="stop"
                    )
                ],
                usage=OpenAIUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    user_input_tokens=user_input_tokens,
                    system_prompt_tokens=system_prompt_tokens,
                    total_credits=total_credits
                ),
                category=category
            )

        except HTTPException:
            # Re-raise HTTPExceptions as-is (including our OpenAI error format exceptions)
            raise
        except Exception as e:
            logger.error(f"OPENAI_SYNC: Error in OpenAI sync response: {e}", exc_info=True)
            # Return proper OpenAI error format for unexpected exceptions
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": f"Error processing request: {str(e)}",
                        "type": "server_error",
                        "param": None,
                        "code": "internal_error"
                    }
                }
            )

    async def _extract_and_resolve_embeds(self, response_content: str, chat_id: str, user_vault_key_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Extract and resolve embed content from response text.
        For API users, we need to provide the actual embed content, not just JSON references.
        """
        import re
        import json

        embeds_list = []

        try:
            # Pattern to match JSON code blocks with embed references
            # Matches ```json\n{ ... "embed_id": "..." ... }\n```
            # This version is more flexible to handle extra fields like app_id, skill_id, query, etc.
            json_block_pattern = r'```json\s*\n\s*(.*?)\s*\n\s*```'
            json_matches = re.findall(json_block_pattern, response_content, re.MULTILINE | re.DOTALL)

            if not json_matches:
                return embeds_list

            embed_ids = []
            for json_str in json_matches:
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict):
                        embed_id = data.get("embed_id")
                        if embed_id:
                            embed_ids.append(embed_id)
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                embed_id = item.get("embed_id")
                                if embed_id:
                                    embed_ids.append(embed_id)
                except json.JSONDecodeError:
                    continue

            if not embed_ids:
                return embeds_list

            # Import necessary services for embed resolution
            from backend.core.api.app.services.cache import CacheService
            from backend.core.api.app.utils.encryption import EncryptionService
            from toon_format import decode
            
            cache_service = CacheService()
            encryption_service = EncryptionService()

            for embed_id in embed_ids:
                try:
                    # Retrieve embed metadata from cache
                    embed_key = f"embed:{embed_id}"
                    embed_json = await cache_service.get(embed_key)

                    if embed_json:
                        # Parse the outer embed metadata
                        if isinstance(embed_json, bytes):
                            embed_json = embed_json.decode('utf-8')
                        
                        embed_data = json.loads(embed_json) if isinstance(embed_json, str) else embed_json
                        
                        # Decrypt content if vault key is available
                        embed_content = {}
                        if user_vault_key_id and embed_data.get("encrypted_content"):
                            try:
                                # Decrypt the content
                                plaintext_toon = await encryption_service.decrypt_with_user_key(
                                    embed_data["encrypted_content"],
                                    user_vault_key_id
                                )
                                
                                if plaintext_toon:
                                    # Decode the TOON-encoded content
                                    embed_content = decode(plaintext_toon)
                                else:
                                    logger.warning(f"Failed to decrypt content for embed {embed_id}")
                            except Exception as decrypt_err:
                                logger.error(f"Error decrypting embed {embed_id}: {decrypt_err}")
                        else:
                            if not user_vault_key_id:
                                logger.warning(f"No vault_key_id provided for resolving embed {embed_id}")
                            elif not embed_data.get("encrypted_content"):
                                logger.warning(f"No encrypted_content found for embed {embed_id}")

                        # Format embed for API response
                        # Use structure from EmbedService and handle different types
                        embed_type = embed_data.get("type") or embed_content.get("type", "unknown")
                        
                        resolved_embed = {
                            "id": embed_id,
                            "type": embed_type,
                            "content": "",
                            "metadata": {},
                            "title": embed_content.get("title") or embed_data.get("title", "Embedded Content")
                        }
                        
                        # Handle different embed types to populate content and metadata
                        if embed_type == "code":
                            # For code embeds, the actual code is in the "code" field
                            code_content = embed_content.get("code", "")
                            language = embed_content.get("language")
                            filename = embed_content.get("filename")
                            
                            # Handle cases where language and filename are stuck in the code content
                            # Format: "language:filename\nCODE" or "language\nCODE" or "filename\nCODE"
                            if code_content and "\n" in code_content and (not language or not filename):
                                first_line, rest = code_content.split("\n", 1)
                                if ":" in first_line:
                                    parsed_lang, parsed_filename = first_line.split(":", 1)
                                    # Simple validation: language shouldn't have spaces and should be reasonably short
                                    if parsed_lang and " " not in parsed_lang and len(parsed_lang) < 20:
                                        language = parsed_lang.strip()
                                        filename = parsed_filename.strip()
                                        code_content = rest
                                elif not language and "." in first_line and " " not in first_line:
                                    # Might be just a filename
                                    filename = first_line.strip()
                                    code_content = rest
                            
                            resolved_embed["content"] = code_content
                            resolved_embed["metadata"] = {
                                "language": language or "",
                                "filename": filename or "",
                                "line_count": embed_content.get("line_count") or (len(code_content.splitlines()) if code_content else 0),
                                "status": embed_content.get("status") or embed_data.get("status")
                            }
                        elif embed_type == "app_skill_use":
                            # For skill results, we might have multiple results
                            # If there's a single clear text-like result, use it as content
                            # Otherwise put everything into metadata
                            results = embed_content.get("results", [])
                            if results and isinstance(results, list) and len(results) == 1:
                                result = results[0]
                                # Try to find a sensible content field in the result
                                resolved_embed["content"] = result.get("content") or result.get("text") or ""
                            
                            # Put all skill-related data into metadata
                            resolved_embed["metadata"] = {
                                "app_id": embed_content.get("app_id"),
                                "skill_id": embed_content.get("skill_id"),
                                "status": embed_content.get("status") or embed_data.get("status"),
                                "result_count": embed_content.get("result_count"),
                                "query": embed_content.get("query"),
                                "provider": embed_content.get("provider"),
                                "url": embed_content.get("url")
                            }
                            # Include the actual results in metadata if not too large
                            if results:
                                resolved_embed["metadata"]["results"] = results
                        else:
                            # Fallback for other types
                            resolved_embed["content"] = embed_content.get("content", "")
                            resolved_embed["metadata"] = {k: v for k, v in embed_content.items() if k not in ["content", "type", "title"]}
                            if not resolved_embed["metadata"]:
                                resolved_embed["metadata"] = embed_content.get("metadata", {})

                        # Add common fields if present
                        if "url" in embed_content or "url" in embed_data:
                            resolved_embed["url"] = embed_content.get("url") or embed_data.get("url")
                        if "thumbnail" in embed_content or "thumbnail" in embed_data:
                            resolved_embed["thumbnail"] = embed_content.get("thumbnail") or embed_data.get("thumbnail")

                        embeds_list.append(resolved_embed)

                    else:
                        # If embed not found, provide placeholder info
                        placeholder_embed = {
                            "id": embed_id,
                            "type": "placeholder",
                            "content": f"Embed content for ID '{embed_id}' is not available.",
                            "metadata": {},
                            "error": "Content not found in cache"
                        }
                        embeds_list.append(placeholder_embed)

                except Exception as embed_error:
                    logger.error(f"Error resolving embed {embed_id}: {embed_error}", exc_info=True)
                    # Add error embed info
                    error_embed = {
                        "id": embed_id,
                        "type": "error",
                        "content": f"Error loading embed: {str(embed_error)}",
                        "metadata": {},
                        "error": str(embed_error)
                    }
                    embeds_list.append(error_embed)

        except Exception as e:
            logger.error(f"Error in _extract_and_resolve_embeds: {e}", exc_info=True)

        return embeds_list

    # Override get_metadata if you need to customize what BaseSkill provides,
    # or to add skill-specific metadata not covered by app.yml fields.
    # For now, the default BaseSkill.get_metadata() should be sufficient if app.yml is well-defined.
