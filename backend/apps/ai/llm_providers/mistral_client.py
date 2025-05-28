# backend/apps/ai/llm_providers/mistral_client.py
# Client for interacting with Mistral AI models.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import httpx  # For making API calls
import json # For parsing JSON strings from LLM
import os # For MISTRAL_API_KEY environment variable (fallback/local dev)
from pydantic import BaseModel, Field # For structured response

from backend.core.api.app.utils.secrets_manager import SecretsManager # Import SecretsManager

logger = logging.getLogger(__name__)

MISTRAL_API_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_API_KEY: Optional[str] = None # Global cache for the API key

# --- Pydantic Models for Structured Mistral Response ---

class MistralToolCallFunction(BaseModel):
    name: str
    arguments: str # This is a JSON string from Mistral

class MistralToolCall(BaseModel):
    id: str
    type: Optional[str] = "function" # Made optional, default to "function" due to API sometimes omitting it
    function: MistralToolCallFunction

class MistralResponseMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[MistralToolCall]] = None

class MistralChoice(BaseModel):
    index: int
    message: MistralResponseMessage
    finish_reason: str # e.g., "stop", "tool_calls", "length"

class MistralUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class RawMistralChatCompletionResponse(BaseModel):
    """Direct mapping of Mistral's API response structure."""
    id: str
    object: str # "chat.completion"
    created: int # timestamp
    model: str
    choices: List[MistralChoice]
    usage: MistralUsage

class ParsedMistralToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Optional[Dict[str, Any]] = None
    parsing_error: Optional[str] = None

class UnifiedMistralResponse(BaseModel):
    """
    A unified structure for returning results from Mistral calls,
    indicating whether it's a direct message or one or more tool calls.
    """
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    
    # If it's a direct chat response
    direct_message_content: Optional[str] = None
    
    # If one or more tools were called
    tool_calls_made: Optional[List[ParsedMistralToolCall]] = None
    
    # Raw API response for debugging or further inspection if needed
    raw_response: Optional[RawMistralChatCompletionResponse] = None
    usage: Optional[MistralUsage] = None


async def initialize_mistral_client():
    """
    Initializes the Mistral client, primarily by fetching the API key.
    This should be called once, perhaps during AI app startup or on first use.
    """
    global MISTRAL_API_KEY
    if MISTRAL_API_KEY: # Already loaded
        return

    # Try loading from SecretsManager first
    # This function now requires secrets_manager to be passed if the key isn't already loaded.
    # The caller (invoke_mistral_chat_completions) will handle providing it.
    # This function is now designed to be called by invoke_mistral_chat_completions if key is needed.
    pass # Actual implementation will be in the version below that accepts secrets_manager


async def initialize_mistral_client(secrets_manager: SecretsManager):
    """
    Initializes the Mistral client by fetching the API key using the provided SecretsManager.
    This should be called once, perhaps during AI app startup or on first use.
    """
    global MISTRAL_API_KEY
    if MISTRAL_API_KEY: # Already loaded
        logger.debug("Mistral API key already loaded.")
        return

    try:
        logger.info("Attempting to fetch Mistral API key from Secrets Manager...")
        # Path based on user feedback: kv/data/providers/mistral_ai, key api_key
        # Env var: SECRET__MISTRAL_AI__API_KEY
        # The convention for secret_path from env var SECRET__GROUP__NAME is kv/data/group/name
        api_key_from_vault = await secrets_manager.get_secret(secret_path="kv/data/providers/mistral_ai", secret_key="api_key")
        
        if api_key_from_vault:
            MISTRAL_API_KEY = api_key_from_vault
            logger.info("Mistral client initialized with API key from Secrets Manager.")
        else:
            logger.error("Mistral API key not found in Secrets Manager. Calls to Mistral API will fail if key is not already set via other means (e.g. tests).")
            # No fallback to os.getenv here to enforce Vault usage.
    except Exception as e:
        logger.error(f"Error during Mistral API key initialization from Secrets Manager: {e}", exc_info=True)
        # If SecretsManager access fails, we don't fallback to os.getenv.
        # The key must be available from Vault for production-like environments.
        if not MISTRAL_API_KEY: # Check if it was somehow set before this attempt
             logger.error("Mistral API key remains unconfigured after Secrets Manager access error. Calls will fail.")


