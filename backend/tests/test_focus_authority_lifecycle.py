# contract-test-file: supporting surface=rest_api assertions=focus-modes.restoration,assistant-speech.execution.text-stream-independent
"""Canonical Focus root authority survives activation but never newer ownership."""
import inspect
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_utils import focus_continuation_history as focus


class Cache:
    def __init__(self):
        self.active = "root"
        self.values = {}
        self.client = self.connection()

    async def connection(self):
        return self

    async def get(self, key):
        return self.values.get(key)

    async def get_active_ai_task(self, chat):
        return self.active

    async def set(self, key, value, ttl=None, ex=None, nx=False):
        if not nx or key not in self.values:
            self.values[key] = value

    def _get_active_task_key(self, chat):
        return 'active'

    async def eval(self, script, key_count, *args):
        keys, argv = args[:key_count], args[key_count:]
        key = keys[0]
        if 'local phase' in script:
            if self.active != argv[0]:
                return 0
            if key not in self.values or self.values[key] == argv[1]:
                self.values[key] = argv[2]
                return 1
            return 0
        if key_count == 2:
            if self.active != argv[1] or self.values.get(key) == 'expired':
                return 0
            self.values[key] = argv[2]
            return 1
        if self.values.get(key) != argv[1]:
            return 0
        self.values[key] = 'expired'
        return 1

    async def get_user_vault_key_id(self, user):
        return "vault"


