# backend/core/api/app/routes/openai_compat.py
#
# Canonical OpenAI-compatible API routes for external SDKs and agentic tools.
# These endpoints intentionally keep OpenAI client tools separate from
# OpenMates app skills: `/v1/chat/completions` may return client tool calls,
# but it never executes OpenMates app skills. Native OpenMates skill execution
# stays on `/v1/apps/ai/skills/ask` and other app-skill routes.

import json
import logging
import time
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.apps.ai.llm_providers.openai_shared import OpenAIUsageMetadata
from backend.core.api.app.routes.apps_api import (
    charge_credits_via_internal_api,
    check_provider_api_key_available,
    get_directus_service,
    get_session_or_api_key_info,
    require_api_key_budget_for_charge,
)
from backend.core.api.app.utils.config_manager import config_manager
from backend.shared.python_utils.billing_utils import calculate_total_credits

logger = logging.getLogger(__name__)

router = APIRouter(tags=["OpenAI Compatibility"])

CHAT_APP_SKILL_ID = "ai.ask"
OPENAI_MODEL_OBJECT = "model"
OPENAI_LIST_OBJECT = "list"
OPENAI_CHAT_COMPLETION_OBJECT = "chat.completion"
OPENAI_CHAT_COMPLETION_CHUNK_OBJECT = "chat.completion.chunk"
SUPPORTED_TOOL_TYPE = "function"
OPENCODE_PROVIDER_PREFIX = "openmates/"


def _openai_error(
    *,
    status_code: int,
    message: str,
    error_type: str = "invalid_request_error",
    param: Optional[str] = None,
    code: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
    )


def _remove_none(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_none(item) for item in value]
    if isinstance(value, dict):
        return {key: _remove_none(item) for key, item in value.items() if item is not None}
    return value


