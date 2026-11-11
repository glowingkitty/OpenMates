# backend/tests/test_images_modify_skill.py
#
# Contract tests for the images.modify skill surface and its task helpers:
# request validation, reference resolution before dispatch, input selection per
# picture kind, the progress wire shape and its draft budget, finished and
# failed result content, metered billing sums and the kept program.

from __future__ import annotations

import base64
import time
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest

from backend.apps.images.modify_author import ModifyAuthorResult
from backend.apps.images.modify_request import ModifyRequestError, parse_modify_request
from backend.apps.images.skills import modify_skill
from backend.apps.images.skills.modify_skill import ModifySkill
from backend.apps.images.tasks import modify_inputs
from backend.apps.images.tasks.modify_billing import estimate_modify_credits, modify_credits
from backend.apps.images.tasks.modify_inputs import (
    KIND_EMBROIDERY,
    KIND_PIXEL,
    KIND_SVG,
    LoadedInput,
    load_embroidery_index_record,
    select_source,
)
from backend.apps.images.tasks.modify_memory import (
    PROGRAM_TTL_SECONDS,
    KeptProgramError,
    program_cache_key,
    recall_program,
    remember_program,
)
from backend.apps.images.tasks.modify_progress import (
    MAX_DRAFT_BASE64_CHARS,
    ModifyProgressPublisher,
    encode_draft,
    processing_content,
)
from backend.apps.images.tasks.modify_result import (
    StoredModifyImage,
    aspect_ratio,
    assistant_result,
    build_failed_content,
    build_finished_content,
)
from backend.apps.images.tasks.reference_images import ReferenceImageUnavailable
from backend.apps.images.vector_author import VectorUsage

PRICING = {"pricing": {"tokens": {"input": {"per_credit_unit": 1000}, "output": {"per_credit_unit": 250}}}}


async def _pricing(_model: str) -> dict:
    return PRICING


def _skill(producer: Any = object()) -> ModifySkill:
    return ModifySkill(
        app=None, app_id="images", skill_id="modify", skill_name="Modify",
        skill_description="Exact picture changes", celery_producer=producer,
    )


def _jpeg(side: int, noise: bool = False) -> bytes:
    from PIL import Image

    image = Image.effect_noise((side, side), 120).convert("RGB") if noise else Image.new("RGB", (side, side), "red")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def _authored(**overrides: Any) -> ModifyAuthorResult:
    values: dict[str, Any] = {
        "image": b"png", "mime_type": "image/png", "width": 1600, "height": 900, "program": "print(1)",
        "model_id": "openai/gpt-6.1-sol", "attempts": 2, "review_status": "unmet_delivered",
        "unmet_requirements": ("logo stays in the corner",),
    }
    values.update(overrides)
    return ModifyAuthorResult(**values)


# contract-test: direct surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_request_defaults_bounds_and_normalisation() -> None:
    request = parse_modify_request(instructions="  put   the logo\n top right ", images=["a.png", "b.svg"])
    assert request.instructions == "put the logo top right"
    assert request.images == ("a.png", "b.svg")
    assert request.requirements == () and request.output_filetype == "png"
    assert parse_modify_request(instructions="x", images=["a"], output_filetype="JPEG").output_filetype == "jpg"
    assert parse_modify_request(instructions="x", images=["a"], requirements=["keep it", " "]).requirements == (
        "keep it",)
    # One text instead of a list counts as one requirement per line.
    assert parse_modify_request(instructions="x", images=["a"], requirements="green background\n\nwhite frame"
                                ).requirements == ("green background", "white frame")
    for bad in ({"instructions": "", "images": ["a"]}, {"instructions": "x" * 2001, "images": ["a"]},
                {"instructions": "x", "images": []}, {"instructions": "x", "images": ["a"] * 7},
                {"instructions": "x", "images": [""]}, {"instructions": "x", "images": "a.png"},
                {"instructions": "x", "images": ["a"], "requirements": ["r"] * 9},
                {"instructions": "x", "images": ["a"], "requirements": ["r" * 301]},
                {"instructions": "x", "images": ["a"], "output_filetype": "gif"}):
        with pytest.raises(ModifyRequestError):
            parse_modify_request(**bad)


