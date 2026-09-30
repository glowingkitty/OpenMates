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


def configure(monkeypatch, *, operation="create", count=1, unavailable=False, clarity="clear", check_mode="none"):
    registry = WorkflowCapabilityRegistry()
    selection = WorkflowPreselection([registry.get_capability("weather.forecast"), registry.get_capability("ai.ask")],
                                     operation, check_mode, True, {},
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
async def test_create_streams_inert_preview_then_returns_validated_disabled_plan(monkeypatch):
    configure(monkeypatch)
    events = []
    author = Author(forecast_plan())
    planner = module.WorkflowRegistryPlanner(secrets_manager=None, author=author, jev_client=object())
    result = await planner._plan("Daily forecast", {"timezone": "Europe/Berlin", "_on_component": events.append},
                                 object(), author)
    assert result["action"] == "create_workflow" and result["enabled"] is False
    previews = [event for event in events if event["type"] == "preview"]
    assert [len(event["graph"]["nodes"]) for event in previews] == [1, 2, 3]
    preview = previews[1]
    assert preview["provisional"] is True and "action" not in preview
    assert {node["id"] for node in preview["graph"]["nodes"]} == {"trigger", "weather"}
    assert len(result["graph"]["nodes"]) == 3
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
async def test_missing_requested_check_reports_specific_finalization_code(monkeypatch):
    configure(monkeypatch, check_mode="ai")
    author = Author(forecast_plan())
    result = await module.WorkflowRegistryPlanner(secrets_manager=None)._plan(
        "Send forecast only if it is useful", {"timezone": "UTC"}, object(), author)
    assert result["action"] == "partial" and author.calls == 2
    assert result["_authoring_metrics"]["last_failure_reason_code"] == "check_mode_omitted"
    assert all(attempt["failure_reason_code"] == "check_mode_omitted"
               for attempt in result["_authoring_metrics"]["generation_attempts"])


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
