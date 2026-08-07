# backend/tests/test_sub_chat_orchestration.py
#
# Unit coverage for sub-chat fan-out limits.
# These tests validate the backend-owned guardrails without invoking real LLM,
# Directus, or Celery execution. The frontend E2E spec covers the inline
# confirmation UI that is shown for large approved batches.

import asyncio

import pytest

from backend.apps.ai import sub_chat_orchestration
from backend.apps.ai.sub_chat_orchestration import (
    MAX_DIRECT_SUB_CHATS_PER_PARENT,
    MAX_TEMPLATE_EXPANSION_ITEMS,
    consume_pending_sub_chat_confirmation,
    create_sub_chat_records,
    ensure_orchestration_envelope,
    expand_sub_chat_requests,
    resolve_sub_chat_depth,
    validate_sub_chat_capacity,
)
from backend.apps.ai.processing.main_processor import (
    _quote_ai_iteration_credits,
    _skill_operation_id,
)


def test_template_expansion_is_capped() -> None:
    expanded = expand_sub_chat_requests(
        [
            {
                "prompt_template": "Research {x}",
                "list": [str(index) for index in range(MAX_TEMPLATE_EXPANSION_ITEMS + 5)],
            }
        ],
        max_template_items=MAX_TEMPLATE_EXPANSION_ITEMS,
    )

    assert len(expanded) == MAX_TEMPLATE_EXPANSION_ITEMS
    assert expanded[0]["prompt"] == "Research 0"
    assert expanded[-1]["prompt"] == f"Research {MAX_TEMPLATE_EXPANSION_ITEMS - 1}"


def test_template_expansion_cannot_bypass_root_cap_for_sequential_queues() -> None:
    expanded = expand_sub_chat_requests([
        {
            "prompt_template": "Research {x}",
            "list": [str(index) for index in range(MAX_TEMPLATE_EXPANSION_ITEMS + 5)],
        }
    ])

    assert len(expanded) == MAX_TEMPLATE_EXPANSION_ITEMS
    assert expanded[-1]["prompt"] == f"Research {MAX_TEMPLATE_EXPANSION_ITEMS - 1}"


def test_capacity_allows_parallel_requests_within_concurrent_limit() -> None:
    result = validate_sub_chat_capacity(existing_count=0, requested_count=20)

    assert result["allowed"] is True
    assert result["remaining"] == 0


def test_capacity_rejects_parallel_requests_above_concurrent_limit() -> None:
    result = validate_sub_chat_capacity(existing_count=0, requested_count=21)

    assert result["allowed"] is False
    assert result["remaining"] == MAX_DIRECT_SUB_CHATS_PER_PARENT
    assert str(MAX_DIRECT_SUB_CHATS_PER_PARENT) in result["message"]
    assert "concurrent" in result["message"]


def test_capacity_counts_existing_children_against_root_limit() -> None:
    result = validate_sub_chat_capacity(existing_count=19, requested_count=2)

    assert result["allowed"] is False
    assert result["remaining"] == 1


class _FailingChatStore:
    async def create_chat_in_directus(self, payload: dict) -> tuple[None, bool]:
        assert "title" not in payload
        return None, False


class _FailingDirectus:
    chat = _FailingChatStore()


def test_failed_child_shell_preparation_dispatches_no_billable_work(monkeypatch) -> None:
    dispatched: list[str] = []

    async def fake_dispatch(**kwargs) -> str:
        dispatched.append(kwargs["sub_chat"]["id"])
        return "task-id"

    monkeypatch.setattr(sub_chat_orchestration, "dispatch_sub_chat_task", fake_dispatch)
    request_data = type("Request", (), {
        "user_id_hash": "hash",
        "chat_id": "root-chat",
        "user_id": "user",
        "is_incognito": False,
        "is_external": False,
        "user_preferences": {},
    })()
    children = [{"id": "child-1", "prompt": "private prompt", "user_message_id": "message-1"}]

    with pytest.raises(RuntimeError, match="child.*persist"):
        asyncio.run(
            sub_chat_orchestration.create_and_dispatch_sub_chats(
                directus_service=_FailingDirectus(),
                request_data=request_data,
                skill_config_dict={},
                spawned_sub_chats=children,
                log_prefix="test",
            )
        )

    assert dispatched == []


def test_missing_child_orchestration_envelope_fails_closed_at_maximum_depth() -> None:
    request_data = type("Request", (), {
        "is_sub_chat": True,
        "orchestration_id": None,
        "root_chat_id": None,
        "root_turn_id": None,
        "orchestration_dispatch_token": None,
        "sub_chat_depth": 0,
    })()

    assert resolve_sub_chat_depth(request_data) == 2


