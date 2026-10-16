# contract-test-file: infrastructure
"""Detached embed admission uses a durable exact invocation before broker work."""
from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest

from backend.shared.python_utils.chat_recovery_context import (
    AuthenticatedDirectSkill, LegacyOutputContext, RecoveryOutputContext,
    active_authenticated_direct_skill, active_recovery_output_context,
    active_verified_output_producer, active_legacy_output_context,
)
from backend.shared.python_utils import embed_producer_dispatch as dispatch
from backend.shared.python_utils import embed_producer_worker as worker
from backend.shared.python_utils import volatile_embed_authority as volatile


OWNER = "owner-uuid"
OWNER_HASH = hashlib.sha256(OWNER.encode()).hexdigest()
TASK_ID = str(uuid.uuid4())
TASK_NAME = "apps.images.tasks.skill_generate"
ARGS = {"user_id": OWNER, "chat_id": "chat-1", "message_id": "message-1", "embed_id": "embed-1"}


def _context() -> RecoveryOutputContext:
    return RecoveryOutputContext(
        owner_id=OWNER, owner_hash=OWNER_HASH, root_chat_id="root-1",
        target_chat_id="chat-1", turn_id="turn-1", preflight_id="preflight-1",
        inference_task_id="inference-1", public_key="public-key", key_version=1,
    )


def _resolved(status: str = "PENDING") -> dict:
    return {"status": status, "context": {
        "hashed_user_id": OWNER_HASH, "root_chat_id": "root-1",
        "target_chat_id": "chat-1", "turn_id": "turn-1",
        "preflight_id": "preflight-1", "inference_task_id": "inference-1",
        "chat_key_version": 1, "recovery_public_key": "public-key",
        "primary_embed_id": "embed-1", "primary_message_id": "message-1",
        "hashed_team_id": None,
    }}


