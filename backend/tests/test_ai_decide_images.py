"""Transient image validation, provider wire format, and bounded admission."""
from __future__ import annotations

import base64
import io
import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from backend.apps.ai.skills import decide_skill
from backend.core.api.app.middleware.ai_decide_body import AIDecideBodyLimitMiddleware
from backend.shared.providers.typesafe.assets import MAX_ASSET_BYTES, MAX_DECISION_BODY_BYTES
from backend.shared.providers.typesafe.client import JevDecisionClient
from backend.shared.python_utils.ai_decide import DecideRequest, decision_quote, decision_result_credits
from backend.tests.test_ai_decide import ANSWER, BODY, _request

REFERENCE = "550e8400-e29b-41d4-a716-446655440000"


def image_asset(fmt: str = "PNG", size: tuple[int, int] = (280, 280), *, noisy: bool = False) -> dict:
    data = io.BytesIO()
    image = Image.frombytes("RGB", size, random.Random(13).randbytes(size[0] * size[1] * 3)) if noisy else Image.new("RGB", size, "blue")
    image.save(data, format=fmt)
    return {"type": "image", "format": "png" if fmt == "PNG" else "jpeg", "data_base64": base64.b64encode(data.getvalue()).decode("ascii")}


def image_body(asset: dict | None = None) -> dict:
    return {**BODY, "state": {"photo": REFERENCE}, "assets": {REFERENCE: asset or image_asset()}}


# contract-test: direct surface=rest_api assertions=ai-decide.request.bounded,ai-decide.images.inline
@pytest.mark.parametrize("invalid", ["base64", "padding", "url", "format", "bytes", "small", "large", "gif", "animated", "unreferenced", "key_only", "not_uuid", "too_many", "oversize"])
def test_invalid_images_fail_before_dispatch_and_quote(invalid: str) -> None:
    body = image_body()
    asset = body["assets"][REFERENCE]
    if invalid == "base64":
        asset["data_base64"] = "PRIVATE_IMAGE_BYTES_NOT_BASE64"
    elif invalid == "padding":
        asset["data_base64"] += "="
    elif invalid == "url":
        asset["url"] = "https://private.invalid/photo.png"
    elif invalid == "format":
        asset["format"] = "jpeg"
    elif invalid == "bytes":
        asset["data_base64"] = base64.b64encode(b"PRIVATE_IMAGE_BYTES").decode()
    elif invalid in {"small", "large"}:
        body = image_body(image_asset(size=(279 if invalid == "small" else 1569, 280)))
    elif invalid == "gif":
        body = image_body(image_asset("GIF"))
    elif invalid == "animated":
        data = io.BytesIO()
        Image.new("RGB", (280, 280), "blue").save(data, format="PNG", save_all=True, append_images=[Image.new("RGB", (280, 280), "red")])
        asset["data_base64"] = base64.b64encode(data.getvalue()).decode()
    elif invalid == "unreferenced":
        body["state"] = "an image"
    elif invalid == "key_only":
        body["state"] = {REFERENCE: "Object keys do not use image assets"}
    elif invalid == "not_uuid":
        body["assets"] = {"photo": asset}
        body["state"] = "photo"
    elif invalid == "too_many":
        body["assets"] = {f"550e8400-e29b-41d4-a716-{i:012d}": asset for i in range(5)}
        body["state"] = list(body["assets"])
    elif invalid == "oversize":
        asset["data_base64"] = base64.b64encode(b"x" * (MAX_ASSET_BYTES + 1)).decode()
    with pytest.raises(ValidationError) as caught:
        DecideRequest.model_validate(body)
    assert "PRIVATE_IMAGE_BYTES" not in str(caught.value)
    assert asset["data_base64"] not in str(caught.value)


