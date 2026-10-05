"""Memory-only summary eligibility, owner isolation and runtime IPC privacy."""

# contract-test-file: infrastructure

from __future__ import annotations

import hashlib
import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from backend.core.api.app.routes import recent_work_internal
from backend.core.api.app.utils import internal_auth
from backend.shared.python_utils.recent_work_summary_cache import RecentWorkSummaryCache
from backend.shared.python_utils import recent_work_summary_cache as summary_cache_module
from backend.shared.python_utils.recent_work_summary_client import RecentWorkSummaryClient
from backend.shared.python_utils.recent_work_summary_client import (
    mint_response_summary_completion, write_response_summary_completion,
)
from pydantic import BaseModel


class FakeEncryption:
    def __init__(self):
        self.sealed = {}
        self.decrypt_calls = 0

    async def encrypt_with_user_key(self, text, key):
        cipher = f"vault:v1:opaque-{len(self.sealed)}"
        self.sealed[(cipher, key)] = text
        return cipher, "v1"

    async def decrypt_with_user_key(self, cipher, key):
        self.decrypt_calls += 1
        return self.sealed.get((cipher, key))


async def store(cache, encryption, **overrides):
    args = dict(owner_id="owner", chat_id="chat", project_id="project", revision="r1",
                text="private summary text", vault_key_id="owner-key", encryption=encryption,
                authorized=True, assistant_completed_at=1_000.0)
    args.update(overrides)
    return await cache.put(**args)


@pytest.mark.asyncio
async def test_ciphertext_only_nonrenewing_expiry_and_no_old_chat_fallback():
    now = [1_000.0]
    cache = RecentWorkSummaryCache(clock=lambda: now[0])
    encryption = FakeEncryption()
    assert await store(cache, encryption)
    assert "private summary text" not in repr(vars(cache))
    now[0] = 2_799.0
    summary = await cache.get(owner_id="owner", chat_id="chat", authorized_chat_ids=["chat"],
                              vault_key_id="owner-key", encryption=encryption)
    assert summary.text == "private summary text"
    assert summary.source.expires_at == 2_800.0
    now[0] = 2_800.0
    assert await cache.get(owner_id="owner", chat_id="chat", authorized_chat_ids=["chat"],
                           vault_key_id="owner-key", encryption=encryption) is None
    assert encryption.decrypt_calls == 1
    assert not cache._entries
    assert not await store(cache, encryption)  # stale source cannot be recreated


@pytest.mark.asyncio
async def test_unauthorized_wrong_owner_key_and_missing_sources_never_decrypt():
    cache = RecentWorkSummaryCache(clock=lambda: 1_000.0)
    encryption = FakeEncryption()
    assert not await store(cache, encryption, authorized=False)
    assert not await store(cache, encryption, assistant_completed_at=None)
    assert not await store(cache, encryption, assistant_completed_at=float("nan"))
    assert await store(cache, encryption, active=True, assistant_completed_at=None)
    for owner, chats, key in [("other", ["chat"], "owner-key"), ("owner", [], "owner-key"),
                              ("owner", ["chat"], "wrong-key")]:
        assert await cache.get(owner_id=owner, chat_id="chat", authorized_chat_ids=chats,
                               vault_key_id=key, encryption=encryption) is None
    assert encryption.decrypt_calls == 0


@pytest.mark.asyncio
async def test_revocation_fences_inflight_write_and_read():
    cache = RecentWorkSummaryCache(clock=lambda: 1_000.0)
    encryption = FakeEncryption()
    original_encrypt = encryption.encrypt_with_user_key

    async def revoke_during_encrypt(text, key):
        cache.revoke_owner("owner")
        return await original_encrypt(text, key)

    encryption.encrypt_with_user_key = revoke_during_encrypt
    assert not await store(cache, encryption)
    encryption.encrypt_with_user_key = original_encrypt
    assert await store(cache, encryption)
    original_decrypt = encryption.decrypt_with_user_key

    async def revoke_during_decrypt(cipher, key):
        cache.revoke_chat(owner_id="owner", chat_id="chat")
        return await original_decrypt(cipher, key)

    encryption.decrypt_with_user_key = revoke_during_decrypt
    assert await cache.get(owner_id="owner", chat_id="chat", authorized_chat_ids=["chat"],
                           vault_key_id="owner-key", encryption=encryption) is None


@pytest.mark.asyncio
async def test_capacity_bound_and_out_of_order_sources():
    cache = RecentWorkSummaryCache(clock=lambda: 1_100.0, max_entries=1)
    encryption = FakeEncryption()
    assert await store(cache, encryption, source_updated_at=1_100.0)
    assert not await store(cache, encryption, source_updated_at=1_050.0)
    assert await store(cache, encryption, chat_id="new")
    assert len(cache._entries) == 1


@pytest.mark.asyncio
async def test_idle_ciphertext_is_evicted_without_reads(monkeypatch):
    monkeypatch.setattr(summary_cache_module, "RECENT_WORK_WINDOW_SECONDS", 0.01)
    cache = RecentWorkSummaryCache()
    assert await store(cache, FakeEncryption(), assistant_completed_at=time.time())
    await asyncio.sleep(0.02)
    assert not cache._entries and not cache._expiry_handles


