"""State-machine tests for client-executed Project file operations."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.project_file_operation_service import (
    PROJECT_FILE_OPERATION_PAUSE_SECONDS,
    PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS,
    ProjectFileOperationError,
    ProjectFileOperationService,
)


class MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.values[key] = value
        if ttl is not None:
            self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> bool:
        self.values.pop(key, None)
        return True

    async def publish_event(self, channel: str, event: dict[str, Any]) -> bool:
        self.published.append((channel, event))
        return True


def focus() -> dict[str, Any]:
    return {
        "project_id": "project-1",
        "focus_id": "focus-1",
        "team_id": None,
        "source_id": "source-1",
    }


async def create_read(service: ProjectFileOperationService, *, now: int = 100) -> dict[str, Any]:
    return await service.create_operation(
        user_id="user-1",
        chat_id="chat-1",
        project_focus=focus(),
        operation="read_text",
        arguments={"path": "README.md"},
        continuation_task_id="continuation-1",
        message_id="message-1",
        operation_id="operation-1",
        now=now,
    )


# contract-test: supporting surface=gui.web assertions=projects.files.executor-wait,projects.files.no-server-decryption-authority
@pytest.mark.asyncio
async def test_available_event_is_metadata_only_and_claim_is_owner_chat_scoped() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    summary = await create_read(service)

    assert summary["operation_id"] == "operation-1"
    event = cache.published[-1][1]
    assert event["event_for_client"] == "project_file_operation_available"
    assert "arguments" not in event["payload"]
    assert "README.md" not in str(event)

    with pytest.raises(ProjectFileOperationError, match="operation_not_found"):
        await service.claim(
            user_id="user-2",
            device_fingerprint_hash="device-a",
            operation_id="operation-1",
            chat_id="chat-1",
            project_id="project-1",
            now=101,
        )
    with pytest.raises(ProjectFileOperationError, match="operation_scope_mismatch"):
        await service.claim(
            user_id="user-1",
            device_fingerprint_hash="device-a",
            operation_id="operation-1",
            chat_id="other-chat",
            project_id="project-1",
            now=101,
        )

    claim = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    assert claim["arguments"] == {"path": "README.md"}
    with pytest.raises(ProjectFileOperationError, match="operation_already_claimed"):
        await service.claim(
            user_id="user-1",
            device_fingerprint_hash="device-b",
            operation_id="operation-1",
            chat_id="chat-1",
            project_id="project-1",
            now=102,
        )


# contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.files.short-write-turn,projects.files.expected-base
@pytest.mark.asyncio
async def test_awaiting_approval_releases_lease_and_fresh_claim_revalidates() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await service.create_operation(
        user_id="user-1",
        chat_id="chat-1",
        project_focus=focus(),
        operation="update_file",
        arguments={"path": "README.md", "expected_base": "a" * 64, "patch": "@@ -1 +1 @@\n-old\n+new"},
        continuation_task_id="continuation-1",
        operation_id="operation-1",
        now=100,
    )
    first = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    awaiting = await service.settle(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        lease_token=first["lease_token"],
        lease_generation=first["lease_generation"],
        status="awaiting_approval",
        result={"proposal_commitment": "b" * 64},
        now=102,
    )
    assert awaiting["job"]["state"] == "AWAITING_APPROVAL"
    assert "lease_token" not in awaiting["job"]

    second = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-b",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=103,
    )
    assert second["lease_generation"] == first["lease_generation"] + 1
    with pytest.raises(ProjectFileOperationError, match="proposal_commitment_mismatch"):
        await service.settle(
            user_id="user-1",
            device_fingerprint_hash="device-b",
            operation_id="operation-1",
            chat_id="chat-1",
            project_id="project-1",
            lease_token=second["lease_token"],
            lease_generation=second["lease_generation"],
            status="completed",
            result={"proposal_commitment": "c" * 64},
            now=104,
        )


# contract-test: supporting surface=gui.web assertions=projects.files.wait-deadlines,projects.files.wait-email,projects.files.wait-expiry
@pytest.mark.asyncio
async def test_fixed_deadlines_do_not_reset_on_claim_and_expire_without_timer() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await create_read(service, now=100)
    claim = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=500,
    )
    assert claim["expires_at"] == 100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS

    # The lease expires without counting as file progress. At ten minutes the
    # same episode may reserve exactly one generic reminder.
    assert await service.mark_email_sent(
        user_id="user-1",
        operation_id="operation-1",
        episode_id=(await service.get_job(user_id="user-1", operation_id="operation-1"))["episode_id"],
        now=100 + PROJECT_FILE_OPERATION_WAIT_EMAIL_SECONDS,
    )
    assert not await service.mark_email_sent(
        user_id="user-1",
        operation_id="operation-1",
        episode_id=(await service.get_job(user_id="user-1", operation_id="operation-1"))["episode_id"],
        now=701,
    )

    with pytest.raises(ProjectFileOperationError, match="paused_requires_explicit_resume"):
        await service.claim(
            user_id="user-1",
            device_fingerprint_hash="device-b",
            operation_id="operation-1",
            chat_id="chat-1",
            project_id="project-1",
            now=100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS,
        )
    job = await service.get_job(user_id="user-1", operation_id="operation-1")
    assert job["state"] == "PAUSED_REQUIRES_EXPLICIT_RESUME"


# contract-test: supporting surface=gui.web assertions=projects.files.wait-deadlines,projects.files.wait-result-reconciliation
@pytest.mark.asyncio
async def test_episode_fence_blocks_stale_callbacks_and_user_rejection_finishes() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await service.create_operation(
        user_id="user-1",
        chat_id="chat-1",
        project_focus=focus(),
        operation="create_file",
        arguments={"path": "new.txt", "expected_base": None, "content": "hello"},
        continuation_task_id="continuation-1",
        operation_id="operation-1",
        now=100,
    )
    claim = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    await service.settle(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        lease_token=claim["lease_token"],
        lease_generation=claim["lease_generation"],
        status="awaiting_approval",
        result={"proposal_commitment": "d" * 64},
        now=102,
    )
    rejection = await service.reject_approval(
        user_id="user-1",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=103,
    )
    job = rejection["job"]
    assert job["result_status"] == "user_declined"
    replayed_rejection = await service.reject_approval(
        user_id="user-1",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=104,
    )
    assert replayed_rejection["replayed"] is True
    assert not await service.pause_if_due(
        user_id="user-1",
        operation_id="operation-1",
        episode_id="stale-episode",
        now=100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS,
    )


# contract-test: supporting surface=gui.web assertions=projects.files.wait-result-reconciliation,projects.files.wait-expiry
@pytest.mark.asyncio
async def test_late_result_is_recorded_once_without_resuming_paused_operation() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await create_read(service, now=100)
    claim = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    job = await service.get_job(user_id="user-1", operation_id="operation-1")
    assert await service.pause_if_due(
        user_id="user-1",
        operation_id="operation-1",
        episode_id=job["episode_id"],
        now=100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS,
    )

    late = await service.settle(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        lease_token=claim["lease_token"],
        lease_generation=claim["lease_generation"],
        status="completed",
        result={"content": "arrived after pause"},
        now=100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS + 1,
    )
    assert late["late_after_pause"] is True
    assert late["replayed"] is False
    assert late["job"]["state"] == "PAUSED_REQUIRES_EXPLICIT_RESUME"
    assert late["job"]["late_result_status"] == "completed"
    assert "arrived after pause" not in str(cache.values)

    replay = await service.settle(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        lease_token=claim["lease_token"],
        lease_generation=claim["lease_generation"],
        status="completed",
        result={"content": "retry transport payload"},
        now=100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS + 2,
    )
    assert replay["replayed"] is True
    assert "retry transport payload" not in str(cache.values)


# contract-test: supporting surface=gui.web assertions=projects.files.wait-result-reconciliation
@pytest.mark.asyncio
async def test_terminal_result_retry_is_idempotent_and_device_scoped() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await create_read(service)
    claim = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    kwargs = {
        "user_id": "user-1",
        "device_fingerprint_hash": "device-a",
        "operation_id": "operation-1",
        "chat_id": "chat-1",
        "project_id": "project-1",
        "lease_token": claim["lease_token"],
        "lease_generation": claim["lease_generation"],
        "status": "completed",
        "result": {"content": "hello"},
    }
    first = await service.settle(**kwargs, now=102)
    retry = await service.settle(**kwargs, now=103)
    assert first["replayed"] is False
    assert retry["replayed"] is True

    with pytest.raises(ProjectFileOperationError, match="operation_already_completed"):
        await service.settle(
            **{**kwargs, "device_fingerprint_hash": "device-b"},
            now=104,
        )


# contract-test: supporting surface=cli assertions=projects.files.executor-wait,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_executor_deferral_releases_lease_without_resetting_episode() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await create_read(service, now=100)
    first = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=101,
    )
    deferred = await service.settle(
        user_id="user-1",
        device_fingerprint_hash="device-a",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        lease_token=first["lease_token"],
        lease_generation=first["lease_generation"],
        status="waiting_for_executor",
        result={"reason": "source_offline"},
        now=102,
    )
    assert deferred["deferred"] is True
    assert deferred["job"]["state"] == "WAITING_FOR_EXECUTOR"
    assert deferred["job"]["pause_at"] == 100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS
    assert "lease_token" not in deferred["job"]

    second = await service.claim(
        user_id="user-1",
        device_fingerprint_hash="device-b",
        operation_id="operation-1",
        chat_id="chat-1",
        project_id="project-1",
        now=200,
    )
    assert second["lease_generation"] == first["lease_generation"] + 1
    assert second["expires_at"] == 100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS


# contract-test: supporting surface=gui.web assertions=projects.files.expected-base,projects.files.write-policy-enforcement
@pytest.mark.parametrize(
    ("operation", "arguments", "code"),
    [
        ("create_file", {"path": "x", "content": "x"}, "invalid_create_file_arguments"),
        ("update_file", {"path": "x", "expected_base": None, "patch": "x"}, "invalid_update_file_arguments"),
        ("read_text", {"path": "../secret"}, "invalid_project_path"),
    ],
)
def test_mutation_and_path_preconditions_are_mandatory(
    operation: str,
    arguments: dict[str, Any],
    code: str,
) -> None:
    with pytest.raises(ProjectFileOperationError, match=code):
        ProjectFileOperationService._validate_arguments(operation, arguments)


# contract-test: supporting surface=cli assertions=projects.files.search-scoped,projects.files.search-consistent
def test_search_protocol_validates_target_mode_and_glob() -> None:
    ProjectFileOperationService._validate_arguments(
        "search",
        {
            "query": "TODO",
            "target": "content",
            "mode": "regex",
            "path": ".",
            "glob": "src/**/*.py",
            "max_results": 20,
        },
    )
    for arguments in (
        {"query": "x", "target": "both"},
        {"query": "x", "mode": "fuzzy"},
        {"query": "x", "glob": "../*.py"},
    ):
        with pytest.raises(ProjectFileOperationError, match="invalid_search_arguments"):
            ProjectFileOperationService._validate_arguments("search", arguments)


# contract-test: supporting surface=gui.web assertions=projects.files.wait-email,projects.files.wait-deadlines
@pytest.mark.asyncio
async def test_same_turn_operations_share_one_wait_episode_and_email() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    await create_read(service, now=100)
    await service.create_operation(
        user_id="user-1",
        chat_id="chat-1",
        project_focus=focus(),
        operation="list",
        arguments={"path": "."},
        continuation_task_id="continuation-2",
        message_id="message-1",
        operation_id="operation-2",
        now=200,
    )
    first = await service.get_job(user_id="user-1", operation_id="operation-1")
    second = await service.get_job(user_id="user-1", operation_id="operation-2")
    assert first["episode_id"] == second["episode_id"]
    assert second["pause_at"] == 100 + PROJECT_FILE_OPERATION_PAUSE_SECONDS
    assert await service.mark_email_sent(
        user_id="user-1", operation_id="operation-1",
        episode_id=first["episode_id"], now=700,
    )
    assert not await service.mark_email_sent(
        user_id="user-1", operation_id="operation-2",
        episode_id=second["episode_id"], now=700,
    )


# contract-test: supporting surface=cli assertions=projects.files.automatic-recovery,projects.files.conflict-decision
@pytest.mark.asyncio
async def test_conflict_recovery_budget_is_per_turn_source_and_opaque_file() -> None:
    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    for attempt in range(3):
        operation_id = f"update-{attempt}"
        await service.create_operation(
            user_id="user-1", chat_id="chat-1", project_focus=focus(),
            operation="update_file",
            arguments={"path": "README.md", "expected_base": "a" * 64, "patch": "@@ -1 +1 @@\n-old\n+new"},
            continuation_task_id=operation_id, message_id="message-1",
            operation_id=operation_id, now=100 + attempt,
        )
        claim = await service.claim(
            user_id="user-1", device_fingerprint_hash="device-a",
            operation_id=operation_id, chat_id="chat-1", project_id="project-1",
            now=110 + attempt,
        )
        outcome = await service.settle(
            user_id="user-1", device_fingerprint_hash="device-a",
            operation_id=operation_id, chat_id="chat-1", project_id="project-1",
            lease_token=claim["lease_token"], lease_generation=claim["lease_generation"],
            status="conflict", result={"reason": "file_changed"}, now=120 + attempt,
        )
        assert outcome["result"]["conflict_recovery_attempt"] == attempt + 1

    with pytest.raises(ProjectFileOperationError, match="conflict_recovery_budget_exhausted"):
        await service.create_operation(
            user_id="user-1", chat_id="chat-1", project_focus=focus(),
            operation="update_file",
            arguments={"path": "README.md", "expected_base": "b" * 64, "patch": "@@ -1 +1 @@\n-old\n+new"},
            continuation_task_id="update-3", message_id="message-1",
            operation_id="update-3", now=130,
        )
    assert "README.md" not in " ".join(cache.values.keys())

    # A different file, or a fresh user turn, has an independent bounded budget.
    for path, message_id, operation_id in (
        ("OTHER.md", "message-1", "other-file"),
        ("README.md", "message-2", "fresh-turn"),
    ):
        await service.create_operation(
            user_id="user-1", chat_id="chat-1", project_focus=focus(),
            operation="update_file",
            arguments={"path": path, "expected_base": "c" * 64, "patch": "@@ -1 +1 @@\n-old\n+new"},
            continuation_task_id=operation_id, message_id=message_id,
            operation_id=operation_id, now=131,
        )
