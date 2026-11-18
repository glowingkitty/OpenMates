# backend/tests/test_image_generate_default_model.py
#
# images.generate makes normal pixel images with the cheap Recraft V4.1 Flash
# model and runs Gemini 3 Pro Image only for quality "max" (an explicit
# highest-quality request). Providers are never called: the credit estimate is
# the first step that names the chosen model, and the test stops the task there.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.images.tasks import generate_task
from backend.shared.python_utils.image_generation_defaults import resolve_images_generate_default
from backend.shared.python_utils.image_safety import PipelineDecision

FLASH = "recraft/recraftv4_1_flash"
GEMINI_PRO_IMAGE = "google/gemini-3-pro-image-preview"


class _StopAtEstimate(Exception):
    """Raised by the patched estimate so the task never reaches a provider."""


class _AvailableStorage:
    """Object storage that reports itself available, so the task reaches its credit step."""

    async def check_availability(self):
        return "available"


class _FakeTask:
    request = SimpleNamespace(id="task-image-default-model")

    def __init__(self):
        self._secrets_manager = object()
        self._cache_service = object()
        self._directus_service = object()
        self._encryption_service = object()
        self._s3_service = _AvailableStorage()

    async def initialize_core_services(self):
        return None

    async def cleanup_services(self):
        return None


class _AllowingImageSafetyPipeline:
    async def validate_input(self, **kwargs):
        return PipelineDecision(allowed=True)


async def _model_chosen_by_task(monkeypatch, skill_id: str, quality: str) -> str:
    chosen: list[str] = []

    async def record_estimate(model_ref, log_prefix):
        chosen.append(model_ref)
        raise _StopAtEstimate()

    for provider in ("generate_image_google", "generate_raster_recraft", "generate_image_fal_flux"):
        monkeypatch.setattr(generate_task, provider, AsyncMock(side_effect=AssertionError("provider called")))
    monkeypatch.setattr(generate_task, "get_pipeline", lambda: _AllowingImageSafetyPipeline())
    monkeypatch.setattr(generate_task, "_estimate_image_generation_credits", record_estimate)

    with pytest.raises(_StopAtEstimate):
        await generate_task._async_generate_image(
            _FakeTask(), "images", skill_id,
            {
                "prompt": "a red bicycle leaning on a garden fence",
                "user_id": "user-1",
                "embed_id": "embed-image-default-model",
                "external_request": True,
                "skill_id": skill_id,
                "quality": quality,
                "full_model_reference": FLASH,
            },
        )
    return chosen[0]


# contract-test: direct surface=rest_api assertions=images-generate.raster.cheap-default
def test_images_generate_default_model_is_recraft_flash():
    default = resolve_images_generate_default()
    assert default.model_reference == FLASH
    assert default.credits == 15


# contract-test: direct surface=rest_api assertions=images-generate.raster.cheap-default
def test_raster_model_resolution_by_quality_and_references():
    resolve = generate_task._resolve_raster_model_ref
    # A normal request stays on Flash; with reference images it uses the cheap edit model.
    assert resolve(FLASH, skill_id="generate", quality="default", has_reference_images=False) == FLASH
    assert resolve(FLASH, skill_id="generate", quality="default", has_reference_images=True) == "bfl/flux-2-klein"
    # Only an explicit highest-quality request switches to Gemini 3 Pro Image, with or without references.
    assert resolve(FLASH, skill_id="generate", quality="max", has_reference_images=False) == GEMINI_PRO_IMAGE
    assert resolve(FLASH, skill_id="generate", quality="max", has_reference_images=True) == GEMINI_PRO_IMAGE
    # Drafts ignore quality.
    assert resolve(FLASH, skill_id="generate_draft", quality="max", has_reference_images=False) == FLASH
    # A model saved in the user's settings is kept; its own tiers still follow quality.
    assert resolve("recraft/recraftv4_1", skill_id="generate", quality="max", has_reference_images=False) == "recraft/recraftv4_1"
    assert resolve(GEMINI_PRO_IMAGE, skill_id="generate", quality="default", has_reference_images=False) == GEMINI_PRO_IMAGE


# contract-test: direct surface=rest_api assertions=images-generate.raster.cheap-default
@pytest.mark.asyncio
async def test_task_estimates_and_routes_normal_request_to_flash(monkeypatch):
    assert await _model_chosen_by_task(monkeypatch, "generate", "default") == FLASH


# contract-test: direct surface=rest_api assertions=images-generate.raster.cheap-default
@pytest.mark.asyncio
async def test_task_routes_explicit_highest_quality_to_gemini(monkeypatch):
    assert await _model_chosen_by_task(monkeypatch, "generate", "max") == GEMINI_PRO_IMAGE
