# backend/apps/ai/llm_providers/mistral_client.py
# Client for interacting with Mistral AI models.

import logging
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import httpx
import json
import os
from pydantic import BaseModel, Field
import tiktoken

from backend.core.api.app.utils.secrets_manager import SecretsManager
from .openai_shared import calculate_token_breakdown

logger = logging.getLogger(__name__)

MISTRAL_API_BASE_URL = "https://api.mistral.ai/v1"
MISTRAL_API_KEY: Optional[str] = None

# --- Pydantic Models for Structured Mistral Response ---

class MistralToolCallFunction(BaseModel):
    name: str
    arguments: str

class MistralToolCall(BaseModel):
    id: str
    type: Optional[str] = "function"
    function: MistralToolCallFunction

class MistralResponseMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[MistralToolCall]] = None

class MistralChoice(BaseModel):
    index: int
    message: MistralResponseMessage
    finish_reason: str

class MistralUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    user_input_tokens: Optional[int] = None
    system_prompt_tokens: Optional[int] = None

class RawMistralChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
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
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedMistralToolCall]] = None
    raw_response: Optional[RawMistralChatCompletionResponse] = None
    usage: Optional[MistralUsage] = None

async def initialize_mistral_client(secrets_manager: SecretsManager):
    global MISTRAL_API_KEY
    if MISTRAL_API_KEY:
        logger.debug("Mistral API key already loaded.")
        return

    try:
        logger.info("Attempting to fetch Mistral API key from Secrets Manager...")
        api_key_from_vault = await secrets_manager.get_secret(secret_path="kv/data/providers/mistral_ai", secret_key="api_key")
        
        if api_key_from_vault:
            MISTRAL_API_KEY = api_key_from_vault
            logger.info("Mistral client initialized with API key from Secrets Manager.")
        else:
            logger.error("Mistral API key not found in Secrets Manager.")
    except Exception as e:
        logger.error(f"Error during Mistral API key initialization from Secrets Manager: {e}", exc_info=True)
        if not MISTRAL_API_KEY:
             logger.error("Mistral API key remains unconfigured after Secrets Manager access error.")

