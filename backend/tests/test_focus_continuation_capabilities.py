"""A focus continuation keeps the turn's client capabilities, so a Project chat keeps its file tools.

Regression: the web Flow 2 proof (Garden Planner on a connected machine) named
`@focus:code:write_specification`; the continuation that answers with the focus active
arrived without `client_capabilities`, so `project_file_jobs` was missing and the
assistant said it could not read the Project's files.
"""

import hashlib
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
    from backend.apps.ai.tasks import focus_mode_auto_confirm_task as auto
    from backend.core.api.app.routes.handlers.websocket_handlers import focus_mode_rejected_handler as rejected
    forwarded = '"client_capabilities": list(pending_context.get("client_capabilities") or [])'
    assert forwarded in inspect.getsource(auto)
    assert forwarded in inspect.getsource(rejected._trigger_continuation_without_focus)
    child = AskSkillRequest.model_validate({
        **_request().model_dump(), "client_capabilities": CAPABILITIES, "is_focus_mode_continuation": True,
    })
    assert "project_file_jobs" in child.client_capabilities
