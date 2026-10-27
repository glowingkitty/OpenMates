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
    embed = SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None))

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

    async def check_availability(self):
        return "available"

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

    async def initialize_core_services(self):
        self.initialized = True

    async def cleanup_services(self):
        self.cleaned = True


@pytest.fixture(autouse=True)
def registered_output_guard(monkeypatch):
    from backend.core.api.app.services.embed_service import EmbedService
    monkeypatch.setattr(EmbedService, "assert_registered_output_can_generate", AsyncMock())


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
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


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
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


# contract-test: supporting surface=gui.web assertions=billing.credits.idempotent-charge
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


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default,video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_skill_preserves_source_and_normalizes_call_settings(monkeypatch):
    dispatch = AsyncMock(return_value="task-h3")
    monkeypatch.setattr(video_skill_module, "execute_skill_via_celery", dispatch)
    skill = GenerateSkill(app=None, app_id="videos", skill_id="generate", skill_name="Generate Video", skill_description="Generate video", celery_producer=object())
    source = "44444444-4444-4444-8444-444444444444"
    result = await skill.execute([{"prompt": "animate this garden", "model": video_skill_module.H3_MODEL, "input_embed_ids": [source]}], user_id="user-1", placeholder_embed_ids=["embed-1"])
    assert result["status"] == "processing"
    args = dispatch.await_args.kwargs["arguments"]["requests"][0]
    assert (args["model"], args["duration_seconds"], args["resolution"]) == (video_skill_module.H3_MODEL, 5, "480p")
    assert args["input_embed_ids"] == [source]
    rejected = await skill.execute([{"prompt": "a garden", "model": video_skill_module.H3_MODEL}], user_id="user-1", external_request=True)
    assert "REST" in rejected["error"]
    assert dispatch.await_count == 1


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default,video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_task_uses_normal_encrypted_storage_and_measured_duration(monkeypatch):
    provider = AsyncMock(return_value=video_task_module.GeneratedH3Video(b"h3-mp4", 5.4, "16:9"))
    monkeypatch.setattr(video_task_module, "_generate_h3_video", provider)
    monkeypatch.setattr(video_task_module, "generate_video_google_veo", AsyncMock(side_effect=AssertionError("must not call Veo")))
    index = AsyncMock(return_value=True)
    monkeypatch.setattr(video_task_module, "index_generated_asset", index)
    monkeypatch.setattr(video_task_module, "cache_s3_file_keys", AsyncMock())
    monkeypatch.setattr(video_task_module, "ensure_credit_headroom", AsyncMock())
    charge = AsyncMock()
    monkeypatch.setattr(video_task_module, "_charge_video_generation_credits", charge)
    task = _FakeTask()
    source = "44444444-4444-4444-8444-444444444444"
    result = await video_task_module._async_generate_video(task, "videos", "generate", {"prompt": "a garden", "model": video_skill_module.H3_MODEL, "user_id": "user-1", "embed_id": "embed-1", "input_embed_ids": [source]})
    assert result["status"] == "finished"
    assert result["provider"] == "fal.ai"
    assert result["duration_seconds"] == 5.4
    assert result["resolution"] == "480p"
    assert result["watermarking"] == "not_reported"
    assert result["input_embed_ids"] == [source]
    assert task._s3_service.uploads[0][2] != b"h3-mp4"
    assert index.await_args.kwargs["content_hash_source"] == b"h3-mp4"
    assert charge.await_args.args[6] == 5.4


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default
@pytest.mark.asyncio
async def test_h3_completed_media_failure_still_charges_once(monkeypatch):
    provider = AsyncMock(side_effect=video_task_module.h3_turbo.FalCompletedMediaError("accepted-1", 5.3))
    monkeypatch.setattr(video_task_module, "_generate_h3_video", provider)
    monkeypatch.setattr(video_task_module, "ensure_credit_headroom", AsyncMock())
    charge = AsyncMock()
    monkeypatch.setattr(video_task_module, "_charge_video_generation_credits", charge)
    task = _FakeTask()
    with pytest.raises(video_task_module.h3_turbo.FalCompletedMediaError):
        await video_task_module._async_generate_video(task, "videos", "generate", {"prompt": "a garden", "model": video_skill_module.H3_MODEL, "user_id": "user-1", "embed_id": "embed-1"})
    charge.assert_awaited_once()
    assert charge.await_args.args[6] == 5.3
    assert not task._s3_service.uploads


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_foreign_source_denied_before_decryption(monkeypatch):
    monkeypatch.setattr(video_task_module, "recover_fresh_upload_image", AsyncMock(side_effect=video_task_module.FreshUploadImageUnavailable("missing")))
    monkeypatch.setattr(video_task_module, "_load_embed_record", AsyncMock(return_value={"user_id": "someone-else", "encrypted_content": "vault:v1:foreign"}))
    decrypt = AsyncMock()
    monkeypatch.setattr(video_task_module, "resolve_encrypted_image_embed", decrypt)
    with pytest.raises(ValueError, match="unavailable to this caller"):
        await video_task_module._resolve_h3_source(_FakeTask(), embed_id="source", user_id="user-1")
    decrypt.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default
