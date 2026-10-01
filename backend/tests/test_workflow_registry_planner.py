"""Generic authoring orchestration contracts; inference is mocked, not billed."""

from copy import deepcopy
import asyncio
import json

import pytest

from backend.core.api.app.services import workflow_registry_planner as module
from backend.core.api.app.services.workflow_authoring_preselection import WorkflowPreselection
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable


@pytest.fixture(autouse=True)
def metadata_registry(monkeypatch):
    monkeypatch.setattr(WorkflowCapabilityRegistry, "_registry", lambda _: _FilesystemWorkflowMetadataRegistry())


def forecast_plan(title="Daily forecast"):
    return {"operation": "create", "title": title, "description": "The requested forecast",
            "icon": "cloud-rain", "schedule": {"type": "daily", "time": "08:00"}, "steps": [
                {"kind": "app", "id": "weather", "capability": "weather.forecast", "input": {
                    "location": "Berlin", "start_date": {"$date": "today", "format": "date"},
                    "end_date": {"$date": "today", "format": "date"}}},
                {"kind": "send", "id": "message", "title": "Forecast", "message": [
                    {"ref": {"step": "weather", "field": "summary"}}]},
            ]}


def configure(monkeypatch, *, operation="create", count=1, unavailable=False, clarity="clear", check_mode="none",
              capability_ids=("weather.forecast", "ai.ask"), chat_delivery=True):
    registry = WorkflowCapabilityRegistry()
    selection = WorkflowPreselection([registry.get_capability(identifier) for identifier in capability_ids],
                                     operation, check_mode, chat_delivery, {},
                                     {"jev_calls": 1, "seconds": 0.01, "estimated_cost_usd": 0.0001}, count, clarity)

    class Selector:
        def __init__(self, **kwargs):
            pass

        async def select(self, *args, **kwargs):
            if unavailable:
                raise DecisionProviderUnavailable("Synthetic outage")
            return selection

    monkeypatch.setattr(module, "WorkflowAuthoringPreselector", Selector)


class Author:
    def __init__(self, raw):
        self.raw = raw
        self.calls = 0
        self.selection = None

    async def generate(self, **kwargs):
        self.calls += 1
        self.selection = kwargs["selection"]
        plans = self.raw.get("operations", [self.raw])
        for workflow_index, plan in enumerate(plans):
            if plan.get("steps"):
                await kwargs["on_plan_component"]({"workflow_index": workflow_index, "index": 0,
                                                   "plan": {**plan, "steps": plan["steps"][:1]}})
        return deepcopy(self.raw), {"seconds": 0.02, "estimated_cost_usd": 0.002}


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_request_local_secrets_keep_provider_cache_expiry_without_sharing_http_clients(monkeypatch):
    class Secrets:
        def __init__(self):
            self.vault_token = "synthetic-token"
            self._token_valid_until = 1234
            self._secrets_cache = {}
            self._http_client = None
            self.closed = False

        async def aclose(self):
            self.closed = True

    original = Secrets()
    expires = asyncio.get_running_loop().time() + 60
    original._secrets_cache = {
        module._PROVIDER_CACHE_KEYS[0]: {"value": "synthetic-google-key", "expires": expires},
        "unrelated/secret": {"value": "unrelated", "expires": expires},
    }
    original._http_client = object()
    monkeypatch.setattr(module, "SecretsManager", Secrets)
    captured = []
    monkeypatch.setattr(module, "JevDecisionClient", lambda **kwargs: captured.append(kwargs["secrets_manager"]) or object())
    monkeypatch.setattr(module, "WorkflowGeminiAuthor", lambda *args: object())
    planner = module.WorkflowRegistryPlanner(secrets_manager=original)

    async def plan(*args):
        local = captured[0]
        assert local is not original and local._http_client is None
        assert "unrelated/secret" not in local._secrets_cache
        assert local._secrets_cache[module._PROVIDER_CACHE_KEYS[0]] == original._secrets_cache[module._PROVIDER_CACHE_KEYS[0]]
        assert local._secrets_cache[module._PROVIDER_CACHE_KEYS[0]] is not original._secrets_cache[module._PROVIDER_CACHE_KEYS[0]]
        local._secrets_cache[module._PROVIDER_CACHE_KEYS[1]] = {"value": "synthetic-router-key", "expires": expires}
        # A concurrent request may have refreshed a key during this request.
        original._secrets_cache[module._PROVIDER_CACHE_KEYS[0]] = {"value": "newer-synthetic-key", "expires": expires + 10}
        return {"action": "needs_clarification"}

    monkeypatch.setattr(planner, "_plan", plan)
    await planner._isolated_plan("Synthetic request", {})
    assert captured[0].closed is True and original.closed is False
    assert original._secrets_cache[module._PROVIDER_CACHE_KEYS[1]]["expires"] == expires
    assert original._secrets_cache[module._PROVIDER_CACHE_KEYS[0]]["value"] == "newer-synthetic-key"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation
