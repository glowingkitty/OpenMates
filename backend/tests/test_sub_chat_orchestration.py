# contract-test-file: infrastructure
# backend/tests/test_sub_chat_orchestration.py
#
# Unit coverage for sub-chat fan-out limits.
# These tests validate the backend-owned guardrails without invoking real LLM,
# Directus, or Celery execution. The frontend E2E spec covers the inline
# confirmation UI that is shown for large approved batches.

import asyncio
import hashlib
import inspect
import json
import uuid as _uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai import sub_chat_focus_links as links
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
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationService,
)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_incognito_subchat_rejects_before_any_durable_write() -> None:
    class NoDirectusAccess:
        def __getattr__(self, name):
            raise AssertionError(f"Unexpected durable access: {name}")

    request = SimpleNamespace(is_incognito=True)
    with pytest.raises(RuntimeError, match="Incognito sub-chats cannot create durable"):
        asyncio.run(create_sub_chat_records(
            directus_service=NoDirectusAccess(),
            request_data=request,
            spawned_sub_chats=[{"id": "child-1", "prompt": "Research"}],
            log_prefix="[incognito-test]",
        ))

try:
    from backend.apps.ai.processing import main_processor
    from backend.apps.ai.processing.main_processor import (
        _max_affordable_ai_output_tokens,
        _orchestrated_ai_output_token_limit,
        _quote_ai_iteration_credits,
        _skill_operation_id,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


def test_parent_continuation_reserves_its_ai_charge_before_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    reservations = []

    class OrchestrationService:
        def __init__(self, directus_service):
            assert directus_service is directus

        async def execute(self, operation, payload):
            reservations.append((operation, payload))

    directus = object()
    request = SimpleNamespace(
        is_anonymous=False,
        is_sub_chat_continuation=True,
        orchestration_id="orchestration-id",
        user_id_hash="owner-hash",
        root_chat_id="root-chat-id",
        chat_id="root-chat-id",
        sub_chat_depth=0,
    )
    monkeypatch.setattr(main_processor, "SubChatOrchestrationService", OrchestrationService)
    monkeypatch.setattr(main_processor, "_quote_ai_iteration_credits", lambda **_kwargs: 56)

    operation_id = asyncio.run(main_processor._reserve_ai_iteration(
        task_id="continuation-task-id",
        iteration=0,
        model_id="google/gemini-test",
        system_prompt="Synthesize child reports",
        message_history=[{"role": "user", "content": "Compare reports"}],
        tools=None,
        output_token_limit=1000,
        request_data=request,
        directus_service=directus,
    ))

    assert operation_id == "ai-ask:continuation-task-id:main:iteration:0:model:google/gemini-test"
    assert reservations == [("reserve_operation", {
        "protocol_version": 1,
        "operation_id": operation_id,
        "charge_id": "ai-ask:continuation-task-id:main",
        "orchestration_id": "orchestration-id",
        "hashed_user_id": "owner-hash",
        "root_chat_id": "root-chat-id",
        "actual_chat_id": "root-chat-id",
        "depth": 0,
        "app_id": "ai",
        "skill_id": "ask",
        "phase": "inference_0",
        "quoted_credits": 56,
    })]


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


def test_template_expansion_preserves_spawn_ui_metadata() -> None:
    expanded = expand_sub_chat_requests([
        {
            "prompt_template": "Research {x}",
            "title": "Research {x}",
            "category": "legal_law",
            "icon": "scale",
            "list": ["GPAI obligations"],
        }
    ])

    assert expanded[0]["title"] == "Research GPAI obligations"
    assert expanded[0]["category"] == "legal_law"
    assert expanded[0]["icon"] == "scale"


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


def test_child_dispatch_inherits_active_focus_context() -> None:
    source = inspect.getsource(sub_chat_orchestration.dispatch_sub_chat_task)

    assert '"active_focus_id": child_active_focus_id(sub_chat, request_data)' in source


def test_orchestration_pauses_emit_usage_for_reservation_settlement() -> None:
    from backend.apps.ai.processing.main_processor import handle_main_processing

    source = inspect.getsource(handle_main_processing)
    confirmation_marker = source.index('"__sub_chat_confirmation_required__": True')
    sequential_marker = source.index(
        'yield {"__awaiting_sub_chats_completion__": True',
        confirmation_marker,
    )
    parallel_marker = source.index(
        'yield {"__awaiting_sub_chats_completion__": True',
        sequential_marker + 1,
    )

    for marker in (confirmation_marker, sequential_marker, parallel_marker):
        assert "yield usage" in source[marker - 300:marker]


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


def test_focus_activation_continuation_can_reuse_root_orchestration_envelope() -> None:
    request_data = type("Request", (), {
        "is_sub_chat": False,
        "is_sub_chat_continuation": False,
        "is_focus_mode_continuation": True,
        "is_app_settings_memories_continuation": False,
        "is_connected_account_permission_continuation": False,
        "orchestration_id": "orchestration-id",
        "root_chat_id": "root-chat-id",
        "root_turn_id": "root-turn-id",
        "root_user_message_id": "initial-root-message-id",
        "chat_id": "root-chat-id",
        "message_id": "focus-continuation-message-id",
        "user_id_hash": "owner-hash",
        "sub_chat_depth": 0,
    })()

    ensure_orchestration_envelope(request_data)

    assert request_data.orchestration_id == "orchestration-id"
    assert request_data.root_chat_id == "root-chat-id"
    assert request_data.root_turn_id == "root-turn-id"
    assert request_data.root_user_message_id == "initial-root-message-id"
    assert request_data.sub_chat_depth == 0


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
            "root_user_message_id": None,
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
    assert first.root_user_message_id == second.root_user_message_id == first.message_id


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
        "root_user_message_id": None,
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
        lambda provider_id, model_id, **_kwargs: {
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


def test_ai_iteration_quote_bounds_enabled_separate_cache_writes(monkeypatch) -> None:
    pricing = {
        "pricing": {"tokens": {
            "input": {"per_credit_unit": 1_000},
            "cache_write": {"per_credit_unit": 500},
            "cache_write_1h": {"per_credit_unit": 100},
            "output": {"per_credit_unit": 1_000},
        }},
        "cache_pricing": {"enabled": False, "write_billing": "separate"},
        "features": {"max_output_tokens": 1},
    }
    monkeypatch.setattr(main_processor.config_manager, "get_model_pricing", lambda *_args, **_kwargs: pricing)
    quote_args = {
        "model_id": "provider/model",
        "system_prompt": "s" * 1_000,
        "message_history": [],
        "tools": None,
    }
    legacy_quote = _quote_ai_iteration_credits(**quote_args)
    pricing["cache_pricing"]["enabled"] = True
    premium_quote = _quote_ai_iteration_credits(**quote_args)
    assert premium_quote > legacy_quote
    assert pricing["pricing"]["tokens"]["input"]["per_credit_unit"] == 1_000
    pricing["cache_pricing"]["write_billing"] = "included_in_input"
    assert _quote_ai_iteration_credits(**quote_args) == legacy_quote


def test_mistral_prompt_cache_key_is_scoped_to_user_team_and_chat(monkeypatch) -> None:
    monkeypatch.setattr(main_processor, "INTERNAL_API_SHARED_TOKEN", "test-secret-for-cache-key")
    request = SimpleNamespace(user_id_hash="user-alpha", team_id=None, chat_id="chat-alpha")
    key = main_processor._mistral_prompt_cache_key(request)
    assert key == main_processor._mistral_prompt_cache_key(request)
    assert len(key) == 64 and "user-alpha" not in key and "chat-alpha" not in key
    for change in ({"user_id_hash": "user-beta"}, {"team_id": "team-one"}, {"chat_id": "chat-beta"}):
        changed = SimpleNamespace(**{**vars(request), **change})
        assert main_processor._mistral_prompt_cache_key(changed) != key


def test_ai_iteration_quote_honors_orchestration_output_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.apps.ai.processing.main_processor.config_manager.get_model_pricing",
        lambda provider_id, model_id, **_kwargs: {
            "pricing": {
                "tokens": {
                    "input": {"per_credit_unit": 10},
                    "output": {"per_credit_unit": 5},
                }
            },
            "features": {"max_output_tokens": 100_000},
        },
    )

    limited_quote = _quote_ai_iteration_credits(
        model_id="provider/model",
        system_prompt="system",
        message_history=[{"role": "user", "content": "hello"}],
        tools=None,
        output_token_limit=8_192,
    )
    maximum_quote = _quote_ai_iteration_credits(
        model_id="provider/model",
        system_prompt="system",
        message_history=[{"role": "user", "content": "hello"}],
        tools=None,
    )

    assert limited_quote < maximum_quote


def test_ai_output_limit_fits_authoritative_remaining_orchestration_credits(monkeypatch) -> None:
    monkeypatch.setitem(
        _max_affordable_ai_output_tokens.__globals__,
        "_quote_ai_iteration_credits",
        lambda *, output_token_limit, **kwargs: 10 + output_token_limit,
    )
    kwargs = {
        "model_id": "provider/model",
        "system_prompt": "system",
        "message_history": [{"role": "user", "content": "hello"}],
        "tools": None,
    }

    fitted_limit = _max_affordable_ai_output_tokens(
        **kwargs,
        requested_output_token_limit=100,
        available_credits=59,
    )

    assert fitted_limit == 49


def test_orchestration_output_limit_preserves_lower_model_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.apps.ai.processing.main_processor.config_manager.get_model_pricing",
        lambda provider_id, model_id, **_kwargs: {"features": {"max_output_tokens": 1_024}},
    )

    assert _orchestrated_ai_output_token_limit("provider/model", "orchestration") == 1_024


