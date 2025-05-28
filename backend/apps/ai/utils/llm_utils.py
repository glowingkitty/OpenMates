# backend/apps/ai/utils/llm_utils.py
# Utilities for interacting with Language Models (LLMs).

import logging
from typing import Dict, Any, List, Optional, AsyncIterator
import copy # For deepcopy
from pydantic import BaseModel # For LLMToolCallResult

# Import the new versatile Mistral client function and response models
from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions, UnifiedMistralResponse, ParsedMistralToolCall
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

# TODO: Import other provider clients as they are created
# from backend.apps.ai.llm_providers.google_client import invoke_google_chat_completions

logger = logging.getLogger(__name__)

# Note: initialize_mistral_client (and similar for other providers) should be in their respective client files
# and ideally called during app startup if pre-initialization is needed.

# Helper function to extract text from Tiptap JSON
def _extract_text_from_tiptap(tiptap_content: Any) -> str:
    if isinstance(tiptap_content, str):
        return tiptap_content
    if not isinstance(tiptap_content, dict) or "type" not in tiptap_content:
        # Attempt to stringify if it's some other non-string, non-dict type, or return empty
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
        role = "assistant"  # Default to assistant
        if msg.get("sender_name") == "user":
            role = "user"
        # If a message somehow already has a 'role', prioritize that.
        # This could happen if system messages are part of history.
        if "role" in msg:
            role = msg["role"]

        content_input = msg.get("content", "")
        plain_text_content = _extract_text_from_tiptap(content_input)
        
        transformed_messages.append({"role": role, "content": plain_text_content})
    return transformed_messages

class LLMPreprocessingCallResult(BaseModel):
    """Result of a call_preprocessing_llm attempt."""
    arguments: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None # Specific error from LLM client or parsing
    raw_provider_response_summary: Optional[Dict[str, Any]] = None # e.g., UnifiedMistralResponse.model_dump(exclude_none=True)

