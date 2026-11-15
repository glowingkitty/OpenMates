"""Synthetic LLM latency probe for the latency research (dev api container only).

Measures, per arm: HTTP response-header time, first streamed chunk, first authored
(non-thought) text, and reported cached tokens. Synthetic prompts only; no chats,
accounts or user data. Run: docker exec -i -e REPEATS=5 api python - < ttft_bench.py
"""

import asyncio
import json
import os
import random
import string
import sys
import time

sys.path.insert(0, "/app")
import httpx  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402

RULE_TOPICS = [
    "formatting",
    "citations",
    "tool use",
    "privacy",
    "tone",
    "languages",
    "code blocks",
    "math",
    "safety",
    "memories",
    "projects",
    "embeds",
    "follow-up suggestions",
    "errors",
]


def system_prompt(target_tokens: int, nonce: str) -> str:
    rng = random.Random(42)
    parts = [
        f"Session marker {nonce}. You are a helpful assistant inside a privacy-focused chat app."
    ]
    i = 0
    while len(" ".join(parts)) / 4 < target_tokens:
        topic = RULE_TOPICS[i % len(RULE_TOPICS)]
        words = " ".join(
            rng.choice(
                [
                    "always",
                    "never",
                    "prefer",
                    "when",
                    "the",
                    "user",
                    "asks",
                    "answer",
                    "briefly",
                    "explain",
                    "include",
                    "avoid",
                    "concise",
                    "examples",
                    "context",
                    "details",
                    "structure",
                    "steps",
                    "clearly",
                    "relevant",
                ]
            )
            for _ in range(60)
        )
        parts.append(f"Rule {i} ({topic}): {words}.")
        i += 1
    return "\n".join(parts)


QUESTION = "Why does the sky look blue? Answer in two short sentences."
ARMS = {
    # name: (provider, model, reasoning, prompt_tokens, cold)
    "gemini-3.8-flash MEDIUM 20k": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "MEDIUM",
        20000,
        True,
    ),
    "gemini-3.8-flash LOW 20k": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "LOW",
        20000,
        True,
    ),
    "gemini-3.8-flash MINIMAL 20k": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "MINIMAL",
        20000,
        True,
    ),
    "gemini-3.8-flash LOW 20k warm-prefix": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "LOW",
        20000,
        False,
    ),
    "gemini-3.8-flash LOW 1k": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "LOW",
        1000,
        True,
    ),
    "gemini-3.8-flash MEDIUM 1k": (
        "google_ai_studio",
        "gemini-3.8-flash",
        "MEDIUM",
        1000,
        True,
    ),
    "mercury-3 instant 20k": ("inception_labs", "mercury-3", "instant", 20000, True),
    "mercury-3 low 20k": ("inception_labs", "mercury-3", "low", 20000, True),
    "mistral-small-latest 20k (EU)": (
        "mistral_ai",
        "mistral-small-latest",
        None,
        20000,
        True,
    ),
    "mistral-medium-latest 20k (EU)": (
        "mistral_ai",
        "mistral-medium-latest",
        None,
        20000,
        True,
    ),
}


def request(arm: str, nonce: str):
    provider, model, reasoning, tokens, cold = ARMS[arm]
    system = system_prompt(tokens, nonce if cold else "stable")
    if provider == "google_ai_studio":
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": QUESTION}]}],
            "generationConfig": {
                "maxOutputTokens": 1024,
                "thinkingConfig": {"thinkingLevel": reasoning, "includeThoughts": True},
            },
        }
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse",
            body,
        )
    body = {
        "model": model,
        "stream": True,
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": QUESTION},
        ],
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    url = {
        "inception_labs": "https://api.inceptionlabs.ai/v1/chat/completions",
        "mistral_ai": "https://api.mistral.ai/v1/chat/completions",
    }[provider]
    return url, body


async def run(client, keys, arm):
    provider = ARMS[arm][0]
    url, body = request(arm, "".join(random.choices(string.ascii_lowercase, k=12)))
    headers = (
        {"x-goog-api-key": keys[provider]}
        if provider == "google_ai_studio"
        else {"Authorization": "Bearer " + keys[provider]}
    )
    row = {
        "arm": arm,
        "headers_ms": None,
        "first_chunk_ms": None,
        "first_text_ms": None,
        "status": None,
        "cached": None,
        "prompt_tokens": None,
        "thought_tokens": None,
    }
    start = time.perf_counter()
    try:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            row["headers_ms"] = (time.perf_counter() - start) * 1000
            row["status"] = resp.status_code
            if resp.status_code != 200:
                row["error"] = (await resp.aread()).decode()[:200]
                return row
            async for line in resp.aiter_lines():
                if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
                    continue
                now = (time.perf_counter() - start) * 1000
                event = json.loads(line[5:])
                row["first_chunk_ms"] = row["first_chunk_ms"] or now
                text = ""
                if provider == "google_ai_studio":
                    for cand in event.get("candidates", []):
                        for part in cand.get("content", {}).get("parts", []):
                            if part.get("text") and not part.get("thought"):
                                text += part["text"]
                    usage = event.get("usageMetadata") or {}
                    row["cached"] = usage.get("cachedContentTokenCount", row["cached"])
                    row["prompt_tokens"] = usage.get(
                        "promptTokenCount", row["prompt_tokens"]
                    )
                    row["thought_tokens"] = usage.get(
                        "thoughtsTokenCount", row["thought_tokens"]
                    )
                else:
                    for choice in event.get("choices", []):
                        text += (choice.get("delta") or {}).get("content") or ""
                    usage = event.get("usage") or {}
                    if usage:
                        row["prompt_tokens"] = usage.get("prompt_tokens")
                        row["cached"] = (usage.get("prompt_tokens_details") or {}).get(
                            "cached_tokens"
                        )
                if text and row["first_text_ms"] is None:
                    row["first_text_ms"] = now
    except httpx.HTTPError as exc:
        row["error"] = type(exc).__name__
    return row


async def main():
    repeats = int(os.environ.get("REPEATS", "5"))
    arms = [
        a
        for a in ARMS
        if not os.environ.get("ARMS")
        or any(s in a for s in os.environ["ARMS"].split(","))
    ]
    manager = SecretsManager()
    await manager.initialize()
    keys = {}
    for provider in {ARMS[a][0] for a in arms}:
        keys[provider] = await manager.get_secret(
            secret_path="kv/data/providers/" + provider, secret_key="api_key"
        )
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5)) as client:
        for r in range(repeats):
            order = arms[r % len(arms) :] + arms[: r % len(arms)]
            for arm in order:
                rows.append(await run(client, keys, arm))
    print(json.dumps(rows))


if __name__ == "__main__":
    asyncio.run(main())
