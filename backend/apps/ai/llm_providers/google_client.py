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

# Google AI Studio (Gemini API) API key (optional; used for non-Vertex Gemini models)
GOOGLE_AI_STUDIO_SECRET_PATH = "kv/data/providers/google_ai_studio"
GOOGLE_AI_STUDIO_API_KEY_NAME = "api_key"
_google_ai_studio_api_key: Optional[str] = None


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


def _get_non_empty_env(key: str) -> Optional[str]:
    value = os.environ.get(key)
    if not value:
        return None
    value = value.strip()
    if not value or value == "IMPORTED_TO_VAULT":
        return None
    return value


async def _get_google_ai_studio_api_key(secrets_manager: Optional[SecretsManager]) -> Optional[str]:
    """
    Retrieve Google AI Studio (Gemini API) key.

    Priority:
    1) `GEMINI_API_KEY` env var (matches Google AI Studio examples)
    2) `SECRET__GOOGLE_AI_STUDIO__API_KEY` env var (for setups without Vault)
    3) Vault: `kv/data/providers/google_ai_studio` key `api_key`
    """
    global _google_ai_studio_api_key

    if _google_ai_studio_api_key:
        return _google_ai_studio_api_key

    env_key = _get_non_empty_env("GEMINI_API_KEY") or _get_non_empty_env("SECRET__GOOGLE_AI_STUDIO__API_KEY")
    if env_key:
        _google_ai_studio_api_key = env_key
        return _google_ai_studio_api_key

    if not secrets_manager:
        return None

    try:
        api_key = await secrets_manager.get_secret(
            secret_path=GOOGLE_AI_STUDIO_SECRET_PATH,
            secret_key=GOOGLE_AI_STUDIO_API_KEY_NAME,
        )
        if api_key:
            _google_ai_studio_api_key = api_key
        return api_key
    except Exception as e:
        logger.error(f"Error retrieving Google AI Studio API key: {e}", exc_info=True)
        return None


def _map_tools_to_google_format(tools: List[Dict[str, Any]]) -> Optional[List[types.Tool]]:
    """
    Maps tools from internal format to Google's expected format.
    
    Note: Tools should already be sanitized (min/max removed) before being passed here.
    This function only handles format conversion, not schema sanitization.
    """
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
                    parameters=func.get("parameters"),  # Should already be sanitized
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


def _normalize_google_model_id(model_id: str) -> str:
    """
    Normalize Google Vertex AI model ID - returns model_id as-is.
    
    Google Vertex AI publisher models must be specified with publisher prefixes
    (e.g., "qwen/qwen3-235b-a22b-instruct-2507-maas"). The google-genai SDK
    requires the full model path including the publisher prefix.
    
    Args:
        model_id: The model ID which should include the publisher prefix
        
    Returns:
        The model ID unchanged (with publisher prefix if present)
    """
    # Return model_id as-is - Google API requires the full format including publisher prefix
    # Example: "qwen/qwen3-235b-a22b-instruct-2507-maas"
    return model_id