def test_non_orchestrated_calls_keep_provider_default_output_limit() -> None:
    assert _orchestrated_ai_output_token_limit("provider/model", None) is None


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


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_verifier_envelope_is_server_claim_only():
    request = SimpleNamespace(is_sub_chat=False, sub_chat_depth=0, active_focus_id="web-research", chat_id="chat",
        is_sub_chat_continuation=True, orchestration_id="root", root_chat_id="chat", root_turn_id="turn")
    with pytest.raises(RuntimeError, match="continuations cannot"):
        ensure_orchestration_envelope(request)
    ensure_orchestration_envelope(request, verification_claim={"research_stage": "verification_due", "root_chat_id": "chat", "root_turn_id": "turn"})
    for change in ({"is_sub_chat": True}, {"sub_chat_depth": 1}, {"active_focus_id": None}, {"root_turn_id": None}):
        child = SimpleNamespace(**(vars(request) | change))
        with pytest.raises(RuntimeError, match="claimed root"):
            ensure_orchestration_envelope(child, verification_claim={"research_stage": "verification_due", "root_chat_id": "chat", "root_turn_id": "turn"})


# --- Sub-chat focus inheritance and Plan/Task links -------------------------


_PLAN = str(_uuid.uuid4())
_USER, _PARENT, _CHILD, _PROJECT = "user-1", "parent-chat", "child-chat", "proj-1"
_FOCUS_HASH = hashlib.sha256(b"project-proj1").hexdigest()