def request(continuation=False):
    return AskSkillRequest(chat_id="chat", message_id="source", user_id="owner", user_id_hash="hash",
                           message_history=[], is_focus_mode_continuation=continuation,
                           recovery_task_id=None if continuation else "root",
                           recovery_inference_task_id="root" if continuation else None)


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_pause_resume_cancellation_mapping_and_watchdog_does_not_expire_running(monkeypatch):
    import importlib
    auto = importlib.import_module("backend.apps.ai.tasks.focus_mode_auto_confirm_task")
    dispatch = Mock()
    monkeypatch.setattr(auto.expire_focus_authority, "apply_async", dispatch)
    cache = Cache()
    await focus.retain_focus_authority(cache, request(), "root", {})
    assert cache.active == "root"
    payload = dispatch.call_args.kwargs['kwargs']['request_envelope']
    assert AskSkillRequest.model_validate(payload).message_history == []
    cache.client = cache.connection()
    await focus.bind_focus_execution(cache, request(True), "child")
    assert 'root' in cache.values['focus_execution_root:owner:chat:child']
    cache.client = cache.connection()
    assert await focus.expire_pending_focus_authority(cache, request(), "root", {}) is False
    assert cache.active == "root"


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_expiry_dispatch_failure_and_missing_pending_context_use_existing_root_cleanup(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task as ask
    cleanup = AsyncMock()
    monkeypatch.setattr(ask, '_cleanup_on_task_failure', cleanup)
    cache = Cache()
    cache.values['focus_authority_phase:owner:chat:root'] = 'pending:root'
    assert await focus.expire_pending_focus_authority(cache, request(), 'root', {}) is True
    assert cleanup.call_args.kwargs['task_id'] == 'root'
    assert cleanup.call_args.kwargs['request_data'].message_id == 'source'
    cache.client = cache.connection()
    with pytest.raises(RuntimeError, match='expired'):
        await focus.bind_focus_execution(cache, request(True), 'late-child')


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_resume_cannot_claim_missing_or_newer_root():
    for owner in (None, 'newer'):
        cache = Cache()
        cache.active = owner
        with pytest.raises(RuntimeError, match='no longer owns'):
            await focus.bind_focus_execution(cache, request(True), 'child')
        cache.client.close()
        assert cache.active == owner


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_failure_handoff_completes_canonical_root_queue_empty_without_clearing_newer(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task as ask
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, 'reconcile_queued_revision_quarantine', AsyncMock(return_value=True))
    cache = AsyncMock()
    cache.get_active_ai_task.return_value = 'root'
    cache.lease_queued_message_prefix.return_value = None
    cache.complete_active_ai_task_if_queue_empty.return_value = 1
    result = await ask._handoff_queued_after_task_failure(request(True), {}, 'root', cache, AsyncMock())
    assert result is ask._FailureHandoffOutcome.OWNED_MARKER_CLEARED
    cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with('chat', 'root')
    cache.reset_mock()
    cache.get_active_ai_task.return_value = 'newer'
    assert await ask._handoff_queued_after_task_failure(request(True), {}, 'root', cache, AsyncMock()) is False
    cache.lease_queued_message_prefix.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_runtime_pause_flag_and_canonical_success_failure_cancel_wiring():
    from backend.apps.ai.tasks import ask_skill_task as ask, stream_consumer
    from backend.core.api.app.routes.handlers.websocket_handlers import cancel_ai_task_handler as cancel
    source = inspect.getsource(stream_consumer._consume_main_processing_stream)
    assert 'debug_metadata["awaiting_focus_mode_continuation"] = True' in source
    ask_source = inspect.getsource(ask)
    assert 'cache_service_instance, request_data, task_id, main_processor_debug_metadata,' in ask_source
    assert 'combined_chat_id, authority_task_id, queued_task_id,' in ask_source
    assert 'clear_active_ai_task_if_matches(chat_id, authority_task_id)' in ask_source
    cancel_source = inspect.getsource(cancel.handle_cancel_ai_task)
    assert 'cancel_focus_execution(' in cancel_source
    assert 'not focus_cancelled' in cancel_source



# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_stop_uses_trusted_mapping_and_existing_failure_handoff_not_direct_clear(monkeypatch):
    import json
    from backend.apps.ai.tasks import ask_skill_task as ask
    cleanup = AsyncMock()
    monkeypatch.setattr(ask, '_cleanup_on_task_failure', cleanup)
    cache = AsyncMock()
    req = request(True)
    cache.get.return_value = json.dumps({'root_id': 'root', 'request': focus.focus_cleanup_envelope(req)})
    cache.get_active_ai_task.return_value = 'root'
    client = AsyncMock()
    async def connection():
        return client
    cache.client = connection()
    assert await focus.cancel_focus_execution(cache, 'owner', 'chat', 'child') is True
    assert cleanup.call_args.kwargs['task_id'] == 'child'
    assert focus.focus_authority_root(cleanup.call_args.kwargs['request_data'], 'child') == 'root'
    assert cleanup.call_args.kwargs['use_cancelled_status'] is True
    client.eval.assert_awaited_once()
    cleanup.reset_mock()
    cache.get_active_ai_task.return_value = 'newer'
    assert await focus.cancel_focus_execution(cache, 'owner', 'chat', 'child') is False
    cleanup.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_watchdog_registered_in_existing_auto_confirm_module():
    import importlib
    auto = importlib.import_module('backend.apps.ai.tasks.focus_mode_auto_confirm_task')
    assert auto.expire_focus_authority.name == 'apps.ai.tasks.expire_focus_authority'
    assert auto.expire_focus_authority.name in auto.app.tasks


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_child_before_parent_pause_and_nested_pause_generation_do_not_expire_wrong_execution(monkeypatch):
    import importlib
    auto = importlib.import_module('backend.apps.ai.tasks.focus_mode_auto_confirm_task')
    monkeypatch.setattr(auto.expire_focus_authority, 'apply_async', Mock())
    cache = Cache()
    await focus.bind_focus_execution(cache, request(True), 'child')
    cache.client = cache.connection()
    await focus.retain_focus_authority(cache, request(), 'root', {})
    key = 'focus_authority_phase:owner:chat:root'
    assert cache.values[key] == 'running:child'
    cache.client = cache.connection()
    await focus.retain_focus_authority(cache, request(True), 'child', {})
    assert cache.values[key] == 'pending:child'
    cache.client = cache.connection()
    assert await focus.expire_pending_focus_authority(cache, request(), 'root', {}, 'root') is False
    cache.client = cache.connection()
    await focus.bind_focus_execution(cache, request(True), 'grandchild')
    assert cache.values[key] == 'running:grandchild'


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_production_parent_terminal_cleanup_precedes_child_bind_without_releasing_root():
    from backend.apps.ai.tasks import ask_skill_task as ask
    cache = Cache()
    cache.complete_active_ai_task_if_queue_empty = AsyncMock(return_value=1)
    state = await ask._complete_active_ai_turn_if_queue_empty(
        cache, request(), 'root', {'awaiting_focus_mode_continuation': True},
    )
    assert state == 2
    cache.complete_active_ai_task_if_queue_empty.assert_not_awaited()
    assert cache.active == 'root'
    await focus.bind_focus_execution(cache, request(True), 'child')
    assert await ask._complete_active_ai_turn_if_queue_empty(cache, request(True), 'child', {}) == 1
    cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with('chat', 'root')


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_atomic_resume_rechecks_root_after_initial_read_races_with_cancel():
    cache = Cache()
    async def old_read(chat):
        cache.active = None
        return 'root'
    cache.get_active_ai_task = old_read
    with pytest.raises(RuntimeError, match='expired'):
        await focus.bind_focus_execution(cache, request(True), 'child')
    assert 'focus_execution_root:owner:chat:child' not in cache.values


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_focus_failure_preserves_and_dispatches_accepted_queued_follower(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task as ask
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, 'reconcile_queued_revision_quarantine', AsyncMock(return_value=True))
    start = AsyncMock()
    monkeypatch.setattr(ask, '_start_recovery_queued_follower', start)
    cache = AsyncMock()
    cache.get_active_ai_task.return_value = 'root'
    lease = {'messages': [{'recovery_task_id': 'follower'}]}
    cache.lease_queued_message_prefix.return_value = lease
    assert await ask._handoff_queued_after_task_failure(request(True), {}, 'root', cache, AsyncMock()) is True
    assert start.call_args.kwargs['prior_task_id'] == 'root'
    assert start.call_args.kwargs['queued_lease'] == lease
    cache.clear_active_ai_task_if_matches.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_origin", ["pending_watchdog", "pending_stop"])
async def test_legacy_parent_cleanup_envelope_retains_real_queued_follower_handoff(monkeypatch, cleanup_origin):
    from backend.apps.ai.tasks import ask_skill_task as ask
    from backend.apps.ai.processing import queued_steering
    monkeypatch.setattr(queued_steering, 'reconcile_queued_revision_quarantine', AsyncMock(return_value=True))
    start = AsyncMock()
    monkeypatch.setattr(ask, '_start_recovery_queued_follower', start)
    parent = request().model_copy(update={
        'recovery_task_id': None, 'legacy_cutover_task_id': 'root',
        'volatile_dispatch_task_id': 'volatile', 'root_legacy_cutover_task_id': 'root',
    })
    # Both watchdog and pending Stop consume this exact metadata-only envelope.
    reconstructed = AskSkillRequest.model_validate(focus.focus_cleanup_envelope(parent))
    assert reconstructed.is_focus_mode_continuation is False
    assert reconstructed.recovery_task_id is None
    assert reconstructed.volatile_dispatch_task_id == 'volatile'
    cache = AsyncMock()
    cache.get_active_ai_task.return_value = 'root'
    lease = {'messages': [{'recovery_task_id': 'accepted-follower'}]}
    cache.lease_queued_message_prefix.return_value = lease
    assert await ask._handoff_queued_after_task_failure(reconstructed, {}, 'root', cache, AsyncMock()) is True
    cache.lease_queued_message_prefix.assert_awaited_once_with('chat', limit=20)
    assert start.call_args.kwargs['prior_task_id'] == 'root'
    assert start.call_args.kwargs['queued_lease'] == lease
    cache.clear_active_ai_task_if_matches.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
@pytest.mark.parametrize('accepted', [True, False])
async def test_legacy_production_child_envelope_binds_root_without_faking_recovery_and_completes(accepted):
    from backend.apps.ai.tasks import ask_skill_task as ask
    from backend.shared.python_utils.recent_work_summary_client import recent_work_authority_task_id
    cache = Cache()
    pending = {'task_id': 'root', 'message_id': 'source', 'legacy_cutover_task_id': 'legacy-identity'}
    child_data = request(True).model_dump()
    child_data['recovery_inference_task_id'] = None
    child_data['active_focus_id'] = 'study-learn_topic' if accepted else None
    # Both production dispatch sites use this helper on their actual child payload.
    child_id = await focus.prepare_focus_continuation_authority(cache, pending, child_data)
    child = AskSkillRequest.model_validate(child_data)
    assert child.resolved_recovery_inference_task_id() is None
    assert child.root_legacy_cutover_task_id == 'legacy-identity'
    assert focus.focus_authority_root(child, child_id) == child_id
    await focus.bind_focus_execution(cache, child, child_id)
    assert focus.focus_authority_root(child, child_id) == 'root'
    assert recent_work_authority_task_id(child, child_id) == 'root'
    assert child.resolved_recovery_inference_task_id() is None
    cache.complete_active_ai_task_if_queue_empty = AsyncMock(return_value=1)
    assert await ask._complete_active_ai_turn_if_queue_empty(cache, child, child_id, {}) == 1
    cache.complete_active_ai_task_if_queue_empty.assert_awaited_once_with('chat', 'root')


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_nested_legacy_watchdog_restores_broker_root_before_failure_cleanup(monkeypatch):
    from backend.apps.ai.tasks import ask_skill_task as ask
    cleanup = AsyncMock()
    monkeypatch.setattr(ask, '_cleanup_on_task_failure', cleanup)
    child = request(True).model_copy(update={'recovery_inference_task_id': None})
    child = AskSkillRequest.model_validate(focus.focus_cleanup_envelope(child))
    cache = Cache()
    cache.values['focus_authority_phase:owner:chat:root'] = 'pending:child'
    assert await focus.expire_pending_focus_authority(cache, child, 'root', {}, 'child') is True
    restored = cleanup.call_args.kwargs['request_data']
    assert focus.focus_authority_root(restored, 'child') == 'root'
    assert restored.resolved_recovery_inference_task_id() is None


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_legacy_stop_restores_root_only_from_trusted_scope_mapping(monkeypatch):
    import json
    from backend.apps.ai.tasks import ask_skill_task as ask
    cleanup = AsyncMock()
    monkeypatch.setattr(ask, '_cleanup_on_task_failure', cleanup)
    child = request(True).model_copy(update={'recovery_inference_task_id': None})
    cache = AsyncMock()
    cache.get.return_value = json.dumps({'root_id': 'root', 'request': focus.focus_cleanup_envelope(child)})
    cache.get_active_ai_task.return_value = 'root'
    client = AsyncMock()
    async def connection():
        return client
    cache.client = connection()
    assert await focus.cancel_focus_execution(cache, 'owner', 'chat', 'legacy-child') is True
    restored = cleanup.call_args.kwargs['request_data']
    assert focus.focus_authority_root(restored, 'legacy-child') == 'root'
    assert restored.resolved_recovery_inference_task_id() is None


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
def test_client_payload_cannot_set_runtime_focus_authority():
    from backend.shared.python_utils.recent_work_summary_client import recent_work_authority_task_id
    data = request(True).model_copy(update={'recovery_inference_task_id': None}).model_dump()
    data['_focus_authority_task_id'] = 'forged-root'
    restored = AskSkillRequest.model_validate(data)
    assert focus.focus_authority_root(restored, 'child') == 'child'
    assert recent_work_authority_task_id(restored, 'child') == 'child'


# contract-test: supporting surface=rest_api assertions=focus-modes.restoration
@pytest.mark.asyncio
async def test_child_authority_mapping_storage_failure_prevents_dispatch_identity():
    cache = AsyncMock()
    cache.set.return_value = False
    with pytest.raises(RuntimeError, match='could not be stored'):
        await focus.prepare_focus_continuation_authority(cache, {'task_id': 'root'}, request(True).model_dump())
