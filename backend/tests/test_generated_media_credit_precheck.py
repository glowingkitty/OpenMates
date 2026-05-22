# backend/tests/test_generated_media_credit_precheck.py
#
# Verifies long-running generated-media Celery tasks block paid provider calls
# when the shared credit precheck rejects. The providers are mocked so these
# tests never invoke paid image, music, or video APIs.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.images.tasks import generate_task as image_task_module
from backend.apps.music.tasks import generate_task as music_task_module
from backend.shared.python_utils.image_safety import PipelineDecision


class _FakeTask:
    request = SimpleNamespace(id="task-generated-media-1")

    def __init__(self):
        self._secrets_manager = object()
        self._cache_service = object()
        self._directus_service = object()
        self._encryption_service = object()
        self._s3_service = object()
        self.initialized = False
        self.cleaned = False

    async def initialize_services(self):
        self.initialized = True

    async def cleanup_services(self):
        self.cleaned = True


class _AllowingImageSafetyPipeline:
    async def validate_input(self, **kwargs):
        return PipelineDecision(allowed=True)


@pytest.mark.asyncio
async def test_image_generate_precheck_blocks_paid_provider_call(monkeypatch):
    provider_mock = AsyncMock()
    monkeypatch.setattr(image_task_module, "generate_image_google", provider_mock)
    monkeypatch.setattr(image_task_module, "get_pipeline", lambda: _AllowingImageSafetyPipeline())
    monkeypatch.setattr(image_task_module, "_estimate_image_generation_credits", AsyncMock(return_value=200))
    monkeypatch.setattr(
        image_task_module,
        "ensure_credit_headroom",
        AsyncMock(side_effect=RuntimeError("Insufficient credits for image generation")),
    )

    task = _FakeTask()
    with pytest.raises(RuntimeError, match="Insufficient credits"):
        await image_task_module._async_generate_image(
            task,
            "images",
            "generate",
            {
                "prompt": "a small test image",
                "user_id": "user-1",
                "embed_id": "embed-image-1",
                "full_model_reference": "google/gemini-3-pro-image-preview",
            },
        )

    provider_mock.assert_not_awaited()
    assert task.initialized is True
    assert task.cleaned is True


@pytest.mark.asyncio
async def test_music_generate_precheck_blocks_paid_provider_call(monkeypatch):
    provider_mock = AsyncMock()
    monkeypatch.setattr(music_task_module, "generate_music_google_lyria", provider_mock)
    monkeypatch.setattr(music_task_module, "_estimate_music_generation_credits", AsyncMock(return_value=120))
    monkeypatch.setattr(
        music_task_module,
        "ensure_credit_headroom",
        AsyncMock(side_effect=RuntimeError("Insufficient credits for music generation")),
    )

    task = _FakeTask()
    with pytest.raises(RuntimeError, match="Insufficient credits"):
        await music_task_module._async_generate_music(
            task,
            "music",
            "generate",
            {
                "prompt": "a short ambient loop",
                "user_id": "user-1",
                "embed_id": "embed-music-1",
                "model": "lyria-3-pro-preview",
            },
        )

    provider_mock.assert_not_awaited()
    assert task.initialized is True
    assert task.cleaned is True
