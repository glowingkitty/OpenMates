# backend/tests/test_images_modify_task.py
#
# Contract tests for one images.modify request (modify_pipeline.run_modify):
# the delivered result and its single charge, every expected failure without a
# charge, and a change of an earlier result through its kept program.
# The author, storage, billing route and safety pipeline are fakes; the
# request parsing, input planning, progress publisher and content builders are real.

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from backend.apps.images.modify_author import ModifyAuthorError, ModifyAuthorResult
from backend.apps.images.tasks import modify_pipeline as pipeline
from backend.apps.images.tasks import modify_task
from backend.apps.images.tasks.modify_inputs import KIND_PIXEL, LoadedInput
from backend.apps.images.tasks.modify_memory import KeptProgram
from backend.apps.images.tasks.modify_result import StoredModifyImage
from backend.apps.images.vector_author import VectorUsage
from backend.shared.providers.e2b_image_edit import ImageEditError
from backend.shared.python_utils.billing_utils import BillingError
from backend.shared.python_utils.generated_media_graph import COMPLETION_RESULT_FIELDS, PER_CHILD_TIMEOUT_SECONDS


@dataclass
class World:
    published: list[dict] = field(default_factory=list)
    progress: list[dict] = field(default_factory=list)
    charges: list[dict] = field(default_factory=list)
    remembered: list[dict] = field(default_factory=list)
    loaded_ids: list[tuple] = field(default_factory=list)
    author_calls: list[dict] = field(default_factory=list)
    kept: dict[str, KeptProgram] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    author_error: Exception | None = None
    headroom_error: Exception | None = None
    input_rejected: bool = False
    stored: int = 0


def _authored() -> ModifyAuthorResult:
    return ModifyAuthorResult(
        image=b"\x89PNG", mime_type="image/png", width=1200, height=800, program="print('edit')",
        model_id="openai/gpt-6.1-sol", attempts=2, review_status="corrected",
        usage=[VectorUsage("author", "openai/gpt-6.1-sol", 2000, 500)], sandbox_seconds=[4.0, 3.0],
    )


