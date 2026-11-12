# backend/tests/test_videos_generate_request.py
#
# videos.generate request contract and skill-side reference resolution (no network).

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.apps.videos import generate_request as gr
from backend.apps.videos.skills import generate_skill as video_skill_module
from backend.apps.videos.skills.generate_skill import GenerateSkill


def _skill():
    skill = GenerateSkill(app=None, app_id="videos", skill_id="generate", skill_name="Generate",
                          skill_description="Generate video", celery_producer=object())
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"
    return skill


@pytest.fixture
def dispatch(monkeypatch):
    mock = AsyncMock(return_value="celery-task-1")
    monkeypatch.setattr(video_skill_module, "execute_skill_via_celery", mock)
    return mock


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_instructions_accept_former_prompt_and_bounds():
    assert gr.parse_generate_request({"prompt": " a garden "}).instructions == "a garden"
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": ""})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x" * 4001})
    assert len(gr.parse_generate_request({"instructions": "x" * 4000}).instructions) == 4000


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_images_limit_and_mode_choices():
    request = gr.parse_generate_request({"instructions": "recap", "images": [f"ref-{i}" for i in range(12)]})
    assert len(request.images) == 12 and request.mode == "auto"
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "recap", "images": [f"ref-{i}" for i in range(13)]})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "recap", "mode": "magic"})


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_duration_bounds_per_route():
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "duration_seconds": 61})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "duration_seconds": 1})
    assert gr.parse_generate_request({"instructions": "x", "mode": "composed", "duration_seconds": 45})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "mode": "generative", "duration_seconds": 16})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "mode": "generative", "duration_seconds": 2})
    assert gr.parse_generate_request({"instructions": "x", "mode": "generative", "duration_seconds": 7})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "source_video": "generated-videos-abc",
                                   "change": "extend_end", "duration_seconds": 11})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "mode": "generative", "aspect_ratio": "1:1"})


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
def test_generative_with_two_pictures_is_an_explicit_error():
    with pytest.raises(gr.GenerateRequestError) as exc:
        gr.parse_generate_request({"instructions": "x", "mode": "generative", "images": ["a", "b"]})
    assert exc.value.code == "generative_needs_one_picture"


# contract-test: supporting surface=gui.web assertions=videos-generate.change.extend-generated-clip
def test_change_fields_and_model_imply_generative():
    request = gr.parse_generate_request({"instructions": "add a sunset", "source_video": "generated-videos-abc"})
    assert request.is_change and request.change == "edit"
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "change": "extend_end"})
    assert gr.parse_generate_request({"instructions": "x", "model": gr.H3_MODEL}).mode == "generative"
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "model": "not-a-model"})
    with pytest.raises(gr.GenerateRequestError):
        gr.parse_generate_request({"instructions": "x", "mode": "composed", "model": gr.DEFAULT_MODEL})


@pytest.mark.parametrize("item, code", [
    ({"instructions": "x", "images": ["upload-1"]}, "not_available_via_api"),
    ({"instructions": "x", "mode": "composed"}, "not_available_via_api"),
    ({"instructions": "x", "source_video": "generated-videos-abc"}, "not_available_via_api"),
    ({"instructions": "x", "model": gr.H3_MODEL}, "not_available_via_api"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
def test_rest_refusals(item, code):
    with pytest.raises(gr.GenerateRequestError) as exc:
        gr.check_external_request(gr.parse_generate_request(item))
    assert exc.value.code == code


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_skill_resolves_exact_refs_and_dispatches(dispatch):
    image_a, image_b = str(uuid.uuid4()), str(uuid.uuid4())
    result = await _skill().execute(
        [{"instructions": "a recap of these photos", "images": ["photo-a", "photo-b"], "mode": "composed",
          "aspect_ratio": "1:1"}],
        user_id="user-1", user_vault_key_id="vault-1", placeholder_embed_ids=["embed-1"],
        file_path_index={"photo-a": image_a, "photo-b": image_b},
    )
    assert result == {"task_id": "celery-task-1", "embed_id": "embed-1", "status": "processing"}
    queued = dispatch.await_args.kwargs["arguments"]["requests"][0]
    assert queued["image_embed_ids"] == [image_a, image_b]
    assert queued["input_embed_ids"] == [image_a, image_b]
    assert queued["images"] == ["photo-a", "photo-b"]
    assert (queued["mode"], queued["aspect_ratio"], queued["model"]) == ("composed", "1:1", None)
    assert queued["first_frame_embed_ids"] == []


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_skill_unknown_ref_is_invalid_input_and_nothing_is_queued(dispatch, monkeypatch):
    monkeypatch.setattr(GenerateSkill, "_resolve_earlier_results", AsyncMock(return_value={}))
    result = await _skill().execute(
        [{"instructions": "recap", "images": ["photo-a", "photo-z"]}],
        user_id="user-1", user_vault_key_id="vault-1", file_path_index={"photo-a": str(uuid.uuid4())},
    )
    assert result["error_code"] == "invalid_input" and "photo-z" in result["error"]
    dispatch.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_skill_resolves_earlier_search_results_through_their_parent(dispatch, monkeypatch):
    child = str(uuid.uuid4())
    resolver = AsyncMock(return_value={"photo-result-1": child})
    monkeypatch.setattr(GenerateSkill, "_resolve_earlier_results", resolver)
    await _skill().execute(
        [{"instructions": "recap", "images": ["photo-result-1"], "mode": "composed"}],
        user_id="user-1", user_vault_key_id="vault-1", file_path_index={"images-search-1": str(uuid.uuid4())},
    )
    assert resolver.await_args.args[0] == ["photo-result-1"]
    assert dispatch.await_args.kwargs["arguments"]["requests"][0]["image_embed_ids"] == [child]


# contract-test: supporting surface=gui.web assertions=videos-generate.request.instruction-and-pictures
@pytest.mark.asyncio
async def test_skill_rest_refuses_pictures_and_composed(dispatch):
    for item in ({"instructions": "x", "images": ["a"]}, {"instructions": "x", "mode": "composed"},
                 {"instructions": "x", "source_video": "v"}):
        result = await _skill().execute([item], user_id="user-1", external_request=True)
        assert result["error_code"] == "not_available_via_api"
    dispatch.assert_not_awaited()


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
@pytest.mark.asyncio
async def test_skill_rest_text_only_is_generative_omni(dispatch):
    await _skill().execute([{"instructions": "a garden at dawn"}], user_id="user-1", external_request=True,
                           placeholder_embed_ids=["embed-1"])
    queued = dispatch.await_args.kwargs["arguments"]["requests"][0]
    assert (queued["mode"], queued["model"], queued["resolution"]) == ("generative", gr.DEFAULT_MODEL, "720p")
    assert queued["full_model_reference"] == f"google/{gr.DEFAULT_MODEL}" == "google/gemini-omni-1.2-flash"


# contract-test: supporting surface=gui.web assertions=videos-generate.routing.generative-or-composed
def test_user_request_travels_to_the_task_for_routing():
    from backend.apps.videos.generate_request import parse_generate_request, task_arguments

    request = parse_generate_request({"instructions": "A cinematic overview of three discoveries",
                                      "user_request": "  Based on the web results, create a short video for me  "})
    assert request.user_request == "Based on the web results, create a short video for me"
    assert parse_generate_request(task_arguments(request)).user_request == request.user_request
    assert parse_generate_request({"instructions": "A fox"}).user_request == ""
