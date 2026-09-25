"""Focused remote command review, encryption, lease, and authority tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.core.api.app.routes.handlers.websocket_handlers import remote_command_handlers
from backend.core.api.app.schemas.remote_command_schemas import RemoteCommandPolicy
from backend.core.api.app.services.remote_command_service import (
    RemoteCommandError,
    RemoteCommandService,
    explain_remote_command,
)


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.events: list[tuple[str, dict]] = []

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None) -> bool:
        self.data[key] = value
        return True

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None

    async def publish_event(self, channel: str, event: dict) -> bool:
        self.events.append((channel, event))
        return True


class MemoryWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, value: dict) -> None:
        self.sent.append(value)


def binding(**overrides):
    return {
        "source_session_id": "session-1",
        "host_user_id": "user-1",
        "device_fingerprint_hash": "device-1",
        "key_epoch": 4,
        "capabilities": ["read", "run_command"],
        **overrides,
    }


async def create_review(service: RemoteCommandService):
    result = await service.create_review(
        user_id="user-1",
        chat_id="chat-1",
        project_id="project-1",
        focus_id="focus-1",
        source_id="source-1",
        command={
            "argv": ["npm", "test"],
            "cwd": ".",
            "mode": "foreground",
            "source_access": "read_only",
            "deadline_ms": 60_000,
            "writable_profiles": [],
            "network_profile": None,
            "credential_profiles": [],
        },
        explanation={"summary": "Runs tests", "effects": [], "risks": [], "uncertainty": "Scripts are indirect."},
        continuation_task_id="continuation-1",
        message_id="message-1",
        wait_for_completion=True,
        one_run_required=False,
        execution_id="execution-1",
        now=100,
        schedule_expiration=False,
    )
    assert not service.cache.events
    await service.register_continuation(
        user_id="user-1", execution_id="execution-1", now=100
    )
    return result


# contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval,code-run.remote.command-lists
@pytest.mark.anyio
async def test_review_plaintext_is_transient_and_prepare_persists_only_ciphertext() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await create_review(service)

    job = await service.get_job(user_id="user-1", execution_id="execution-1")
    assert "command" not in job
    assert "explanation" not in job
    review = cache.events[-1][1]["payload"]
    assert review["command"]["argv"] == ["npm", "test"]

    await service.prepare(
        user_id="user-1",
        execution_id="execution-1",
        chat_id="chat-1",
        project_id="project-1",
        source_id="source-1",
        review_token=review["review_token"],
        encrypted_request="project-key-ciphertext",
        request_digest="project-key-hmac-" + "a" * 32,
        approval={"kind": "one_run"},
        binding=binding(),
        now=101,
    )
    cached_text = repr(cache.data)
    assert "npm" not in cached_text
    assert "Runs tests" not in cached_text
    assert "project-key-ciphertext" in cached_text


# contract-test: supporting surface=cli assertions=code-run.remote.confinement,code-run.remote.resource-profiles
def test_remote_policy_keeps_shell_composition_exact_and_rejects_parent_cwd_and_background_writes() -> None:
    composed = RemoteCommandPolicy(argv=["bash", "-lc", "npm test && npm run lint"], cwd=".", deadline_ms=1000)
    assert composed.argv == ["bash", "-lc", "npm test && npm run lint"]
    with pytest.raises(ValidationError):
        RemoteCommandPolicy(argv=["npm", "test"], cwd="../other", deadline_ms=1000)
    with pytest.raises(ValidationError):
        RemoteCommandPolicy(
            argv=["npm", "test"], cwd=".", mode="background", source_access="read_write", deadline_ms=1000
        )


# contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,code-run.remote.explicit-approval
@pytest.mark.anyio
async def test_claim_revalidate_events_and_origin_completion_are_exact_and_idempotent() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await create_review(service)
    review = cache.events[-1][1]["payload"]
    await service.prepare(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1", project_id="project-1",
        source_id="source-1", review_token=review["review_token"], encrypted_request="ciphertext",
        request_digest="hmac-" + "a" * 32, approval={"kind": "one_run"}, binding=binding(), now=101,
    )

    claim = await service.claim(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1", binding=binding(), now=102,
    )
    replayed_claim = await service.claim(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1", binding=binding(), now=103,
    )
    assert replayed_claim["lease_generation"] == claim["lease_generation"]
    assert replayed_claim["lease_token"] == claim["lease_token"]

    authority = await service.revalidate(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1",
        lease_token=claim["lease_token"], lease_generation=claim["lease_generation"], binding=binding(), now=104,
    )
    assert authority["authorized"] is True
    assert authority["request_digest"] == "hmac-" + "a" * 32

    await service.record_event(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1",
        lease_token=claim["lease_token"], lease_generation=claim["lease_generation"], sequence=0,
        event_kind="status", status="running", encrypted_event="encrypted-running", binding=binding(), now=105,
    )
    recovered = await service.recover(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1", last_sequence=0,
        runtime_status="running", binding=binding(), now=196,
    )
    assert recovered["launch_allowed"] is False
    await service.record_event(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1",
        lease_token=recovered["lease_token"], lease_generation=recovered["lease_generation"], sequence=1,
        event_kind="terminal", status="succeeded", encrypted_event="encrypted-terminal", binding=binding(), now=197,
    )
    first = await service.complete_from_origin(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1", project_id="project-1",
        result_status="succeeded", safety_receipt={"scanned": True}, now=198,
    )
    replay = await service.complete_from_origin(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1", project_id="project-1",
        result_status="succeeded", safety_receipt={"scanned": True}, now=199,
    )
    assert first["replayed"] is False
    assert replay["replayed"] is True
    terminal_retry = await service.record_event(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1",
        lease_token=recovered["lease_token"], lease_generation=recovered["lease_generation"], sequence=1,
        event_kind="terminal", status="succeeded", encrypted_event="encrypted-terminal", binding=binding(), now=200,
    )
    assert terminal_retry["state"] == "TERMINAL"


# contract-test: supporting surface=cli assertions=code-run.remote.managed-jobs,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_changed_binding_and_event_sequence_are_rejected() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await create_review(service)
    review = cache.events[-1][1]["payload"]
    await service.prepare(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1", project_id="project-1",
        source_id="source-1", review_token=review["review_token"], encrypted_request="ciphertext",
        request_digest="hmac-" + "b" * 32, approval={"kind": "preset", "preset_id": "checks", "definition_digest": "d" * 64},
        binding=binding(), now=101,
    )
    claim = await service.claim(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1", binding=binding(), now=102,
    )
    with pytest.raises(RemoteCommandError, match="command_authority_revoked"):
        await service.revalidate(
            host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
            execution_id="execution-1", project_id="project-1", source_id="source-1",
            lease_token=claim["lease_token"], lease_generation=claim["lease_generation"],
            binding=binding(key_epoch=5), now=103,
        )
    with pytest.raises(RemoteCommandError, match="event_sequence_gap"):
        await service.record_event(
            host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
            execution_id="execution-1", project_id="project-1", source_id="source-1",
            lease_token=claim["lease_token"], lease_generation=claim["lease_generation"], sequence=2,
            event_kind="output", status="running", encrypted_event="encrypted-output", binding=binding(), now=103,
        )


# contract-test: direct surface=cli assertions=code-run.remote.managed-jobs,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_owned_running_command_can_be_stopped_after_focus_is_off_but_cross_owner_is_denied() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await create_review(service)
    review = cache.events[-1][1]["payload"]
    await service.prepare(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1", project_id="project-1",
        source_id="source-1", review_token=review["review_token"], encrypted_request="ciphertext",
        request_digest="hmac-" + "s" * 32, approval={"kind": "one_run"}, binding=binding(), now=101,
    )
    claim = await service.claim(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1", binding=binding(), now=102,
    )
    await service.record_event(
        host_user_id="user-1", device_fingerprint_hash="device-1", source_session_id="session-1",
        execution_id="execution-1", project_id="project-1", source_id="source-1",
        lease_token=claim["lease_token"], lease_generation=claim["lease_generation"], sequence=0,
        event_kind="status", status="running", encrypted_event="encrypted-running", binding=binding(), now=103,
    )

    owner_socket = MemoryWebSocket()
    await remote_command_handlers.handle_remote_command_stop(
        websocket=owner_socket,
        cache_service=cache,
        directus_service=object(),
        user_id="user-1",
        payload={
            "protocol_version": 1,
            "execution_id": "execution-1",
            "chat_id": "chat-1",
            "project_id": "project-1",
        },
    )
    assert owner_socket.sent[-1]["type"] == "remote_command_stop_ack"
    assert owner_socket.sent[-1]["payload"]["state"] == "STOP_REQUESTED"

    other_socket = MemoryWebSocket()
    await remote_command_handlers.handle_remote_command_stop(
        websocket=other_socket,
        cache_service=cache,
        directus_service=object(),
        user_id="user-2",
        payload={
            "protocol_version": 1,
            "execution_id": "execution-1",
            "chat_id": "chat-1",
            "project_id": "project-1",
        },
    )
    assert other_socket.sent[-1] == {
        "type": "remote_command_error",
        "payload": {"execution_id": "execution-1", "code": "unknown_execution"},
    }


# contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval,projects.files.write-policy-enforcement
@pytest.mark.anyio
async def test_always_ask_write_rejects_preset_approval() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await service.create_review(
        user_id="user-1", chat_id="chat-1", project_id="project-1", focus_id="focus-1",
        source_id="source-1", command={"argv": ["npm", "run", "format"]},
        explanation={"summary": "Formats files"}, continuation_task_id="continuation-2",
        message_id="message-1", wait_for_completion=True, one_run_required=True,
        execution_id="execution-2", now=100,
        schedule_expiration=False,
    )
    await service.register_continuation(
        user_id="user-1", execution_id="execution-2", now=100
    )
    review = cache.events[-1][1]["payload"]
    with pytest.raises(RemoteCommandError, match="one_run_approval_required"):
        await service.prepare(
            user_id="user-1", execution_id="execution-2", chat_id="chat-1", project_id="project-1",
            source_id="source-1", review_token=review["review_token"], encrypted_request="ciphertext",
            request_digest="hmac-" + "c" * 32,
            approval={"kind": "preset", "preset_id": "format", "definition_digest": "d" * 64},
            binding=binding(), now=101,
        )


# contract-test: supporting surface=cli assertions=code-run.remote.explicit-approval,code-run.execution.wait-or-continue
@pytest.mark.anyio
async def test_review_rejection_and_expiration_are_idempotent_terminal_decisions() -> None:
    cache = MemoryCache()
    service = RemoteCommandService(cache)
    await create_review(service)
    review = cache.events[-1][1]["payload"]
    first = await service.reject_review(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1",
        project_id="project-1", review_token=review["review_token"], now=101,
    )
    replay = await service.reject_review(
        user_id="user-1", execution_id="execution-1", chat_id="chat-1",
        project_id="project-1", review_token=review["review_token"], now=102,
    )
    assert first["replayed"] is False
    assert replay["replayed"] is True

    await service.create_review(
        user_id="user-1", chat_id="chat-1", project_id="project-1", focus_id="focus-1",
        source_id="source-1", command={"argv": ["npm", "test"]}, explanation={"summary": "Runs tests"},
        continuation_task_id="continuation-2", message_id="message-1", wait_for_completion=True,
        one_run_required=False, execution_id="execution-2", now=200, schedule_expiration=False,
    )
    early = await service.expire_review(
        user_id="user-1", execution_id="execution-2", created_at=200, now=799,
    )
    expired = await service.expire_review(
        user_id="user-1", execution_id="execution-2", created_at=200, now=800,
    )
    expired_replay = await service.expire_review(
        user_id="user-1", execution_id="execution-2", created_at=200, now=801,
    )
    assert early["expired"] is False
    assert expired["expired"] is True and expired["replayed"] is False
    assert expired_replay["replayed"] is True
# contract-test: supporting surface=cli assertions=code-run.remote.explanation
@pytest.mark.anyio
async def test_explanation_call_is_isolated_and_fixed_to_flash_lite() -> None:
    captured = {}

    async def caller(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            arguments={"summary": "Runs tests", "effects": [], "risks": [], "uncertainty": "Indirect scripts may change."}
        )

    result = await explain_remote_command(
        task_id="execution-1",
        command={"argv": ["npm", "test"], "cwd": ".", "credential_profiles": ["registry-read"]},
        script_excerpt="test script body",
        secrets_manager=object(),
        caller=caller,
    )
    assert result["summary"] == "Runs tests"
    assert captured["model_id"] == "google/gemini-3.5-flash-lite"
    assert captured["fallback_models"] == []
    assert len(captured["message_history"]) == 1
    serialized = repr(captured["message_history"])
    assert "test script body" in serialized
    assert "Project focus" not in serialized