async def invoke_google_ai_studio_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedGoogleResponse, AsyncIterator[Union[str, ParsedGoogleToolCall, GoogleUsageMetadata]]]:
    """
    Google AI Studio (Gemini API) client using `google-genai` API-key auth.

    Note: This is separate from `invoke_google_chat_completions`, which uses Vertex AI service-account auth.
    """
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        error_msg = (
            "Google AI Studio API key not configured. "
            "Add `SECRET__GOOGLE_AI_STUDIO__API_KEY` (or `GEMINI_API_KEY`) to your environment (see `.env.example`) so it can be imported into Vault."
        )
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    try:
        google_genai_client = genai.Client(api_key=api_key)
    except Exception as e:
        error_msg = f"Failed to create Google AI Studio GenAI client: {e}"
        logger.error(f"[{task_id}] {error_msg}", exc_info=True)
        if stream:
            raise ValueError(error_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    normalized_model_id = _normalize_google_model_id(model_id)
    log_prefix = f"[{task_id}] Google AI Studio Client ({normalized_model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        system_prompt, contents = _prepare_messages_and_system_prompt(messages)
        if not contents:
            err_msg = "Message history is empty after processing."
            if stream:
                raise ValueError(err_msg)
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
        if stream:
            raise ValueError(err_msg)
        return UnifiedGoogleResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

    async def _process_non_stream_response(response: types.GenerateContentResponse) -> UnifiedGoogleResponse:
        logger.info(f"{log_prefix} Received non-streamed response from API.")

        usage_metadata_dict = None
        if response.usage_metadata:
            try:
                usage_metadata_dict = {
                    "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "candidates_token_count": getattr(response.usage_metadata, "candidates_token_count", 0),
                    "total_token_count": getattr(response.usage_metadata, "total_token_count", 0),
                }
            except Exception as e:
                logger.warning(f"{log_prefix} Failed to extract usage_metadata attributes: {e}")
                usage_metadata_dict = None

        raw_response_pydantic = RawGoogleChatCompletionResponse(
            text=response.text,
            function_calls=[fc.to_dict() for fc in response.function_calls] if response.function_calls else None,
            usage_metadata=GoogleUsageMetadata.model_validate(usage_metadata_dict) if usage_metadata_dict else None,
        )

        unified_resp = UnifiedGoogleResponse(
            task_id=task_id, model_id=model_id, success=True, raw_response=raw_response_pydantic, usage=raw_response_pydantic.usage_metadata
        )

        if response.function_calls:
            unified_resp.tool_calls_made = []
            for fc in response.function_calls:
                args_dict = dict(fc.args)
                unified_resp.tool_calls_made.append(
                    ParsedGoogleToolCall(
                        tool_call_id=f"{fc.name}-{uuid.uuid4().hex[:8]}",
                        function_name=fc.name,
                        function_arguments_parsed=args_dict,
                        function_arguments_raw=json.dumps(args_dict),
                    )
                )
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
        stream_succeeded = False
        try:
            stream_iterator = await google_genai_client.aio.models.generate_content_stream(
                model=normalized_model_id,
                contents=contents,
                config=generation_config,
            )

            async for chunk in stream_iterator:
                if chunk.function_calls:
                    for fc in chunk.function_calls:
                        args_dict = dict(fc.args)
                        parsed_tool_call = ParsedGoogleToolCall(
                            tool_call_id=f"{fc.name}-{uuid.uuid4().hex[:8]}",
                            function_name=fc.name,
                            function_arguments_parsed=args_dict,
                            function_arguments_raw=json.dumps(args_dict),
                        )
                        logger.info(f"{log_prefix} Yielding a tool call from stream: {fc.name}")
                        yield parsed_tool_call
                elif chunk.text:
                    output_buffer += chunk.text
                    yield chunk.text

            try:
                usage_metadata_obj = getattr(getattr(stream_iterator, "response", None), "usage_metadata", None)
                if usage_metadata_obj:
                    if hasattr(usage_metadata_obj, "to_dict"):
                        usage_dict = usage_metadata_obj.to_dict()
                    else:
                        usage_dict = {
                            "prompt_token_count": getattr(usage_metadata_obj, "prompt_token_count", 0),
                            "candidates_token_count": getattr(usage_metadata_obj, "candidates_token_count", 0),
                            "total_token_count": getattr(usage_metadata_obj, "total_token_count", 0),
                        }

                    if system_prompt:
                        try:
                            encoding = tiktoken.get_encoding("cl100k_base")
                            system_prompt_tokens = len(encoding.encode(system_prompt))
                            usage_dict["prompt_token_count"] += system_prompt_tokens
                            usage_dict["total_token_count"] += system_prompt_tokens
                            logger.info(f"{log_prefix} Manually added {system_prompt_tokens} system prompt tokens to usage metadata.")
                        except Exception as e_tok:
                            logger.error(f"{log_prefix} Could not encode system_prompt to add tokens manually: {e_tok}")

                    usage = GoogleUsageMetadata.model_validate(usage_dict)
                    yield usage
            except Exception as e:
                logger.warning(f"{log_prefix} Could not extract usage metadata after stream: {e}")

            stream_succeeded = True
            logger.info(f"{log_prefix} Stream finished.")

        except google_errors.APIError as e_api:
            error_str = str(e_api)
            if "404" in error_str or "NOT_FOUND" in error_str or "not found" in error_str.lower():
                logger.error(
                    f"{log_prefix} Google API error: Model not found (404). "
                    f"Model ID used: '{model_id}'. Original error: {e_api}",
                    exc_info=True,
                )
            else:
                err_msg = f"Google API error during streaming: {e_api}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Google API Error: {e_api}") from e_api
        except Exception as e_stream:
            err_msg = f"Unexpected error during streaming: {e_stream}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            raise IOError(f"Google API Unexpected Streaming Error: {e_stream}") from e_stream
        finally:
            if not usage and stream_succeeded:
                logger.warning(f"{log_prefix} Stream finished successfully but without usage data. Estimating tokens with tiktoken.")
                try:
                    encoding = tiktoken.get_encoding("cl100k_base")
                    system_prompt_tokens = len(encoding.encode(system_prompt)) if system_prompt else 0
                    prompt_tokens = sum(len(encoding.encode(part.text)) for content in contents for part in content.parts) + system_prompt_tokens
                    completion_tokens = len(encoding.encode(output_buffer))
                    usage = GoogleUsageMetadata(
                        prompt_token_count=prompt_tokens,
                        candidates_token_count=completion_tokens,
                        total_token_count=prompt_tokens + completion_tokens,
                    )
                    yield usage
                except Exception as e:
                    logger.error(f"{log_prefix} Failed to estimate tokens with tiktoken: {e}", exc_info=True)
            elif not usage and not stream_succeeded:
                logger.info(f"{log_prefix} Stream failed with error. Not estimating usage - billing will be skipped.")

    if stream:
        return _iterate_stream_response()
    else:
        try:
            response = await google_genai_client.aio.models.generate_content(
                model=normalized_model_id,
                contents=contents,
                config=generation_config,
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

    # Normalize model_id by stripping publisher prefixes if present
    # Google Vertex AI expects just the model name, not "publisher/model-name"
    normalized_model_id = _normalize_google_model_id(model_id)
    
    log_prefix = f"[{task_id}] Google Client ({normalized_model_id}):"
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
        
        # Convert usage_metadata from protobuf object to dict by accessing attributes directly
        # The usage_metadata object doesn't have a to_dict() method, so we access its attributes
        usage_metadata_dict = None
        if response.usage_metadata:
            try:
                usage_metadata_dict = {
                    "prompt_token_count": getattr(response.usage_metadata, "prompt_token_count", 0),
                    "candidates_token_count": getattr(response.usage_metadata, "candidates_token_count", 0),
                    "total_token_count": getattr(response.usage_metadata, "total_token_count", 0),
                }
            except Exception as e:
                logger.warning(f"{log_prefix} Failed to extract usage_metadata attributes: {e}")
                usage_metadata_dict = None
        
        raw_response_pydantic = RawGoogleChatCompletionResponse(
            text=response.text,
            function_calls=[fc.to_dict() for fc in response.function_calls] if response.function_calls else None,
            usage_metadata=GoogleUsageMetadata.model_validate(usage_metadata_dict) if usage_metadata_dict else None
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
        stream_succeeded = False  # Track if stream completed successfully (no exception)
        try:
            stream_iterator = await google_genai_client.aio.models.generate_content_stream(
                model=normalized_model_id,
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

            # Mark stream as succeeded if we got here without exceptions
            stream_succeeded = True
            logger.info(f"{log_prefix} Stream finished.")

        except google_errors.APIError as e_api:
            # Improve error message for 404 errors (model not found)
            error_str = str(e_api)
            if "404" in error_str or "NOT_FOUND" in error_str or "not found" in error_str.lower():
                logger.error(
                    f"{log_prefix} Google API error: Model not found (404). "
                    f"This usually means the model path is incorrect or the project doesn't have access to this model. "
                    f"Model ID used: '{model_id}'. "
                    f"Please verify the model identifier in the provider configuration. "
                    f"Original error: {e_api}",
                    exc_info=True
                )
            else:
                err_msg = f"Google API error during streaming: {e_api}"
                logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            # Don't estimate usage for API errors - stream failed
            raise IOError(f"Google API Error: {e_api}") from e_api
        except Exception as e_stream:
            err_msg = f"Unexpected error during streaming: {e_stream}"
            logger.error(f"{log_prefix} {err_msg}", exc_info=True)
            # Don't estimate usage for unexpected errors - stream failed
            raise IOError(f"Google API Unexpected Streaming Error: {e_stream}") from e_stream
        finally:
            # Only estimate usage if stream completed successfully but didn't provide usage metadata
            # This handles cases where the stream finished but usage metadata wasn't available
            # We should NOT estimate usage when the stream failed due to errors
            if not usage and stream_succeeded:
                logger.warning(f"{log_prefix} Stream finished successfully but without usage data. Estimating tokens with tiktoken.")
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
            elif not usage and not stream_succeeded:
                logger.info(f"{log_prefix} Stream failed with error. Not estimating usage - billing will be skipped.")


    if stream:
        return _iterate_stream_response()
    else:
        try:
            response = await google_genai_client.aio.models.generate_content(
                model=normalized_model_id,
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