# contract-test: direct surface=rest_api assertions=images-modify.request.pictures-from-the-chat
@pytest.mark.asyncio
async def test_skill_resolves_exact_refs_and_dispatches_one_request(monkeypatch) -> None:
    dispatched: list[dict] = []

    async def dispatch(**kwargs: Any) -> str:
        dispatched.append(kwargs)
        return "task-1"

    monkeypatch.setattr(modify_skill, "execute_skill_via_celery", dispatch)
    result = await _skill().execute(
        instructions="Put the logo top right", images=["photo.jpg", "logo.svg"], requirements=["logo unchanged"],
        file_path_index={"photo.jpg": "embed-photo", "logo.svg": "embed-logo"}, placeholder_embed_ids=["slot-1"],
        user_id="user-1", user_vault_key_id="vault-1",
    )
    assert result == {"task_id": "task-1", "embed_id": "slot-1", "status": "processing"}
    arguments = dispatched[0]["arguments"]
    assert dispatched[0]["app_id"] == "images" and dispatched[0]["skill_id"] == "modify"
    assert arguments["input_embed_ids"] == ["embed-photo", "embed-logo"]
    assert arguments["images"] == ["photo.jpg", "logo.svg"] and arguments["output_filetype"] == "png"
    assert arguments["requests"][0]["input_embed_ids"] == ["embed-photo", "embed-logo"]
    assert "requests" not in arguments["requests"][0]


# contract-test: direct surface=rest_api assertions=images-modify.request.pictures-from-the-chat
@pytest.mark.asyncio
async def test_skill_rejects_unknown_refs_and_invalid_calls_before_dispatch(monkeypatch) -> None:
    async def dispatch(**_kwargs: Any) -> str:
        raise AssertionError("nothing may be dispatched")

    monkeypatch.setattr(modify_skill, "execute_skill_via_celery", dispatch)
    unknown = await _skill().execute(instructions="x", images=["Photo.JPG"], file_path_index={"photo.jpg": "e"})
    assert unknown["error_code"] == "invalid_input" and "'Photo.JPG'" in unknown["error"]
    too_many = await _skill().execute(instructions="x", images=[f"{i}.png" for i in range(7)])
    assert too_many["error_code"] == "invalid_request"


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_source_selection_uses_full_resolution_per_kind() -> None:
    assert select_source({"code": "<svg viewBox='0 0 1 1'/>"}) == (KIND_SVG, "<svg viewBox='0 0 1 1'/>", None)
    stitches = {"preview_transparent": {"s3_key": "p.png", "format": "png"}, "full": {"format": "webp"}}
    assert select_source({"files": stitches})[0] == KIND_EMBROIDERY
    assert select_source({"files": {"original": {"format": "svg", "s3_key": "o.svg"}}})[0] == KIND_SVG
    original = {"format": "jpg", "s3_key": "o.jpg"}
    assert select_source({"files": {"original": original, "full": {"format": "webp"}}}) == (KIND_PIXEL, None,
                                                                                            original)
    full = {"format": "webp", "s3_key": "f.webp"}
    assert select_source({"files": {"original": {"format": "heic"}, "full": full}}) == (KIND_PIXEL, None, full)
    for content in ({}, {"files": {"preview": {"format": "webp"}}}, {"code": "plain text"}):
        with pytest.raises(ReferenceImageUnavailable):
            select_source(content)
    assert LoadedInput("e", "n", b"", KIND_EMBROIDERY).program_kind == "pixel"
    assert LoadedInput("e", "n", b"", KIND_SVG).program_kind == "svg"


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
@pytest.mark.asyncio
async def test_embroidery_index_record_is_owner_bound_and_within_the_window() -> None:
    def row(**overrides: Any) -> dict:
        value = {"embed_id": "emb-1", "user_id": "user-1", "created_at": int(time.time()) - 60,
                 "files_metadata": {"preview_transparent": {"s3_key": "k"}}, "vault_wrapped_aes_key": "wrapped"}
        value.update(overrides)
        return value

    class Directus:
        def __init__(self, rows: list) -> None:
            self.rows = rows
            self.params: dict = {}

        async def get_items(self, collection: str, params: dict, no_cache: bool) -> list:
            assert collection == "upload_files" and no_cache
            self.params = params
            return self.rows

    directus = Directus([row()])
    record = await load_embroidery_index_record(directus_service=directus, embed_id="emb-1", user_id="user-1")
    assert record["files"] == {"preview_transparent": {"s3_key": "k"}}
    assert directus.params["filter"]["user_id"] == {"_eq": "user-1"}
    for rows in ([], [row(user_id="user-2")], [row(created_at=int(time.time()) - 90_000)],
                 [row(files_metadata={"full": {}})], [row(vault_wrapped_aes_key="")]):
        with pytest.raises(ReferenceImageUnavailable):
            await load_embroidery_index_record(directus_service=Directus(rows), embed_id="emb-1", user_id="user-1")
    assert modify_inputs.FRESH_UPLOAD_WINDOW_SECONDS == 86400


