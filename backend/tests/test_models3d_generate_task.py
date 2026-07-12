# backend/tests/test_models3d_generate_task.py
#
# Contract tests for models3d generation request planning. The planner keeps
# image references out of Celery payloads and makes text/image billing explicit
# before any provider work begins.

import pytest

from backend.apps.models3d.skills.generate_skill import build_generation_plan
from backend.shared.python_utils.image_generation_defaults import (
    ImageGenerationDefault,
    resolve_images_generate_default,
)


REFERENCE_DEFAULT = ImageGenerationDefault(
    model_reference="configured-provider/configured-image-model",
    credits=73,
)


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



    with pytest.raises(ValueError, match="object"):
        build_generation_plan(
            prompt=None,
            image_embed_refs=[],
            image_views=[{"embed_ref": "front.png", "view": "front"}, "not-a-view"],
            file_path_index={"front.png": "embed-front"},
        )
