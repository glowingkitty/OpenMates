"""Bounded synthetic provider usage probe. Run inside app-ai-worker.

Only numeric usage fields and error classes are written. No prompts, responses,
credentials, or request identifiers are persisted.
"""

import asyncio
import json
import sys
from typing import Any

from backend.core.api.app.utils.secrets_manager import SecretsManager


PREFIX = "OpenMates synthetic cache usage test. Numbers: one two three four five six. " * 310
QUESTION = "Reply with OK."
FIELDS = {
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens",
    "completion_tokens", "prompt_token_count", "candidates_token_count",
    "total_token_count", "cached_content_token_count", "cached_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
    "cacheReadInputTokens", "cacheWriteInputTokens", "inputTokens",
    "outputTokens", "totalTokens", "ephemeral_5m_input_tokens",
    "ephemeral_1h_input_tokens", "thoughts_token_count",
}


def numeric(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, dict):
        return {k: v for k, raw in value.items() if (v := numeric(raw)) is not None and (k in FIELDS or isinstance(v, dict))}
    if isinstance(value, list):
        rows = [v for raw in value if (v := numeric(raw)) is not None]
        return rows or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def capture(result: dict, name: str, usage: Any) -> None:
    result[name] = {"status": "ok", "usage": numeric(usage)}


def error(result: dict, name: str, exc: Exception) -> None:
    result[name] = {"status": "error", "error_type": type(exc).__name__}
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        result[name]["status_code"] = status


