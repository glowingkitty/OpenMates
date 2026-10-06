#!/usr/bin/env python3
# contract-test-file: tooling
"""Small direct-API latency sample; run inside api with Vault-backed credentials.

Usage: docker exec api python /app/backend/scripts/test_mistral_large4_latency.py
Measures API streaming latency, excluding the OpenMates processing pipeline.
"""

import asyncio
import json
import logging
import time

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager


PROMPT = (
    "Explain in about 60 words why time to first token and total response time "
    "measure different aspects of an AI model's speed."
)


async def sample(client, api_key, model, effort=None):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": True,
        "max_tokens": 1536,
        "temperature": 0.7,
    }
    if effort:
        payload["reasoning_effort"] = effort
    started = time.perf_counter()
    first_event = first_answer = None
    answer = ""
    usage = {}
    finish_reason = None
    async with client.stream(
        "POST", "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"}, json=payload,
    ) as response:
        if response.status_code != 200:
            body = json.loads(await response.aread())
            error = body.get("message") or body.get("detail") or body.get("error", {}).get("message")
            return {"model": model, "status": "fail", "http_status": response.status_code,
                    "error": str(error)[:500]}
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line[6:] == "[DONE]":
                continue
            event = json.loads(line[6:])
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                finish_reason = choice.get("finish_reason") or finish_reason
                content = choice.get("delta", {}).get("content")
                if not content:
                    continue
                if first_event is None:
                    first_event = time.perf_counter() - started
                text = content if isinstance(content, str) else "".join(
                    block.get("text", "") for block in content
                    if block.get("type") == "text"
                )
                if text:
                    if first_answer is None:
                        first_answer = time.perf_counter() - started
                    answer += text
    return {
        "model": model, "reasoning_effort": effort or "default",
        "status": "pass" if answer and finish_reason == "stop" else "incomplete",
        "first_content_seconds": round(first_event, 3) if first_event is not None else None,
        "first_answer_seconds": round(first_answer, 3) if first_answer is not None else None,
        "total_seconds": round(time.perf_counter() - started, 3),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cached_tokens": usage.get("prompt_tokens_details", {}).get("cached_tokens"),
        "answer_words": len(answer.split()), "finish_reason": finish_reason,
    }


async def main():
    logging.basicConfig(level=logging.ERROR)
    secrets = SecretsManager()
    await secrets.initialize()
    try:
        api_key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not api_key:
            print(json.dumps({"status": "fail", "error": "Mistral key unavailable"}))
            return
        async with httpx.AsyncClient(timeout=90) as client:
            for model, effort in [
                ("mistral-large-4", "high"),
                ("mistral-large-4", "high"),
                ("mistral-medium-latest", None),
            ]:
                result = await asyncio.wait_for(sample(client, api_key, model, effort), timeout=100)
                print(json.dumps(result), flush=True)
                if result["status"] != "pass":
                    break
    finally:
        await secrets.aclose()


if __name__ == "__main__":
    asyncio.run(main())