@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2])
async def test_create_streams_inert_preview_then_returns_validated_disabled_plan(monkeypatch, count):
    configure(monkeypatch, count=count)
    events = []
    raw = forecast_plan() if count == 1 else {"operations": [forecast_plan(), forecast_plan("Second forecast")]}
    author = Author(raw)
    planner = module.WorkflowRegistryPlanner(secrets_manager=None, author=author, jev_client=object())
    result = await planner._plan("Daily forecast", {"timezone": "Europe/Berlin", "_on_component": events.append},
                                 object(), author)
    plans = [result] if count == 1 else result["operations"]
    assert result["action"] == ("create_workflow" if count == 1 else "batch")
    assert len(plans) == count and all(plan["enabled"] is False for plan in plans)
    scope = next(event for event in events if event.get("workflow_count") is not None)
    assert scope == {"type": "progress", "phase": "planning", "operation": "create", "workflow_count": count}
    assert events.index(scope) < next(index for index, event in enumerate(events) if event["type"] == "preview")
    previews = [event for event in events if event["type"] == "preview"]
    assert [len(event["graph"]["nodes"]) for event in previews] == ([1, 2, 1, 2, 3, 3] if count == 2 else [1, 2, 3])
    preview = previews[1]
    assert preview["provisional"] is True and "action" not in preview
    assert {node["id"] for node in preview["graph"]["nodes"]} == {"trigger", "weather"}
    assert all(len(plan["graph"]["nodes"]) == 3 for plan in plans)
    assert author.calls == 1


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.atomic-update
@pytest.mark.asyncio
async def test_second_failure_retains_only_valid_batch_nodes_as_disabled_partial(monkeypatch):
    configure(monkeypatch, count=2)
    invalid = forecast_plan("Second")
    invalid["steps"][1]["message"][0]["ref"]["field"] = "invented_output"
    author = Author({"operations": [forecast_plan(), invalid]})
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Create two forecasts", {"timezone": "Europe/Berlin"}, object(), author)
    assert result["action"] == "partial" and result["reason"] == "provider_error"
    assert author.calls == 2 and len(result["operations"]) == 2
    assert all(item["enabled"] is False for item in result["operations"])
    assert {node["id"] for node in result["operations"][1]["graph"]["nodes"]} == {"trigger", "weather"}


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
@pytest.mark.asyncio
async def test_batch_requires_every_selected_workflow_count(monkeypatch):
    configure(monkeypatch, count=2)
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Create two forecasts", {"timezone": "Europe/Berlin"}, object(), Author(forecast_plan()))
    assert result["action"] == "partial" and len(result["operations"]) == 1
    assert result["_authoring_metrics"]["gemini_calls"] == 2


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
@pytest.mark.asyncio
async def test_unclear_count_does_not_author_or_save_an_arbitrary_batch(monkeypatch):
    configure(monkeypatch, count=None)
    author = Author(forecast_plan())
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Create these workflows", {"timezone": "Europe/Berlin"}, object(), author)
    assert result["action"] == "needs_clarification" and author.calls == 0


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_only_jev_unclear_intent_opens_clarification_and_title_only_skips_author(monkeypatch):
    configure(monkeypatch, operation="clarify", count=None)
    planner = module.WorkflowRegistryPlanner(secrets_manager=None)
    result = await planner._plan("My research", {"timezone": "Europe/Berlin"}, object(), Author(forecast_plan()))
    assert result["action"] == "needs_clarification"
    configure(monkeypatch, operation="create", count=1, clarity="title_only")
    author = Author(forecast_plan())
    draft = await planner._plan("My research", {"timezone": "Europe/Berlin"}, object(), author)
    assert draft["action"] == "create_empty_workflow" and draft["title"] == "My research"
    assert author.calls == 0


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_jev_outage_uses_one_gemini_authoring_call_with_registry_contracts(monkeypatch):
    configure(monkeypatch, unavailable=True)
    author = Author(forecast_plan())
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "Europe/Berlin"}, object(), author)
    assert result["action"] == "create_workflow"
    assert author.calls == 1 and result["_authoring_metrics"]["jev_unavailable"] is True
    assert "weather.forecast" in {cap.id for cap in author.selection.capabilities}


