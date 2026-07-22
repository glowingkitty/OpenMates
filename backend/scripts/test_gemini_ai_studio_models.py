#!/usr/bin/env python3
# backend/scripts/test_gemini_ai_studio_models.py
#
# Direct Google AI Studio model probe and small deterministic benchmark.
# Runs inside the API container so it uses the same Vault-backed
# `kv/data/providers/google_ai_studio` secret and google_client.py path as the
# backend. This intentionally bypasses OpenMates chat personas and app-skill
# routing so model comparisons measure the provider model, not product behavior.
#
# Usage:
#   docker exec api python /app/backend/scripts/test_gemini_ai_studio_models.py

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.1-pro-preview",
]


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    prompt: str
    max_tokens: int


CASES = [
    BenchmarkCase(
        id="exact_token",
        prompt="Reply with exactly this token and no extra text: BENCHMARK_SMOKE_OK",
        max_tokens=256,
    ),
    BenchmarkCase(
        id="arithmetic",
        prompt="Compute 19 * 23. Reply with only the integer result.",
        max_tokens=256,
    ),
    BenchmarkCase(
        id="code_palindrome",
        prompt=(
            "Write a TypeScript function isPalindrome(input: string): boolean "
            "that ignores spaces, punctuation, and case. Include only the "
            "function and one short usage example."
        ),
        max_tokens=900,
    ),
]


def score_case(case_id: str, text: str) -> tuple[bool, int, str]:
    stripped = text.strip()
    lowered = stripped.lower()

    if case_id == "exact_token":
        passed = stripped == "BENCHMARK_SMOKE_OK"
        return passed, 3 if passed else 0, "exact token match" if passed else "response was not exact"

    if case_id == "arithmetic":
        digits = re.sub(r"\D+", "", stripped)
        passed = digits == "437"
        return passed, 3 if passed else 0, "correct arithmetic" if passed else f"expected 437, got {stripped[:80]}"

    if case_id == "code_palindrome":
        checks = [
            ("function name", "ispalindrome" in lowered),
            ("string parameter", "input" in lowered and "string" in lowered),
            ("boolean return", "boolean" in lowered),
            ("normalization", "tolowercase" in lowered or "lowercase" in lowered),
            ("punctuation removal", "replace" in lowered or "match" in lowered or "regex" in lowered),
            ("reverse comparison", "reverse" in lowered or "left" in lowered and "right" in lowered),
            ("usage example", "console.log" in lowered or "ispalindrome(" in lowered and stripped.count("isPalindrome") >= 2),
        ]
        score = sum(1 for _, ok in checks if ok)
        missing = [name for name, ok in checks if not ok]
        passed = score >= 6
        reason = "passed code checks" if passed else "missing: " + ", ".join(missing)
        return passed, score, reason

    return False, 0, "unknown case"


async def run_case(model: str, case: BenchmarkCase, secrets_manager: Any) -> dict[str, Any]:
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

    start = time.perf_counter()
    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"gemini_model_benchmark_{model}_{case.id}".replace(".", "_").replace("-", "_"),
            model_id=model,
            messages=[{"role": "user", "content": case.prompt}],
            secrets_manager=secrets_manager,
            temperature=1.0,
            max_tokens=case.max_tokens,
            stream=False,
        )
    except Exception as exc:  # noqa: BLE001 - script reports provider errors as data.
        return {
            "case_id": case.id,
            "success": False,
            "passed": False,
            "score": 0,
            "duration_ms": round((time.perf_counter() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }

    duration_ms = round((time.perf_counter() - start) * 1000)
    text = (response.direct_message_content or "").strip()
    passed, score, reason = score_case(case.id, text)
    usage = response.usage.model_dump() if response.usage else None
    return {
        "case_id": case.id,
        "success": response.success,
        "passed": bool(response.success and passed),
        "score": score if response.success else 0,
        "reason": reason if response.success else response.error_message,
        "duration_ms": duration_ms,
        "usage": usage,
        "text_preview": text[:240],
    }


async def main() -> int:
    sys.path.append("/app")

    parser = argparse.ArgumentParser(description="Direct Gemini AI Studio model probe and deterministic benchmark.")
    parser.add_argument("--model", action="append", dest="models", help="Model ID to test. Can be repeated.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    if args.json:
        logging.getLogger("backend.apps.ai.llm_providers.google_client").setLevel(logging.CRITICAL)
        logging.getLogger("google").setLevel(logging.CRITICAL)

    from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    key = await _get_google_ai_studio_api_key(secrets_manager)
    models = args.models or DEFAULT_MODELS

    results: list[dict[str, Any]] = []
    for model in models:
        case_results = [await run_case(model, case, secrets_manager) for case in CASES]
        passed = sum(1 for result in case_results if result["passed"])
        total_score = sum(int(result["score"] or 0) for result in case_results)
        total_duration = sum(int(result["duration_ms"] or 0) for result in case_results)
        total_tokens = sum(
            int((result.get("usage") or {}).get("total_token_count") or 0)
            for result in case_results
        )
        results.append(
            {
                "model": model,
                "available": all(result["success"] for result in case_results),
                "passed": passed,
                "total": len(case_results),
                "score": total_score,
                "duration_ms": total_duration,
                "total_tokens": total_tokens,
                "cases": case_results,
            }
        )

    output = {
        "vault_key_present": bool(key),
        "models": results,
        "ranking": sorted(
            [
                {
                    "model": result["model"],
                    "passed": result["passed"],
                    "total": result["total"],
                    "score": result["score"],
                    "duration_ms": result["duration_ms"],
                    "total_tokens": result["total_tokens"],
                    "available": result["available"],
                }
                for result in results
            ],
            key=lambda item: (item["available"], item["passed"], item["score"], -item["duration_ms"]),
            reverse=True,
        ),
    }

    print(json.dumps(output, indent=2 if not args.json else None))
    return 0 if all(result["available"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
