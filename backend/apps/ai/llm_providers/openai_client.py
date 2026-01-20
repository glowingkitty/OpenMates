"""
Unified OpenAI client that supports:
- Direct OpenAI API
- OpenRouter delegation
- Azure scaffold (to be implemented)
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Union
import logging

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager

from .openai_shared import (
    UnifiedOpenAIResponse,
    ParsedOpenAIToolCall,
    OpenAIUsageMetadata,
    RawOpenAIChatCompletionResponse,
    _map_tools_to_openai_format,
    calculate_token_breakdown,
)
from .openai_openrouter import invoke_openrouter_chat_completions

try:
    from openai import AsyncOpenAI  # type: ignore
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore

logger = logging.getLogger(__name__)

# Global state
_openai_client_initialized: bool = False
_openai_direct_client: Optional["AsyncOpenAI"] = None
_openai_api_key: Optional[str] = None
_openai_base_url: Optional[str] = None
_openai_organization: Optional[str] = None
_openai_project: Optional[str] = None


def _is_reasoning_model(model_id: str) -> bool:
    """Check if model is a reasoning model based on config."""
    try:
        model_config = config_manager.get_model_pricing("openai", model_id)
        if model_config and model_config.get("features", {}).get("reasoning_token_support"):
            return True
        # Fallback for known reasoning models if config is missing
        return model_id.startswith(("o1", "o3", "gpt-5"))
    except Exception:
        return model_id.startswith(("o1", "o3", "gpt-5"))


def _select_server_for_model(model_id: str) -> str:
    """Return one of: "openai", "openrouter", or "azure" (default "openai")."""
    try:
        provider_config = config_manager.get_provider_config("openai")
        if not provider_config:
            return "openai"
        for model in provider_config.get("models", []):
            if isinstance(model, dict) and model.get("id") == model_id:
                default_server = model.get("default_server")
                if default_server in {"openai", "openrouter", "azure"}:
                    return default_server
                break
        return "openai"
    except Exception:
        return "openai"


async def initialize_openai_client(secrets_manager: SecretsManager) -> None:
    """Initialize AsyncOpenAI client from Vault secrets (openai api)."""
    global _openai_client_initialized, _openai_direct_client
    global _openai_api_key, _openai_base_url, _openai_organization, _openai_project

    if _openai_client_initialized:
        logger.debug("OpenAI client already initialized.")
        return

    if AsyncOpenAI is None:
        logger.error("OpenAI SDK missing; install 'openai'.")
        _openai_client_initialized = False
        return

    secret_path = "kv/data/providers/openai"
    try:
        _openai_api_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="api_key")
        _openai_base_url = await secrets_manager.get_secret(secret_path=secret_path, secret_key="base_url")
        _openai_organization = await secrets_manager.get_secret(secret_path=secret_path, secret_key="organization")
        _openai_project = await secrets_manager.get_secret(secret_path=secret_path, secret_key="project")

        if not _openai_api_key:
            logger.error("OpenAI API key not found in Vault; direct API disabled.")
            _openai_client_initialized = False
            return

        _openai_direct_client = AsyncOpenAI(
            api_key=_openai_api_key,
            base_url=_openai_base_url or None,
            organization=_openai_organization or None,
            project=_openai_project or None,
        )
        _openai_client_initialized = True
        logger.info("OpenAI direct client initialized.")
    except Exception as exc:
        logger.error("Failed to initialize OpenAI client: %s", exc, exc_info=True)
        _openai_client_initialized = False
        _openai_direct_client = None


def _parse_tool_calls_from_choice(choice: Dict[str, Any]) -> Optional[List[ParsedOpenAIToolCall]]:
    try:
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        parsed: List[ParsedOpenAIToolCall] = []
        for tc in tool_calls:
            function = (tc or {}).get("function") or {}
            fname = function.get("name") or ""
            raw_args = function.get("arguments") or ""
            parsed_args: Dict[str, Any] = {}
            parsing_error: Optional[str] = None
            if isinstance(raw_args, str):
                import json
                try:
                    parsed_args = json.loads(raw_args)
                except Exception as exc:
                    parsing_error = f"Failed to parse tool args as JSON: {exc}"
            elif isinstance(raw_args, dict):
                parsed_args = raw_args

            parsed.append(
                ParsedOpenAIToolCall(
                    tool_call_id=str(tc.get("id") or ""),
                    function_name=fname,
                    function_arguments_raw=str(raw_args),
                    function_arguments_parsed=parsed_args,
                    parsing_error=parsing_error,
                )
            )
        return parsed or None
    except Exception as exc:
        logger.error("Tool-call parsing error: %s", exc, exc_info=True)
        return None


def _build_unified_response(
    task_id: str, 
    model_id: str, 
    response_json: Dict[str, Any], 
    messages: Optional[List[Dict[str, Any]]] = None,
    tools: Optional[List[Dict[str, Any]]] = None
) -> UnifiedOpenAIResponse:
    try:
        choices = response_json.get("choices") or []
        first = choices[0] if choices else {}
        message = first.get("message") or {}
        content = message.get("content")
        parsed_tool_calls = _parse_tool_calls_from_choice(first)

        usage_raw = response_json.get("usage") or {}
        usage = None
        if usage_raw:
            try:
                # Get breakdown if messages provided
                # Include tools in the breakdown to ensure system_prompt_tokens matches prompt_tokens
                breakdown = calculate_token_breakdown(messages, model_id, tools=tools) if messages else {}
                
                usage = OpenAIUsageMetadata(
                    input_tokens=int(usage_raw.get("prompt_tokens") or 0),
                    output_tokens=int(usage_raw.get("completion_tokens") or 0),
                    total_tokens=int(usage_raw.get("total_tokens") or 0),
                    user_input_tokens=breakdown.get("user_input_tokens"),
                    system_prompt_tokens=breakdown.get("system_prompt_tokens")
                )
            except Exception:
                usage = None

        raw_wrapper = RawOpenAIChatCompletionResponse(
            text=content,
            tool_calls=None,
            usage_metadata=usage,
        )

        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=True,
            direct_message_content=content,
            tool_calls_made=parsed_tool_calls,
            raw_response=raw_wrapper,
            usage=usage,
        )
    except Exception as exc:
        logger.error("Failed to build unified response: %s", exc, exc_info=True)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(exc))


async def _invoke_openai_direct_api(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    if not _openai_direct_client:
        error_msg = "OpenAI direct client is not initialized."
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    # NOTE: About OpenAI Responses API (not used here yet)
    # We intentionally use Chat Completions streaming instead of the newer Responses API for now.
    # Rationale:
    # - Integration cost today: Our pipeline expects Chat-Completions-style chunks (strings + tool-calls + optional
    #   usage). The Responses API emits typed SSE events (e.g., response.output_text.delta, ...FunctionCallArgumentsDelta),
    #   which would require an adapter to translate events into our unified stream types and to reshape inputs
    #   (messages -> input content parts). Tool definition/choice mapping would also need adjustments.
    # - Provider parity: Other providers (OpenRouter, Anthropic via our current paths) already integrate with
    #   Chat/Completions-like semantics. Switching only OpenAI to Responses introduces a second pattern to maintain and
    #   test, increasing complexity.
    # - Stability: We just enabled OpenAI direct streaming in this module. Keeping the interface stable before
    #   introducing a second streaming model reduces breakage risk across aggregation, Redis publishing, and persistence.
    # - Feature need: If/when we need typed events, multimodal input via `input`, or structured-output streaming,
    #   we can add a Responses-API-backed path behind a feature flag with a focused adapter, without disrupting the
    #   existing flow.
    async def _iterate_openai_direct_stream() -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
        """
        Stream handler for OpenAI Chat Completions API using the official SDK.

        Yields text deltas as strings, emits tool calls as ParsedOpenAIToolCall when completed,
        and finally yields usage metadata if available. Designed to integrate into the
        existing streaming pipeline used across providers.
        """
        log_prefix = f"[{task_id}] OpenAI Direct (Stream):"
        logger.info(f"{log_prefix} Starting streaming request for model '{model_id}'")

        # Track in-progress tool calls across chunks keyed by index or id
        tool_calls_buffer: Dict[str, Dict[str, Any]] = {}

        # Optional usage accumulator (SDK may not include usage on stream). If not provided,
        # we'll estimate using tiktoken at the end to ensure billing works for models like gpt-5.
        cumulative_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

        # For fallback token estimation when usage is absent
        collected_output_text_parts: List[str] = []

        is_reasoning = _is_reasoning_model(model_id)

        # Build payload with streaming enabled
        stream_payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": True,
        }
        
        # Add temperature if NOT a reasoning model (reasoning models usually don't support it or require 1.0)
        if not is_reasoning:
            stream_payload["temperature"] = temperature

        if max_tokens is not None:
            # Reasoning models (like o1, gpt-5) use max_completion_tokens instead of max_tokens
            if is_reasoning:
                stream_payload["max_completion_tokens"] = max_tokens
            else:
                stream_payload["max_tokens"] = max_tokens
        if tools:
            mapped_tools = _map_tools_to_openai_format(tools)
            if mapped_tools:
                stream_payload["tools"] = mapped_tools
                if tool_choice:
                    if tool_choice == "required":
                        stream_payload["tool_choice"] = {"type": "function"}
                    elif tool_choice == "auto":
                        stream_payload["tool_choice"] = "auto"
                    else:
                        stream_payload["tool_choice"] = tool_choice

        try:
            # Create the streaming request
            stream_resp = await _openai_direct_client.chat.completions.create(**stream_payload)  # type: ignore

            # Calculate token breakdown from input messages (estimate)
            # Include tools in the estimate to ensure it matches the actual prompt_tokens from API
            token_breakdown = calculate_token_breakdown(messages, model_id, tools=mapped_tools if tools else None)

            # Iterate over streamed ChatCompletionChunk objects
            async for chunk in stream_resp:  # type: ignore
                try:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = getattr(choice, "delta", None)

                    # Handle text deltas
                    if delta is not None and getattr(delta, "content", None):
                        text_piece = delta.content  # type: ignore[attr-defined]
                        if text_piece:
                            text_str = str(text_piece)
                            collected_output_text_parts.append(text_str)
                            yield text_str

                    # Handle tool call deltas
                    if delta is not None and getattr(delta, "tool_calls", None):
                        for tc_delta in delta.tool_calls:  # type: ignore[attr-defined]
                            # Prefer stable id when present; otherwise fall back to index
                            tc_id = getattr(tc_delta, "id", None) or str(getattr(tc_delta, "index", 0))
                            if tc_id not in tool_calls_buffer:
                                tool_calls_buffer[tc_id] = {
                                    "id": tc_id,
                                    "function": {"name": "", "arguments": ""},
                                }

                            # Update function name and arguments incrementally
                            function_obj = getattr(tc_delta, "function", None)
                            if function_obj is not None:
                                fn_name = getattr(function_obj, "name", None)
                                if fn_name:
                                    tool_calls_buffer[tc_id]["function"]["name"] = fn_name

                                fn_args_part = getattr(function_obj, "arguments", None)
                                if fn_args_part:
                                    existing = tool_calls_buffer[tc_id]["function"].get("arguments", "")
                                    tool_calls_buffer[tc_id]["function"]["arguments"] = existing + str(fn_args_part)

                    # If the current choice finished due to tool calls, emit completed calls
                    finish_reason = getattr(choice, "finish_reason", None)
                    if finish_reason == "tool_calls":
                        for finished_id, finished_tc in list(tool_calls_buffer.items()):
                            function_name = finished_tc["function"]["name"]
                            arguments_raw = finished_tc["function"]["arguments"]

                            # Parse arguments JSON safely
                            parsed_args: Dict[str, Any] = {}
                            parsing_error: Optional[str] = None
                            try:
                                import json as _json
                                parsed_args = _json.loads(arguments_raw) if arguments_raw else {}
                            except Exception as parse_exc:  # pragma: no cover - defensive
                                parsing_error = f"Failed to parse tool args: {parse_exc}"
                                logger.error(f"{log_prefix} {parsing_error}")

                            yield ParsedOpenAIToolCall(
                                tool_call_id=str(finished_id),
                                function_name=function_name or "",
                                function_arguments_raw=str(arguments_raw or ""),
                                function_arguments_parsed=parsed_args,
                                parsing_error=parsing_error,
                            )

                        tool_calls_buffer.clear()

                    # Capture usage if present on chunk (some SDK versions include it on final chunk)
                    usage_obj = getattr(chunk, "usage", None)
                    if usage_obj is not None:
                        # Best-effort extraction; attributes may vary across SDK versions
                        try:
                            prompt_tokens = int(getattr(usage_obj, "prompt_tokens", 0))
                            completion_tokens = int(getattr(usage_obj, "completion_tokens", 0))
                            total_tokens = int(getattr(usage_obj, "total_tokens", prompt_tokens + completion_tokens))
                            cumulative_usage["input_tokens"] = prompt_tokens
                            cumulative_usage["output_tokens"] = completion_tokens
                            cumulative_usage["total_tokens"] = total_tokens
                        except Exception:  # pragma: no cover - defensive
                            pass

                except Exception as chunk_exc:  # pragma: no cover - defensive
                    logger.error(f"{log_prefix} Error processing stream chunk: {chunk_exc}", exc_info=True)
                    continue

            # After stream completion, emit usage if we have it; otherwise estimate using tiktoken
            if not any(v > 0 for v in cumulative_usage.values()):
                try:
                    import tiktoken  # type: ignore
                    # Heuristic: use GPT-4o encoding if model-specific encoding unavailable; this is a best-effort estimate.
                    encoding = None
                    try:
                        encoding = tiktoken.encoding_for_model(model_id)
                    except Exception:
                        encoding = tiktoken.get_encoding("o200k_base")

                    # Estimate input tokens from messages
                    def _concat_messages_for_estimation(msgs: List[Dict[str, Any]]) -> str:
                        try:
                            return "\n".join([f"{m.get('role','')}:{m.get('content','')}" for m in msgs])
                        except Exception:
                            return ""

                    input_text_joined = _concat_messages_for_estimation(messages)
                    output_text_joined = "".join(collected_output_text_parts)
                    input_tokens_est = len(encoding.encode(input_text_joined)) if input_text_joined else 0
                    output_tokens_est = len(encoding.encode(output_text_joined)) if output_text_joined else 0
                    total_tokens_est = input_tokens_est + output_tokens_est

                    cumulative_usage["input_tokens"] = input_tokens_est
                    cumulative_usage["output_tokens"] = output_tokens_est
                    cumulative_usage["total_tokens"] = total_tokens_est

                    logger.info(
                        "[%s] OpenAI Direct (Stream): Usage not provided by API; using token estimates input=%d, output=%d, total=%d",
                        task_id,
                        input_tokens_est,
                        output_tokens_est,
                        total_tokens_est,
                    )
                except Exception as est_exc:
                    logger.error(
                        "[%s] OpenAI Direct (Stream): Failed to estimate tokens via tiktoken: %s",
                        task_id,
                        est_exc,
                        exc_info=True,
                    )

            # Emit usage (real or estimated)
            yield OpenAIUsageMetadata(
                input_tokens=cumulative_usage["input_tokens"],
                output_tokens=cumulative_usage["output_tokens"],
                total_tokens=cumulative_usage["total_tokens"],
                user_input_tokens=token_breakdown.get("user_input_tokens"),
                system_prompt_tokens=token_breakdown.get("system_prompt_tokens")
            )

            logger.info(f"{log_prefix} Stream completed for model '{model_id}'")

        except Exception as exc:
            error_msg_local = f"OpenAI streaming error: {exc}"
            logger.error(f"{log_prefix} {error_msg_local}", exc_info=True)
            # Yield an error string to propagate to consumers without crashing the pipeline
            yield f"[ERROR: {error_msg_local}]"

    if stream:
        # Return the async generator for the calling pipeline to iterate over
        return _iterate_openai_direct_stream()

    is_reasoning = _is_reasoning_model(model_id)

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
    }
    
    # Add temperature if NOT a reasoning model
    if not is_reasoning:
        payload["temperature"] = temperature
        
    if max_tokens is not None:
        # Reasoning models (like o1, gpt-5) use max_completion_tokens instead of max_tokens
        if is_reasoning:
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = _map_tools_to_openai_format(tools)
        if tool_choice:
            if tool_choice == "required":
                payload["tool_choice"] = {"type": "function"}
            elif tool_choice == "auto":
                payload["tool_choice"] = "auto"
            else:
                payload["tool_choice"] = tool_choice

    logger.debug("[%s] OpenAI Direct payload (sanitized): %s", task_id, {k: v for k, v in payload.items() if k != "messages"})

    try:
        resp = await _openai_direct_client.chat.completions.create(**payload)  # type: ignore
        response_json: Dict[str, Any] = resp.model_dump() if hasattr(resp, "model_dump") else resp  # type: ignore
        logger.info("[%s] OpenAI Direct API success for model '%s'", task_id, model_id)
        # Pass mapped tools to ensure correct token breakdown calculation
        return _build_unified_response(task_id, model_id, response_json, messages=messages, tools=payload.get("tools"))
    except Exception as exc:
        logger.error("[%s] OpenAI Direct API error: %s", task_id, exc, exc_info=True)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(exc))


async def invoke_openai_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, Any]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    if secrets_manager and not _openai_client_initialized:
        await initialize_openai_client(secrets_manager)

    server_choice = _select_server_for_model(model_id)
    logger.info("[%s] OpenAI Client: server=%s, stream=%s", task_id, server_choice, stream)

    if server_choice == "openrouter":
        return await invoke_openrouter_chat_completions(
            task_id=task_id,
            model_id=model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
        )

    if server_choice == "azure":
        error_msg = "Azure OpenAI selected by config, but not yet implemented in this client."
        logger.error("[%s] %s", task_id, error_msg)
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    return await _invoke_openai_direct_api(
        task_id=task_id,
        model_id=model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        stream=stream,
    )
