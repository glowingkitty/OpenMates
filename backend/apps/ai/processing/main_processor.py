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
from backend.apps.base_app import AppYAML, AppSkillDefinition
from backend.core.api.app.utils.secrets_manager import SecretsManager

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService


logger = logging.getLogger(__name__)

# Max iterations for tool calling to prevent infinite loops
MAX_TOOL_CALL_ITERATIONS = 5
DEFAULT_APP_INTERNAL_PORT = 8000
APPROX_MAX_CONVERSATION_TOKENS = 80000
AVG_CHARS_PER_TOKEN = 4
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")


async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    secrets_manager: Optional[SecretsManager] = None
) -> AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]]:
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")
    
    # --- Existing logic for setup ---
    loaded_app_settings_and_memories_content: Dict[str, Any] = {}
    if preprocessing_results.load_app_settings_and_memories:
        if user_vault_key_id:
            for item_full_key in preprocessing_results.load_app_settings_and_memories:
                try:
                    app_id, item_key = item_full_key.split('.', 1)
                    decrypted_value = await directus_service.app_settings_and_memories.get_decrypted_user_app_item_value(
                        user_id_hash=request_data.user_id_hash,
                        app_id=app_id,
                        item_key=item_key,
                        user_vault_key_id=user_vault_key_id
                    )
                    if decrypted_value is not None:
                        loaded_app_settings_and_memories_content[item_full_key] = decrypted_value
                except Exception as e:
                    logger.error(f"{log_prefix} Error loading app item '{item_full_key}': {e}", exc_info=True)

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
    
    available_tools_for_llm: List[Dict[str, Any]] = []
    if selected_mate_config and selected_mate_config.assigned_apps and discovered_apps_metadata:
        for app_id in selected_mate_config.assigned_apps:
            app_meta = discovered_apps_metadata.get(app_id)
            if app_meta and app_meta.skills:
                for skill_def in app_meta.skills:
                    if skill_def.stage == "production":
                        tool_name = f"{app_id}.{skill_def.id}"
                        parameters_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
                        available_tools_for_llm.append({
                            "type": "function",
                            "function": {"name": tool_name, "description": skill_def.description, "parameters": parameters_schema}
                        })

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

        async with httpx.AsyncClient() as client:
            for tool_call in tool_calls_for_this_turn:
                tool_name = tool_call.function_name
                tool_arguments_str = tool_call.function_arguments_raw
                tool_call_id = tool_call.tool_call_id
                tool_result_content_str: str
                try:
                    parsed_args = json.loads(tool_arguments_str)
                    app_id, skill_id = tool_name.split('.', 1)
                    skill_url = f"http://{app_id}:{DEFAULT_APP_INTERNAL_PORT}/skill/{skill_id}/execute"
                    response = await client.post(skill_url, json=parsed_args, headers={}, timeout=30.0)
                    response.raise_for_status()
                    tool_result_content_str = response.text
                except Exception as e:
                    logger.error(f"{log_prefix} Error executing tool '{tool_name}': {e}", exc_info=True)
                    tool_result_content_str = json.dumps({"error": "Skill execution failed.", "details": str(e)})
                
                tool_response_message = {"tool_call_id": tool_call_id, "role": "tool", "name": tool_name, "content": tool_result_content_str}
                current_message_history.append(tool_response_message)

        if iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            yield "\n[Max tool call iterations reached.]"
            break

    if usage:
        yield usage

    logger.info(f"{log_prefix} Main processing stream finished.")
