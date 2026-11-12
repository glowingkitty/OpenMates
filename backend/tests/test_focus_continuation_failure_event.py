# contract-test-file: supporting surface=rest_api assertions=focus-modes.restoration
"""A focus continuation that lost its authority fails with a client-visible terminal code."""
import asyncio
from pathlib import Path

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_utils import focus_continuation_history as focus


class UnownedCache:
    """Chat whose active marker belongs to another task."""

    async def get(self, key):
        return None

    async def get_active_ai_task(self, chat_id):
        return "other-task"


def _request(root_id="root-task"):
    return AskSkillRequest.model_validate({
        "chat_id": "chat", "message_id": "msg", "user_id": "owner", "user_id_hash": "hash",
        "message_history": [], "is_focus_mode_continuation": True,
        "recovery_inference_task_id": root_id,
    })


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_unowned_focus_continuation_raises_typed_authority_error():
    with pytest.raises(focus.FocusContinuationAuthorityError) as info:
        asyncio.run(focus.bind_focus_execution(UnownedCache(), _request(), "child-task"))
    assert isinstance(info.value, RuntimeError)
    assert info.value.terminal_failure_code == "focus_continuation_unavailable"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_service_init_failure_publishes_typing_ended_with_terminal_code():
    source = Path("backend/apps/ai/tasks/ask_skill_task.py").read_text()
    init_failure = source.split("Failed to initialize services", 1)[1].split(
        'raise RuntimeError(f"Service initialization failed', 1)[0]
    assert "isinstance(e, FocusContinuationAuthorityError)" in init_failure
    assert "_publish_typing_ended(" in init_failure
    assert "terminal_failure_code=e.terminal_failure_code" in init_failure
