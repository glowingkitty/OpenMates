# backend/apps/ai/llm_providers/google_client.py
# Client for interacting with Google Gemini models via Vertex AI, using the google-genai SDK.

import logging
import json
import os
import tempfile
import uuid
import atexit
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import tiktoken

# Use the newer google-genai library
from google import genai
from google.genai import types
from google.genai import errors as google_errors
from pydantic import BaseModel, Field

from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# --- Global State ---
GOOGLE_PROJECT_ID: Optional[str] = None
GOOGLE_LOCATION: Optional[str] = None
_google_client_initialized = False
_temp_credentials_file: Optional[str] = None


# --- Pydantic Models for Structured Google Response (remain compatible) ---

class GoogleUsageMetadata(BaseModel):
    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int

class RawGoogleChatCompletionResponse(BaseModel):
    text: Optional[str] = None
    function_calls: Optional[List[Dict[str, Any]]] = None
    usage_metadata: Optional[GoogleUsageMetadata] = None

class ParsedGoogleToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Dict[str, Any]
    parsing_error: Optional[str] = None

class UnifiedGoogleResponse(BaseModel):
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedGoogleToolCall]] = None
    raw_response: Optional[RawGoogleChatCompletionResponse] = None
    usage: Optional[GoogleUsageMetadata] = None


async def initialize_google_client(secrets_manager: SecretsManager):
    global _google_client_initialized, GOOGLE_PROJECT_ID, GOOGLE_LOCATION, _temp_credentials_file
    if _google_client_initialized:
        logger.debug("Google GenAI client already initialized.")
        return

    try:
        logger.info("Attempting to initialize Google GenAI client for Vertex AI...")
        
        secret_path = "kv/data/providers/google"
        service_account_str = await secrets_manager.get_secret(secret_path=secret_path, secret_key="service_account_json")
        project_id = await secrets_manager.get_secret(secret_path=secret_path, secret_key="project_id")
        location = await secrets_manager.get_secret(secret_path=secret_path, secret_key="location")

        if not location:
            location = 'global'
            logger.info(f"Location not found in secrets. Defaulting to '{location}'.")

        if not all([project_id, service_account_str]):
            logger.error(f"Google config (project_id, service_account_json) not found at '{secret_path}'. Initialization failed.")
            return
        
        GOOGLE_PROJECT_ID = project_id
        GOOGLE_LOCATION = location

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json", encoding='utf-8') as fp:
            fp.write(service_account_str)
            _temp_credentials_file = fp.name
        
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _temp_credentials_file
        logger.info(f"Set GOOGLE_APPLICATION_CREDENTIALS to temporary file: {_temp_credentials_file}")

        _google_client_initialized = True
        logger.info(f"Google GenAI credentials initialized successfully for project '{GOOGLE_PROJECT_ID}' in '{GOOGLE_LOCATION}'.")

    except Exception as e:
        logger.error(f"Error during Google GenAI client initialization: {e}", exc_info=True)
        if _temp_credentials_file and os.path.exists(_temp_credentials_file):
            os.remove(_temp_credentials_file)
        _google_client_initialized = False


def _cleanup_google_client():
    global _temp_credentials_file
    if _temp_credentials_file and os.path.exists(_temp_credentials_file):
        try:
            os.remove(_temp_credentials_file)
            logger.info(f"Cleaned up temporary Google credentials file: {_temp_credentials_file}")
            _temp_credentials_file = None
        except OSError as e:
            logger.error(f"Error cleaning up temp credentials file {_temp_credentials_file}: {e}")

atexit.register(_cleanup_google_client)


def _map_tools_to_google_format(tools: List[Dict[str, Any]]) -> Optional[List[types.Tool]]:
    if not tools:
        return None
    
    function_declarations = []
    for tool_def in tools:
        if tool_def.get("type") == "function":
            func = tool_def.get("function", {})
            function_declarations.append(
                types.FunctionDeclaration(
                    name=func.get("name"),
                    description=func.get("description"),
                    parameters=func.get("parameters"),
                )
            )
    
    return [types.Tool(function_declarations=function_declarations)] if function_declarations else None


