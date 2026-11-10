# backend/tests/test_design_embroidery_task.py
#
# Contract tests for one design.embroidery conversion (feature.app-skill.design-embroidery).
# The sandbox session and the vector author are fakes; storage encryption,
# request rules, rework decisions, result content and billing sums are real.

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from backend.apps.design.embroidery import pipeline, rework
from backend.apps.design.embroidery.content import INVALID_SOURCE_MESSAGE
from backend.apps.design.embroidery.storage import RESULT_VARIANTS
from backend.apps.images.vector_author import VectorAuthorError, VectorAuthorResult, VectorUsage
from backend.shared.providers.e2b_embroidery import (
    EMBROIDERY_TEMPLATE_NAME,
    EmbroideryCheck,
    EmbroideryError,
    EmbroideryOptions,
    EmbroideryRun,
)
from backend.shared.python_utils.encrypted_embed_vectors import ResolvedVectorSource, VectorSourceError
from backend.shared.python_utils.media_encryption import decrypt_media_payload

SOURCE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><path d="M0 0H100V80Z" fill="#c33"/></svg>'
REWORKED_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><path d="M0 0H90V80Z" fill="#c33"/></svg>'
EMBED_ID = "6f1c2f5e-6a3b-4c7e-9d1a-2b3c4d5e6f70"
SUMMARY = {
    "width_mm": 90.0, "height_mm": 74.0, "stitch_count": 12345, "thread_changes": 2,
    "estimated_minutes": 14, "fits_hoop": "yes",
    "threads": [
        {"colour_hex": "#cc3333", "name": "Red", "stitch_count": 8000},
        {"colour_hex": "#222222", "name": "Black", "stitch_count": 3000},
        {"colour_hex": "#ffffff", "name": "White", "stitch_count": 1345},
    ],
    "notes": [{"code": "background_removed", "text": "Background left out"},
              {"code": "tiny_details_removed", "count": 3, "text": "3 detail(s) too small to sew left out"}],
}


@dataclass
class World:
    findings: list[dict] = field(default_factory=list)
    remaining: list[dict] = field(default_factory=list)
    convert_error: EmbroideryError | None = None
    sandbox_seconds: float = 21.0
    sessions: int = 0
    session_kwargs: list[dict] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    converted: list[tuple[str, Any]] = field(default_factory=list)
    author_calls: list[dict] = field(default_factory=list)
    author_result: Any = None
    published: list[dict] = field(default_factory=list)
    charges: list[dict] = field(default_factory=list)
    uploads: dict[str, bytes] = field(default_factory=dict)
    indexed: list[dict] = field(default_factory=list)
    source: Any = None


class FakeSession:
    def __init__(self, world: World) -> None:
        self.world = world
        world.sessions += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    @property
    def sandbox_seconds(self) -> float:
        return self.world.sandbox_seconds

    async def check(self, svg: str, options: EmbroideryOptions) -> Any:
        self.world.checked.append(svg)
        return EmbroideryCheck(findings=list(self.world.findings), colour_count=3, shape_count=4)

    async def convert(self, svg: str, options: EmbroideryOptions) -> Any:
        self.world.converted.append((svg, options))
        if self.world.convert_error:
            raise self.world.convert_error
        files = {name: f"{name}-bytes".encode() for name in RESULT_VARIANTS}
        return EmbroideryRun(summary=dict(SUMMARY), files=files, findings=list(self.world.remaining))