# contract-test: direct surface=rest_api assertions=images-modify.progress.shown-while-running
def test_processing_content_carries_stage_attempt_and_optional_draft() -> None:
    content = processing_content(instructions="Put the logo", model="gpt-6.1-sol", output_filetype="png",
                                 input_embed_ids=["a"], stage="checking", attempt=2, image_draft="QUJD")
    assert content["status"] == "processing" and content["skill_id"] == "modify"
    assert content["draft_stage"] == "checking" and content["draft_attempt"] == 2
    assert content["image_draft"] == "QUJD" and not content["image_draft"].startswith("data:")
    plain = processing_content(instructions="x", model=None, output_filetype="png", input_embed_ids=[],
                               stage="writing", attempt=1, image_draft=None)
    assert "image_draft" not in plain
    with pytest.raises(ValueError):
        processing_content(instructions="x", model=None, output_filetype="png", input_embed_ids=[],
                           stage="drawing", attempt=1, image_draft=None)


# contract-test: direct surface=rest_api assertions=images-modify.progress.shown-while-running
def test_draft_is_a_bare_base64_jpeg_within_60_kb() -> None:
    small = _jpeg(64)
    assert base64.b64decode(encode_draft(small)) == small
    large = _jpeg(1400, noise=True)
    assert len(large) > MAX_DRAFT_BASE64_CHARS
    encoded = encode_draft(large)
    assert encoded is not None and len(encoded) <= MAX_DRAFT_BASE64_CHARS
    assert base64.b64decode(encoded)[:3] == b"\xff\xd8\xff"


# contract-test: direct surface=rest_api assertions=images-modify.progress.shown-while-running
@pytest.mark.asyncio
async def test_publisher_keeps_the_latest_draft_and_skips_repeats() -> None:
    sent: list[dict] = []

    class EmbedService:
        async def send_embed_data_to_client(self, **kwargs: Any) -> None:
            from toon_format import decode as toon_decode

            sent.append({**kwargs, "content": toon_decode(kwargs["content_toon"])})

    publisher = ModifyProgressPublisher(
        EmbedService(), embed_id="child-1", parent_embed_id="parent-1", user_id="user-1", chat_id="chat-1",
        message_id="msg-1", instructions="Put the logo", model="gpt-6.1-sol", output_filetype="png",
        input_embed_ids=["a"], log_prefix="[t]",
    )
    await publisher.announce()
    await publisher("running", 1, None)
    await publisher("checking", 1, _jpeg(64))
    await publisher("checking", 1, None)
    await publisher("correcting", 2, None)
    stages = [(item["content"]["draft_stage"], "image_draft" in item["content"]) for item in sent]
    assert stages == [("writing", False), ("running", False), ("checking", True), ("correcting", True)]
    first = sent[0]
    assert first["status"] == "processing" and first["embed_type"] == "generated_image"
    assert first["parent_embed_id"] == "parent-1" and first["check_cache_status"] is False


# contract-test: direct surface=rest_api assertions=images-modify.result.normal-image
def test_finished_content_is_a_generated_image_with_review_fields_and_no_draft() -> None:
    stored = StoredModifyImage(
        files_metadata={"original": {"s3_key": "o", "width": 1600, "height": 900, "size_bytes": 10, "format": "png",
                                     "mime_type": "image/png"},
                        "preview": {"s3_key": "p", "width": 600, "height": 338, "size_bytes": 4, "format": "webp",
                                    "mime_type": "image/webp"}},
        aes_key_b64="key", nonce_b64="", vault_wrapped_aes_key="wrapped", s3_base_url="https://b.example.org",
        filename="logo.png", output_filetype="png",
    )
    content = build_finished_content(skill_id="modify", stored=stored, authored=_authored(), instructions="Put",
                                     input_embed_ids=["a", "b"], changed_from_program=True, billing_status="charged")
    assert content["status"] == "finished" and content["type"] == "image" and "image_draft" not in content
    assert content["aspect_ratio"] == "16:9" and content["model"] == "gpt-6.1-sol" and content["provider"] == "openai"
    assert content["review_status"] == "unmet_delivered"
    assert content["unmet_requirements"] == ["logo stays in the corner"] and content["attempts"] == 2
    assert content["changed_from_program"] is True and "program" not in content
    reply = assistant_result(embed_id="child-1", content=content)
    assert reply["embed_ref"].startswith("generated-images-") and reply["width"] == 1600
    assert reply["review_status"] == "unmet_delivered" and "aes_key" not in reply
    assert set(reply["files"]["original"]) == {"width", "height", "size_bytes", "format"}
    assert aspect_ratio(1024, 1024) == "1:1"


