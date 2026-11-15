"""A focus continuation keeps the turn's client capabilities, so a Project chat keeps its file tools.

Regression: the web Flow 2 proof (Garden Planner on a connected machine) named
`@focus:code:write_specification`; the continuation that answers with the focus active
arrived without `client_capabilities`, so `project_file_jobs` was missing and the
assistant said it could not read the Project's files.
"""

import hashlib
import importlib
import inspect
import json

from backend.apps.ai.processing.main_processor import _forward_agentic_context
from backend.apps.ai.skills.ask_skill import AskSkillRequest

CAPABILITIES = ["project_file_jobs", "remote_command_jobs", "memory_write_jobs"]


def _request(**extra):
    return AskSkillRequest(
        chat_id="chat", message_id="first", user_id="owner",
        user_id_hash=hashlib.sha256(b"owner").hexdigest(),
        is_incognito=False, is_external=False, is_anonymous=False,
        message_history=[{"role": "user", "message_id": "first",
                          "content": "Write the Specification for the harvest log", "created_at": 1}],
        **extra,
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_pending_focus_context_keeps_client_capabilities_json_safe():
    stored = json.loads(json.dumps(_forward_agentic_context(_request(client_capabilities=CAPABILITIES))))
    assert stored["client_capabilities"] == CAPABILITIES
    assert _forward_agentic_context(_request())["client_capabilities"] == []


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_both_focus_continuation_paths_forward_the_capabilities():
    # The tasks package re-exports the Celery task under the module's name, so import the module itself.
    auto = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
    from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as rejected
    forwarded = '"client_capabilities": list(pending_context.get("client_capabilities") or [])'
    assert forwarded in inspect.getsource(auto)
    assert forwarded in inspect.getsource(rejected._trigger_continuation_without_focus)
    child = AskSkillRequest.model_validate({
        **_request().model_dump(), "client_capabilities": CAPABILITIES, "is_focus_mode_continuation": True,
    })
    assert "project_file_jobs" in child.client_capabilities


class _ActiveTaskCache:
    """In-memory stand-in for the chat's active-task marker (claim and atomic transfer)."""

    def __init__(self, active=None):
        self.active = active

    async def try_claim_active_ai_task(self, chat_id, task_id):
        if self.active is not None:
            return False
        self.active = task_id
        return True

    async def transfer_active_ai_task(self, chat_id, prior, nxt):
        if self.active != prior:
            return False
        self.active = nxt
        return True


# contract-test: supporting surface=rest_api assertions=focus-modes.project-specialist-composition
def test_focus_continuation_owns_the_chat_so_project_operations_can_pause_it():
    import asyncio
    from backend.shared.python_utils.focus_continuation_history import claim_focus_continuation_ownership

    finished_source = _ActiveTaskCache()
    assert asyncio.run(claim_focus_continuation_ownership(finished_source, "chat", "source", "child"))
    assert finished_source.active == "child"
    running_source = _ActiveTaskCache("source")
    assert asyncio.run(claim_focus_continuation_ownership(running_source, "chat", "source", "child"))
    assert running_source.active == "child"
    newer_turn = _ActiveTaskCache("newer")
    assert not asyncio.run(claim_focus_continuation_ownership(newer_turn, "chat", "source", "child"))
    assert newer_turn.active == "newer"
    claim = "claim_focus_continuation_ownership("
    from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as rejected
    auto = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
    assert claim in inspect.getsource(auto) and claim in inspect.getsource(rejected)