# contract-test: supporting surface=rest_api assertions=workflows.authoring.atomic-update
@pytest.mark.asyncio
async def test_schedule_only_update_keeps_every_node_and_captures_prior_version(monkeypatch):
    configure(monkeypatch, operation="update")
    registry = WorkflowCapabilityRegistry()
    base_selection = WorkflowPreselection([registry.get_capability("weather.forecast")], "create", "none", True, {}, {})
    graph = module.compile_authoring_plan(forecast_plan(), base_selection, "Europe/Berlin")["graph"]
    before = {"id": "owned-workflow", "version": 7, "title": "Daily forecast", "description": "Existing",
              "icon": "cloud-rain", "graph": graph}
    author = Author({"operation": "update", "workflow_id": before["id"], "schedule": {"type": "daily", "time": "10:00"}})
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Move this to ten", {"timezone": "Europe/Berlin", "selected_workflow": before}, object(), author)
    assert result["action"] == "update_workflow" and result["expected_record_version"] == 7
    assert result["graph"]["nodes"][1:] == graph["nodes"][1:]
    assert result["_authoring_before"][before["id"]]["version"] == 7


class FlatAuthor:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def generate(self, **kwargs):
        self.requests.append(kwargs)
        response = deepcopy(self.responses[min(len(self.requests) - 1, len(self.responses) - 1)])
        for index, workflow in enumerate(response["workflows"]):
            await kwargs["on_plan_component"]({"type": "header", "workflow_index": index,
                                               "header": workflow["header"]})
            for node in workflow["nodes"]:
                await kwargs["on_plan_component"]({"type": "node", "workflow_index": index, "node": node})
        return response, {"seconds": 0.02, "estimated_cost_usd": 0.002}


def flat_forecast():
    plan = forecast_plan()
    return {"workflows": [{"header": {key: value for key, value in plan.items() if key != "steps"},
                           "nodes": module.WorkflowRegistryPlanner._flat_nodes(plan["steps"])}]}


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_invalid_schedule_retries_with_field_feedback_before_any_preview(monkeypatch):
    configure(monkeypatch)
    good = flat_forecast()
    good["workflows"][0]["header"]["schedule"] = {
        "type": "weekly", "weekdays": ["monday"], "time": "07:30",
    }
    bad = deepcopy(good)
    bad["workflows"][0]["header"]["schedule"]["at"] = bad["workflows"][0]["header"]["schedule"].pop("time")
    author = FlatAuthor([bad, good])
    events = []
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Every Monday at 07:30, send Berlin weather", {"timezone": "Europe/Berlin", "_on_component": events.append},
        object(), author,
    )
    assert result["action"] == "create_workflow"
    assert len(author.requests) == 2
    assert author.requests[1]["accepted_prefixes"] == []
    assert "weekly schedule supports time" in author.requests[1]["correction"]
    assert "unsupported fields: at" in author.requests[1]["correction"]
    assert "07:30" not in author.requests[1]["correction"]
    retry_index = next(index for index, event in enumerate(events) if event.get("phase") == "retrying_node")
    assert not any(event["type"] == "preview" for event in events[:retry_index])
    assert result["graph"]["nodes"][0]["config"]["schedule"]["time"] == "07:30"


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_invalid_node_never_streams_and_corrective_retry_keeps_accepted_prefix(monkeypatch):
    configure(monkeypatch)
    valid = flat_forecast()
    invalid = deepcopy(valid)
    invalid["workflows"][0]["nodes"][1]["message_json"] = '[{"ref":{"step":"weather","field":"invented"}}]'
    author = FlatAuthor([invalid, valid])
    checkpoints, events = [], []
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send my daily forecast", {"timezone": "Europe/Berlin", "_on_checkpoint": checkpoints.append,
                                   "_on_component": events.append}, object(), author)
    assert result["action"] == "create_workflow" and len(author.requests) == 2
    assert author.requests[1]["correction"]
    assert len(author.requests[1]["accepted_prefixes"][0]["nodes"]) == 1
    assert [checkpoint["accepted_node_count"] for checkpoint in checkpoints] == [0, 1, 2]
    assert not any(event["type"] == "preview" for event in events)
    assert any(event.get("phase") == "retrying_node" for event in events)
    assert "invented" not in str(checkpoints)