class _Cache:
    def __init__(self) -> None:
        self.data: dict = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ttl=None):
        self.data[key] = value
        return True

    async def get_keys_by_pattern(self, pattern):
        prefix = pattern.rstrip("*")
        return [key for key in self.data if key.startswith(prefix)]

    async def delete(self, key):
        return self.data.pop(key, None) is not None

    async def get_discovered_apps_metadata(self):
        focus = SimpleNamespace(id="research")
        return {"web": SimpleNamespace(focuses=[focus])}

    async def close(self):
        return None


class _Directus:
    def __init__(self, *, child_parent=_PARENT, task_owner=_USER, stored_tasks=None) -> None:
        self.child_parent = child_parent
        self.updates: list = []
        outer = self
        self.project = SimpleNamespace(
            get_project=self._project, get_project_settings=self._settings,
        )

        class _Chat:
            async def get_chat_metadata(self, chat_id, admin_required=False):
                hashed = hashlib.sha256(_USER.encode()).hexdigest()
                if chat_id == _PARENT:
                    return {"hashed_user_id": hashed}
                return {"hashed_user_id": hashed, "is_sub_chat": True, "parent_id": outer.child_parent}

        class _Task:
            async def get_task(self, task_id, user_id, team_id=None):
                if user_id != task_owner:
                    return None
                if stored_tasks is not None and task_id not in stored_tasks:
                    return None
                return {"id": "row-1", "task_id": task_id, "plan_id": _PLAN}

        self.chat, self.user_task = _Chat(), _Task()

    async def _project(self, *a, **k):
        return {"id": _PROJECT}

    async def _settings(self, *a, **k):
        return {"default_focus_id_hash": _FOCUS_HASH, "focus_instruction": "x"}

    async def update_item(self, collection, item_id, data, admin_required=False):
        self.updates.append((collection, item_id, data))


