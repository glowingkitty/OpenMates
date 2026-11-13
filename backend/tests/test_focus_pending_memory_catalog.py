"""A pending Focus activation keeps the Memory catalog as JSON-safe metadata for its continuation."""

import hashlib
import json

from backend.apps.ai.processing.main_processor import _forward_agentic_context
from backend.apps.ai.processing.rule_context import request_personal_catalog
from backend.apps.ai.skills.ask_skill import AskSkillRequest

CATALOG = [{"id": "career-profile", "title": "Career profile",
            "when_to_use": "Job applications and CVs.", "load_mode": "ask_first",
            "source": "personal"}]


def _request(**extra):
    return AskSkillRequest(
        chat_id="chat", message_id="first", user_id="owner",
        user_id_hash=hashlib.sha256(b"owner").hexdigest(),
        is_incognito=False, is_external=False, is_anonymous=False,
        message_history=[{"role": "user", "message_id": "first",
                          "content": "Write my cover letter", "created_at": 1}],
        **extra,
    )


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes,app-memories.selection.source-scoped
def test_pending_focus_context_serializes_the_memory_catalog():
    context = _forward_agentic_context(_request(memory_catalog=CATALOG))
    # Stored in Redis as JSON; a pydantic entry here made the store fail and the
    # Focus turn never continued.
    stored = json.loads(json.dumps(context))
    assert stored["memory_catalog"] == CATALOG
    restored = _request(memory_catalog=stored["memory_catalog"])
    assert [entry.id for entry in request_personal_catalog(restored)] == ["career-profile"]


# contract-test: supporting surface=rest_api assertions=app-memories.load-modes
def test_pending_focus_context_without_catalog_stays_empty():
    context = _forward_agentic_context(_request())
    assert json.loads(json.dumps(context))["memory_catalog"] == []
