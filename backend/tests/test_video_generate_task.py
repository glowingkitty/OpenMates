# backend/tests/test_video_generate_task.py
#
# Mock-based coverage for videos.generate. These tests must never call the real
# Google Veo API because regular test/spec runs must stay deterministic and free
# of paid generation costs.

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.videos.skills import generate_skill as video_skill_module
from backend.apps.videos.skills.generate_skill import GenerateSkill
from backend.apps.videos.tasks import generate_task as video_task_module
from backend.shared.providers.google.gemini_video import GeneratedVideo


class _FakeDirectusService:
    async def get_user_profile(self, user_id: str):
        return True, {"vault_key_id": f"vault-{user_id}"}, None


class _FakeEncryptionService:
    async def encrypt_with_user_key(self, value: str, vault_key_id: str):
        return f"wrapped:{vault_key_id}:{value[:8]}", None


class _FakeS3Service:
    base_domain = "s3.example.test"

    def __init__(self):
        self.uploads = []
        self.deleted = []

    async def upload_file(self, bucket_key: str, file_key: str, content: bytes, content_type: str):
        self.uploads.append((bucket_key, file_key, content, content_type))
        return {"url": f"https://s3.example.test/{file_key}"}

    async def delete_file(self, bucket_key: str, file_key: str):
        self.deleted.append((bucket_key, file_key))


class _FakeTask:
    request = SimpleNamespace(id="task-video-1")

    def __init__(self):
        self._secrets_manager = object()
        self._directus_service = _FakeDirectusService()
        self._encryption_service = _FakeEncryptionService()
        self._s3_service = _FakeS3Service()
        self._cache_service = object()
        self.initialized = False
        self.cleaned = False

    async def initialize_services(self):
        self.initialized = True

    async def cleanup_services(self):
        self.cleaned = True


@pytest.mark.asyncio
async def test_video_generate_skill_dispatches_celery_without_real_provider(monkeypatch):
    dispatched = {}

    async def fake_execute_skill_via_celery(**kwargs):
        dispatched.update(kwargs)
        return "celery-task-1"

    monkeypatch.setattr(video_skill_module, "execute_skill_via_celery", fake_execute_skill_via_celery)

    skill = GenerateSkill(
        app=None,
        app_id="videos",
        skill_id="generate",
        skill_name="Generate Video",
        skill_description="Generate video",
        celery_producer=object(),
    )
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    result = await skill.execute(
        [{"prompt": "a robot walking through Berlin", "duration_seconds": 8, "resolution": "1080p"}],
        user_id="user-1",
        placeholder_embed_ids=["embed-1"],
    )

    assert result == {"task_id": "celery-task-1", "embed_id": "embed-1", "status": "processing"}
    assert dispatched["app_id"] == "videos"
    assert dispatched["skill_id"] == "generate"
    assert dispatched["arguments"]["prompt"] == "a robot walking through Berlin"
    assert dispatched["arguments"]["duration_seconds"] == 8
    assert dispatched["arguments"]["resolution"] == "1080p"


@pytest.mark.asyncio
async def test_video_generate_task_uses_mocked_provider_and_returns_rest_download_url(monkeypatch):
    provider_mock = AsyncMock(
        return_value=GeneratedVideo(
            video_bytes=b"fake mp4 bytes",
            mime_type="video/mp4",
            model="veo-3.1-fast-generate-preview",
            duration_seconds=8,
            resolution="1080p",
            aspect_ratio="16:9",
        )
    )
    monkeypatch.setattr(video_task_module, "generate_video_google_veo", provider_mock)
    monkeypatch.setattr(video_task_module, "index_generated_asset", AsyncMock(return_value=True))
    monkeypatch.setattr(video_task_module, "cache_s3_file_keys", AsyncMock(return_value=None))
    precheck_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(video_task_module, "ensure_credit_headroom", precheck_mock)
    charge_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(video_task_module, "_charge_video_generation_credits", charge_mock)

    task = _FakeTask()
    result = await video_task_module._async_generate_video(
        task,
        "videos",
        "generate",
        {
            "prompt": "a robot walking through Berlin",
            "user_id": "user-1",
            "embed_id": "embed-video-1",
            "model": "veo-3.1-fast-generate-preview",
            "duration_seconds": 8,
            "resolution": "1080p",
            "external_request": True,
        },
    )

    provider_mock.assert_awaited_once()
    precheck_mock.assert_awaited_once_with(
        user_id="user-1",
        estimated_credits=1440,
        log_prefix="[Task ID: task-video-1]",
        operation_name="video generation",
    )
    charge_mock.assert_not_awaited()
    assert task.initialized is True
    assert task.cleaned is True
    assert task._s3_service.uploads
    assert result["status"] == "finished"
    assert result["files"]["original"]["download_url"].startswith(
        "https://api.dev.openmates.org/v1/generated-assets/embed-video-1/files/original/download?token="
    )
    assert "aes_key" not in result
    assert "aes_nonce" not in result
    assert "vault_wrapped_aes_key" not in result


@pytest.mark.asyncio
async def test_video_generate_task_precheck_blocks_paid_provider_call(monkeypatch):
    provider_mock = AsyncMock()
    monkeypatch.setattr(video_task_module, "generate_video_google_veo", provider_mock)
    monkeypatch.setattr(
        video_task_module,
        "ensure_credit_headroom",
        AsyncMock(side_effect=RuntimeError("Insufficient credits for video generation")),
    )

    task = _FakeTask()
    with pytest.raises(RuntimeError, match="Insufficient credits"):
        await video_task_module._async_generate_video(
            task,
            "videos",
            "generate",
            {
                "prompt": "a robot walking through Berlin",
                "user_id": "user-1",
                "embed_id": "embed-video-1",
                "model": "veo-3.1-generate-preview",
                "duration_seconds": 8,
                "resolution": "720p",
            },
        )

    provider_mock.assert_not_awaited()
    assert task.cleaned is True
