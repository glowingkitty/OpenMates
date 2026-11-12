# contract-test-file: supporting surface=rest_api assertions=focus-modes.restoration,app-memories.load-modes
"""A Focus activation inside a Memory-approval continuation resumes the turn.

Regression: the source task released the chat's active marker when it paused
for the Memory request, the continuation ran unowned, and its pending Focus
activation named the original task as root. The auto-confirmed Focus
continuation then failed with "Focus continuation no longer owns admitted
authority" and the turn stalled without an answer.
"""
import asyncio
import importlib
import json
from unittest.mock import Mock

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_utils import focus_continuation_history as focus

handler = importlib.import_module(
    "backend.core.api.app.routes.handlers.websocket_handlers.app_settings_memories_confirmed_handler"
)


class ActiveCache:
    """Active marker, phase keys and mappings with the Redis script semantics used here."""

    def __init__(self, active=None):
        self.active = active
        self.values = {}

    @property
    def client(self):
        async def connection():
            return self
        return connection()

    def _get_active_task_key(self, chat_id):
        return "active"

    async def get_active_ai_task(self, chat_id):
        return self.active

    async def try_claim_active_ai_task(self, chat_id, task_id, ttl=600):
        if self.active is not None:
            return False
        self.active = task_id
        return True

    async def transfer_active_ai_task(self, chat_id, prior_task_id, next_task_id):
        if self.active != prior_task_id:
            return False
        self.active = next_task_id
        return True

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True

    async def eval(self, script, key_count, *args):
        keys, argv = args[:key_count], args[key_count:]
        if "local phase" in script:  # retain_focus_authority
            if self.active != argv[0]:
                return 0
            if keys[0] not in self.values or self.values[keys[0]] == argv[1]:
                self.values[keys[0]] = argv[2]
                return 1
            return 0
        # bind_focus_execution
        if self.active != argv[1] or self.values.get(keys[0]) == "expired":
            return 0
        self.values[keys[0]] = argv[2]
        return 1


def _memory_continuation():
    return AskSkillRequest(
        chat_id="chat", message_id="source", user_id="owner", user_id_hash="hash",
        message_history=[], is_app_settings_memories_continuation=True,
        recovery_inference_task_id="source-task",
    )


def _pending_focus_context(request, task_id):
    # main_processor stores this root in the pending Focus activation context.
    return {"focus_authority_task_id": focus.focus_authority_root(request, task_id),
            "message_id": request.message_id}


def _focus_child_request():
    return {"chat_id": "chat", "message_id": "source", "user_id": "owner", "user_id_hash": "hash",
            "message_history": [], "is_focus_mode_continuation": True,
            "recovery_inference_task_id": "source-task"}


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration,app-memories.load-modes
def test_memory_continuation_claims_marker_released_by_paused_source():
    cache = ActiveCache(active=None)
    task_id, owned = asyncio.run(handler._claim_continuation_task(cache, "chat", "source-task"))
    assert owned and cache.active == task_id and task_id != "source-task"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration,app-memories.load-modes
def test_memory_continuation_takes_over_from_unfinished_source_but_never_from_newer_turn():
    cache = ActiveCache(active="source-task")
    task_id, owned = asyncio.run(handler._claim_continuation_task(cache, "chat", "source-task"))
    assert owned and cache.active == task_id
    newer = ActiveCache(active="newer-turn")
    _, owned = asyncio.run(handler._claim_continuation_task(newer, "chat", "source-task"))
    assert owned is False and newer.active == "newer-turn"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration,app-memories.load-modes
@pytest.mark.asyncio
async def test_focus_activation_inside_memory_continuation_resumes(monkeypatch):
    auto = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
    monkeypatch.setattr(auto.expire_focus_authority, "apply_async", Mock())
    cache = ActiveCache()
    memory_task_id, owned = await handler._claim_continuation_task(cache, "chat", "source-task")
    assert owned
    request = _memory_continuation()
    await focus.retain_focus_authority(cache, request, memory_task_id, {})
    assert cache.values[focus.focus_authority_phase_key("owner", "chat", memory_task_id)] == (
        f"pending:{memory_task_id}")
    pending = _pending_focus_context(request, memory_task_id)
    assert pending["focus_authority_task_id"] == memory_task_id

    child_data = _focus_child_request()
    child_id = await focus.prepare_focus_continuation_authority(cache, pending, child_data)
    child = AskSkillRequest.model_validate(child_data)
    await focus.bind_focus_execution(cache, child, child_id)
    assert focus.focus_authority_root(child, child_id) == memory_task_id
    mapping = json.loads(cache.values[f"focus_execution_root:owner:chat:{child_id}"])
    assert mapping["root_id"] == memory_task_id


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_original_source_root_is_not_the_memory_continuation_authority():
    cache = ActiveCache(active="memory-task")
    pending = {"focus_authority_task_id": "source-task", "message_id": "source"}
    child_data = _focus_child_request()
    child_id = await focus.prepare_focus_continuation_authority(cache, pending, child_data)
    with pytest.raises(RuntimeError, match="no longer owns"):
        await focus.bind_focus_execution(cache, AskSkillRequest.model_validate(child_data), child_id)