async def invoke_mistral_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]], # Combined system prompt (if any) and message history
    secrets_manager: Optional[SecretsManager] = None, # Added to allow key loading
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None, # "auto", "any", or "none" (or specific tool like {"type": "function", "function": {"name": "my_function"}})
    stream: bool = False
) -> Union[UnifiedMistralResponse, AsyncIterator[Union[str, ParsedMistralToolCall]]]: # Updated return type
    """
    Invokes a Mistral model for chat completions, with optional tool calling.
    If stream is True, yields content chunks (str) or ParsedMistralToolCall objects.
    If stream is False, returns a UnifiedMistralResponse object with the full response.

    Args:
        task_id: The ID of the Celery task, for logging context.
        model_id: The specific Mistral model ID to use.
        messages: The list of messages, including system prompt (if any) as the first message.
        temperature: The temperature for the LLM response.
        max_tokens: Optional maximum number of tokens to generate.
        tools: Optional list of tool definitions for the LLM.
        tool_choice: Optional control over how tools are called ("auto", "any", "none", or specific tool).
        stream: If True, the response will be streamed.

    Returns:
        If stream=False, a UnifiedMistralResponse object.
        If stream=True, an AsyncIterator yielding response content chunks (str) or ParsedMistralToolCall objects.
    """
    global MISTRAL_API_KEY
    if not MISTRAL_API_KEY:
        if secrets_manager:
            await initialize_mistral_client(secrets_manager)
        else:
            # This case should ideally not be hit if SecretsManager is always passed.
            # If it is hit, it means SM was not provided, and the key isn't globally set.
            logger.error(f"[{task_id}] SecretsManager not provided to invoke_mistral_chat_completions, and Mistral API key is not loaded. API call will likely fail.")
            # We proceed, and the check below will catch the missing key.

    if not MISTRAL_API_KEY: # Check again after initialization attempt
        error_msg = "Mistral API key not configured. It must be loaded via SecretsManager."
        logger.error(f"[{task_id}] Mistral Client: API key not available for model {model_id}. Error: {error_msg}")
        if stream:
            raise ValueError(error_msg) # Fail fast for streams
        return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    log_prefix = f"[{task_id}] Mistral Client ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    endpoint = f"{MISTRAL_API_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "stream": stream
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
        if tool_choice: # Only add tool_choice if tools are present
            payload["tool_choice"] = tool_choice
        elif not tool_choice and tools: # Default to "auto" if tools are present but no choice specified
             payload["tool_choice"] = "auto"


    logger.debug(f"{log_prefix} Payload: {json.dumps(payload, indent=2)}")

    async def _process_non_stream_response(response_json: Dict[str, Any]) -> UnifiedMistralResponse:
        logger.info(f"{log_prefix} Received non-streamed response from API.")
        logger.debug(f"{log_prefix} Full non-streamed response data: {json.dumps(response_json, indent=2)}")
        try:
            raw_api_response = RawMistralChatCompletionResponse(**response_json)
        except Exception as pydantic_error:
            logger.error(f"{log_prefix} Failed to parse raw Mistral API response: {pydantic_error}", exc_info=True)
            return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=f"Failed to parse API response: {pydantic_error}")

        unified_resp_obj = UnifiedMistralResponse(
            task_id=task_id, model_id=model_id, success=True,
            raw_response=raw_api_response, usage=raw_api_response.usage
        )
        if raw_api_response.choices:
            first_choice = raw_api_response.choices[0]
            message_data = first_choice.message
            if message_data.tool_calls:
                unified_resp_obj.tool_calls_made = []
                for tc in message_data.tool_calls:
                    parsed_args, parsing_err_msg = None, None
                    try:
                        parsed_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError as e_json:
                        parsing_err_msg = f"JSONDecodeError: {e_json}. Raw: '{tc.function.arguments}'"
                        logger.error(f"{log_prefix} {parsing_err_msg} for tool {tc.function.name}")
                    unified_resp_obj.tool_calls_made.append(ParsedMistralToolCall(
                        tool_call_id=tc.id, function_name=tc.function.name,
                        function_arguments_raw=tc.function.arguments,
                        function_arguments_parsed=parsed_args, parsing_error=parsing_err_msg
                    ))
                logger.info(f"{log_prefix} Call resulted in {len(unified_resp_obj.tool_calls_made)} tool call(s).")
            elif message_data.content is not None:
                unified_resp_obj.direct_message_content = message_data.content
                logger.info(f"{log_prefix} Call resulted in a direct message response.")
            else:
                logger.warning(f"{log_prefix} Response message has neither tool_calls nor content. Finish: {first_choice.finish_reason}")
                unified_resp_obj.error_message = "Response has neither tool_calls nor content."
        else:
            logger.warning(f"{log_prefix} No 'choices' in API response.")
            unified_resp_obj.success = False
            unified_resp_obj.error_message = "No choices found in API response."
        return unified_resp_obj

    async def _iterate_stream_response(client: httpx.AsyncClient) -> AsyncIterator[Union[str, ParsedMistralToolCall]]:
        # This generator will yield either strings (content chunks) or ParsedMistralToolCall objects.
        # It needs to accumulate arguments if a tool call's arguments are chunked.
        current_tool_call_id: Optional[str] = None
        current_tool_function_name: Optional[str] = None
        current_tool_function_args_buffer: str = ""
        # active_tool_call_index: Optional[int] = None # Mistral tool_calls delta includes an index

        try:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                logger.info(f"{log_prefix} Stream connection established.")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_json = line[len("data: "):]
                        if data_json.strip() == "[DONE]":
                            logger.info(f"{log_prefix} Stream finished with [DONE].")
                            # If there's an unfinished tool call in buffer, it's an error or incomplete stream
                            if current_tool_function_name:
                                logger.warning(f"{log_prefix} Stream ended with an unterminated tool call: {current_tool_function_name}, args: {current_tool_function_args_buffer}")
                            break
                        try:
                            chunk = json.loads(data_json)
                            if chunk.get("choices"):
                                choice = chunk["choices"][0]
                                delta = choice.get("delta", {})

                                if delta.get("content"): # Text chunk
                                    # If there was an active tool call being buffered, it means the LLM switched from tool call to content.
                                    # This shouldn't typically happen if arguments were complete for the tool.
                                    # For now, we assume content and tool calls are somewhat exclusive per "turn" from LLM.
                                    if current_tool_function_name:
                                        logger.warning(f"{log_prefix} Received content chunk while buffering tool call {current_tool_function_name}. Flushing buffered tool call as incomplete.")
                                        # Attempt to parse what we have for the tool call
                                        parsed_args, err_msg = None, f"Tool call {current_tool_function_name} interrupted by content."
                                        try: parsed_args = json.loads(current_tool_function_args_buffer)
                                        except json.JSONDecodeError as e: err_msg += f" JSONDecodeError: {e}"
                                        yield ParsedMistralToolCall(tool_call_id=current_tool_call_id or "unknown_stream_id", function_name=current_tool_function_name, function_arguments_raw=current_tool_function_args_buffer, function_arguments_parsed=parsed_args, parsing_error=err_msg)
                                        current_tool_function_name, current_tool_function_args_buffer, current_tool_call_id = None, "", None
                                    
                                    yield delta["content"]

                                if delta.get("tool_calls"): # Tool call chunk
                                    for tc_delta_part in delta["tool_calls"]:
                                        # tc_delta_part is like: {"index": 0, "id": "call_xxx", "type": "function", "function": {"name": "yyy", "arguments": "{\"arg": "val"}"}}
                                        # OR {"index": 0, "function": {"arguments": "ore text"}} if arguments are chunked.
                                        
                                        tc_index = tc_delta_part.get("index") # Assuming one tool call at a time for now (index 0)
                                        # For simplicity, we'll focus on the first tool call if multiple are streamed,
                                        # or assume they come sequentially per index.
                                        # A robust multi-tool-call stream parser would be more complex.

                                        new_tool_id = tc_delta_part.get("id")
                                        func_details = tc_delta_part.get("function", {})
                                        
                                        if new_tool_id: # Start of a new tool call or ID confirmation
                                            if current_tool_function_name and current_tool_call_id != new_tool_id : # New tool call started before old one finished arguments
                                                logger.warning(f"{log_prefix} New tool call {new_tool_id} started before {current_tool_call_id} finished. Flushing old.")
                                                parsed_args, err_msg = None, f"Tool call {current_tool_function_name} superseded by {new_tool_id}."
                                                try: parsed_args = json.loads(current_tool_function_args_buffer)
                                                except json.JSONDecodeError as e: err_msg += f" JSONDecodeError: {e}"
                                                yield ParsedMistralToolCall(tool_call_id=current_tool_call_id, function_name=current_tool_function_name, function_arguments_raw=current_tool_function_args_buffer, function_arguments_parsed=parsed_args, parsing_error=err_msg)
                                            
                                            current_tool_call_id = new_tool_id
                                            current_tool_function_name = func_details.get("name") # Name might arrive here
                                            current_tool_function_args_buffer = func_details.get("arguments", "") # First part of args
                                        elif current_tool_function_name: # Continuation of arguments for the current tool
                                            current_tool_function_args_buffer += func_details.get("arguments", "")
                                        
                                        # If name is now present and was not, update it
                                        if current_tool_function_name is None and func_details.get("name"):
                                            current_tool_function_name = func_details.get("name")


                                # Check if this chunk signals the end of tool calls for this turn
                                if choice.get("finish_reason") == "tool_calls":
                                    logger.info(f"{log_prefix} Stream indicated finish_reason: tool_calls.")
                                    if current_tool_function_name:
                                        parsed_args, err_msg = None, None
                                        try:
                                            parsed_args = json.loads(current_tool_function_args_buffer)
                                        except json.JSONDecodeError as e:
                                            err_msg = f"Stream JSONDecodeError on finish: {e}. Raw: '{current_tool_function_args_buffer}'"
                                            logger.error(f"{log_prefix} {err_msg} for tool {current_tool_function_name}")
                                        
                                        yield ParsedMistralToolCall(
                                            tool_call_id=current_tool_call_id or "unknown_finish_id",
                                            function_name=current_tool_function_name,
                                            function_arguments_raw=current_tool_function_args_buffer,
                                            function_arguments_parsed=parsed_args,
                                            parsing_error=err_msg
                                        )
                                        current_tool_function_name, current_tool_function_args_buffer, current_tool_call_id = None, "", None
                                    return # End this generator as tool calls are complete for this LLM turn.
                                
                        except json.JSONDecodeError:
                            logger.warning(f"{log_prefix} Failed to decode JSON from stream line: {data_json}")
                    elif line: # Non-empty line that isn't data
                        logger.debug(f"{log_prefix} Received non-data line from stream: {line}")
        except httpx.HTTPStatusError as e_http:
            err_msg = f"HTTP error during streaming. Status: {e_http.response.status_code}. Response: {await e_http.response.aread()}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Mistral API HTTP Error: {e_http.response.status_code}") from e_http
        except Exception as e_stream:
            err_msg = f"Unexpected error during streaming. Error: {e_stream}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Mistral API Unexpected Streaming Error: {e_stream}") from e_stream
        # Note: Usage data for streamed responses might need to be handled differently,
        # as it's often not part of the stream itself or comes at the very end in a separate event.
        # For now, UnifiedMistralResponse.usage will be None for streamed calls from this client.

    if stream:
        # When stream=True, we return the async generator directly.
        # The httpx.AsyncClient should be managed by the caller or within the generator.
        # For simplicity here, we'll create it inside the generator.
        return _iterate_stream_response(httpx.AsyncClient(timeout=180.0))
    else:
        # For non-streaming, execute and process fully.
        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                response_json = response.json()
                
                # Process non-stream response
                processed_response = await _process_non_stream_response(response_json)

                # Log input, output, and token usage
                logger.debug(f"{log_prefix} API Call Details:")
                logger.debug(f"{log_prefix}   Input Payload: {json.dumps(payload, indent=2)}") # Log the full input payload

                if processed_response.direct_message_content:
                    logger.debug(f"{log_prefix}   Output Message Content: {processed_response.direct_message_content}")
                if processed_response.tool_calls_made:
                    # Log tool calls in a structured way
                    tool_calls_log = []
                    for tc in processed_response.tool_calls_made:
                        tool_calls_log.append({
                            "tool_call_id": tc.tool_call_id,
                            "function_name": tc.function_name,
                            "function_arguments_raw": tc.function_arguments_raw,
                            "function_arguments_parsed": tc.function_arguments_parsed,
                            "parsing_error": tc.parsing_error
                        })
                    logger.debug(f"{log_prefix}   Tool Calls Made: {json.dumps(tool_calls_log, indent=2)}")
                
                if processed_response.raw_response and processed_response.raw_response.usage:
                    usage = processed_response.raw_response.usage
                    logger.debug(f"{log_prefix}   Token Usage: Prompt Tokens: {usage.prompt_tokens}, Completion Tokens: {usage.completion_tokens}, Total Tokens: {usage.total_tokens}")
                elif processed_response.usage: # Fallback if raw_response not populated but usage is
                    usage = processed_response.usage
                    logger.debug(f"{log_prefix}   Token Usage (from UnifiedMistralResponse.usage): Prompt Tokens: {usage.prompt_tokens}, Completion Tokens: {usage.completion_tokens}, Total Tokens: {usage.total_tokens}")
                else:
                    logger.debug(f"{log_prefix}   Token Usage: Not available in response.")
                
                # Log the full raw response for complete transparency if needed for debugging, but can be verbose
                # logger.debug(f"{log_prefix} Full Raw API Response: {json.dumps(response_json, indent=2)}")

                return processed_response
            except httpx.HTTPStatusError as e_http:
                err_msg = f"HTTP error calling API. Status: {e_http.response.status_code}. Response: {e_http.response.text}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
                logger.debug(f"{log_prefix} API Call Failed. Input Payload: {json.dumps(payload, indent=2)}")
                return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)
            except httpx.RequestError as e_req:
                err_msg = f"Request error calling API. Error: {e_req}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
                return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)
            except Exception as e_gen: # Includes JSONDecodeError if response is not JSON
                err_msg = f"Unexpected error during API call or non-stream response processing. Error: {e_gen}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
                return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

