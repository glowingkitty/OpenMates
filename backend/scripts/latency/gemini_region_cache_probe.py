"""Gemini region / explicit-cache / parallel-start probe (dev api container, synthetic prompts only).

Arms (gemini-3.8-flash, thinking LOW unless named, 20k-token synthetic system prompt):
  studio            AI Studio (today's route)
  vertex-global     Vertex AI, location global
  vertex-eu         Vertex AI, EU multi-region endpoint
  vertex-us         Vertex AI, US multi-region endpoint
  studio-explicit-cache  AI Studio with an explicit cachedContents prefix
  serial-pre        two Mercury 3 preprocessing-sized calls, then the main Gemini call (today's order)
  parallel-pre      the same three calls started together; main first text measured from t0
Env: REPEATS, ARMS (comma substrings).
"""

import asyncio
import json
import os
import random
import string
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import httpx
import google.auth.transport.requests
from google.oauth2 import service_account
from backend.core.api.app.utils.secrets_manager import SecretsManager
from llm_first_text_probe import system_prompt  # shared synthetic 20k-token prompt

MODEL = "gemini-3.8-flash"
QUESTION = "Why does the sky look blue? Answer in two short sentences."


def nonce():
    return "".join(random.choices(string.ascii_lowercase, k=12))


def gemini_body(system, level="LOW", cached=None):
    body = {
        "contents": [{"role": "user", "parts": [{"text": QUESTION}]}],
        "generationConfig": {
            "maxOutputTokens": 512,
            "thinkingConfig": {"thinkingLevel": level, "includeThoughts": True},
        },
    }
    if cached:
        body["cachedContent"] = cached
    else:
        body["systemInstruction"] = {"role": "system", "parts": [{"text": system}]}
    return body


async def stream_gemini(client, url, headers, body):
    row = {"headers_ms": None, "first_text_ms": None, "status": None, "cached": None}
    t0 = time.perf_counter()
    async with client.stream("POST", url, headers=headers, json=body) as resp:
        row["headers_ms"] = (time.perf_counter() - t0) * 1000
        row["status"] = resp.status_code
        if resp.status_code != 200:
            row["error"] = (await resp.aread()).decode()[:240]
            return row
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:])
            for c in ev.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    if (
                        p.get("text")
                        and not p.get("thought")
                        and row["first_text_ms"] is None
                    ):
                        row["first_text_ms"] = (time.perf_counter() - t0) * 1000
            u = ev.get("usageMetadata") or {}
            row["cached"] = u.get("cachedContentTokenCount", row["cached"])
    return row


async def mercury(client, key, tokens):
    body = {
        "model": "mercury-3",
        "stream": False,
        "max_tokens": 200,
        "reasoning_effort": "instant",
        "messages": [
            {"role": "system", "content": system_prompt(tokens, nonce())},
            {
                "role": "user",
                "content": 'Classify this request and reply with JSON {"tier":"low"}: '
                + QUESTION,
            },
        ],
    }
    r = await client.post(
        "https://api.inceptionlabs.ai/v1/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json=body,
    )
    return r.status_code


async def main():
    sm = SecretsManager()
    await sm.initialize()
    studio_key = await sm.get_secret("kv/data/providers/google_ai_studio", "api_key")
    merc_key = await sm.get_secret("kv/data/providers/inception_labs", "api_key")
    project = await sm.get_secret("kv/data/providers/google", "project_id")
    creds = service_account.Credentials.from_service_account_info(
        json.loads(
            await sm.get_secret("kv/data/providers/google", "service_account_json")
        ),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google.auth.transport.requests.Request())

    def vhead():
        return {"Authorization": "Bearer " + creds.token}

    vurl = {
        "vertex-global": f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global",
        "vertex-eu": f"https://aiplatform.eu.rep.googleapis.com/v1/projects/{project}/locations/eu",
        "vertex-us": f"https://aiplatform.us.rep.googleapis.com/v1/projects/{project}/locations/us",
    }
    studio_url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:streamGenerateContent?alt=sse"
    shead = {"x-goog-api-key": studio_key}
    arms = [
        "studio",
        "vertex-global",
        "vertex-eu",
        "vertex-us",
        "studio-explicit-cache",
        "serial-pre",
        "parallel-pre",
    ]
    if os.environ.get("ARMS"):
        arms = [a for a in arms if any(s == a for s in os.environ["ARMS"].split(","))]
    rows = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        cache_name = None
        if "studio-explicit-cache" in arms:
            r = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/cachedContents",
                headers=shead,
                json={
                    "model": f"models/{MODEL}",
                    "ttl": "900s",
                    "systemInstruction": {
                        "parts": [{"text": system_prompt(20000, "explicit-stable")}]
                    },
                },
            )
            cache_name = r.json().get("name") if r.status_code == 200 else None
            if not cache_name:
                rows.append({"arm": "studio-explicit-cache", "error": r.text[:240]})
        for rep in range(int(os.environ.get("REPEATS", "5"))):
            for arm in arms[rep % len(arms) :] + arms[: rep % len(arms)]:
                try:
                    if arm == "studio":
                        row = await stream_gemini(
                            client,
                            studio_url,
                            shead,
                            gemini_body(system_prompt(20000, nonce())),
                        )
                    elif arm.startswith("vertex"):
                        url = f"{vurl[arm]}/publishers/google/models/{MODEL}:streamGenerateContent?alt=sse"
                        row = await stream_gemini(
                            client,
                            url,
                            vhead(),
                            gemini_body(system_prompt(20000, nonce())),
                        )
                    elif arm == "studio-explicit-cache":
                        if not cache_name:
                            continue
                        row = await stream_gemini(
                            client,
                            studio_url,
                            shead,
                            gemini_body(None, cached=cache_name),
                        )
                    elif arm == "serial-pre":
                        t0 = time.perf_counter()
                        await mercury(client, merc_key, 3000)
                        await mercury(client, merc_key, 1500)
                        pre = (time.perf_counter() - t0) * 1000
                        row = await stream_gemini(
                            client,
                            studio_url,
                            shead,
                            gemini_body(system_prompt(20000, nonce())),
                        )
                        row = {
                            **row,
                            "pre_ms": pre,
                            "first_text_ms": row["first_text_ms"]
                            and row["first_text_ms"] + pre,
                        }
                    else:  # parallel-pre
                        t0 = time.perf_counter()

                        async def preprocessing():
                            await asyncio.gather(
                                mercury(client, merc_key, 3000),
                                mercury(client, merc_key, 1500),
                            )
                            return (time.perf_counter() - t0) * 1000

                        res = await asyncio.gather(
                            preprocessing(),
                            stream_gemini(
                                client,
                                studio_url,
                                shead,
                                gemini_body(system_prompt(20000, nonce())),
                            ),
                        )
                        row = {**res[1], "pre_done_ms": res[0]}
                except httpx.HTTPError as exc:
                    row = {"error": type(exc).__name__}
                rows.append({"arm": arm, **row})
        if cache_name:
            await client.delete(
                f"https://generativelanguage.googleapis.com/v1beta/{cache_name}",
                headers=shead,
            )
    print(json.dumps(rows))


asyncio.run(main())
