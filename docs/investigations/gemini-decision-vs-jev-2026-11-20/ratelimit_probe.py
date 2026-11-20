"""Pace Gemini Decision 1 at fixed rates; record status, latency and the first 429 body and headers.

Run inside the api container (Vault credentials): python ratelimit_probe.py. Synthetic text only.
"""

import asyncio
import json
import time

import httpx

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.google.decisions import GEMINI_DECISIONS_URL, GeminiDecisionClient, request_body

STATE = {"text": "Could you tell me what the weather is like"}
QUESTIONS = {"q": {"type": "noul", "instructions": "Has the speaker finished their sentence?"}}
RATES = ((2, 20), (5, 20), (10, 20))  # (target calls per second, seconds)


def percentile(sorted_values: list[float], q: float) -> float | None:
    return sorted_values[max(0, int(len(sorted_values) * q) - 1)] if sorted_values else None


async def main() -> None:
    secrets = SecretsManager()
    await secrets.initialize()
    key = await GeminiDecisionClient(secrets_manager=secrets)._api_key()
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    body = request_body(STATE, QUESTIONS)
    first_429: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as http:
        for rps, seconds in RATES:
            results: list[tuple[int, float]] = []
            started = time.perf_counter()
            while time.perf_counter() - started < seconds:
                call_started = time.perf_counter()
                response = await http.post(GEMINI_DECISIONS_URL, headers=headers, json=body)
                results.append((response.status_code, (time.perf_counter() - call_started) * 1000))
                if response.status_code == 429 and not first_429:
                    first_429.append({"body": response.text[:600], "headers": dict(response.headers)})
                await asyncio.sleep(max(0, len(results) / rps - (time.perf_counter() - started)))
            ok = sorted(ms for code, ms in results if code == 200)
            limited = sum(code == 429 for code, _ in results)
            other = sum(code not in (200, 429) for code, _ in results)
            print(f"{rps} rps: calls={len(results)} 200={len(ok)} 429={limited} other={other} "
                  f"p50={percentile(ok, 0.5)} p95={percentile(ok, 0.95)}", flush=True)
    print(json.dumps(first_429, indent=1)[:1500])


if __name__ == "__main__":
    asyncio.run(main())