async def invoke_mistral_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedMistralResponse, AsyncIterator[Union[str, ParsedMistralToolCall, MistralUsage]]]:
    global MISTRAL_API_KEY
    if not MISTRAL_API_KEY and secrets_manager:
        await initialize_mistral_client(secrets_manager)

    if not MISTRAL_API_KEY:
        error_msg = "Mistral API key not configured."
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    log_prefix = f"[{task_id}] Mistral Client ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}.")

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
        # Map tool_choice to Mistral-specific values
        if tool_choice == "required":
            payload["tool_choice"] = "any"
        elif tool_choice:
            payload["tool_choice"] = tool_choice
        else:
            payload["tool_choice"] = "auto"

    logger.debug(f"{log_prefix} Payload: {json.dumps(payload, indent=2)}")

    # Calculate token breakdown from input messages (estimate)
    token_breakdown = calculate_token_breakdown(messages, model_id)

    async def _process_non_stream_response(response_json: Dict[str, Any]) -> UnifiedMistralResponse:
        logger.info(f"{log_prefix} Received non-streamed response.")
        try:
            raw_api_response = RawMistralChatCompletionResponse(**response_json)
            # Add breakdown to usage
            if raw_api_response.usage:
                raw_api_response.usage.user_input_tokens = token_breakdown.get("user_input_tokens")
                raw_api_response.usage.system_prompt_tokens = token_breakdown.get("system_prompt_tokens")
                
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
                        except json.JSONDecodeError as e:
                            parsing_err_msg = f"JSONDecodeError: {e}"
                        unified_resp_obj.tool_calls_made.append(ParsedMistralToolCall(
                            tool_call_id=tc.id, function_name=tc.function.name,
                            function_arguments_raw=tc.function.arguments,
                            function_arguments_parsed=parsed_args, parsing_error=parsing_err_msg
                        ))
                elif message_data.content is not None:
                    unified_resp_obj.direct_message_content = message_data.content
            return unified_resp_obj
        except Exception as e:
            logger.error(f"{log_prefix} Failed to parse non-streamed response: {e}", exc_info=True)
            return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))

    async def _iterate_stream_response(client: httpx.AsyncClient) -> AsyncIterator[Union[str, ParsedMistralToolCall, MistralUsage]]:
        current_tool_call_id: Optional[str] = None
        current_tool_function_name: Optional[str] = None
        current_tool_function_args_buffer: str = ""
        
        usage_info: Optional[Dict[str, int]] = None
        aggregated_response = ""
        was_interrupted = False

        try:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                logger.info(f"{log_prefix} Stream connection established.")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_json = line[len("data: "):]
                        if data_json.strip() == "[DONE]":
                            logger.info(f"{log_prefix} Stream finished with [DONE].")
                            break
                        try:
                            chunk = json.loads(data_json)
                            if "usage" in chunk and chunk["usage"] is not None:
                                usage_info = chunk["usage"]
                                # Do not continue here, as the last chunk can have both usage and a final delta.
                            
                            if chunk.get("choices"):
                                choice = chunk["choices"][0]
                                delta = choice.get("delta", {})
                                if delta.get("content"):
                                    content_chunk = delta["content"]
                                    aggregated_response += content_chunk
                                    yield content_chunk
                                if delta.get("tool_calls"):
                                    for tc_delta_part in delta["tool_calls"]:
                                        new_tool_id = tc_delta_part.get("id")
                                        func_details = tc_delta_part.get("function", {})
                                        if new_tool_id:
                                            if current_tool_function_name:
                                                parsed_args, err_msg = None, "Incomplete tool call"
                                                try: parsed_args = json.loads(current_tool_function_args_buffer)
                                                except json.JSONDecodeError as e: err_msg += f" JSONDecodeError: {e}"
                                                yield ParsedMistralToolCall(tool_call_id=current_tool_call_id, function_name=current_tool_function_name, function_arguments_raw=current_tool_function_args_buffer, function_arguments_parsed=parsed_args, parsing_error=err_msg)
                                            current_tool_call_id = new_tool_id
                                            current_tool_function_name = func_details.get("name")
                                            current_tool_function_args_buffer = func_details.get("arguments", "")
                                        elif current_tool_function_name:
                                            current_tool_function_args_buffer += func_details.get("arguments", "")
                                if choice.get("finish_reason") == "tool_calls" and current_tool_function_name:
                                    parsed_args, err_msg = None, None
                                    try:
                                        parsed_args = json.loads(current_tool_function_args_buffer)
                                    except json.JSONDecodeError as e:
                                        err_msg = f"Stream JSONDecodeError: {e}"
                                    yield ParsedMistralToolCall(
                                        tool_call_id=current_tool_call_id,
                                        function_name=current_tool_function_name,
                                        function_arguments_raw=current_tool_function_args_buffer,
                                        function_arguments_parsed=parsed_args,
                                        parsing_error=err_msg
                                    )
                                    current_tool_function_name, current_tool_function_args_buffer, current_tool_call_id = None, "", None
                        except json.JSONDecodeError:
                            logger.warning(f"{log_prefix} Failed to decode JSON from stream line: {data_json}")
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            logger.warning(f"{log_prefix} Stream interrupted due to network error: {e}")
            was_interrupted = True
        except Exception as e:
            logger.error(f"{log_prefix} Unhandled error during stream processing: {e}", exc_info=True)
            was_interrupted = True
        
        # After the loop, if we have collected usage info, yield it
        if usage_info:
            final_usage = MistralUsage(
                prompt_tokens=usage_info.get("prompt_tokens", 0),
                completion_tokens=usage_info.get("completion_tokens", 0),
                total_tokens=usage_info.get("total_tokens", 0),
                user_input_tokens=token_breakdown.get("user_input_tokens"),
                system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
            )
            logger.info(f"[{task_id}] Mistral Client: Yielding final usage info from streaming response.")
            yield final_usage
        
        # If the stream finished (interrupted or not) and we don't have usage info, we must estimate it.
        else:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                encoding = tiktoken.encoding_for_model("gpt-4") # Fallback

            # Estimate input tokens from the original payload
            estimated_input_tokens = 0
            if payload.get("messages"):
                # This is a simplified representation. For full accuracy, one would
                # replicate the exact prompt format with special tokens.
                conversation_text = ""
                for message in payload["messages"]:
                    # Simple concatenation; real implementation might need role tokens etc.
                    conversation_text += message.get("role", "") + "\n" + str(message.get("content", "")) + "\n"
                estimated_input_tokens = len(encoding.encode(conversation_text))

            # Estimate output tokens from the aggregated response
            estimated_output_tokens = len(encoding.encode(aggregated_response))
            
            log_message_prefix = "Mistral stream was interrupted." if was_interrupted else "Mistral stream finished without usage info."
            logger.warning(f"[{task_id}] {log_message_prefix} Estimating tokens: "
                           f"Input ~{estimated_input_tokens}, Output ~{estimated_output_tokens}")

            if estimated_input_tokens > 0 or estimated_output_tokens > 0:
                estimated_usage = MistralUsage(
                    prompt_tokens=estimated_input_tokens,
                    completion_tokens=estimated_output_tokens,
                    total_tokens=estimated_input_tokens + estimated_output_tokens,
                    user_input_tokens=token_breakdown.get("user_input_tokens"),
                    system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
                )
                log_yield_reason = "interrupted stream" if was_interrupted else "stream without usage info"
                logger.info(f"[{task_id}] Mistral Client: Yielding ESTIMATED usage for {log_yield_reason}.")
                yield estimated_usage


    if stream:
        return _iterate_stream_response(httpx.AsyncClient(timeout=180.0))
    else:
        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                response.raise_for_status()
                return await _process_non_stream_response(response.json())
            except httpx.HTTPStatusError as e:
                err_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
                return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)
            except Exception as e:
                logger.error(f"{log_prefix} Unexpected error: {e}", exc_info=True)
                return UnifiedMistralResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))

if __name__ == '__main__':
    async def main_test():
        logging.basicConfig(level=logging.DEBUG)
        test_sm = SecretsManager()
        await initialize_mistral_client(test_sm)

        if MISTRAL_API_KEY:
            logger.info("Test: Mistral API key loaded.")
            # Add tests here
        else:
            logger.error("Test: Mistral API key not loaded. Cannot run tests.")

    import asyncio
    asyncio.run(main_test())
