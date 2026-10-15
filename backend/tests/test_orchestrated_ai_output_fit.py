"""Exercise production main-call admission without model or Directus traffic."""
# contract-test-file: infrastructure
from __future__ import annotations

import ast
import asyncio
import math
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest


class ProtocolError(RuntimeError):
    def __init__(self, status_code, code):
        self.status_code, self.code = status_code, code


def _admit(request, *, spent=806, held=200, input_quote=900, model_limit=65536,
           directus_available=True, service_error=None, reservation_race_credits=0):
    source = Path(__file__).parents[1] / "apps/ai/processing/main_processor.py"
    tree = ast.parse(source.read_text())
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    fitter_name = next(name for name in functions if name in {
        "_fit_parent_continuation_output_token_limit", "_fit_orchestrated_output_token_limit",
    })
    events = []
    client = object()

    def quote(**kwargs):
        return input_quote + math.ceil(kwargs["output_token_limit"] / 30)

    class Service:
        def __init__(self, directus):
            assert directus is client

        async def execute(self, operation, payload):
            assert payload["hashed_user_id"] == "trusted-owner"
            assert payload["orchestration_id"] == "trusted-root"
            events.append((operation, payload))
            if service_error:
                raise ProtocolError(404, service_error)
            if operation == "get_root_state":
                # The durable owner-scoped state, not client-provided limits.
                return {"credit_limit": 2000, "spent_credits": spent, "reserved_credits": held}
            assert operation == "reserve_operation"
            if spent + held + reservation_race_credits + payload["quoted_credits"] > 2000:
                raise ProtocolError(409, "orchestration_credit_limit_exceeded")
            return {"state": "reserved"}

    namespace = {"Optional": typing.Optional, "List": list, "Dict": dict, "Any": typing.Any,
                 "AskSkillRequest": object, "DirectusService": object,
                 "SubChatOrchestrationProtocolError": ProtocolError,
                 "SubChatOrchestrationService": Service,
                 "is_sub_chat_continuation": lambda req: req.is_sub_chat_continuation,
                 "_normal_chat_cache_pricing_scope": lambda _: False,
                 "_quote_ai_iteration_credits": quote,
                 "ORCHESTRATED_AI_MAX_OUTPUT_TOKENS": 8192,
                 "ANONYMOUS_AI_MAX_OUTPUT_TOKENS": 1024,
                 "logger": SimpleNamespace(info=lambda *args: None, warning=lambda *args: None),
                 "config_manager": SimpleNamespace(get_model_pricing=lambda *args: {
                     "features": {"max_output_tokens": model_limit}})}
    names = [fitter_name, "_max_affordable_ai_output_tokens", "_orchestrated_ai_output_token_limit", "_reserve_ai_iteration"]
    exec(compile(ast.Module(body=[functions[name] for name in names], type_ignores=[]), str(source), "exec"), namespace)

    # Use the actual main-loop cap/fitter/reservation assignments and its typed
    # budget handler. This catches omitted depth-1 integration and fallback drift,
    # rather than exercising a reimplementation of the dispatch condition.
    main = functions["handle_main_processing"]
    preparation = next(node for node in ast.walk(main) if isinstance(node, ast.Try)
                       and any(isinstance(handler.type, ast.Name)
                               and handler.type.id == "SubChatOrchestrationProtocolError"
                               for handler in node.handlers))
    assignments = [node for node in preparation.body if isinstance(node, ast.Assign)
                   and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                           and call.func.id in {fitter_name, "_orchestrated_ai_output_token_limit", "_reserve_ai_iteration"}
                           for call in ast.walk(node))]
    assert len(assignments) == 3
    budget_handler = next(handler for handler in preparation.handlers
                          if isinstance(handler.type, ast.Name)
                          and handler.type.id == "SubChatOrchestrationProtocolError")
    body = ast.parse("async def run():\n    while True:\n        pass\n").body[0]
    body.body[0].body = [ast.Try(body=assignments, handlers=[budget_handler], orelse=[], finalbody=[]), ast.Break()]
    body.body += ast.parse("return current_output_token_limit, current_ai_operation_id, preparation_failure_reason, current_model_index").body
    # All state is explicit fixture data; the extracted production assignments
    # mutate global dispatch state exactly once in this isolated namespace.
    body.body.insert(0, ast.Global(names=["current_output_token_limit", "current_ai_operation_id", "preparation_failure_reason", "current_model_index"]))
    namespace.update({"current_model_id": "google/test", "request_data": request,
                      "iteration_system_prompt": "bounded research", "current_message_history": [],
                      "iteration_tools": [], "directus_service": client if directus_available else None,
                      "log_prefix": "", "logical_billing_task_id": "task", "iteration": 1,
                      "current_output_token_limit": None, "current_ai_operation_id": None,
                      "preparation_failure_reason": None, "current_model_index": 0})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[body], type_ignores=[])), str(source), "exec"), namespace)
    return asyncio.run(namespace["run"]()), events


