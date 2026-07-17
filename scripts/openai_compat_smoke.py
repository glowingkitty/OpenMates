#!/usr/bin/env python3
"""Live smoke test for OpenMates' OpenAI-compatible `/v1` API.

Requires `OPENMATES_TEST_ACCOUNT_API_KEY` and the official `openai` Python
package. The script targets the dev API by default, discovers a model from
`/v1/models`, then checks model retrieval, text chat, streaming, forced function
tool calls, and a tool-result follow-up through the official SDK.
"""

from __future__ import annotations

import os
import sys
from typing import Any
import argparse


DEFAULT_BASE_URL = "https://api.dev.openmates.org/v1"
DEFAULT_ORIGIN = "https://app.dev.openmates.org"


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test OpenMates' OpenAI-compatible API.")
    parser.add_argument("--base-url", default=os.getenv("OPENMATES_OPENAI_COMPAT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--origin", default=os.getenv("OPENMATES_OPENAI_COMPAT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--model", default=os.getenv("OPENMATES_OPENAI_COMPAT_MODEL"))
    parser.add_argument("--mode", default="all", help="Accepted for spec command compatibility; this script runs the full smoke.")
    return parser.parse_args()


def _client(args: argparse.Namespace) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit("Install the official OpenAI Python SDK to run this smoke test: pip install openai") from exc

    return OpenAI(
        api_key=_require_env("OPENMATES_TEST_ACCOUNT_API_KEY"),
        base_url=args.base_url,
        default_headers={"Origin": args.origin},
    )


def _pick_model(client: Any, configured_model: str | None) -> str:
    if configured_model:
        return configured_model
    models = list(client.models.list().data)
    if not models:
        raise SystemExit("/v1/models returned no models")
    return models[0].id


def main() -> int:
    args = _parse_args()
    client = _client(args)
    model = _pick_model(client, args.model)
    print(f"[openai-compat] model={model}")

    retrieved = client.models.retrieve(model)
    assert retrieved.id == model, f"Unexpected model retrieve result: {retrieved}"

    text_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        temperature=0,
    )
    text = text_response.choices[0].message.content or ""
    assert text.strip(), "Plain chat completion returned empty content"
    print(f"[openai-compat] text={text[:80]!r}")

    stream_chunks = []
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with one short word."}],
        temperature=0,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            stream_chunks.append(delta.content)
    assert "".join(stream_chunks).strip(), "Streaming chat completion returned empty content"
    print(f"[openai-compat] stream={''.join(stream_chunks)[:80]!r}")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    tool_response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "What is the weather in Berlin?"}],
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "get_weather"}},
    )
    tool_calls = tool_response.choices[0].message.tool_calls or []
    assert tool_calls, "Forced function tool call returned no tool_calls"
    assert tool_calls[0].function.name == "get_weather"
    print(f"[openai-compat] tool_call={tool_calls[0].id}:{tool_calls[0].function.name}")

    followup = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "What is the weather in Berlin?"},
            tool_response.choices[0].message,
            {"role": "tool", "tool_call_id": tool_calls[0].id, "content": '{"weather":"sunny"}'},
            {"role": "user", "content": "Summarize the weather in five words."},
        ],
        tools=tools,
    )
    final_text = followup.choices[0].message.content or ""
    assert final_text.strip(), "Tool follow-up returned empty content"
    print(f"[openai-compat] followup={final_text[:80]!r}")
    print("[openai-compat] python SDK smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
