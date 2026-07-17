# backend/tests/test_task_main_processor_tools.py
#
# Red-phase contract tests for Tasks V1 main-processor tool injection. These
# tests define the small helper seam that main_processor.py will call before the
# LLM request is sent. They avoid live Directus and model calls so the tool
# contract can be verified deterministically.

from __future__ import annotations

from unittest.mock import AsyncMock
import pytest

from backend.apps.ai.processing.task_runtime_tools import (
    TASK_TOOL_BLOCK,
    TASK_TOOL_COMPLETE,
    TASK_TOOL_CREATE,
    TASK_TOOL_MOVE,
    TASK_TOOL_UNBLOCK,
    TASK_TOOL_UPDATE,
    build_task_runtime_tools,
    merge_task_runtime_tools,
)
from backend.apps.ai.processing.task_tool_executor import (
    _check_expected_version,
    assigned_app_ids_with_task_app_for_explicit_skill,
    execute_task_tool_call,
    explicit_task_app_skill_tool_name,
    is_legacy_task_runtime_tool_name,
    is_task_tool_name,
    should_suppress_task_runtime_tools_for_app_skill,
    task_app_skill_ids_from_message_text,
    task_app_skill_ids_from_user_override_skills,
    task_tool_name_variants,
)
from backend.apps.ai.processing.task_tool_context import resolve_task_tool_context
from backend.apps.ai.processing.task_tool_context import TaskToolContext
from backend.apps.ai.llm_providers.openai_shared import _sanitize_schema_for_llm_providers
from backend.shared.python_utils.thought_signature import serialize_thought_signature
from backend.core.api.app.services.user_task_service import UserTaskConflictError


def _tool_names(tools: list[dict]) -> set[str]:
    return {str(tool["function"]["name"]) for tool in tools}


@pytest.mark.asyncio
async def test_create_only_task_tool_is_injected_when_chat_has_no_visible_tasks() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = []

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Please split this launch into tasks.",
    )
    tools = build_task_runtime_tools(context)

    assert _tool_names(tools) == {TASK_TOOL_CREATE}
    task_methods.list_tasks.assert_awaited_once_with("user-1", chat_id="chat-1", limit=50)


@pytest.mark.asyncio
async def test_attached_tasks_enable_update_reorder_block_complete_and_move_tools() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = [
        {
            "task_id": "TASK-101",
            "short_id": "TASK-101",
            "primary_chat_id": "chat-1",
            "status": "todo",
            "version": 4,
        }
    ]

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Update the task list.",
    )
    names = _tool_names(build_task_runtime_tools(context))

    assert {
        TASK_TOOL_CREATE,
        TASK_TOOL_UPDATE,
        TASK_TOOL_BLOCK,
        TASK_TOOL_COMPLETE,
        TASK_TOOL_MOVE,
    }.issubset(names)
    assert "task_reorder" not in names
    assert TASK_TOOL_UNBLOCK not in names


@pytest.mark.asyncio
async def test_bare_short_id_mentions_resolve_active_chat_tasks_as_attached() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = []
    task_methods.get_task_by_short_id.return_value = {
        "task_id": "task-1",
        "short_id": "TASK-101",
        "primary_chat_id": "chat-1",
        "status": "todo",
        "version": 1,
    }

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Update TASK-101 to mention final review.",
    )
    names = _tool_names(build_task_runtime_tools(context))

    assert [task["short_id"] for task in context.attached_tasks] == ["TASK-101"]
    assert TASK_TOOL_UPDATE in names
    task_methods.get_task_by_short_id.assert_awaited_once_with("TASK-101", "user-1")


@pytest.mark.asyncio
async def test_blocked_attached_tasks_enable_unblock_tool() -> None:
    task_methods = AsyncMock()
    task_methods.list_tasks.return_value = [
        {
            "task_id": "TASK-202",
            "short_id": "TASK-202",
            "primary_chat_id": "chat-1",
            "status": "blocked",
            "version": 2,
        }
    ]

    context = await resolve_task_tool_context(
        task_methods=task_methods,
        user_id="user-1",
        chat_id="chat-1",
        message_text="Unblock anything waiting on me.",
    )
    names = _tool_names(build_task_runtime_tools(context))

    assert TASK_TOOL_UNBLOCK in names
    assert TASK_TOOL_BLOCK not in names