def _request(*, depth=1, continuation=False, orchestration="trusted-root", external=False):
    return SimpleNamespace(is_anonymous=False, is_external=external, is_sub_chat=depth > 0,
                           is_sub_chat_continuation=continuation, sub_chat_depth=depth,
                           orchestration_id=orchestration, user_id_hash="trusted-owner",
                           root_chat_id="root-chat", chat_id="child" if depth else "root-chat",
                           orchestration_credit_limit=999999)


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("depth,continuation", [(1, False), (2, False), (0, False), (0, True)])
def test_main_admission_fits_every_orchestrated_iteration_to_authoritative_capacity(depth, continuation):
    result, events = _admit(_request(depth=depth, continuation=continuation))
    assert result == (2820, "ai-ask:task:main:iteration:1:model:google/test", None, 0)
    assert [operation for operation, _ in events] == ["get_root_state", "reserve_operation"]
    assert events[1][1]["quoted_credits"] == 994
    assert events[1][1]["depth"] == depth
    assert 806 + 200 + events[1][1]["quoted_credits"] == 2000


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("external", [False, True])
def test_ordinary_and_external_unorchestrated_calls_keep_the_provider_default(external):
    result, events = _admit(_request(depth=0, orchestration=None, external=external))
    assert result == (None, None, None, 0)
    assert events == []


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
@pytest.mark.parametrize("spent,held", [(1100, 0), (806, 394), (2000, 0)])
def test_unaffordable_input_stops_before_atomic_reservation_without_model_fallback(spent, held):
    result, events = _admit(_request(), spent=spent, held=held)
    assert result[1:] == (None, "orchestration_budget_limit", 0)
    assert [operation for operation, _ in events] == ["get_root_state"]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_minimum_output_and_lower_provider_limit_are_preserved():
    result, events = _admit(_request(), spent=1099, held=0, model_limit=1)
    assert result[0] == 1
    assert events[-1][1]["quoted_credits"] == 901


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_wrong_owner_or_root_rejection_is_not_reclassified_as_budget_or_provider_fallback():
    with pytest.raises(ProtocolError) as error:
        _admit(_request(), service_error="orchestration_not_found")
    assert error.value.code == "orchestration_not_found"


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_atomic_reservation_still_rejects_capacity_consumed_after_the_fit():
    result, events = _admit(_request(), reservation_race_credits=1)
    assert result == (2820, None, "orchestration_budget_limit", 0)
    assert [operation for operation, _ in events] == ["get_root_state", "reserve_operation"]


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_full_output_allowance_is_preserved_when_authoritative_capacity_covers_it():
    result, events = _admit(_request(), spent=100, held=0)
    assert result[0] == 8192
    assert events[-1][1]["quoted_credits"] == 1174


# contract-test: supporting surface=rest_api assertions=billing.credits.idempotent-charge
def test_missing_durable_service_cannot_authorize_orchestrated_paid_work():
    with pytest.raises(RuntimeError, match="Orchestrated AI reservation requires Directus"):
        _admit(_request(), directus_available=False)