def _created_timestamp(model_config: Dict[str, Any]) -> int:
    release_date = model_config.get("release_date")
    if isinstance(release_date, str) and release_date:
        try:
            return int(datetime.fromisoformat(release_date).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            logger.debug("Invalid model release_date for OpenAI model object: %s", release_date)
    return 0


def _get_config_manager(request: Request) -> Any:
    return getattr(request.app.state, "config_manager", config_manager)


def _get_global_skill_registry() -> Any:
    from backend.core.api.app.services.skill_registry import get_global_registry

    return get_global_registry()


def _get_secrets_manager(request: Request) -> Any:
    return getattr(request.app.state, "secrets_manager", None)


def _is_chat_model(model_config: Dict[str, Any]) -> bool:
    output_types = model_config.get("output_types") or []
    return model_config.get("for_app_skill") == CHAT_APP_SKILL_ID and "text" in output_types


def _model_object(provider_id: str, model_config: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(model_config["id"])
    return {
        "id": f"{provider_id}/{model_id}",
        "object": OPENAI_MODEL_OBJECT,
        "created": _created_timestamp(model_config),
        "owned_by": provider_id,
    }


def _model_server_ids(provider_id: str, model_config: Dict[str, Any]) -> set[str]:
    server_ids = {provider_id}
    default_server = model_config.get("default_server")
    if isinstance(default_server, str) and default_server.strip():
        server_ids.add(default_server.strip())
    for server in model_config.get("servers") or []:
        if isinstance(server, dict) and isinstance(server.get("id"), str) and server["id"].strip():
            server_ids.add(server["id"].strip())
    return server_ids


async def _server_or_provider_available(config: Any, provider_id: str, secrets_manager: Any) -> bool:
    provider_config = config.get_provider_config(provider_id) if hasattr(config, "get_provider_config") else None
    if not provider_config and hasattr(config, "get_provider_configs"):
        provider_config = (config.get_provider_configs() or {}).get(provider_id)
    if isinstance(provider_config, dict) and provider_config.get("no_api_key") is True:
        return True
    if secrets_manager is None:
        return True
    return await check_provider_api_key_available(provider_id, secrets_manager, config)


async def _available_model_objects(config: Any, secrets_manager: Any = None) -> List[Dict[str, Any]]:
    provider_configs = config.get_provider_configs() if config else {}
    models: List[Dict[str, Any]] = []
    for provider_id, provider_config in provider_configs.items():
        if not isinstance(provider_config, dict):
            continue
        canonical_provider_id = str(provider_config.get("provider_id") or provider_id)
        for model_config in provider_config.get("models", []):
            if not isinstance(model_config, dict) or not model_config.get("id"):
                continue
            if _is_chat_model(model_config) and any(
                [await _server_or_provider_available(config, server_id, secrets_manager) for server_id in _model_server_ids(canonical_provider_id, model_config)]
            ):
                models.append(_model_object(canonical_provider_id, model_config))
    return sorted(models, key=lambda model: model["id"])


async def _find_model(config: Any, model_id: str, secrets_manager: Any = None) -> Optional[Dict[str, Any]]:
    for model in await _available_model_objects(config, secrets_manager):
        if model["id"] == model_id:
            return model
    return None


def _normalize_model_id(model_id: Any) -> Any:
    if isinstance(model_id, str) and model_id.startswith(OPENCODE_PROVIDER_PREFIX):
        return model_id[len(OPENCODE_PROVIDER_PREFIX):]
    return model_id


def _model_config_for_id(config: Any, model_id: str) -> Optional[Dict[str, Any]]:
    if "/" not in model_id:
        return None
    provider_id, raw_model_id = model_id.split("/", 1)
    provider_config = config.get_provider_config(provider_id) if hasattr(config, "get_provider_config") else None
    if not provider_config and hasattr(config, "get_provider_configs"):
        provider_config = (config.get_provider_configs() or {}).get(provider_id)
    if not isinstance(provider_config, dict):
        return None
    for model_config in provider_config.get("models", []):
        if isinstance(model_config, dict) and model_config.get("id") == raw_model_id:
            return model_config
    return None


def _validate_messages(body: Dict[str, Any]) -> Optional[JSONResponse]:
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _openai_error(
            status_code=400,
            message="'messages' is required and must be a non-empty array.",
            param="messages",
            code="invalid_type",
        )
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            return _openai_error(
                status_code=400,
                message=f"'messages[{index}]' must be an object.",
                param="messages",
                code="invalid_type",
            )
        if not isinstance(message.get("role"), str):
            return _openai_error(
                status_code=400,
                message=f"'messages[{index}].role' is required.",
                param="messages",
                code="missing_required_parameter",
            )
        if "content" not in message and "tool_calls" not in message:
            return _openai_error(
                status_code=400,
                message=f"'messages[{index}].content' is required unless tool_calls are present.",
                param="messages",
                code="missing_required_parameter",
            )
    return None


def _validate_tools(body: Dict[str, Any]) -> Optional[JSONResponse]:
    tools = body.get("tools")
    if tools is None:
        return None
    if not isinstance(tools, list):
        return _openai_error(
            status_code=400,
            message="'tools' must be an array.",
            param="tools",
            code="invalid_type",
        )
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            return _openai_error(
                status_code=400,
                message=f"'tools[{index}]' must be an object.",
                param="tools",
                code="invalid_type",
            )
        if tool.get("type") != SUPPORTED_TOOL_TYPE:
            return _openai_error(
                status_code=400,
                message="Only standard OpenAI function tools are supported in this endpoint.",
                param="tools",
                code="unsupported_tool_type",
            )
        function = tool.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            return _openai_error(
                status_code=400,
                message="Function tools require function.name.",
                param="tools",
                code="missing_required_parameter",
            )
    return None


def _validate_tool_choice(body: Dict[str, Any]) -> Optional[JSONResponse]:
    if "tool_choice" not in body:
        return None
    tool_choice = body.get("tool_choice")
    if tool_choice in ("none", "auto", "required"):
        return None
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    tool_names = {
        tool.get("function", {}).get("name")
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }
    if (
        isinstance(tool_choice, dict)
        and tool_choice.get("type") == "function"
        and isinstance(tool_choice.get("function"), dict)
        and isinstance(tool_choice["function"].get("name"), str)
        and tool_choice["function"]["name"] in tool_names
    ):
        return None
    return _openai_error(
        status_code=400,
        message="'tool_choice' must be 'none', 'auto', 'required', or a named function tool choice.",
        param="tool_choice",
        code="invalid_value",
    )


async def _validate_chat_request(config: Any, body: Dict[str, Any], secrets_manager: Any = None) -> Optional[JSONResponse]:
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        return _openai_error(
            status_code=400,
            message="'model' is required.",
            param="model",
            code="missing_required_parameter",
        )
    if not await _find_model(config, model, secrets_manager):
        return _openai_error(
            status_code=404,
            message=f"Model '{model}' is not available.",
            param="model",
            code="model_not_found",
        )
    return _validate_messages(body) or _validate_tools(body) or _validate_tool_choice(body)


def _is_client_tool_request(body: Dict[str, Any]) -> bool:
    tools = body.get("tools")
    if isinstance(tools, list) and len(tools) > 0:
        return True
    return any(isinstance(message, dict) and message.get("role") == "tool" for message in body.get("messages", []))


def _tool_call_to_openai(tool_call: Any) -> Dict[str, Any]:
    raw_args = getattr(tool_call, "function_arguments_raw", "")
    if not isinstance(raw_args, str):
        raw_args = json.dumps(raw_args)
    return {
        "id": getattr(tool_call, "tool_call_id", None) or f"call_{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": getattr(tool_call, "function_name", ""),
            "arguments": raw_args,
        },
    }


def _usage_to_openai(usage: Optional[OpenAIUsageMetadata]) -> Optional[Dict[str, int]]:
    if not usage:
        return None
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _credits_for_usage(config: Any, model_id: str, usage: Optional[OpenAIUsageMetadata]) -> int:
    if not usage:
        return 1
    model_config = _model_config_for_id(config, model_id) or {}
    pricing_config = model_config.get("pricing") or {}
    credits = calculate_total_credits(
        pricing_config=pricing_config,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    return max(credits, 1)


async def _charge_client_tool_usage(
    *,
    request_body: Dict[str, Any],
    user_info: Dict[str, Any],
    usage: Optional[OpenAIUsageMetadata],
    already_charged_credits: int = 0,
) -> int:
    config = request_body.get("_openmates_config_manager") or config_manager
    credits = _credits_for_usage(config, request_body["model"], usage)
    credits_to_charge = max(credits - already_charged_credits, 0)
    if credits_to_charge <= 0:
        return credits
    directus_service = request_body.get("_openmates_directus_service")
    if directus_service:
        await require_api_key_budget_for_charge(
            directus_service,
            user_info=user_info,
            requested_credits=credits_to_charge,
        )
    user_id = user_info["user_id"]
    provider_id = request_body["model"].split("/", 1)[0] if "/" in request_body["model"] else None
    usage_details = {
        "api_key_name": user_info.get("api_key_encrypted_name"),
        "external_request": True,
        "openai_compatible_endpoint": True,
        "model_used": request_body["model"],
        "server_provider": provider_id,
        "server_region": None,
    }
    if usage:
        usage_details["input_tokens"] = usage.input_tokens
        usage_details["output_tokens"] = usage.output_tokens
    await charge_credits_via_internal_api(
        user_id=user_id,
        user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
        credits=credits_to_charge,
        app_id="ai",
        skill_id="ask",
        usage_details=usage_details,
        api_key_hash=user_info.get("api_key_hash"),
        device_hash=user_info.get("device_hash"),
    )
    return credits


async def _dispatch_ai_ask_chat_completion(
    *,
    request_body: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Any:
    request_payload = dict(request_body)
    request_payload["apps_enabled"] = False
    request_payload["allowed_apps"] = []
    request_payload["_user_id"] = user_info["user_id"]
    request_payload["_api_key_name"] = user_info.get("api_key_encrypted_name", "")
    request_payload["_api_key_hash"] = user_info.get("api_key_hash")
    request_payload["_device_hash"] = user_info.get("device_hash")
    request_payload["_external_request"] = True
    if user_info.get("vault_key_id"):
        request_payload["_user_vault_key_id"] = user_info["vault_key_id"]

    result = await _get_global_skill_registry().dispatch_skill("ai", "ask", request_payload)
    if request_body.get("stream"):
        return result
    return _remove_none(result) if isinstance(result, dict) else result


async def _direct_client_tool_events(
    request_body: Dict[str, Any],
    request_id: str,
) -> AsyncIterator[Any]:
    from backend.apps.ai.utils.llm_utils import call_main_llm_stream

    secrets_manager = request_body.get("_openmates_secrets_manager")
    async for item in call_main_llm_stream(
        task_id=request_id,
        model_id=request_body["model"],
        system_prompt="",
        message_history=request_body["messages"],
        temperature=float(request_body.get("temperature") if request_body.get("temperature") is not None else 0.7),
        secrets_manager=secrets_manager,
        tools=request_body.get("tools"),
        tool_choice=request_body.get("tool_choice"),
    ):
        yield item


async def _stream_client_tool_chat_completion(
    request_body: Dict[str, Any],
    user_info: Dict[str, Any],
    request_id: str,
    prepaid_credits: int,
) -> AsyncIterator[str]:
    created = int(time.time())
    usage: Optional[OpenAIUsageMetadata] = None
    async for item in _direct_client_tool_events(request_body, request_id):
        if isinstance(item, str):
            chunk = {
                "id": request_id,
                "object": OPENAI_CHAT_COMPLETION_CHUNK_OBJECT,
                "created": created,
                "model": request_body["model"],
                "choices": [{"index": 0, "delta": {"content": item}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        elif isinstance(item, OpenAIUsageMetadata):
            usage = item
        elif hasattr(item, "function_name"):
            chunk = {
                "id": request_id,
                "object": OPENAI_CHAT_COMPLETION_CHUNK_OBJECT,
                "created": created,
                "model": request_body["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [_tool_call_to_openai(item)]},
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
    await _charge_client_tool_usage(
        request_body=request_body,
        user_info=user_info,
        usage=usage,
        already_charged_credits=prepaid_credits,
    )
    yield "data: [DONE]\n\n"


async def _dispatch_client_tool_chat_completion(
    *,
    request_body: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Any:
    request_id = f"chatcmpl-{uuid.uuid4().hex}"
    prepaid_credits = await _charge_client_tool_usage(
        request_body=request_body,
        user_info=user_info,
        usage=None,
    )
    if request_body.get("stream"):
        return StreamingResponse(
            _stream_client_tool_chat_completion(request_body, user_info, request_id, prepaid_credits),
            media_type="text/event-stream",
        )

    content_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    usage: Optional[OpenAIUsageMetadata] = None
    async for item in _direct_client_tool_events(request_body, request_id):
        if isinstance(item, str):
            content_parts.append(item)
        elif hasattr(item, "function_name"):
            tool_calls.append(_tool_call_to_openai(item))
        elif isinstance(item, OpenAIUsageMetadata):
            usage = item

    credits_charged = await _charge_client_tool_usage(
        request_body=request_body,
        user_info=user_info,
        usage=usage,
        already_charged_credits=prepaid_credits,
    )

    message: Dict[str, Any] = {"role": "assistant", "content": "".join(content_parts) or None}
    finish_reason = "stop"
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"

    response = {
        "id": request_id,
        "object": OPENAI_CHAT_COMPLETION_OBJECT,
        "created": int(time.time()),
        "model": request_body["model"],
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _usage_to_openai(usage),
    }
    if isinstance(response.get("usage"), dict):
        response["usage"]["total_credits"] = credits_charged
    return _remove_none(response)


@router.get("/v1/models")
async def list_models(
    request: Request,
    user_info: Dict[str, Any] = Depends(get_session_or_api_key_info),
) -> Dict[str, Any]:
    del user_info
    return {"object": OPENAI_LIST_OBJECT, "data": await _available_model_objects(_get_config_manager(request), _get_secrets_manager(request))}


@router.get("/v1/models/{model_id:path}")
async def get_model(
    model_id: str,
    request: Request,
    user_info: Dict[str, Any] = Depends(get_session_or_api_key_info),
) -> Any:
    del user_info
    canonical_model_id = _normalize_model_id(model_id)
    model = await _find_model(_get_config_manager(request), canonical_model_id, _get_secrets_manager(request))
    if not model:
        return _openai_error(
            status_code=404,
            message=f"Model '{model_id}' is not available.",
            param="model",
            code="model_not_found",
        )
    return model


@router.post("/v1/chat/completions")
async def create_chat_completion(
    request: Request,
    user_info: Dict[str, Any] = Depends(get_session_or_api_key_info),
    directus_service: Any = Depends(get_directus_service),
) -> Any:
    try:
        body = await request.json()
    except ValueError:
        return _openai_error(
            status_code=400,
            message="Request body must be valid JSON.",
            code="invalid_json",
        )
    if not isinstance(body, dict):
        return _openai_error(
            status_code=400,
            message="Request body must be a JSON object.",
            code="invalid_type",
        )
    body = dict(body)
    body["model"] = _normalize_model_id(body.get("model"))

    validation_error = await _validate_chat_request(_get_config_manager(request), body, _get_secrets_manager(request))
    if validation_error:
        return validation_error

    if _is_client_tool_request(body):
        dispatch_body = dict(body)
        dispatch_body["_openmates_secrets_manager"] = getattr(request.app.state, "secrets_manager", None)
        dispatch_body["_openmates_directus_service"] = directus_service
        dispatch_body["_openmates_config_manager"] = _get_config_manager(request)
        return await _dispatch_client_tool_chat_completion(request_body=dispatch_body, user_info=user_info)
    return await _dispatch_ai_ask_chat_completion(request_body=body, user_info=user_info)
