# backend/tests/test_models3d_generate_task.py
#
# Contract tests for models3d generation request planning. The planner keeps
# image references out of Celery payloads and makes text/image billing explicit
# before any provider work begins.

import pytest

from backend.apps.models3d.skills import generate_skill
from backend.apps.models3d import billing
from backend.apps.models3d.skills.generate_skill import GenerateSkill, build_generation_plan
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery
from backend.shared.python_utils.image_generation_defaults import (
    ImageGenerationDefault,
    resolve_images_generate_default,
)
from backend.apps.models3d.storage import (
    build_master_variant_metadata,
    build_poster_variant_metadata,
    build_preview_variant_metadata,
)


REFERENCE_DEFAULT = ImageGenerationDefault(
    model_reference="configured-provider/configured-image-model",
    credits=73,
)


@pytest.mark.asyncio
async def test_models3d_dispatches_to_shared_media_worker_queue() -> None:
    sent: dict[str, object] = {}

    class FakeProducer:
        def send_task(self, **kwargs):
            sent.update(kwargs)
            return type("Task", (), {"id": "task-model-1"})()

    task_id = await execute_skill_via_celery(
        app_id="models3d",
        skill_id="generate",
        arguments={"embed_id": "embed-model"},
        celery_producer=FakeProducer(),
    )

    assert task_id == "task-model-1"
    assert sent["name"] == "apps.models3d.tasks.skill_generate"
    assert sent["queue"] == "app_images"


def test_images_generate_default_is_resolved_from_canonical_metadata() -> None:
    default = resolve_images_generate_default()

    assert default.model_reference == "google/gemini-3-pro-image-preview"
    assert default.credits == 200


def test_text_generation_requires_reference_stage_and_combined_estimate() -> None:
    plan = build_generation_plan(
        prompt="a small orange retro desk lamp",
        image_embed_refs=[],
        image_views=[],
        file_path_index={},
        reference_image_default=REFERENCE_DEFAULT,
        model_credits=25,
    )

    assert plan.input_mode == "text"
    assert plan.requires_reference_image is True
    assert plan.reference_embed_ids == ()
    assert plan.reference_image_model == "configured-provider/configured-image-model"
    assert plan.estimated_credits == 98


@pytest.mark.asyncio
async def test_text_generation_is_rejected_before_celery_dispatch(monkeypatch) -> None:
    async def unexpected_dispatch(**_kwargs):
        raise AssertionError("text generation must not enqueue an unsupported worker task")

    monkeypatch.setattr(generate_skill, "execute_skill_via_celery", unexpected_dispatch)
    skill = GenerateSkill(
        app=None,
        app_id="models3d",
        skill_id="generate",
        skill_name="Generate",
        skill_description="Generate 3D models",
        celery_producer=object(),
    )

    result = await skill.execute(prompt="a small orange retro desk lamp")

    assert result == {
        "error": "Text-to-3D is not available until reference image artifact retention is implemented"
    }


def test_single_image_skips_reference_stage_and_resolves_embed_id() -> None:
    plan = build_generation_plan(
        prompt=None,
        image_embed_refs=["chair.png"],
        image_views=[],
        file_path_index={"chair.png": "embed-chair"},
        reference_image_default=REFERENCE_DEFAULT,
        model_credits=25,
    )

    assert plan.input_mode == "single_image"
    assert plan.requires_reference_image is False
    assert plan.reference_embed_ids == ("embed-chair",)
    assert plan.estimated_credits == 25


def test_multi_view_resolves_and_orders_canonical_views() -> None:
    plan = build_generation_plan(
        prompt=None,
        image_embed_refs=[],
        image_views=[
            {"embed_ref": "right.png", "view": "right"},
            {"embed_ref": "front.png", "view": "front"},
            {"embed_ref": "back.png", "view": "back"},
        ],
        file_path_index={"front.png": "embed-front", "back.png": "embed-back", "right.png": "embed-right"},
        reference_image_default=REFERENCE_DEFAULT,
        model_credits=25,
    )

    assert plan.input_mode == "multi_view"
    assert plan.ordered_views == (("front", "embed-front"), ("back", "embed-back"), ("right", "embed-right"))
    assert plan.estimated_credits == 25


