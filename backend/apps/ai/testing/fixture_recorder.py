# backend/apps/ai/testing/fixture_recorder.py
# Records real LLM responses and skill outputs as fixture files for E2E test mocking.
#
# When a user message contains <<<TEST_RECORD:fixture_id>>>, the Celery task runs
# normally (real LLM + real skills). After the task completes, the recorder saves
# the full response and metadata as a fixture JSON file that can later be replayed
# with <<<TEST_MOCK:fixture_id>>>.
#
# Fixtures store only the full response text — chunks are generated at replay time
# by splitting at sentence/paragraph boundaries. This keeps fixtures small and
# human-editable.
#
# Security: Only works when SERVER_ENVIRONMENT != "production".
#
# Architecture context: See docs/claude/testing-ref.md ("E2E Mock/Replay System")

import json
import logging
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
    Records data during a real LLM task execution for later mock replay.

    Captures preprocessing results, typing metadata, the full response text,
    skill executions, and usage data. Saves as a compact JSON fixture.

    Usage (in ask_skill_task.py):
        recorder = FixtureRecorder(fixture_id, request_data)
        recorder.record_preprocessing(preprocessing_result)
        recorder.record_typing_started(category, model_name, ...)
        recorder.record_skill_execution(app_id, skill_id, status, preview_data)
        recorder.record_usage(prompt_tokens, completion_tokens, ...)
        recorder.set_response(aggregated_final_response)
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
                    self.user_message_snippet = msg.content[:200]
                    break

        # Collected data
        self.preprocessing_data: Dict[str, Any] = {}
        self.typing_started_data: Dict[str, Any] = {}
        self.skill_executions: Dict[str, Dict[str, Any]] = {}  # keyed by "app_id.skill_id"
        self.usage_data: Dict[str, Any] = {}
        self.thinking_content: Optional[str] = None
        self.response: str = ""

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

    def record_skill_execution(
        self,
        app_id: str,
        skill_id: str,
        status: str,
        preview_data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        at_fraction: Optional[float] = None,
    ) -> None:
        """
        Record a skill execution status update.

        Args:
            app_id: The app ID (e.g., "web")
            skill_id: The skill ID (e.g., "search")
            status: Status ("processing", "finished", "error")
            preview_data: Skill-specific preview data
            error: Error message if status is "error"
            at_fraction: When during streaming this event should fire (0.0-1.0).
                         E.g., 0.3 = after 30% of chunks have been sent.
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
        if at_fraction is not None:
            update["at_fraction"] = at_fraction

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

    def set_response(self, response: str) -> None:
        """Set the full aggregated response text."""
        self.response = response

    def save(self) -> Path:
        """
        Save the recorded data as a fixture JSON file.

        Returns:
            Path to the saved fixture file.
        """
        fixture = {
            "fixture_id": self.fixture_id,
            "recorded_at": self.recorded_at,
            "speed_profile": "instant",
            "user_message_snippet": self.user_message_snippet,
            "preprocessing": self.preprocessing_data,
            "typing_started": self.typing_started_data,
            "response": self.response,
            "skill_executions": list(self.skill_executions.values()),
            "thinking_content": self.thinking_content,
            "usage": self.usage_data,
        }

        # Ensure fixtures directory exists
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

        fixture_path = FIXTURES_DIR / f"{self.fixture_id}.json"
        with open(fixture_path, "w", encoding="utf-8") as f:
            json.dump(fixture, f, indent=2, ensure_ascii=False)

        logger.info(
            f"[RECORD] Saved fixture '{self.fixture_id}' to {fixture_path} "
            f"(response={len(self.response)} chars, "
            f"{len(self.skill_executions)} skill executions)"
        )
        return fixture_path