def _bind_parent(cache: _Cache, directus: _Directus) -> None:
    service = ProjectWriteAuthorizationService(directus, cache)
    binding = {
        "project_id": _PROJECT, "focus_id": "project-proj1", "focus_id_hash": _FOCUS_HASH,
        "instruction": "x", "instruction_revision": None, "activation_id": "act-parent", "team_id": None,
    }
    from backend.core.api.app.services import project_write_authorization_service as mod
    binding["instruction_revision"] = mod._focus_instruction_revision(
        {"default_focus_id_hash": _FOCUS_HASH, "focus_instruction": "x"},
    )
    cache.data[service._focus_key(_USER, _PARENT)] = binding


def _request():
    return SimpleNamespace(
        user_id=_USER, chat_id=_PARENT, message_id="turn", is_incognito=False, team_id=None, active_focus_id=None,
    )


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering
def test_focus_id_validation_drops_unknown_and_project_base() -> None:
    known = {"web-research"}
    def check(value, spec=None):
        return links.validate_focus_id(value, known_builtin=known, parent_specialist_id=spec)

    assert check("web-research") == "web-research"
    assert check("web-unknown") is None
    assert check("project-proj1") is None
    assert check("project-focus:proj1:item1") is None
    assert check("project-focus:proj1:item1", "project-focus:proj1:item1") == "project-focus:proj1:item1"


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering
def test_child_inherits_parent_project_base_and_specific_focus() -> None:
    cache, directus = _Cache(), _Directus()
    _bind_parent(cache, directus)
    children = [{"id": _CHILD, "focus_id": "web-research", "link": None}]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    assert children[0]["project_base"]["project_id"] == _PROJECT
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus,
        log_prefix="[t]", cache_factory=lambda: cache,
    ))
    child_binding = cache.data[ProjectWriteAuthorizationService._focus_key(_USER, _CHILD)]
    assert child_binding["parent_activation_id"] == "act-parent"
    assert child_binding["activation_id"] != "act-parent"
    assert children[0]["project_base"] is not None
    assert links.child_active_focus_id(children[0], _request()) == "web-research"
    children[0]["focus_id"] = None
    assert links.child_active_focus_id(children[0], _request()) == "project-proj1"


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering
def test_child_without_parent_binding_keeps_parent_focus() -> None:
    cache, directus = _Cache(), _Directus()
    children = [{"id": _CHILD, "focus_id": "bogus-focus", "link": None}]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    assert children[0]["project_base"] is None and children[0]["focus_id"] is None
    request = _request()
    request.active_focus_id = "web-research"
    assert links.child_active_focus_id(children[0], request) == "web-research"