# contract-test: direct surface=rest_api assertions=ai-decide.images.inline,ai-decide.request.bounded
@pytest.mark.parametrize("location", ["state", "instructions", "choice", "score", "noul"])
def test_image_references_work_in_string_values_for_all_question_types(location: str) -> None:
    body = image_body()
    if location != "state":
        body["state"] = {"text": "Classify the supplied image"}
        body["questions"] = json.loads(json.dumps(BODY["questions"]))
        if location == "instructions":
            body["questions"]["safe"]["instructions"] = f"Is this safe? {REFERENCE}"
        elif location == "choice":
            body["questions"]["route"]["criteria"]["account"] = REFERENCE
        elif location == "score":
            body["questions"]["priority"]["criteria"][0] = REFERENCE
        else:
            body["questions"]["safe"]["criteria"] = {"true": REFERENCE, "false": "Other"}
    parsed = DecideRequest.model_validate(body)
    assert parsed.assets[REFERENCE].format == "png"
    assert decision_quote(has_assets=True) == 9
    assert decision_quote() == 43
    assert "data_base64" not in repr(parsed)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.images.inline,ai-decide.billing.bounded
@pytest.mark.parametrize("status", [200, 503, 400])
async def test_images_send_exact_wire_header_never_fallback_and_account_failure(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int) -> None:
    body = image_body()
    calls = []
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host == "api.typesafe.ai"
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert "TypeSafe-Danger-Zone-Long-Context" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "jev-1.14.0"
        assert payload["assets"] == body["assets"]
        return httpx.Response(status, json=ANSWER if status == 200 else {"error": {"code": "max_tokens_exceeded" if status == 400 else "unavailable"}})
    monkeypatch.setenv("SECRET__TYPESAFE__API_KEY", "test")
    monkeypatch.setenv("SECRET__OPENROUTER__API_KEY", "test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(decide_skill, "JevDecisionClient", lambda **kwargs: JevDecisionClient(http_client=client, **kwargs))
        skill = object.__new__(decide_skill.DecideSkill)
        if status == 200:
            result = await skill.execute(DecideRequest.model_validate(body))
            assert result.usage.credits == 2
            assert decision_result_credits(result.model_dump(), has_assets=True) == 2
        else:
            with pytest.raises(HTTPException) as caught:
                await skill.execute(DecideRequest.model_validate(body))
            assert caught.value.status_code == (422 if status == 400 else 503)
            assert caught.value.incurred_credits == 9
    assert len(calls) == 1
    assert body["assets"][REFERENCE]["data_base64"] not in caplog.text


# contract-test: direct surface=rest_api assertions=ai-decide.request.bounded,ai-decide.images.inline
@pytest.mark.parametrize("path", ["/v1/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide/availability"])
def test_decide_body_bound_runs_before_json_parse(path: str) -> None:
    app = FastAPI()
    app.add_middleware(AIDecideBodyLimitMiddleware)
    parsed = []
    @app.post(path)
    async def route(request: Request):
        parsed.append(True)
        return await request.json()
    with TestClient(app) as client:
        response = client.post(path, content=b"x" * (MAX_DECISION_BODY_BYTES + 1), headers={"Content-Type": "application/json"})
        assert response.status_code == 413
        assert parsed == []
        multipart = client.post(path, content=b"anything", headers={"Content-Type": "multipart/form-data"})
        assert multipart.status_code == 415
        assert parsed == []
        valid = client.post(path, json=image_body())
        assert valid.status_code == 200


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.request.bounded
async def test_streamed_body_without_content_length_is_bounded_before_inner_app() -> None:
    inner = AsyncMock()
    receive = AsyncMock(side_effect=[{"type": "http.request", "body": b"x" * MAX_DECISION_BODY_BYTES, "more_body": True},
                                    {"type": "http.request", "body": b"x", "more_body": False}])
    send = AsyncMock()
    await AIDecideBodyLimitMiddleware(inner)({"type": "http", "method": "POST", "path": "/v1/apps/ai/skills/decide", "headers": []}, receive, send)
    inner.assert_not_awaited()
    assert send.call_args_list[0].args[0]["status"] == 413


# contract-test: direct surface=rest_api assertions=ai-decide.images.inline,billing.anonymous.local-only-content
@pytest.mark.parametrize("path", ["/v1/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide", "/v1/anonymous/apps/ai/skills/decide/availability"])
@pytest.mark.parametrize("invalid", ["root", "json", "exception"])
def test_actual_logging_stack_never_logs_invalid_inline_image_data(path: str, invalid: str, caplog: pytest.LogCaptureFixture) -> None:
    from backend.core.api.app.middleware.logging_middleware import LoggingMiddleware
    app = FastAPI()
    app.state.metrics_service = Mock()
    @app.post(path)
    async def route(body: dict):
        if invalid == "exception":
            raise RuntimeError("PRIVATE_IMAGE_MARKER")
        return {}
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(AIDecideBodyLimitMiddleware)
    with TestClient(app, raise_server_exceptions=False) as client:
        if invalid == "root":
            response = client.post(path, json=[{"data_base64": "PRIVATE_IMAGE_MARKER"}])
        elif invalid == "json":
            response = client.post(path, content=b'{"assets":"PRIVATE_IMAGE_MARKER",', headers={"Content-Type": "application/json"})
        else:
            response = client.post(path, json={"assets": "PRIVATE_IMAGE_MARKER"})
    assert response.status_code == (500 if invalid == "exception" else 422)
    assert "PRIVATE_IMAGE_MARKER" not in caplog.text


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=ai-decide.images.inline,ai-decide.billing.bounded
async def test_anonymous_large_image_uses_image_quote_in_availability_and_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.api.app.routes import anonymous
    from backend.core.api.app.services import skill_registry
    from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
    from backend.shared.python_utils import app_skill_output_safety
    from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition
    skill = AppSkillDefinition(id="decide", name_translation_key="ai.decide", description_translation_key="ai.decide.description", anonymous_access="inline")
    result = {**ANSWER, "success": True, "usage": {**ANSWER["usage"], "credits": 2, "complete": True}}
    registry = SimpleNamespace(get_metadata=lambda app: SimpleNamespace(skills=[skill]), is_skill_available=lambda *args: True,
        dispatch_skill=AsyncMock(return_value=result))
    identity_service = AnonymousFreeUsageService(directus_service=None, hmac_secret="image-test-secret")
    service = SimpleNamespace(open_request=AsyncMock(return_value=SimpleNamespace(accepted=True)),
        request_identity=identity_service.request_identity,
        consume_local_rate_limit=AsyncMock(return_value=True), reserve_operation=AsyncMock(return_value=SimpleNamespace(accepted=True)),
        finalize_charge=AsyncMock(), release_reservation=AsyncMock(), get_public_status=AsyncMock(return_value={"active": True, "can_send_text": True}))
    monkeypatch.setattr(anonymous.limiter, "enabled", False, raising=False)
    monkeypatch.setattr(anonymous, "_require_official_cloud", lambda request: None)
    monkeypatch.setattr(anonymous, "_anonymous_usage_service", lambda *args: service)
    monkeypatch.setattr(skill_registry, "get_global_registry", lambda: registry)
    async def sanitize(result, context):
        return result
    monkeypatch.setattr(app_skill_output_safety, "sanitize_app_skill_output", sanitize)
    body = image_body(image_asset(noisy=True))
    assert len(json.dumps(body)) > 20_000
    availability = await anonymous.anonymous_app_skill_availability(_request(), "ai", "decide", body, None, None)
    assert availability.allowed is True
    assert service.get_public_status.call_args.kwargs["estimated_credits"] == 9
    response = await anonymous.anonymous_app_skill(_request(), "ai", "decide", body, None, None)
    assert response["credits_charged"] == 2
    assert service.reserve_operation.call_args.kwargs["quoted_credits"] == 9
    assert service.finalize_charge.call_args.kwargs["actual_credits"] == 2