class FakeS3:
    base_domain = "s3.example.test"
    environment = "development"

    def __init__(self, world: World) -> None:
        self.world = world

    async def upload_file(self, *, bucket_key: str, file_key: str, content: bytes, content_type: str) -> dict:
        self.world.uploads[file_key] = content
        return {"url": f"https://example.test/{file_key}"}

    async def delete_file(self, *, bucket_key: str, file_key: str) -> None:
        self.world.uploads.pop(file_key, None)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    state = World()
    state.source = ResolvedVectorSource(svg=SOURCE_SVG, origin="generated_svg", label="Fox logo")
    monkeypatch.setenv(pipeline.TEMPLATE_ENV, "embroidery-template-id")

    async def noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def storage(_task: Any) -> FakeS3:
        return FakeS3(state)

    async def resolve(**_kwargs: Any) -> ResolvedVectorSource:
        if isinstance(state.source, Exception):
            raise state.source
        return state.source

    async def publish(_service: Any, **kwargs: Any) -> str:
        state.published.append(kwargs)
        return "generated-design-ref"

    async def index(_task: Any, **kwargs: Any) -> bool:
        state.indexed.append(kwargs)
        return True

    async def charge(**kwargs: Any) -> None:
        state.charges.append(kwargs)

    async def pricing(_model: str) -> dict:
        return {"pricing": {"tokens": {"input": {"per_credit_unit": 1000}, "output": {"per_credit_unit": 100}}}}

    async def author(**kwargs: Any) -> Any:
        state.author_calls.append(kwargs)
        if isinstance(state.author_result, Exception):
            raise state.author_result
        return state.author_result

    async def estimate(**_kwargs: Any) -> int:
        return 20

    async def api_key(_secrets: Any) -> str:
        return "e2b-test-key"

    original_credits = pipeline.embroidery_credits

    async def credits(**kwargs: Any) -> Any:
        return await original_credits(pricing_for=pricing, **kwargs)

    monkeypatch.setattr(pipeline, "_assert_can_generate", noop)
    monkeypatch.setattr(pipeline, "initialize_task_storage", storage)
    monkeypatch.setattr(pipeline, "require_storage_available", noop)
    monkeypatch.setattr(pipeline, "_embed_service", lambda _task: object())
    monkeypatch.setattr(pipeline, "get_bucket_name", lambda *_args: "chatfiles-dev")
    monkeypatch.setattr(pipeline, "resolve_vector_source_embed", resolve)
    monkeypatch.setattr(pipeline, "send_generated_media_child", publish)
    monkeypatch.setattr(pipeline, "index_generated_asset", index)
    monkeypatch.setattr(pipeline, "cache_s3_file_keys", noop)
    monkeypatch.setattr(pipeline, "charge_embroidery_credits", charge)
    monkeypatch.setattr(pipeline, "embroidery_credits", credits)
    monkeypatch.setattr(pipeline, "estimate_embroidery_credits", estimate)
    monkeypatch.setattr(pipeline, "ensure_credit_headroom", noop)
    monkeypatch.setattr(pipeline, "get_e2b_api_key_async", api_key)
    def open_session(*, api_key: str, template: str) -> FakeSession:
        state.session_kwargs.append({"api_key": api_key, "template": template})
        return FakeSession(state)

    monkeypatch.setattr(pipeline, "open_embroidery_session", open_session)
    monkeypatch.setattr(rework, "author_svg", author)
    return state


def _task(world: World) -> Any:
    async def client() -> object:
        return object()

    async def wrap(aes_key_b64: str, vault_key_id: str) -> tuple[str, str]:
        return f"vault:v1:{vault_key_id}", "v1"

    async def init() -> None:
        return None

    class Cache:
        @property
        def client(self) -> Any:
            return client()

    cache = Cache()
    return SimpleNamespace(
        request=SimpleNamespace(id="task-1"),
        initialize_core_services=init,
        _cache_service=cache,
        _directus_service=object(),
        _encryption_service=SimpleNamespace(encrypt_with_user_key=wrap),
        _secrets_manager=object(),
        _s3_service=FakeS3(world),
    )


def _arguments(**overrides: Any) -> dict[str, Any]:
    return {
        "user_id": "user-1", "user_vault_key_id": "vault-key-1", "embed_id": EMBED_ID,
        "producer_embed_id": EMBED_ID, "chat_id": "chat-1", "message_id": "message-1",
        "source": "fox-logo.svg", "source_embed_id": "source-embed-1", "width_mm": 90,
        "hoop": "130x180", "fabric": "normal", "instructions": "", **overrides,
    }


async def _run(world: World, **overrides: Any) -> dict[str, Any]:
    return await pipeline.run_embroidery(_task(world), "design", "embroidery", _arguments(**overrides))


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source,design-embroidery.result.complete-and-truthful
@pytest.mark.asyncio
async def test_generated_svg_converts_without_model_call_and_delivers_every_file(world: World) -> None:
    result = await _run(world)

    assert world.author_calls == []
    assert world.checked == [SOURCE_SVG]
    assert world.converted[0][0] == SOURCE_SVG
    assert world.converted[0][1] == EmbroideryOptions(width_mm=90.0, hoop="130x180", fabric="normal")
    assert result["status"] == "finished"
    assert result["stitch_count"] == 12345 and result["thread_changes"] == 2
    assert set(result["files"]) == set(RESULT_VARIANTS)
    content = world.published[-1]["content"]
    assert content["status"] == "finished" and content["type"] == "embroidery_design"
    assert set(content["files"]) == {"dst", "pes", "exp", "jef", "vp3", "preview", "prepared_svg", "stitches"}
    for key in ("title", "width_mm", "height_mm", "stitch_count", "thread_changes", "estimated_minutes", "hoop",
                "fits_hoop", "fabric", "reworked", "threads", "notes", "s3_base_url", "aes_key",
                "vault_wrapped_aes_key", "generated_at", "source_embed_ref", "input_embed_ids", "billing_status"):
        assert key in content, key
    assert content["title"] == "Fox logo"
    assert content["width_mm"] == 90.0 and content["height_mm"] == 74.0
    assert [thread["name"] for thread in content["threads"]] == ["Red", "Black", "White"]
    assert content["notes"] == [
        {"code": "background_removed", "text": "Background left out"},
        {"code": "tiny_details_removed", "text": "3 detail(s) too small to sew left out", "count": 3},
    ]
    assert content["reworked"] is False and content["billing_status"] == "charged"
    assert content["source_embed_ref"] == "fox-logo.svg" and content["input_embed_ids"] == ["source-embed-1"]
    assert content["files"]["pes"]["filename"] == "fox-logo.pes"
    assert content["files"]["pes"]["mime_type"] == "application/octet-stream"


