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
    mate_id: Optional[str] = Field(default=None, description="The ID of the Mate to use. If None, AI will select.")
    active_focus_id: Optional[str] = Field(default=None, description="The ID of the currently active focus, if any.")
    user_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict, description="User-specific preferences.")

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

class OpenAIChoice(BaseModel):
    index: int = Field(..., description="The index of the choice.")
    message: OpenAIMessage = Field(..., description="The message generated by the model.")
    finish_reason: Optional[str] = Field(default=None, description="The reason the model stopped generating tokens.")

class OpenAIUsage(BaseModel):
    prompt_tokens: int = Field(..., description="Number of tokens in the prompt.")
    completion_tokens: int = Field(..., description="Number of tokens in the completion.")
    total_tokens: int = Field(..., description="Total number of tokens used.")

class OpenAICompletionResponse(BaseModel):
    id: str = Field(..., description="A unique identifier for the completion.")
    object: str = Field(default="chat.completion", description="The object type.")
    created: int = Field(..., description="The Unix timestamp when the completion was created.")
    model: str = Field(..., description="The model used for completion.")
    choices: List[OpenAIChoice] = Field(..., description="A list of completion choices.")
    usage: Optional[OpenAIUsage] = Field(default=None, description="Usage statistics for the completion request.")

class OpenAIDelta(BaseModel):
    role: Optional[str] = Field(default=None, description="The role of the author of this message.")
    content: Optional[str] = Field(default=None, description="The contents of the chunk message.")
    embeds: Optional[List[Dict[str, Any]]] = Field(default=None, description="Embedded content resolved for streaming API users.")

class OpenAIStreamChoice(BaseModel):
    index: int = Field(..., description="The index of the choice.")
    delta: OpenAIDelta = Field(..., description="A chat completion delta generated by streamed model responses.")
    finish_reason: Optional[str] = Field(default=None, description="The reason the model stopped generating tokens.")

