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
# Architecture context: See docs/architecture/e2e-test-mock-replay.md

import asyncio
import json
import logging
import os
import re
import time
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

    logger.info(
        f"[MOCK] Loaded fixture '{fixture_id}' "
        f"({len(data.get('stream_chunks', []))} chunks, "
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
    usage = fixture_data.get("usage", {})

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

    Everything downstream (billing preflight, postprocessing, persistence) still runs
    with the synthetic PreprocessingResult and aggregated response from the fixture.

    Args:
        fixture_id: ID of the fixture to replay
        task_id: Current Celery task ID (used as message_id for the AI response)
        request_data: The AskSkillRequest with user/chat context
        cache_service: CacheService for Redis pub/sub
        speed_override: Optional speed profile override (from marker)

    Returns:
        Dict containing:
            - preprocessing_result: Synthetic PreprocessingResult
            - aggregated_final_response: The full response text
            - thinking_content: List of thinking text chunks (if any)
            - main_processor_debug_metadata: Empty dict (no real processing)
            - revoked_in_consumer: False
            - soft_limited_in_consumer: False
    """
    fixture_data = load_fixture(fixture_id)
    preprocessing_result = build_preprocessing_result(fixture_data)

    # Determine streaming speed
    speed_profile = speed_override or fixture_data.get("speed_profile", DEFAULT_SPEED_PROFILE)
    chunk_delay = get_chunk_delay_seconds(speed_profile)

    logger.info(
        f"[MOCK] Replaying fixture '{fixture_id}' for task {task_id}, "
        f"speed_profile={speed_profile}, chunk_delay={chunk_delay}s"
    )

    # --- 1. Publish preprocessing step events ---
    await _publish_preprocessing_steps(
        fixture_data, task_id, request_data, cache_service
    )

    # --- 2. Publish ai_typing_started event ---
    await _publish_typing_started(
        fixture_data, task_id, request_data, cache_service, preprocessing_result
    )

    # --- 3. Publish skill execution events (interleaved with stream chunks) ---
    # Skills are published at the sequence numbers recorded in the fixture.
    skill_events_by_sequence = _build_skill_event_schedule(fixture_data)

    # --- 4. Publish ai_message_chunk events ---
    stream_chunks = fixture_data.get("stream_chunks", [])
    usage = fixture_data.get("usage", {})

    for i, chunk in enumerate(stream_chunks):
        sequence = chunk.get("sequence", i + 1)

        # Publish any skill events scheduled before or at this sequence number
        for seq_num in sorted(skill_events_by_sequence.keys()):
            if seq_num <= sequence:
                for skill_event in skill_events_by_sequence.pop(seq_num):
                    await _publish_skill_status(
                        skill_event, task_id, request_data, cache_service
                    )

        is_final = chunk.get("is_final", i == len(stream_chunks) - 1)

        payload = {
            "type": "ai_message_chunk",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "message_id": task_id,
            "user_message_id": request_data.message_id,
            "full_content_so_far": chunk.get("full_content_so_far", ""),
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

    # Publish any remaining skill events (after all stream chunks)
    for seq_num in sorted(skill_events_by_sequence.keys()):
        for skill_event in skill_events_by_sequence[seq_num]:
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

    final_response = fixture_data.get("final_response", "")
    logger.info(
        f"[MOCK] Fixture '{fixture_id}' replay complete. "
        f"Response length: {len(final_response)} chars, "
        f"{len(stream_chunks)} chunks published."
    )

    return {
        "preprocessing_result": preprocessing_result,
        "aggregated_final_response": final_response,
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
) -> Dict[int, List[Dict[str, Any]]]:
    """
    Build a mapping of stream sequence number → skill events to publish.

    Skill executions in the fixture have an optional 'at_sequence' field
    indicating when in the stream they should be published. Events without
    a sequence are published before streaming starts (sequence 0).
    """
    schedule: Dict[int, List[Dict[str, Any]]] = {}
    skill_executions = fixture_data.get("skill_executions", [])

    for skill_exec in skill_executions:
        status_updates = skill_exec.get("status_updates", [])
        app_id = skill_exec.get("app_id", "")
        skill_id = skill_exec.get("skill_id", "")

        for update in status_updates:
            seq = update.get("at_sequence", 0)
            event = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status": update.get("status", "finished"),
                "preview_data": update.get("preview_data", {}),
                "error": update.get("error"),
            }
            schedule.setdefault(seq, []).append(event)

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
