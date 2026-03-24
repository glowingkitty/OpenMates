# backend/apps/ai/testing/mock_replay.py
# Marker detection, fixture loading, and Redis stream replay for E2E test mocking.
#
# When a user message contains <<<TEST_MOCK:fixture_id>>> or <<<TEST_MOCK:fixture_id:speed>>>,
# the Celery task skips real LLM inference and skill API calls, replaying pre-recorded
# fixture data through the same Redis pub/sub channels. Everything else (WebSocket,
# encryption, billing preflight, postprocessing, persistence) remains real.
#
# Security: All functions return None / no-op when SERVER_ENVIRONMENT == "production".
#
# Architecture context: See docs/contributing/guides/testing.md ("E2E Mock/Replay System")

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

# Directory where fixture JSON files are stored
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Regex to detect mock/record markers in message text.
# Formats:
#   <<<TEST_MOCK:fixture_id>>>                 — replay fixture with its default speed
#   <<<TEST_MOCK:fixture_id:speed_profile>>>   — replay with speed override
#   <<<TEST_RECORD:fixture_id>>>               — record real response to fixture file
_MARKER_PATTERN = re.compile(
    r"<<<TEST_(MOCK|RECORD):([a-zA-Z0-9_-]+)(?::([a-zA-Z0-9_]+))?\s*>>>"
)

# Speed profiles: maps profile name to inter-chunk delay in milliseconds
SPEED_PROFILES = {
    "slow": 50,      # ~60 tokens/s (e.g., Claude Opus thinking)
    "medium": 20,    # ~150 tokens/s (e.g., GPT-4o, Claude Sonnet)
    "fast": 5,       # ~500 tokens/s (e.g., Cerebras, Groq)
    "instant": 0,    # No delay — fastest test execution
}

DEFAULT_SPEED_PROFILE = "instant"