def two_deliveries():
    raw = flat_forecast()
    second = deepcopy(raw["workflows"][0]["nodes"][1])
    second["id"] = "second_message"
    raw["workflows"][0]["nodes"].append(second)
    return raw


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_separate_failing_nodes_each_get_one_correction_with_frozen_progress(monkeypatch):
    configure(monkeypatch)
    good = two_deliveries()
    first_bad, second_bad = deepcopy(good), deepcopy(good)
    first_bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    second_bad["workflows"][0]["nodes"][2]["message_json"] = '{'
    author = FlatAuthor([first_bad, second_bad, good])
    checkpoints, events = [], []
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send two forecast messages", {"timezone": "UTC", "_on_checkpoint": checkpoints.append,
                                       "_on_component": events.append}, object(), author)
    assert result["action"] == "create_workflow" and len(author.requests) == 3
    assert [len(request["accepted_prefixes"][0]["nodes"]) for request in author.requests[1:]] == [1, 2]
    assert [item["accepted_node_count"] for item in checkpoints] == [0, 1, 2, 3]
    retries = [event for event in events if event.get("phase") == "retrying_node"]
    assert [(event["attempt"], event["node_index"], event["correction_attempt"]) for event in retries] == [
        (2, 1, 1), (3, 2, 1)]
    assert all(node["config"]["message"] == "{{ $nodes.weather.output.summary }}"
               for checkpoint in checkpoints for node in checkpoint["graph"]["nodes"]
               if node["type"] == "send_chat_message")
    assert len({node["id"] for node in result["graph"]["nodes"]}) == 4


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_twice_invalid_node_stops_even_when_rejected_id_changes(monkeypatch):
    configure(monkeypatch)
    bad = flat_forecast()
    bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    renamed = deepcopy(bad)
    renamed["workflows"][0]["nodes"][1]["id"] = "renamed_failure"
    author = FlatAuthor([bad, renamed, flat_forecast()])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "partial" and len(author.requests) == 2
    assert [node["id"] for node in result["operations"][0]["graph"]["nodes"]] == ["trigger", "weather"]
    assert result["operations"][0]["enabled"] is False


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_later_twice_invalid_node_stops_after_earlier_node_was_repaired(monkeypatch):
    configure(monkeypatch)
    good = two_deliveries()
    first_bad, later_bad = deepcopy(good), deepcopy(good)
    first_bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    later_bad["workflows"][0]["nodes"][2]["message_json"] = '{'
    author = FlatAuthor([first_bad, later_bad, later_bad, good])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send two forecast messages", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "partial" and len(author.requests) == 3
    assert [node["id"] for node in result["operations"][0]["graph"]["nodes"]] == ["trigger", "weather", "message"]


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_header_and_first_node_have_independent_correction_allowances(monkeypatch):
    configure(monkeypatch)
    good = flat_forecast()
    bad_header, bad_node = deepcopy(good), deepcopy(good)
    bad_header["workflows"][0]["header"]["schedule"] = {"type": "daily", "time": "not-a-clock"}
    bad_node["workflows"][0]["nodes"][0]["input_json"] = '{'
    author = FlatAuthor([bad_header, bad_node, good])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "create_workflow" and len(author.requests) == 3
    assert author.requests[1]["accepted_prefixes"] == []
    assert author.requests[2]["accepted_prefixes"][0]["nodes"] == []


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_nonrepairable_provider_request_error_does_not_repeat_the_same_request(monkeypatch):
    configure(monkeypatch)

    class RejectedAuthor:
        calls = 0

        async def generate(self, **kwargs):
            self.calls += 1
            error = module.WorkflowAuthoringProviderError("Workflow provider HTTP 400")
            error.http_status = 400
            raise error

    author = RejectedAuthor()
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "partial" and result["operations"] == [] and author.calls == 1
    assert result["_authoring_metrics"]["generation_attempts"][0]["provider_http_status"] == 400


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_real_adapter_and_compiler_repair_two_nodes_in_three_provider_requests(monkeypatch):
    import httpx

    configure(monkeypatch)
    good = two_deliveries()
    first_bad, second_bad = deepcopy(good), deepcopy(good)
    first_bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    second_bad["workflows"][0]["nodes"][2]["message_json"] = '{'
    responses, requests, checkpoints = [first_bad, second_bad, good], [], []

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    def provider(request):
        payload = json.loads(request.content)
        requests.append(json.loads(payload["contents"][0]["parts"][0]["text"]))
        event = {"candidates": [{"content": {"parts": [{"text": json.dumps(responses[len(requests) - 1])}]},
                                  "finishReason": "STOP"}],
                 "usageMetadata": {"promptTokenCount": 600, "candidatesTokenCount": 120}}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        author = module.WorkflowGeminiAuthor(Secrets(), client)
        result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
            "Send two forecast messages", {"timezone": "UTC", "_on_checkpoint": checkpoints.append}, object(), author)
    assert result["action"] == "create_workflow" and len(requests) == 3
    assert [len(request["accepted_prefixes"][0]["nodes"]) for request in requests[1:]] == [1, 2]
    assert "node 2" in requests[1]["validation_correction"]
    assert "node 3" in requests[2]["validation_correction"]
    assert [item["accepted_node_count"] for item in checkpoints] == [0, 1, 2, 3]
    assert [attempt["input_tokens"] for attempt in result["_authoring_metrics"]["generation_attempts"]] == [600] * 3


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.access.boundaries
@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_target", [False, True])
async def test_jev_outage_adapter_loads_owned_overview_edit_before_header_validation(monkeypatch, foreign_target):
    import httpx

    configure(monkeypatch, unavailable=True)
    registry = WorkflowCapabilityRegistry()
    original = module.compile_authoring_plan(forecast_plan(), WorkflowPreselection(
        [registry.get_capability("weather.forecast")], "create", "none", True, {}, {}), "UTC")["graph"]
    target = {"id": "owned-workflow", "title": "Daily forecast", "description": "Original",
              "version": 7, "icon": "cloud-rain", "graph": original}
    header = {"operation": "update", "workflow_id": "foreign-workflow" if foreign_target else target["id"],
              "schedule": {"type": "daily", "time": "10:00"}}
    response = {"workflows": [{"header": header, "nodes": []}]}
    loaded = []

    class Secrets:
        async def get_secret(self, **kwargs):
            return "synthetic-key"

    def provider(request):
        event = {"candidates": [{"content": {"parts": [{"text": json.dumps(response)}]}, "finishReason": "STOP"}]}
        return httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n')

    def load(identifier):
        loaded.append(identifier)
        assert identifier == target["id"]
        return target

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
            "Move Daily forecast to 10:00", {"timezone": "UTC", "_load_workflows": lambda: [
                {key: target[key] for key in ("id", "title", "description")}], "_load_workflow": load},
            object(), module.WorkflowGeminiAuthor(Secrets(), client))
    if foreign_target:
        assert result["action"] == "partial" and result["operations"] == [] and loaded == []
    else:
        assert result["action"] == "update_workflow" and loaded == [target["id"]]
        assert result["expected_record_version"] == 7
        assert result["graph"]["nodes"][0]["config"]["schedule"]["time"] == "10:00"
        assert result["graph"]["nodes"][1:] == original["nodes"][1:]
        assert result["_authoring_metrics"]["gemini_calls"] == 1


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_retry_allowances_are_independent_across_workflows(monkeypatch):
    configure(monkeypatch, count=2)
    good = {"workflows": [flat_forecast()["workflows"][0], flat_forecast()["workflows"][0]]}
    good["workflows"][1]["header"]["title"] = "Second forecast"
    first_bad, second_bad = deepcopy(good), deepcopy(good)
    first_bad["workflows"][0]["nodes"][1]["message_json"] = '{'
    second_bad["workflows"][1]["nodes"][1]["message_json"] = '{'
    author = FlatAuthor([first_bad, second_bad, good])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Create two forecast workflows", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "batch" and len(result["operations"]) == 2 and len(author.requests) == 3
    assert [len(item["nodes"]) for item in author.requests[2]["accepted_prefixes"]] == [2, 1]


