#!/usr/bin/env python3
"""Bounded matched utility-model evaluation using current OpenMates contracts.

This is an explicit paid diagnostic. It sends synthetic prompts only, attempts
each primary once with no fallback, and writes a local JSON receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.apps.ai.llm_providers import google_client, mistral_client
from backend.apps.ai.processing import postprocessor, preprocessor
from backend.apps.ai.processing.postprocessor import extract_available_skills
from backend.apps.ai.utils import llm_utils
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult, call_preprocessing_llm
from backend.core.api.app.services.skill_registry import build_skill_registry
from backend.core.api.app.utils.secrets_manager import SecretsManager


MODELS = (
    "google/gemini-3.5-flash-lite",
    "mistral/mistral-small-2506",
)
REQUIRED_ROUTING_FIELDS = (
    "topic_area",
    "topic_shift",
    "harmful_or_illegal",
    "misuse_risk",
    "output_language",
    "title",
    "icon_names",
)
ROUTING_CASES = (
    ("factual", "What is the capital of France?"),
    ("current_web", "Find today's official weather forecast for Berlin."),
    ("code_docs", "Look up the current Python pathlib documentation for globbing files."),
    ("image_generation", "Create a watercolor illustration of a red bicycle beside a canal."),
    ("safety", "Explain at a high level why phishing is harmful and how to recognize it."),
    ("german", "Erkläre mir kurz, warum der Himmel blau ist."),
)
METADATA_CASES = (
    (
        "factual_metadata",
        "What is the capital of France?",
        "Paris is the capital and largest city of France.",
    ),
    (
        "code_metadata",
        "How do I read a UTF-8 file in Python?",
        "Use pathlib.Path.read_text with encoding='utf-8', or open with that encoding.",
    ),
    (
        "german_metadata",
        "Warum ist der Himmel blau?",
        "Kurzwelliges blaues Licht wird in der Atmosphäre stärker gestreut.",
    ),
)

_TOKEN_PREP_SECONDS = 0.0


def _instrument_token_preparation() -> None:
    """Measure synchronous pre-HTTP token estimation in both provider clients."""
    def install(module: Any) -> None:
        original = module.calculate_token_breakdown

        def measured(*args: Any, **kwargs: Any) -> dict[str, int]:
            global _TOKEN_PREP_SECONDS
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                _TOKEN_PREP_SECONDS += time.perf_counter() - started

        module.calculate_token_breakdown = measured

    install(google_client)
    install(mistral_client)


def _catalogues(apps: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    skills: list[str] = []
    focuses: list[str] = []
    app_ids = sorted(apps)
    for app_id, app in apps.items():
        for skill in app.skills or []:
            if app_id == "ai" and skill.id == "ask":
                continue
            label = f"{app_id}-{skill.id}"
            skills.append(f"{label}: {skill.preprocessor_hint.strip()}" if skill.preprocessor_hint else label)
        for focus in app.focuses or []:
            label = f"{app_id}-{focus.id}"
            focuses.append(f"{label}: {focus.preprocessor_hint.strip()}" if focus.preprocessor_hint else label)
    return skills, focuses, app_ids


def _usage(summary: dict[str, Any] | None) -> tuple[int, int]:
    usage = (summary or {}).get("usage") or {}
    return (
        int(usage.get("prompt_token_count") or usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        int(usage.get("candidates_token_count") or usage.get("completion_tokens") or usage.get("output_tokens") or 0),
    )


async def _invoke(
    *,
    secrets: SecretsManager,
    model: str,
    task_id: str,
    messages: list[dict[str, str]],
    tool: dict[str, Any],
    dynamic_context: dict[str, Any] | None = None,
    purpose: str,
    required_fields: tuple[str, ...],
    cold: bool,
) -> dict[str, Any]:
    global _TOKEN_PREP_SECONDS
    _TOKEN_PREP_SECONDS = 0.0
    started = time.perf_counter()
    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=model,
        message_history=messages,
        tool_definition=tool,
        secrets_manager=secrets,
        dynamic_context=dynamic_context,
        fallback_models=[],
        allow_retries=False,
        observability_purpose=purpose,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    token_prep_ms = round(_TOKEN_PREP_SECONDS * 1000, 1)
    arguments = result.arguments or {}
    input_tokens, output_tokens = _usage(result.raw_provider_response_summary)
    missing = [field for field in required_fields if field not in arguments]
    return {
        "model": model,
        "cold_provider_call": cold,
        "elapsed_ms": elapsed_ms,
        "local_token_preparation_ms": token_prep_ms,
        "elapsed_excluding_local_token_preparation_ms": round(max(0.0, elapsed_ms - token_prep_ms), 1),
        "success": result.arguments is not None and not result.error_message,
        "error": result.error_message,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "required_fields_present": not missing,
        "missing_required_fields": missing,
        "routing": {
            key: arguments.get(key)
            for key in ("topic_area", "relevant_app_skills", "relevant_focus_modes", "output_language")
        },
    }


async def _capture_postprocess_contract(
    *,
    base: dict[str, Any],
    apps: dict[str, Any],
    user: str,
    assistant: str,
    case_id: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    captured: dict[str, Any] = {}
    original = postprocessor.call_preprocessing_llm

    async def capture(**kwargs: Any) -> LLMPreprocessingCallResult:
        captured.update(kwargs)
        return LLMPreprocessingCallResult(error_message="contract captured")

    postprocessor.call_preprocessing_llm = capture
    try:
        await postprocessor.handle_postprocessing(
            task_id=f"capture-{case_id}",
            user_message=user,
            assistant_response=assistant,
            chat_summary=None,
            chat_tags=[],
            message_history=[{"role": "user", "content": user}],
            base_instructions=base,
            secrets_manager=None,  # capture returns before credentials are used
            cache_service=None,
            available_app_ids=sorted(apps),
            available_skills=extract_available_skills(apps),
            output_language="de" if case_id.startswith("german") else "en",
            user_system_language="de" if case_id.startswith("german") else "en",
            current_chat_title=None,
        )
    finally:
        postprocessor.call_preprocessing_llm = original
    return captured["message_history"], captured["tool_definition"]


async def run(
    output: Path,
    *,
    routing_models: tuple[str, ...] = MODELS,
    routing_case_ids: set[str] | None = None,
    skip_metadata: bool = False,
    apply_mistral_fix: bool = False,
    prewarm_tokenizers: bool = False,
) -> dict[str, Any]:
    # One provider request gets the complete foreground budget. No fallback means
    # there is no reason to reserve a fraction for another provider.
    llm_utils.PREPROCESSING_TIMEOUT_SECONDS = 12.0
    llm_utils.PREPROCESSING_TOTAL_TIMEOUT_SECONDS = 12.0
    _instrument_token_preparation()
    if prewarm_tokenizers:
        import tiktoken

        tiktoken.get_encoding("o200k_base")
        tiktoken.get_encoding("cl100k_base")
    if apply_mistral_fix:
        original_mistral = llm_utils.PROVIDER_CLIENT_REGISTRY["mistral"]

        async def fixed_mistral(**kwargs: Any) -> Any:
            tools = kwargs.get("tools") or []
            if kwargs.get("tool_choice") == "required" and len(tools) == 1:
                name = tools[0].get("function", {}).get("name")
                if name:
                    kwargs["tool_choice"] = {"type": "function", "function": {"name": name}}
            return await original_mistral(**kwargs)

        llm_utils.PROVIDER_CLIENT_REGISTRY["mistral"] = fixed_mistral

    _, apps = build_skill_registry()
    skills, focuses, app_ids = _catalogues(apps)
    base = load_base_instructions()
    routing_tool = copy.deepcopy(base["preprocess_request_tool"])
    required = routing_tool["function"]["parameters"].setdefault("required", [])
    for field in REQUIRED_ROUTING_FIELDS:
        if field not in required:
            required.append(field)
    dynamic_context = {
        "TOPIC_AREAS_LIST": preprocessor._build_topic_areas_list(),
        "AVAILABLE_APP_SKILLS": skills,
        "AVAILABLE_FOCUS_MODES": focuses,
        "RECENT_SKILL_ACTIVITY": "- None recorded",
        "CURRENT_DATE_TIME": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "USER_SYSTEM_LANGUAGE": "en",
        "PREVIOUS_CATEGORY": "none (first message or unknown)",
    }

    secrets = SecretsManager()
    await secrets.initialize()
    rows: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for case_index, (case_id, prompt) in enumerate(ROUTING_CASES):
        if routing_case_ids is not None and case_id not in routing_case_ids:
            continue
        order = routing_models if case_index % 2 == 0 else tuple(reversed(routing_models))
        for model in order:
            row = await _invoke(
                secrets=secrets,
                model=model,
                task_id=f"utility-routing-{case_id}-{model.split('/')[0]}",
                messages=[{"role": "user", "content": prompt}],
                tool=copy.deepcopy(routing_tool),
                dynamic_context={**dynamic_context, "USER_SYSTEM_LANGUAGE": "de" if case_id == "german" else "en"},
                purpose="preprocess",
                required_fields=REQUIRED_ROUTING_FIELDS,
                cold=model not in seen_models,
            )
            seen_models.add(model)
            rows.append({"phase": "routing", "case": case_id, **row})

    for case_index, (case_id, user, assistant) in enumerate(() if skip_metadata else METADATA_CASES):
        messages, tool = await _capture_postprocess_contract(
            base=base, apps=apps, user=user, assistant=assistant, case_id=case_id
        )
        required_metadata = tuple(tool["function"]["parameters"].get("required", []))
        order = MODELS if case_index % 2 == 1 else tuple(reversed(MODELS))
        for model in order:
            row = await _invoke(
                secrets=secrets,
                model=model,
                task_id=f"utility-metadata-{case_id}-{model.split('/')[0]}",
                messages=messages,
                tool=tool,
                purpose="postprocess",
                required_fields=required_metadata,
                cold=False,
            )
            rows.append({"phase": "metadata", "case": case_id, **row})

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "constraints": {"fallbacks": False, "attempts_per_case_model": 1, "timeout_seconds": 12},
        "contract": {
            "discovered_apps": len(app_ids),
            "expanded_skills": len(skills),
            "expanded_focus_modes": len(focuses),
            "routing_schema_chars": len(json.dumps(routing_tool, separators=(",", ":"))),
        },
        "rows": rows,
    }
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/utility-model-evaluation.json"))
    parser.add_argument("--routing-model", action="append", choices=MODELS)
    parser.add_argument("--routing-case", action="append", choices=[case[0] for case in ROUTING_CASES])
    parser.add_argument("--skip-metadata", action="store_true")
    parser.add_argument("--apply-mistral-fix", action="store_true")
    parser.add_argument("--prewarm-tokenizers", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    result = asyncio.run(
        run(
            args.output,
            routing_models=tuple(args.routing_model or MODELS),
            routing_case_ids=set(args.routing_case) if args.routing_case else None,
            skip_metadata=args.skip_metadata,
            apply_mistral_fix=args.apply_mistral_fix,
            prewarm_tokenizers=args.prewarm_tokenizers,
        )
    )
    print(json.dumps({"output": str(args.output), "rows": len(result["rows"]), "contract": result["contract"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