# contract-test: direct surface=rest_api assertions=images-modify.result.normal-image
def test_failed_content_explains_and_is_not_charged() -> None:
    content = build_failed_content(skill_id="modify", instructions="x", output_filetype="png", input_embed_ids=["a"],
                                   error_code="no_valid_picture", user_message="No valid picture.")
    assert content["status"] == "error" and content["files"] == {}
    assert content["billing_status"] == "not_charged" and content["error_code"] == "no_valid_picture"


# contract-test: direct surface=rest_api assertions=images-modify.billing.metered
@pytest.mark.asyncio
async def test_billing_sums_tokens_once_and_five_credits_per_started_sandbox_minute() -> None:
    usage = [VectorUsage("author", "openai/gpt-6.1-sol", 2000, 500),
             VectorUsage("review", "openai/gpt-6.1-sol", 1500, 250)]
    credits, details = await modify_credits(usage=usage, sandbox_seconds=[4.0], pricing_for=_pricing)
    # tokens: 2 + 2 + 1.5 + 1 = 6.5 -> 6; one started minute -> 5
    assert credits == 11
    assert details["input_tokens"] == 3500 and details["sandbox_runs"] == 1
    assert details["provider_calls"][-1] == {"step": "sandbox_run", "model_used": "e2b/sandbox",
                                             "duration_seconds": 4.0, "credits": 5}
    two_runs, _ = await modify_credits(usage=usage, sandbox_seconds=[4.0, 61.0], pricing_for=_pricing)
    assert two_runs == 6 + 5 + 10
    assert await estimate_modify_credits(picture_count=2, author_model="openai/gpt-6.1-sol",
                                         pricing_for=_pricing) == 5 + 10 + 5


# contract-test: supporting surface=rest_api assertions=images-modify.billing.metered
@pytest.mark.asyncio
async def test_billing_never_treats_missing_usage_or_price_as_free() -> None:
    async def no_price(_model: str) -> None:
        return None

    with pytest.raises(RuntimeError):
        await modify_credits(usage=[VectorUsage("author", "openai/gpt-6.1-sol", 0, 0)], sandbox_seconds=[],
                             pricing_for=_pricing)
    with pytest.raises(RuntimeError):
        await modify_credits(usage=[VectorUsage("author", "openai/gpt-6.1-sol", 10, 10)], sandbox_seconds=[],
                             pricing_for=no_price)


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, tuple[Any, int]] = {}

    async def set(self, key: str, value: Any, ex: int) -> None:
        self.values[key] = (value, ex)

    async def get(self, key: str) -> Any:
        entry = self.values.get(key)
        return entry[0] if entry else None


async def _client(cache: _Cache) -> _Cache:
    return cache


class _Encryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> tuple[str, str]:
        return f"enc:{key_id}:{plaintext}", "v1"

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> str:
        prefix = f"enc:{key_id}:"
        return ciphertext[len(prefix):] if ciphertext.startswith(prefix) else ""


def _memory_task(cache: _Cache) -> Any:
    class CacheService:
        @property
        def client(self) -> Any:
            return _client(cache)

    return SimpleNamespace(_cache_service=CacheService(), _encryption_service=_Encryption())


# contract-test: direct surface=rest_api assertions=images-modify.author.program-not-pixels
@pytest.mark.asyncio
async def test_kept_program_round_trips_encrypted_for_24_hours() -> None:
    cache = _Cache()
    task = _memory_task(cache)
    await remember_program(task, embed_id="result-1", program="print('edit')", input_embed_ids=["a", "b"],
                           input_refs=["photo.jpg", "logo.svg"], vault_key_id="vault-1")
    stored, ttl = cache.values[program_cache_key("result-1")]
    assert ttl == PROGRAM_TTL_SECONDS == 86400 and stored.startswith("enc:vault-1:")
    kept = await recall_program(task, embed_id="result-1", vault_key_id="vault-1")
    assert kept is not None and kept.program == "print('edit')"
    assert kept.input_embed_ids == ("a", "b") and kept.input_refs == ("photo.jpg", "logo.svg")
    assert await recall_program(task, embed_id="other", vault_key_id="vault-1") is None
    with pytest.raises(KeptProgramError):
        await recall_program(task, embed_id="result-1", vault_key_id="vault-2")
