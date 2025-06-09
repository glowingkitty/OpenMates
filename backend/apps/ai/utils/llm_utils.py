# backend/apps/ai/utils/llm_utils.py
# Utilities for interacting with Language Models (LLMs).

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import copy # For deepcopy
from pydantic import BaseModel # For LLMToolCallResult
import json # For serializing complex objects if needed, though logger extra should handle dicts
import os # For accessing environment variables
from dotenv import load_dotenv # For loading .env file

# Load environment variables from .env file
load_dotenv()

# --- CORRECTED IMPORTS ---
# Import the versatile Mistral client function and response models
from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions, UnifiedMistralResponse, ParsedMistralToolCall
# Import the new versatile Google client function and response models
from backend.apps.ai.llm_providers.google_client import invoke_google_chat_completions, UnifiedGoogleResponse, ParsedGoogleToolCall
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

logger = logging.getLogger(__name__)

# Helper function to extract text from Tiptap JSON
def _extract_text_from_tiptap(tiptap_content: Any) -> str:
    if isinstance(tiptap_content, str):
        return tiptap_content
    if not isinstance(tiptap_content, dict) or "type" not in tiptap_content:
        if not isinstance(tiptap_content, (str, dict, list)):
            try:
                return str(tiptap_content)
            except:
                return ""
        return ""

    text_parts = []
    if tiptap_content.get("type") == "text" and "text" in tiptap_content:
        text_parts.append(tiptap_content["text"])

    if "content" in tiptap_content and isinstance(tiptap_content["content"], list):
        for sub_content in tiptap_content["content"]:
            text_parts.append(_extract_text_from_tiptap(sub_content))
    
    return "".join(text_parts)