class OpenAIStreamResponse(BaseModel):
    id: str = Field(..., description="A unique identifier for the completion.")
    object: str = Field(default="chat.completion.chunk", description="The object type.")
    created: int = Field(..., description="The Unix timestamp when the completion was created.")
    model: str = Field(..., description="The model used for completion.")
    choices: List[OpenAIStreamChoice] = Field(..., description="A list of completion choices.")


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
        """
        # Generate required IDs for stateless operation
        chat_id = f"openai-{uuid.uuid4()}" if not openai_request.is_incognito else "incognito"
        message_id = f"msg-{uuid.uuid4()}"
        user_id = "openai-api-user"  # Static user for API requests
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]

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
            mate_id=openai_request.mate_id,
            active_focus_id=openai_request.focus_mode,
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

            yield f"data: {initial_chunk.model_dump_json()}\n\n"

            # Subscribe to Redis stream for real-time updates
            redis_channel = f"chat_stream::{internal_request.chat_id}"

            # Import cache service
            from backend.core.api.app.services.cache import CacheService
            cache_service = CacheService()

            # Collect all content to extract embeds at the end
            full_response_content = ""

            # Listen to Redis stream
            async for chunk_data in self._listen_to_redis_stream(cache_service, redis_channel, task_id):
                if chunk_data is None:
                    # Task completed
                    break

                # Convert Redis chunk to OpenAI format
                if isinstance(chunk_data, str):
                    # Track full content for embed extraction
                    full_response_content += chunk_data

                    # Text content chunk
                    content_chunk = OpenAIStreamResponse(
                        id=completion_id,
                        created=created_timestamp,
                        model=model_name,
                        choices=[
                            OpenAIStreamChoice(
                                index=0,
                                delta=OpenAIDelta(content=chunk_data),
                                finish_reason=None
                            )
                        ]
                    )
                    yield f"data: {content_chunk.model_dump_json()}\n\n"

            # Extract embeds after streaming is complete
            embeds_content = await self._extract_and_resolve_embeds(full_response_content, internal_request.chat_id)

            # Send embeds as additional data if found
            if embeds_content:
                embed_chunk = OpenAIStreamResponse(
                    id=completion_id,
                    created=created_timestamp,
                    model=model_name,
                    choices=[
                        OpenAIStreamChoice(
                            index=0,
                            delta=OpenAIDelta(embeds=embeds_content),
                            finish_reason=None
                        )
                    ]
                )
                yield f"data: {embed_chunk.model_dump_json()}\n\n"

            # Send final chunk
            final_chunk = OpenAIStreamResponse(
                id=completion_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    OpenAIStreamChoice(
                        index=0,
                        delta=OpenAIDelta(),
                        finish_reason="stop"
                    )
                ]
            )

            yield f"data: {final_chunk.model_dump_json()}\n\n"
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
        Yields text chunks as they arrive and monitors task completion.
        """
        import json

        logger.info(f"Listening to Redis stream: {redis_channel} for task: {task_id}")

        # Track task completion
        task_completed = False
        content_buffer = ""

        try:
            # Subscribe to the specific channel using the same pattern as WebSocket handler
            async for message in cache_service.subscribe_to_channel(redis_channel):
                if message is None:
                    continue

                try:
                    # Parse the Redis message (same format as WebSocket handler)
                    if isinstance(message, dict):
                        data = message.get("data", {})
                    else:
                        # Message might be JSON string
                        data = json.loads(message) if isinstance(message, str) else message

                    # Extract payload data
                    if isinstance(data, dict):
                        chunk_type = data.get("chunk_type", 1)
                        content = data.get("content", "")
                        is_final = data.get("is_final", False)
                        message_task_id = data.get("task_id", "")

                        # Only process messages for our specific task
                        if message_task_id == task_id:
                            if chunk_type == 1 and content:  # Content chunk
                                # Stream content as it arrives
                                yield content
                                content_buffer += content

                            elif is_final:  # Final marker
                                logger.info(f"Received final marker for task: {task_id}")
                                task_completed = True
                                break

                except Exception as parse_e:
                    logger.debug(f"Redis message parse error (normal): {parse_e}")
                    continue

                # Add timeout protection
                if task_completed:
                    break

        except Exception as e:
            logger.error(f"Error in Redis stream listener: {e}", exc_info=True)

        logger.info(f"Finished listening to Redis stream for task: {task_id}, received {len(content_buffer)} characters")

    async def _handle_openai_sync_response(self, internal_request: AskSkillRequest, openai_request: OpenAICompletionRequest) -> OpenAICompletionResponse:
        """
        Handle non-streaming OpenAI-compatible response.
        Waits for the Celery task to complete and returns the full response.
        """
        completion_id = f"chatcmpl-{uuid.uuid4()}"
        created_timestamp = int(time.time())
        model_name = openai_request.model or "openmates-ai"

        try:
            # Execute the internal request (this dispatches to Celery)
            internal_response = await self._handle_internal_request(internal_request)
            task_id = internal_response.task_id

            # Collect all content by listening to the Redis stream
            redis_channel = f"chat_stream::{internal_request.chat_id}"

            # Import cache service
            from backend.core.api.app.services.cache import CacheService
            cache_service = CacheService()

            # Collect all streaming content
            response_content = ""
            async for chunk_data in self._listen_to_redis_stream(cache_service, redis_channel, task_id):
                if chunk_data:
                    response_content += chunk_data

            # If no content was collected, provide a fallback message
            if not response_content.strip():
                response_content = "I'm processing your request. Please try again or check the task status if this persists."

            # Extract and resolve embed content for CLI/API users
            embeds_content = await self._extract_and_resolve_embeds(response_content, internal_request.chat_id)

            # Create the assistant message with embed content included
            assistant_message = OpenAIMessage(
                role="assistant",
                content=response_content
            )

            # Add embeds as additional data if any were found
            if embeds_content:
                assistant_message.embeds = embeds_content

            response = OpenAICompletionResponse(
                id=completion_id,
                created=created_timestamp,
                model=model_name,
                choices=[
                    OpenAIChoice(
                        index=0,
                        message=assistant_message,
                        finish_reason="stop"
                    )
                ],
                usage=OpenAIUsage(
                    prompt_tokens=sum(len(msg.content.split()) for msg in openai_request.messages),
                    completion_tokens=len(response_content.split()),
                    total_tokens=sum(len(msg.content.split()) for msg in openai_request.messages) + len(response_content.split())
                )
            )

            return response

        except Exception as e:
            logger.error(f"Error in OpenAI sync response: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error processing OpenAI request: {str(e)}")

    async def _extract_and_resolve_embeds(self, response_content: str, chat_id: str) -> List[Dict[str, Any]]:
        """
        Extract and resolve embed content from response text.
        For API users, we need to provide the actual embed content, not just JSON references.
        """
        import re
        import json

        embeds_list = []

        try:
            # Pattern to match JSON code blocks with embed references
            # This matches ```json\n{"type": "...", "embed_id": "..."}\n```
            json_block_pattern = r'```json\s*\n\s*\{\s*"type"\s*:\s*"[^"]*"\s*,\s*"embed_id"\s*:\s*"([^"]+)"\s*\}\s*\n\s*```'
            embed_matches = re.findall(json_block_pattern, response_content, re.MULTILINE | re.DOTALL)

            if not embed_matches:
                return embeds_list

            # Import necessary services for embed resolution
            from backend.core.api.app.services.cache import CacheService
            cache_service = CacheService()

            for embed_id in embed_matches:
                try:
                    # Retrieve embed content from cache/storage
                    # Use the correct cache key pattern as used by the existing embed system
                    embed_key = f"embed:{embed_id}"
                    embed_data = await cache_service.get(embed_key)

                    if embed_data:
                        # The embed_data from cache is TOON-encoded content
                        # We need to decode it to get the actual content
                        try:
                            from toon_format import decode
                            # Decode the TOON-encoded content
                            if isinstance(embed_data, str):
                                embed_content = decode(embed_data)
                            else:
                                # Fallback to JSON parsing if not a string
                                embed_content = json.loads(embed_data) if isinstance(embed_data, str) else embed_data
                        except ImportError:
                            logger.warning("TOON decoder not available, using JSON fallback")
                            # Fallback to JSON parsing if TOON decoder not available
                            if isinstance(embed_data, str):
                                try:
                                    embed_content = json.loads(embed_data)
                                except json.JSONDecodeError:
                                    embed_content = {"content": embed_data, "type": "unknown"}
                            else:
                                embed_content = embed_data
                        except Exception as decode_error:
                            logger.warning(f"TOON decode failed for embed {embed_id}, trying JSON fallback: {decode_error}")
                            # Fallback to JSON if TOON decode fails
                            if isinstance(embed_data, str):
                                try:
                                    embed_content = json.loads(embed_data)
                                except json.JSONDecodeError:
                                    embed_content = {"content": embed_data, "type": "unknown"}
                            else:
                                embed_content = embed_data

                        # Format embed for API response
                        resolved_embed = {
                            "id": embed_id,
                            "type": embed_content.get("type", "unknown"),
                            "content": embed_content.get("content", ""),
                            "metadata": embed_content.get("metadata", {}),
                            "url": embed_content.get("url"),
                            "thumbnail": embed_content.get("thumbnail"),
                            "title": embed_content.get("title", "Embedded Content")
                        }

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
