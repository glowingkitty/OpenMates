# backend/apps/ai/utils/llm_utils.py
# Utilities for interacting with Language Models (LLMs).

import logging
from typing import Dict, Any, List, Optional, AsyncIterator
import copy # For deepcopy

# Import the new versatile Mistral client function and response models
from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions, UnifiedMistralResponse, ParsedMistralToolCall
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs

# TODO: Import other provider clients as they are created
# from backend.apps.ai.llm_providers.google_client import invoke_google_chat_completions

logger = logging.getLogger(__name__)

# Note: initialize_mistral_client (and similar for other providers) should be in their respective client files
# and ideally called during app startup if pre-initialization is needed.

async def call_preprocessing_llm(
    task_id: str,
    model_id: str,
    message_history: List[Dict[str, str]],
    tool_definition: Dict[str, Any], # The single tool expected for preprocessing
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None, # New parameter
    dynamic_context: Optional[Dict[str, Any]] = None # Made optional, specific keys handled below
) -> Optional[Dict[str, Any]]: # Returns parsed arguments of the *expected* tool
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

    messages = message_history # Preprocessing usually doesn't have a separate system prompt beyond tool instruction

    if model_id.startswith("mistralai/"):
        logger.info(f"[{task_id}] LLM Utils: Routing to Mistral client for preprocessing model {model_id}.")
        
        # For preprocessing, we expect a single tool to be called.
        # We force this by providing only one tool and setting tool_choice to "any" or the specific tool name.
        # The name of the function within the tool_definition is the expected one.
        expected_tool_name = current_tool_definition.get("function", {}).get("name")
        if not expected_tool_name:
            logger.error(f"[{task_id}] LLM Utils: Preprocessing tool definition is missing function name. Cannot proceed.")
            return None

        response: UnifiedMistralResponse = await invoke_mistral_chat_completions(
            task_id=task_id,
            model_id=model_id,
            messages=messages,
            tools=[current_tool_definition],
            tool_choice="any", # Force call of the provided tool
            stream=False
        )

        if response.success and response.tool_calls_made:
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == expected_tool_name:
                    if tool_call.parsing_error:
                        logger.error(f"[{task_id}] LLM Utils: Failed to parse arguments for expected tool '{expected_tool_name}': {tool_call.parsing_error}")
                        return None
                    logger.info(f"[{task_id}] LLM Utils: Successfully received and parsed arguments for preprocessing tool '{expected_tool_name}'.")
                    return tool_call.function_arguments_parsed
            logger.warning(f"[{task_id}] LLM Utils: Expected tool '{expected_tool_name}' not found in tool calls: {response.tool_calls_made}")
        elif not response.success:
            logger.error(f"[{task_id}] LLM Utils: Mistral client call failed for preprocessing: {response.error_message}")
        else: # Success but no tool_calls_made or not the right one
            logger.error(f"[{task_id}] LLM Utils: Preprocessing LLM did not make the expected tool call. Response: {response.model_dump_json(indent=2)}")
        return None
    
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
        logger.error(f"[{task_id}] LLM Utils: No provider client implemented for preprocessing model_id: '{model_id}'.")
        return None

async def call_main_llm_stream(
    task_id: str,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, str]],
    temperature: float,
    available_tools: Optional[List[Dict[str, Any]]] = None
) -> AsyncIterator[str]:
    """
    Calls the main LLM for generating a response, supporting streaming and optional tools.
    Yields paragraphs of the response. Tool call execution is not handled here yet.
    """
    log_prefix = f"[{task_id}] LLM Utils (Main Stream - {model_id}):"
    logger.info(f"{log_prefix} Preparing to call. System prompt length: {len(system_prompt)}. History items: {len(message_history)}. Temp: {temperature}. Tools: {len(available_tools) if available_tools else 0}")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(message_history)

    if model_id.startswith("mistralai/"):
        logger.info(f"{log_prefix} Routing to Mistral client.")
        try:
            # invoke_mistral_chat_completions returns AsyncIterator[str] when stream=True
            raw_chunk_stream = await invoke_mistral_chat_completions(
                task_id=task_id,
                model_id=model_id,
                messages=messages,
                temperature=temperature,
                tools=available_tools,
                tool_choice="auto" if available_tools else None, # Let LLM decide if tools are available
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