def test_task_runtime_tools_merge_with_existing_main_processor_tools_without_duplicates() -> None:
    existing_tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": TASK_TOOL_CREATE,
                "description": "Existing duplicate should not be kept.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
    ]
    task_tools = [
        {
            "type": "function",
            "function": {
                "name": TASK_TOOL_CREATE,
                "description": "Create a task.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]

    merged = merge_task_runtime_tools(existing_tools, task_tools)

    assert [tool["function"]["name"] for tool in merged] == ["web_search", TASK_TOOL_CREATE]


def test_reorder_tool_is_not_advertised_until_atomic_persistence_exists() -> None:
    names = _tool_names(build_task_runtime_tools(TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[{"task_id": "TASK-1", "status": "todo", "version": 1}],
    )))

    assert "task_reorder" not in names


def test_task_tool_expected_version_is_required_before_mutation() -> None:
    with pytest.raises(UserTaskConflictError, match="version is required"):
        _check_expected_version({"task_id": "task-1", "version": 2}, None)


def test_task_tool_allow_list_preserves_provider_emitted_name() -> None:
    allowed_names = task_tool_name_variants(TASK_TOOL_CREATE)

    assert TASK_TOOL_CREATE in allowed_names
    assert "task-create" in allowed_names
    assert is_task_tool_name(TASK_TOOL_CREATE)
    assert is_task_tool_name("task-create")


def test_tasks_app_skill_names_are_not_legacy_task_runtime_tools() -> None:
    assert is_legacy_task_runtime_tool_name("task_create")
    assert is_legacy_task_runtime_tool_name("task-create")
    assert not is_legacy_task_runtime_tool_name("tasks_create")
    assert not is_legacy_task_runtime_tool_name("tasks-create")


def test_explicit_tasks_app_skill_suppresses_legacy_task_runtime_tools() -> None:
    assert should_suppress_task_runtime_tools_for_app_skill(
        {"tasks-create"},
        user_requested_skills_only=True,
    )
    assert should_suppress_task_runtime_tools_for_app_skill(
        {"tasks-search"},
        user_requested_skills_only=True,
    )
    assert not should_suppress_task_runtime_tools_for_app_skill(
        {"tasks-create"},
        user_requested_skills_only=False,
    )
    assert not should_suppress_task_runtime_tools_for_app_skill(
        {"web-search"},
        user_requested_skills_only=True,
    )


def test_tasks_app_skill_mentions_resolve_from_backend_wire_syntax() -> None:
    assert task_app_skill_ids_from_message_text("@skill:tasks:create create three tasks") == {"tasks-create"}
    assert task_app_skill_ids_from_message_text("@skill:tasks:search find launch tasks") == {"tasks-search"}
    assert task_app_skill_ids_from_message_text("@skill:tasks:unknown do something") == set()


def test_tasks_app_skill_mentions_resolve_from_user_overrides() -> None:
    assert task_app_skill_ids_from_user_override_skills([("tasks", "create")]) == {"tasks-create"}
    assert task_app_skill_ids_from_user_override_skills([("tasks", "search")]) == {"tasks-search"}
    assert task_app_skill_ids_from_user_override_skills([("web", "search"), ("tasks", "unknown")]) == set()


def test_explicit_tasks_app_skill_expands_assigned_app_allowlist() -> None:
    assert assigned_app_ids_with_task_app_for_explicit_skill(
        ["sheets"],
        {"tasks-create"},
    ) == ["sheets", "tasks"]
    assert assigned_app_ids_with_task_app_for_explicit_skill(
        ["tasks"],
        {"tasks-search"},
    ) == ["tasks"]
    assert assigned_app_ids_with_task_app_for_explicit_skill(None, {"tasks-create"}) is None
    assert assigned_app_ids_with_task_app_for_explicit_skill(["sheets"], set()) == ["sheets"]


def test_explicit_tasks_app_skill_accepts_legacy_singular_tool_aliases() -> None:
    assert explicit_task_app_skill_tool_name("task_create", {"tasks-create"}) == "tasks-create"
    assert explicit_task_app_skill_tool_name("task-search", {"tasks-search"}) == "tasks-search"
    assert explicit_task_app_skill_tool_name("task_create", {"tasks-search"}) == "task-create"


def test_task_tool_schema_sanitizer_removes_google_unsupported_additional_properties() -> None:
    schema = build_task_runtime_tools(TaskToolContext(user_id="user-1", chat_id="chat-1"))[0]["function"]["parameters"]

    sanitized = _sanitize_schema_for_llm_providers(schema)

    assert "additionalProperties" not in sanitized


def test_google_thought_signature_serializer_handles_candidate_fallback_values() -> None:
    assert serialize_thought_signature(b"signature") == "c2lnbmF0dXJl"
    assert serialize_thought_signature("already-encoded") == "already-encoded"
    assert serialize_thought_signature(None) is None


@pytest.mark.asyncio
async def test_client_persisted_task_update_sequences_later_completion_in_same_turn() -> None:
    stored_jobs: list[dict] = []

    class FakeCache:
        async def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
            if key.startswith("user_task_update_job:"):
                stored_jobs.append(value)
            return True

    class FakeEncryption:
        async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str) -> tuple[str, int]:
            return f"cipher:{plaintext}", 1

    directus_service = AsyncMock()
    directus_service.user_task.update_task_if_version = AsyncMock()
    context = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "chat-1",
                "status": "todo",
                "version": 1,
            }
        ],
    )

    update_result = await execute_task_tool_call(
        tool_name=TASK_TOOL_UPDATE,
        args={"task_id": "TASK-1", "expected_version": 1, "title": "Final review"},
        context=context,
        cache_service=FakeCache(),
        directus_service=directus_service,
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    complete_result = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=FakeCache(),
        directus_service=directus_service,
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert update_result["status"] == "pending_client_persistence"
    assert complete_result["status"] == "pending_client_persistence"
    assert [job["expected_task_version"] for job in stored_jobs] == [1, 2]
    assert context.attached_tasks[0]["version"] == 3
    assert context.attached_tasks[0]["status"] == "done"
    directus_service.user_task.update_task_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_move_job_includes_source_task_chat_for_client_lookup() -> None:
    stored_jobs: list[dict] = []

    class FakeCache:
        async def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
            if key.startswith("user_task_update_job:"):
                stored_jobs.append(value)
            return True

    class FakeEncryption:
        async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str) -> tuple[str, int]:
            return f"cipher:{plaintext}", 1

    context = TaskToolContext(
        user_id="user-1",
        chat_id="target-chat",
        referenced_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "source-chat",
                "status": "todo",
                "version": 1,
            }
        ],
    )

    result = await execute_task_tool_call(
        tool_name=TASK_TOOL_MOVE,
        args={"task_id": "TASK-1", "target_chat_id": "target-chat", "expected_version": 1},
        context=context,
        cache_service=FakeCache(),
        directus_service=AsyncMock(),
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert result["status"] == "pending_client_persistence"
    assert stored_jobs[0]["source_task_chat_id"] == "source-chat"
    assert stored_jobs[0]["chat_id"] == "target-chat"


@pytest.mark.asyncio
async def test_repeated_client_persisted_task_calls_are_same_turn_noops() -> None:
    stored_jobs: list[dict] = []

    class FakeCache:
        async def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
            if key.startswith("user_task_update_job:"):
                stored_jobs.append(value)
            return True

    class FakeEncryption:
        async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str) -> tuple[str, int]:
            return f"cipher:{plaintext}", 1

    directus_service = AsyncMock()
    directus_service.user_task.update_task_if_version = AsyncMock()
    context = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "chat-1",
                "title": "Draft checklist",
                "status": "todo",
                "version": 1,
            }
        ],
    )
    cache = FakeCache()
    encryption = FakeEncryption()

    first_update = await execute_task_tool_call(
        tool_name=TASK_TOOL_UPDATE,
        args={"task_id": "TASK-1", "expected_version": 1, "title": "Final review"},
        context=context,
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=encryption,
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    repeated_update = await execute_task_tool_call(
        tool_name=TASK_TOOL_UPDATE,
        args={"task_id": "TASK-1", "expected_version": 1, "title": "Final review"},
        context=context,
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=encryption,
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    first_complete = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=encryption,
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    repeated_complete = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=encryption,
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    same_version_repeated_complete = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 3},
        context=context,
        cache_service=cache,
        directus_service=directus_service,
        encryption_service=encryption,
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert first_update["status"] == "pending_client_persistence"
    assert repeated_update == {"status": "already_applied", "operation": "update", "task_id": "task-1", "version": 2}
    assert first_complete["status"] == "pending_client_persistence"
    assert repeated_complete == {"status": "already_applied", "operation": "complete", "task_id": "task-1", "version": 3}
    assert same_version_repeated_complete == {"status": "already_applied", "operation": "complete", "task_id": "task-1", "version": 3}
    assert [job["expected_task_version"] for job in stored_jobs] == [1, 2]
    directus_service.user_task.update_task_if_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_direct_task_complete_returns_event_noop() -> None:
    directus_service = AsyncMock()
    directus_service.user_task.get_task = AsyncMock(return_value={"task_id": "task-1", "primary_chat_id": "chat-1"})
    directus_service.user_task.list_tasks = AsyncMock(return_value=[])
    directus_service.user_task.update_task_if_version = AsyncMock(
        return_value={
            "task_id": "task-1",
            "short_id": "TASK-1",
            "primary_chat_id": "chat-1",
            "status": "done",
            "version": 2,
        }
    )
    context = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "chat-1",
                "status": "todo",
                "version": 1,
            }
        ],
    )

    first_complete = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=AsyncMock(),
        directus_service=directus_service,
        encryption_service=AsyncMock(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    repeated_complete = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=AsyncMock(),
        directus_service=directus_service,
        encryption_service=AsyncMock(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )
    malformed_version_retry = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": "latest"},
        context=context,
        cache_service=AsyncMock(),
        directus_service=directus_service,
        encryption_service=AsyncMock(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert first_complete["status"] == "ok"
    assert first_complete["event"]["event_type"] == "completed"
    assert repeated_complete["status"] == "ok"
    assert repeated_complete["event"]["event_type"] == "completed"
    assert repeated_complete["updated_task"]["version"] == 2
    assert malformed_version_retry["status"] == "ok"
    assert malformed_version_retry["event"]["event_type"] == "completed"
    directus_service.user_task.update_task_if_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_task_complete_uses_store_already_applied_state_after_conflict() -> None:
    completed_task = {
        "task_id": "task-1",
        "short_id": "TASK-1",
        "primary_chat_id": "chat-1",
        "status": "done",
        "version": 2,
    }
    directus_service = AsyncMock()
    directus_service.user_task.get_task = AsyncMock(return_value=completed_task)
    directus_service.user_task.list_tasks = AsyncMock(return_value=[])
    directus_service.user_task.update_task_if_version = AsyncMock(return_value=None)
    context = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "chat-1",
                "status": "todo",
                "version": 1,
            }
        ],
    )

    result = await execute_task_tool_call(
        tool_name=TASK_TOOL_COMPLETE,
        args={"task_id": "TASK-1", "expected_version": 1},
        context=context,
        cache_service=AsyncMock(),
        directus_service=directus_service,
        encryption_service=AsyncMock(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert result["status"] == "ok"
    assert result["event"]["event_type"] == "completed"
    assert result["updated_task"]["version"] == 2
    assert context.attached_tasks[0]["status"] == "done"


@pytest.mark.asyncio
async def test_task_tool_accepts_model_formatted_task_id_and_version() -> None:
    stored_jobs: list[dict] = []

    class FakeCache:
        async def set(self, key: str, value: dict, ttl: int | None = None) -> bool:
            if key.startswith("user_task_update_job:"):
                stored_jobs.append(value)
            return True

    class FakeEncryption:
        async def encrypt_with_user_key(self, plaintext: str, vault_key_id: str) -> tuple[str, int]:
            return f"cipher:{plaintext}", 1

    context = TaskToolContext(
        user_id="user-1",
        chat_id="chat-1",
        attached_tasks=[
            {
                "task_id": "task-1",
                "short_id": "TASK-1",
                "primary_chat_id": "chat-1",
                "title": "Draft checklist",
                "status": "todo",
                "version": 1,
            }
        ],
    )

    result = await execute_task_tool_call(
        tool_name=TASK_TOOL_UPDATE,
        args={"task_id": "`TASK-1`", "expected_version": "version 1", "title": "Final review"},
        context=context,
        cache_service=FakeCache(),
        directus_service=AsyncMock(),
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key-1",
        message_id="message-1",
    )

    assert result["status"] == "pending_client_persistence"
    assert stored_jobs[0]["expected_task_version"] == 1