# contract-test: supporting surface=rest_api assertions=focus-modes.project-layering
def test_inheritance_refused_for_chat_that_is_not_a_child_of_the_parent() -> None:
    cache, directus = _Cache(), _Directus(child_parent="other-parent")
    _bind_parent(cache, directus)
    children = [{"id": _CHILD, "focus_id": None, "link": None, "project_base": {"project_id": _PROJECT}}]
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus,
        log_prefix="[t]", cache_factory=lambda: cache,
    ))
    assert children[0]["project_base"] is None
    assert ProjectWriteAuthorizationService._focus_key(_USER, _CHILD) not in cache.data


# contract-test: supporting surface=rest_api assertions=plans.assumptions.investigated-before-work
def test_assumption_link_passes_through_and_task_link_is_written() -> None:
    cache, directus = _Cache(), _Directus()
    raw = {"kind": "assumption", "plan_id": _PLAN, "id": "a-1"}
    task = {"kind": "task", "plan_id": _PLAN, "id": "t-1"}
    children = [
        {"id": "c1", "focus_id": None, "link": raw},
        {"id": "c2", "focus_id": None, "link": task},
        {"id": "c3", "focus_id": None, "link": {"kind": "task", "plan_id": "nope", "id": "t"}},
    ]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus, log_prefix="[t]",
        cache_factory=lambda: cache,
    ))
    assert children[0]["link"] == raw
    assert children[1]["link"] == task
    assert children[2]["link"] is None
    assert directus.updates == [("user_tasks", "row-1", {"linked_sub_chat_id": "c2"})]


# contract-test: supporting surface=rest_api assertions=plans.assumptions.investigated-before-work
def test_task_link_refused_for_another_users_task() -> None:
    cache, directus = _Cache(), _Directus(task_owner="someone-else")
    children = [{"id": "c2", "focus_id": None, "link": {"kind": "task", "plan_id": _PLAN, "id": "t-1"}}]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus, log_prefix="[t]",
        cache_factory=lambda: cache,
    ))
    assert children[0]["link"] is None
    assert directus.updates == []


# contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
@pytest.mark.parametrize(("embed_owner", "vault_task_ids", "linked"), [
    ("owner-hash", ["task-1"], True),
    ("other-owner", ["task-1"], False),
    ("owner-hash", ["task-1", "task-2"], False),
])
async def test_later_task_sub_chat_resolves_unambiguous_owned_title(
    monkeypatch, embed_owner, vault_task_ids, linked,
):
    from toon_format import encode
    from backend.core.api.app.utils import encryption

    request = _request()
    request.user_id_hash = "owner-hash"
    request.embed_file_path_index = {f"task-{index}": str(index) for index in range(len(vault_task_ids))}
    cache = _Cache()
    cache.get_embed_from_cache = AsyncMock(return_value={
        "type": "task", "status": "finished", "chat_id": _PARENT, "hashed_user_id": embed_owner,
        "encrypted_content": "vault:v1:test",
    })
    cache.get_user_vault_key_id = AsyncMock(return_value="owner-vault")
    decrypt = AsyncMock(return_value=[
        encode({"title": "Build the importer", "type": "task", "task_id": task_id,
                "task_source": json.dumps({"plan": _PLAN})})
        for task_id in vault_task_ids
    ])
    monkeypatch.setattr(encryption, "EncryptionService", lambda **kwargs: SimpleNamespace(
        decrypt_many_with_user_key=decrypt, close=AsyncMock(),
    ))
    directus = _Directus(stored_tasks=set(vault_task_ids))
    children = [{"id": "child", "link": {"kind": "task", "plan_id": _PLAN, "id": "build the importer"}}]

    await links.apply_inheritance_and_task_links(
        children, request_data=request, directus_service=directus, log_prefix="test", cache_factory=lambda: cache,
    )

    if linked:
        assert children[0]["link"]["id"] == "task-1"
        assert directus.updates == [("user_tasks", "row-1", {"linked_sub_chat_id": "child"})]
    else:
        assert children[0]["link"] is None
        assert directus.updates == []
    if embed_owner != request.user_id_hash:
        decrypt.assert_not_awaited()


