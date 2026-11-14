"""AI evaluation source runner: threshold gating and route outcomes with the model mocked."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.api.app.services.user_check_ai_evaluator import AiEvaluationError, evaluate_check_source
from backend.core.api.app.services.user_check_service import CheckError


def response(verdict, band):
    from backend.shared.providers.typesafe.models import ChoiceAnswer  # noqa: F401
    return SimpleNamespace(answers={
        "verdict": SimpleNamespace(choice=verdict, confidence=0.9),
        "quality": SimpleNamespace(choice=band, confidence=0.9),
    })


@pytest.fixture(autouse=True)
def plain_choice(monkeypatch):
    from backend.core.api.app.services import user_check_ai_evaluator as module
    monkeypatch.setattr(module, "choice_value", lambda r, q, min_confidence=0.0: r.answers[q].choice)


# contract-test: supporting surface=rest_api assertions=checks.ai.structured-bounded
@pytest.mark.asyncio
async def test_pass_above_threshold() -> None:
    result = await evaluate_check_source("q", "e", evaluator=AsyncMock(return_value=response("pass", "good")))
    assert (result.verdict, result.score) == ("pass", 80)


# contract-test: supporting surface=rest_api assertions=checks.ai.structured-bounded
@pytest.mark.asyncio
async def test_below_threshold_fails() -> None:
    result = await evaluate_check_source("q", "e", threshold=90, evaluator=AsyncMock(return_value=response("pass", "good")))
    assert result.verdict == "fail" and result.score == 80


# contract-test: supporting surface=rest_api assertions=checks.ai.structured-bounded
@pytest.mark.asyncio
async def test_model_error_raises() -> None:
    with pytest.raises(AiEvaluationError):
        await evaluate_check_source("q", "e", evaluator=AsyncMock(side_effect=RuntimeError("down")))


def client(service):
    pytest.importorskip("slowapi")
    from backend.core.api.app.routes import user_checks
    app = FastAPI()
    app.include_router(user_checks.router)
    app.state.directus_service = SimpleNamespace()
    app.state.secrets_manager = None
    app.dependency_overrides[user_checks.get_current_user_or_api_key] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[user_checks.ensure_projects_enabled] = lambda: None
    user_checks.limiter.enabled = False
    patches = [patch.object(user_checks, "UserCheckService", return_value=service),
               patch.object(user_checks, "_bill_ai_evaluation", AsyncMock())]
    for p in patches:
        p.start()
    return TestClient(app), patches


def make_service(require=None):
    service = AsyncMock()
    service.require_binding = AsyncMock(side_effect=require)
    service.record_result = AsyncMock(return_value={"run": {"status": "passed"}})
    return service


def post(service, model):
    test_client, patches = client(service)
    from backend.core.api.app.routes import user_checks
    try:
        with patch.object(user_checks, "evaluate_check_source", model):
            return test_client.post(f"/v1/user-checks/runs/{uuid4()}/sources/ai/ai-evaluate",
                                    json={"question": "Is it ok?", "evidence": "yes"})
    finally:
        for p in patches:
            p.stop()


# contract-test: direct surface=rest_api assertions=checks.ai.structured-bounded,checks.sources.mixed-types
def test_route_passed_stores_score() -> None:
    from backend.core.api.app.services.user_check_ai_evaluator import AiEvaluation
    service = make_service()
    res = post(service, AsyncMock(return_value=AiEvaluation("pass", 80, "ok")))
    assert res.status_code == 200 and res.json()["verdict"] == "pass" and res.json()["feedback"] == "ok"
    body = service.record_result.await_args.args[3]
    assert body["status"] == "passed" and body["ai_score"] == 80 and body["ai_threshold"] == 70


# contract-test: direct surface=rest_api assertions=checks.ai.structured-bounded
def test_route_failed_below_threshold() -> None:
    from backend.core.api.app.services.user_check_ai_evaluator import AiEvaluation
    service = make_service()
    res = post(service, AsyncMock(return_value=AiEvaluation("fail", 35, "no")))
    assert res.json()["verdict"] == "fail" and service.record_result.await_args.args[3]["status"] == "failed"


# contract-test: direct surface=rest_api assertions=checks.types.explicit
def test_route_wrong_binding_kind_is_422() -> None:
    model = AsyncMock()
    res = post(make_service(require=CheckError("CHECK_RESULT_MISMATCH", 422)), model)
    assert res.status_code == 422 and res.json()["detail"]["error"] == "CHECK_RESULT_MISMATCH"
    model.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=checks.ai.structured-bounded
def test_route_model_error_stores_error_status() -> None:
    service = make_service()
    res = post(service, AsyncMock(side_effect=AiEvaluationError("ai_evaluation_unavailable")))
    assert res.json()["verdict"] == "error" and service.record_result.await_args.args[3]["status"] == "error"
