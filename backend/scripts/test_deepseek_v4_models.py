#!/usr/bin/env python3
# backend/scripts/test_deepseek_v4_models.py
#
# Live verification and practical speed comparison for DeepSeek V4 models.
# Tests V4 Pro through Together AI direct API and OpenRouter fallback, then
# compares it against V4 Flash through OpenRouter with AtlasCloud routing.

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from backend.apps.ai.llm_providers.openai_openrouter import (
    invoke_openrouter_chat_completions,
)
from backend.apps.ai.llm_providers.together_wrapper import (
    invoke_together_chat_completions,
)
from backend.core.api.app.utils.config_manager import config_manager
from backend.core.api.app.utils.secrets_manager import SecretsManager


BENCHMARK_MESSAGES = [
    {
        "role": "user",
        "content": (
            "In exactly four bullet points, compare latency, price, context, "
            "and best use case for a fast model versus a pro model."
        ),
    }
]


@dataclass
class BenchmarkResult:
    label: str
    success: bool
    elapsed_seconds: float
    output_chars: int
    total_tokens: int | None
    output_tokens: int | None
    error: str | None = None

    @property
    def output_tokens_per_second(self) -> float | None:
        if not self.output_tokens or self.elapsed_seconds <= 0:
            return None
        return self.output_tokens / self.elapsed_seconds


async def run_case(
    label: str,
    call: Callable[[], Awaitable],
) -> BenchmarkResult:
    start = time.perf_counter()
    response = await call()
    elapsed = time.perf_counter() - start

    if not response.success:
        return BenchmarkResult(
            label=label,
            success=False,
            elapsed_seconds=elapsed,
            output_chars=0,
            total_tokens=None,
            output_tokens=None,
            error=response.error_message,
        )

    content = response.direct_message_content or ""
    usage = response.usage
    return BenchmarkResult(
        label=label,
        success=True,
        elapsed_seconds=elapsed,
        output_chars=len(content),
        total_tokens=usage.total_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
    )


def verify_config() -> None:
    pro = config_manager.get_model_pricing("deepseek", "deepseek-v4-pro")
    flash = config_manager.get_model_pricing("deepseek", "deepseek-v4-flash")
    assert pro is not None, "missing deepseek-v4-pro config"
    assert flash is not None, "missing deepseek-v4-flash config"
    assert pro["default_server"] == "together"
    assert [server["id"] for server in pro["servers"]] == ["together", "openrouter"]
    assert pro["servers"][0]["model_id"] == "deepseek-ai/DeepSeek-V4-Pro"
    assert pro["servers"][1]["model_id"] == "deepseek/deepseek-v4-pro"
    assert flash["default_server"] == "openrouter"


async def main() -> int:
    verify_config()

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    cases = [
        (
            "DeepSeek V4 Pro - Together direct",
            lambda: invoke_together_chat_completions(
                task_id="bench_deepseek_v4_pro_together",
                model_id="deepseek-ai/DeepSeek-V4-Pro",
                messages=BENCHMARK_MESSAGES,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=512,
                stream=False,
            ),
        ),
        (
            "DeepSeek V4 Pro - OpenRouter fallback",
            lambda: invoke_openrouter_chat_completions(
                task_id="bench_deepseek_v4_pro_openrouter",
                model_id="deepseek/deepseek-v4-pro",
                messages=BENCHMARK_MESSAGES,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=512,
                stream=False,
            ),
        ),
        (
            "DeepSeek V4 Flash - OpenRouter AtlasCloud",
            lambda: invoke_openrouter_chat_completions(
                task_id="bench_deepseek_v4_flash_openrouter",
                model_id="deepseek/deepseek-v4-flash",
                messages=BENCHMARK_MESSAGES,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=512,
                stream=False,
            ),
        ),
    ]

    print("\nDeepSeek V4 live benchmark")
    print("=" * 80)
    results = []
    for label, call in cases:
        result = await run_case(label, call)
        results.append(result)
        status = "OK" if result.success else "FAIL"
        tps = result.output_tokens_per_second
        tps_text = f"{tps:.1f} output tok/s" if tps is not None else "n/a tok/s"
        print(
            f"{status} | {result.label} | {result.elapsed_seconds:.2f}s | "
            f"{result.output_chars} chars | {result.total_tokens} total tokens | {tps_text}"
        )
        if result.error:
            print(f"  error: {result.error}")

    return 0 if all(result.success for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