@pytest.mark.parametrize(
    ("image_embed_refs", "image_views", "message"),
    [
        (["chair.png"], [{"embed_ref": "front.png", "view": "front"}], "exactly one input mode"),
        ([], [{"embed_ref": "front.png", "view": "front"}], "two to four"),
        (
            [],
            [{"embed_ref": "front.png", "view": "front"}, {"embed_ref": "other.png", "view": "front"}],
            "duplicate view",
        ),
    ],
)
def test_invalid_or_ambiguous_inputs_fail_before_dispatch(image_embed_refs, image_views, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_generation_plan(
            prompt=None,
            image_embed_refs=image_embed_refs,
            image_views=image_views,
            file_path_index={"chair.png": "embed-chair", "front.png": "embed-front", "other.png": "embed-other"},
            reference_image_default=REFERENCE_DEFAULT,
            model_credits=25,
        )


def test_malformed_or_oversized_view_inputs_fail_before_copying() -> None:
    with pytest.raises(ValueError, match="two to four"):
        build_generation_plan(
            prompt=None,
            image_embed_refs=[],
            image_views=[{"embed_ref": f"view-{index}.png", "view": "front"} for index in range(5)],
            file_path_index={},
        )


def test_master_variant_uses_chunked_encryption_metadata() -> None:
    metadata = build_master_variant_metadata("users/user-1/models/model.glb.enc", 12_345)

    assert metadata == {
        "s3_key": "users/user-1/models/model.glb.enc",
        "size_bytes": 12_345,
        "format": "glb",
        "mime_type": "model/gltf-binary",
        "encryption": "chunked-aes-256-gcm-v1",
    }


def test_poster_variant_preserves_provider_image_mime_type() -> None:
    metadata = build_poster_variant_metadata("users/user-1/models/poster.webp.enc", 123, "image/webp")

    assert metadata == {
        "s3_key": "users/user-1/models/poster.webp.enc",
        "size_bytes": 123,
        "format": "webp",
        "mime_type": "image/webp",
    }
    with pytest.raises(ValueError, match="poster MIME"):
        build_poster_variant_metadata("users/user-1/models/poster.gif.enc", 123, "image/gif")


def test_preview_variant_records_its_own_encryption_nonce() -> None:
    metadata = build_preview_variant_metadata("users/user-1/models/preview.glb.enc", 456, "nonce-b64")

    assert metadata["aes_nonce"] == "nonce-b64"
    assert metadata["compression"] == {"geometry": "meshopt", "textures": "webp"}
    with pytest.raises(ValueError, match="encryption nonce"):
        build_preview_variant_metadata("users/user-1/models/preview.glb.enc", 456, "")


def test_malformed_view_object_fails_before_dispatch() -> None:
    with pytest.raises(ValueError, match="object"):
        build_generation_plan(
            prompt=None,
            image_embed_refs=[],
            image_views=[{"embed_ref": "front.png", "view": "front"}, "not-a-view"],
            file_path_index={"front.png": "embed-front"},
        )


@pytest.mark.asyncio
async def test_skill_dispatch_marks_external_requests_and_keeps_payload_compact(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_execute_skill_via_celery(**kwargs):
        captured.update(kwargs)
        return "task-model-1"

    monkeypatch.setattr(generate_skill, "execute_skill_via_celery", fake_execute_skill_via_celery)
    skill = GenerateSkill(
        app=None,
        app_id="models3d",
        skill_id="generate",
        skill_name="Generate",
        skill_description="Generate 3D models",
        celery_producer=object(),
    )
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    result = await skill.execute(
        image_embed_refs=["chair.png"],
        file_path_index={"chair.png": "embed-chair"},
        placeholder_embed_ids=["embed-model"],
        user_id="user-1",
        user_vault_key_id="vault-key-1",
        api_key_hash="api-key-hash",
        device_hash="device-hash",
        external_request=True,
    )

    task_arguments = captured["arguments"]
    assert result == {
        "task_id": "task-model-1",
        "embed_id": "embed-model",
        "status": "processing",
        "estimated_credits": 25,
    }
    assert task_arguments["external_request"] is True
    assert task_arguments["api_key_hash"] == "api-key-hash"
    assert task_arguments["device_hash"] == "device-hash"
    assert task_arguments["reference_embed_ids"] == ["embed-chair"]
    assert "chair.png" not in str(task_arguments)


@pytest.mark.asyncio
async def test_model_generation_charge_payload_uses_hi3d_metadata(monkeypatch) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url, json, headers):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(billing.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(billing, "INTERNAL_API_SHARED_TOKEN", "shared-token")

    await billing.charge_model_generation_credits(
        user_id="user-1",
        user_id_hash="hash-1",
        app_id="models3d",
        skill_id="generate",
        credits=25,
        chat_id="chat-1",
            message_id="message-1",
            api_key_hash="api-key-hash",
            device_hash="device-hash",
            log_prefix="[test]",
    )

    assert requests == [
        {
            "url": "http://api:8000/internal/billing/charge",
            "headers": {"Content-Type": "application/json", "X-Internal-Service-Token": "shared-token"},
            "json": {
                "user_id": "user-1",
                "user_id_hash": "hash-1",
                "credits": 25,
                "skill_id": "generate",
                "app_id": "models3d",
                "api_key_hash": "api-key-hash",
                "device_hash": "device-hash",
                "usage_details": {
                    "chat_id": "chat-1",
                    "message_id": "message-1",
                    "units_processed": 1,
                    "unit_name": "generated_model",
                    "model_used": "hi3d/hitem3dv2.1-fast-pbr",
                    "server_provider": "Hi3D",
                    "server_region": "global",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_model_generation_charge_failure_is_not_silenced(monkeypatch) -> None:
    class FailingResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("billing unavailable")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url, json, headers):
            return FailingResponse()

    monkeypatch.setattr(billing.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(RuntimeError, match="billing unavailable"):
        await billing.charge_model_generation_credits(
            user_id="user-1",
            user_id_hash="hash-1",
            app_id="models3d",
            skill_id="generate",
            credits=25,
            chat_id=None,
            message_id=None,
            api_key_hash=None,
            device_hash=None,
            log_prefix="[test]",
        )
