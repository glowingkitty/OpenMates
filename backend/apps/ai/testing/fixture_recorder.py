# backend/apps/ai/testing/fixture_recorder.py
# Records real LLM responses and skill outputs as fixture files for E2E test mocking.
#
# When a user message contains <<<TEST_RECORD:fixture_id>>>, the Celery task runs
# normally (real LLM + real skills) but wraps the Redis publish calls to capture
# every event. After the task completes, the recorder serializes everything to a
# fixture JSON file that can later be replayed with <<<TEST_MOCK:fixture_id>>>.
#
# Security: Only works when SERVER_ENVIRONMENT != "production".
#
# Architecture context: See docs/architecture/e2e-test-mock-replay.md

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.apps.ai.processing.preprocessor import PreprocessingResult
from backend.apps.ai.skills.ask_skill import AskSkillRequest

logger = logging.getLogger(__name__)

# Directory where fixture JSON files are stored
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FixtureRecorder:
    """
    Records Redis events published during a real LLM task execution.

    Usage (in ask_skill_task.py):
        recorder = FixtureRecorder(fixture_id, request_data)
        # ... run normal processing ...
        recorder.record_preprocessing(preprocessing_result)
        recorder.record_stream_chunk(sequence, full_content_so_far, is_final)
        recorder.record_skill_execution(app_id, skill_id, status, preview_data, at_sequence)
        recorder.record_usage(prompt_tokens, completion_tokens, ...)
        recorder.save()
    """

    def __init__(self, fixture_id: str, request_data: AskSkillRequest) -> None:
        self.fixture_id = fixture_id
        self.recorded_at = datetime.now(timezone.utc).isoformat()

        # Extract the last user message for reference
        self.user_message_snippet = ""
        if request_data.message_history:
            for msg in reversed(request_data.message_history):
                if msg.role == "user":
                    # Truncate to first 200 chars for the fixture
                    self.user_message_snippet = msg.content[:200]
                    break

        # Collected data
        self.preprocessing_data: Dict[str, Any] = {}
        self.typing_started_data: Dict[str, Any] = {}
        self.stream_chunks: List[Dict[str, Any]] = []
        self.chunk_timestamps_ms: List[int] = []
        self.skill_executions: Dict[str, Dict[str, Any]] = {}  # keyed by "app_id.skill_id"
        self.usage_data: Dict[str, Any] = {}
        self.thinking_content: Optional[str] = None
        self.final_response: str = ""

        self._first_chunk_time: Optional[float] = None

        logger.info(f"[RECORD] FixtureRecorder initialized for fixture '{fixture_id}'")

    def record_preprocessing(self, result: PreprocessingResult) -> None:
        """Record preprocessing result data."""
        self.preprocessing_data = {
            "can_proceed": result.can_proceed,
            "category": result.category,
            "title": result.title,
            "icon_names": result.icon_names,
            "selected_model_id": result.selected_main_llm_model_id,
            "selected_model_name": result.selected_main_llm_model_name,
            "mate_id": result.selected_mate_id,
            "chat_summary": result.chat_summary,
            "chat_tags": result.chat_tags,
            "relevant_app_skills": result.relevant_app_skills,
            "llm_response_temp": result.llm_response_temp,
            "complexity": result.complexity,
            "steps": [],  # Will be populated by record_preprocessing_step
        }

    def record_preprocessing_step(
        self, step: str, data: Dict[str, Any], skipped: bool = False
    ) -> None:
        """Record a single preprocessing step event."""
        if "steps" not in self.preprocessing_data:
            self.preprocessing_data["steps"] = []
        self.preprocessing_data["steps"].append({
            "step": step,
            "data": data,
            "skipped": skipped,
        })

    def record_typing_started(
        self,
        category: Optional[str] = None,
        model_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        server_region: Optional[str] = None,
        icon_names: Optional[List[str]] = None,
    ) -> None:
        """Record the ai_typing_started event data."""
        self.typing_started_data = {
            "category": category,
            "model_name": model_name,
            "provider_name": provider_name,
            "server_region": server_region,
        }
        if icon_names:
            self.typing_started_data["icon_names"] = icon_names

    def record_stream_chunk(
        self,
        sequence: int,
        full_content_so_far: str,
        is_final: bool = False,
    ) -> None:
        """
        Record a single streaming chunk.

        Also captures inter-chunk timing for realistic speed replay.
        """
        now = time.monotonic()
        if self._first_chunk_time is None:
            self._first_chunk_time = now

        elapsed_ms = int((now - self._first_chunk_time) * 1000)
        self.chunk_timestamps_ms.append(elapsed_ms)

        chunk_data: Dict[str, Any] = {
            "sequence": sequence,
            "full_content_so_far": full_content_so_far,
        }
        if is_final:
            chunk_data["is_final"] = True
            self.final_response = full_content_so_far

        self.stream_chunks.append(chunk_data)

    def record_skill_execution(
        self,
        app_id: str,
        skill_id: str,
        status: str,
        preview_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        at_sequence: Optional[int] = None,
    ) -> None:
        """
        Record a skill execution status update.

        Args:
            app_id: The app ID (e.g., "web")
            skill_id: The skill ID (e.g., "search")
            status: Status ("processing", "finished", "error")
            preview_data: Skill-specific preview data
            error: Error message if status is "error"
            at_sequence: Stream chunk sequence number when this event was published.
                         Used during replay to interleave skill events with stream chunks.
        """
        key = f"{app_id}.{skill_id}"

        if key not in self.skill_executions:
            self.skill_executions[key] = {
                "app_id": app_id,
                "skill_id": skill_id,
                "status_updates": [],
            }

        update: Dict[str, Any] = {"status": status}
        if preview_data:
            update["preview_data"] = preview_data
        if error:
            update["error"] = error
        if at_sequence is not None:
            update["at_sequence"] = at_sequence

        self.skill_executions[key]["status_updates"].append(update)

    def record_usage(
        self,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_credits: Optional[int] = None,
        model_name: Optional[str] = None,
    ) -> None:
        """Record token usage and billing data."""
        self.usage_data = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_credits": total_credits,
            "model_name": model_name,
        }

    def record_thinking_content(self, content: str) -> None:
        """Record thinking/reasoning content from thinking models."""
        self.thinking_content = content

    def save(self) -> Path:
        """
        Save the recorded data as a fixture JSON file.

        Returns:
            Path to the saved fixture file.
        """
        # Infer speed profile from actual chunk timing
        inferred_speed = self._infer_speed_profile()

        fixture = {
            "fixture_id": self.fixture_id,
            "recorded_at": self.recorded_at,
            "speed_profile": inferred_speed,
            "recorded_chunk_timestamps_ms": self.chunk_timestamps_ms,
            "user_message_snippet": self.user_message_snippet,
            "preprocessing": self.preprocessing_data,
            "typing_started": self.typing_started_data,
            "stream_chunks": self.stream_chunks,
            "skill_executions": list(self.skill_executions.values()),
            "thinking_content": self.thinking_content,
            "usage": self.usage_data,
            "final_response": self.final_response,
        }

        # Ensure fixtures directory exists
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

        fixture_path = FIXTURES_DIR / f"{self.fixture_id}.json"
        with open(fixture_path, "w", encoding="utf-8") as f:
            json.dump(fixture, f, indent=2, ensure_ascii=False)

        logger.info(
            f"[RECORD] Saved fixture '{self.fixture_id}' to {fixture_path} "
            f"({len(self.stream_chunks)} chunks, "
            f"{len(self.skill_executions)} skill executions, "
            f"inferred_speed={inferred_speed})"
        )
        return fixture_path

    def generate_chunks_from_response(self, full_response: str) -> None:
        """
        Generate synthetic stream chunks from the aggregated final response.

        If no chunks were recorded via record_stream_chunk() (e.g., because we
        couldn't hook into stream_consumer.py), this creates approximate chunks
        by splitting the response at word boundaries.

        The exact chunking doesn't matter for replay — speed profiles control
        the pacing. What matters is that the content builds up progressively.
        """
        if self.stream_chunks:
            # Chunks were already recorded directly — use those
            # Just ensure the final_response is set
            if not self.final_response and self.stream_chunks:
                last_chunk = self.stream_chunks[-1]
                self.final_response = last_chunk.get("full_content_so_far", "")
            return

        if not full_response:
            return

        self.final_response = full_response

        # Split into ~20-50 chunks at word boundaries
        words = full_response.split(" ")
        target_chunks = min(max(len(words) // 3, 5), 50)
        words_per_chunk = max(1, len(words) // target_chunks)

        for i in range(0, len(words), words_per_chunk):
            chunk_words = words[: i + words_per_chunk]
            content_so_far = " ".join(chunk_words)
            is_final = (i + words_per_chunk) >= len(words)

            chunk_data: Dict[str, Any] = {
                "sequence": len(self.stream_chunks) + 1,
                "full_content_so_far": content_so_far,
            }
            if is_final:
                chunk_data["is_final"] = True
                chunk_data["full_content_so_far"] = full_response  # Ensure exact final content

            self.stream_chunks.append(chunk_data)

        # Generate synthetic timestamps (evenly spaced)
        self.chunk_timestamps_ms = [
            i * 20 for i in range(len(self.stream_chunks))
        ]

    def _infer_speed_profile(self) -> str:
        """
        Infer the closest speed profile from actual inter-chunk timings.

        Calculates the median inter-chunk delay and maps it to the closest
        named speed profile.
        """
        if len(self.chunk_timestamps_ms) < 2:
            return "medium"  # Not enough data, default to medium

        # Calculate inter-chunk delays
        delays = [
            self.chunk_timestamps_ms[i] - self.chunk_timestamps_ms[i - 1]
            for i in range(1, len(self.chunk_timestamps_ms))
        ]
        delays.sort()
        median_delay = delays[len(delays) // 2]

        # Map to closest profile
        if median_delay <= 2:
            return "instant"
        elif median_delay <= 10:
            return "fast"
        elif median_delay <= 35:
            return "medium"
        else:
            return "slow"