@pytest.fixture
def world(monkeypatch) -> World:
    state = World()

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    class EmbedService:
        async def send_embed_data_to_client(self, **kwargs: Any) -> None:
            from toon_format import decode as toon_decode

            state.progress.append(toon_decode(kwargs["content_toon"]))

    async def storage(_task: Any) -> Any:
        return SimpleNamespace(environment="development")

    async def publish(_service: Any, **kwargs: Any) -> None:
        state.published.append(kwargs["content"])

    async def recall(_task: Any, *, embed_id: str, vault_key_id: str) -> Any:
        return state.kept.get(embed_id)

    async def load(_task: Any, *, embed_ids: Any, refs: Any, **_kwargs: Any) -> list[LoadedInput]:
        state.loaded_ids.append(tuple(embed_ids))
        for embed_id in embed_ids:
            if embed_id in state.missing:
                raise pipeline.ReferenceImageUnavailable(f"{embed_id} expired")
        return [LoadedInput(embed_id, ref, b"pixels", KIND_PIXEL) for embed_id, ref in zip(embed_ids, refs)]

    def prepare(items: list) -> list:
        return [SimpleNamespace(name=name, preview=b"jpeg", preview_mime="image/jpeg") for name, _, _ in items]

    class Safety:
        async def validate_input(self, **_kwargs: Any) -> Any:
            if state.input_rejected:
                return SimpleNamespace(allowed=False, rejection=SimpleNamespace(reason="blocked"))
            return SimpleNamespace(allowed=True, rejection=None)

        async def validate_output(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(allowed=True, rejection=None)

    async def reject(*_args: Any, **_kwargs: Any) -> None:
        raise pipeline.ModifyFailure(pipeline.ERROR_SAFETY, "This picture couldn't be modified.")

    async def estimate(**_kwargs: Any) -> int:
        return 20

    async def headroom(**_kwargs: Any) -> None:
        if state.headroom_error:
            raise state.headroom_error

    async def author(**kwargs: Any) -> ModifyAuthorResult:
        state.author_calls.append(kwargs)
        await kwargs["progress"]("running", 1, None)
        if state.author_error:
            raise state.author_error
        return _authored()

    async def credits(**kwargs: Any) -> tuple[int, dict]:
        return 4 + 5 * len(kwargs["sandbox_seconds"]), {"sandbox_runs": len(kwargs["sandbox_seconds"])}

    async def remember(_task: Any, **kwargs: Any) -> None:
        state.remembered.append(kwargs)

    async def store(_task: Any, **kwargs: Any) -> StoredModifyImage:
        state.stored += 1
        return StoredModifyImage(
            files_metadata={"original": {"s3_key": "o", "width": 1200, "height": 800, "size_bytes": 4,
                                         "format": "png", "mime_type": "image/png"}},
            aes_key_b64="key", nonce_b64="", vault_wrapped_aes_key="wrapped", s3_base_url="https://b.example.org",
            filename="edit.png", output_filetype="png",
        )

    async def charge(**kwargs: Any) -> None:
        state.charges.append(kwargs)

    monkeypatch.setattr(pipeline, "_assert_can_generate", noop)
    monkeypatch.setattr(pipeline, "_embed_service", lambda _task: EmbedService())
    monkeypatch.setattr(pipeline, "initialize_task_storage", storage)
    monkeypatch.setattr(pipeline, "require_storage_available", noop)
    monkeypatch.setattr(pipeline, "get_bucket_name", lambda *_args: "chatfiles-dev")
    monkeypatch.setattr(pipeline, "send_generated_media_child", publish)
    monkeypatch.setattr(pipeline, "recall_program", recall)
    monkeypatch.setattr(pipeline, "load_modify_inputs", load)
    monkeypatch.setattr(pipeline, "prepare_inputs", prepare)
    monkeypatch.setattr(pipeline, "get_pipeline", lambda: Safety())
    monkeypatch.setattr(pipeline, "_reject", reject)
    monkeypatch.setattr(pipeline, "estimate_modify_credits", estimate)
    monkeypatch.setattr(pipeline, "ensure_credit_headroom", headroom)
    monkeypatch.setattr(pipeline, "author_modification", author)
    monkeypatch.setattr(pipeline, "modify_credits", credits)
    monkeypatch.setattr(pipeline, "remember_program", remember)
    monkeypatch.setattr(pipeline, "store_modified_image", store)
    monkeypatch.setattr(pipeline, "charge_modify_credits", charge)
    return state


def _task() -> Any:
    async def init() -> None:
        return None

    return SimpleNamespace(request=SimpleNamespace(id="task-1"), initialize_core_services=init,
                           _secrets_manager=object(), _directus_service=object())


def _arguments(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "instructions": "Put the logo top right", "images": ["photo.jpg", "logo.svg"],
        "input_embed_ids": ["embed-photo", "embed-logo"], "requirements": ["logo unchanged"],
        "output_filetype": "png", "user_id": "user-1", "user_vault_key_id": "vault-1", "chat_id": "chat-1",
        "message_id": "msg-1", "embed_id": "child-1", "producer_embed_id": "parent-1",
    }
    values.update(overrides)
    return values


async def _run(**overrides: Any) -> dict[str, Any]:
    return await pipeline.run_modify(_task(), "images", "modify", _arguments(**overrides))


# contract-test: direct surface=rest_api assertions=images-modify.result.normal-image
@pytest.mark.asyncio
async def test_delivered_picture_is_stored_charged_once_and_published(world: World) -> None:
    result = await _run()
    assert result["status"] == "finished" and result["embed_ref"].startswith("generated-images-")
    assert result["review_status"] == "corrected" and result["attempts"] == 2
    assert result["changed_from_program"] is False and result["billing_status"] == "charged"
    assert world.stored == 1 and len(world.published) == 1
    finished = world.published[0]
    assert finished["status"] == "finished" and "image_draft" not in finished
    assert finished["input_embed_ids"] == ["embed-photo", "embed-logo"]
    assert world.remembered[0]["input_embed_ids"] == ["embed-photo", "embed-logo"]
    assert world.remembered[0]["input_refs"] == ["photo.jpg", "logo.svg"]
    assert world.author_calls[0]["requirements"] == ("logo unchanged",)
    assert world.author_calls[0]["source_program"] is None


# contract-test: direct surface=rest_api assertions=images-modify.billing.metered
@pytest.mark.asyncio
async def test_charge_covers_tokens_and_every_sandbox_run(world: World) -> None:
    await _run()
    assert len(world.charges) == 1
    charge = world.charges[0]
    assert charge["credits"] == 4 + 10 and charge["usage_details"] == {"sandbox_runs": 2}
    assert charge["event_id"] == "child-1" and charge["model_ref"] == "openai/gpt-6.1-sol"


# contract-test: direct surface=rest_api assertions=images-modify.progress.shown-while-running
@pytest.mark.asyncio
async def test_progress_is_published_before_and_while_the_author_runs(world: World) -> None:
    await _run()
    assert [item["draft_stage"] for item in world.progress] == ["writing", "running"]
    assert all(item["status"] == "processing" and item["skill_id"] == "modify" for item in world.progress)


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (lambda w: setattr(w, "author_error", ModifyAuthorError("no valid picture")), "no_valid_picture"),
        (lambda w: setattr(w, "author_error", ImageEditError("sandbox_failed", "The sandbox failed.")),
         "sandbox_failed"),
        (lambda w: setattr(w, "author_error", ImageEditError("invalid_input", "Unreadable picture.")),
         "invalid_input"),
        (lambda w: setattr(w, "headroom_error", BillingError("low")), "insufficient_credits"),
        (lambda w: setattr(w, "input_rejected", True), "safety_rejected"),
        (lambda w: w.missing.add("embed-logo"), "invalid_input"),
    ],
)
# contract-test: direct surface=rest_api assertions=images-modify.billing.metered
@pytest.mark.asyncio
async def test_expected_failures_publish_a_reason_and_charge_nothing(world: World, setup: Any, code: str) -> None:
    setup(world)
    result = await _run()
    assert result["status"] == "failed" and result["error_code"] == code and result["child_published"] is True
    assert result["billing_status"] == "not_charged"
    assert world.charges == [] and world.stored == 0 and world.remembered == []
    assert world.published[-1]["status"] == "error" and world.published[-1]["error_code"] == code