@pytest.mark.asyncio
async def test_h3_duplicate_submission_never_contacts_provider(monkeypatch):
    class Cache:
        @property
        async def client(self):
            return SimpleNamespace(set=AsyncMock(return_value=False))
    task = _FakeTask()
    task._cache_service = Cache()
    task._secrets_manager = SimpleNamespace(get_secret=AsyncMock(return_value="fake-key"))
    submit = AsyncMock()
    monkeypatch.setattr(video_task_module.h3_turbo, "submit_clip", submit)
    with pytest.raises(RuntimeError, match="already submitted"):
        await video_task_module._generate_h3_video(task, prompt="a garden", user_id="user-1", embed_id="embed-1", source_ids=[], seed=None)
    submit.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default
@pytest.mark.asyncio
async def test_h3_provider_submits_once_and_uses_measured_output_duration(monkeypatch):
    class Cache:
        @property
        async def client(self):
            return SimpleNamespace(set=AsyncMock(return_value=True))
    task = _FakeTask()
    task._cache_service = Cache()
    task._secrets_manager = SimpleNamespace(get_secret=AsyncMock(return_value="fake-key"))
    submit = AsyncMock(return_value=SimpleNamespace(request_id="accepted-1"))
    result = video_task_module.h3_turbo.FalClip(b"mp4", 5.0, 5.6, "accepted-1")
    poll = AsyncMock(return_value=result)
    monkeypatch.setattr(video_task_module.h3_turbo, "submit_clip", submit)
    monkeypatch.setattr(video_task_module.h3_turbo, "await_clip", poll)
    generated = await video_task_module._generate_h3_video(task, prompt="a garden", user_id="user-1", embed_id="embed-1", source_ids=[], seed=42)
    submit.assert_awaited_once()
    poll.assert_awaited_once()
    assert submit.await_args.kwargs["seed"] == 42
    assert generated.video_bytes == b"mp4"
    assert generated.duration_seconds == 5.6


