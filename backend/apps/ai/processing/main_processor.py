# backend/apps/ai/processing/main_processor.py
# Handles the main processing stage of AI skill requests.

import logging
from typing import Dict, Any, List, Optional, AsyncIterator
import json
import httpx # Added for actual skill execution

# Import Pydantic models for type hinting
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.utils.llm_utils import call_main_llm_stream
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.apps.ai.llm_providers.mistral_client import ParsedMistralToolCall
from backend.apps.base_app import AppYAML, AppSkillDefinition # For discovered_apps_metadata
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService


logger = logging.getLogger(__name__)

# Max iterations for tool calling to prevent infinite loops
MAX_TOOL_CALL_ITERATIONS = 5
DEFAULT_APP_INTERNAL_PORT = 8000 # Standard internal port for our apps
APPROX_MAX_CONVERSATION_TOKENS = 80000 # Suggested limit for starting a new chat
AVG_CHARS_PER_TOKEN = 4 # Rough average for token estimation

async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML], # Added for skill discovery
    secrets_manager: Optional[SecretsManager] = None # Added SecretsManager
) -> AsyncIterator[str]: # Returns an async generator of string chunks
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.

    Args:
        task_id: The ID of the Celery task, for logging context.
        request_data: The original data from the AskSkillRequest.
        preprocessing_results: The output from the handle_preprocessing function.
        base_instructions: Loaded content from base_instructions.yml.
        directus_service: Instance of DirectusService to fetch app memories.
        user_vault_key_id: The user's Vault key ID for decrypting memories.
        all_mates_configs: A list of all loaded MateConfig objects.
        discovered_apps_metadata: Metadata of all enabled and discovered apps.
        # active_focus_prompt: System prompt from an active focus, if any.

    Yields:
        str: Chunks of the assistant's final response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")
    logger.debug(f"{log_prefix} Preprocessing results: {preprocessing_results.model_dump_json(indent=2)}")
    logger.debug(f"{log_prefix} User Vault Key ID available: {'Yes' if user_vault_key_id else 'No'}")
    logger.debug(f"{log_prefix} Received {len(all_mates_configs)} mate configurations and {len(discovered_apps_metadata)} discovered app metadata entries.")

    loaded_app_settings_and_memories_content: Dict[str, Any] = {}

    # 1. Settings & Memory Loading:
    if preprocessing_results.load_app_settings_and_memories:
        logger.info(f"{log_prefix} Attempting to load app settings/memories: {preprocessing_results.load_app_settings_and_memories}")
        if not user_vault_key_id:
            logger.warning(f"{log_prefix} User vault key ID is missing. Cannot decrypt and load app settings/memories.")
        else:
            for item_full_key in preprocessing_results.load_app_settings_and_memories:
                try:
                    app_id, item_key = item_full_key.split('.', 1)
                    logger.debug(f"{log_prefix} Loading item '{item_key}' for app '{app_id}' for user '{request_data.user_id_hash}'.")
                    
                    decrypted_value = await directus_service.app_settings_and_memories.get_decrypted_user_app_item_value(
                        user_id_hash=request_data.user_id_hash,
                        app_id=app_id,
                        item_key=item_key,
                        user_vault_key_id=user_vault_key_id
                    )
                    
                    if decrypted_value is not None:
                        loaded_app_settings_and_memories_content[item_full_key] = decrypted_value # Storing with full key for clarity
                        logger.info(f"{log_prefix} Successfully loaded and decrypted app item '{item_full_key}'. Type: {type(decrypted_value)}")
                    else:
                        logger.warning(f"{log_prefix} Failed to load or decrypt app item '{item_full_key}'. It will not be included in the prompt.")
                except ValueError:
                    logger.error(f"{log_prefix} Invalid format for item key '{item_full_key}'. Expected 'app_id.item_key'. Skipping.")
                except Exception as e:
                    logger.error(f"{log_prefix} Error loading app item '{item_full_key}': {e}", exc_info=True)
        logger.info(f"{log_prefix} Loaded app settings/memories content (keys): {list(loaded_app_settings_and_memories_content.keys())}")
    else:
        logger.info(f"{log_prefix} No app settings/memories requested for loading by preprocessor.")

    # 2. Assemble Full System Prompt:
    prompt_parts = []

    # Base Ethics
    base_ethics_instruction = base_instructions.get("base_ethics_instruction")
    if base_ethics_instruction:
        prompt_parts.append(base_ethics_instruction)
    else:
        logger.warning(f"{log_prefix} 'base_ethics_instruction' not found in base_instructions.")

    # Mate Default System Prompt
    mate_default_prompt = None
    selected_mate_config: Optional[MateConfig] = None
    if preprocessing_results.selected_mate_id:
        selected_mate_config = next((mate for mate in all_mates_configs if mate.id == preprocessing_results.selected_mate_id), None)
        if selected_mate_config:
            mate_default_prompt = selected_mate_config.default_system_prompt
            prompt_parts.append(mate_default_prompt)
            logger.info(f"{log_prefix} Added default system prompt for Mate ID: {preprocessing_results.selected_mate_id}")
        else:
            logger.warning(f"{log_prefix} Selected Mate ID '{preprocessing_results.selected_mate_id}' not found in all_mates_configs. Skipping mate prompt.")
    else:
        logger.info(f"{log_prefix} No Mate ID selected by preprocessor. Proceeding without a mate-specific default prompt.")

    # Base App Use Instruction
    base_app_use_instruction = base_instructions.get("base_app_use_instruction")
    if base_app_use_instruction:
        prompt_parts.append(base_app_use_instruction)
    else:
        logger.warning(f"{log_prefix} 'base_app_use_instruction' not found in base_instructions.")

    # Follow Up Instruction
    follow_up_instruction = base_instructions.get("follow_up_instruction")
    if follow_up_instruction:
        prompt_parts.append(follow_up_instruction)
    else:
        logger.warning(f"{log_prefix} 'follow_up_instruction' not found in base_instructions.")

    # Integrate Loaded App Settings and Memories
    if loaded_app_settings_and_memories_content:
        settings_and_memories_prompt_section = ["\n--- Relevant Information from Your App Settings and Memories ---"]
        for key, value in loaded_app_settings_and_memories_content.items():
            # Value can be any JSON-parsable type, convert to string for prompt
            value_str = json.dumps(value) if not isinstance(value, str) else value
            settings_and_memories_prompt_section.append(f"- {key}: {value_str}")
        prompt_parts.append("\n".join(settings_and_memories_prompt_section))
        logger.info(f"{log_prefix} Added {len(loaded_app_settings_and_memories_content)} loaded app settings/memories to the prompt.")

    # TODO: User-configured App-Specific Instructions (Future V2)
    # This would involve fetching user-specific overrides or additions for prompts related to certain apps.

    # Active Focus System Prompt
    active_focus_prompt_text: Optional[str] = None
    if request_data.active_focus_id:
        logger.info(f"{log_prefix} Active focus ID provided: {request_data.active_focus_id}. Attempting to load its system prompt.")
        try:
            # Focus ID is expected to be "app_id.focus_id_in_app_yaml"
            app_id_of_focus, focus_id_in_app = request_data.active_focus_id.split('.', 1)
            
            app_metadata_for_focus = discovered_apps_metadata.get(app_id_of_focus)
            if app_metadata_for_focus and app_metadata_for_focus.focuses:
                for focus_def in app_metadata_for_focus.focuses:
                    if focus_def.id == focus_id_in_app:
                        active_focus_prompt_text = focus_def.systemprompt
                        logger.info(f"{log_prefix} Found and loaded system prompt for active focus '{request_data.active_focus_id}' from app '{app_id_of_focus}'.")
                        break
                if not active_focus_prompt_text:
                    logger.warning(f"{log_prefix} Active focus ID '{focus_id_in_app}' not found within app '{app_id_of_focus}'s defined focuses.")
            else:
                logger.warning(f"{log_prefix} App metadata for app_id '{app_id_of_focus}' (from active_focus_id) not found or has no focuses defined.")
        except ValueError:
            logger.error(f"{log_prefix} Invalid active_focus_id format: '{request_data.active_focus_id}'. Expected 'app_id.focus_id'.")
        except Exception as e:
            logger.error(f"{log_prefix} Error processing active_focus_id '{request_data.active_focus_id}': {e}", exc_info=True)

    if active_focus_prompt_text:
        # Prepend focus prompt so it takes precedence or sets a specific context early.
        prompt_parts.insert(0, f"--- Active Focus: {request_data.active_focus_id} ---\n{active_focus_prompt_text}\n--- End Active Focus ---")

    full_system_prompt = "\n\n".join(filter(None, prompt_parts)) # Join non-empty parts
    logger.info(f"{log_prefix} Assembled full system prompt.")
    logger.debug(f"{log_prefix} Full System Prompt:\n{full_system_prompt}")


    # 3. Assemble Available Tools for LLM:
    available_tools_for_llm: List[Dict[str, Any]] = []
    if selected_mate_config and selected_mate_config.assigned_apps and discovered_apps_metadata:
        logger.info(f"{log_prefix} Assembling tools for Mate '{selected_mate_config.id}' based on assigned apps: {selected_mate_config.assigned_apps}")
        for app_id in selected_mate_config.assigned_apps:
            app_meta = discovered_apps_metadata.get(app_id)
            if app_meta and app_meta.skills:
                for skill_def in app_meta.skills:
                    if skill_def.stage == "production": # Only production skills
                        tool_name = f"{app_id}.{skill_def.id}"
                        # Generic parameters for now, to be refined based on actual skill needs
                        # The skill itself would define its expected parameters in its app.yml eventually.
                        parameters_schema = {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": f"The input or query for the {skill_def.name} skill."
                                }
                                # TODO: Add more specific parameters based on skill_def.parameters if available
                            },
                            "required": ["query"] # Assuming 'query' is a common basic parameter
                        }
                        # If skill_def has a more specific parameter definition, use it.
                        # For now, this is a placeholder.
                        # if hasattr(skill_def, 'parameters_schema') and skill_def.parameters_schema:
                        #     parameters_schema = skill_def.parameters_schema

                        available_tools_for_llm.append({
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "description": skill_def.description or f"Execute the {skill_def.name} skill from the {app_meta.name} app.",
                                "parameters": parameters_schema
                            }
                        })
                        logger.debug(f"{log_prefix} Added tool: {tool_name} for app {app_id}")
        logger.info(f"{log_prefix} Assembled {len(available_tools_for_llm)} tools for the LLM.")
    else:
        logger.info(f"{log_prefix} No assigned apps for Mate or no discovered metadata, or no mate selected. No tools will be available to the LLM.")

    # 4. LLM Interaction Loop (for tool calls)
    current_message_history: List[Dict[str, Any]] = [msg.model_dump(exclude_none=True) for msg in request_data.message_history]

    # 4.a Check conversation token length before starting LLM interaction
    total_chars_in_history = 0
    for message in current_message_history:
        if isinstance(message.get("content"), str):
            total_chars_in_history += len(message.get("content", ""))
        elif isinstance(message.get("content"), list): # Handle cases like tool calls where content is a list of parts
            for part in message.get("content", []):
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    total_chars_in_history += len(part.get("text", ""))
    
    estimated_tokens_in_history = total_chars_in_history / AVG_CHARS_PER_TOKEN
    logger.info(f"{log_prefix} Estimated tokens in current history: {estimated_tokens_in_history:.0f} (based on {total_chars_in_history} chars)")

    if estimated_tokens_in_history > APPROX_MAX_CONVERSATION_TOKENS:
        logger.warning(
            f"{log_prefix} Conversation history ({estimated_tokens_in_history:.0f} tokens) "
            f"exceeds threshold ({APPROX_MAX_CONVERSATION_TOKENS} tokens). Suggesting new chat."
        )
        yield (
            "This conversation is getting quite long, which can sometimes affect performance "
            "and focus. To ensure the best experience, I recommend starting a new chat for new topics. "
            "Would you like to continue this current chat, or shall we start fresh?"
        )
        # Stop further processing for this request. The user will see the suggestion.
        return

    for iteration in range(MAX_TOOL_CALL_ITERATIONS):
        logger.info(f"{log_prefix} LLM call iteration {iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}")

        llm_stream = call_main_llm_stream(
            task_id=task_id, # Pass task_id for logging within call_main_llm_stream
            system_prompt=full_system_prompt,
            message_history=current_message_history,
            model_id=preprocessing_results.selected_main_llm_model_id,
            temperature=preprocessing_results.llm_response_temp,
            secrets_manager=secrets_manager, # Pass SecretsManager
            tools=available_tools_for_llm if available_tools_for_llm else None, # Pass None if no tools
            tool_choice="auto" # Let the LLM decide if it wants to use tools
        )

        assistant_response_text_chunks = []
        tool_calls_for_this_turn: List[ParsedMistralToolCall] = []
        
        # Aggregate paragraphs and process tool calls from the stream
        async for chunk in aggregate_paragraphs(llm_stream): # aggregate_paragraphs yields str or ParsedMistralToolCall
            if isinstance(chunk, ParsedMistralToolCall):
                logger.info(f"{log_prefix} LLM requested tool call: {chunk.function.name} with ID {chunk.id}")
                tool_calls_for_this_turn.append(chunk)
            elif isinstance(chunk, str):
                assistant_response_text_chunks.append(chunk)
                # If this is the final iteration or no tools are being called in this turn,
                # we can yield text immediately.
                # However, if tools ARE called, we should wait to yield text until after tool results.
                # For simplicity in this loop, we'll collect all text for the turn first.
            else:
                logger.warning(f"{log_prefix} Received unexpected chunk type from stream: {type(chunk)}")

        current_assistant_response_content = "".join(assistant_response_text_chunks)

        if not tool_calls_for_this_turn:
            # No tool calls, this is the final response (or part of it)
            logger.info(f"{log_prefix} No tool calls in this iteration. Streaming final response content.")
            if current_assistant_response_content:
                yield current_assistant_response_content
            # If there was no content and no tool calls, it might be an empty response.
            break # Exit the loop as we have the final answer

        # If there are tool calls, prepare messages for the next LLM iteration
        logger.info(f"{log_prefix} Processing {len(tool_calls_for_this_turn)} tool call(s).")
        
        # Construct the assistant's message including any preliminary text and the tool call requests
        assistant_message_tool_calls_formatted = []
        for tc in tool_calls_for_this_turn:
            assistant_message_tool_calls_formatted.append({
                "id": tc.id,
                "type": "function", # Assuming all our tools are functions for now
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments # This is a string of JSON arguments
                }
            })

        assistant_message: Dict[str, Any] = {"role": "assistant"}
        if current_assistant_response_content.strip(): # Add content only if it's not empty
            assistant_message["content"] = current_assistant_response_content
        
        # Only add tool_calls key if there are actual tool calls.
        # Mistral API expects content to be null if tool_calls is present and there's no preceding text.
        # If content is empty string and tool_calls is present, it's fine.
        # If content is None and tool_calls is present, it's also fine.
        if not assistant_message.get("content"): # if content is empty or None
            assistant_message["content"] = None # Explicitly set to None if no text but tool calls exist

        assistant_message["tool_calls"] = assistant_message_tool_calls_formatted
        current_message_history.append(assistant_message)
        logger.debug(f"{log_prefix} Appended assistant message with tool calls to history: {assistant_message}")

        # Execute tool calls and add tool responses to history
        async with httpx.AsyncClient() as client:
            for tool_call in tool_calls_for_this_turn:
                tool_name = tool_call.function.name
                tool_arguments_str = tool_call.function.arguments
                tool_call_id = tool_call.id
                tool_result_content_str: str

                try:
                    parsed_args = json.loads(tool_arguments_str)
                except json.JSONDecodeError:
                    logger.error(f"{log_prefix} Failed to parse JSON arguments for tool {tool_name}: {tool_arguments_str}")
                    tool_result_content_str = json.dumps({
                        "error": "Failed to parse arguments provided by LLM.",
                        "tool_name": tool_name,
                        "arguments_string": tool_arguments_str
                    })
                    parsed_args = None # Ensure parsed_args is defined for the finally block if needed

                if parsed_args is not None: # Proceed only if arguments were parsed
                    try:
                        app_id, skill_id = tool_name.split('.', 1)
                        skill_url = f"http://{app_id}:{DEFAULT_APP_INTERNAL_PORT}/skill/{skill_id}/execute"
                        
                        logger.info(f"{log_prefix} Executing tool '{tool_name}' (App: {app_id}, Skill: {skill_id}) "
                                    f"at URL: {skill_url} with args: {parsed_args}")

                        # TODO: Add appropriate headers if skills require authentication/authorization
                        # For now, assuming skills are internally accessible without special auth.
                        # headers = {"X-Internal-Service-Token": "your_service_token"}
                        headers = {}

                        response = await client.post(skill_url, json=parsed_args, headers=headers, timeout=30.0) # 30s timeout for skill
                        response.raise_for_status() # Raise an exception for HTTP 4xx/5xx errors
                        
                        # Assuming the skill returns a JSON string as its result
                        skill_response_text = response.text
                        try:
                            # Validate if the skill response is valid JSON, as expected by the LLM for tool content
                            json.loads(skill_response_text)
                            tool_result_content_str = skill_response_text
                            logger.info(f"{log_prefix} Tool '{tool_name}' executed successfully. Response: {skill_response_text[:200]}...")
                        except json.JSONDecodeError:
                            logger.error(f"{log_prefix} Tool '{tool_name}' response was not valid JSON: {skill_response_text}")
                            tool_result_content_str = json.dumps({
                                "error": "Skill response was not valid JSON.",
                                "tool_name": tool_name,
                                "response_text": skill_response_text
                            })

                    except httpx.HTTPStatusError as e:
                        logger.error(f"{log_prefix} HTTP error executing tool '{tool_name}': {e.response.status_code} - {e.response.text}", exc_info=True)
                        tool_result_content_str = json.dumps({
                            "error": "Skill execution failed with HTTP status error.",
                            "tool_name": tool_name,
                            "status_code": e.response.status_code,
                            "details": e.response.text[:500] # Limit error detail length
                        })
                    except httpx.RequestError as e: # Catches timeouts, connection errors, etc.
                        logger.error(f"{log_prefix} Request error executing tool '{tool_name}': {e}", exc_info=True)
                        tool_result_content_str = json.dumps({
                            "error": "Skill execution failed due to a request error (e.g., timeout, connection issue).",
                            "tool_name": tool_name,
                            "details": str(e)
                        })
                    except ValueError: # For tool_name.split error
                         logger.error(f"{log_prefix} Invalid tool name format: '{tool_name}'. Expected 'app_id.skill_id'.")
                         tool_result_content_str = json.dumps({
                            "error": "Invalid tool name format received from LLM.",
                            "tool_name": tool_name
                        })
                    except Exception as e:
                        logger.error(f"{log_prefix} Unexpected error executing tool '{tool_name}': {e}", exc_info=True)
                        tool_result_content_str = json.dumps({
                            "error": "An unexpected error occurred during skill execution.",
                            "tool_name": tool_name,
                            "details": str(e)
                        })
                
                tool_response_message = {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": tool_result_content_str # This must be a string, expecting JSON string from skill
                }
                current_message_history.append(tool_response_message)
                logger.debug(f"{log_prefix} Appended tool response message to history: {tool_response_message}")

        if iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            logger.warning(f"{log_prefix} Reached max tool call iterations ({MAX_TOOL_CALL_ITERATIONS}). "
                           "The LLM might be in a loop or require more steps than allowed.")
            # If we hit max iterations and the last response was a tool call,
            # we don't have a final text response to yield.
            # The calling task should handle this (e.g., by sending an error or a "max iterations reached" message).
            # For now, we yield a message indicating this.
            yield "\n[Max tool call iterations reached. Unable to get a final response after tool executions.]"
            break

    # After the loop, if it broke due to no tool calls, current_assistant_response_content was already yielded.
    # If the loop finished due to max iterations, a warning message was yielded.
    logger.info(f"{log_prefix} Main processing stream finished.")

    # Billing/usage tracking will be handled by the calling Celery task
    # after consuming this async generator.
    # This function now only yields the string content.
