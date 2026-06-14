#!/usr/bin/env python3
# backend/scripts/test_kimi_k2_7_code.py
#
# Live quality smoke test for Moonshot Kimi K2.7 Code via OpenRouter.
# Invokes the configured OpenRouter model on three coding tasks, extracts the
# returned Python code, performs a small AST safety check, and runs deterministic
# correctness cases against the generated implementations.

import ast
import asyncio
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


MODEL_ID = "moonshot/kimi-k2.7-code"
MAX_TOKENS = 1800
TEMPERATURE = 0

SAFE_BUILTINS = {
    "__build_class__": __build_class__,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "object": object,
    "range": range,
    "reversed": reversed,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
}

FORBIDDEN_AST_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.Import,
    ast.ImportFrom,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.With,
)
FORBIDDEN_CALL_NAMES = {"compile", "eval", "exec", "globals", "locals", "open", "__import__"}


@dataclass(frozen=True)
class SmokeTask:
    name: str
    prompt: str
    validator: Callable[[dict[str, Any]], None]


def _extract_python_code(content: str) -> str:
    fenced = re.search(r"```(?:python)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return content.strip()


def _assert_safe_python(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, FORBIDDEN_AST_NODES):
            raise AssertionError(f"Forbidden syntax in generated code: {type(node).__name__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALL_NAMES:
                raise AssertionError(f"Forbidden call in generated code: {node.func.id}")


def _exec_generated(code: str) -> dict[str, Any]:
    _assert_safe_python(code)
    namespace: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "__name__": "__kimi_smoke__"}
    exec(compile(code, "<kimi-k2.7-code-output>", "exec"), namespace)
    return namespace


def _validate_longest_valid_parentheses(namespace: dict[str, Any]) -> None:
    fn = namespace.get("longest_valid_parentheses")
    if not callable(fn):
        raise AssertionError("Missing callable longest_valid_parentheses")
    cases = {
        "": 0,
        "(()": 2,
        ")()())": 4,
        "()(())": 6,
        ")()())()()": 4,
        "((()))())": 8,
    }
    for value, expected in cases.items():
        actual = fn(value)
        if actual != expected:
            raise AssertionError(f"longest_valid_parentheses({value!r}) -> {actual}, expected {expected}")


def _validate_top_k_frequent(namespace: dict[str, Any]) -> None:
    fn = namespace.get("top_k_frequent")
    if not callable(fn):
        raise AssertionError("Missing callable top_k_frequent")
    cases = [
        ([1, 1, 1, 2, 2, 3], 2, {1, 2}),
        ([4, 4, 4, 6, 6, 7, 7, 7, 7], 1, {7}),
        ([5, -1, -1, 5, 5, 2], 2, {5, -1}),
    ]
    for nums, k, expected in cases:
        actual = set(fn(nums, k))
        if actual != expected:
            raise AssertionError(f"top_k_frequent({nums!r}, {k}) -> {actual}, expected {expected}")


def _validate_lru_cache(namespace: dict[str, Any]) -> None:
    cls = namespace.get("LRUCache")
    if not isinstance(cls, type):
        raise AssertionError("Missing class LRUCache")
    cache = cls(2)
    cache.put(1, 1)
    cache.put(2, 2)
    if cache.get(1) != 1:
        raise AssertionError("LRUCache failed to return existing key")
    cache.put(3, 3)
    if cache.get(2) != -1:
        raise AssertionError("LRUCache failed to evict least recently used key 2")
    cache.put(4, 4)
    if (cache.get(1), cache.get(3), cache.get(4)) != (-1, 3, 4):
        raise AssertionError("LRUCache final eviction/access sequence failed")


SMOKE_TASKS = [
    SmokeTask(
        name="longest_valid_parentheses",
        prompt=(
            "Return only Python code, no explanation and no imports. "
            "Implement def longest_valid_parentheses(s: str) -> int. "
            "It must return the length of the longest contiguous valid parentheses substring."
        ),
        validator=_validate_longest_valid_parentheses,
    ),
    SmokeTask(
        name="top_k_frequent_bug_fix",
        prompt=(
            "Return only Python code, no explanation and no imports. "
            "Implement def top_k_frequent(nums: list[int], k: int) -> list[int]. "
            "The function must return exactly k numbers with the highest frequencies. "
            "Handle negative numbers and ties may be returned in any order."
        ),
        validator=_validate_top_k_frequent,
    ),
    SmokeTask(
        name="lru_cache",
        prompt=(
            "Return only Python code, no explanation and no imports. "
            "Implement class LRUCache with __init__(capacity: int), get(key: int) -> int, "
            "and put(key: int, value: int) -> None. get returns -1 for missing keys. "
            "Both operations should update recency."
        ),
        validator=_validate_lru_cache,
    ),
]


async def _run_smoke_tests() -> int:
    from backend.apps.ai.llm_providers.openai_openrouter import invoke_openrouter_chat_completions
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    print("KIMI K2.7 CODE QUALITY SMOKE TEST")
    print(f"Model: {MODEL_ID}")
    print(f"Tasks: {len(SMOKE_TASKS)}")

    failures = 0
    for task in SMOKE_TASKS:
        response = await invoke_openrouter_chat_completions(
            task_id=f"test_kimi_k2_7_code_{task.name}",
            model_id=MODEL_ID,
            messages=[{"role": "user", "content": task.prompt}],
            secrets_manager=secrets_manager,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        if not response.success:
            print(f"FAIL {task.name}: {response.error_message}")
            failures += 1
            continue

        content = response.direct_message_content or ""
        code = _extract_python_code(content)
        try:
            namespace = _exec_generated(code)
            task.validator(namespace)
        except Exception as exc:
            print(f"FAIL {task.name}: {exc}")
            print("Generated code:")
            print(code[:2000])
            failures += 1
            continue

        usage = f", tokens={response.usage.total_tokens}" if response.usage else ""
        print(f"PASS {task.name}{usage}")

    if failures:
        print(f"FAILED: {failures}/{len(SMOKE_TASKS)} tasks failed")
        return 1

    print("PASSED: all quality smoke tasks passed")
    return 0


if __name__ == "__main__":
    sys.path.append("/app")
    raise SystemExit(asyncio.run(_run_smoke_tests()))
