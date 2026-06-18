#!/usr/bin/env python3
# backend/tests/test_kimi_k2_7_code_script.py
#
# Unit coverage for the live Kimi K2.7 Code smoke-test helper.
# Keeps the script's local extraction, sandbox, and validators deterministic
# without making live Together AI calls during regular test runs. The live model
# quality check remains backend/scripts/test_kimi_k2_7_code.py.

from pathlib import Path

import pytest
import yaml

from backend.scripts import test_kimi_k2_7_code as smoke


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_extract_python_code_from_fenced_block():
    content = "Here is code:\n```python\ndef answer():\n    return 42\n```"

    assert smoke._extract_python_code(content) == "def answer():\n    return 42"


def test_smoke_script_targets_together_primary_model():
    assert smoke.MODEL_ID == "moonshotai/Kimi-K2.7-Code"


def test_kimi_k2_7_code_config_uses_together_primary_with_openrouter_fallback():
    provider_config = yaml.safe_load((REPO_ROOT / "backend/providers/moonshot.yml").read_text())
    model = next(model for model in provider_config["models"] if model["id"] == "kimi-k2.7-code")

    assert model["default_server"] == "together"
    assert model["external_ids"]["together"] == "moonshotai/Kimi-K2.7-Code"
    assert [server["id"] for server in model["servers"]] == ["together", "openrouter"]
    assert model["servers"][0]["model_id"] == "moonshotai/Kimi-K2.7-Code"
    assert model["servers"][1]["model_id"] == "moonshotai/kimi-k2.7-code"


def test_sandbox_rejects_imports():
    with pytest.raises(AssertionError, match="Forbidden syntax"):
        smoke._exec_generated("import os\n")


def test_longest_valid_parentheses_validator_accepts_correct_solution():
    namespace = smoke._exec_generated(
        "def longest_valid_parentheses(s: str) -> int:\n"
        "    stack = [-1]\n"
        "    best = 0\n"
        "    for index, char in enumerate(s):\n"
        "        if char == '(':\n"
        "            stack.append(index)\n"
        "        else:\n"
        "            stack.pop()\n"
        "            if stack:\n"
        "                best = max(best, index - stack[-1])\n"
        "            else:\n"
        "                stack.append(index)\n"
        "    return best\n"
    )

    smoke._validate_longest_valid_parentheses(namespace)


def test_top_k_validator_rejects_incorrect_solution():
    namespace = smoke._exec_generated("def top_k_frequent(nums: list[int], k: int) -> list[int]:\n    return nums[:k]\n")

    with pytest.raises(AssertionError, match="top_k_frequent"):
        smoke._validate_top_k_frequent(namespace)


def test_lru_cache_validator_accepts_correct_solution():
    namespace = smoke._exec_generated(
        "class LRUCache:\n"
        "    def __init__(self, capacity: int):\n"
        "        self.capacity = capacity\n"
        "        self.items = {}\n"
        "        self.order = []\n"
        "    def get(self, key: int) -> int:\n"
        "        if key not in self.items:\n"
        "            return -1\n"
        "        self.order.remove(key)\n"
        "        self.order.append(key)\n"
        "        return self.items[key]\n"
        "    def put(self, key: int, value: int) -> None:\n"
        "        if key in self.items:\n"
        "            self.order.remove(key)\n"
        "        elif len(self.items) >= self.capacity:\n"
        "            old_key = self.order.pop(0)\n"
        "            del self.items[old_key]\n"
        "        self.items[key] = value\n"
        "        self.order.append(key)\n"
    )

    smoke._validate_lru_cache(namespace)
