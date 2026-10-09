"""
backend/tests/test_anonymous_skill_access.py

Contract tests for anonymous execution gating. Anonymous callers may use only
explicitly reviewed inline skills; file, background, durable-write, and
connected-account skills are rejected before inference or provider work.
"""

from __future__ import annotations

import sys
import json
import asyncio
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request

import backend.core.api.app.routes.anonymous as anonymous_routes
from backend.core.api.app.routes.anonymous import (
    AnonymousChatStreamRequest,
    anonymous_app_skill,
    anonymous_chat_stream,
    reject_anonymous_file_payloads,
    validate_anonymous_skill_allowed,
)
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService, AnonymousReservationResult
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition
from backend.shared.python_utils.anonymous_skill_policy import filter_anonymous_tools, is_anonymous_inline_skill
from backend.shared.python_utils.anonymous_skill_policy import has_single_anonymous_provider_request
from backend.tests.test_anonymous_free_usage_budget import FakeCache, FakeDirectus


# contract-test: supporting surface=rest_api assertions=billing.anonymous.local-only-content
def test_anonymous_code_and_plot_fences_become_local_embeds_without_rewriting_bash() -> None:
    from toon_format import decode

    content = (
        'Set the VM name.\n```bash:vm.sh\nVM_NAME="test-vm"\n'
        'echo "${VM_NAME}"\n```\n```plot\nf(x)=x^2\n```\n'
        '```json\n{"type":"app_skill_use","embed_id":"existing",'
        '"app_id":"web","skill_id":"search"}\n```'
    )
    rendered, embeds = anonymous_routes._transient_anonymous_fence_embeds(content)

    assert [embed["type"] for embed in embeds] == ["code", "math-plot"]
    assert decode(embeds[0]["content"])["code"] == 'VM_NAME="test-vm"\necho "${VM_NAME}"'
    assert decode(embeds[0]["content"])["filename"] == "vm.sh"
    assert decode(embeds[1]["content"])["plot_spec"] == "f(x)=x^2"
    assert rendered.count('```json\n{"type":') == 3
    assert '"embed_id":"existing"' in rendered
    assert "${VM_NAME}" not in rendered
    # Generated display references are safe to discard from untrusted history.
    projected = anonymous_routes._anonymous_history_content({"role": "assistant", "content": rendered})
    assert all(embed["embed_id"] not in projected for embed in embeds)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering,billing.anonymous.local-only-content
async def test_anonymous_postprocessor_uses_detected_language_and_actual_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import main_processor, model_usage_tracker, postprocessor

    calls: list[tuple[str, Any]] = []

    class UsageService:
        async def reserve_operation(self, **kwargs: Any) -> AnonymousReservationResult:
            calls.append(("reserve", kwargs))
            return AnonymousReservationResult(accepted=True, request_id=kwargs["operation_id"])

        async def finalize_charge(self, charge_id: str, *, actual_credits: int) -> None:
            calls.append(("finalize", {"charge_id": charge_id, "actual_credits": actual_credits}))

    async def fake_postprocessor(**kwargs: Any) -> postprocessor.PostProcessingResult:
        assert kwargs["is_incognito"] is False
        assert kwargs["allow_model_fallbacks"] is False
        assert kwargs["translate_ui_metadata"] is False
        assert kwargs["output_language"] == "de"
        assert kwargs["user_system_language"] == "de"
        assert kwargs["current_chat_title"] == "Deutscher Titel"
        assert kwargs["available_app_ids"] == ["web"]
        assert [skill["id"] for skill in kwargs["available_skills"]] == ["web-search"]
        return postprocessor.PostProcessingResult(
            follow_up_request_suggestions=["Erkläre mir den nächsten Schritt"],
            chat_summary="Wir haben den nächsten Schritt erklärt",
            updated_chat_title="Ein besserer deutscher Titel",
            usage_telemetry={"input_tokens": 100, "output_tokens": 30, "inference_host": "google"},
        )

    monkeypatch.setattr(main_processor, "_quote_ai_iteration_credits", lambda **kwargs: 10)
    monkeypatch.setattr(model_usage_tracker, "calculate_model_usage_credits", lambda *args, **kwargs: 2)
    monkeypatch.setattr(postprocessor, "handle_postprocessing", fake_postprocessor)

    class MetadataCache(FakeCache):
        async def get_discovered_apps_metadata(self) -> dict[str, Any]:
            def skill(skill_id: str, access: str) -> SimpleNamespace:
                return SimpleNamespace(
                    id=skill_id, anonymous_access=access, internal=False, preprocessor_hint="Test hint",
                    api_config=None,
                )
            return {
                "web": SimpleNamespace(skills=[skill("search", "inline"), skill("read", "inline")]),
                "tasks": SimpleNamespace(skills=[skill("search", "inline")]),
            }

    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1", client_chat_id="chat-1", client_message_id="msg-1",
        plaintext_message="Wie geht es weiter?", system_language="de",
    )
    event = await anonymous_routes._anonymous_post_processing_event(
        chat_id="chat-1", task_id="task-1", payload=payload,
        assistant="So geht es weiter.",
        generated_metadata={"title": "Deutscher Titel", "output_language": "de"},
        cache_service=MetadataCache(), usage_service=UsageService(), parent_request_id="parent-1",
    )

    assert event["follow_up_request_suggestions"] == ["Erkläre mir den nächsten Schritt"]
    assert event["chat_summary"] == "Wir haben den nächsten Schritt erklärt"
    assert event["updated_chat_title"] == "Ein besserer deutscher Titel"
    assert calls == [
        ("reserve", {"parent_request_id": "parent-1", "operation_id": "anonymous-postprocess:task-1",
                     "charge_id": "anonymous-postprocess:task-1", "quoted_credits": 10}),
        ("finalize", {"charge_id": "anonymous-postprocess:task-1", "actual_credits": 2}),
    ]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_postprocessor_skips_provider_when_quote_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import main_processor, postprocessor

    class DeniedUsageService:
        async def reserve_operation(self, **kwargs: Any) -> AnonymousReservationResult:
            return AnonymousReservationResult(accepted=False, request_id=kwargs["operation_id"], reason="budget_exhausted")

        async def finalize_charge(self, *args: Any, **kwargs: Any) -> None:
            pytest.fail("Denied metadata operation must not finalize")

    async def unexpected_postprocessor(**kwargs: Any) -> Any:
        pytest.fail("Denied metadata operation must not call a provider")

    monkeypatch.setattr(main_processor, "_quote_ai_iteration_credits", lambda **kwargs: 10)
    monkeypatch.setattr(postprocessor, "handle_postprocessing", unexpected_postprocessor)
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1", client_chat_id="chat-1", client_message_id="msg-1",
        plaintext_message="Wie geht es weiter?", system_language="de", current_chat_summary="Vorher",
    )
    event = await anonymous_routes._anonymous_post_processing_event(
        chat_id="chat-1", task_id="task-1", payload=payload,
        assistant="So geht es weiter.", generated_metadata={},
        cache_service=FakeCache(), usage_service=DeniedUsageService(), parent_request_id="parent-1",
    )

    assert event["chat_summary"] == "Vorher"
    assert event["follow_up_request_suggestions"] == []