def test_continuation_cannot_create_orchestration_envelope() -> None:
    request_data = type("Request", (), {
        "is_sub_chat": False,
        "is_sub_chat_continuation": True,
    })()

    with pytest.raises(RuntimeError, match="continuations"):
        ensure_orchestration_envelope(request_data)


def test_root_orchestration_identity_is_stable_across_reconstructed_retries() -> None:
    def request() -> object:
        return type("Request", (), {
            "is_sub_chat": False,
            "is_sub_chat_continuation": False,
            "is_focus_mode_continuation": False,
            "is_app_settings_memories_continuation": False,
            "is_connected_account_permission_continuation": False,
            "orchestration_id": None,
            "root_chat_id": None,
            "root_turn_id": None,
            "chat_id": "11111111-1111-4111-8111-111111111111",
            "message_id": "22222222-2222-4222-8222-222222222222",
            "user_id_hash": "owner-hash",
            "sub_chat_depth": 0,
        })()

    first = request()
    second = request()
    ensure_orchestration_envelope(first)
    ensure_orchestration_envelope(second)

    assert first.orchestration_id == second.orchestration_id
    assert first.root_turn_id == second.root_turn_id


class _Response:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return {"data": self._data}


class _CapturingTransactionDirectus:
    base_url = "http://cms:8055"

    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def _make_api_request(self, method: str, url: str, **kwargs) -> _Response:
        self.requests.append({"method": method, "url": url, **kwargs})
        return _Response({"accepted": True})


def test_child_batch_is_prepared_without_private_content_before_dispatch(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    directus = _CapturingTransactionDirectus()
    request_data = type("Request", (), {
        "chat_id": "11111111-1111-4111-8111-111111111111",
        "message_id": "root-message",
        "user_id_hash": "hash",
        "team_id_hash": None,
        "is_sub_chat": False,
        "is_sub_chat_continuation": False,
        "is_focus_mode_continuation": False,
        "is_app_settings_memories_continuation": False,
        "is_connected_account_permission_continuation": False,
        "orchestration_id": None,
        "root_chat_id": None,
        "root_turn_id": None,
        "sub_chat_depth": 0,
        "orchestration_dispatch_token": None,
        "orchestration_descendant_limit": 3,
        "orchestration_credit_limit": 2_000,
        "orchestration_approved": False,
    })()
    child = {
        "id": "22222222-2222-4222-8222-222222222222",
        "user_message_id": "child-message",
        "prompt": "private prompt",
        "budget_limit": 500,
    }

    tokens = asyncio.run(create_sub_chat_records(
        directus_service=directus,
        request_data=request_data,
        spawned_sub_chats=[child],
        log_prefix="test",
    ))

    assert [request["json"]["operation"] for request in directus.requests] == [
        "create_root",
        "prepare_batch",
    ]
    prepared_child = directus.requests[1]["json"]["data"]["children"][0]
    assert set(prepared_child) == {
        "child_chat_id",
        "user_message_id",
        "dispatch_token",
        "budget_limit",
    }
    assert "private prompt" not in repr(directus.requests)
    assert tokens[child["id"]] == prepared_child["dispatch_token"]

    replay_tokens = asyncio.run(create_sub_chat_records(
        directus_service=directus,
        request_data=request_data,
        spawned_sub_chats=[child],
        log_prefix="test",
    ))
    assert replay_tokens == tokens


def test_skill_operation_identity_distinguishes_repeated_tool_calls() -> None:
    first = _skill_operation_id("web", "search", "task-1", "tool-call-1", 0)
    second = _skill_operation_id("web", "search", "task-1", "tool-call-2", 0)

    assert first != second
    assert first == _skill_operation_id("web", "search", "task-1", "tool-call-1", 0)


def test_ai_iteration_quote_uses_input_and_maximum_output_tokens(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.apps.ai.processing.main_processor.config_manager.get_model_pricing",
        lambda provider_id, model_id: {
            "pricing": {
                "tokens": {
                    "input": {"per_credit_unit": 10},
                    "output": {"per_credit_unit": 5},
                }
            },
            "features": {"max_output_tokens": 100},
        },
    )

    quote = _quote_ai_iteration_credits(
        model_id="provider/model",
        system_prompt="system",
        message_history=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "search"}}],
    )

    assert quote >= 20


def test_pending_confirmation_is_consumed_exactly_once() -> None:
    class AtomicCache:
        def __init__(self) -> None:
            self.value: dict | None = {"private": "context"}

        async def get_and_delete(self, key: str) -> dict | None:
            value = self.value
            self.value = None
            return value

    async def consume_twice() -> list[dict | None]:
        cache = AtomicCache()
        return await asyncio.gather(*(
            consume_pending_sub_chat_confirmation(
                cache_service=cache,
                chat_id="chat-1",
                task_id="task-1",
            )
            for _ in range(2)
        ))

    results = asyncio.run(consume_twice())

    assert sum(result is not None for result in results) == 1
