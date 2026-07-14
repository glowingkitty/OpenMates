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
    execute_task_tool_call,
    is_task_tool_name,
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

    assert first_update["status"] == "pending_client_persistence"
    assert repeated_update == {"status": "already_applied", "operation": "update", "task_id": "task-1", "version": 2}
    assert first_complete["status"] == "pending_client_persistence"
    assert repeated_complete == {"status": "already_applied", "operation": "complete", "task_id": "task-1", "version": 3}
    assert [job["expected_task_version"] for job in stored_jobs] == [1, 2]
    directus_service.user_task.update_task_if_version.assert_not_awaited()
