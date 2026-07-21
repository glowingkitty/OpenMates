# backend/tests/test_code_image_to_html_skill.py
#
# Focused tests for the Code image-to-HTML skill request contract. These tests
# avoid external Gemini/E2B calls by asserting Celery dispatch payloads only.

from __future__ import annotations

import base64

import pytest

from backend.apps.code.skills.image_to_html_skill import (
    DEFAULT_MAX_CORRECTION_PASSES,
    MAX_CORRECTION_PASSES,
    ImageToHtmlSkill,
    validate_image_input,
)


PNG_1X1 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


def test_validate_image_input_rejects_image_url() -> None:
    with pytest.raises(ValueError, match="image_url"):
        validate_image_input({"image_url": "https://example.com/mockup.png"})


def test_validate_image_input_accepts_base64_png_and_defaults_correction_passes() -> None:
    parsed = validate_image_input({"image_base64": PNG_1X1, "mime_type": "image/png"})

    assert parsed.image_bytes.startswith(b"\x89PNG")
    assert parsed.mime_type == "image/png"
    assert parsed.max_correction_passes == DEFAULT_MAX_CORRECTION_PASSES


def test_validate_image_input_rejects_out_of_range_correction_passes() -> None:
    with pytest.raises(ValueError, match="max_correction_passes"):
        validate_image_input({"image_base64": PNG_1X1, "mime_type": "image/png", "max_correction_passes": MAX_CORRECTION_PASSES + 1})


@pytest.mark.asyncio
async def test_skill_dispatches_image_to_html_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: dict[str, object] = {}

    async def fake_execute_skill_via_celery(**kwargs):
        dispatched.update(kwargs)
        return "task-123"

    from backend.apps.code.skills import image_to_html_skill as skill_module

    monkeypatch.setattr(skill_module, "execute_skill_via_celery", fake_execute_skill_via_celery)
    skill = ImageToHtmlSkill(
        app=None,
        app_id="code",
        skill_id="image_to_html",
        skill_name="Image to HTML",
        skill_description="Generate HTML from an image.",
        celery_producer=object(),
    )

    response = await skill.execute(
        requests=[{"image_base64": PNG_1X1, "mime_type": "image/png", "max_correction_passes": 2}],
        user_id="user-1",
        user_vault_key_id="vault-1",
    )

    assert response.task_id == "task-123"
    assert response.embed_id
    assert response.results == [{
        "task_id": "task-123",
        "embed_id": response.embed_id,
        "status": "processing",
        "reserved_credits": 1500,
    }]
    assert dispatched["app_id"] == "code"
    assert dispatched["skill_id"] == "image_to_html"
    assert dispatched["celery_producer"] is skill.celery_producer
    arguments = dispatched["arguments"]
    assert isinstance(arguments, dict)
    assert arguments["image_base64"] == PNG_1X1
    assert arguments["user_id"] == "user-1"
    assert arguments["user_vault_key_id"] == "vault-1"
    assert arguments["reserved_credits"] == 1500


@pytest.mark.asyncio
async def test_chat_bound_skill_reuses_placeholder_embed_id(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatched: dict[str, object] = {}

    async def fake_execute_skill_via_celery(**kwargs):
        dispatched.update(kwargs)
        return "task-chat"

    from backend.apps.code.skills import image_to_html_skill as skill_module

    monkeypatch.setattr(skill_module, "execute_skill_via_celery", fake_execute_skill_via_celery)
    skill = ImageToHtmlSkill(
        app=None,
        app_id="code",
        skill_id="image_to_html",
        skill_name="Image to HTML",
        skill_description="Generate HTML from an image.",
        celery_producer=object(),
    )
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    response = await skill.execute(
        requests=[{"image_base64": PNG_1X1, "mime_type": "image/png", "max_correction_passes": 2}],
        placeholder_embed_ids=["embed-placeholder-1"],
    )

    assert response.task_id == "task-chat"
    assert response.embed_id == "embed-placeholder-1"
    arguments = dispatched["arguments"]
    assert isinstance(arguments, dict)
    assert arguments["embed_id"] == "embed-placeholder-1"
    assert arguments["chat_id"] == "chat-1"
    assert arguments["message_id"] == "message-1"