async def run_extras() -> dict:
    """Probe native explicit controls; always delete created Google caches."""
    result: dict[str, Any] = {}
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        from openai import OpenAI
        key = await secrets.get_secret("kv/data/providers/openai", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        client = OpenAI(api_key=key)
        try:
            response = client.responses.create(
                model="gpt-6.1-sol", input=QUESTION, reasoning={"effort": "low"},
                max_output_tokens=24, store=False,
                extra_body={"prompt_cache_options": {"mode": "explicit"}},
            )
            capture(result, "openai_explicit_control", response.usage)
        except Exception as exc:
            error(result, "openai_explicit_control", exc)
    except Exception as exc:
        error(result, "openai_explicit_setup", exc)

    try:
        from google import genai
        from google.genai import types
        key = await secrets.get_secret("kv/data/providers/google_ai_studio", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        client = genai.Client(api_key=key)
        await probe_google_cache(result, "google_studio_explicit", client, types)
    except Exception as exc:
        error(result, "google_studio_explicit_setup", exc)

    try:
        from google import genai
        from google.genai import types
        from google.oauth2 import service_account
        sa = await secrets.get_secret("kv/data/providers/google", "service_account_json")
        project = await secrets.get_secret("kv/data/providers/google", "project_id")
        location = await secrets.get_secret("kv/data/providers/google", "location") or "global"
        if not sa or not project:
            raise RuntimeError("missing credential")
        creds = service_account.Credentials.from_service_account_info(json.loads(sa), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        await probe_google_cache(result, "google_vertex_explicit", client, types)
    except Exception as exc:
        error(result, "google_vertex_explicit_setup", exc)

    await secrets.aclose()
    return result


async def run_streams() -> dict:
    """Capture terminal usage only; never persist streamed text or tool data."""
    result: dict[str, Any] = {}
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        from openai import OpenAI
        key = await secrets.get_secret("kv/data/providers/openai", "api_key")
        client = OpenAI(api_key=key)
        last = None
        for chunk in client.chat.completions.create(
            model="gpt-6-luna", messages=[{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}],
            max_completion_tokens=24, stream=True, stream_options={"include_usage": True},
        ):
            if chunk.usage:
                last = chunk.usage
        capture(result, "openai_chat_stream", last)
        last = None
        for event in client.responses.create(
            model="gpt-6.1-sol", input=[{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}],
            reasoning={"effort": "low"}, max_output_tokens=24, store=False, stream=True,
        ):
            if event.type == "response.completed":
                last = event.response.usage
        capture(result, "openai_responses_stream", last)
    except Exception as exc:
        error(result, "openai_stream", exc)

    try:
        from anthropic import Anthropic
        key = await secrets.get_secret("kv/data/providers/anthropic", "api_key")
        client = Anthropic(api_key=key)
        parts: dict[str, Any] = {}
        for event in client.messages.create(
            model="claude-sonnet-4-6", max_tokens=8, stream=True,
            system=[{"type": "text", "text": PREFIX, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": QUESTION}],
        ):
            if event.type == "message_start":
                parts["start"] = numeric(event.message.usage)
            elif event.type == "message_delta":
                parts["delta"] = numeric(event.usage)
        result["anthropic_stream"] = {"status": "ok", "usage": parts}
    except Exception as exc:
        error(result, "anthropic_stream", exc)

    try:
        import boto3
        key = await secrets.get_secret("kv/data/providers/aws", "access_key_id")
        secret = await secrets.get_secret("kv/data/providers/aws", "secret_access_key")
        region = await secrets.get_secret("kv/data/providers/aws", "region") or "eu-central-1"
        client = boto3.client("bedrock-runtime", aws_access_key_id=key, aws_secret_access_key=secret, region_name=region)
        last = None
        response = client.converse_stream(
            modelId="eu.anthropic.claude-sonnet-4-6",
            system=[{"text": PREFIX}, {"cachePoint": {"type": "default"}}],
            messages=[{"role": "user", "content": [{"text": QUESTION}]}],
            inferenceConfig={"maxTokens": 8},
        )
        for event in response["stream"]:
            if "metadata" in event:
                last = event["metadata"].get("usage")
        capture(result, "bedrock_stream", last)
    except Exception as exc:
        error(result, "bedrock_stream", exc)

    try:
        from google import genai
        from google.genai import types
        key = await secrets.get_secret("kv/data/providers/google_ai_studio", "api_key")
        client = genai.Client(api_key=key)
        last = None
        for chunk in client.models.generate_content_stream(
            model="gemini-3.8-flash", contents=QUESTION,
            config=types.GenerateContentConfig(system_instruction=PREFIX, max_output_tokens=12),
        ):
            if chunk.usage_metadata:
                last = chunk.usage_metadata
        capture(result, "google_studio_stream", last)
    except Exception as exc:
        error(result, "google_studio_stream", exc)

    try:
        from google import genai
        from google.genai import types
        from google.oauth2 import service_account
        sa = await secrets.get_secret("kv/data/providers/google", "service_account_json")
        project = await secrets.get_secret("kv/data/providers/google", "project_id")
        location = await secrets.get_secret("kv/data/providers/google", "location") or "global"
        creds = service_account.Credentials.from_service_account_info(json.loads(sa), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        last = None
        for chunk in client.models.generate_content_stream(
            model="gemini-3.8-flash", contents=QUESTION,
            config=types.GenerateContentConfig(system_instruction=PREFIX, max_output_tokens=12),
        ):
            if chunk.usage_metadata:
                last = chunk.usage_metadata
        capture(result, "google_vertex_stream", last)
    except Exception as exc:
        error(result, "google_vertex_stream", exc)

    try:
        import httpx
        key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
        last = None
        with httpx.stream(
            "POST", "https://api.mistral.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}], "max_tokens": 8, "stream": True},
            timeout=30,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    data = json.loads(line[6:])
                    if data.get("usage") is not None:
                        last = data["usage"]
        capture(result, "mistral_stream", last)
    except Exception as exc:
        error(result, "mistral_stream", exc)

    await secrets.aclose()
    return result


async def probe_google_cache(result: dict, name: str, client: Any, types: Any) -> None:
    cached = None
    try:
        cached = client.caches.create(
            model="gemini-3.8-flash",
            config=types.CreateCachedContentConfig(system_instruction=PREFIX, ttl="300s"),
        )
        capture(result, name + "_create", cached.usage_metadata)
        for attempt in range(2):
            response = client.models.generate_content(
                model="gemini-3.8-flash", contents=QUESTION,
                config=types.GenerateContentConfig(cached_content=cached.name, max_output_tokens=12),
            )
            capture(result, f"{name}_read_{attempt}", response.usage_metadata)
    except Exception as exc:
        error(result, name + "_error", exc)
    finally:
        if cached is not None:
            try:
                client.caches.delete(name=cached.name)
                result[name + "_delete"] = {"status": "ok"}
            except Exception as exc:
                error(result, name + "_delete", exc)


async def run() -> dict:
    result: dict[str, Any] = {}
    secrets = SecretsManager()
    await secrets.initialize()

    # OpenAI's two transports use different typed usage objects.
    try:
        from openai import OpenAI
        key = await secrets.get_secret("kv/data/providers/openai", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        client = OpenAI(api_key=key)
        for attempt in range(2):
            try:
                response = client.responses.create(model="gpt-6.1-sol", input=[{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}], reasoning={"effort": "low"}, max_output_tokens=24, store=False)
                capture(result, f"openai_responses_{attempt}", response.usage)
            except Exception as exc:
                error(result, f"openai_responses_{attempt}", exc)
                break
        for attempt in range(2):
            try:
                response = client.chat.completions.create(model="gpt-6-luna", messages=[{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}], max_completion_tokens=24)
                capture(result, f"openai_chat_{attempt}", response.usage)
            except Exception as exc:
                error(result, f"openai_chat_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "openai_setup", exc)

    # Both Google API surfaces use google-genai's GenerateContentResponseUsageMetadata.
    try:
        from google import genai
        from google.genai import types
        key = await secrets.get_secret("kv/data/providers/google_ai_studio", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        client = genai.Client(api_key=key)
        for attempt in range(2):
            try:
                response = client.models.generate_content(model="gemini-3.8-flash", contents=QUESTION, config=types.GenerateContentConfig(system_instruction=PREFIX, max_output_tokens=12))
                capture(result, f"google_studio_{attempt}", response.usage_metadata)
            except Exception as exc:
                error(result, f"google_studio_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "google_studio_setup", exc)

    try:
        from google import genai
        from google.genai import types
        from google.oauth2 import service_account
        sa = await secrets.get_secret("kv/data/providers/google", "service_account_json")
        project = await secrets.get_secret("kv/data/providers/google", "project_id")
        location = await secrets.get_secret("kv/data/providers/google", "location") or "global"
        if not sa or not project:
            raise RuntimeError("missing credential")
        creds = service_account.Credentials.from_service_account_info(json.loads(sa), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
        for attempt in range(2):
            try:
                response = client.models.generate_content(model="gemini-3.8-flash", contents=QUESTION, config=types.GenerateContentConfig(system_instruction=PREFIX, max_output_tokens=12))
                capture(result, f"google_vertex_{attempt}", response.usage_metadata)
            except Exception as exc:
                error(result, f"google_vertex_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "google_vertex_setup", exc)

    # One explicit breakpoint gives observable creation/read counters.
    try:
        from anthropic import Anthropic
        key = await secrets.get_secret("kv/data/providers/anthropic", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        client = Anthropic(api_key=key)
        for attempt in range(2):
            try:
                response = client.messages.create(model="claude-sonnet-4-6", max_tokens=8, system=[{"type": "text", "text": PREFIX, "cache_control": {"type": "ephemeral"}}], messages=[{"role": "user", "content": QUESTION}])
                capture(result, f"anthropic_{attempt}", response.usage)
            except Exception as exc:
                error(result, f"anthropic_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "anthropic_setup", exc)

    try:
        import boto3
        key = await secrets.get_secret("kv/data/providers/aws", "access_key_id")
        secret = await secrets.get_secret("kv/data/providers/aws", "secret_access_key")
        region = await secrets.get_secret("kv/data/providers/aws", "region") or "eu-central-1"
        if not key or not secret:
            raise RuntimeError("missing credential")
        client = boto3.client("bedrock-runtime", aws_access_key_id=key, aws_secret_access_key=secret, region_name=region)
        for attempt in range(2):
            try:
                response = client.converse(modelId="eu.anthropic.claude-sonnet-4-6", system=[{"text": PREFIX}, {"cachePoint": {"type": "default"}}], messages=[{"role": "user", "content": [{"text": QUESTION}]}], inferenceConfig={"maxTokens": 8})
                capture(result, f"bedrock_{attempt}", response.get("usage"))
            except Exception as exc:
                error(result, f"bedrock_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "bedrock_setup", exc)

    try:
        import httpx
        key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not key:
            raise RuntimeError("missing credential")
        for attempt in range(2):
            try:
                response = httpx.post("https://api.mistral.ai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": "mistral-small-latest", "messages": [{"role": "system", "content": PREFIX}, {"role": "user", "content": QUESTION}], "max_tokens": 8}, timeout=30)
                response.raise_for_status()
                capture(result, f"mistral_{attempt}", response.json().get("usage"))
            except Exception as exc:
                error(result, f"mistral_{attempt}", exc)
                break
    except Exception as exc:
        error(result, "mistral_setup", exc)

    await secrets.aclose()
    return result


if __name__ == "__main__":
    selected = run_extras() if "--extras" in sys.argv else run_streams() if "--streams" in sys.argv else run()
    print(json.dumps(asyncio.run(selected), sort_keys=True))
