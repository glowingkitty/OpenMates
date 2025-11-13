# backend/apps/ai/processing/main_processor.py
# Handles the main processing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import json
import httpx
import datetime
import os

# Import Pydantic models for type hinting
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.utils.llm_utils import call_main_llm_stream
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.apps.ai.llm_providers.mistral_client import ParsedMistralToolCall, MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata, ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import ParsedAnthropicToolCall, AnthropicUsageMetadata
from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService

# Import tool generator
from backend.apps.ai.processing.tool_generator import generate_tools_from_apps
# Import skill executor
from backend.apps.ai.processing.skill_executor import execute_skill_with_multiple_requests
# Import billing utilities
from backend.shared.python_utils.billing_utils import calculate_total_credits, MINIMUM_CREDITS_CHARGED


logger = logging.getLogger(__name__)

# Max iterations for tool calling to prevent infinite loops
MAX_TOOL_CALL_ITERATIONS = 5
DEFAULT_APP_INTERNAL_PORT = 8000
APPROX_MAX_CONVERSATION_TOKENS = 80000
AVG_CHARS_PER_TOKEN = 4
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


async def _publish_skill_status(
    cache_service: Optional[CacheService],
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    status: str,
    preview_data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> None:
    """
    Publish skill execution status update to Redis for WebSocket delivery.
    
    Args:
        cache_service: CacheService instance for publishing events
        task_id: Task ID for the skill execution
        request_data: AskSkillRequest containing user and chat info
        app_id: The app ID that owns the skill
        skill_id: The skill ID being executed
        status: Status of execution ('processing', 'finished', 'error')
        preview_data: Optional preview data for the skill results
        error: Optional error message if status is 'error'
    """
    if not cache_service:
        logger.debug(f"[Task ID: {task_id}] Cache service not available, skipping skill status publish")
        return
    
    try:
        # Construct the skill status payload matching frontend expectations
        skill_status_payload = {
            "type": "skill_execution_status",
            "event_for_client": "skill_execution_status",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "message_id": request_data.message_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "app_id": app_id,
            "skill_id": skill_id,
            "status": status,
            "preview_data": preview_data or {}
        }
        
        # Add error if present
        if error:
            skill_status_payload["error"] = error
        
        # Publish to Redis channel for WebSocket delivery
        # Channel format: ai_typing_indicator_events::{user_id_hash}
        channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
        await cache_service.publish_event(channel, skill_status_payload)
        logger.debug(
            f"[Task ID: {task_id}] Published skill status '{status}' for skill '{app_id}.{skill_id}' "
            f"to channel '{channel}'"
        )
    except Exception as e:
        logger.error(
            f"[Task ID: {task_id}] Failed to publish skill status for '{app_id}.{skill_id}': {e}",
            exc_info=True
        )


async def _charge_skill_credits(
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    results: List[Dict[str, Any]],
    parsed_args: Dict[str, Any],
    log_prefix: str
) -> None:
    """
    Calculate and charge credits for a skill execution.
    Creates usage entry automatically via BillingService.
    """
    try:
        # Get skill definition from app metadata
        app_metadata = discovered_apps_metadata.get(app_id)
        if not app_metadata:
            logger.warning(f"{log_prefix} App '{app_id}' not found in discovered apps metadata. Skipping skill billing.")
            return
        
        # Find the skill definition
        skill_def: Optional[AppSkillDefinition] = None
        for skill in app_metadata.skills or []:
            if skill.id == skill_id:
                skill_def = skill
                break
        
        if not skill_def:
            logger.warning(f"{log_prefix} Skill '{skill_id}' not found in app '{app_id}' metadata. Skipping skill billing.")
            return
        
        # Get pricing config from skill definition
        pricing_config = None
        if skill_def.pricing:
            pricing_config = skill_def.pricing.model_dump(exclude_none=True)
        
        # Calculate credits based on skill execution
        # For web.search: charge per search request (units_processed)
        units_processed = None
        if app_id == "web" and skill_id == "search":
            # Count number of search requests
            if "requests" in parsed_args and isinstance(parsed_args["requests"], list):
                units_processed = len(parsed_args["requests"])
            elif "query" in parsed_args:
                units_processed = 1
            else:
                units_processed = len(results) if results else 1
        
        # Calculate credits
        if pricing_config:
            credits_charged = calculate_total_credits(
                pricing_config=pricing_config,
                units_processed=units_processed
            )
        else:
            # Default to minimum charge if no pricing config
            credits_charged = MINIMUM_CREDITS_CHARGED
            logger.info(f"{log_prefix} No pricing config for skill '{app_id}.{skill_id}', using minimum charge: {credits_charged}")
        
        if credits_charged <= 0:
            logger.debug(f"{log_prefix} Calculated credits for skill '{app_id}.{skill_id}' is 0, skipping billing.")
            return
        
        # Prepare usage details
        usage_details = {
            "chat_id": request_data.chat_id,
            "message_id": request_data.message_id,
            "units_processed": units_processed
        }
        
        # Charge credits via internal API (this will also create usage entry)
        charge_payload = {
            "user_id": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "credits": credits_charged,
            "skill_id": skill_id,
            "app_id": app_id,
            "usage_details": usage_details
        }
        
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        
        async with httpx.AsyncClient() as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            logger.info(f"{log_prefix} Charging {credits_charged} credits for skill '{app_id}.{skill_id}'. Payload: {charge_payload}")
            response = await client.post(url, json=charge_payload, headers=headers, timeout=10.0)
            response.raise_for_status()
            logger.info(f"{log_prefix} Successfully charged {credits_charged} credits for skill '{app_id}.{skill_id}'. Response: {response.json()}")
            
    except httpx.HTTPStatusError as e:
        logger.error(f"{log_prefix} HTTP error charging credits for skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution
    except Exception as e:
        logger.error(f"{log_prefix} Error charging credits for skill '{app_id}.{skill_id}': {e}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution


async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    secrets_manager: Optional[SecretsManager] = None,
    cache_service: Optional[CacheService] = None
) -> AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]]:
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")
    
    # --- Request app settings/memories from client (zero-knowledge architecture) ---
    # The server NEVER decrypts app settings/memories - client decrypts using crypto API
    # Requests are stored as system messages in chat history (persist indefinitely, work across devices)
    loaded_app_settings_and_memories_content: Dict[str, Any] = {}
    if preprocessing_results.load_app_settings_and_memories and cache_service:
        try:
            # Import helper functions for app settings/memories requests
            from backend.core.api.app.utils.app_settings_memories_request import (
                check_chat_history_for_app_settings_memories,
                create_app_settings_memories_request_message
            )
            
            # First, check chat history for existing app settings/memories request messages
            # Extract accepted responses from the most recent request
            requested_keys = preprocessing_results.load_app_settings_and_memories
            
            # Convert message_history to list of dicts for checking
            message_history_dicts = [msg.model_dump() if hasattr(msg, 'model_dump') else dict(msg) for msg in request_data.message_history]
            
            # Check for existing accepted responses in chat history
            accepted_responses = await check_chat_history_for_app_settings_memories(
                message_history=message_history_dicts,
                requested_keys=requested_keys
            )
            
            if accepted_responses:
                logger.info(f"{log_prefix} Found {len(accepted_responses)} accepted app settings/memories responses in chat history")
                loaded_app_settings_and_memories_content = accepted_responses
            
            # Check if we need to create a new request for missing keys
            missing_keys = [key for key in requested_keys if key not in accepted_responses]
            
            if missing_keys:
                logger.info(f"{log_prefix} Creating new app settings/memories request for {len(missing_keys)} missing keys")
                # Create new system message request in chat history
                # Client will encrypt with chat key and store it
                request_id = await create_app_settings_memories_request_message(
                    chat_id=request_data.chat_id,
                    requested_keys=missing_keys,
                    cache_service=cache_service,
                    connection_manager=None,  # Celery tasks run in separate processes, can't access WebSocket manager directly
                    user_id=request_data.user_id,
                    device_fingerprint_hash=None  # Will use first available device connection
                )
                
                if request_id:
                    logger.info(f"{log_prefix} Created app settings/memories request {request_id} - client will respond when ready (may be hours/days later)")
                else:
                    logger.warning(f"{log_prefix} Failed to create app settings/memories request message")
            else:
                logger.info(f"{log_prefix} All requested app settings/memories keys have accepted responses in chat history")
            
            # Continue processing immediately (no waiting)
            # If data is missing, the conversation continues without it
            # User can respond hours/days later, and the data will be available for the next message
            
        except Exception as e:
            logger.error(f"{log_prefix} Error handling app settings/memories requests: {e}", exc_info=True)
            # Continue without app settings/memories - don't fail the entire request

    prompt_parts = []
    now = datetime.datetime.now(datetime.timezone.utc)
    date_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    prompt_parts.append(f"Current date and time: {date_time_str}")
    prompt_parts.append(base_instructions.get("base_ethics_instruction", ""))
    selected_mate_config = next((mate for mate in all_mates_configs if mate.id == preprocessing_results.selected_mate_id), None)
    if selected_mate_config:
        prompt_parts.append(selected_mate_config.default_system_prompt)
    # Insert creator_and_used_model_instruction right after the mate-specific prompt
    # This informs the user who created the assistant and which model (name and id) powers the response.
    try:
        creator_and_model_instruction_template = base_instructions.get("creator_and_used_model_instruction")
        if creator_and_model_instruction_template:
            # Prefer the model name from preprocessing; fall back to suffix of the model id or a generic label
            selected_model_id: str = preprocessing_results.selected_main_llm_model_id or ""
            # If model name is missing, use the id's suffix (after provider prefix) as a reasonable display name
            derived_model_name: str = (
                preprocessing_results.selected_main_llm_model_name
                or (selected_model_id.split("/", 1)[-1] if selected_model_id else "AI")
            )

            filled_instruction = creator_and_model_instruction_template.format(
                MODEL_NAME=derived_model_name,
                MODEL_ID=selected_model_id,
            )
            prompt_parts.append(filled_instruction)
            logger.debug(
                f"{log_prefix} Added creator_and_used_model_instruction with model_name='{derived_model_name}', model_id='{selected_model_id}'."
            )
        else:
            logger.debug(f"{log_prefix} Base instructions missing 'creator_and_used_model_instruction'; skipping injection.")
    except Exception as e:
        # Robust error handling to ensure prompt construction never fails because of formatting issues
        logger.error(
            f"{log_prefix} Failed to inject creator_and_used_model_instruction: {e}",
            exc_info=True,
        )
    # TODO: Update this key once app use is implemented - currently using base_capabilities_instruction
    # which explains what the chatbot can and cannot do yet
    prompt_parts.append(base_instructions.get("base_capabilities_instruction", ""))
    prompt_parts.append(base_instructions.get("follow_up_instruction", ""))
    if loaded_app_settings_and_memories_content:
        settings_and_memories_prompt_section = ["\n--- Relevant Information from Your App Settings and Memories ---"]
        for key, value in loaded_app_settings_and_memories_content.items():
            value_str = json.dumps(value) if not isinstance(value, str) else value
            settings_and_memories_prompt_section.append(f"- {key}: {value_str}")
        prompt_parts.append("\n".join(settings_and_memories_prompt_section))

    active_focus_prompt_text: Optional[str] = None
    if request_data.active_focus_id:
        try:
            app_id_of_focus, focus_id_in_app = request_data.active_focus_id.split('.', 1)
            app_metadata_for_focus = discovered_apps_metadata.get(app_id_of_focus)
            if app_metadata_for_focus and app_metadata_for_focus.focuses:
                for focus_def in app_metadata_for_focus.focuses:
                    if focus_def.id == focus_id_in_app:
                        active_focus_prompt_text = focus_def.systemprompt
                        break
        except Exception as e:
            logger.error(f"{log_prefix} Error processing active_focus_id '{request_data.active_focus_id}': {e}", exc_info=True)
    if active_focus_prompt_text:
        prompt_parts.insert(0, f"--- Active Focus: {request_data.active_focus_id} ---\n{active_focus_prompt_text}\n--- End Active Focus ---")

    full_system_prompt = "\n\n".join(filter(None, prompt_parts))
    
    # Generate tool definitions from discovered apps using the tool generator
    # Filter by preselected skills from preprocessing if available
    preselected_skills = None
    if hasattr(preprocessing_results, 'relevant_app_skills') and preprocessing_results.relevant_app_skills:
        preselected_skills = set(preprocessing_results.relevant_app_skills)
        logger.debug(f"{log_prefix} Using preselected skills: {preselected_skills}")
    
    assigned_app_ids = selected_mate_config.assigned_apps if selected_mate_config else None
    available_tools_for_llm = generate_tools_from_apps(
        discovered_apps_metadata=discovered_apps_metadata,
        assigned_app_ids=assigned_app_ids,
        preselected_skills=preselected_skills
    )

    current_message_history: List[Dict[str, Any]] = [msg.model_dump(exclude_none=True) for msg in request_data.message_history]
    
    # --- End of existing logic ---

    # Validate that we have a model_id before proceeding with main processing
    # This prevents crashes when preprocessing fails and model_id is None
    if not preprocessing_results.selected_main_llm_model_id:
        error_msg = (
            f"{log_prefix} Cannot proceed with main processing: selected_main_llm_model_id is None. "
            f"This usually indicates preprocessing failed (rejection_reason: {preprocessing_results.rejection_reason}). "
            f"Main processing requires a valid model_id."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None
    
    for iteration in range(MAX_TOOL_CALL_ITERATIONS):
        logger.info(f"{log_prefix} LLM call iteration {iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}")

        llm_stream = call_main_llm_stream(
            task_id=task_id,
            system_prompt=full_system_prompt,
            message_history=current_message_history,
            model_id=preprocessing_results.selected_main_llm_model_id,
            temperature=preprocessing_results.llm_response_temp,
            secrets_manager=secrets_manager,
            tools=available_tools_for_llm if available_tools_for_llm else None,
            tool_choice="auto"
        )

        current_turn_text_buffer = []
        tool_calls_for_this_turn: List[Union[ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedOpenAIToolCall]] = []
        llm_turn_had_content = False
        
        async for chunk in aggregate_paragraphs(llm_stream):
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata)):
                usage = chunk
                continue
            if isinstance(chunk, (ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedOpenAIToolCall)):
                tool_calls_for_this_turn.append(chunk)
            elif isinstance(chunk, str):
                llm_turn_had_content = True
                if not tool_calls_for_this_turn:
                    yield chunk
                else:
                    current_turn_text_buffer.append(chunk)
            else:
                logger.warning(f"{log_prefix} Received unexpected chunk type from stream: {type(chunk)}")

        final_buffered_text_for_turn = "".join(current_turn_text_buffer)

        if not tool_calls_for_this_turn:
            break

        logger.info(f"{log_prefix} Processing {len(tool_calls_for_this_turn)} tool call(s).")
        
        assistant_message_content_for_history = final_buffered_text_for_turn
        assistant_message_tool_calls_formatted = [{"id": tc.tool_call_id, "type": "function", "function": {"name": tc.function_name, "arguments": tc.function_arguments_raw}} for tc in tool_calls_for_this_turn]
        assistant_message: Dict[str, Any] = {"role": "assistant", "content": assistant_message_content_for_history or None, "tool_calls": assistant_message_tool_calls_formatted}
        current_message_history.append(assistant_message)

        # Execute all tool calls (skills) in this turn
        for tool_call in tool_calls_for_this_turn:
            tool_name = tool_call.function_name
            tool_arguments_str = tool_call.function_arguments_raw
            tool_call_id = tool_call.tool_call_id
            tool_result_content_str: str
            
            try:
                # Parse function arguments
                parsed_args = json.loads(tool_arguments_str)
                
                # Extract app_id and skill_id from tool name (format: "app_id.skill_id")
                app_id, skill_id = tool_name.split('.', 1)
                
                logger.debug(f"{log_prefix} Executing skill '{tool_name}' with app_id='{app_id}', skill_id='{skill_id}'")
                
                # Publish "processing" status when skill starts
                await _publish_skill_status(
                    cache_service=cache_service,
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    status="processing"
                )
                
                # Execute skill with support for multiple parallel requests
                results = await execute_skill_with_multiple_requests(
                    app_id=app_id,
                    skill_id=skill_id,
                    arguments=parsed_args,
                    timeout=30.0
                )
                
                # Extract preview data from results for status update
                # For web search, extract query and results
                preview_data: Dict[str, Any] = {}
                if app_id == "web" and skill_id == "search":
                    # Extract query from arguments or results
                    if "query" in parsed_args:
                        preview_data["query"] = parsed_args["query"]
                    elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                        # Use first request's query if multiple
                        first_request = parsed_args["requests"][0]
                        preview_data["query"] = first_request.get("query", "")
                    
                    # Default provider for Brave Search
                    preview_data["provider"] = "Brave Search"
                    
                    # Extract results from skill response
                    # SearchResponse has "previews" field containing the results
                    if len(results) == 1:
                        result = results[0]
                        if "previews" in result:
                            preview_data["results"] = result["previews"]
                    elif len(results) > 1:
                        # Multiple results - combine previews from all results
                        all_previews = []
                        for result in results:
                            if "previews" in result:
                                all_previews.extend(result["previews"])
                        preview_data["results"] = all_previews
                        preview_data["completed_count"] = len(results)
                        preview_data["total_count"] = len(results)
                
                # If multiple results, combine them; otherwise use single result
                if len(results) == 1:
                    tool_result_content_str = json.dumps(results[0])
                else:
                    # Multiple results - combine into a list
                    tool_result_content_str = json.dumps({"results": results, "count": len(results)})
                
                logger.debug(f"{log_prefix} Skill '{tool_name}' executed successfully, returned {len(results)} result(s)")
                
                # Calculate and charge credits for skill execution
                await _charge_skill_credits(
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    discovered_apps_metadata=discovered_apps_metadata,
                    results=results,
                    parsed_args=parsed_args,
                    log_prefix=log_prefix
                )
                
                # Publish "finished" status with preview data
                await _publish_skill_status(
                    cache_service=cache_service,
                    task_id=task_id,
                    request_data=request_data,
                    app_id=app_id,
                    skill_id=skill_id,
                    status="finished",
                    preview_data=preview_data if preview_data else None
                )
                
            except json.JSONDecodeError as e:
                logger.error(f"{log_prefix} Invalid JSON in tool arguments for '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid JSON in function arguments.", "details": str(e)})
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('.', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid JSON in function arguments"
                    )
                except:
                    pass  # Don't fail if status publish fails
            except ValueError as e:
                # Invalid tool name format
                logger.error(f"{log_prefix} Invalid tool name format '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid tool name format.", "details": str(e)})
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('.', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid tool name format"
                    )
                except:
                    pass  # Don't fail if status publish fails
            except Exception as e:
                logger.error(f"{log_prefix} Error executing tool '{tool_name}': {e}", exc_info=True)
                tool_result_content_str = json.dumps({"error": "Skill execution failed.", "details": str(e)})
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('.', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error=str(e)
                    )
                except:
                    pass  # Don't fail if status publish fails
            
            # Add tool response to message history
            tool_response_message = {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": tool_result_content_str
            }
            current_message_history.append(tool_response_message)

        if iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            yield "\n[Max tool call iterations reached.]"
            break

    if usage:
        yield usage

    logger.info(f"{log_prefix} Main processing stream finished.")
