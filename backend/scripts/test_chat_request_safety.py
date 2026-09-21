#!/usr/bin/env python3
# contract-test-file: tooling
"""Evaluate chat request safety with Vault-backed provider credentials.

Architecture: Runs inside the API container and calls the production preliminary
first/follow-up prompt followed by structured confirmation when it produces a
safety candidate. Output contains only case IDs, scores, decisions, categories,
and aggregate counts; user text and provider payloads are never printed.
Usage: docker exec api python /app/backend/scripts/test_chat_request_safety.py
"""

from __future__ import annotations

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

import yaml

from backend.apps.ai.processing.chat_request_safety import (
    confirm_chat_request_safety,
    needs_safety_confirmation,
)
from backend.apps.ai.testing.chat_request_safety_cases import (
    CHAT_REQUEST_SAFETY_CASES,
    CHAT_REQUEST_SAFETY_CORPUS_VERSION,
)
from backend.apps.ai.utils.llm_utils import call_preprocessing_llm
from backend.core.api.app.utils.secrets_manager import SecretsManager


BASE_INSTRUCTIONS_PATH = Path(__file__).resolve().parents[1] / "apps/ai/base_instructions.yml"
APP_CONFIG_PATH = Path(__file__).resolve().parents[1] / "apps/ai/app.yml"


def _configured_safety() -> tuple[str, float, float]:
    app_config = yaml.safe_load(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    ask_skill = next(skill for skill in app_config["skills"] if skill.get("id") == "ask")
    skill_config = ask_skill["skill_config"]
    defaults = skill_config["default_llms"]
    thresholds = skill_config["preprocessing_thresholds"]
    model_id = defaults.get("request_safety_model") or defaults["preprocessing_model"]
    return (
        str(model_id),
        float(thresholds["harmful_content_score"]),
        float(thresholds["misuse_risk_score"]),
    )


DEFAULT_MODEL, HARM_THRESHOLD, MISUSE_THRESHOLD = _configured_safety()


def _history_for_case(case: dict[str, object]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    previous = str(case.get("previous") or "")
    if previous:
        history.extend(
            [
                {"role": "user", "content": previous},
                {"role": "assistant", "content": "Earlier assistant response."},
            ]
        )
    history.append({"role": "user", "content": str(case["current"])})
    return history


def _preliminary_tool(case: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    instructions = yaml.safe_load(BASE_INSTRUCTIONS_PATH.read_text(encoding="utf-8"))
    is_follow_up = bool(case.get("previous"))
    tool_key = "preprocess_request_tool" if is_follow_up else "fast_preprocess_request_tool"
    tool = copy.deepcopy(instructions[tool_key])
    if is_follow_up:
        required = tool["function"]["parameters"]["required"]
        for field in ("topic_area", "topic_shift", "harmful_or_illegal", "misuse_risk", "output_language"):
            if field not in required:
                required.append(field)
    dynamic_context = {
        "TOPIC_AREAS_LIST": ["general_misc", "software_development", "health_wellness"],
        "AVAILABLE_APP_SKILLS": [],
        "AVAILABLE_FOCUS_MODES": [],
        "CURRENT_DATE_TIME": datetime.now(timezone.utc).isoformat(),
        "PREVIOUS_CATEGORY": "general_knowledge",
        "USER_SYSTEM_LANGUAGE": "en",
    }
    return tool, dynamic_context


async def _evaluate_case(
    case: dict[str, object],
    *,
    model_id: str,
    secrets_manager: SecretsManager,
) -> dict[str, object]:
    case_id = str(case["id"])
    expected = str(case["expected"])
    history = _history_for_case(case)
    tool, dynamic_context = _preliminary_tool(case)
    preliminary = await call_preprocessing_llm(
        task_id=f"request-safety-eval-{case_id}-preliminary",
        model_id=model_id,
        message_history=history,
        tool_definition=tool,
        secrets_manager=secrets_manager,
        dynamic_context=dynamic_context,
    )
    if preliminary.error_message or preliminary.arguments is None:
        return {
            "id": case_id,
            "path": "follow_up" if case.get("previous") else "first_message",
            "expected": expected,
            "actual": "preliminary_error",
            "passed": False,
            "status": "preliminary_error",
            "category": "none",
        }

    try:
        harmful_score = float(preliminary.arguments.get("harmful_or_illegal", 0))
        misuse_score = float(preliminary.arguments.get("misuse_risk", 0))
    except (TypeError, ValueError):
        harmful_score = 0.0
        misuse_score = 0.0

    candidate = needs_safety_confirmation(
        harmful_score,
        misuse_score,
        harm_threshold=HARM_THRESHOLD,
        misuse_threshold=MISUSE_THRESHOLD,
    )
    if candidate:
        confirmation = await confirm_chat_request_safety(
            message_history=history,
            task_id=f"request-safety-eval-{case_id}",
            model_id=model_id,
            secrets_manager=secrets_manager,
        )
        actual = confirmation.final_outcome
        status = confirmation.status
        category = confirmation.category
    else:
        actual = "allow"
        status = "below_candidate_threshold"
        category = "none"

    return {
        "id": case_id,
        "path": "follow_up" if case.get("previous") else "first_message",
        "expected": expected,
        "actual": actual,
        "passed": actual == expected,
        "status": status,
        "category": category,
        "harmful_score": harmful_score,
        "misuse_score": misuse_score,
        "confirmation_called": candidate,
    }


async def evaluate(model_id: str) -> tuple[dict[str, object], int]:
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    rows: list[dict[str, object]] = []
    try:
        for case in CHAT_REQUEST_SAFETY_CASES:
            rows.append(await _evaluate_case(
                case,
                model_id=model_id,
                secrets_manager=secrets_manager,
            ))
    finally:
        await secrets_manager.aclose()

    passed = sum(bool(row["passed"]) for row in rows)
    report: dict[str, object] = {
        "status": "pass" if passed == len(rows) else "fail",
        "corpus_version": CHAT_REQUEST_SAFETY_CORPUS_VERSION,
        "model": model_id,
        "passed": passed,
        "total": len(rows),
        "cases": rows,
    }
    return report, 0 if passed == len(rows) else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate allow-biased chat request safety")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    report, exit_code = await evaluate(args.model)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