def runtime_app(monkeypatch):
    app = FastAPI()
    app.include_router(recent_work_internal.router)
    encryption = FakeEncryption()
    tasks = {"current": "task-current", "related": "task-related"}
    owned = {"current", "related"}

    class RuntimeCache:
        async def get(self, key):
            return "turn"

        async def get_active_ai_task(self, chat):
            return tasks.get(chat)

        async def get_active_ai_tasks(self, chats):
            return {chat: tasks[chat] for chat in chats if chat in tasks}

        async def get_user_vault_key_id(self, owner):
            return "owner-key" if owner == "owner" else None

    class DirectusMetadata:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "chats" and params["fields"] == "id,hashed_team_id"
            assert kwargs == {"no_cache": True, "admin_required": True}
            if params["filter[hashed_user_id][_eq]"] != hashlib.sha256(b"owner").hexdigest():
                return []
            return [{"id": chat} for chat in params["filter[id][_in]"].split(",") if chat in owned]

    app.state.cache_service = RuntimeCache()
    app.state.directus_service = DirectusMetadata()
    app.state.encryption_service = encryption
    monkeypatch.setattr(recent_work_internal, "recent_work_summary_cache", RecentWorkSummaryCache())
    monkeypatch.setattr(internal_auth, "INTERNAL_API_SHARED_TOKEN", "service-token")
    return app, tasks, owned, encryption


@pytest.mark.asyncio
async def test_worker_to_api_ipc_rechecks_owner_and_active_turn(monkeypatch):
    app, tasks, owned, encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))
    assert await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="r1",
                           text="transient private summary", assistant_completed_at=time.time())
    result = await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current",
                            authorized_chat_ids=["related"])
    assert result[0].text == "transient private summary"
    assert result[0].source.chat_id == "related"
    assert not await ipc.read(owner_id="other", current_chat_id="current", task_id="task-current",
                              authorized_chat_ids=["related"])
    tasks["current"] = "new-turn"
    assert not await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current",
                              authorized_chat_ids=["related"])
    tasks["current"] = "task-current"
    owned.remove("related")
    assert not await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current",
                              authorized_chat_ids=["related"])
    assert encryption.decrypt_calls == 1


@pytest.mark.asyncio
async def test_transport_auth_and_errors_never_echo_summary(monkeypatch):
    app, *_ = runtime_app(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
        unauthorized = await client.post("/internal/recent-work/write", json={"text": "private sentinel"})
        assert unauthorized.status_code == 401
        invalid = await client.post("/internal/recent-work/write", json={"text": "private sentinel"},
                                    headers={"X-Internal-Service-Token": "service-token"})
        assert invalid.status_code == 400
        assert "private sentinel" not in invalid.text


@pytest.mark.asyncio
async def test_failed_active_work_does_not_manufacture_completion(monkeypatch):
    app, tasks, _owned, encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))
    assert await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="checkpoint",
                           text="work checkpoint", active=True)
    assert await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"])
    del tasks["related"]
    assert not await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"])
    assert encryption.decrypt_calls == 1


@pytest.mark.asyncio
async def test_completion_ticket_accepts_finished_turn_once_preserving_timestamp(monkeypatch):
    app, tasks, _owned, _encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))
    ticket = await ipc.mint_completion(turn_id="turn", owner_id="owner", chat_id="related", task_id="task-related", revision="completed-r1")
    assert ticket
    permit = recent_work_internal.recent_work_summary_cache._completion_permits[ticket]
    del tasks["related"]
    assert await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="completed-r1",
                           text="fresh final summary", completion_ticket=ticket)
    summaries = await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"])
    assert summaries[0].source.assistant_completed_at == permit.assistant_completed_at
    assert summaries[0].source.expires_at == permit.assistant_completed_at + 1800
    assert not await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="completed-r1",
                               text="replayed summary", completion_ticket=ticket)


@pytest.mark.asyncio
async def test_old_ticket_cannot_overwrite_or_delete_newer_turn_summary(monkeypatch):
    app, tasks, _owned, _encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))
    ticket = await ipc.mint_completion(turn_id="turn", owner_id="owner", chat_id="related", task_id="task-related", revision="old-r1")
    tasks["related"] = "new-task"
    assert await ipc.write(owner_id="owner", chat_id="related", task_id="new-task", revision="new-r2",
                           text="new work summary", active=True)
    assert not await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="old-r1",
                               text="old work summary", completion_ticket=ticket)
    summaries = await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"])
    assert summaries[0].text == "new work summary"


