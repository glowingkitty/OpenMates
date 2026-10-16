"""Voice uses the real Project operation lease/approval machinery."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.processing import voice_project_tools as voice
from backend.core.api.app.services.project_file_operation_service import ProjectFileOperationError, ProjectFileOperationService
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService


class Redis:
    def __init__(self, binding):
        self.values = {}
        self.binding = binding

    async def hmget(self, _key, *fields):
        authority = {"user": self.binding["user_id"], "session": self.binding["session_id"],
                     "chat": self.binding["chat_id"], "state": "active"}
        return [authority.get(field) for field in fields]

    async def hget(self, _key, _field):
        return "user"

    async def exists(self, key):
        return key in self.values

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script, _count, key, token):
        if self.values.get(key) == token:
            del self.values[key]
        return 1


class Cache:
    def __init__(self, binding):
        self.redis = Redis(binding)
        self.values = {}
        self.published = []
        self.on_available = None

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ttl=None):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True

    async def get_user_vault_key_id(self, _user):
        return "owner-vault-key"

    async def publish_event(self, channel, event):
        self.published.append((channel, event))
        if event["event_for_client"] == "project_file_operation_available" and self.on_available:
            await self.on_available(event["payload"])
        return True


class Encryption:
    def __init__(self):
        self.sealed = {}

    async def encrypt_with_user_key(self, plaintext, key):
        assert key == "owner-vault-key"
        ciphertext = f"sealed-{len(self.sealed)}"
        self.sealed[ciphertext] = plaintext
        return ciphertext, {}

    async def decrypt_with_user_key(self, ciphertext, key):
        assert key == "owner-vault-key"
        return self.sealed[ciphertext]


@pytest.fixture
def setup(monkeypatch):
    focus = {"project_id": "project", "focus_id": "project-focus", "focus_id_hash": "hash",
             "activation_id": "activation", "team_id": "team"}
    binding = {"call_id": "c" * 32, "session_id": "session", "user_id": "owner", "chat_id": "chat",
               "user_message_id": "issued-user-turn", "operation_id": "a" * 32,
               "project_focus": focus, "context": {"client_capabilities": ["project_file_jobs"]}}
    cache = Cache(binding)
    cache.values[ProjectWriteAuthorizationService._focus_key("owner", "chat")] = focus
    directus = SimpleNamespace(project=SimpleNamespace(get_source=AsyncMock(
        return_value={"status": "connected", "capabilities": ["read", "search", "write_request"]})))
    encryption = Encryption()
    monkeypatch.setattr(ProjectWriteAuthorizationService, "get_active_focus", AsyncMock(return_value=focus))
    deadlines = ModuleType("backend.core.api.app.tasks.project_file_operation_tasks")
    deadlines.schedule_project_file_operation_deadlines = Mock()
    monkeypatch.setitem(sys.modules, deadlines.__name__, deadlines)
    return binding, cache, directus, encryption, deadlines


def load_handlers(monkeypatch):
    continuation = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation.dispatch_async_skill_continuation = AsyncMock()
    monkeypatch.setitem(sys.modules, continuation.__name__, continuation)
    path = Path(__file__).parents[1] / "core/api/app/routes/handlers/websocket_handlers/project_file_operation_handlers.py"
    spec = importlib.util.spec_from_file_location("_voice_project_handlers", path)
    handlers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handlers)
    return handlers, continuation.dispatch_async_skill_continuation


async def execute(setup, tool="project_read_text", arguments=None, **overrides):
    binding, cache, directus, encryption, _ = setup
    return await voice.execute_voice_project_tool(tool_name=tool, arguments=arguments or {"path": "README.md"},
        call_binding={**binding, **overrides}, operation_identity="call:0", cache_service=cache,
        directus_service=directus, encryption_service=encryption)


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.skill-integration,projects.files.search-scoped
@pytest.mark.asyncio
async def test_read_terminal_is_sealed_scoped_and_deduplicated_without_text_continuation(setup, monkeypatch):
    binding, cache, directus, encryption, deadlines = setup
    handlers, continuation = load_handlers(monkeypatch)
    websocket = SimpleNamespace(send_json=AsyncMock(), app=SimpleNamespace(state=SimpleNamespace(encryption_service=encryption)))

    async def client_result(summary):
        service = ProjectFileOperationService(cache)
        claim = await service.claim(user_id="owner", chat_id="chat", project_id="project",
                                    operation_id=summary["operation_id"], device_fingerprint_hash="owner-device")
        await handlers.handle_project_file_operation_result(websocket=websocket,
            manager=SimpleNamespace(can_execute_project_file_job=lambda *_: True), cache_service=cache,
            directus_service=directus, user_id="owner", device_fingerprint_hash="owner-device",
            payload={"protocol_version": 1, "operation_id": summary["operation_id"], "chat_id": "chat",
                     "project_id": "project", "lease_token": claim["lease_token"],
                     "lease_generation": claim["lease_generation"], "status": "completed",
                     "result": {"content": "PRIVATE FILE TEXT", "base_hash": "b" * 64}})

    cache.on_available = client_result
    first = await execute(setup)
    assert first["content"] == "PRIVATE FILE TEXT"
    assert first["status"] == "completed"
    assert first["base_hash"] == "b" * 64
    assert await execute(setup) == first
    assert len([event for _, event in cache.published if event["event_for_client"] == "project_file_operation_available"]) == 1
    deadlines.schedule_project_file_operation_deadlines.assert_called_once()
    assert "PRIVATE FILE TEXT" not in str(cache.values)
    assert "PRIVATE FILE TEXT" not in str(cache.published)
    envelope = json.loads(next(iter(encryption.sealed.values())))
    assert all(envelope[field] == binding[field] for field in voice._BINDING_FIELDS)
    continuation.assert_not_awaited()
    assert websocket.send_json.await_args.args[0]["type"] == "project_file_operation_completed"
    with pytest.raises(ProjectFileOperationError, match="identity_reused"):
        await execute(setup, arguments={"path": "OTHER.md"})


# contract-test: supporting surface=gui.web assertions=video-call.privacy,projects.files.search-scoped
@pytest.mark.asyncio
@pytest.mark.parametrize("tool,args,code", [
    ("project_read_text", {"path": "../secret"}, "invalid_project_path"),
    ("project_update_file", {"path": "README.md", "patch": "diff", "expected_base": "bad"}, "invalid_update_file_arguments"),
    ("project_create_file", {"path": "new.md", "content": "text", "expected_base": "existing"}, "invalid_create_file_arguments"),
    ("project_read_text", {"path": "README.md", "user_id": "other"}, "invalid_operation_arguments"),
    ("project_search_text", {"query": "needle", "include_content": True}, "invalid_operation_arguments"),
    ("project_read_text", {"path": "README.md", "source_id": 1}, "invalid_project_source"),
])
# contract-test: supporting surface=rest_api assertions=video-call.chat.project-context
async def test_arguments_use_existing_paths_hash_and_schema_rules(setup, tool, args, code):
    with pytest.raises(ProjectFileOperationError, match=code):
        await execute(setup, tool, args)
    assert not setup[1].published


# contract-test: supporting surface=gui.web assertions=video-call.privacy,projects.files.search-scoped
@pytest.mark.asyncio
async def test_fresh_focus_call_owner_and_source_capabilities_block_dispatch(setup):
    binding, cache, directus, _, _ = setup
    with pytest.raises(PermissionError):
        await execute(setup, user_id="different-owner")
    with pytest.raises(ProjectFileOperationError, match="project_focus_changed"):
        await execute(setup, project_focus={**binding["project_focus"], "focus_id_hash": "stale"})
    directus.project.get_source.return_value = {"status": "connected", "capabilities": ["search"]}
    with pytest.raises(ProjectFileOperationError, match="project_source_not_authorized"):
        await execute(setup, "project_search_files", {"query": "README", "source_id": "source", "include_content": True})
    directus.project.get_source.assert_awaited_once_with("project", "owner", "source", team_id="team")
    directus.project.get_source.return_value = {"status": "revoked", "capabilities": ["read"]}
    with pytest.raises(ProjectFileOperationError, match="project_source_not_authorized"):
        await execute(setup, arguments={"path": "README.md", "source_id": "source"})
    assert not cache.published


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.skill-integration
@pytest.mark.asyncio
async def test_cancellation_pauses_job_and_reconnect_cannot_replay_write(setup):
    binding, cache, _, _, _ = setup

    async def cancel(_summary):
        await cache.redis.set(voice.transport_key(binding["operation_id"], "cancel"), "1")

    cache.on_available = cancel
    with pytest.raises(ProjectFileOperationError, match="canceled"):
        await execute(setup, "project_create_file", {"path": "new.md", "content": "text", "expected_base": None})
    summary = cache.published[0][1]["payload"]
    service = ProjectFileOperationService(cache)
    job = await service.get_job(user_id="owner", operation_id=summary["operation_id"])
    assert job["state"] == "PAUSED_REQUIRES_EXPLICIT_RESUME"
    with pytest.raises(ProjectFileOperationError):
        await service.claim(user_id="owner", operation_id=job["operation_id"], chat_id="chat", project_id="project",
                            device_fingerprint_hash="owner-device")
    assert not any(":payload:" in key for key in cache.values)


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.skill-integration
@pytest.mark.asyncio
async def test_voice_timeout_pauses_early_and_claim_stays_paused_before_normal_deadline(setup, monkeypatch):
    _, cache, _, _, _ = setup
    real_time = time.time

    async def advance_clock(_summary):
        monkeypatch.setattr(voice.time, "time", lambda: real_time() + 20)

    cache.on_available = advance_clock
    result = await execute(setup, expires_at=real_time() + 10)
    assert result["status"] == "paused_requires_explicit_resume"
    service = ProjectFileOperationService(cache)
    job = await service.get_job(user_id="owner", operation_id=result["operation_id"])
    assert job["state"] == "PAUSED_REQUIRES_EXPLICIT_RESUME"
    with pytest.raises(ProjectFileOperationError, match="paused_requires_explicit_resume"):
        await service.claim(user_id="owner", operation_id=job["operation_id"], chat_id="chat", project_id="project",
                            device_fingerprint_hash="owner-device")


# contract-test: supporting surface=gui.web assertions=video-call.privacy
@pytest.mark.asyncio
async def test_expired_worker_envelope_cannot_dispatch_new_client_work(setup):
    with pytest.raises(ProjectFileOperationError, match="voice_project_request_expired"):
        await execute(setup, expires_at=1)
    assert not setup[1].published


# contract-test: supporting surface=gui.web assertions=video-call.privacy
def test_compact_results_bound_file_content_and_report_truncation():
    result = voice._compact({"status": "completed", "files": [{"content": "x" * 50_000} for _ in range(100)],
                            "vault_key_id": "private-key"})
    assert len(json.dumps(result)) < 26_000
    assert result["status"] == "completed"
    assert "Content truncated for voice" in result["files"][0]["content"]
    assert "private-key" not in str(result)


# contract-test: supporting surface=gui.web assertions=video-call.privacy,video-call.chat.skill-integration,projects.files.write-policy-enforcement
@pytest.mark.asyncio
async def test_rejected_normal_write_approval_returns_voice_result_without_text_turn(setup, monkeypatch):
    _, cache, directus, encryption, _ = setup
    handlers, continuation = load_handlers(monkeypatch)
    websocket = SimpleNamespace(send_json=AsyncMock(), app=SimpleNamespace(state=SimpleNamespace(encryption_service=encryption)))

    async def reject(summary):
        service = ProjectFileOperationService(cache)
        claim = await service.claim(user_id="owner", chat_id="chat", project_id="project",
                                    operation_id=summary["operation_id"], device_fingerprint_hash="owner-device")
        await service.settle(user_id="owner", chat_id="chat", project_id="project", operation_id=summary["operation_id"],
            device_fingerprint_hash="owner-device", lease_token=claim["lease_token"], lease_generation=claim["lease_generation"],
            status="awaiting_approval", result={"proposal_commitment": "b" * 64, "proposal": {"path": "new.md"}})
        await handlers.handle_project_file_operation_reject(websocket=websocket,
            manager=SimpleNamespace(can_execute_project_file_job=lambda *_: True), cache_service=cache, directus_service=directus,
            user_id="owner", device_fingerprint_hash="owner-device", payload={"protocol_version": 1,
                "operation_id": summary["operation_id"], "chat_id": "chat", "project_id": "project"})

    cache.on_available = reject
    result = await execute(setup, "project_create_file", {"path": "new.md", "content": "text", "expected_base": None})
    assert result["status"] == "user_declined"
    continuation.assert_not_awaited()