@pytest.fixture(autouse=True)
def use_in_process_anonymous_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        anonymous_routes,
        "_anonymous_usage_service",
        lambda directus_service, cache_service: AnonymousFreeUsageService(
            directus_service=directus_service,
            cache_service=cache_service,
            hmac_secret="test-secret",
        ),
    )


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_skill_without_connected_account_requirement_is_allowed() -> None:
    skill = {
        "id": "search",
        "anonymous_access": "inline",
    }
    validate_anonymous_skill_allowed("events", skill)


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_connected_account_skill_is_rejected_for_anonymous_callers() -> None:
    skill = {
        "id": "get-events",
        "anonymous_access": "inline",
    }

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("calendar", skill)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_missing_connected_account_classification_fails_closed() -> None:
    skill = {"id": "unknown"}

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("unknown", skill)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "skill_metadata_missing"


@pytest.mark.parametrize("app_id, skill_id", [
    ("images", "generate"), ("music", "generate"), ("videos", "create"),
    ("social_media", "search"), ("weather", "rain_radar"),
    ("web", "read"), ("videos", "get_transcript"),
    ("tasks", "search"),
])
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_file_background_and_account_state_skills_are_rejected_even_if_misclassified(app_id: str, skill_id: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed(app_id, {"id": skill_id, "anonymous_access": "inline"})
    assert exc_info.value.status_code == 403


# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_every_app_skill_has_reviewed_anonymous_classification() -> None:
    apps_dir = Path(__file__).resolve().parents[1] / "apps"
    inline = set()
    for app_yml in sorted(apps_dir.glob("*/app.yml")):
        app_id = app_yml.parent.name
        metadata = yaml.safe_load(app_yml.read_text()) or {}
        for raw_skill in metadata.get("skills", []):
            assert raw_skill.get("anonymous_access") in {"inline", "authenticated"}, (app_id, raw_skill.get("id"))
            skill = AppSkillDefinition.model_validate(raw_skill)
            if skill.anonymous_access == "inline":
                assert is_anonymous_inline_skill(app_id, skill), (app_id, skill.id)
                inline.add((app_id, skill.id))
    assert {("events", "search"), ("web", "search"), ("math", "calculate")} <= inline
    assert not {
        ("images", "generate"), ("social_media", "search"), ("tasks", "create"),
        ("web", "read"), ("videos", "get_transcript"),
    } & inline


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_chat_offers_inline_search_but_no_file_or_system_tools() -> None:
    apps_metadata = {
        "events": SimpleNamespace(skills=[SimpleNamespace(id="search", anonymous_access="inline", internal=False)]),
        "images": SimpleNamespace(skills=[SimpleNamespace(id="generate", anonymous_access="authenticated", internal=False)]),
    }
    tools = [
        {"function": {"name": name}}
        for name in ("events-search", "images-generate", "start_sub_chats")
    ]
    assert filter_anonymous_tools(tools, apps_metadata, lambda name: name.replace("_", "-")) == tools[:1]


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering,billing.anonymous.local-only-content,apps.anonymous.cli-equivalent-gate
async def test_anonymous_direct_skill_uses_shared_cap_without_content_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.shared.python_utils import app_skill_output_safety

    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True, monthly_budget_credits=100, daily_hard_cap_percent=10,
        weekly_cap_percent=50, per_identity_daily_cap_credits=100,
        admin_user_id="admin-1",
    )
    skill = SimpleNamespace(
        id="search", internal=False, anonymous_access="inline", api_config=None,
        pricing=SimpleNamespace(model_dump=lambda **_kwargs: {"per_unit": {"credits": 6}}),
        providers=[], full_model_reference=None,
        model_dump=lambda: {"id": "search", "anonymous_access": "inline", "internal": False},
    )
    metadata = SimpleNamespace(skills=[skill])
    dispatched: list[dict] = []

    class FakeRegistry:
        def get_metadata(self, app_id: str):
            assert app_id == "web"
            return metadata

        def is_skill_available(self, app_id: str, skill_id: str) -> bool:
            return (app_id, skill_id) == ("web", "search")

        async def dispatch_skill(self, app_id: str, skill_id: str, body: dict) -> dict:
            dispatched.append(body)
            return {"success": True, "data": {"results": [{"title": "Example"}]}}

    fake_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_registry_module)
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(app_skill_output_safety, "sanitize_app_skill_output", lambda result, _context: asyncio.sleep(0, result=result))
    request = Request({
        "type": "http", "method": "POST", "path": "/v1/anonymous/apps/web/skills/search",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"x-openmates-anonymous-id", b"guest-1")],
        "client": ("198.51.100.7", 443),
        "app": SimpleNamespace(state=SimpleNamespace(secrets_manager=None)),
    })
    body = {"requests": [{"query": "test query"}]}
    before = await anonymous_routes.anonymous_app_skill_availability(request, "web", "search", body, directus, FakeCache())
    assert before.allowed is True
    assert not dispatched
    assert (await service.get_budget_status()).daily_used_credits == 0
    first = await anonymous_app_skill(request, "web", "search", body, directus, FakeCache())
    assert first["credits_charged"] == 6
    assert len(dispatched) == 1
    assert dispatched[0] == body
    assert (await service.get_budget_status()).daily_used_credits == 6
    assert {collection for collection, _ in directus.created_payloads} <= {
        "anonymous_free_usage_budget", "anonymous_free_usage_identity_daily", "anonymous_free_usage_reservations",
    }
    after = await anonymous_routes.anonymous_app_skill_availability(request, "web", "search", body, directus, FakeCache())
    assert after.allowed is False
    assert after.reason in {"budget_exhausted", "per_identity_exhausted"}
    assert len(dispatched) == 1
    assert (await service.get_budget_status()).daily_used_credits == 6
    with pytest.raises(HTTPException) as exc_info:
        await anonymous_app_skill(request, "web", "search", body, directus, FakeCache())
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "budget_exhausted"
    assert len(dispatched) == 1


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_direct_skill_rejects_private_references() -> None:
    with pytest.raises(HTTPException) as exc_info:
        anonymous_routes._reject_anonymous_skill_references({"requests": [{"embed_id": "private-embed"}]})
    assert exc_info.value.status_code == 403


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_input_cannot_multiply_a_single_provider_quote() -> None:
    assert has_single_anonymous_provider_request("web", "search", {"requests": [{"query": "one"}]})
    assert not has_single_anonymous_provider_request("web", "search", {"requests": []})
    assert not has_single_anonymous_provider_request("web", "search", {"requests": [{"query": "one"}, {"query": "two"}]})
    assert has_single_anonymous_provider_request("business", "company_financials", {"companies": [{"query": "AAPL"}]})
    assert not has_single_anonymous_provider_request(
        "business", "company_financials", {"companies": [{"query": "AAPL"}, {"query": "MSFT"}]}
    )


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_rate_limit_rejects_before_background_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.apps.ai.processing import rate_limiting
    from backend.apps.ai.processing.skill_executor import execute_skill

    async def denied(**_kwargs: Any) -> tuple[bool, float]:
        return False, 10.0

    class NoQueueProducer:
        def signature(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("anonymous work was queued")

    class RateLimitedRegistry:
        def has_app(self, _app_id: str) -> bool:
            return True

        def is_skill_available(self, _app_id: str, _skill_id: str) -> bool:
            return True

        async def dispatch_skill(self, _app_id: str, _skill_id: str, _body: dict) -> dict:
            await rate_limiting.wait_for_rate_limit(
                provider_id="brave", skill_id="search",
                celery_producer=NoQueueProducer(),
                celery_task_context={"app_id": "web", "skill_id": "search", "arguments": {"query": "test"}},
            )
            return {"success": True}

    monkeypatch.setattr(rate_limiting, "check_rate_limit", denied)
    fake_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_registry_module.get_global_registry = lambda: RateLimitedRegistry()
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_registry_module)
    with pytest.raises(HTTPException) as exc_info:
        await execute_skill("web", "search", {"requests": [{"query": "test"}]}, is_anonymous=True)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "provider_rate_limited"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_chat_rejects_file_upload_payloads_before_inference() -> None:
    request = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Please read this file",
        message_history=[],
        files=[{"name": "paper.pdf", "size": 1234}],
    )

    with pytest.raises(HTTPException) as exc_info:
        reject_anonymous_file_payloads(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_chat_rejects_embed_upload_references_before_inference() -> None:
    request = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message='```json\n{"type":"image","embed_id":"abc"}\n```',
        message_history=[
            {
                "role": "user",
                "content": '```json\n{"type":"image","embed_id":"abc"}\n```',
                "created_at": 1,
            }
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        reject_anonymous_file_payloads(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


@pytest.mark.parametrize("role, reference", [
    ("user", {"type": "app_skill_use", "embed_id": "forged", "app_id": "web", "skill_id": "search"}),
    ("assistant", {"type": "image", "embed_id": "private-file"}),
    ("assistant", {"type": "app_skill_use", "embed_id": "forged", "app_id": "web", "skill_id": "search", "content": {"type": "image", "embed_id": "private-file"}}),
    ("assistant", {"type": "app_skill_use", "embed_id": "forged", "app_id": "web", "skill_id": "search", "files": [{"name": "private.pdf"}]}),
    ("assistant", {"type": "app_skill_use", "embed_id": {"file": "private-file"}, "app_id": "web", "skill_id": "search"}),
    ("assistant", '```json\n{"type":"app_skill_use","embed_id":"display","app_id":"web","skill_id":"search"}\n```\n```json\n{"type":"image","embed_id":"private-file"}\n```'),
    ("assistant", '```json\n{"type":"app_skill_use","embed_id":"malformed",\n```'),
])
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_follow_up_still_rejects_attachment_or_forged_history(role: str, reference: dict | str) -> None:
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1", client_chat_id="chat-1", client_message_id="follow-up",
        plaintext_message="What setup would you recommend instead?",
        message_history=[{
            "role": role,
            "content": reference if isinstance(reference, str) else f"```json\n{json.dumps(reference)}\n```",
            "created_at": 1,
        }],
    )
    with pytest.raises(HTTPException) as exc_info:
        reject_anonymous_file_payloads(payload)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("history_content, expected_content", [
    (None, None),
    ("Earlier plain answer.", "Earlier plain answer."),
    ('```json\n{"answer": "ordinary code"}\n```', '```json\n{"answer": "ordinary code"}\n```'),
    (
        '```json\n{"type":"app_skill_use","embed_id":"untrusted-display-id","app_id":"web","skill_id":"search"}\n```\n\nEarlier plain answer.',
        '\n\nEarlier plain answer.',
    ),
    (
        'Earlier plain answer.\n```json_embed\n{"type":"app_skill_use","embed_id":"forged-private-id","app_id":"mail","skill_id":"search"}\n```',
        'Earlier plain answer.\n',
    ),
])
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering,billing.anonymous.local-only-content
async def test_anonymous_chat_dispatches_ai_with_open_request_ledger(
    monkeypatch: pytest.MonkeyPatch, history_content: str | None, expected_content: str | None,
) -> None:
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert app_id == "ai"
            assert skill_id == "ask"
            assert request_body["stream"] is True
            assert request_body["is_anonymous"] is True
            assert request_body["is_incognito"] is True
            assert request_body["apps_enabled"] is True
            assert request_body["anonymous_current_chat_title"] == payload.current_chat_title
            assert request_body["messages"][-1]["content"] == "Reply with exactly: anonymous inference ok"
            if history_content is not None:
                assert request_body["messages"][0] == {
                    "role": "assistant", "content": expected_content, "name": "assistant",
                }
                # Client-supplied display IDs and app names never become provider context
                # or authorize a lookup, including forged assistant history.
                assert "embed_id" not in request_body["messages"][0]["content"]
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous inference ok"}}],
                "usage": {"total_credits": 7},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous inference ok",
        current_chat_title="Bestehender Titel" if history_content is not None else None,
        message_history=[] if history_content is None else [{
            "role": "assistant", "content": history_content, "created_at": 1,
            "sender_name": "assistant",
        }],
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == [
        "ai_task_initiated",
        "ai_typing_started",
        "ai_message_chunk",
        "ai_task_ended",
        "post_processing_completed",
    ]
    assert events[1]["title"] == (
        "Bestehender Titel" if history_content is not None
        else "Reply with exactly: anonymous inference ok"
    )
    final_chunk = events[2]
    assert final_chunk["message_id"] != payload.client_message_id
    assert final_chunk["message_id"].startswith("chat-1-")
    assert final_chunk["full_content_so_far"] == "anonymous inference ok"
    assert final_chunk["is_final_chunk"] is True
    post_processing = events[4]
    assert post_processing["chat_id"] == payload.client_chat_id
    # The fake main result has no preprocessing metadata, and this unit test
    # does not configure a priced postprocessing model.
    assert post_processing["chat_summary"] == ""
    assert post_processing["follow_up_request_suggestions"] == []
    status = await service.get_budget_status()
    assert status.daily_used_credits == 0
    assert any(row.get("status") == "request_open" for row in directus.reservations.values())
    assert {collection for collection, _ in directus.created_payloads} <= {
        "anonymous_free_usage_budget", "anonymous_free_usage_identity_daily", "anonymous_free_usage_reservations",
    }


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chats.streaming.ordered-final,web-search.surface-parity
async def test_anonymous_sse_forwards_transient_app_skill_embeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def openai_stream():
        yield 'data: {"model":"openmates-ai","choices":[{"delta":{"content":"News with [source](embed:source-ref)"}}]}\n\n'
        yield (
            'data: {"model":"google/gemini-test","choices":[{"delta":{"embeds":['
            '{"embed_id":"parent-id","type":"app_skill_use","content":"app_id: news\\nskill_id: search\\nstatus: finished",'
            '"status":"finished","embed_ids":["child-id"]},'
            '{"embed_id":"child-id","type":"news_result","content":"type: news_result\\nembed_ref: source-ref\\ntitle: Source",'
            '"status":"finished","parent_embed_id":"parent-id"}'
            ']},"finish_reason":null}]}\n\n'
        )
        yield 'data: {"model":"google/gemini-test","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield 'data: [DONE]\n\n'

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> StreamingResponse:
            assert request_body["is_anonymous"] is True
            return StreamingResponse(openai_stream(), media_type="text/event-stream")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(
        AnonymousFreeUsageService,
        "open_request",
        lambda self, **kwargs: asyncio.sleep(0, result=AnonymousReservationResult(accepted=True, request_id=kwargs["request_id"])),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="anonymous-chat-1",
        client_message_id="message-1",
        plaintext_message="Search the news",
    )

    response = await anonymous_chat_stream(
        request=request,
        payload=payload,
        directus_service=FakeDirectus(),
        cache_service=FakeCache(),
    )
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    embed_events = [event for event in events if event["type"] == "send_embed_data"]
    assert [event["payload"]["embed_id"] for event in embed_events] == ["parent-id", "child-id"]
    assert [event["payload"]["type"] for event in embed_events] == ["app_skill_use", "news_result"]
    assert all(event["payload"]["chat_id"] == payload.client_chat_id for event in embed_events)
    assert all(event["payload"]["message_id"] != payload.client_message_id for event in embed_events)
    final_chunk = next(event for event in events if event["type"] == "ai_message_chunk" and event["is_final_chunk"])
    assert final_chunk["model_name"] == "google/gemini-test"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chats.streaming.ordered-final,billing.anonymous.hard-capped-provider-metering
@pytest.mark.parametrize("snapshot_kind", ["standardized", "empty", "absent"])
async def test_anonymous_sse_reports_pre_dispatch_usage_limit_without_generic_error(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_kind: str,
) -> None:
    from backend.apps.ai.utils.preprocessing_history import STANDARDIZED_USER_ERROR_MESSAGE

    async def limited_stream():
        terminal_frame = {
            "choices": [{"delta": {}, "finish_reason": "error"}],
            "failure_reason": "anonymous_usage_limit",
        }
        if snapshot_kind != "absent":
            terminal_frame["full_content"] = STANDARDIZED_USER_ERROR_MESSAGE if snapshot_kind == "standardized" else ""
        yield "data: " + json.dumps(terminal_frame) + "\n\n"
        yield "data: [DONE]\n\n"

    class FakeRegistry:
        async def dispatch_skill(self, _app_id: str, _skill_id: str, _body: dict) -> StreamingResponse:
            return StreamingResponse(limited_stream(), media_type="text/event-stream")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(
        AnonymousFreeUsageService,
        "open_request",
        lambda self, **kwargs: asyncio.sleep(0, result=AnonymousReservationResult(accepted=True, request_id=kwargs["request_id"])),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http", "method": "POST", "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1", client_chat_id="anonymous-chat-1",
        client_message_id="message-1", plaintext_message="Search docs",
    )
    response = await anonymous_chat_stream(
        request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache(),
    )
    body = "".join([chunk.decode() if isinstance(chunk, bytes) else str(chunk) async for chunk in response.body_iterator])
    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    final = next(event for event in events if event.get("is_final_chunk"))
    assert final["full_content_so_far"] == "Create an account to keep using OpenMates."
    assert final["rejection_reason"] == "anonymous_usage_limit"
    assert [event["status"] for event in events if event["type"] == "ai_task_ended"] == ["failed"]
    assert not any(event["type"] == "post_processing_completed" for event in events)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chats.streaming.ordered-final,billing.anonymous.local-only-content
@pytest.mark.parametrize("failure_reason", [None, "anonymous_usage_limit"])
async def test_anonymous_sse_uses_authoritative_final_snapshot_after_redis_prefix_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    failure_reason: str | None,
) -> None:
    from types import MethodType

    fake_celery_module = ModuleType("celery")
    fake_celery_module.Celery = object
    monkeypatch.setitem(sys.modules, "celery", fake_celery_module)
    import backend.apps.ai.skills.ask_skill as ask_skill_module
    from backend.apps.ai.skills.ask_skill import AskSkill, AskSkillResponse, OpenAICompletionRequest
    from backend.apps.ai.utils.preprocessing_history import STANDARDIZED_USER_ERROR_MESSAGE

    app_fence = (
        '```json\n{"type":"app_skill_use","embed_id":"result-1",'
        '"app_id":"web","skill_id":"search"}\n```\n\n'
    )
    snapshots = [
        app_fence,
        app_fence + "This draft answer is longer and will be replaced.",
        app_fence + "Corrected",
        app_fence + "Corrected [source](embed:source-ref).\n\n" + STANDARDIZED_USER_ERROR_MESSAGE,
    ]
    task_id = "redis-prefix-rewrite-task"
    resolved_embed = {
        "embed_id": "result-1",
        "type": "app_skill_use",
        "content": "app_id: web\nskill_id: search\nstatus: finished",
        "status": "finished",
    }
    notifications: list[tuple[str, str, str]] = []

    async def fake_notify(request_identity: str, *, stage: str, category: str) -> None:
        notifications.append((request_identity, stage, category))

    class FakeRedisStreamCache:
        async def get_user_vault_key_id(self, _user_id: str) -> None:
            return None

        async def subscribe_to_channel(self, _channel: str):
            for index, snapshot in enumerate(snapshots):
                yield {
                    "data": {
                        "task_id": task_id,
                        "full_content_so_far": snapshot,
                        "is_final_chunk": index == len(snapshots) - 1,
                        "error": index == len(snapshots) - 1,
                        "failure_reason": failure_reason if index == len(snapshots) - 1 else None,
                        "model_name": "google/gemini-test",
                        "anonymous_embeds": [resolved_embed] if index == len(snapshots) - 1 else None,
                    }
                }

    fake_cache_module = ModuleType("backend.core.api.app.services.cache")
    fake_cache_module.CacheService = FakeRedisStreamCache
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", fake_cache_module)
    monkeypatch.setattr(ask_skill_module, "notify_chat_failure", fake_notify)
    monkeypatch.setattr(anonymous_routes, "notify_chat_failure", fake_notify)

    skill = object.__new__(AskSkill)

    async def fake_handle_internal(_self: AskSkill, _request: Any) -> AskSkillResponse:
        return AskSkillResponse(task_id=task_id)

    async def no_embeds(_self: AskSkill, _content: str, _chat_id: str, _vault_key: str | None = None) -> list[dict]:
        return []

    skill._handle_internal_request = MethodType(fake_handle_internal, skill)
    skill._extract_and_resolve_embeds = MethodType(no_embeds, skill)

    openai_frames: list[str] = []

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> StreamingResponse:
            assert (app_id, skill_id) == ("ai", "ask")
            assert request_body["_chat_id"] == "anonymous-chat-1"
            assert request_body["_message_id"] == "message-1"
            openai_request = OpenAICompletionRequest.model_validate(request_body)
            internal_request = await skill._transform_openai_to_internal(openai_request)

            async def recorded_openai_stream():
                async for frame in skill._stream_openai_response(internal_request, openai_request):
                    openai_frames.append(frame)
                    yield frame

            return StreamingResponse(recorded_openai_stream(), media_type="text/event-stream")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(
        AnonymousFreeUsageService,
        "open_request",
        lambda self, **kwargs: asyncio.sleep(0, result=AnonymousReservationResult(accepted=True, request_id=kwargs["request_id"])),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="anonymous-chat-1",
        client_message_id="message-1",
        plaintext_message="Search and summarize",
    )

    response = await anonymous_chat_stream(
        request=request,
        payload=payload,
        directus_service=FakeDirectus(),
        cache_service=FakeCache(),
    )
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    final_chunk = next(event for event in events if event["type"] == "ai_message_chunk" and event["is_final_chunk"])
    expected_content = (
        app_fence + "Corrected [source](embed:source-ref).\n\nCreate an account to keep using OpenMates."
        if failure_reason else snapshots[-1]
    )
    assert final_chunk["full_content_so_far"] == expected_content
    assert final_chunk["rejection_reason"] == (failure_reason or "anonymous_inference_failed")
    assert [event["status"] for event in events if event["type"] == "ai_task_ended"] == ["failed"]
    assert not any(event["type"] == "post_processing_completed" for event in events)
    assert [event["payload"]["embed_id"] for event in events if event["type"] == "send_embed_data"] == ["result-1"]
    assert notifications == [("anonymous-chat-1:message-1", "inference", "processing_error")]

    openai_payloads = [
        json.loads(frame.removeprefix("data: ").strip())
        for frame in openai_frames
        if frame.startswith("data: {")
    ]
    assert openai_payloads[-1]["full_content"] == snapshots[-1]
    assert openai_payloads[-1].get("failure_reason") == failure_reason
    assert openai_payloads[-1]["choices"][0]["delta"] == {}
    assert openai_payloads[-1]["choices"][0]["finish_reason"] == "error"
    emitted_deltas = [
        choice.get("delta", {}).get("content")
        for frame in openai_payloads
        for choice in frame.get("choices", [])
        if choice.get("delta", {}).get("content")
    ]
    assert snapshots[2] not in emitted_deltas
    assert snapshots[-1] not in emitted_deltas


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.streaming.ordered-final
async def test_openai_stream_missing_terminal_frame_notifies_once_and_returns_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import MethodType

    fake_celery_module = ModuleType("celery")
    fake_celery_module.Celery = object
    monkeypatch.setitem(sys.modules, "celery", fake_celery_module)
    import backend.apps.ai.skills.ask_skill as ask_skill_module
    from backend.apps.ai.skills.ask_skill import AskSkill, AskSkillResponse, OpenAICompletionRequest

    task_id = "delivery-failure-task"
    notifications: list[tuple[str, str, str]] = []

    async def fake_notify(request_identity: str, *, stage: str, category: str) -> None:
        notifications.append((request_identity, stage, category))

    class MissingTerminalRedisStreamCache:
        async def get_user_vault_key_id(self, _user_id: str) -> None:
            return None

        async def subscribe_to_channel(self, _channel: str):
            yield {
                "data": {
                    "task_id": task_id,
                    "full_content_so_far": "partial answer",
                    "is_final_chunk": False,
                    "error": False,
                }
            }
            await asyncio.Event().wait()

    fake_cache_module = ModuleType("backend.core.api.app.services.cache")
    fake_cache_module.CacheService = MissingTerminalRedisStreamCache
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache", fake_cache_module)
    monkeypatch.setattr(ask_skill_module, "notify_chat_failure", fake_notify)
    monkeypatch.setattr(ask_skill_module, "OPENAI_STREAM_COMPLETION_TIMEOUT_SECONDS", 0.01)

    skill = object.__new__(AskSkill)

    async def fake_handle_internal(_self: AskSkill, _request: Any) -> AskSkillResponse:
        return AskSkillResponse(task_id=task_id)

    skill._handle_internal_request = MethodType(fake_handle_internal, skill)
    internal_request = SimpleNamespace(chat_id="anonymous-chat-1", message_id="message-1", user_id="anonymous")
    openai_request = OpenAICompletionRequest(messages=[{"role": "user", "content": "hello"}], stream=True)

    frames = [frame async for frame in skill._stream_openai_response(internal_request, openai_request)]
    payloads = [json.loads(frame.removeprefix("data: ").strip()) for frame in frames if frame.startswith("data: {")]

    failure_identity = "anonymous-chat-1:message-1"
    assert notifications == [(failure_identity, "streaming", "delivery_error")]
    assert payloads[-1]["choices"][0]["finish_reason"] == "error"
    assert payloads[-1]["choices"][0]["delta"]["content"] == "Error: AI stream timed out before receiving a terminal frame"
    assert frames[-1] == "data: [DONE]\n\n"

    class FakeRegistry:
        async def dispatch_skill(self, _app_id: str, _skill_id: str, _request_body: dict) -> StreamingResponse:
            async def replay_error_stream():
                for frame in frames:
                    yield frame

            return StreamingResponse(replay_error_stream(), media_type="text/event-stream")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)
    monkeypatch.setattr(anonymous_routes, "notify_chat_failure", fake_notify)
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(
        AnonymousFreeUsageService,
        "open_request",
        lambda self, **kwargs: asyncio.sleep(0, result=AnonymousReservationResult(accepted=True, request_id=kwargs["request_id"])),
    )
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    response = await anonymous_chat_stream(
        request=request,
        payload=AnonymousChatStreamRequest(
            anonymous_id="anon-1",
            client_chat_id="anonymous-chat-1",
            client_message_id="message-1",
            plaintext_message="hello",
        ),
        directus_service=FakeDirectus(),
        cache_service=FakeCache(),
    )
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    final = next(event for event in events if event.get("is_final_chunk"))
    assert final["full_content_so_far"] == anonymous_routes.ANONYMOUS_INFERENCE_ERROR_MESSAGE
    assert final["rejection_reason"] == "anonymous_inference_failed"
    assert [event["status"] for event in events if event["type"] == "ai_task_ended"] == ["failed"]
    assert notifications == [(failure_identity, "streaming", "delivery_error")]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_sse_does_not_double_finalize_worker_usage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        raise ValueError("reservation not found")

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["stream"] is True
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous inference ok"}}],
                "usage": {"total_credits": 7},
            }

    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )
    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", failing_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous inference ok",
    )

    with caplog.at_level("ERROR"):
        response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())
        body = ""
        async for chunk in response.body_iterator:
            body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in events] == [
        "ai_task_initiated",
        "ai_typing_started",
        "ai_message_chunk",
        "ai_task_ended",
        "post_processing_completed",
    ]
    assert events[2]["full_content_so_far"] == "anonymous inference ok"
    assert events[3]["status"] == "completed"
    assert "reservation not found" not in body
    assert "Anonymous free usage reservation finalization failed" not in caplog.text


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
@pytest.mark.parametrize("transport", ["stream", "sse_dict", "json"])
@pytest.mark.parametrize("answer", [
    None,
    "",
    "   ",
    '```json\n{"type":"app_skill_use","embed_id":"result-1","app_id":"web","skill_id":"search"}\n```\n\n'
    '```json\n{"type":"app_skill_use","embed_id":"result-2","app_id":"web","skill_id":"search"}\n```\n',
])
async def test_anonymous_sse_sanitizes_internal_inference_errors(
    monkeypatch: pytest.MonkeyPatch, transport: str, answer: str | None,
) -> None:
    notifications: list[tuple[str, str, str]] = []

    async def fake_notify(request_identity: str, *, stage: str, category: str) -> None:
        notifications.append((request_identity, stage, category))

    async def accepted_open_request(
        self: AnonymousFreeUsageService,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
    ) -> AnonymousReservationResult:
        return AnonymousReservationResult(accepted=True, request_id=request_id)

    class FailingRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict | StreamingResponse:
            if answer is None:
                raise RuntimeError("private provider diagnostic")
            if transport == "stream":
                async def completed_embed_only_stream():
                    yield "data: " + json.dumps({"choices": [{"delta": {"content": answer}}]}) + "\n\n"
                    yield 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                    yield 'data: [DONE]\n\n'
                return StreamingResponse(completed_embed_only_stream(), media_type="text/event-stream")
            return {"choices": [{"message": {"content": answer}}]}

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FailingRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(anonymous_routes, "notify_chat_failure", fake_notify)
    monkeypatch.setattr(AnonymousFreeUsageService, "open_request", accepted_open_request)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"application/json" if transport == "json" else b"text/event-stream")],
        "client": ("198.51.100.8", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="hello",
    )

    if transport == "json":
        with pytest.raises(HTTPException) as exc_info:
            await anonymous_chat_stream(request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache())
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail["code"] == "anonymous_inference_failed"
        assert len(notifications) == 1
        assert notifications[0][0] == "chat-1:message-1"
        assert notifications[0][1:] == ("streaming", "delivery_error")
        return

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache())
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    assert "private provider diagnostic" not in body
    assert "Anonymous inference failed. Please try again." in body

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    finals = [event for event in events if event.get("is_final_chunk")]
    assert len(finals) == 1
    assert finals[0]["rejection_reason"] == "anonymous_inference_failed"
    assert [event["status"] for event in events if event["type"] == "ai_task_ended"] == ["failed"]
    assert not any(event["type"] == "post_processing_completed" for event in events)
    assert len(notifications) == 1
    assert notifications[0][0] == "chat-1:message-1"
    assert notifications[0][1:] == ("streaming", "delivery_error")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_sse_emits_initial_lifecycle_before_budget_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    reserve_started = asyncio.Event()
    release_reservation = asyncio.Event()

    async def delayed_open_request(
        self: AnonymousFreeUsageService,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
    ) -> AnonymousReservationResult:
        reserve_started.set()
        await release_reservation.wait()
        return AnonymousReservationResult(accepted=True, request_id=request_id)

    async def noop_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        return None

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["anonymous_reservation_id"]
            return {
                "model": "test-model",
                "choices": [{"message": {"content": "after reservation"}}],
                "usage": {"total_credits": 3},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "open_request", delayed_open_request)
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", noop_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply after delayed reservation",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache())
    iterator = response.body_iterator
    first = await asyncio.wait_for(iterator.__anext__(), timeout=0.5)
    second = await asyncio.wait_for(iterator.__anext__(), timeout=0.5)

    assert json.loads(str(first).removeprefix("data: "))["type"] == "ai_task_initiated"
    typing_event = json.loads(str(second).removeprefix("data: "))
    assert typing_event["type"] == "ai_typing_started"
    assert typing_event["title"] == "Reply after delayed reservation"

    third_chunk_task = asyncio.create_task(iterator.__anext__())
    await asyncio.wait_for(reserve_started.wait(), timeout=0.5)
    await asyncio.sleep(0)
    assert third_chunk_task.done() is False

    release_reservation.set()
    third = await asyncio.wait_for(third_chunk_task, timeout=0.5)
    assert json.loads(str(third).removeprefix("data: "))["type"] == "ai_message_chunk"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_chat_keeps_json_response_for_native_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert app_id == "ai"
            assert skill_id == "ask"
            assert request_body["stream"] is False
            assert request_body["is_anonymous"] is True
            assert request_body["apps_enabled"] is True
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous json ok"}}],
                "usage": {"total_credits": 5},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous json ok",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())

    assert response.status == "completed"
    assert response.assistant == "anonymous json ok"
    assert response.creditsCharged == 5


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_json_does_not_double_finalize_worker_usage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        raise ValueError("reservation not found")

    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["stream"] is False
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous json ok"}}],
                "usage": {"total_credits": 5},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", failing_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous json ok",
    )

    with caplog.at_level("ERROR"):
        response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())

    assert response.status == "completed"
    assert response.assistant == "anonymous json ok"
    assert response.creditsCharged == 5
    assert "Anonymous free usage reservation finalization failed" not in caplog.text