@pytest.mark.asyncio
async def test_expired_revoked_or_wrong_revision_completion_ticket_is_denied(monkeypatch):
    app, _tasks, _owned, _encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))
    ticket = await ipc.mint_completion(turn_id="turn", owner_id="owner", chat_id="related", task_id="task-related", revision="r1")
    assert not await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="wrong",
                               text="summary", completion_ticket=ticket)
    recent_work_internal.recent_work_summary_cache.revoke_owner("owner")
    assert not await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="r1",
                               text="summary", completion_ticket=ticket)
    ticket = await ipc.mint_completion(turn_id="turn", owner_id="owner", chat_id="related", task_id="task-related", revision="r1")
    recent_work_internal.recent_work_summary_cache._clock = lambda: time.time() + 121
    assert not await ipc.write(owner_id="owner", chat_id="related", task_id="task-related", revision="r1",
                               text="summary", completion_ticket=ticket)


@pytest.mark.asyncio
async def test_pipeline_completion_ticket_is_not_serialized_as_request_or_old_summary(monkeypatch):
    app, tasks, _owned, _encryption = runtime_app(monkeypatch)
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token",
                                  transport=httpx.ASGITransport(app=app))

    class RequestModel(BaseModel):
        user_id: str = "owner"
        message_id: str = "turn"
        chat_id: str = "related"
        assistant_response_source_revision: int = 1

    request = RequestModel()
    await mint_response_summary_completion(request, "task-related", client=ipc)
    assert request._recent_summary_completion_ticket
    assert "_recent_summary_completion_ticket" not in request.model_dump()
    del tasks["related"]
    assert not await write_response_summary_completion(request, "task-related", None, client=ipc)
    assert await write_response_summary_completion(request, "task-related", "new final summary", client=ipc)


@pytest.mark.asyncio
async def test_private_context_ipc_fences_owner_latest_turn_and_expiry(monkeypatch):
    from unittest.mock import AsyncMock
    from backend.shared.python_utils.recent_work_summary_cache import TransientContextHandoffStore
    app, _tasks, owned, _encryption = runtime_app(monkeypatch)
    app.state.cache_service.get = AsyncMock(return_value="turn")
    monkeypatch.setattr(recent_work_internal, "transient_context_handoff_store", TransientContextHandoffStore())
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token", transport=httpx.ASGITransport(app=app))
    binding = dict(owner_id="owner", chat_id="current", turn_id="turn", request_id="request")
    fields = {"related_task_candidates": [{"summary": "synthetic sentinel"}]}
    reference = await ipc.seal_context(**binding, fields=fields)
    assert reference and await ipc.open_context(**binding, reference=reference) == fields
    app.state.cache_service.get.return_value = "new-turn"
    assert await ipc.open_context(**binding, reference=reference) is None
    app.state.cache_service.get.return_value = "turn"
    owned.remove("current")
    assert await ipc.open_context(**binding, reference=reference) is None
    public = RecentWorkSummaryClient(base_url="http://runtime", token="wrong", transport=httpx.ASGITransport(app=app))
    assert await public.seal_context(**binding, fields=fields) is None


@pytest.mark.asyncio
async def test_active_work_accepts_old_completion_without_fabricating_recent_completion_or_read_renewal():
    now = [3000.0]
    cache, encryption = RecentWorkSummaryCache(clock=lambda: now[0]), FakeEncryption()
    assert await store(cache, encryption, active=True, active_task_id="current-task", assistant_completed_at=1000.0)
    summary = await cache.get(owner_id="owner", chat_id="chat", authorized_chat_ids=["chat"],
                              vault_key_id="owner-key", encryption=encryption)
    assert summary.source.assistant_completed_at == 1000.0
    now[0] = 3500
    assert cache.mark_active(owner_id="owner", chat_id="chat", vault_key_id="owner-key", task_id="new-task")
    source = cache.candidates(owner_id="owner", authorized_chat_ids=["chat"])[0]
    assert source.assistant_completed_at == 1000.0 and source.revision == "r1"
    assert source.active_task_id == "new-task" and source.expires_at == 5300
    await cache.get(owner_id="owner", chat_id="chat", authorized_chat_ids=["chat"],
                    vault_key_id="owner-key", encryption=encryption)
    assert cache.candidates(owner_id="owner", authorized_chat_ids=["chat"])[0].expires_at == 5300


@pytest.mark.asyncio
async def test_active_first_response_goal_is_labeled_and_ineligible_after_actual_task_ends(monkeypatch):
    from unittest.mock import AsyncMock
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
    app, tasks, _owned, _encryption = runtime_app(monkeypatch)
    app.state.cache_service.get = AsyncMock(return_value="turn")
    monkeypatch.setattr(ProjectWriteAuthorizationService, "get_active_focus", AsyncMock(return_value=None))
    ipc = RecentWorkSummaryClient(base_url="http://runtime", token="service-token", transport=httpx.ASGITransport(app=app))
    assert await ipc.mark_active(owner_id="owner", chat_id="related", task_id="task-related", turn_id="turn",
                                 active_goal="Diagnose a synthetic API timeout")
    summaries = await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"])
    assert len(summaries) == 1
    assert summaries[0].source.source_kind == "authorized_active_request_goal"
    assert summaries[0].source.assistant_completed_at is None
    assert "no assistant completion" in summaries[0].text
    del tasks["related"]
    assert await ipc.read(owner_id="owner", current_chat_id="current", task_id="task-current", authorized_chat_ids=["related"]) == []
