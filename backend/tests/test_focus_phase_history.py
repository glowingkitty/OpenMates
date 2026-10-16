# contract-test-file: supporting surface=rest_api assertions=focus-modes.full-instruction,focus-modes.history-events
"""Phase transition notices remain stored but do not become model instructions."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.apps.ai.processing.focus_phase_history import filter_focus_phase_history


CHAT_ID = str(uuid4())


def _event(**changes: object) -> str:
    event = {
        "type": "focus_phase_changed",
        "event_id": str(uuid4()),
        "chat_id": CHAT_ID,
        "focus_id": "jobs-career_insights",
        "run_id": str(uuid4()),
        "version": 2,
        "created_at": 1791124238,
        "previous_phase_id": "confirm_profile",
        "phase_id": "explore",
        "phase_title": "Explore career directions",
        "direction": "forward",
    }
    event.update(changes)
    return json.dumps(event)


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,focus-modes.history-events
def test_only_valid_current_chat_system_phase_notice_is_removed() -> None:
    transition = SimpleNamespace(role="system", content=_event())
    ordinary = SimpleNamespace(role="system", content="User approved this plan")
    user_question = SimpleNamespace(role="user", content=_event())
    assistant_quote = SimpleNamespace(role="assistant", content=_event())
    history = [ordinary, transition, user_question, assistant_quote]

    projected = filter_focus_phase_history(history, chat_id=CHAT_ID)

    assert projected == [ordinary, user_question, assistant_quote]
    assert projected is not history
    assert history == [ordinary, transition, user_question, assistant_quote]

    v7_chat_id = "019429f2-8e00-7000-8000-000000000001"
    v7_notice = SimpleNamespace(role="system", content=_event(chat_id=v7_chat_id))
    assert filter_focus_phase_history([ordinary, v7_notice], chat_id=v7_chat_id) == [ordinary]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,focus-modes.history-events
def test_ambiguous_or_malformed_system_content_is_preserved() -> None:
    candidates = [
        _event(chat_id=str(uuid4())),
        _event(event_id="not-a-uuid"),
        _event(version="2"),
        _event(direction="sideways"),
        _event(extra="unexpected"),
        '{"type":"focus_phase_changed"}',
        "Here is a transition: " + _event(),
    ]
    history = [SimpleNamespace(role="system", content=content) for content in candidates]

    assert filter_focus_phase_history(history, chat_id=CHAT_ID) == history


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction,focus-modes.history-events
def test_worker_filters_inference_history_before_preprocessing() -> None:
    source = (Path(__file__).resolve().parents[1] / "apps/ai/tasks/ask_skill_task.py").read_text()
    module = ast.parse(source)
    worker = next(
        node for node in ast.walk(module)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_async_process_ai_skill_ask_task"
    )
    filters = [
        node for node in ast.walk(worker)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "filter_focus_phase_history"
    ]
    assert len(filters) == 1
    preprocessing = [
        node for node in ast.walk(worker)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "handle_preprocessing"
    ]
    assert preprocessing and filters[0].lineno < preprocessing[0].lineno