def detect_marker(content: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Detect a TEST_MOCK or TEST_RECORD marker in message content.

    Returns:
        Tuple of (mode, fixture_id, speed_override) where:
            mode: "mock" or "record"
            fixture_id: identifier for the fixture file
            speed_override: optional speed profile override (only for mock mode)
        Returns None if no marker found or if running in production.
    """
    # SECURITY: Never honor markers in production
    if os.getenv("SERVER_ENVIRONMENT", "production") == "production":
        return None

    match = _MARKER_PATTERN.search(content)
    if not match:
        return None

    mode = match.group(1).lower()  # "mock" or "record"
    fixture_id = match.group(2)
    speed_override = match.group(3)  # None if not provided

    return (mode, fixture_id, speed_override)


def strip_marker(content: str) -> str:
    """Remove the TEST_MOCK/TEST_RECORD marker from message content."""
    return _MARKER_PATTERN.sub("", content).rstrip()


def get_chunk_delay_seconds(speed_profile: Optional[str]) -> float:
    """
    Convert a speed profile name to inter-chunk delay in seconds.

    Args:
        speed_profile: One of "slow", "medium", "fast", "instant", or None.
                       Falls back to DEFAULT_SPEED_PROFILE if None or unknown.

    Returns:
        Delay in seconds between streaming chunks.
    """
    if speed_profile and speed_profile in SPEED_PROFILES:
        return SPEED_PROFILES[speed_profile] / 1000.0
    return SPEED_PROFILES[DEFAULT_SPEED_PROFILE] / 1000.0


def load_fixture(fixture_id: str) -> Dict[str, Any]:
    """
    Load a fixture JSON file by its ID.

    Args:
        fixture_id: The fixture identifier (maps to fixtures/{fixture_id}.json)

    Returns:
        Parsed fixture data.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
        json.JSONDecodeError: If the fixture file is not valid JSON.
    """
    fixture_path = FIXTURES_DIR / f"{fixture_id}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"Test fixture not found: {fixture_path}. "
            f"Record it first with <<<TEST_RECORD:{fixture_id}>>> or create it manually."
        )

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    response = data.get("response") or data.get("final_response", "")
    logger.info(
        f"[MOCK] Loaded fixture '{fixture_id}' "
        f"(response={len(response)} chars, "
        f"{len(data.get('skill_executions', []))} skill executions)"
    )
    return data


def build_preprocessing_result(fixture_data: Dict[str, Any]) -> PreprocessingResult:
    """
    Build a synthetic PreprocessingResult from fixture data.

    The PreprocessingResult is needed by billing preflight validation and postprocessing.
    It contains the model selection, category, title, etc. from the original recorded response.
    """
    preprocessing = fixture_data.get("preprocessing", {})

    return PreprocessingResult(
        can_proceed=preprocessing.get("can_proceed", True),
        category=preprocessing.get("category", "general_knowledge"),
        title=preprocessing.get("title"),
        icon_names=preprocessing.get("icon_names"),
        selected_mate_id=preprocessing.get("mate_id", "default"),
        selected_main_llm_model_id=preprocessing.get("selected_model_id"),
        selected_main_llm_model_name=preprocessing.get("selected_model_name"),
        chat_summary=preprocessing.get("chat_summary"),
        chat_tags=preprocessing.get("chat_tags", []),
        relevant_app_skills=preprocessing.get("relevant_app_skills", []),
        llm_response_temp=preprocessing.get("llm_response_temp"),
        complexity=preprocessing.get("complexity"),
    )


def _split_response_into_chunks(response: str) -> List[str]:
    """
    Split a full response into progressive cumulative chunk strings.

    Returns a list where each entry is the response content up to that point
    (i.e., response[:boundary]). The last entry is always the full response.

    Splits at paragraph breaks (\\n\\n), then sentence ends (. ),
    falling back to ~80-char word boundaries for long runs without punctuation.
    """
    if not response:
        return [response] if response == "" else []

    boundaries: List[int] = []
    pos = 0

    while pos < len(response):
        # Look for next paragraph break
        para_idx = response.find("\n\n", pos)
        if para_idx != -1 and para_idx < pos + 200:
            boundaries.append(para_idx + 2)
            pos = para_idx + 2
            continue

        # Look for next sentence end
        sent_idx = response.find(". ", pos)
        if sent_idx != -1 and sent_idx < pos + 200:
            boundaries.append(sent_idx + 2)
            pos = sent_idx + 2
            continue

        # Fallback: word boundary around ~80 chars
        target = pos + 80
        if target >= len(response):
            break
        space_idx = response.find(" ", target)
        if space_idx != -1:
            boundaries.append(space_idx + 1)
            pos = space_idx + 1
        else:
            break

    # Build cumulative chunks from boundaries
    chunks = [response[:b] for b in boundaries]

    # Always end with the full response
    if not chunks or chunks[-1] != response:
        chunks.append(response)

    return chunks


async def replay_fixture(
    fixture_id: str,
    task_id: str,
    request_data: AskSkillRequest,
    cache_service: CacheService,
    speed_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Replay a recorded fixture through Redis pub/sub channels.

    Publishes the same events that real LLM processing would produce:
    1. Preprocessing step events
    2. ai_typing_started event
    3. ai_message_chunk events (with configurable streaming speed)
    4. Skill execution status events (if any)

    The fixture stores only the full response text. Chunks are generated at replay
    time by splitting at sentence/paragraph boundaries.

    Everything downstream (billing preflight, postprocessing, persistence) still runs
    with the synthetic PreprocessingResult and aggregated response from the fixture.
    """
    fixture_data = load_fixture(fixture_id)
    preprocessing_result = build_preprocessing_result(fixture_data)

    # Determine streaming speed
    speed_profile = speed_override or fixture_data.get("speed_profile", DEFAULT_SPEED_PROFILE)
    chunk_delay = get_chunk_delay_seconds(speed_profile)

    # Get the full response text (support both new "response" and legacy "final_response" fields)
    full_response = fixture_data.get("response") or fixture_data.get("final_response", "")

    logger.info(
        f"[MOCK] Replaying fixture '{fixture_id}' for task {task_id}, "
        f"speed_profile={speed_profile}, chunk_delay={chunk_delay}s, "
        f"response_len={len(full_response)}"
    )

    # --- 1. Publish preprocessing step events ---
    await _publish_preprocessing_steps(
        fixture_data, task_id, request_data, cache_service
    )

    # --- 2. Publish ai_typing_started event ---
    await _publish_typing_started(
        fixture_data, task_id, request_data, cache_service, preprocessing_result
    )

    # --- 3. Build skill event schedule ---
    skill_events_by_fraction = _build_skill_event_schedule(fixture_data)

    # --- 4. Generate chunks and publish ai_message_chunk events ---
    # Support legacy fixtures that still have stream_chunks
    legacy_chunks = fixture_data.get("stream_chunks", [])
    if legacy_chunks:
        cumulative_chunks = [c.get("full_content_so_far", "") for c in legacy_chunks]
    else:
        cumulative_chunks = _split_response_into_chunks(full_response)

    usage = fixture_data.get("usage", {})
    total_chunks = len(cumulative_chunks)

    for i, content_so_far in enumerate(cumulative_chunks):
        sequence = i + 1
        is_final = (i == total_chunks - 1)
        fraction = (i + 1) / total_chunks if total_chunks > 0 else 1.0

        # Publish any skill events scheduled at or before this fraction
        for frac_threshold in sorted(list(skill_events_by_fraction.keys())):
            if frac_threshold <= fraction:
                for skill_event in skill_events_by_fraction.pop(frac_threshold):
                    await _publish_skill_status(
                        skill_event, task_id, request_data, cache_service
                    )

        payload: Dict[str, Any] = {
            "type": "ai_message_chunk",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "message_id": task_id,
            "user_message_id": request_data.message_id,
            "full_content_so_far": content_so_far if not is_final else full_response,
            "sequence": sequence,
            "is_final_chunk": is_final,
            "external_request": request_data.is_external,
        }

        # Add model info
        model_name = usage.get("model_name") or preprocessing_result.selected_main_llm_model_name
        if model_name:
            payload["model_name"] = model_name

        category = preprocessing_result.category
        if category:
            payload["category"] = category

        # Add usage data on final chunk
        if is_final:
            payload["interrupted_by_soft_limit"] = False
            payload["interrupted_by_revocation"] = False
            if usage.get("prompt_tokens") is not None:
                payload["prompt_tokens"] = usage["prompt_tokens"]
            if usage.get("completion_tokens") is not None:
                payload["completion_tokens"] = usage["completion_tokens"]
            if usage.get("total_credits") is not None:
                payload["total_credits"] = usage["total_credits"]

        # Publish chunk to Redis
        channel = f"chat_stream::{request_data.chat_id}"
        await cache_service.publish_event(channel, payload)

        # Simulate streaming delay between chunks (not after the last one)
        if not is_final and chunk_delay > 0:
            await asyncio.sleep(chunk_delay)

    # Publish any remaining skill events
    for frac in sorted(skill_events_by_fraction.keys()):
        for skill_event in skill_events_by_fraction[frac]:
            await _publish_skill_status(
                skill_event, task_id, request_data, cache_service
            )

    # --- 5. Publish thinking content (if any) ---
    thinking_content_text = fixture_data.get("thinking_content")
    thinking_content_list: List[str] = []
    if thinking_content_text:
        thinking_content_list = [thinking_content_text]
        thinking_payload = {
            "type": "thinking_content",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "thinking_content": thinking_content_text,
            "is_complete": True,
        }
        thinking_channel = f"chat_stream_thinking::{request_data.chat_id}"
        await cache_service.publish_event(thinking_channel, thinking_payload)

    logger.info(
        f"[MOCK] Fixture '{fixture_id}' replay complete. "
        f"Response length: {len(full_response)} chars, "
        f"{total_chunks} chunks published."
    )

    return {
        "preprocessing_result": preprocessing_result,
        "aggregated_final_response": full_response,
        "thinking_content": thinking_content_list,
        "main_processor_debug_metadata": {"mocked": True, "fixture_id": fixture_id},
        "revoked_in_consumer": False,
        "soft_limited_in_consumer": False,
    }


# --- Internal helpers ---


async def _publish_preprocessing_steps(
    fixture_data: Dict[str, Any],
    task_id: str,
    request_data: AskSkillRequest,
    cache_service: CacheService,
) -> None:
    """Publish preprocessing step events to the preprocessing stream channel."""
    if request_data.is_external:
        return  # No preprocessing events for REST API requests

    preprocessing = fixture_data.get("preprocessing", {})
    steps = preprocessing.get("steps", [])
    channel = f"preprocessing_stream::{request_data.user_id_hash}"

    for step in steps:
        step_payload = {
            "type": "preprocessing_step_result",
            "event_for_client": "preprocessing_step_result",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "step": step.get("step"),
            "data": step.get("data", {}),
            "skipped": step.get("skipped", False),
        }
        await cache_service.publish_event(channel, step_payload)

    if steps:
        logger.debug(
            f"[MOCK] Published {len(steps)} preprocessing steps for task {task_id}"
        )


async def _publish_typing_started(
    fixture_data: Dict[str, Any],
    task_id: str,
    request_data: AskSkillRequest,
    cache_service: CacheService,
    preprocessing_result: PreprocessingResult,
) -> None:
    """Publish the ai_typing_started event."""
    if request_data.is_external:
        return  # No typing indicator for REST API requests

    typing_data = fixture_data.get("typing_started", {})
    preprocessing = fixture_data.get("preprocessing", {})

    typing_payload = {
        "type": "ai_processing_started_event",
        "event_for_client": "ai_typing_started",
        "task_id": task_id,
        "chat_id": request_data.chat_id,
        "user_id_uuid": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "user_message_id": request_data.message_id,
        "category": typing_data.get("category") or preprocessing_result.category or "general_knowledge",
        "model_name": typing_data.get("model_name") or preprocessing_result.selected_main_llm_model_name,
        "provider_name": typing_data.get("provider_name", "Mock"),
        "server_region": typing_data.get("server_region"),
        "is_continuation": request_data.is_app_settings_memories_continuation or request_data.is_focus_mode_continuation,
    }

    # Include title and icon_names for new chats (only when both are present)
    title = preprocessing.get("title") or preprocessing_result.title
    icon_names = preprocessing.get("icon_names") or preprocessing_result.icon_names
    if title and icon_names:
        typing_payload["title"] = title
        typing_payload["icon_names"] = icon_names

    channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
    await cache_service.publish_event(channel, typing_payload)
    logger.debug(f"[MOCK] Published ai_typing_started for task {task_id}")


def _build_skill_event_schedule(
    fixture_data: Dict[str, Any],
) -> Dict[float, List[Dict[str, Any]]]:
    """
    Build a mapping of chunk fraction → skill events to publish.

    Skill executions in the fixture have an optional 'at_fraction' field (0.0-1.0)
    indicating when during streaming they should be published. Events without a
    fraction are published before streaming starts (fraction 0.0).

    Also supports legacy 'at_sequence' (converted to fraction 0.0 for simplicity).
    """
    schedule: Dict[float, List[Dict[str, Any]]] = {}
    skill_executions = fixture_data.get("skill_executions", [])

    for skill_exec in skill_executions:
        status_updates = skill_exec.get("status_updates", [])
        app_id = skill_exec.get("app_id", "")
        skill_id = skill_exec.get("skill_id", "")

        for update in status_updates:
            # Support new at_fraction and legacy at_sequence
            fraction = update.get("at_fraction", 0.0)
            if "at_sequence" in update and "at_fraction" not in update:
                fraction = 0.0  # Legacy: publish at start
            event = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status": update.get("status", "finished"),
                "preview_data": update.get("preview_data", {}),
                "error": update.get("error"),
            }
            schedule.setdefault(fraction, []).append(event)

    return schedule


async def _publish_skill_status(
    skill_event: Dict[str, Any],
    task_id: str,
    request_data: AskSkillRequest,
    cache_service: CacheService,
) -> None:
    """Publish a single skill execution status event."""
    if request_data.is_external:
        return  # No skill status events for REST API requests

    payload = {
        "type": "skill_execution_status",
        "event_for_client": "skill_execution_status",
        "task_id": task_id,
        "chat_id": request_data.chat_id,
        "message_id": request_data.message_id,
        "user_id_uuid": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "app_id": skill_event["app_id"],
        "skill_id": skill_event["skill_id"],
        "status": skill_event["status"],
        "preview_data": skill_event.get("preview_data", {}),
    }

    if skill_event.get("error"):
        payload["error"] = skill_event["error"]

    channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
    await cache_service.publish_event(channel, payload)
    logger.debug(
        f"[MOCK] Published skill status '{skill_event['status']}' "
        f"for {skill_event['app_id']}.{skill_event['skill_id']}"
    )