# contract-test: direct surface=rest_api assertions=design-embroidery.privacy.stored-like-generated-media
@pytest.mark.asyncio
async def test_result_files_are_stored_encrypted_and_indexed_for_downloads(world: World) -> None:
    await _run(world)

    content = world.published[-1]["content"]
    import base64
    aes_key = base64.b64decode(content["aes_key"])
    for variant, metadata in content["files"].items():
        stored = world.uploads[metadata["s3_key"]]
        assert stored != f"{variant}-bytes".encode()
        plaintext = decrypt_media_payload(
            encrypted_data=stored, aes_key=aes_key, variant=metadata, legacy_nonce_b64=content["aes_nonce"],
        )
        assert plaintext == f"{variant}-bytes".encode()
    assert world.indexed[0]["files_metadata"] == content["files"]
    assert world.indexed[0]["vault_wrapped_aes_key"] == "vault:v1:vault-key-1"


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_svg_code_embed_source_converts_at_default_width(world: World) -> None:
    world.source = ResolvedVectorSource(svg=SOURCE_SVG, origin="svg_code", label="")

    result = await _run(world, width_mm=None, hoop=None, fabric=None, source="star.svg")

    assert result["status"] == "finished"
    assert world.converted[0][1] == EmbroideryOptions(width_mm=100.0, hoop="none", fabric="normal")
    assert world.published[-1]["content"]["title"] == "star"


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source,design-embroidery.billing.metered
@pytest.mark.asyncio
@pytest.mark.parametrize("source_error", [
    VectorSourceError("Referenced embed is not a vector graphic"),
    VectorSourceError("Referenced image is no longer available"),
])
async def test_pixel_or_unknown_source_fails_without_sandbox_or_charge(world: World, source_error: Exception) -> None:
    world.source = source_error

    result = await _run(world, source="dog.jpg")

    assert result["status"] == "failed" and result["error_code"] == "invalid_source"
    assert result["error"] == INVALID_SOURCE_MESSAGE
    assert world.sessions == 0 and world.charges == [] and world.uploads == {}
    content = world.published[-1]["content"]
    assert content["status"] == "error" and content["error_code"] == "invalid_source"
    assert content["files"] == {} and content["billing_status"] == "not_charged"


# contract-test: direct surface=rest_api assertions=design-embroidery.request.vector-source
@pytest.mark.asyncio
async def test_missing_source_embed_id_is_invalid_source(world: World) -> None:
    result = await _run(world, source_embed_id="")

    assert result["error_code"] == "invalid_source"
    assert world.sessions == 0 and world.charges == []


# contract-test: direct surface=rest_api assertions=design-embroidery.prepare.model-rework-only-when-needed,design-embroidery.billing.metered
@pytest.mark.asyncio
async def test_findings_trigger_exactly_one_rework_before_conversion(world: World) -> None:
    world.findings = [
        {"code": "gradient_or_filter", "detail": "linear gradient on badge"},
        {"code": "live_text", "detail": "one <text> element"},
    ]
    world.author_result = VectorAuthorResult(
        svg=REWORKED_SVG, model_id="openai/gpt-6.1-sol", attempts=1, review_status="skipped",
        usage=[VectorUsage("drawing", "openai/gpt-6.1-sol", 4000, 3000)],
    )
    world.sandbox_seconds = 48.0

    result = await _run(world)

    assert len(world.author_calls) == 1
    call = world.author_calls[0]
    assert call["source_svgs"] == (SOURCE_SVG,) and call["requirements"] == () and call["max_attempts"] == 1
    assert "gradients or filters" in call["prompt"] and "live text" in call["prompt"]
    assert "at most 12" in call["prompt"] and "1 mm" in call["prompt"]
    assert world.converted[0][0] == REWORKED_SVG
    content = world.published[-1]["content"]
    assert content["reworked"] is True
    codes = [note["code"] for note in content["notes"]]
    assert "solved_gradient_or_filter" in codes and "solved_live_text" in codes
    # 48 s sandbox = 5 credits; 4000/1000 + 3000/100 = 34 token credits.
    assert world.charges[0]["credits"] == 39
    assert result["billing_status"] == "charged"


