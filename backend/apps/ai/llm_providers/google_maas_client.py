# backend/apps/ai/llm_providers/google_maas_client.py
# Client for interacting with non-Google models on Google Vertex AI Model-as-a-Service (MaaS).
#
# Google Vertex AI MaaS hosts third-party models (DeepSeek, Qwen, Llama, etc.) using an
# OpenAI-compatible /chat/completions endpoint, NOT the Gemini generateContent API.
# This client sends requests in standard OpenAI format via httpx to the MaaS endpoint.
#
# Architecture note:
# - google_client.py -> Uses google-genai SDK + Gemini generateContent API (for Google models)
# - google_maas_client.py (this file) -> Uses httpx + OpenAI-compatible API (for third-party MaaS models)
#
# The function name `invoke_google_maas_chat_completions` is auto-discovered by the provider
# registry in llm_utils.py, matching server_id "google_maas" in provider YAML configs.

import logging
import json
import httpx
import time
from typing import Dict, Any, List, Optional, Union, AsyncIterator

from .openai_shared import (
    UnifiedOpenAIResponse,
    ParsedOpenAIToolCall,
    OpenAIUsageMetadata,
    RawOpenAIChatCompletionResponse,
    _map_tools_to_openai_format,
    calculate_token_breakdown,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

# Default timeout for API calls (in seconds)
DEFAULT_TIMEOUT = 180.0

# Cache for the access token (short-lived, refreshed as needed)
_cached_access_token: Optional[str] = None
_cached_token_expiry: float = 0.0

# Cache for project/location from Vault
_cached_project_id: Optional[str] = None
_cached_location: Optional[str] = None


async def _get_google_maas_credentials(secrets_manager: SecretsManager) -> tuple:
    """
    Retrieve Google Vertex AI project ID, location, and a fresh access token
    using service account credentials from Vault.

    Returns:
        Tuple of (project_id, location, access_token)

    Raises:
        ValueError if credentials cannot be obtained.
    """
    global _cached_access_token, _cached_token_expiry, _cached_project_id, _cached_location

    secret_path = "kv/data/providers/google"

    # Get project_id and location (cached after first load)
    if not _cached_project_id:
        _cached_project_id = await secrets_manager.get_secret(secret_path=secret_path, secret_key="project_id")
        _cached_location = await secrets_manager.get_secret(secret_path=secret_path, secret_key="location") or "global"

    if not _cached_project_id:
        raise ValueError("Google project_id not configured in Vault at 'kv/data/providers/google'")

    # Get a fresh access token using google-auth (reads GOOGLE_APPLICATION_CREDENTIALS)
    # Token is cached and refreshed when expired
    current_time = time.time()
    if _cached_access_token and current_time < _cached_token_expiry - 60:
        # Token still valid (with 60s buffer)
        return _cached_project_id, _cached_location, _cached_access_token

    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        # Refresh the token
        credentials.refresh(google.auth.transport.requests.Request())
        _cached_access_token = credentials.token
        # Set expiry - google-auth tokens are typically valid for 1 hour
        _cached_token_expiry = current_time + 3500  # ~58 minutes
        return _cached_project_id, _cached_location, _cached_access_token
    except Exception as e:
        raise ValueError(f"Failed to obtain Google access token: {e}") from e


def _build_maas_url(project_id: str, location: str) -> str:
    """
    Build the Google Vertex AI MaaS OpenAI-compatible endpoint URL.

    The endpoint follows the format:
    https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/endpoints/openapi/chat/completions

    For location='global', uses 'us-central1' as the API host since global is not
    a valid Vertex AI API hostname prefix.
    """
    # 'global' location routes to us-central1 for API access
    api_location = location if location != "global" else "us-central1"
    return (
        f"https://{api_location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/"
        f"endpoints/openapi/chat/completions"
    )


async def invoke_google_maas_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    """
    Google Vertex AI MaaS client using OpenAI-compatible chat/completions API.

    This client is used for non-Google models hosted on Vertex AI MaaS (e.g., DeepSeek, Qwen).
    These models use the standard OpenAI message format, NOT the Gemini generateContent format.

    The function name matches the pattern invoke_{server_id}_chat_completions for auto-discovery
    by the provider registry, where server_id = "google_maas".

    Args:
        task_id: Unique identifier for the task (Celery task ID)
        model_id: The MaaS model ID including publisher prefix (e.g., "deepseek-ai/deepseek-v3.2-maas")
        messages: List of message objects with role and content (OpenAI format)
        secrets_manager: SecretsManager instance for retrieving credentials
        temperature: Sampling temperature (default: 0.7)
        max_tokens: Maximum number of tokens to generate
        tools: List of tool definitions in OpenAI format
        tool_choice: Tool choice strategy ("auto", "none", "required")
        stream: Whether to stream the response

    Returns:
        If stream=False, returns a UnifiedOpenAIResponse object.
        If stream=True, returns an AsyncIterator yielding strings, ParsedOpenAIToolCall, or OpenAIUsageMetadata.
    """
    log_prefix = f"[{task_id}] Google MaaS Client ({model_id}):"

    if not secrets_manager:
        error_msg = "SecretsManager not provided for Google MaaS client"
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    try:
        project_id, location, access_token = await _get_google_maas_credentials(secrets_manager)
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"{log_prefix} {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    api_url = _build_maas_url(project_id, location)
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. URL: {api_url}")

    # Build OpenAI-compatible request payload
    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }

    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    if tools:
        openai_tools = _map_tools_to_openai_format(tools)
        if openai_tools:
            payload["tools"] = openai_tools
            if tool_choice:
                if tool_choice == "required":
                    # Force tool usage: if single tool, specify it; otherwise use "auto"
                    if len(openai_tools) == 1 and "function" in openai_tools[0]:
                        function_name = openai_tools[0]["function"].get("name")
                        if function_name:
                            payload["tool_choice"] = {"type": "function", "function": {"name": function_name}}
                        else:
                            payload["tool_choice"] = "auto"
                    else:
                        payload["tool_choice"] = "auto"
                else:
                    payload["tool_choice"] = tool_choice

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    if stream:
        return _stream_google_maas_response(task_id, model_id, payload, headers, api_url)
    else:
        return await _send_google_maas_request(task_id, model_id, payload, headers, api_url)


