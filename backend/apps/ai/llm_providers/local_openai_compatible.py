"""
Local OpenAI-compatible LLM provider adapters.

Supports self-hosted Ollama, LM Studio, and custom OpenAI-compatible servers
configured through provider overlay YAML files. The model creator remains the
normal provider namespace (for example alibaba/qwen3-8b-local), while the
server entry routes the request to a local runtime such as ollama or lm_studio.
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Union
import logging

from backend.core.api.app.utils.config_manager import config_manager
from backend.core.api.app.utils.secrets_manager import SecretsManager

from .openai_shared import (
    OpenAIUsageMetadata,
    ParsedOpenAIToolCall,
    RawOpenAIChatCompletionResponse,
    UnifiedOpenAIResponse,
    _map_tools_to_openai_format,
    calculate_token_breakdown,
)

try:
    from openai import AsyncOpenAI  # type: ignore
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore


logger = logging.getLogger(__name__)

LOCAL_SERVER_DEFAULTS = {
    "ollama": {
        "name": "Ollama",
        "base_url": "http://host.docker.internal:11434/v1",
        "api_key": "ollama",
    },
    "lm_studio": {
        "name": "LM Studio",
        "base_url": "http://host.docker.internal:1234/v1",
        "api_key": "lm-studio",
    },
    "custom_openai_compatible": {
        "name": "Custom OpenAI-compatible API",
        "base_url": "",
        "api_key": "local",
    },
}


def _find_server_config(server_id: str, model_id: str) -> Dict[str, Any]:
    """Find the local server config for a server/model pair."""
    for provider_config in config_manager.get_provider_configs().values():
        for model in provider_config.get("models", []):
            if not isinstance(model, dict):
                continue
            for server in model.get("servers", []):
                if not isinstance(server, dict):
                    continue
                if server.get("id") == server_id and server.get("model_id") == model_id:
                    return server
    return {}


def _resolve_server_settings(server_id: str, model_id: str) -> Dict[str, Any]:
    defaults = LOCAL_SERVER_DEFAULTS.get(server_id, {})
    server = _find_server_config(server_id, model_id)
    base_url = str(server.get("base_url") or defaults.get("base_url") or "").rstrip("/")
    if not base_url:
        raise ValueError(f"Local server '{server_id}' for model '{model_id}' has no base_url configured.")

    api_key = server.get("api_key") or defaults.get("api_key") or "local"
    return {
        "base_url": base_url,
        "api_key": str(api_key),
        "supports_tools": bool(server.get("supports_tools", False)),
        "server_name": server.get("name") or defaults.get("name") or server_id,
    }


def _parse_tool_calls_from_choice(choice: Any) -> Optional[List[ParsedOpenAIToolCall]]:
    message = getattr(choice, "message", None)
    tool_calls = getattr(message, "tool_calls", None) if message is not None else None
    if not tool_calls:
        return None

    parsed: List[ParsedOpenAIToolCall] = []
    for tc in tool_calls:
        function = getattr(tc, "function", None)
        function_name = getattr(function, "name", "") if function is not None else ""
        arguments_raw = getattr(function, "arguments", "") if function is not None else ""
        arguments_parsed: Dict[str, Any] = {}
        parsing_error: Optional[str] = None
        if isinstance(arguments_raw, str) and arguments_raw:
            try:
                import json

                arguments_parsed = json.loads(arguments_raw)
            except Exception as exc:
                parsing_error = f"Failed to parse tool args as JSON: {exc}"

        parsed.append(
            ParsedOpenAIToolCall(
                tool_call_id=str(getattr(tc, "id", "")),
                function_name=function_name,
                function_arguments_raw=str(arguments_raw or ""),
                function_arguments_parsed=arguments_parsed,
                parsing_error=parsing_error,
            )
        )
    return parsed or None


def _estimate_output_tokens(text: str, model_id: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore

        try:
            encoding = tiktoken.encoding_for_model(model_id)
        except Exception:
            encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


async def _invoke_local_openai_compatible_chat_completions(
    *,
    server_id: str,
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
    del secrets_manager
    if AsyncOpenAI is None:
        error_msg = "OpenAI SDK missing; install 'openai'."
        if stream:
            raise ValueError(error_msg)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    settings = _resolve_server_settings(server_id, model_id)
    client = AsyncOpenAI(api_key=settings["api_key"], base_url=settings["base_url"])
    mapped_tools = _map_tools_to_openai_format(tools) if tools and settings["supports_tools"] else None
    token_breakdown = calculate_token_breakdown(messages, model_id, tools=mapped_tools)

    payload: Dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if mapped_tools:
        payload["tools"] = mapped_tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    logger.info(
        "[%s] Local OpenAI-compatible client: server=%s base_url=%s model=%s stream=%s tools=%s",
        task_id,
        server_id,
        settings["base_url"],
        model_id,
        stream,
        bool(mapped_tools),
    )

    async def _iterate_stream() -> AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]:
        collected_text: List[str] = []
        tool_calls_buffer: Dict[str, Dict[str, Any]] = {}
        usage_tokens = {"input": 0, "output": 0, "total": 0}
        try:
            stream_resp = await client.chat.completions.create(**payload, stream=True)  # type: ignore[arg-type]
            async for chunk in stream_resp:  # type: ignore[union-attr]
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue

                choice = choices[0]
                delta = getattr(choice, "delta", None)
                if delta is not None and getattr(delta, "content", None):
                    text_piece = str(delta.content)
                    collected_text.append(text_piece)
                    yield text_piece

                if delta is not None and getattr(delta, "tool_calls", None):
                    for tc_delta in delta.tool_calls:
                        tc_id = getattr(tc_delta, "id", None) or str(getattr(tc_delta, "index", 0))
                        if tc_id not in tool_calls_buffer:
                            tool_calls_buffer[tc_id] = {"id": tc_id, "function": {"name": "", "arguments": ""}}
                        function_obj = getattr(tc_delta, "function", None)
                        if function_obj is not None:
                            fn_name = getattr(function_obj, "name", None)
                            if fn_name:
                                tool_calls_buffer[tc_id]["function"]["name"] = fn_name
                            fn_args_part = getattr(function_obj, "arguments", None)
                            if fn_args_part:
                                current = tool_calls_buffer[tc_id]["function"].get("arguments", "")
                                tool_calls_buffer[tc_id]["function"]["arguments"] = current + str(fn_args_part)

                if getattr(choice, "finish_reason", None) == "tool_calls":
                    for finished_id, finished_tc in list(tool_calls_buffer.items()):
                        args_raw = finished_tc["function"].get("arguments", "")
                        parsed_args: Dict[str, Any] = {}
                        parsing_error: Optional[str] = None
                        try:
                            import json

                            parsed_args = json.loads(args_raw) if args_raw else {}
                        except Exception as exc:
                            parsing_error = f"Failed to parse tool args: {exc}"
                        yield ParsedOpenAIToolCall(
                            tool_call_id=str(finished_id),
                            function_name=finished_tc["function"].get("name", ""),
                            function_arguments_raw=str(args_raw or ""),
                            function_arguments_parsed=parsed_args,
                            parsing_error=parsing_error,
                        )
                    tool_calls_buffer.clear()

                usage_obj = getattr(chunk, "usage", None)
                if usage_obj is not None:
                    usage_tokens["input"] = int(getattr(usage_obj, "prompt_tokens", 0) or 0)
                    usage_tokens["output"] = int(getattr(usage_obj, "completion_tokens", 0) or 0)
                    usage_tokens["total"] = int(getattr(usage_obj, "total_tokens", 0) or 0)

            if not any(usage_tokens.values()):
                output_tokens = _estimate_output_tokens("".join(collected_text), model_id)
                input_tokens = int(token_breakdown.get("user_input_tokens", 0) or 0) + int(
                    token_breakdown.get("system_prompt_tokens", 0) or 0
                )
                usage_tokens.update({"input": input_tokens, "output": output_tokens, "total": input_tokens + output_tokens})

            yield OpenAIUsageMetadata(
                input_tokens=usage_tokens["input"],
                output_tokens=usage_tokens["output"],
                total_tokens=usage_tokens["total"],
                user_input_tokens=token_breakdown.get("user_input_tokens"),
                system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
            )
        except Exception as exc:
            logger.error("[%s] Local OpenAI-compatible streaming error: %s", task_id, exc, exc_info=True)
            yield f"[ERROR: Local OpenAI-compatible streaming error: {exc}]"

    if stream:
        return _iterate_stream()

    try:
        response = await client.chat.completions.create(**payload)  # type: ignore[arg-type]
        choices = getattr(response, "choices", None) or []
        choice = choices[0] if choices else None
        message = getattr(choice, "message", None) if choice is not None else None
        content = getattr(message, "content", None) if message is not None else None
        usage_obj = getattr(response, "usage", None)
        output_tokens = int(getattr(usage_obj, "completion_tokens", 0) or 0) if usage_obj is not None else _estimate_output_tokens(str(content or ""), model_id)
        input_tokens = int(getattr(usage_obj, "prompt_tokens", 0) or 0) if usage_obj is not None else int(token_breakdown.get("user_input_tokens", 0) or 0) + int(token_breakdown.get("system_prompt_tokens", 0) or 0)
        usage = OpenAIUsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=int(getattr(usage_obj, "total_tokens", input_tokens + output_tokens) or input_tokens + output_tokens) if usage_obj is not None else input_tokens + output_tokens,
            user_input_tokens=token_breakdown.get("user_input_tokens"),
            system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
        )
        return UnifiedOpenAIResponse(
            task_id=task_id,
            model_id=model_id,
            success=True,
            direct_message_content=content,
            tool_calls_made=_parse_tool_calls_from_choice(choice) if choice is not None else None,
            raw_response=RawOpenAIChatCompletionResponse(text=content, usage_metadata=usage),
            usage=usage,
        )
    except Exception as exc:
        logger.error("[%s] Local OpenAI-compatible API error: %s", task_id, exc, exc_info=True)
        return UnifiedOpenAIResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(exc))


async def invoke_ollama_chat_completions(**kwargs: Any) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    return await _invoke_local_openai_compatible_chat_completions(server_id="ollama", **kwargs)


async def invoke_lm_studio_chat_completions(**kwargs: Any) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    return await _invoke_local_openai_compatible_chat_completions(server_id="lm_studio", **kwargs)


async def invoke_custom_openai_compatible_chat_completions(**kwargs: Any) -> Union[UnifiedOpenAIResponse, AsyncIterator[Union[str, ParsedOpenAIToolCall, OpenAIUsageMetadata]]]:
    return await _invoke_local_openai_compatible_chat_completions(server_id="custom_openai_compatible", **kwargs)
