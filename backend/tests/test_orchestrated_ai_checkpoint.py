"""Focused numeric checkpoint tests without provider/Directus dependencies."""
# contract-test-file: infrastructure
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest


def _checkpoint_function(service):
    # Compile the production helper directly, isolating the heavy AI imports.
    source = Path(__file__).parents[1] / "apps/ai/processing/main_processor.py"
    tree = ast.parse(source.read_text())
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_checkpoint_orchestrated_ai_iteration")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"SubChatOrchestrationService": service, "AskSkillRequest": object,
                 "DirectusService": object}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace[node.name]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_completed_iteration_uses_cumulative_rounding_delta_and_scope():
    calls = []

    class Service:
        def __init__(self, directus):
            assert directus is client

        async def execute(self, operation, payload):
            calls.append((operation, payload))
            return {**payload, "quoted_credits": 10, "state": "reserved", "idempotent": False}

    client = object()
    fn = _checkpoint_function(Service)
    request = SimpleNamespace(orchestration_id="root", user_id_hash="owner", chat_id="child")
    previous = 0
    # Cumulative rounded costs: two fractional-credit calls together cost 1,
    # rather than charging/holding one rounded credit for each iteration.
    for index, cumulative in enumerate([1, 1, 2]):
        previous = asyncio.run(fn(operation_id=f"iteration:{index}", task_id="task",
                                 cumulative_credits=cumulative, checkpointed_credits=previous,
                                 request_data=request, directus_service=client))
    assert [payload["actual_credits"] for _, payload in calls] == [1, 0, 1]
    assert sum(payload["actual_credits"] for _, payload in calls) == 2
    assert calls[0] == ("checkpoint_ai_operation", {
        "protocol_version": 1, "operation_id": "iteration:0", "charge_id": "ai-ask:task:main",
        "orchestration_id": "root", "hashed_user_id": "owner", "actual_chat_id": "child",
        "actual_credits": 1,
    })


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_decreasing_completed_usage_fails_before_ledger_access():
    class Service:
        def __init__(self, _):
            pytest.fail("Decreasing cumulative usage must not mutate the ledger")
    fn = _checkpoint_function(Service)
    with pytest.raises(RuntimeError, match="Cumulative orchestration usage decreased"):
        asyncio.run(fn(operation_id="iteration", task_id="task", cumulative_credits=1,
                       checkpointed_credits=2, request_data=object(), directus_service=object()))


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_ambiguous_checkpoint_acknowledgement_is_not_counted_as_success():
    class Service:
        def __init__(self, _):
            pass
        async def execute(self, operation, payload):
            raise ConnectionError("lost numeric ledger acknowledgement")
    fn = _checkpoint_function(Service)
    request = SimpleNamespace(orchestration_id="root", user_id_hash="owner", chat_id="child")
    with pytest.raises(ConnectionError):
        asyncio.run(fn(operation_id="iteration", task_id="task", cumulative_credits=1,
                       checkpointed_credits=0, request_data=request, directus_service=object()))


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_parent_input_budget_failure_remains_a_budget_admission_error():
    class ProtocolError(RuntimeError):
        def __init__(self, status_code, code):
            self.status_code, self.code = status_code, code
    class Service:
        def __init__(self, _):
            pass
        async def execute(self, operation, payload):
            assert operation == "get_root_state"
            return {"credit_limit": 2000, "spent_credits": 1900, "reserved_credits": 100}
    source = Path(__file__).parents[1] / "apps/ai/processing/main_processor.py"
    tree = ast.parse(source.read_text())
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_fit_parent_continuation_output_token_limit")
    namespace = {"Optional": __import__("typing").Optional,
                 "List": list, "Dict": dict, "Any": object,
                 "AskSkillRequest": object, "DirectusService": object,
                 "SubChatOrchestrationProtocolError": ProtocolError,
                 "SubChatOrchestrationService": Service,
                 "is_sub_chat_continuation": lambda _: True,
                 "_normal_chat_cache_pricing_scope": lambda _: False,
                 "_max_affordable_ai_output_tokens": lambda **kwargs: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    request = SimpleNamespace(orchestration_id="root", user_id_hash="owner")
    with pytest.raises(ProtocolError) as error:
        asyncio.run(namespace[node.name](model_id="google/test", system_prompt="",
                    message_history=[], tools=None, requested_output_token_limit=8192,
                    request_data=request, directus_service=object(), log_prefix=""))
    assert error.value.code == "orchestration_credit_limit_exceeded"
    assert error.value.status_code == 409


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("override", [
    {"operation_id": "foreign"}, {"charge_id": "foreign"}, {"orchestration_id": "foreign"},
    {"state": "settled"}, {"actual_credits": 2}, {"actual_credits": True}, {"actual_credits": 1.0},
    {"quoted_credits": 0}, {"quoted_credits": True}, {"idempotent": None}, {},
])
def test_invalid_checkpoint_acknowledgement_does_not_advance_completed_usage(override):
    class Service:
        def __init__(self, _):
            pass
        async def execute(self, operation, payload):
            if not override:
                return {}
            return {**payload, "quoted_credits": 10, "state": "reserved", "idempotent": False, **override}
    fn = _checkpoint_function(Service)
    request = SimpleNamespace(orchestration_id="root", user_id_hash="owner", chat_id="child")
    with pytest.raises(RuntimeError, match="checkpoint receipt is invalid"):
        asyncio.run(fn(operation_id="iteration", task_id="task", cumulative_credits=1,
                       checkpointed_credits=0, request_data=request, directus_service=object()))
