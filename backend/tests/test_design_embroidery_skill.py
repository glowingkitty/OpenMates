# backend/tests/test_design_embroidery_skill.py
#
# Contract tests for the design.embroidery skill surface: request validation,
# source resolution before dispatch, queue routing, billing sums, result
# filenames, vector source classification and the failed-child media graph.

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from backend.apps.design.embroidery import billing
from backend.apps.design.embroidery.request import parse_embroidery_request
from backend.apps.design.embroidery.storage import RESULT_VARIANTS, result_title, variant_filename
from backend.apps.design.skills import embroidery_skill
from backend.apps.design.skills.embroidery_skill import EmbroiderySkill
from backend.apps.images.vector_author import VectorUsage
from backend.shared.python_utils.encrypted_embed_vectors import classify_vector_content
from backend.shared.python_utils.generated_media_graph import (
    MEDIA_CHILD_TYPES,
    PER_CHILD_TIMEOUT_SECONDS,
    run_generated_media_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill(producer: Any = object()) -> EmbroiderySkill:
    return EmbroiderySkill(
        app=None, app_id="design", skill_id="embroidery", skill_name="Embroidery",
        skill_description="Embroidery machine files", celery_producer=producer,
    )


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source
def test_request_defaults_and_bounds() -> None:
    assert parse_embroidery_request() == parse_embroidery_request(width_mm=100, hoop="none", fabric="normal")
    assert parse_embroidery_request(width_mm=20).width_mm == 20.0
    assert parse_embroidery_request(width_mm="400").width_mm == 400.0
    for bad in ({"width_mm": 19.9}, {"width_mm": 401}, {"width_mm": True}, {"width_mm": "wide"},
                {"hoop": "90x90"}, {"fabric": "leather"}, {"instructions": "x" * 501}):
        with pytest.raises(ValueError):
            parse_embroidery_request(**bad)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_is_optional_bounded_and_black_by_default() -> None:
    assert parse_embroidery_request().border_mm is None
    request = parse_embroidery_request(border_mm=3)
    assert request.border_mm == 3.0 and request.border_colour == "#000000"
    assert parse_embroidery_request(border_mm="8", border_colour="#E8451F").border_colour == "#e8451f"
    for bad in ({"border_mm": 0.5}, {"border_mm": 9}, {"border_mm": True}, {"border_mm": "thick"},
                {"border_mm": 3, "border_colour": "black"}, {"border_mm": 3, "border_colour": "#12345"}):
        with pytest.raises(ValueError):
            parse_embroidery_request(**bad)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.fill-the-hoop
def test_fit_hoop_is_off_by_default_and_needs_a_hoop() -> None:
    assert parse_embroidery_request().fit_hoop is False
    assert parse_embroidery_request(hoop="200x300", fit_hoop=True, border_mm=3).fit_hoop is True
    assert parse_embroidery_request(hoop="200x300", fit_hoop=False).fit_hoop is False
    with pytest.raises(ValueError, match="fit_hoop needs a hoop"):
        parse_embroidery_request(fit_hoop=True)
    with pytest.raises(ValueError, match="fit_hoop must be true or false"):
        parse_embroidery_request(hoop="200x300", fit_hoop="yes")


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
@pytest.mark.asyncio
async def test_skill_dispatches_the_border_only_when_requested(monkeypatch) -> None:
    dispatched: list[dict] = []

    async def dispatch(**kwargs: Any) -> str:
        dispatched.append(kwargs)
        return "task-1"

    monkeypatch.setattr(embroidery_skill, "execute_skill_via_celery", dispatch)
    index = {"fox-logo.svg": "source-embed-1"}
    await _skill().execute(source="fox-logo.svg", border_mm=3, file_path_index=index)
    await _skill().execute(source="fox-logo.svg", file_path_index=index)
    with_border, without = (call["arguments"] for call in dispatched)
    assert with_border["border_mm"] == 3.0 and with_border["border_colour"] == "#000000"
    assert with_border["requests"][0]["border_mm"] == 3.0
    assert "border_mm" not in without and "border_colour" not in without
    bad = await _skill().execute(source="fox-logo.svg", border_mm=12, file_path_index=index)
    assert "border_mm" in bad["error"] and len(dispatched) == 2


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_skill_resolves_source_and_dispatches_one_registered_request(monkeypatch) -> None:
    dispatched: list[dict] = []

    async def dispatch(**kwargs: Any) -> str:
        dispatched.append(kwargs)
        return "task-1"

    monkeypatch.setattr(embroidery_skill, "execute_skill_via_celery", dispatch)
    result = await _skill().execute(
        source="fox-logo.svg", width_mm=90, hoop="130x180", instructions="  thick   outline ",
        file_path_index={"fox-logo.svg": "source-embed-1"}, placeholder_embed_ids=["parent-1"],
        user_id="user-1", user_vault_key_id="vault-1",
    )

    assert result == {"task_id": "task-1", "embed_id": "parent-1", "status": "processing"}
    arguments = dispatched[0]["arguments"]
    assert dispatched[0]["app_id"] == "design" and dispatched[0]["skill_id"] == "embroidery"
    assert arguments["source_embed_id"] == "source-embed-1" and arguments["width_mm"] == 90.0
    assert arguments["instructions"] == "thick outline" and arguments["fabric"] == "normal"
    assert len(arguments["requests"]) == 1 and "requests" not in arguments["requests"][0]
    assert "svg" not in str(arguments).lower().replace("fox-logo.svg", "")


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source,design-embroidery.billing.metered
@pytest.mark.asyncio
async def test_unknown_source_or_bad_settings_fail_before_dispatch(monkeypatch) -> None:
    async def unexpected(**_kwargs: Any) -> str:
        raise AssertionError("an invalid request must not start a conversion")

    monkeypatch.setattr(embroidery_skill, "execute_skill_via_celery", unexpected)
    unknown = await _skill().execute(source="dog.jpg", file_path_index={})
    assert unknown["error_code"] == "invalid_source"
    assert "images.vectorize" in unknown["error"] and "images.generate" in unknown["error"]
    assert (await _skill().execute(source="", file_path_index={}))["error_code"] == "invalid_source"
    assert "width_mm" in (await _skill().execute(source="a.svg", width_mm=1000, file_path_index={"a.svg": "e"}))["error"]


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source
def test_only_generated_svg_and_svg_code_embeds_are_vector_sources() -> None:
    generated = {"files": {"original": {"s3_key": "u/a.svg", "format": "svg"}, "preview": {"s3_key": "u/a.webp"}}}
    assert classify_vector_content(generated)[0] == "generated_svg"
    assert classify_vector_content({"code": '<svg viewBox="0 0 1 1"/>', "language": "svg"})[0] == "svg_code"
    assert classify_vector_content({"files": {"original": {"s3_key": "u/dog.jpg", "format": "jpg"}}}) is None
    assert classify_vector_content({"files": {"preview": {"s3_key": "u/dog.webp", "format": "webp"}}}) is None
    assert classify_vector_content({"code": "print('hi')"}) is None


# contract-test: direct surface=rest_api assertions=design-embroidery.billing.metered
@pytest.mark.asyncio
@pytest.mark.parametrize(("seconds", "credits"), [(21.0, 4), (60.0, 4), (61.0, 8), (179.0, 12)])
async def test_sandbox_time_is_charged_per_started_minute(seconds: float, credits: int) -> None:
    async def no_pricing(_model: str) -> None:
        raise AssertionError("no rework means no pricing lookup")

    total, details = await billing.embroidery_credits(sandbox_seconds=seconds, usage=[], pricing_for=no_pricing)

    assert total == credits
    assert details["provider_calls"][-1]["model_used"] == "e2b/sandbox"


# contract-test: direct surface=rest_api assertions=design-embroidery.billing.metered
@pytest.mark.asyncio
async def test_rework_tokens_are_added_and_unpriced_calls_are_never_free() -> None:
    async def pricing(_model: str) -> dict:
        return {"pricing": {"tokens": {"input": {"per_credit_unit": 1000}, "output": {"per_credit_unit": 100}}}}

    usage = [VectorUsage("drawing", "openai/gpt-6.1-sol", 4500, 2550)]
    total, details = await billing.embroidery_credits(sandbox_seconds=48.0, usage=usage, pricing_for=pricing)
    assert total == 4 + 30  # 4.5 + 25.5 token credits floored once
    assert details["input_tokens"] == 4500 and details["output_tokens"] == 2550

    async def unpriced(_model: str) -> None:
        return None

    with pytest.raises(RuntimeError):
        await billing.embroidery_credits(sandbox_seconds=10.0, usage=usage, pricing_for=unpriced)
    with pytest.raises(RuntimeError):
        await billing.embroidery_credits(
            sandbox_seconds=10.0, usage=[VectorUsage("drawing", "m/x", 0, 0)], pricing_for=pricing,
        )


# contract-test: direct surface=rest_api assertions=design-embroidery.result.view-and-download
def test_every_variant_gets_a_filename_with_its_extension() -> None:
    title = result_title("Fröhlicher Fuchs — Logo.svg")
    names = {variant: variant_filename(title, variant) for variant in RESULT_VARIANTS}
    assert names["dst"] == "frohlicher-fuchs-logo.dst"
    assert [names[name].rsplit(".", 1)[1] for name in ("dst", "pes", "exp", "jef", "vp3")] == [
        "dst", "pes", "exp", "jef", "vp3"]
    assert names["preview"].endswith(".webp") and names["prepared_svg"].endswith(".svg")
    assert names["stitches"].endswith(".json")
    assert result_title("") == "Embroidery design"


# contract-test: direct surface=rest_api assertions=design-embroidery.surface.semantic-parity
def test_app_registration_routes_to_shared_media_worker() -> None:
    from backend.apps.ai.processing.celery_helpers import SHARED_APP_QUEUES
    from backend.apps.ai.processing.main_processor import ASYNC_SKILLS

    assert SHARED_APP_QUEUES["design"] == "app_images"
    assert ("design", "embroidery") in ASYNC_SKILLS
    assert MEDIA_CHILD_TYPES["design"] == "embroidery_design"
    assert PER_CHILD_TIMEOUT_SECONDS[("design", "embroidery")] < 420
    config = yaml.safe_load((REPO_ROOT / "backend/apps/design/app.yml").read_text(encoding="utf-8"))
    skill = next(item for item in config["skills"] if item["id"] == "embroidery")
    assert skill["api_config"] == {"expose_get": False, "expose_post": False}
    assert skill["pricing"] == {"per_minute": 4}
    assert skill["tool_schema"]["required"] == ["source"]
    parent = next(item for item in config["embed_types"] if item["id"] == "embroidery")
    assert parent["child_type"] == "embroidery_design" and parent["child_frontend_type"] == "design-embroidery"


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_celery_task_is_registered_on_the_images_worker() -> None:
    pytest.importorskip("celery")
    from backend.core.api.app.tasks import celery_config

    assert "backend.apps.design.tasks" in celery_config._task_modules_for_worker_queues("app_images")
    from backend.apps.design.tasks.embroidery_task import TASK_NAME, embroidery_task

    assert TASK_NAME == "apps.design.tasks.skill_embroidery"
    assert embroidery_task.name == TASK_NAME and embroidery_task.queue == "app_images"
    assert embroidery_task.soft_time_limit == 1500 and embroidery_task.time_limit == 1560


# contract-test: direct surface=gui.web assertions=design-embroidery.result.view-and-download,design-embroidery.convert.sandbox-inkstitch
@pytest.mark.asyncio
async def test_failed_child_is_sealed_under_parent_and_reported_with_its_reason(monkeypatch) -> None:
    parent_id = str(uuid.uuid4())
    sent: list[dict] = []
    callback = AsyncMock()

    class FakeEmbedService:
        def __init__(self, *_args: Any) -> None:
            pass

        @staticmethod
        def _registered_child_embed_id(embed_id: str, index: int) -> str:
            return str(uuid.uuid5(uuid.UUID(embed_id), f"embed-child:{index}"))

        async def send_embed_data_to_client(self, **kwargs: Any) -> bool:
            sent.append(kwargs)
            return True

    embed_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_module.EmbedService = FakeEmbedService
    monkeypatch.setitem(sys.modules, embed_module.__name__, embed_module)
    continuation = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation.dispatch_async_skill_continuation = callback
    monkeypatch.setitem(sys.modules, continuation.__name__, continuation)

    class FakeTask:
        request = SimpleNamespace(id=str(uuid.uuid4()))
        _cache_service = _directus_service = _encryption_service = object()

        async def initialize_core_services(self) -> None:
            return None

        async def cleanup_services(self) -> None:
            return None

    async def generate_one(_task: Any, _app: str, _skill: str, child_args: dict) -> dict:
        return {"embed_id": child_args["embed_id"], "status": "failed", "child_published": True,
                "error": "The design has too many stitches; try a smaller width.", "error_code": "too_many_stitches"}

    result = await run_generated_media_batch(
        FakeTask(), app_id="design", skill_id="embroidery",
        arguments={"embed_id": parent_id, "user_id": "user-1", "chat_id": "chat-1", "message_id": "message-1",
                   "requests": [{"source_embed_id": "source-1"}]},
        generate_one=generate_one,
    )

    child_id = FakeEmbedService._registered_child_embed_id(parent_id, 0)
    parent = sent[-1]
    assert parent["embed_ids"] == [child_id]
    assert parent["producer_final_children"] == [{"subject_id": child_id, "output_kind": "embed", "output_version": 1}]
    assert result["status"] == "error" and result["child_embed_ids"] == []
    rows = callback.await_args.kwargs["completed_results"]
    assert rows == [{
        "parent_embed_id": parent_id,
        "request_index": 0, "status": "error",
        "error": "The design has too many stitches; try a smaller width.", "error_code": "too_many_stitches",
    }]
    assert callback.await_args.kwargs["result_status"] == "failed"
    assert hashlib.sha256(b"user-1").hexdigest() == parent["user_id_hash"]


# contract-test: supporting surface=rest_api assertions=design-embroidery.result.complete-and-truthful
def test_slug_and_filename_labels_become_readable_titles() -> None:
    title = result_title("simple-flat-three-colour-logo-of-a-fox-head-clean-geometric")
    assert title == "Simple flat three colour logo of a fox head"
    assert len(title) <= 48 and not title.endswith("…")
    assert result_title("fox_head-logo.svg") == "Fox head logo"
    assert variant_filename(title, "dst") == "simple-flat-three-colour-logo-of-a-fox-head.dst"


# contract-test: supporting surface=rest_api assertions=design-embroidery.result.complete-and-truthful
def test_natural_labels_are_kept_and_capped_at_a_word_boundary() -> None:
    assert result_title("Fröhlicher Fuchs") == "Fröhlicher Fuchs"
    long = result_title("A very friendly red fox sitting on a hill at sunrise with mist")
    assert len(long) <= 48 and long == "A very friendly red fox sitting on a hill at"


# contract-test: supporting surface=rest_api assertions=design-embroidery.result.complete-and-truthful
def test_embed_label_is_derived_readable_from_the_source() -> None:
    from backend.shared.python_utils.encrypted_embed_vectors import _label_from_content

    assert _label_from_content({"title": "fox-head_logo.svg"}) == "Fox head logo"