# contract-test: supporting surface=rest_api assertions=workflows.authoring.provisional-validation,workflows.authoring.atomic-update
@pytest.mark.asyncio
async def test_stop_keeps_accepted_prefix_without_a_retry(monkeypatch):
    configure(monkeypatch)
    stopped = False
    checkpoints = []

    def checkpoint(value):
        nonlocal stopped
        checkpoints.append(value)
        if value["accepted_node_count"] == 1:
            stopped = True

    author = FlatAuthor([flat_forecast()])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send my daily forecast", {"timezone": "Europe/Berlin", "_on_checkpoint": checkpoint,
                                   "_should_stop": lambda: stopped}, object(), author)
    assert result["action"] == "partial" and result["reason"] == "stopped"
    assert len(author.requests) == 1
    assert {node["id"] for node in result["operations"][0]["graph"]["nodes"]} == {"trigger", "weather"}
    assert result["operations"][0]["enabled"] is False


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_gemini_clarification_output_is_retried_then_fails_without_opening_chat(monkeypatch):
    configure(monkeypatch)
    author = FlatAuthor([{"workflows": [{"header": {"operation": "clarify", "message": "Missing detail"},
                                         "nodes": []}]}])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "Europe/Berlin"}, object(), author)
    assert result["action"] == "partial" and result["operations"] == []
    assert len(author.requests) == 2


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["enum", "Private generated value"])
async def test_retry_metrics_keep_safe_failure_codes_without_private_correction(monkeypatch, keyword):
    configure(monkeypatch)

    class FailingAuthor:
        async def generate(self, **kwargs):
            error = module.WorkflowAuthoringProviderError("Workflow header failed validation",
                                                         {"output_tokens": 34})
            error.code = "header_validation"
            error.validation_code = "schedule_fields"
            error.validation_path = "$.schedule.time"
            error.validation_keyword = keyword
            error.validation_error = "Private generated value must stay in correction only"
            raise error

    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Private user request", {"timezone": "Europe/Berlin"}, object(), FailingAuthor())
    assert result["action"] == "partial" and result["operations"] == []
    metrics = result["_authoring_metrics"]
    assert metrics["last_failure_reason_code"] == "header_validation"
    assert metrics["last_validation_code"] == "schedule_fields"
    assert metrics["last_validation_path"] == "$.schedule.time"
    assert metrics.get("last_validation_keyword") == ("enum" if keyword == "enum" else None)
    assert len(metrics["generation_attempts"]) == 2
    assert all(attempt["failure_reason_code"] == "header_validation"
               and attempt["validation_code"] == "schedule_fields"
               and attempt.get("validation_keyword") == ("enum" if keyword == "enum" else None)
               for attempt in metrics["generation_attempts"])
    assert "Private" not in json.dumps(metrics)


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
@pytest.mark.parametrize("hint", ["none", "exact", "ai", "both"])
async def test_unused_jev_check_candidates_do_not_force_a_check_or_correction(monkeypatch, hint):
    configure(monkeypatch, check_mode=hint)
    author = Author(forecast_plan())
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Every day at 08:00 UTC, send the Berlin forecast", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "create_workflow" and author.calls == 1
    assert not any(node["type"] == "check" for node in result["graph"]["nodes"])


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_price_filter_completes_without_a_check_despite_jev_control_hints(monkeypatch):
    configure(monkeypatch, check_mode="both", chat_delivery=False,
              capability_ids=("shopping.search_products", "weather.forecast", "ai.ask"))
    raw = {"operation": "create", "title": "Headphones", "description": "Matching products under 150 euros",
           "icon": "help-circle", "schedule": {"type": "weekly", "time": "18:00", "weekdays": ["friday"]},
           "steps": [{"kind": "app", "id": "products", "capability": "shopping.search_products", "input": {
               "requests": [{"query": "noise-cancelling headphones", "category": "electronics",
                             "country": "de", "max_price": 150}]}},
                     {"kind": "send", "id": "delivery", "title": "Headphones", "message": [
                         {"ref": {"step": "products", "field": "results"}}]}]}
    author = Author(raw)
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Every Friday at 18:00 UTC find headphones under 150 euros and send the matching products in chat",
        {"timezone": "UTC"}, object(), author)
    assert result["action"] == "create_workflow" and author.calls == 1
    assert [node["type"] for node in result["graph"]["nodes"]] == [
        "schedule_trigger", "app_skill_action", "send_chat_message"]
    assert result["graph"]["nodes"][1]["config"]["input"]["requests"][0]["max_price"] == 150


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan
@pytest.mark.asyncio
async def test_gemini_can_include_a_needed_exact_check_even_when_jev_suggests_none(monkeypatch):
    configure(monkeypatch, check_mode="none", chat_delivery=False)
    raw = forecast_plan()
    raw["steps"][1:] = [{"kind": "check", "id": "rain", "mode": "exact", "predicate": {
        "op": "eq", "left": {"ref": {"step": "weather", "field": "rain_expected"}}, "right": True},
        "yes": [{"kind": "send", "id": "umbrella", "title": "Weather", "message": [{"text": "Take an umbrella"}]}],
        "no": [{"kind": "send", "id": "dry", "title": "Weather", "message": [{"text": "It should be dry"}]}]}]
    author = Author(raw)
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Every day check Berlin weather. If rain is expected send an umbrella reminder, otherwise say it should be dry",
        {"timezone": "UTC"}, object(), author)
    assert result["action"] == "create_workflow" and author.calls == 1
    check = next(node for node in result["graph"]["nodes"] if node["type"] == "check")
    assert check["config"]["mode"] == "exact"
    assert check["config"]["predicate"]["left"] == "$nodes.weather.output.rain_expected"
    assert {edge.get("branch") for edge in result["graph"]["edges"] if edge["from"] == "rain"} == {"yes", "no"}


# contract-test: supporting surface=rest_api assertions=workflows.authoring.compact-plan,workflows.authoring.provisional-validation
@pytest.mark.asyncio
async def test_compact_return_does_not_reject_json_whitespace_after_validated_node_callbacks(monkeypatch):
    configure(monkeypatch)

    class CompactReturningAuthor(FlatAuthor):
        async def generate(self, **kwargs):
            await super().generate(**kwargs)
            return forecast_plan(), {"seconds": 0.02, "estimated_cost_usd": 0.002}

    raw = flat_forecast()
    for node in raw["workflows"][0]["nodes"]:
        for key, value in list(node.items()):
            if key.endswith("_json"):
                node[key] = json.dumps(json.loads(value), indent=2)
    author = CompactReturningAuthor([raw])
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Daily forecast", {"timezone": "Europe/Berlin"}, object(), author)
    assert result["action"] == "create_workflow" and len(author.requests) == 1