if __name__ == '__main__':
    # Basic test for initialization (requires MISTRAL_API_KEY environment variable)
    async def main_test():
        logging.basicConfig(level=logging.DEBUG) # Use DEBUG for more verbose output
        
        # For testing, we'd ideally mock SecretsManager or ensure MISTRAL_API_KEY env var is set.
        # For this ad-hoc test, let's assume MISTRAL_API_KEY env var is the primary way for it to work.
        # If you have a local Vault, you could instantiate a real SecretsManager for a more complete test.
        # test_secrets_manager = SecretsManager() 
        # await test_secrets_manager.initialize() # If SM has async init
        # await initialize_mistral_client(test_secrets_manager) # Initialize with SM

        # Fallback for simple local test:
        # For local testing where Vault might not be running, one might temporarily set MISTRAL_API_KEY
        # via os.environ BEFORE this test runs, or mock SecretsManager.
        # The code now prioritizes SecretsManager.
        test_sm = SecretsManager()
        # if hasattr(test_sm, 'initialize'): # If SecretsManager has its own async init
        #    await test_sm.initialize()
        await initialize_mistral_client(test_sm)


        if MISTRAL_API_KEY: # Ensure it's a real key for API calls
            logger.info(f"Test: Mistral API key is loaded: {'Yes' if MISTRAL_API_KEY else 'No'}")
            
            example_tool_def = { # Simplified for testing the new function
                "type": "function",
                "function": {
                    "name": "get_flight_details",
                    "description": "Get flight details for a given destination and date.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "destination": {"type": "string", "description": "City of arrival"},
                            "date": {"type": "string", "description": "Date of travel, YYYY-MM-DD"}
                        },
                        "required": ["destination", "date"]
                    }
                }
            }

            example_messages_for_tool_call = [
                {"role": "user", "content": "I want to fly to Paris on 2025-12-20."}
            ]
            
            logger.info("Test: Invoking with tool call (non-streaming)...")
            # Test non-streaming tool call
            response_with_tool = await invoke_mistral_chat_completions(
                task_id="test-tool-nonstream",
                model_id="mistral-small-latest", # Use a model that supports tools
                messages=example_messages_for_tool_call,
                # secrets_manager=test_secrets_manager, # Pass SM if using real one
                tools=[example_tool_def],
                tool_choice="any", # Force tool call for this test
                stream=False
            )
            if response_with_tool.success:
                logger.info(f"Test (Tool Call, Non-Stream) - Success: {response_with_tool.success}")
                if response_with_tool.tool_calls_made:
                    logger.info(f"  Tool calls: {response_with_tool.tool_calls_made}")
                if response_with_tool.direct_message_content:
                     logger.info(f"  Direct message: {response_with_tool.direct_message_content}")
                logger.info(f"  Usage: {response_with_tool.usage}")
            else:
                logger.error(f"Test (Tool Call, Non-Stream) - Error: {response_with_tool.error_message}")


            example_messages_for_chat = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, how are you today?"}
            ]

            logger.info("\nTest: Invoking plain chat (non-streaming)...")
            # Test non-streaming plain chat
            response_plain_chat = await invoke_mistral_chat_completions(
                task_id="test-chat-nonstream",
                model_id="mistral-tiny", # Any chat model
                messages=example_messages_for_chat,
                # secrets_manager=test_secrets_manager, # Pass SM
                temperature=0.5,
                stream=False
            )
            if response_plain_chat.success:
                logger.info(f"Test (Plain Chat, Non-Stream) - Success: {response_plain_chat.success}")
                logger.info(f"  Direct message: {response_plain_chat.direct_message_content}")
                logger.info(f"  Usage: {response_plain_chat.usage}")
            else:
                logger.error(f"Test (Plain Chat, Non-Stream) - Error: {response_plain_chat.error_message}")

            logger.info("\nTest: Invoking plain chat (streaming)...")
            # Test streaming plain chat
            try:
                full_streamed_response = ""
                async for chunk in invoke_mistral_chat_completions(
                    task_id="test-chat-stream",
                    model_id="mistral-tiny",
                    messages=example_messages_for_chat,
                    # secrets_manager=test_secrets_manager, # Pass SM
                    temperature=0.5,
                    stream=True
                ):
                    if isinstance(chunk, str): # Should always be str if stream=True and no pre-flight error
                        print(chunk, end="", flush=True) # Print chunks as they arrive
                        full_streamed_response += chunk
                    else: # Should not happen with current implementation if stream=True
                        logger.error(f"Unexpected chunk type in stream: {type(chunk)} - {chunk}")

                print() # Newline after stream
                logger.info(f"Test (Plain Chat, Stream) - Full streamed response collected: '{full_streamed_response}'")
            except Exception as e_stream_test:
                logger.error(f"Test (Plain Chat, Stream) - Error during streaming test: {e_stream_test}", exc_info=True)

        else:
            logger.error("Test: Mistral API key is NOT loaded. Cannot run API call tests.")

    import asyncio
    asyncio.run(main_test())