def _prepare_messages_and_system_prompt(messages: List[Dict[str, str]]) -> (Optional[str], List[types.Content]):
    system_prompt = None
    history = []
    
    processed_messages = list(messages)
    
    if processed_messages and processed_messages[0].get("role") == "system":
        system_prompt = processed_messages.pop(0)["content"]

    for msg in processed_messages:
        role = "user" if msg.get("role") == "user" else "model"
        content = msg.get("content", "")
        if content:
            history.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
            
    return system_prompt, history


async def invoke_google_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False
) -> Union[UnifiedGoogleResponse, AsyncIterator[Union[str, ParsedGoogleToolCall, GoogleUsageMetadata]]]:
    if not _google_client_initialized:
        if secrets_manager:
            await initialize_google_client(secrets_manager)
        else:
            error_msg = "SecretsManager not provided, and Google client is not initialized."
            logger.error(f"[{task_id}] {error_msg}")
            if stream: raise ValueError(error_msg)
            return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    if not _google_client_initialized:
        error_msg = "Google client credential initialization failed. Check logs for details."
        logger.error(f"[{task_id}] {error_msg}")
        if stream: raise ValueError(error_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    try:
        google_genai_client = genai.Client(vertexai=True, project=GOOGLE_PROJECT_ID, location=GOOGLE_LOCATION)
    except Exception as e:
        error_msg = f"Failed to create Google GenAI client: {e}"
        logger.error(f"[{task_id}] {error_msg}", exc_info=True)
        if stream: raise ValueError(error_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    log_prefix = f"[{task_id}] Google Client ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        system_prompt, contents = _prepare_messages_and_system_prompt(messages)
        
        if not contents:
            err_msg = "Message history is empty after processing."
            if stream: raise ValueError(err_msg)
            return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

        google_tools = _map_tools_to_google_format(tools)
        
        tool_config_dict = {}
        if google_tools:
            mode_map = {"auto": "AUTO", "any": "ANY", "none": "NONE"}
            selected_mode = mode_map.get((tool_choice or "auto").lower(), "AUTO")
            tool_config_dict = {"function_calling_config": {"mode": selected_mode}}

        generation_config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_prompt,
            tools=google_tools,
            tool_config=tool_config_dict if tool_config_dict else None,
        )

    except Exception as e:
        err_msg = f"Error during request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream: raise ValueError(err_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

    async def _process_non_stream_response(response: types.GenerateContentResponse) -> UnifiedGoogleResponse:
        logger.info(f"{log_prefix} Received non-streamed response from API.")
        
        raw_response_pydantic = RawGoogleChatCompletionResponse(
            text=response.text,
            function_calls=[fc.to_dict() for fc in response.function_calls] if response.function_calls else None,
            usage_metadata=GoogleUsageMetadata.model_validate(response.usage_metadata.to_dict()) if response.usage_metadata else None
        )

        unified_resp = UnifiedGoogleResponse(
            task_id=task_id, model_id=model_id, success=True,
            raw_response=raw_response_pydantic, usage=raw_response_pydantic.usage_metadata
        )
        
        if response.function_calls:
            unified_resp.tool_calls_made = []
            for fc in response.function_calls:
                args_dict = dict(fc.args)
                unified_resp.tool_calls_made.append(ParsedGoogleToolCall(
                    tool_call_id=f"{fc.name}-{uuid.uuid4().hex[:8]}",
                    function_name=fc.name,
                    function_arguments_parsed=args_dict,
                    function_arguments_raw=json.dumps(args_dict)
                ))
            logger.info(f"{log_prefix} Call resulted in {len(unified_resp.tool_calls_made)} tool call(s).")
        
        elif response.text:
            unified_resp.direct_message_content = response.text
            logger.info(f"{log_prefix} Call resulted in a direct message response.")
        
        else:
            unified_resp.error_message = "Response has no text or function calls."
            logger.warning(f"{log_prefix} {unified_resp.error_message}")
            
        return unified_resp

    async def _iterate_stream_response() -> AsyncIterator[Union[str, ParsedGoogleToolCall, GoogleUsageMetadata]]:
        logger.info(f"{log_prefix} Stream connection initiated.")
        stream_iterator = None
        output_buffer = ""
        usage = None
        try:
            stream_iterator = await google_genai_client.aio.models.generate_content_stream(
                model=model_id,
                contents=contents,
                config=generation_config
            )
            
            async for chunk in stream_iterator:
                if chunk.function_calls:
                    for fc in chunk.function_calls:
                        args_dict = dict(fc.args)
                        parsed_tool_call = ParsedGoogleToolCall(
                            tool_call_id=f"{fc.name}-{uuid.uuid4().hex[:8]}",
                            function_name=fc.name,
                            function_arguments_parsed=args_dict,
                            function_arguments_raw=json.dumps(args_dict)
                        )
                        logger.info(f"{log_prefix} Yielding a tool call from stream: {fc.name}")
                        yield parsed_tool_call
                elif chunk.text:
                    output_buffer += chunk.text
                    yield chunk.text
            
            # After the stream is done, the response object on the iterator has usage metadata
            try:
                if stream_iterator and stream_iterator.response and stream_iterator.response.usage_metadata:
                    usage_dict = stream_iterator.response.usage_metadata.to_dict()
                    
                    # Manually add system prompt tokens if they are not included by the API.
                    # This ensures consistent and accurate billing.
                    if system_prompt:
                        try:
                            encoding = tiktoken.get_encoding("cl100k_base")
                            system_prompt_tokens = len(encoding.encode(system_prompt))
                            
                            # Add system prompt tokens to the counts from the API
                            usage_dict['prompt_token_count'] += system_prompt_tokens
                            usage_dict['total_token_count'] += system_prompt_tokens
                            logger.info(f"{log_prefix} Manually added {system_prompt_tokens} system prompt tokens to usage metadata.")
                        except Exception as e_tok:
                            logger.error(f"{log_prefix} Could not encode system_prompt to add tokens manually: {e_tok}")

                    usage = GoogleUsageMetadata.model_validate(usage_dict)
                    yield usage
            except Exception as e:
                logger.warning(f"{log_prefix} Could not extract usage metadata after stream: {e}")

            logger.info(f"{log_prefix} Stream finished.")

        except google_errors.APIError as e_api:
            err_msg = f"Google API error during streaming: {e_api}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Google API Error: {e_api}") from e_api
        except Exception as e_stream:
            err_msg = f"Unexpected error during streaming: {e_stream}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Google API Unexpected Streaming Error: {e_stream}") from e_stream
        finally:
            if not usage:
                logger.warning(f"{log_prefix} Stream interrupted or finished without usage data. Estimating tokens with tiktoken.")
                try:
                    encoding = tiktoken.get_encoding("cl100k_base")
                    system_prompt_tokens = len(encoding.encode(system_prompt)) if system_prompt else 0
                    prompt_tokens = sum(len(encoding.encode(part.text)) for content in contents for part in content.parts) + system_prompt_tokens
                    completion_tokens = len(encoding.encode(output_buffer))
                    usage = GoogleUsageMetadata(
                        prompt_token_count=prompt_tokens,
                        candidates_token_count=completion_tokens,
                        total_token_count=prompt_tokens + completion_tokens
                    )
                    yield usage
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to estimate tokens with tiktoken: {e}", exc_info=True)


    if stream:
        return _iterate_stream_response()
    else:
        try:
            response = await google_genai_client.aio.models.generate_content(
                model=model_id,
                contents=contents,
                config=generation_config
            )
            return await _process_non_stream_response(response)
        except google_errors.APIError as e_api:
            err_msg = f"Google API error calling API: {e_api}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e_api))
        except Exception as e_gen:
            err_msg = f"Unexpected error during API call: {e_gen}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e_gen))
