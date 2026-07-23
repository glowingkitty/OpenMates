# backend/tests/test_code_image_to_html_task.py
#
# Worker-level tests for code.image_to_html. Provider calls, billing, and embed
# delivery are injected or skipped so the test remains deterministic while still
# proving the Celery task orchestration contract.

from __future__ import annotations

import base64
import importlib
import types

import pytest

from backend.shared.providers.image_to_html_generator import ImageToHtmlProviderResult


task_module = importlib.import_module("backend.apps.code.tasks.image_to_html_task")


PNG_1X1 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


class FakeTask:
    request = types.SimpleNamespace(id="task-image-html-1")
    _secrets_manager = object()
    _cache_service = object()
    _directus_service = object()
    _encryption_service = object()
    _s3_service = object()

    def __init__(self) -> None:
        self.initialized = False
        self.cleaned = False

    async def initialize_services(self) -> None:
        self.initialized = True

    async def cleanup_services(self) -> None:
        self.cleaned = True


class FakeGenerator:
    async def generate(self, **kwargs):
        assert kwargs["image_bytes"].startswith(b"\x89PNG")
        assert kwargs["mime_type"] == "image/png"
        assert kwargs["max_correction_passes"] == 2
        return ImageToHtmlProviderResult(
            html="<!doctype html><html><body>Hello</body></html>",
            screenshot_bytes=None,
            correction_passes_used=1,
            validation_warnings=["Repaired inline-only validation errors"],
            usage={"model": "fake-gemini", "input_tokens": 1000, "output_tokens": 500, "e2b_render_seconds": 61.0},
        )


@pytest.mark.asyncio
async def test_image_to_html_worker_generates_charges_and_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    prechecks: list[dict[str, object]] = []
    charges: list[dict[str, object]] = []

    async def fake_ensure_credit_headroom(**kwargs):
        prechecks.append(kwargs)

    async def fake_charge_func(**kwargs):
        charges.append(kwargs)
        return kwargs["credits"]

    monkeypatch.setattr(task_module, "ensure_credit_headroom", fake_ensure_credit_headroom)
    task = FakeTask()

    result = await task_module._async_image_to_html(
        task,
        "code",
        "image_to_html",
        {
            "image_base64": PNG_1X1,
            "mime_type": "image/png",
            "max_correction_passes": 2,
            "reserved_credits": 1500,
            "user_id": "user-1",
            "embed_id": "embed-1",
        },
        generator_factory=lambda _task: FakeGenerator(),
        charge_func=fake_charge_func,
    )

    assert task.initialized is True
    assert task.cleaned is True
    assert prechecks[0]["estimated_credits"] == 1500
    assert charges[0]["credits"] == result["usage"]["credits_charged"]
    assert charges[0]["usage_details"]["image_to_html_e2b_credits"] == 10
    assert charges[0]["usage_details"]["model_used"] == "fake-gemini"
    assert charges[0]["usage_details"]["input_tokens"] == 1000
    assert charges[0]["usage_details"]["output_tokens"] == 500
    assert charges[0]["usage_details"]["duration_second"] == 61.0
    assert result["status"] == "finished"
    assert result["embed_id"] == "embed-1"
    assert result["user_id_hash"]
    assert result["html"].startswith("<!doctype html>")
    assert result["usage"]["credits_refunded"] >= 0


@pytest.mark.asyncio
async def test_image_to_html_worker_resolves_uploaded_source_image(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ensure_credit_headroom(**kwargs):
        return None

    async def fake_charge_func(**kwargs):
        return kwargs["credits"]

    async def fake_resolve_encrypted_image_embed(**kwargs):
        assert kwargs["embed_id"] == "source-embed-1"
        assert kwargs["user_vault_key_id"] == "vault-1"
        return types.SimpleNamespace(
            content=base64.b64decode(PNG_1X1),
            mime_type="image/png",
        )

    monkeypatch.setattr(task_module, "ensure_credit_headroom", fake_ensure_credit_headroom)
    monkeypatch.setattr(task_module, "resolve_encrypted_image_embed", fake_resolve_encrypted_image_embed)

    result = await task_module._async_image_to_html(
        FakeTask(),
        "code",
        "image_to_html",
        {
            "source_image_embed_id": "source-embed-1",
            "filename": "mockup.png",
            "max_correction_passes": 2,
            "reserved_credits": 1500,
            "user_id": "user-1",
            "user_vault_key_id": "vault-1",
            "embed_id": "embed-1",
        },
        generator_factory=lambda _task: FakeGenerator(),
        charge_func=fake_charge_func,
    )

    assert result["status"] == "finished"
    assert result["html"].startswith("<!doctype html>")