# contract-test: direct surface=rest_api assertions=images-modify.request.pictures-from-the-chat
@pytest.mark.asyncio
async def test_seven_pictures_or_unresolved_refs_fail_before_any_work(world: World) -> None:
    refs = [f"{index}.png" for index in range(7)]
    too_many = await _run(images=refs, input_embed_ids=[f"e{index}" for index in range(7)])
    unresolved = await _run(input_embed_ids=["embed-photo"])
    assert too_many["error_code"] == unresolved["error_code"] == "invalid_request"
    assert world.loaded_ids == [] and world.author_calls == [] and world.charges == []


# contract-test: direct surface=rest_api assertions=images-modify.author.program-not-pixels
@pytest.mark.asyncio
async def test_changing_an_earlier_result_reruns_its_program_on_the_original_inputs(world: World) -> None:
    world.kept["result-0"] = KeptProgram(program="print('first')", input_embed_ids=("embed-photo", "embed-logo"),
                                         input_refs=("photo.jpg", "logo.svg"))
    result = await _run(images=["edited.png", "badge.png"], input_embed_ids=["result-0", "embed-badge"])
    assert world.loaded_ids == [("embed-photo", "embed-logo", "embed-badge")]
    assert world.author_calls[0]["source_program"] == "print('first')"
    assert [item.name for item in world.author_calls[0]["inputs"]] == ["photo.jpg", "logo.svg", "badge.png"]
    assert result["changed_from_program"] is True
    assert result["input_embed_ids"] == ["embed-photo", "embed-logo", "embed-badge"]


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
@pytest.mark.asyncio
async def test_expired_original_inputs_use_the_earlier_result_as_a_picture(world: World) -> None:
    world.kept["result-0"] = KeptProgram(program="print('first')", input_embed_ids=("embed-gone",),
                                         input_refs=("old.jpg",))
    world.missing.add("embed-gone")
    result = await _run(images=["edited.png"], input_embed_ids=["result-0"])
    assert world.loaded_ids == [("embed-gone",), ("result-0",)]
    assert world.author_calls[0]["source_program"] is None
    assert result["status"] == "finished" and result["changed_from_program"] is False


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_kept_program_is_not_expanded_beyond_the_picture_limit() -> None:
    kept = {"r": KeptProgram(program="p", input_embed_ids=tuple(f"o{i}" for i in range(5)),
                             input_refs=tuple(f"o{i}.png" for i in range(5)))}
    expanded = pipeline.plan_inputs(["r", "x"], ["r.png", "x.png"], kept)
    assert expanded.embed_ids == ("o0", "o1", "o2", "o3", "o4", "x") and expanded.changed_result_id == "r"
    plain = pipeline.plan_inputs(["r", "x", "y"], ["r.png", "x.png", "y.png"], kept)
    assert plain.embed_ids == ("r", "x", "y") and plain.source_program is None and plain.changed_result_id is None


# contract-test: supporting surface=rest_api assertions=images-modify.surface.semantic-parity
def test_task_registration_matches_the_generated_media_graph() -> None:
    assert modify_task.TASK_NAME == "apps.images.tasks.skill_modify"
    assert PER_CHILD_TIMEOUT_SECONDS[("images", "modify")] == 600
    assert {"review_status", "unmet_requirements", "attempts", "changed_from_program"} <= set(
        COMPLETION_RESULT_FIELDS)