def _transform_message_history_for_llm(message_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Transforms message history from internal format (sender_name, Tiptap content)
    to LLM provider expected format (role, string content).
    """
    transformed_messages = []
    for msg in message_history:
        role = "assistant"
        if msg.get("sender_name") == "user":
            role = "user"
        if "role" in msg:
            role = msg["role"]

        content_input = msg.get("content", "")
        plain_text_content = _extract_text_from_tiptap(content_input)
        
        transformed_messages.append({"role": role, "content": plain_text_content})
    return transformed_messages

class LLMPreprocessingCallResult(BaseModel):
    """Result of a call_preprocessing_llm attempt."""
    arguments: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    raw_provider_response_summary: Optional[Dict[str, Any]] = None

async def call_preprocessing_llm(
    task_id: str,
    model_id: str,
    message_history: List[Dict[str, str]],
    tool_definition: Dict[str, Any],
    secrets_manager: Optional[SecretsManager] = None,
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None,
    dynamic_context: Optional[Dict[str, Any]] = None
) -> LLMPreprocessingCallResult:
    """
    Calls a preprocessing LLM, expecting it to call a specific tool.
    """
    logger.info(f"[{task_id}] LLM Utils: Calling preprocessing LLM {model_id}.")

    current_tool_definition = copy.deepcopy(tool_definition)
    if "function" in current_tool_definition and "description" in current_tool_definition["function"]:
        tool_desc = current_tool_definition["function"]["description"]
        
        app_data_placeholder = "{AVAILABLE_APP_SETTINGS_AND_MEMORIES}"
        if user_app_settings_and_memories_metadata:
            app_data_str = "; ".join([f"{app_id}: {', '.join(keys)}" for app_id, keys in user_app_settings_and_memories_metadata.items()])
            tool_desc = tool_desc.replace(app_data_placeholder, app_data_str if app_data_str else "No app settings or memories currently have data for this user.")
        else:
            tool_desc = tool_desc.replace(app_data_placeholder, "No app settings or memories currently have data for this user.")

        if dynamic_context:
            for key, value in dynamic_context.items():
                placeholder = f"{{{key}}}"
                value_str = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                tool_desc = tool_desc.replace(placeholder, value_str)
                
        current_tool_definition["function"]["description"] = tool_desc
        logger.debug(f"[{task_id}] LLM Utils: Preprocessing tool description updated: {tool_desc[:300]}...")
    else:
        logger.warning(f"[{task_id}] LLM Utils: Preprocessing tool definition issue. Cannot inject dynamic context. Def: {current_tool_definition}")

    transformed_messages_for_llm = _transform_message_history_for_llm(message_history)

    provider_prefix = ""
    actual_model_id = model_id
    if "/" in model_id:
        parts = model_id.split("/", 1)
        provider_prefix = parts[0]
        actual_model_id = parts[1]
        logger.info(f"[{task_id}] LLM Utils: Parsed model_id. Provider: '{provider_prefix}', Model ID: '{actual_model_id}'.")
    else:
        logger.warning(f"[{task_id}] LLM Utils: model_id '{model_id}' does not contain a provider prefix.")

    # --- COMMON LOGIC FOR HANDLING ANY PROVIDER'S RESPONSE ---
    def handle_response(response: Union[UnifiedMistralResponse, UnifiedGoogleResponse], expected_tool_name: str) -> LLMPreprocessingCallResult:
        current_raw_provider_response_summary = response.model_dump(exclude_none=True, exclude={'raw_response'})
        
        # Log the output
        log_output_extra = {
            "task_id": task_id, "success": response.success, "error_message": response.error_message,
            "tool_calls_made": [tc.model_dump() for tc in response.tool_calls_made] if response.tool_calls_made else None,
            "raw_provider_response_summary": current_raw_provider_response_summary, "event_type": "llm_preprocessing_output"
        }
        if os.getenv("SERVER_ENVIRONMENT") == "development":
            logger.info(f"[{task_id}] Preprocessing LLM call output", extra=log_output_extra)
        else:
            logger.info(f"[{task_id}] Preprocessing LLM call completed. Success: {response.success}. Detailed logging skipped.")

        # Process the response
        if response.success and response.tool_calls_made:
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == expected_tool_name:
                    if tool_call.parsing_error:
                        err_msg = f"Failed to parse arguments for tool '{expected_tool_name}': {tool_call.parsing_error}"
                        logger.error(f"[{task_id}] LLM Utils: {err_msg}")
                        return LLMPreprocessingCallResult(error_message=err_msg, raw_provider_response_summary=current_raw_provider_response_summary)
                    logger.info(f"[{task_id}] LLM Utils: Successfully parsed arguments for tool '{expected_tool_name}'.")
                    return LLMPreprocessingCallResult(arguments=tool_call.function_arguments_parsed, raw_provider_response_summary=current_raw_provider_response_summary)
            
            err_msg_tool_not_found = f"Expected tool '{expected_tool_name}' not found in tool calls."
            logger.warning(f"[{task_id}] LLM Utils: {err_msg_tool_not_found}")
            return LLMPreprocessingCallResult(error_message=err_msg_tool_not_found, raw_provider_response_summary=current_raw_provider_response_summary)

        elif not response.success:
            err_msg_client_fail = f"Client call failed for preprocessing: {response.error_message}"
            logger.error(f"[{task_id}] LLM Utils: {err_msg_client_fail}")
            return LLMPreprocessingCallResult(error_message=err_msg_client_fail, raw_provider_response_summary=current_raw_provider_response_summary)
        else: # Success but no tool_calls_made
            err_msg_no_tool_call = f"Preprocessing LLM ({model_id}) did not make the expected tool call."
            logger.error(f"[{task_id}] LLM Utils: {err_msg_no_tool_call}")
            return LLMPreprocessingCallResult(error_message=err_msg_no_tool_call, raw_provider_response_summary=current_raw_provider_response_summary)

    expected_tool_name = current_tool_definition.get("function", {}).get("name")
    if not expected_tool_name:
        error_msg = "Preprocessing tool definition is missing function name."
        logger.error(f"[{task_id}] LLM Utils: {error_msg}")
        return LLMPreprocessingCallResult(error_message=error_msg)

    # --- PROVIDER ROUTING LOGIC ---
    if provider_prefix == "mistralai":
        logger.info(f"[{task_id}] LLM Utils: Routing to Mistral client for model {actual_model_id}.")
        response = await invoke_mistral_chat_completions(
            task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
            secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="any", stream=False
        )
        return handle_response(response, expected_tool_name)

    elif provider_prefix == "google":
        logger.info(f"[{task_id}] LLM Utils: Routing to Google client for model {actual_model_id}.")
        # The google client supports non-streaming, so we call it the same way as mistral's
        response = await invoke_google_chat_completions(
            task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
            secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="any", stream=False
        )
        return handle_response(response, expected_tool_name)
    
    else:
        err_msg_no_provider = f"No provider client implemented for preprocessing model_id: '{model_id}'."
        logger.error(f"[{task_id}] LLM Utils: {err_msg_no_provider}")
        return LLMPreprocessingCallResult(error_message=err_msg_no_provider)


async def call_main_llm_stream(
    task_id: str,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, str]],
    temperature: float,
    secrets_manager: Optional[SecretsManager] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None
) -> AsyncIterator[str]:
    """
    Calls the main LLM for generating a response, supporting streaming and optional tools.
    """
    log_prefix = f"[{task_id}] LLM Utils (Main Stream - {model_id}):"
    logger.info(f"{log_prefix} Preparing to call. Temp: {temperature}. Tools: {len(tools) if tools else 0}. Choice: {tool_choice}")

    transformed_user_assistant_messages = _transform_message_history_for_llm(message_history)
    llm_api_messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    llm_api_messages.extend(transformed_user_assistant_messages)

    provider_prefix = ""
    actual_model_id = model_id
    if "/" in model_id:
        parts = model_id.split("/", 1)
        provider_prefix = parts[0]
        actual_model_id = parts[1]
        logger.info(f"{log_prefix} Parsed model_id. Provider: '{provider_prefix}', Model ID: '{actual_model_id}'.")
    else:
        logger.warning(f"{log_prefix} model_id '{model_id}' does not contain a provider prefix.")

    main_llm_input_details = {
        "task_id": task_id, "model_id": actual_model_id, "messages": llm_api_messages,
        "temperature": temperature, "tools": tools, "tool_choice": tool_choice, "stream": True
    }

    provider_client = None
    if provider_prefix == "mistralai":
        logger.info(f"{log_prefix} Routing to Mistral client.")
        provider_client = invoke_mistral_chat_completions
    elif provider_prefix == "google":
        logger.info(f"{log_prefix} Routing to Google client.")
        provider_client = invoke_google_chat_completions
    else:
        err_msg = f"No provider client for main stream model_id: '{model_id}'."
        logger.error(f"{log_prefix} {err_msg}")
        yield f"[ERROR: Model provider for '{model_id}' not supported.]"
        return

    try:
        raw_chunk_stream = await provider_client(secrets_manager=secrets_manager, **main_llm_input_details)
        
        if hasattr(raw_chunk_stream, '__aiter__'):
            async for paragraph in aggregate_paragraphs(raw_chunk_stream):
                yield paragraph
        else:
            logger.error(f"{log_prefix} Expected a stream but did not receive one. Response type: {type(raw_chunk_stream)}")
            yield f"[ERROR: Expected a stream but received {type(raw_chunk_stream)}]"

    except (ValueError, IOError) as e:
        logger.error(f"{log_prefix} Client or stream error: {e}", exc_info=True)
        yield f"[ERROR: LLM stream failed - {e}]"
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error during main LLM stream: {e}", exc_info=True)
        yield f"[ERROR: An unexpected error occurred - {e}]"


def log_main_llm_stream_aggregated_output(task_id: str, aggregated_response: str, error_message: Optional[str] = None):
    """
    Logs the fully aggregated response from the main LLM stream.
    """
    log_prefix = f"[{task_id}] LLM Utils (Main Stream Aggregated Output):"
    
    if os.getenv("SERVER_ENVIRONMENT") == "development":
        if error_message:
            log_details = {"task_id": task_id, "error": error_message, "partial_response_if_any": aggregated_response or "N/A", "event_type": "llm_main_stream_aggregated_output_error"}
            logger.error(f"{log_prefix} Error during stream processing: {error_message}", extra=log_details)
        else:
            response_snippet = aggregated_response[:1000] + "..." if len(aggregated_response) > 1000 else aggregated_response
            log_details = {"task_id": task_id, "aggregated_response_length": len(aggregated_response), "aggregated_response_snippet": response_snippet, "event_type": "llm_main_stream_aggregated_output_success"}
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}", extra=log_details)
    else:
        if error_message:
            logger.error(f"{log_prefix} Error during stream processing: {error_message}. Detailed logging skipped.")
        else:
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}. Detailed logging skipped.")