# backend/tests/test_videos_generate_pipeline.py
#
# Contract tests for one videos.generate request (generate_pipeline.run_generate):
# a composed video is stored, charged once (author tokens plus 5 credits per
# started sandbox minute) and delivered as ONE child with timeline and source;
# a compose failure, a change request or an unreachable routing model publish a
# failed child and charge nothing; a generative clip carries made_by and a
# one-clip timeline. The composer, storage, billing route and safety are fakes.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock

from backend.apps.videos.composed.models import AuthorUsage, ComposedInput, ComposedVideo, ComposeFailure
from backend.apps.videos.routing import RoutingUnavailable
from backend.apps.videos.tasks import generate_pipeline as pipeline
from backend.apps.videos.tasks import generate_task
from backend.apps.videos.tasks.generate_inputs import PictureRef
from backend.apps.videos.tasks.generate_result import StoredVideo
from backend.shared.python_utils.generated_media_graph import COMPLETION_RESULT_FIELDS

TIMELINE = {"fps": 30, "duration_in_frames": 180, "width": 1080, "height": 1080, "tracks": [
    {"id": "t1", "name": "Slides", "kind": "visual", "parts": [
        {"id": "p1", "label": "Title", "from": 0, "duration_in_frames": 180, "kind": "text",
         "texts": [{"id": "x1", "value": "Launch week"}]}]}]}


def _video() -> ComposedVideo:
    return ComposedVideo(
        mp4=b"mp4", thumbnail_png=b"png", source="export const Composition = () => null;",
        filename="Composition.tsx", timeline=TIMELINE, fps=30, width=1080, height=1080, duration_in_frames=180,
        attempts=2, author_model="openai/gpt-6.1-sol",
        usage=(AuthorUsage("gpt-6.1-sol", "openai", 3000, 2000, "writing"),
               AuthorUsage("gpt-6.1-sol", "openai", 3500, 900, "correcting")),
        sandbox_seconds=(50.0, 70.0),
    )


@dataclass
class World:
    published: list[dict] = field(default_factory=list)
    progress: list[dict] = field(default_factory=list)
    charges: list[dict] = field(default_factory=list)
    compose_calls: list[Any] = field(default_factory=list)
    stored: int = 0
    compose_error: Exception | None = None
    route_error: Exception | None = None
    pictures: list[PictureRef] = field(default_factory=list)
    reviewed_frames: list[bytes] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)
    store_kwargs: list[dict] = field(default_factory=list)


class _Task:
    request = SimpleNamespace(id="task-video-2")

    def __init__(self) -> None:
        self._secrets_manager = object()
        self._directus_service = object()
        self._cache_service = object()
        self._encryption_service = object()
        self.cleaned = 0

    async def initialize_core_services(self) -> None:
        return None

    async def cleanup_services(self) -> None:
        self.cleaned += 1


