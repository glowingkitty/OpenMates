"""Exercise real workflow recovery and persistence in a disposable CI database.

The production planner, native authors, parsers, billing arithmetic and input
service execute unchanged. Only provider/Jev replies, wallet transport and the
payload cipher are deterministic test boundaries. Synthetic owners never refer
to accounts. The CLI refuses every host except the isolated CI CMS service.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch
import uuid

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.api.app.services import workflow_authoring_billing as billing_module
from backend.core.api.app.services.workflow_authoring_billing import GEMINI_MODEL, MERCURY_MODEL
from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)
from backend.core.api.app.services.workflow_gemini_authoring import WorkflowGeminiAuthor
from backend.core.api.app.services.workflow_input_service import WorkflowInputService
from backend.core.api.app.services.workflow_mercury_authoring import WorkflowMercuryAuthor
from backend.core.api.app.services.workflow_registry_planner import (
    PARTIAL_FAILURE, PARTIAL_STOPPED, WorkflowRegistryPlanner,
)
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService, _hash_owner_id
from backend.scripts.probe_workflow_authoring_transaction import _rows
from backend.shared.providers.inception import InceptionClient
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.tests.workflow_test_utils import FakeWorkflowPayloadCipher

SCENARIOS = ("mercury_recovery", "gemini_recovery", "exhaustion", "stop", "outage")
PROMPT = "Every day at 08:00 UTC get today's Berlin weather and send its results to chat."


def _flat_plan(*, valid: bool, attempt: int) -> dict[str, Any]:
    return {"workflows": [{"header": {
        "operation": "create", "title": "Berlin forecast", "description": "Daily weather results",
        "icon": "cloud-rain", "schedule": {"type": "daily", "time": "08:00", "timezone": "UTC"},
    }, "nodes": [
        {"kind": "app", "id": "weather", "capability": "weather.forecast",
         "input_json": json.dumps({"location": "Berlin", "days": 1})},
        {"kind": "send", "id": "message" if valid else f"rejected_{attempt}", "title": "Forecast",
         "message_json": json.dumps([{"ref": {"step": "weather", "field": "results"}}]) if valid else "{"},
    ]}]}


class _Secrets:
    async def get_secret(self, secret_path: str, secret_key: str) -> str:
        assert secret_path in {"kv/data/providers/inception_labs", "kv/data/providers/google_ai_studio"}
        assert secret_key == "api_key"
        return "synthetic-noncredential"


class _Jev:
    """Answer actual registry-generated questions without bypassing preselection."""

    async def evaluate(self, *, state, questions, **_kwargs):
        assert isinstance(state, dict)
        preferred = {"operation": "create", "check_mode": "none", "workflow_count": "1",
                     "request_clarity": "clear", "schedule_timezone": "UTC"}
        answers = {}
        for name, question in questions.items():
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": float(name in {"weather.forecast", "chat_delivery"})}
            else:
                assert question["type"] == "choice" and name in preferred
                value = preferred[name]
                assert value in question["criteria"]
                answers[name] = {"type": "choice", "choice": value, "confidence": 1.0,
                                 "probabilities": {key: float(key == value) for key in question["criteria"]}}
        return DecisionResponse.model_validate({"provider": "typesafe", "model": "jev-1.14", "answers": answers,
                                               "usage": {"input_tokens": 100, "output_tokens": len(answers)}})


class _Upstream:
    """Mock HTTP only: native clients must still parse each complete SSE response."""

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.requests: list[dict[str, Any]] = []

    def response(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        mercury = request.url.host == "api.inceptionlabs.ai"
        assert mercury or request.url.host == "generativelanguage.googleapis.com"
        profile = payload["reasoning_effort"] if mercury else payload["generationConfig"]["thinkingConfig"]["thinkingLevel"]
        user = json.loads(payload["messages"][1]["content"] if mercury else payload["contents"][0]["parts"][0]["text"])
        self.requests.append({"model": MERCURY_MODEL if mercury else GEMINI_MODEL,
                              "profile": profile, "user": user})
        if self.scenario == "outage" and mercury:
            return httpx.Response(503, json={"error": {"message": "Synthetic unavailable supplier"}})
        valid = ((self.scenario == "mercury_recovery" and mercury and profile == "low")
                 or (self.scenario in {"gemini_recovery", "outage"} and not mercury))
        text = json.dumps(_flat_plan(valid=valid, attempt=len(self.requests)))
        if mercury:
            events = [{"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 30,
                       "total_tokens": 130, "prompt_tokens_details": {"cached_tokens": 80}}},
                      {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}]
        else:
            events = [{"usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 40,
                                         "thoughtsTokenCount": 10, "totalTokenCount": 250}},
                      {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}]
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        if mercury:
            body += "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def exercise_recovery(make_service: Callable[[], WorkflowService], owner: str) -> list[dict[str, Any]]:
    """Same assertions run locally with memory storage and in CI with Directus."""
    outcomes = []
    registry = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry())
    for scenario in SCENARIOS:
        upstream = _Upstream(scenario)
        transport = httpx.MockTransport(upstream.response)
        gemini_client = httpx.AsyncClient(transport=transport)
        def factory(key, **kwargs):
            return InceptionClient(key, transport=transport, **kwargs)
        secrets = _Secrets()
        planner = WorkflowRegistryPlanner(secrets_manager=secrets, jev_client=_Jev(), registry=registry,
            author=WorkflowMercuryAuthor(secrets, native_client_factory=factory),
            recovery_author=WorkflowMercuryAuthor(secrets, native_client_factory=factory, reasoning_effort="low"),
            fallback_author=WorkflowGeminiAuthor(secrets, gemini_client))
        service = make_service()
        inputs = WorkflowInputService(workflow_service=service, planner=planner)
        events, charges, prechecks = [], [], []
        idempotency_key = f"ci-recovery-{scenario}"
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow-input:{owner}:personal:{idempotency_key}"))

        def observe(event):
            events.append(deepcopy(event))
            if scenario == "stop" and event.get("type") == "preview" and event.get("accepted_node_count") == 1:
                stopped = inputs.stop(user_id=owner, session_id=session_id)
                assert stopped.stop_requested

        async def precheck(**kwargs):
            prechecks.append(kwargs)

        async def charge(**kwargs):
            charges.append(kwargs)
            return {"charged_credits": kwargs["credits"]}

        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(billing_module, "ensure_credit_headroom", precheck))
                stack.enter_context(patch.dict(sys.modules, {
                    "backend.core.api.app.routes.apps_api": SimpleNamespace(charge_credits_via_internal_api=charge)}))
                result = inputs.start(user_id=owner, text=PROMPT, timezone="UTC", on_event=observe,
                                      idempotency_key=idempotency_key)
            assert result.error_code is None, (scenario, result.error_code, result.message)
            assert result.workflow is not None
            metrics = result.authoring_metrics
            assert metrics is not None
            expected = [(MERCURY_MODEL, "instant")]
            if scenario != "stop":
                if scenario != "outage":
                    expected.append((MERCURY_MODEL, "low"))
                if scenario != "mercury_recovery":
                    expected.append((GEMINI_MODEL, "low"))
            assert [(row["model"], row["profile"]) for row in upstream.requests] == expected
            assert [(row["model_used"], row["reasoning_effort"]) for row in metrics["generation_attempts"]] == expected
            prefix = _flat_plan(valid=True, attempt=0)["workflows"][0]["nodes"][:1]
            for index, request in enumerate(upstream.requests[1:], start=1):
                accepted = request["user"].get("accepted_prefixes", [])
                if scenario == "outage":
                    assert accepted == []
                else:
                    assert len(accepted) == 1 and accepted[0]["nodes"] == prefix
                    assert "rejected_" not in json.dumps(accepted)
                    assert request["user"].get("validation_correction")
            previews = [e for e in events if e.get("type") == "preview"]
            complete = scenario in {"mercury_recovery", "gemini_recovery", "outage"}
            assert [e["accepted_node_count"] for e in previews] == ([0, 1, 2] if complete else [0, 1])
            graph = result.workflow.graph.model_dump(mode="json", by_alias=True)
            assert [n["id"] for n in graph["nodes"]] == (["trigger", "weather", "message"] if complete else ["trigger", "weather"])
            assert len({n["id"] for n in graph["nodes"]}) == len(graph["nodes"])
            assert result.workflow.enabled is False
            if complete:
                assert result.status == "executed" and result.partial_reason is None
                assert graph["nodes"][-1]["config"]["message"] == "{{ $nodes.weather.output.results }}"
            else:
                assert result.status == "draft"
                assert result.partial_reason == ("stopped" if scenario == "stop" else "provider_error")
                assert result.message == result.partial_warning == (PARTIAL_STOPPED if scenario == "stop" else PARTIAL_FAILURE)
                if scenario == "exhaustion":
                    assert "could not be created" in result.message and "disabled" in result.message
                    assert "edit it manually" in result.message
                assert graph == previews[-1]["graph"]
            entries = [e for e in metrics["billing"]["entries"] if e["model_used"] in {MERCURY_MODEL, GEMINI_MODEL}]
            assert [(e["model_used"], e["reasoning_effort"]) for e in entries] == expected
            assert [e["provider_step"] for e in entries] == [
                f"{'mercury' if model == MERCURY_MODEL else 'gemini'}:{index}" for index, (model, _) in enumerate(expected)]
            assert len(prechecks) == len(metrics["billing"]["entries"])
            charged_authors = [c["usage_details"] for c in charges if c["usage_details"]["model_used"] in {MERCURY_MODEL, GEMINI_MODEL}]
            assert [(c["model_used"], c["reasoning_effort"]) for c in charged_authors] == (expected[1:] if scenario == "outage" else expected)
            assert len({c["idempotency_key"] for c in charges}) == len(charges)
            if scenario == "outage":
                assert entries[0]["metered"] is False and entries[0]["credits_charged"] == 0
            for charge_row in charged_authors:
                if charge_row["model_used"] == MERCURY_MODEL:
                    assert charge_row["input_tokens"] == 100 and charge_row["cache_read_input_tokens"] == 80
                    assert charge_row["uncached_input_tokens"] == 20
            # A fresh service must decrypt the published record from the actual
            # repository; provisional model output alone cannot satisfy this.
            reloaded = make_service().get_workflow(result.workflow.id, owner)
            assert reloaded.graph.model_dump(mode="json", by_alias=True) == graph
            assert reloaded.enabled is False and reloaded.title == "Berlin forecast"
            outcomes.append({"scenario": scenario, "workflow_id": reloaded.id,
                             "status": result.status, "profiles": [profile for _, profile in expected]})
        finally:
            asyncio.run(gemini_client.aclose())
    assert len(make_service().list_workflows(owner)) == len(SCENARIOS)
    return outcomes


def main() -> None:
    if (os.getenv("CI") != "true" or os.getenv("OPENMATES_CI_ISOLATED") != "1"
            or os.getenv("CMS_URL", "").rstrip("/") != "http://cms:8055"):
        raise RuntimeError("Recovery probe requires the disposable isolated CI CMS")
    owner = "ci-recovery-" + str(uuid.uuid4())
    owner_hash = _hash_owner_id(owner)
    cipher = FakeWorkflowPayloadCipher()
    repositories = []

    def make_service():
        repository = DirectusWorkflowRepository()
        repositories.append(repository)
        return WorkflowService(repository=repository, payload_cipher=cipher)

    admin = httpx.Client(base_url="http://cms:8055", timeout=30)
    try:
        login = admin.post("/auth/login", json={"email": os.environ["DATABASE_ADMIN_EMAIL"],
                          "password": os.environ["DATABASE_ADMIN_PASSWORD"], "mode": "json"})
        login.raise_for_status()
        admin.headers["Authorization"] = "Bearer " + login.json()["data"]["access_token"]
        exercise_recovery(make_service, owner)
        for table in ("workflows", "workflow_versions", "workflow_input_mutations", "workflow_authoring_operations"):
            assert len(_rows(admin, table, owner_hash)) == len(SCENARIOS), table
        print("real-db workflow authoring recovery passed")
    finally:
        try:
            for table in ("workflow_triggers", "workflow_input_mutations", "workflow_authoring_operations",
                          "workflow_versions", "workflow_encrypted_blobs", "workflows"):
                for row in _rows(admin, table, owner_hash):
                    admin.delete(f"/items/{table}/{row['id']}").raise_for_status()
        finally:
            for repository in repositories:
                repository._client.close()
            admin.close()


if __name__ == "__main__":
    main()