class Producer:
    def __init__(self, calls: list): self.calls = calls
    def send_task(self, **kwargs):
        self.calls.append(("send", kwargs))
        return type("Sent", (), {"id": kwargs["task_id"]})()


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_epoch_zero_registers_exact_root_admission_before_broker(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    calls = []
    async def register(operation, data):
        calls.append((operation, data))
        return {"producer_intent_id": TASK_ID, "status": "LEGACY_AUTHORIZED"}
    monkeypatch.setattr(dispatch, "_transaction", register)
    context = LegacyOutputContext(
        owner_id=OWNER, owner_hash=OWNER_HASH,
        legacy_task_identity=hashlib.sha256(f"{OWNER}:root-1:root-message".encode()).hexdigest(),
        root_chat_id="root-1", root_turn_id="turn-1",
        root_user_message_id="root-message", target_chat_id="chat-1",
    )
    token = active_legacy_output_context.set(context)
    try:
        await dispatch.dispatch_legacy_embed_task(
            Producer(calls), task_name=TASK_NAME, queue="app_images",
            kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
            target_chat_id="chat-1", message_id="message-1",
            embed_id="embed-1", task_uuid=TASK_ID,
        )
    finally:
        active_legacy_output_context.reset(token)
    assert [call[0] for call in calls] == ["register_legacy_output_producer", "send"]
    assert calls[0][1]["root_user_message_id"] == "root-message"
    assert calls[0][1]["legacy_task_identity"] == context.legacy_task_identity


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_stateless_rest_authority_binds_main_and_detached_task(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret-long-enough-for-signing")
    principal = volatile.AuthenticatedVolatileAI(OWNER, OWNER_HASH, "external")
    header = volatile.make_main_header(
        principal, owner_id=OWNER, owner_hash=OWNER_HASH,
        chat_id="chat-1", message_id="message-1", main_task_id="main-1",
    )
    context = volatile.verify_main_header(
        header, owner_id=OWNER, owner_hash=OWNER_HASH,
        chat_id="chat-1", message_id="message-1", main_task_id="main-1",
    )
    token = volatile.active_volatile_ai_context.set(context)
    calls = []
    try:
        await dispatch.dispatch_volatile_embed_task(
            Producer(calls), task_name=TASK_NAME, queue="app_images",
            kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
            target_chat_id="chat-1", message_id="message-1",
            embed_id="embed-1", task_uuid=TASK_ID,
        )
    finally:
        volatile.active_volatile_ai_context.reset(token)
    async def authorize(operation, data):
        assert operation == "verify_volatile_output_actor"
        assert data["hashed_user_id"] == OWNER_HASH
        return {"authorized": True}
    monkeypatch.setattr(worker, "_transaction", authorize)
    sent = calls[0][1]
    producer, recovery = await worker.verify_output_producer(
        task_name=TASK_NAME, task_id=TASK_ID, args=(),
        kwargs=sent["kwargs"], headers=sent["headers"],
    )
    assert producer.classification == "authorized_volatile"
    assert producer.intent_kind == "external" and recovery is None
    tampered = {**sent["kwargs"], "arguments": {**ARGS, "embed_id": "other"}}
    with pytest.raises(worker.ProducerHold, match="volatile_authority_invalid"):
        await worker.verify_output_producer(
            task_name=TASK_NAME, task_id=TASK_ID, args=(),
            kwargs=tampered, headers=sent["headers"],
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_incognito_requires_live_server_session_and_expiry(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret-long-enough-for-signing")
    principal = volatile.AuthenticatedVolatileAI(
        OWNER, OWNER_HASH, "incognito", "chat-1", "message-1",
        "server-nonce-" + "a" * 40,
    )
    header = volatile.make_main_header(
        principal, owner_id=OWNER, owner_hash=OWNER_HASH,
        chat_id="chat-1", message_id="message-1", main_task_id="main-1",
    )
    context = volatile.verify_main_header(
        header, owner_id=OWNER, owner_hash=OWNER_HASH,
        chat_id="chat-1", message_id="message-1", main_task_id="main-1",
    )
    async def closed(*_):
        raise ValueError("closed")
    monkeypatch.setattr(dispatch, "require_live_incognito_session", closed)
    token = volatile.active_volatile_ai_context.set(context)
    calls = []
    try:
        with pytest.raises(Exception, match="Incognito live session closed"):
            await dispatch.dispatch_volatile_embed_task(
                Producer(calls), task_name=TASK_NAME, queue="app_images",
                kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
                target_chat_id="chat-1", message_id="message-1",
                embed_id="embed-1", task_uuid=TASK_ID,
            )
    finally:
        volatile.active_volatile_ai_context.reset(token)
    assert calls == []
    with pytest.raises(ValueError, match="expired"):
        volatile.verify_main_header(
            header, owner_id=OWNER, owner_hash=OWNER_HASH,
            chat_id="chat-1", message_id="message-1",
            main_task_id="main-1", now=context.expires_at,
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_live_socket_lease_checks_exact_owner_and_closes_cache(monkeypatch):
    import sys
    from types import ModuleType

    calls = []
    class Client:
        async def get(self, key):
            calls.append(("get", key))
            return OWNER_HASH
    class Cache:
        @property
        async def client(self):
            return Client()
        async def close(self):
            calls.append(("close",))
    cache_module = ModuleType("backend.core.api.app.services.cache")
    cache_module.CacheService = Cache
    monkeypatch.setitem(sys.modules, cache_module.__name__, cache_module)
    await volatile.require_live_incognito_session("nonce-1", OWNER_HASH)
    assert calls == [("get", "volatile_ai_live:v1:nonce-1"), ("close",)]
    calls.clear()
    with pytest.raises(ValueError, match="closed"):
        await volatile.require_live_incognito_session("nonce-1", "0" * 64)
    assert calls[-1] == ("close",)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_register_commits_before_broker_and_hmac_binds_complete_invocation(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    calls: list = []
    async def register(operation, data):
        calls.append((operation, data))
        return {"producer_intent_id": TASK_ID, "status": "PENDING"}
    monkeypatch.setattr(dispatch, "_transaction", register)
    token = active_recovery_output_context.set(_context())
    try:
        result = await dispatch.dispatch_recoverable_embed_task(
            Producer(calls), task_name=TASK_NAME, queue="app_images",
            kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
            target_chat_id="chat-1", message_id="message-1", embed_id="embed-1",
            task_uuid=TASK_ID,
        )
    finally:
        active_recovery_output_context.reset(token)
    assert result.id == TASK_ID
    assert [call[0] for call in calls] == ["register_output_producer", "send"]
    registered, sent = calls[0][1], calls[1][1]
    assert registered["kwargs_binding"] == dispatch.bind_task_invocation(
        task_name=TASK_NAME, task_uuid=TASK_ID, args=[], kwargs=sent["kwargs"],
    )
    assert sent["headers"] == {dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}}
    assert "secret" not in repr(registered)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_failed_registration_never_dispatches(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    async def fail(*_): raise RuntimeError("database unavailable")
    monkeypatch.setattr(dispatch, "_transaction", fail)
    calls: list = []
    token = active_recovery_output_context.set(_context())
    try:
        with pytest.raises(RuntimeError, match="database unavailable"):
            await dispatch.dispatch_recoverable_embed_task(
                Producer(calls), task_name=TASK_NAME, queue="app_images",
                kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
                target_chat_id="chat-1", message_id="message-1", embed_id="embed-1",
                task_uuid=TASK_ID,
            )
    finally:
        active_recovery_output_context.reset(token)
    assert calls == []


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_recovery_dispatch_helper_never_sends_without_admitted_context():
    calls: list = []
    with pytest.raises(RuntimeError, match="durable recovery admission"):
        await dispatch.dispatch_recoverable_embed_task(
            Producer(calls), task_name=TASK_NAME, queue="app_images",
            kwargs={"arguments": dict(ARGS)}, owner_id=OWNER,
            target_chat_id="chat-1", message_id="message-1", embed_id="embed-1",
            task_uuid=TASK_ID,
        )
    assert calls == []


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_worker_uses_authoritative_context_and_holds_sealed_retry(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    async def resolve(operation, data):
        assert operation == "resolve_output_producer"
        assert data["kwargs_binding"] == dispatch.bind_task_invocation(
            task_name=TASK_NAME, task_uuid=TASK_ID, args=[], kwargs={"arguments": ARGS},
        )
        return _resolved()
    monkeypatch.setattr(worker, "_transaction", resolve)
    header = {dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}}
    producer, context = await worker.verify_output_producer(
        task_name=TASK_NAME, task_id=TASK_ID, args=(), kwargs={"arguments": ARGS}, headers=header,
    )
    assert producer.classification == "registered_ai"
    assert producer.kwargs_binding and producer.task_name == TASK_NAME
    assert context and context.owner_hash == OWNER_HASH and context.public_key == "public-key"
    async def sealed(*_): return _resolved("SEALED")
    monkeypatch.setattr(worker, "_transaction", sealed)
    with pytest.raises(worker.ProducerHold, match="sealed_result_recovery_pending"):
        await worker.verify_output_producer(
            task_name=TASK_NAME, task_id=TASK_ID, args=(), kwargs={"arguments": ARGS}, headers=header,
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_untagged_admitted_and_spoofed_context_hold(monkeypatch):
    async def admitted(operation, data):
        assert operation == "classify_untagged_output_producer"
        assert data["hashed_user_id"] == OWNER_HASH
        return {"status": "ADMITTED_UNTAGGED", "preflight_id": "preflight-1"}
    monkeypatch.setattr(worker, "_transaction", admitted)
    with pytest.raises(worker.ProducerHold, match="admitted_task_missing_intent"):
        await worker.verify_output_producer(
            task_name=TASK_NAME, task_id=TASK_ID, args=(), kwargs={"arguments": ARGS}, headers=None,
        )
    with pytest.raises(worker.ProducerHold, match="invalid_producer_header"):
        await worker.verify_output_producer(
            task_name=TASK_NAME, task_id=TASK_ID, args=(), kwargs={"arguments": ARGS},
            headers={dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": str(uuid.uuid4())}},
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_direct_rerender_has_distinct_durable_proof_and_no_recovery_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    async def direct(operation, _data):
        if operation == "claim_authorized_direct_producer":
            return {"producer_intent_id": TASK_ID, "status": "RUNNING",
                    "intent_kind": "rerender", "claimed": True}
        assert operation == "resolve_output_producer"
        result = _resolved("DIRECT_AUTHORIZED")
        for field in ("root_chat_id", "turn_id", "preflight_id", "inference_task_id",
                      "chat_key_version", "recovery_public_key"):
            result["context"].pop(field)
        result["intent_kind"] = "rerender"
        result["context"]["expected_embed_version"] = 2
        return result
    monkeypatch.setattr(worker, "_transaction", direct)
    rerender_args = ({**ARGS, "source_version": 1},)
    producer, recovery = await worker.verify_output_producer(
        task_name="apps.videos.tasks.render_remotion", task_id=TASK_ID,
        args=rerender_args, kwargs={},
        headers={dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}},
    )
    assert producer.classification == "authorized_direct" and recovery is None
    assert producer.intent_kind == "rerender"
    assert producer.expected_embed_version == 2
    async def claimed(operation, _data):
        if operation == "resolve_output_producer":
            return await direct(operation, _data)
        assert operation == "claim_authorized_direct_producer"
        return {"producer_intent_id": TASK_ID, "status": "BLOCKED",
                "intent_kind": "rerender", "claimed": False}
    monkeypatch.setattr(worker, "_transaction", claimed)
    with pytest.raises(worker.ProducerHold, match="direct_intent_already_claimed"):
        await worker.verify_output_producer(
            task_name="apps.videos.tasks.render_remotion", task_id=TASK_ID,
            args=rerender_args, kwargs={},
            headers={dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}},
        )
    async def unrelated(*_): return {"status": "UNRELATED"}
    monkeypatch.setattr(worker, "_transaction", unrelated)
    with pytest.raises(worker.ProducerHold, match="untagged_task_requires_durable_authorization"):
        await worker.verify_output_producer(
            task_name="apps.videos.tasks.render_remotion", task_id=TASK_ID,
            args=rerender_args, kwargs={}, headers=None,
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_authenticated_standalone_skill_registers_before_broker(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    calls = []
    async def register(operation, data):
        calls.append((operation, data))
        return {"producer_intent_id": data["task_uuid"], "status": "DIRECT_AUTHORIZED"}
    monkeypatch.setattr(dispatch, "_transaction", register)
    principal = AuthenticatedDirectSkill(
        owner_id=OWNER, owner_hash=OWNER_HASH, app_id="images", skill_id="generate",
    )
    token = active_authenticated_direct_skill.set(principal)
    try:
        sent = await dispatch.dispatch_authorized_direct_skill_task(
            Producer(calls), task_name=TASK_NAME, queue="app_images",
            kwargs={"arguments": {"user_id": OWNER, "embed_id": "embed-1"}},
            owner_id=OWNER, embed_id="embed-1", task_uuid=TASK_ID,
        )
    finally:
        active_authenticated_direct_skill.reset(token)
    assert sent.id == TASK_ID
    assert [call[0] for call in calls] == ["register_authorized_direct_skill", "send"]
    assert calls[0][1]["actor_user_id"] == OWNER
    assert calls[0][1]["target_chat_id"] is None
    assert calls[0][1]["primary_message_id"] is None
    with pytest.raises(RuntimeError, match="principal is missing"):
        await dispatch.dispatch_authorized_direct_skill_task(
            Producer([]), task_name=TASK_NAME, queue="app_images",
            owner_id=OWNER, embed_id="embed-1", task_uuid=TASK_ID,
        )


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_worker_accepts_bound_direct_skill_without_chat_or_recovery_key(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    async def resolve(operation, _data):
        if operation == "claim_authorized_direct_producer":
            return {"producer_intent_id": TASK_ID, "status": "RUNNING",
                    "intent_kind": "direct_skill", "claimed": True}
        assert operation == "resolve_output_producer"
        return {"status": "DIRECT_AUTHORIZED", "intent_kind": "direct_skill", "context": {
            "hashed_user_id": OWNER_HASH,
            "hashed_team_id": None, "target_chat_id": None,
            "primary_message_id": None, "primary_embed_id": "embed-1",
        }}
    monkeypatch.setattr(worker, "_transaction", resolve)
    producer, recovery = await worker.verify_output_producer(
        task_name=TASK_NAME, task_id=TASK_ID, args=(),
        kwargs={"arguments": {"user_id": OWNER, "embed_id": "embed-1"}},
        headers={dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}},
    )
    assert producer.classification == "authorized_direct"
    assert producer.target_chat_id == "" and recovery is None

    async def team_resolve(operation, _data):
        if operation == "claim_authorized_direct_producer":
            return {"producer_intent_id": TASK_ID, "status": "RUNNING",
                    "intent_kind": "direct_skill", "claimed": True}
        assert operation == "resolve_output_producer"
        return {"status": "DIRECT_AUTHORIZED", "intent_kind": "direct_skill", "context": {
            "hashed_user_id": OWNER_HASH,
            "hashed_team_id": hashlib.sha256(b"team-1").hexdigest(),
            "target_chat_id": None, "primary_message_id": None,
            "primary_embed_id": "embed-1",
        }}
    monkeypatch.setattr(worker, "_transaction", team_resolve)
    team_producer, team_recovery = await worker.verify_output_producer(
        task_name=TASK_NAME, task_id=TASK_ID, args=(),
        kwargs={"arguments": {"user_id": OWNER, "embed_id": "embed-1", "team_id": "team-1"}},
        headers={dispatch.PRODUCER_HEADER: {"version": 1, "intent_id": TASK_ID}},
    )
    assert team_producer.hashed_team_id == hashlib.sha256(b"team-1").hexdigest()
    assert team_recovery is None


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_owner_chat_message_embed_and_team_are_checked_before_context_binding():
    for key, value in (("hashed_user_id", "wrong"), ("target_chat_id", "other"),
                       ("primary_message_id", "other"), ("primary_embed_id", "other")):
        result = _resolved()
        result["context"][key] = value
        with pytest.raises(worker.ProducerHold, match="producer_identity_mismatch"):
            worker._checked_context(result, ARGS, TASK_ID, TASK_NAME, "hmac")
    result = _resolved()
    result["context"]["hashed_team_id"] = hashlib.sha256(b"team-A").hexdigest()
    with pytest.raises(worker.ProducerHold, match="producer_team_mismatch"):
        worker._checked_context(result, {**ARGS, "team_id": "team-B"}, TASK_ID, TASK_NAME, "hmac")
    with pytest.raises(worker.ProducerHold, match="producer_not_pending"):
        worker._checked_context({"status": "BLOCKED", "reason": "team_deleted"},
                                ARGS, TASK_ID, TASK_NAME, "hmac")


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_hmac_changes_for_any_task_argument_and_missing_key_fails(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    base = dispatch.bind_task_invocation(task_name=TASK_NAME, task_uuid=TASK_ID, args=[], kwargs={"arguments": ARGS})
    changed = dispatch.bind_task_invocation(task_name=TASK_NAME, task_uuid=TASK_ID, args=[], kwargs={"arguments": {**ARGS, "prompt": "other"}})
    assert base != changed and len(base) == 64
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN")
    with pytest.raises(RuntimeError, match="binding key"):
        dispatch.bind_task_invocation(task_name=TASK_NAME, task_uuid=TASK_ID, args=[], kwargs={"arguments": ARGS})


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_worker_context_is_reset_after_body_failure_or_retry():
    producer, recovery = worker._checked_context(_resolved(), ARGS, TASK_ID, TASK_NAME, "hmac")
    assert active_verified_output_producer.get() is None
    assert active_recovery_output_context.get() is None
    with pytest.raises(RuntimeError, match="retry"):
        with worker.bound_output_producer(producer, recovery):
            assert active_verified_output_producer.get() == producer
            assert active_recovery_output_context.get() == recovery
            raise RuntimeError("retry")
    assert active_verified_output_producer.get() is None
    assert active_recovery_output_context.get() is None


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_direct_rerender_requires_canonical_head_and_durable_registration(monkeypatch):
    from fastapi import HTTPException
    from backend.core.api.app.routes import video_remotion

    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret")
    async def cached(*_):
        return {"app_id": "videos", "skill_id": "create", "remotion_source": "source",
                "message_id": "message-1", "current_source_version": 1}
    monkeypatch.setattr(video_remotion, "_load_remotion_embed_content", cached)
    row = {"hashed_user_id": OWNER_HASH,
           "hashed_chat_id": hashlib.sha256(b"chat-1").hexdigest(),
           "version_number": 2, "encrypted_content": "encrypted"}
    async def get_row(*_): return row
    async def decrypt(*_):
        return json.dumps({"app_id": "videos", "skill_id": "create",
                           "remotion_source": "source", "message_id": "message-1"})
    calls = []
    async def register(operation, data):
        calls.append((operation, data))
        return {"producer_intent_id": data["task_uuid"], "status": "DIRECT_AUTHORIZED"}
    monkeypatch.setattr(dispatch, "_transaction", register)
    def send(name, *, args, queue, **options):
        calls.append(("send", name, args, queue, options))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(remotion_task_sender=send)))
    current_user = SimpleNamespace(id=OWNER, vault_key_id="vault")
    directus = SimpleNamespace(embed=SimpleNamespace(get_sync_embed_by_id=get_row))
    result = await video_remotion.start_remotion_render(
        "embed-1", video_remotion.RemotionRenderRequest(chat_id="chat-1"), request,
        current_user=current_user, cache_service=object(),
        directus_service=directus, encryption_service=SimpleNamespace(decrypt_with_user_key=decrypt),
    )
    assert result["status"] == "rendering"
    assert [call[0] for call in calls] == ["register_authorized_rerender", "send"]
    registered, sent = calls[0][1], calls[1]
    assert registered["expected_embed_version"] == 2
    assert registered["hashed_user_id"] == OWNER_HASH
    assert sent[4]["headers"][dispatch.PRODUCER_HEADER]["intent_id"] == registered["task_uuid"]
    row["hashed_user_id"] = "other"
    with pytest.raises(HTTPException) as exc:
        await video_remotion.start_remotion_render(
            "embed-1", video_remotion.RemotionRenderRequest(chat_id="chat-1"), request,
            current_user=current_user, cache_service=object(),
            directus_service=directus, encryption_service=SimpleNamespace(decrypt_with_user_key=decrypt),
        )
    assert exc.value.status_code == 404
    assert len(calls) == 2