def _stage_create_job(cache: _Cache, task_id: str, owner: str = _USER) -> None:
    from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
    from backend.core.api.app.services.directus.user_task_methods import hash_id
    cache.data[f"{TASK_TOOL_JOB_CACHE_PREFIX}job-{task_id}"] = {
        "owner_hash": hash_id(owner), "task_id": task_id, "operation": "create", "state": "PENDING",
    }


# contract-test: supporting surface=rest_api assertions=plans.sub-chats.assumption-and-task-chats
def test_task_created_this_turn_is_linked_once_the_client_stores_it() -> None:
    from backend.core.api.app.services.task_sub_chat_link_service import apply_pending_link
    cache, directus = _Cache(), _Directus(stored_tasks=set())
    _stage_create_job(cache, "t-new")
    children = [{"id": "c9", "focus_id": None, "link": {"kind": "task", "plan_id": _PLAN, "id": "t-new"}}]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus, log_prefix="[t]",
        cache_factory=lambda: cache,
    ))
    assert children[0]["link"]["id"] == "t-new"
    assert directus.updates == []
    stored = {"id": "row-7", "task_id": "t-new", "plan_id": _PLAN}
    linked = asyncio.run(apply_pending_link(cache, directus, user_id=_USER, task=stored))
    assert linked == "c9"
    assert directus.updates == [("user_tasks", "row-7", {"linked_sub_chat_id": "c9"})]
    assert asyncio.run(apply_pending_link(cache, directus, user_id=_USER, task=stored)) is None


# contract-test: supporting surface=rest_api assertions=plans.sub-chats.assumption-and-task-chats
def test_pending_task_link_needs_own_staged_task_and_same_plan() -> None:
    from backend.core.api.app.services.task_sub_chat_link_service import apply_pending_link
    cache, directus = _Cache(), _Directus(stored_tasks=set())
    _stage_create_job(cache, "t-other", owner="someone-else")
    _stage_create_job(cache, "t-mine")
    children = [
        {"id": "c1", "focus_id": None, "link": {"kind": "task", "plan_id": _PLAN, "id": "t-other"}},
        {"id": "c2", "focus_id": None, "link": {"kind": "task", "plan_id": _PLAN, "id": "t-mine"}},
    ]
    asyncio.run(links.annotate_sub_chats(
        children, request_data=_request(), directus_service=directus,
        cache_service=cache, log_prefix="[t]",
    ))
    asyncio.run(links.apply_inheritance_and_task_links(
        children, request_data=_request(), directus_service=directus, log_prefix="[t]",
        cache_factory=lambda: cache,
    ))
    assert children[0]["link"] is None and children[1]["link"] is not None
    other_plan = {"id": "row-8", "task_id": "t-mine", "plan_id": str(_uuid.uuid4())}
    assert asyncio.run(apply_pending_link(cache, directus, user_id=_USER, task=other_plan)) is None
    assert directus.updates == []


# contract-test: supporting surface=rest_api assertions=chat-orchestration.sub-chats.work-links
def test_task_short_id_is_resolved_to_the_canonical_plan_link() -> None:
    cache, directus = _Cache(), _Directus(stored_tasks=set())
    directus.user_task.get_task_by_short_id = AsyncMock(
        return_value={"id": "row-1", "task_id": "canonical-task", "plan_id": _PLAN},
    )
    link = {"kind": "task", "plan_id": _PLAN, "id": "TASK-12"}
    asyncio.run(links.apply_inheritance_and_task_links(
        [{"id": "child", "link": link}], request_data=_request(), directus_service=directus,
        log_prefix="[t]", cache_factory=lambda: cache,
    ))
    directus.user_task.get_task_by_short_id.assert_awaited_once_with("TASK-12", _USER, None)
    assert link["id"] == "canonical-task"
    assert directus.updates == [("user_tasks", "row-1", {"linked_sub_chat_id": "child"})]


def test_expand_carries_focus_and_link_fields() -> None:
    out = expand_sub_chat_requests([{"prompt": "p", "focus_id": "web-research", "link": {"kind": "task"}}])
    assert out[0]["focus_id"] == "web-research" and out[0]["link"] == {"kind": "task"}