@pytest.fixture
def world(monkeypatch) -> World:
    state = World()

    class EmbedService:
        def __init__(self, *_args: Any) -> None:
            pass

        @staticmethod
        async def assert_registered_output_can_generate(*_args: Any, **_kwargs: Any) -> None:
            return None

        async def send_embed_data_to_client(self, **kwargs: Any) -> None:
            from toon_format import decode as toon_decode

            state.progress.append(toon_decode(kwargs["content_toon"]))

    import backend.core.api.app.services.embed_service as embed_service_module

    monkeypatch.setattr(embed_service_module, "EmbedService", EmbedService)

    async def publish(_service: Any, **kwargs: Any) -> None:
        state.published.append(kwargs["content"])

    async def storage(_task: Any) -> Any:
        return SimpleNamespace(environment="development", base_domain="s3.example.test")

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def classify(embed_ids: Any, refs: Any, **_kwargs: Any) -> list[PictureRef]:
        return state.pictures or [PictureRef(embed_id, ref, "image") for embed_id, ref in zip(embed_ids, refs)]

    async def load(_task: Any, *, pictures: Any, **_kwargs: Any) -> tuple[list, list]:
        inputs = [ComposedInput(name=f"input-{i}.jpg", content=b"jpeg", mime_type="image/jpeg", width=800,
                                height=600, title="Rocket launch" if p.kind == "search_result" else "photo.jpg",
                                kind="search_result" if p.kind == "search_result" else "image")
                  for i, p in enumerate(pictures, start=1)]
        return inputs, [p.kind for p in pictures]

    class Safety:
        async def validate_input(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(allowed=True, rejection=None)

        async def validate_output(self, **kwargs: Any) -> Any:
            state.reviewed_frames.append(kwargs["image_bytes"])
            return SimpleNamespace(allowed=True, rejection=None)

    async def compose(request: Any, *, on_stage: Any, **_kwargs: Any) -> ComposedVideo:
        state.compose_calls.append(request)
        for stage in ("writing", "rendering", "correcting", "rendering"):
            await on_stage(stage)
        if state.compose_error:
            raise state.compose_error
        return _video()

    async def decide(**kwargs: Any) -> Any:
        if state.route_error:
            raise state.route_error
        from backend.apps.videos.routing import decide_route

        return await decide_route(**kwargs)

    async def pricing(_model_ref: str) -> dict:
        return {"pricing": {"tokens": {"input": {"per_credit_unit": 1000}, "output": {"per_credit_unit": 500}}}}

    async def credits(**kwargs: Any) -> tuple[int, dict]:
        from backend.apps.videos.tasks.generate_billing import composed_credits

        return await composed_credits(**kwargs, pricing_for=pricing)

    async def estimate(**_kwargs: Any) -> int:
        return 30

    async def store(_task: Any, **kwargs: Any) -> StoredVideo:
        state.stored += 1
        state.store_kwargs.append(kwargs)
        return StoredVideo(files_metadata={"original": {"s3_key": "o", "size_bytes": 3, "format": "mp4"},
                                           "thumbnail": {"s3_key": "t", "size_bytes": 3, "format": "png"}},
                           extra_metadata={}, aes_key_b64="key", nonce_b64="nonce", vault_wrapped_aes_key="wrapped",
                           s3_base_url="https://chatfiles.s3.example.test")

    async def charge(**kwargs: Any) -> None:
        state.charges.append(kwargs)

    monkeypatch.setattr(pipeline, "send_generated_media_child", publish)
    monkeypatch.setattr(pipeline, "initialize_task_storage", storage)
    monkeypatch.setattr(pipeline, "require_storage_available", noop)
    monkeypatch.setattr(pipeline, "get_bucket_name", lambda *_args: "chatfiles")
    monkeypatch.setattr(pipeline, "task_reader", lambda *_args: None)
    monkeypatch.setattr(pipeline, "classify_pictures", classify)
    monkeypatch.setattr(pipeline, "load_composed_inputs", load)
    monkeypatch.setattr(pipeline, "get_pipeline", lambda: Safety())
    monkeypatch.setattr(pipeline, "compose_video", compose)
    monkeypatch.setattr(pipeline, "decide_route", decide)
    monkeypatch.setattr(pipeline, "composed_credits", credits)
    monkeypatch.setattr(pipeline, "estimate_composed_credits", estimate)
    monkeypatch.setattr(pipeline, "ensure_credit_headroom", noop)
    monkeypatch.setattr(pipeline, "store_composed_video", store)
    monkeypatch.setattr(pipeline, "charge_composed_credits", charge)

    async def review_frames(_mp4: bytes) -> tuple[bytes, ...]:
        return (b"first", b"middle", b"last")

    async def keep(_task: Any, **kwargs: Any) -> None:
        state.kept.append(kwargs)

    from backend.shared.python_utils import video_frames

    monkeypatch.setattr(video_frames, "review_frames", review_frames)
    monkeypatch.setattr(pipeline, "_keep_composed", keep)
    return state


def _arguments(**overrides: Any) -> dict:
    images = overrides.pop("image_embed_ids", [str(uuid.uuid4()), str(uuid.uuid4())])
    return {
        "instructions": "A square recap of the launch with the title Launch week",
        "prompt": "A square recap of the launch with the title Launch week",
        "images": [f"photo-{i}" for i in range(len(images))], "mode": "composed", "aspect_ratio": "1:1",
        "duration_seconds": 6, "resolution": None, "model": None, "seed": None, "source_video": None,
        "change": None, "first_frame_embed_ids": [], "image_embed_ids": images, "input_embed_ids": images,
        "user_id": "user-1", "user_vault_key_id": "vault-1", "chat_id": "chat-1", "message_id": "message-1",
        "embed_id": "child-1", "producer_embed_id": "parent-1", "media_child_index": 0, "media_batch": True,
        **overrides,
    }


# contract-test: supporting surface=gui.web assertions=billing.credits.idempotent-charge
@pytest.mark.asyncio
async def test_composed_video_is_stored_charged_once_and_one_child(world: World) -> None:
    task = _Task()
    result = await pipeline.run_generate(task, "videos", "generate", _arguments())

    assert world.stored == 1 and len(world.published) == 1
    [charge] = world.charges
    # 6500 input tokens / 1000 + 2900 output tokens / 500 = 12.3 → 12, plus 5 + 10 for a 50 s and a 70 s render.
    assert charge["credits"] == 27 and charge["event_id"] == "child-1"
    assert charge["usage_details"]["sandbox_runs"] == 2
    child = world.published[0]
    assert child["made_by"] == "composed" and child["routing_decided_by"] == "request_mode"
    assert child["timeline"] == TIMELINE and child["remotion_source"].startswith("export const")
    assert (child["fps"], child["width"], child["height"], child["duration_seconds"]) == (30, 1080, 1080, 6.0)
    assert child["version"] == 1 and child["attempts"] == 2 and child["author_model"] == "openai/gpt-6.1-sol"
    assert child["can_extend_end"] is False and child["can_extend_start"] is False
    assert set(child["files"]) == {"original", "thumbnail"}
    assert world.compose_calls[0].aspect_ratio == "1:1" and len(world.compose_calls[0].inputs) == 2
    assert [update["progress_stage"] for update in world.progress] == ["writing", "rendering", "correcting",
                                                                       "rendering"]
    assert result["status"] == "finished" and "remotion_source" not in result and "aes_key" not in result
    assert {"made_by", "routing_decided_by", "width", "height", "fps", "source_titles"} <= COMPLETION_RESULT_FIELDS
    assert task.cleaned == 1
    # Output safety looks at the first, middle and last frame of the MP4.
    assert world.reviewed_frames == [b"first", b"middle", b"last"]
    # The input pictures are stored with the video and kept for later changes.
    assert len(world.store_kwargs[0]["inputs"]) == 2
    assert world.kept[0]["in_chat"] is True and len(world.kept[0]["pictures"]) == 2


# contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
@pytest.mark.asyncio
async def test_search_result_titles_reach_the_child(world: World) -> None:
    ids = [str(uuid.uuid4())]
    world.pictures = [PictureRef(ids[0], "photo-0", "search_result")]
    await pipeline.run_generate(_Task(), "videos", "generate", _arguments(image_embed_ids=ids))
    assert world.published[0]["source_titles"] == ["Rocket launch"]


# contract-test: supporting surface=gui.web assertions=videos-generate.billing.metered
@pytest.mark.asyncio
async def test_compose_failure_charges_nothing_and_publishes_failed_child(world: World) -> None:
    world.compose_error = ComposeFailure("render_failed", "the sandbox render failed")
    result = await pipeline.run_generate(_Task(), "videos", "generate", _arguments())
    assert world.charges == [] and world.stored == 0
    assert result["status"] == "failed" and result["child_published"] is True
    assert result["error_code"] == "render_failed"
    assert world.published[0]["status"] == "error" and world.published[0]["made_by"] == "composed"


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_change_request_is_not_available_before_anything_runs(world: World, monkeypatch) -> None:
    monkeypatch.delenv("IMAGE_EDIT_AS_EMBED_VERSION", raising=False)
    result = await pipeline.run_generate(_Task(), "videos", "generate", _arguments(
        source_video="generated-videos-abc", change="extend_end", source_video_embed_id=str(uuid.uuid4()),
        images=[], image_embed_ids=[], input_embed_ids=[], mode="auto"))
    assert result["error_code"] == "change_not_available" and world.charges == []
    assert world.compose_calls == [] and world.published[0]["error_code"] == "change_not_available"


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_change_of_a_video_that_is_not_a_generated_child_fails_without_charge(world: World, monkeypatch) -> None:
    from backend.shared.python_utils import media_revision

    monkeypatch.setenv("IMAGE_EDIT_AS_EMBED_VERSION", "true")
    monkeypatch.setattr(media_revision, "find_revision_target", AsyncMock(return_value=None))
    result = await pipeline.run_generate(_Task(), "videos", "generate", _arguments(
        source_video="generated-videos-abc", change="extend_end", source_video_embed_id=str(uuid.uuid4()),
        images=[], image_embed_ids=[], input_embed_ids=[], mode="auto", user_vault_key_id="vault-1"))
    assert result["error_code"] == "invalid_input" and world.charges == [] and world.compose_calls == []
    assert "only a video made by this chat" in result["error"]


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_unreachable_routing_model_fails_without_charge(world: World) -> None:
    world.route_error = RoutingUnavailable("down")
    result = await pipeline.run_generate(_Task(), "videos", "generate", _arguments(mode="auto"))
    assert result["error_code"] == "routing_unavailable" and world.charges == [] and world.compose_calls == []
    assert world.progress[0]["progress_stage"] == "deciding"


# contract-test: supporting surface=gui.web assertions=videos-generate.generative.clip
@pytest.mark.asyncio
async def test_generative_route_uses_clip_producer_with_final_settings(world: World, monkeypatch) -> None:
    captured = {}

    async def clip(_task: Any, _app: str, _skill: str, arguments: dict) -> dict:
        captured.update(arguments)
        return {"status": "finished", "embed_id": arguments["embed_id"]}

    monkeypatch.setattr(generate_task, "_async_generate_video", clip)
    source = str(uuid.uuid4())
    await pipeline.run_generate(_Task(), "videos", "generate", _arguments(
        mode="generative", aspect_ratio="16:9", duration_seconds=None, image_embed_ids=[source]))
    # A picture without a named model starts a Gemini Omni clip as its first frame.
    assert (captured["model"], captured["duration_seconds"], captured["resolution"]) == (
        "gemini-omni-1.2-flash", 8, "720p")
    assert captured["full_model_reference"] == "google/gemini-omni-1.2-flash"
    assert captured["input_embed_ids"] == [source] and captured["routing_decided_by"] == "request_mode"
    assert [update["progress_stage"] for update in world.progress] == ["generating"]
    assert world.compose_calls == []


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_generative_with_a_search_result_picture_is_explicit(world: World) -> None:
    ids = [str(uuid.uuid4())]
    world.pictures = [PictureRef(ids[0], "photo-0", "search_result")]
    result = await pipeline.run_generate(_Task(), "videos", "generate", _arguments(
        mode="generative", aspect_ratio="16:9", duration_seconds=None, image_embed_ids=ids))
    assert result["error_code"] == "invalid_input" and world.charges == []


# contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
def test_generative_child_fields_carry_made_by_and_one_clip_timeline() -> None:
    generated = SimpleNamespace(resolution="720p", aspect_ratio="9:16", duration_seconds=8)
    fields = generate_task._generative_result_fields({"routing_decided_by": "routing_model"}, generated,
                                                     "A fox in snow")
    assert fields["made_by"] == "generative" and fields["routing_decided_by"] == "routing_model"
    assert (fields["width"], fields["height"], fields["fps"], fields["version"]) == (720, 1280, 30, 1)
    [track] = fields["timeline"]["tracks"]
    [part] = track["parts"]
    assert part["duration_in_frames"] == fields["timeline"]["duration_in_frames"] == 240
    assert part["label"] == "A fox in snow"
    assert fields["can_extend_end"] is False and fields["can_extend_start"] is False


# contract-test: supporting surface=gui.web assertions=videos-generate.change.same-video-next-version
@pytest.mark.asyncio
async def test_change_request_checks_the_output_guard_before_any_work(world: World, monkeypatch) -> None:
    import backend.core.api.app.services.embed_service as embed_service_module

    guard = AsyncMock(side_effect=RuntimeError("producer mismatch"))
    monkeypatch.setattr(embed_service_module.EmbedService, "assert_registered_output_can_generate", guard)
    run_change = AsyncMock()
    monkeypatch.setattr(pipeline, "run_change_request", run_change)
    with pytest.raises(RuntimeError, match="producer mismatch"):
        await pipeline.run_generate(_Task(), "videos", "generate", _arguments(
            source_video="generated-videos-abc", change="extend_end", source_video_embed_id=str(uuid.uuid4()),
            images=[], image_embed_ids=[], input_embed_ids=[], mode="auto"))
    guard.assert_awaited_once()
    run_change.assert_not_awaited()