# contract-test: direct surface=rest_api assertions=design-embroidery.prepare.model-rework-only-when-needed
@pytest.mark.asyncio
async def test_instructions_alone_trigger_rework(world: World) -> None:
    world.author_result = VectorAuthorResult(
        svg=REWORKED_SVG, model_id="openai/gpt-6.1-sol", attempts=1, review_status="skipped",
        usage=[VectorUsage("drawing", "openai/gpt-6.1-sol", 1000, 100)],
    )

    await _run(world, instructions="sew the outline as a thick satin border")

    assert len(world.author_calls) == 1
    assert "sew the outline as a thick satin border" in world.author_calls[0]["prompt"]
    notes = world.published[-1]["content"]["notes"]
    assert any(note["code"] == "instructions_applied" for note in notes)


# contract-test: direct surface=rest_api assertions=design-embroidery.prepare.model-rework-only-when-needed
@pytest.mark.asyncio
@pytest.mark.parametrize("author_result", [
    VectorAuthorError("all models failed"),
    VectorAuthorResult(svg="<svg><text>no viewBox</text></svg>", model_id="m/x", attempts=1, review_status="skipped"),
])
async def test_failed_rework_continues_with_original_and_names_remaining_findings(
    world: World, author_result: Any,
) -> None:
    world.findings = [{"code": "more_than_12_colours", "detail": "18 colours"}]
    world.remaining = [{"code": "more_than_12_colours", "detail": "18 colours"}]
    world.author_result = author_result

    result = await _run(world)

    assert result["status"] == "finished"
    assert world.converted[0][0] == SOURCE_SVG
    content = world.published[-1]["content"]
    assert content["reworked"] is False
    codes = [note["code"] for note in content["notes"]]
    assert "rework_failed" in codes and "unsolved_more_than_12_colours" in codes
    assert world.charges[0]["credits"] == 5


# contract-test: direct surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch,design-embroidery.billing.metered
@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["unreadable_svg", "nothing_to_sew", "too_many_stitches", "timeout", "sandbox_failed"])
async def test_sandbox_errors_deliver_failed_result_without_files_or_charge(world: World, code: str) -> None:
    world.convert_error = EmbroideryError(code, f"plain words for {code}")

    result = await _run(world)

    assert result == {
        "embed_id": EMBED_ID, "child_embed_id": EMBED_ID, "status": "failed", "child_published": True,
        "error": f"plain words for {code}", "error_code": code, "billing_status": "not_charged",
        "input_embed_ids": ["source-embed-1"],
    }
    assert world.charges == [] and world.uploads == {} and world.indexed == []
    content = world.published[-1]["content"]
    assert content["status"] == "error" and content["error_code"] == code and content["files"] == {}


# contract-test: direct surface=rest_api assertions=design-embroidery.result.complete-and-truthful
@pytest.mark.asyncio
async def test_missing_machine_file_is_never_delivered_as_finished(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    original_convert = FakeSession.convert

    async def convert_without_vp3(self: FakeSession, svg: str, options: EmbroideryOptions) -> Any:
        run = await original_convert(self, svg, options)
        run.files.pop("vp3")
        return run

    monkeypatch.setattr(FakeSession, "convert", convert_without_vp3)

    result = await _run(world)

    assert result["status"] == "failed" and result["error_code"] == "sandbox_failed"
    assert world.uploads == {} and world.charges == []


# contract-test: direct surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
@pytest.mark.asyncio
async def test_named_template_is_the_default_and_env_only_overrides_it(
    world: World, monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _run(world)
    monkeypatch.delenv(pipeline.TEMPLATE_ENV, raising=False)
    await _run(world)

    assert [call["template"] for call in world.session_kwargs] == ["embroidery-template-id", EMBROIDERY_TEMPLATE_NAME]
    assert EMBROIDERY_TEMPLATE_NAME == "openmates-embroidery"


# contract-test: direct surface=rest_api assertions=design-embroidery.surface.semantic-parity
@pytest.mark.asyncio
async def test_assistant_result_has_numbers_and_notes_but_no_keys(world: World) -> None:
    from backend.shared.python_utils.generated_media_graph import media_completion_result

    result = await _run(world)
    completion = media_completion_result(result)

    for key in ("width_mm", "height_mm", "stitch_count", "thread_changes", "estimated_minutes",
                "fits_hoop", "threads", "notes", "title"):
        assert key in completion, key
    for secret in ("aes_key", "aes_nonce", "vault_wrapped_aes_key", "s3_base_url", "files"):
        assert secret not in completion