# contract-test: supporting surface=gui.web assertions=video-call.video.fast-generation-default
@pytest.mark.asyncio
async def test_h3_rest_rejected_before_paid_generation(monkeypatch):
    provider = AsyncMock()
    monkeypatch.setattr(video_task_module, "_generate_h3_video", provider)
    with pytest.raises(ValueError, match="REST"):
        await video_task_module._async_generate_video(_FakeTask(), "videos", "generate", {"prompt": "a garden", "model": video_skill_module.H3_MODEL, "user_id": "user-1", "external_request": True})
    provider.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_fixture_requires_all_guards_and_keeps_saved_source(monkeypatch):
    import io
    import subprocess
    from PIL import Image
    from backend.shared.python_utils.encrypted_embed_images import ResolvedEncryptedImage
    photo = io.BytesIO()
    Image.new("RGB", (640, 480), "green").save(photo, "JPEG")
    source = ResolvedEncryptedImage(photo.getvalue(), "image/jpeg")
    monkeypatch.setattr(video_task_module, "_resolve_h3_source", AsyncMock(return_value=source))
    # asyncio.to_thread awaits the synchronous renderer in production.
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"local-fixture-mp4"))
    submit = AsyncMock()
    monkeypatch.setattr(video_task_module.h3_turbo, "submit_clip", submit)
    for key, value in {"CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_AI_FIXTURES": "1", "MOCK_EXTERNAL_APIS": "true"}.items():
        monkeypatch.setenv(key, value)
    task = _FakeTask()
    generated = await video_task_module._generate_h3_video(task, prompt="Animate the exact saved camera image with a gentle camera movement.", user_id="user-1", embed_id="embed-1", source_ids=["saved-source"], seed=None)
    assert generated.video_bytes == b"local-fixture-mp4"
    assert generated.aspect_ratio == "640:480"
    submit.assert_not_awaited()
    monkeypatch.delenv("OPENMATES_CI_ISOLATED")
    task._secrets_manager = SimpleNamespace(get_secret=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await video_task_module._generate_h3_video(task, prompt="Animate the exact saved camera image with a gentle camera movement.", user_id="user-1", embed_id="embed-1", source_ids=["saved-source"], seed=None)


# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_source_upload_survives_client_encrypted_cache_replacement(monkeypatch):
    import base64
    import io
    from PIL import Image
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aes_key = bytes(range(32))
    nonce = bytes(range(12))
    photo = io.BytesIO()
    Image.new("RGB", (32, 24), "green").save(photo, "JPEG")
    source_bytes = photo.getvalue()
    upload = {"embed_id": "source", "user_id": "user-1",
              # Older upload records label original JPEGs as WEBP.
              "files": {"original": {"s3_key": "owner/image", "format": "webp"}},
              "aes_nonce": base64.b64encode(nonce).decode(),
              "vault_wrapped_aes_key": "vault:v1:wrapped"}
    monkeypatch.setattr(video_task_module, "recover_fresh_upload_image", AsyncMock(return_value=upload))
    # The ordinary embed is client ciphertext and cannot be opened by Vault.
    load = AsyncMock(return_value={"encrypted_content": "client-ciphertext", "hashed_user_id": video_task_module._hash_value("user-1")})
    monkeypatch.setattr(video_task_module, "_load_embed_record", load)
    task = _FakeTask()
    task._encryption_service.decrypt_with_user_key = AsyncMock(return_value=base64.b64encode(aes_key).decode())
    task._s3_service.get_file = AsyncMock(return_value=AESGCM(aes_key).encrypt(nonce, source_bytes, None))
    result = await video_task_module._resolve_h3_source(task, embed_id="source", user_id="user-1")
    assert result.content == source_bytes
    assert result.mime_type == "image/jpeg"
    load.assert_not_awaited()
    task._encryption_service.decrypt_with_user_key.assert_awaited_once_with("vault:v1:wrapped", "vault-user-1")



# contract-test: supporting surface=gui.web assertions=video-call.video.source-frame-provenance
@pytest.mark.asyncio
async def test_h3_never_decrypts_client_embed_content_with_vault(monkeypatch):
    monkeypatch.setattr(video_task_module, "recover_fresh_upload_image", AsyncMock(side_effect=video_task_module.FreshUploadImageUnavailable("expired")))
    monkeypatch.setattr(video_task_module, "_load_embed_record", AsyncMock(return_value={"user_id": "user-1", "encrypted_content": "client-ciphertext"}))
    decrypt = AsyncMock()
    monkeypatch.setattr(video_task_module, "resolve_encrypted_image_embed", decrypt)
    with pytest.raises(ValueError, match="no longer available"):
        await video_task_module._resolve_h3_source(_FakeTask(), embed_id="source", user_id="user-1")
    decrypt.assert_not_awaited()