async def _send_google_maas_request(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    api_url: str,
) -> UnifiedOpenAIResponse:
    """
    Sends a non-streaming request to the Google MaaS OpenAI-compatible endpoint.
    """
    log_prefix = f"[{task_id}] Google MaaS Client:"
    start_time = time.time()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)
            logger.info(f"{log_prefix} Received response: HTTP {response.status_code}")

            if response.status_code >= 400:
                error_text = response.text[:500]
                error_msg = f"HTTP {response.status_code}: {error_text}"
                logger.error(f"{log_prefix} API error: {error_msg}")
                return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

            response_data = response.json()
            elapsed_time = time.time() - start_time
            logger.info(f"{log_prefix} Request completed in {elapsed_time:.2f}s")

            choices = response_data.get("choices", [])
            if not choices:
                return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message="No choices in response")

            first_choice = choices[0]
            message = first_choice.get("message", {})
            content = message.get("content")

            # Extract usage
            usage_data = response_data.get("usage", {})
            messages_for_breakdown = payload.get("messages", [])
            breakdown = calculate_token_breakdown(messages_for_breakdown, model_id, tools=payload.get("tools"))

            usage = OpenAIUsageMetadata(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                user_input_tokens=breakdown.get("user_input_tokens"),
                system_prompt_tokens=breakdown.get("system_prompt_tokens"),
            )

            # Handle tool calls
            tool_calls_made = None
            if "tool_calls" in message:
                tool_calls_made = []
                for tc in message.get("tool_calls", []):
                    if tc.get("type") == "function":
                        func_data = tc.get("function", {})
                        func_name = func_data.get("name", "")
                        args_raw = func_data.get("arguments", "{}")
                        parsed_args = {}
                        parsing_error = None
                        try:
                            parsed_args = json.loads(args_raw)
                        except json.JSONDecodeError as e:
                            parsing_error = f"Failed to parse function arguments: {e}"
                            logger.error(f"{log_prefix} {parsing_error}")
                        tool_calls_made.append(
                            ParsedOpenAIToolCall(
                                tool_call_id=tc.get("id", ""),
                                function_name=func_name,
                                function_arguments_raw=args_raw,
                                function_arguments_parsed=parsed_args,
                                parsing_error=parsing_error,
                            )
                        )

            raw_response = RawOpenAIChatCompletionResponse(
                text=content,
                tool_calls=message.get("tool_calls"),
                usage_metadata=usage,
            )

            return UnifiedOpenAIResponse(
                task_id=task_id,
                model_id=model_id,
                success=True,
                direct_message_content=content,
                tool_calls_made=tool_calls_made,
                raw_response=raw_response,
                usage=usage,
            )

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text[:500]}"
        logger.error(f"{log_prefix} {error_msg}")
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)
    except httpx.RequestError as e:
        error_msg = f"Request error: {e}"
        logger.error(f"{log_prefix} {error_msg}")
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)