async def call_preprocessing_llm(
    task_id: str,
    model_id: str,
    message_history: List[Dict[str, str]],
    tool_definition: Dict[str, Any], # The single tool expected for preprocessing
    secrets_manager: Optional[SecretsManager] = None, # Added SecretsManager
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None, # New parameter
    dynamic_context: Optional[Dict[str, Any]] = None # Made optional, specific keys handled below
) -> LLMPreprocessingCallResult: # Returns a structured result
    """
    Calls a preprocessing LLM, expecting it to call a specific tool.

    This function will determine the provider based on the model_id (implicitly for now,
    assuming Mistral if it's a Mistral model ID) and then call the appropriate
    provider-specific client function.

    Args:
        task_id: The ID of the Celery task for logging.
        model_id: The specific preprocessing model ID (e.g., "mistralai/mistral-small-latest").
        message_history: Chat message history.
        tool_definition: The tool definition for the LLM to call (from base_instructions.yml).
        user_app_settings_and_memories_metadata: Metadata about available user app settings/memories.
        dynamic_context: Other dynamic values for placeholders in the tool description.

    Returns:
        A dictionary of arguments for the called tool, or None on failure.
    """
    logger.info(f"[{task_id}] LLM Utils: Calling preprocessing LLM {model_id}.")

    current_tool_definition = copy.deepcopy(tool_definition)
    if "function" in current_tool_definition and "description" in current_tool_definition["function"]:
        tool_desc = current_tool_definition["function"]["description"]
        
        # Handle specific placeholders first
        # Placeholder for app settings and memories
        app_data_placeholder = "{AVAILABLE_APP_SETTINGS_AND_MEMORIES}"
        if user_app_settings_and_memories_metadata:
            app_data_str = "; ".join([f"{app_id}: {', '.join(keys)}" for app_id, keys in user_app_settings_and_memories_metadata.items()])
            tool_desc = tool_desc.replace(app_data_placeholder, app_data_str if app_data_str else "No app settings or memories currently have data for this user.")
        else:
            tool_desc = tool_desc.replace(app_data_placeholder, "No app settings or memories currently have data for this user.")

        # Handle other dynamic context items
        if dynamic_context:
            for key, value in dynamic_context.items():
                placeholder = f"{{{key}}}"
                # Generic value formatting, assuming list for CATEGORIES_LIST
                value_str = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                tool_desc = tool_desc.replace(placeholder, value_str)
                
        current_tool_definition["function"]["description"] = tool_desc
        logger.debug(f"[{task_id}] LLM Utils: Preprocessing tool description updated: {tool_desc[:300]}...")
    else:
        logger.warning(f"[{task_id}] LLM Utils: Preprocessing tool definition issue. Cannot inject dynamic context. Def: {current_tool_definition}")

    # Transform message history for LLM provider
    # The type hint for message_history is List[Dict[str, str]], but content can be a dict.
    # Casting to List[Dict[str, Any]] for the transformation function.
    transformed_messages_for_llm = _transform_message_history_for_llm(message_history)

    # Determine provider and actual model name
    provider_prefix = ""
    actual_model_id = model_id
    if "/" in model_id:
        parts = model_id.split("/", 1)
        provider_prefix = parts[0]
        actual_model_id = parts[1]
        logger.info(f"[{task_id}] LLM Utils: Parsed model_id. Provider: '{provider_prefix}', Actual Model ID: '{actual_model_id}'.")
    else:
        # If no slash, assume it's a direct model ID for a default provider (e.g. Mistral if only Mistral is configured)
        # Or, this could be an error if prefixes are always expected. For now, log and proceed.
        logger.warning(f"[{task_id}] LLM Utils: model_id '{model_id}' does not contain a provider prefix. Assuming direct model ID.")


    if provider_prefix == "mistralai":
        logger.info(f"[{task_id}] LLM Utils: Routing to Mistral client for model {actual_model_id} (original: {model_id}).")
        
        # For preprocessing, we expect a single tool to be called.
        # We force this by providing only one tool and setting tool_choice to "any" or the specific tool name.
        # The name of the function within the tool_definition is the expected one.
        expected_tool_name = current_tool_definition.get("function", {}).get("name")
        if not expected_tool_name:
            logger.error(f"[{task_id}] LLM Utils: Preprocessing tool definition is missing function name. Cannot proceed.")
            return LLMPreprocessingCallResult(error_message="Preprocessing tool definition is missing function name.")

        response: UnifiedMistralResponse = await invoke_mistral_chat_completions(
            task_id=task_id,
            model_id=actual_model_id, # Use the parsed actual_model_id
            messages=transformed_messages_for_llm, # Use transformed messages
            secrets_manager=secrets_manager, # Pass SecretsManager
            tools=[current_tool_definition],
            tool_choice="any", # Force call of the provided tool
            stream=False
        )

        if response.success and response.tool_calls_made:
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == expected_tool_name:
                    if tool_call.parsing_error:
                        err_msg = f"Failed to parse arguments for expected tool '{expected_tool_name}': {tool_call.parsing_error}"
                        logger.error(f"[{task_id}] LLM Utils: {err_msg}")
                        return LLMPreprocessingCallResult(error_message=err_msg, raw_provider_response_summary=response.model_dump(exclude_none=True, exclude={'raw_response'}))
                    logger.info(f"[{task_id}] LLM Utils: Successfully received and parsed arguments for preprocessing tool '{expected_tool_name}'.")
                    return LLMPreprocessingCallResult(arguments=tool_call.function_arguments_parsed, raw_provider_response_summary=response.model_dump(exclude_none=True, exclude={'raw_response'}))
            
            err_msg_tool_not_found = f"Expected tool '{expected_tool_name}' not found in tool calls: {response.tool_calls_made}"
            logger.warning(f"[{task_id}] LLM Utils: {err_msg_tool_not_found}")
            return LLMPreprocessingCallResult(error_message=err_msg_tool_not_found, raw_provider_response_summary=response.model_dump(exclude_none=True, exclude={'raw_response'}))

        elif not response.success:
            err_msg_client_fail = f"Mistral client call failed for preprocessing: {response.error_message}"
            logger.error(f"[{task_id}] LLM Utils: {err_msg_client_fail}")
            return LLMPreprocessingCallResult(error_message=err_msg_client_fail, raw_provider_response_summary=response.model_dump(exclude_none=True, exclude={'raw_response'}))
        else: # Success but no tool_calls_made
            err_msg_no_tool_call = f"Preprocessing LLM ({model_id}) did not make the expected tool call. Response: {response.model_dump_json(exclude_none=True, exclude={'raw_response'}, indent=2)}"
            logger.error(f"[{task_id}] LLM Utils: {err_msg_no_tool_call}")
            return LLMPreprocessingCallResult(error_message=err_msg_no_tool_call, raw_provider_response_summary=response.model_dump(exclude_none=True, exclude={'raw_response'}))

    # Example for future Google client integration
    # elif model_id.startswith("google/"):
    #     logger.info(f"[Celery Task ID: {task_id}] LLM Utils: Routing to Google client for model {model_id}.")
    #     # tool_call_args = await google_tool_caller(
    #     #     task_id=task_id,
    #     #     model_id=model_id,
    #     #     message_history=message_history,
    #     #     tool_definition=current_tool_definition
    #     # )
    #     # if tool_call_args is not None:
    #     #     logger.info(f"[Celery Task ID: {task_id}] LLM Utils: Received tool call arguments from Google client for model {model_id}: {tool_call_args}")
    #     # else:
    #     #     logger.error(f"[Celery Task ID: {task_id}] LLM Utils: Google client returned no arguments for model {model_id}.")
    #     # return tool_call_args
    
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
    secrets_manager: Optional[SecretsManager] = None, # Added SecretsManager
    tools: Optional[List[Dict[str, Any]]] = None, # Renamed from available_tools
    tool_choice: Optional[str] = None # Added tool_choice
) -> AsyncIterator[str]:
    """
    Calls the main LLM for generating a response, supporting streaming and optional tools.
    Yields paragraphs of the response. Tool call execution is not handled here yet.
    """
    log_prefix = f"[{task_id}] LLM Utils (Main Stream - {model_id}):"
    logger.info(f"{log_prefix} Preparing to call. System prompt length: {len(system_prompt)}. History items: {len(message_history)}. Temp: {temperature}. Tools: {len(tools) if tools else 0}. Tool choice: {tool_choice}")

    # Transform message history part for LLM provider
    # The type hint for message_history is List[Dict[str, str]], but content can be a dict.
    # Casting to List[Dict[str, Any]] for the transformation function.
    transformed_user_assistant_messages = _transform_message_history_for_llm(message_history)

    llm_api_messages = []
    if system_prompt:
        # System prompt content should already be a string.
        llm_api_messages.append({"role": "system", "content": system_prompt})
    llm_api_messages.extend(transformed_user_assistant_messages)

    # Determine provider and actual model name for main LLM stream
    provider_prefix_main = ""
    actual_model_id_main = model_id
    if "/" in model_id:
        parts_main = model_id.split("/", 1)
        provider_prefix_main = parts_main[0]
        actual_model_id_main = parts_main[1]
        logger.info(f"{log_prefix} Parsed model_id for main stream. Provider: '{provider_prefix_main}', Actual Model ID: '{actual_model_id_main}'.")
    else:
        logger.warning(f"{log_prefix} model_id '{model_id}' for main stream does not contain a provider prefix. Assuming direct model ID.")

    if provider_prefix_main == "mistralai":
        logger.info(f"{log_prefix} Routing to Mistral client for model {actual_model_id_main} (original: {model_id}).")
        try:
            # invoke_mistral_chat_completions returns AsyncIterator[str] when stream=True
            raw_chunk_stream = await invoke_mistral_chat_completions(
                task_id=task_id,
                model_id=actual_model_id_main, # Use the parsed actual_model_id_main
                messages=llm_api_messages, # Use fully transformed messages
                secrets_manager=secrets_manager, # Pass SecretsManager
                temperature=temperature,
                tools=tools, # Use the new 'tools' parameter
                tool_choice=tool_choice, # Use the new 'tool_choice' parameter
                stream=True
            )
            
            # Check if the response is an AsyncIterator (streaming case)
            # This check is a bit of a workaround for the Union return type.
            # In a robust system, the client might have distinct stream/non-stream methods.
            if hasattr(raw_chunk_stream, '__aiter__'):
                 async for paragraph in aggregate_paragraphs(raw_chunk_stream):
                    yield paragraph
            else:
                # This block would be hit if invoke_mistral_chat_completions returned UnifiedMistralResponse
                # despite stream=True, which indicates an early error (like API key missing, already handled by raising).
                # Or if a non-streaming path was mistakenly taken.
                # For now, assuming if stream=True, we always get an AsyncIterator or an exception.
                logger.error(f"{log_prefix} Expected a stream but did not receive one. Response type: {type(raw_chunk_stream)}")
                # yield f"[ERROR: Expected a stream but received {type(raw_chunk_stream)}]" # Or raise

        except ValueError as ve: # Catch API key error from mistral client for stream=True
            logger.error(f"{log_prefix} Value error during Mistral stream setup: {ve}")
            yield f"[ERROR: Configuration error - {ve}]" # Yield error message as part of the stream
        except IOError as ioe: # Catch IOErrors from Mistral client during streaming
            logger.error(f"{log_prefix} IO error during Mistral stream: {ioe}")
            yield f"[ERROR: LLM stream failed - {ioe}]" # Yield error message
        except Exception as e:
            logger.error(f"{log_prefix} Unexpected error during main LLM stream: {e}", exc_info=True)
            yield f"[ERROR: An unexpected error occurred during streaming - {e}]"
            
    # elif model_id.startswith("google/"):
    #     # Similar logic for Google client
    #     pass
    else:
        logger.error(f"{log_prefix} No provider client implemented for model_id: '{model_id}'.")
        yield f"[ERROR: Model provider for '{model_id}' not supported.]"