async def _stream_google_maas_response(
    task_id: str,
    model_id: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    api_url: str,
) -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
    """
    Streams the response from Google MaaS OpenAI-compatible endpoint.

    Uses SSE (Server-Sent Events) format identical to OpenAI's streaming API.
    Yields text content, tool calls, and usage metadata.
    """
    log_prefix = f"[{task_id}] Google MaaS Client (Stream):"
    logger.info(f"{log_prefix} Starting stream request to {api_url}")

    payload["stream"] = True

    cumulative_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    tool_calls_buffer: Dict[int, Dict[str, Any]] = {}

    messages_for_breakdown = payload.get("messages", [])
    token_breakdown = calculate_token_breakdown(messages_for_breakdown, model_id, tools=payload.get("tools"))

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", api_url, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT) as response:
                # Handle HTTP errors
                if response.status_code >= 400:
                    error_body = b""
                    try:
                        async for chunk in response.aiter_bytes():
                            error_body += chunk
                            if len(error_body) > 10000:
                                break
                    except Exception as e:
                        logger.warning(f"{log_prefix} Error reading error response body: {e}")

                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_text = error_body.decode("utf-8", errors="ignore").strip()
                        if error_text:
                            try:
                                error_detail = json.loads(error_text)
                                error_msg = error_detail.get("error", {}).get("message", error_msg)
                            except json.JSONDecodeError:
                                error_msg = f"HTTP {response.status_code}: {error_text[:500]}"
                    except UnicodeDecodeError:
                        error_msg = f"HTTP {response.status_code}: {str(error_body[:500])}"

                    logger.error(f"{log_prefix} API error: {error_msg}")
                    raise IOError(f"Google MaaS API Error: {error_msg}")

                # Process SSE stream
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if line.startswith(":"):
                        continue

                    if line.startswith("data: "):
                        line = line[6:]
                    else:
                        continue

                    if line.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(line)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta", {})

                        # Handle text content
                        if "content" in delta and delta["content"]:
                            yield delta["content"]

                        # Handle tool calls (streamed incrementally)
                        if "tool_calls" in delta:
                            for tc_delta in delta["tool_calls"]:
                                tc_id = tc_delta.get("id", "")
                                tc_index = tc_delta.get("index", 0)
                                buffer_key = tc_index

                                if buffer_key not in tool_calls_buffer:
                                    tool_calls_buffer[buffer_key] = {
                                        "id": tc_id,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                elif tc_id:
                                    tool_calls_buffer[buffer_key]["id"] = tc_id

                                if "function" in tc_delta and "name" in tc_delta["function"]:
                                    tool_calls_buffer[buffer_key]["function"]["name"] = tc_delta["function"]["name"]
                                if "function" in tc_delta and "arguments" in tc_delta["function"]:
                                    tool_calls_buffer[buffer_key]["function"]["arguments"] += tc_delta["function"]["arguments"]

                        # Yield tool calls on finish_reason
                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("tool_calls", "tool_call") and tool_calls_buffer:
                            for _key, tc in tool_calls_buffer.items():
                                func_name = tc["function"]["name"]
                                args_raw = tc["function"]["arguments"]
                                parsed_args = {}
                                parsing_error = None
                                try:
                                    parsed_args = json.loads(args_raw)
                                except json.JSONDecodeError as e:
                                    parsing_error = f"Failed to parse function arguments: {e}"
                                    logger.error(f"{log_prefix} {parsing_error}")
                                yield ParsedOpenAIToolCall(
                                    tool_call_id=tc["id"],
                                    function_name=func_name,
                                    function_arguments_raw=args_raw,
                                    function_arguments_parsed=parsed_args,
                                    parsing_error=parsing_error,
                                )
                            tool_calls_buffer.clear()

                        # Update usage if present
                        if "usage" in chunk:
                            usage = chunk["usage"]
                            cumulative_usage["input_tokens"] = usage.get("prompt_tokens", cumulative_usage["input_tokens"])
                            cumulative_usage["output_tokens"] = usage.get("completion_tokens", cumulative_usage["output_tokens"])
                            cumulative_usage["total_tokens"] = usage.get("total_tokens", cumulative_usage["total_tokens"])

                    except json.JSONDecodeError as e:
                        logger.warning(f"{log_prefix} Failed to parse SSE chunk: {e}. Line: {line[:100]}...")
                        continue

                # Yield final usage
                yield OpenAIUsageMetadata(
                    input_tokens=cumulative_usage["input_tokens"],
                    output_tokens=cumulative_usage["output_tokens"],
                    total_tokens=cumulative_usage["total_tokens"],
                    user_input_tokens=token_breakdown.get("user_input_tokens"),
                    system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
                )

                logger.info(f"{log_prefix} Stream completed successfully")

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text[:500] if hasattr(e.response, 'text') else str(e)}"
        logger.error(f"{log_prefix} {error_msg}")
        raise IOError(f"Google MaaS API Error: {error_msg}") from e
    except httpx.RequestError as e:
        error_msg = f"Request error: {e}"
        logger.error(f"{log_prefix} {error_msg}")
        raise IOError(f"Google MaaS API Connection Error: {error_msg}") from e
    except IOError:
        raise  # Re-raise IOError from error handling above
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        raise IOError(f"Google MaaS API Unexpected Error: {error_msg}") from e
