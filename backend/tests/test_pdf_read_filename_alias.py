"""PDF read may resolve a CLI filename only through its scoped upload index.

The same module covers the shared OCR-readiness wait the PDF skills use and the
single-flight claim of the OCR task, which need the same offline setup.

These tests execute the skill's lookup and OCR-decryption path with synthetic
cryptographic data. They require no account, provider call, or shared runtime.
"""

from __future__ import annotations

import json
import sys
import types

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import redis.asyncio  # noqa: F401
except ModuleNotFoundError as exc:
    if exc.name not in {"redis", "redis.asyncio"}:
        raise
    redis_stub = types.ModuleType("redis")
    redis_asyncio_stub = types.ModuleType("redis.asyncio")
    redis_stub.asyncio = redis_asyncio_stub
    sys.modules["redis"] = redis_stub
    sys.modules["redis.asyncio"] = redis_asyncio_stub
try:
    import toon_format  # noqa: F401
except ModuleNotFoundError as exc:
    if exc.name != "toon_format":
        raise
    toon_stub = types.ModuleType("toon_format")
    toon_stub.decode = lambda _value: {}  # lookup is isolated below
    sys.modules["toon_format"] = toon_stub

from backend.apps.pdf.skills.read_skill import ReadSkill, _candidate_pdf_upload_refs
from backend.shared.python_utils.pdf_ocr_readiness import (
    PdfNotReadyError,
    PdfProcessingFailedError,
    wait_for_pdf_artefacts,
)


PDF_NAME = "community-garden-budget.pdf"
PDF_REF = "community-garden-budget-pdf-f8af2cbf-93a-5b2dbd"
SECOND_PDF_REF = "community-garden-budget-pdf-aabbccdd-aaa-123abc"


def _skill_with_embeds(monkeypatch: pytest.MonkeyPatch, embeds: dict[str, dict]):
    skill = object.__new__(ReadSkill)
    looked_up: list[tuple[str, str]] = []
    key = AESGCM.generate_key(bit_length=256)
    nonce = b"0123456789ab"
    ocr = json.dumps({"pages": {"1": {"markdown": "Budget total: 1115 EUR"}}}).encode()
    ciphertext = nonce + AESGCM(key).encrypt(nonce, ocr, None)

    async def lookup(embed_id: str, vault_key_id: str) -> dict:
        looked_up.append((embed_id, vault_key_id))
        if vault_key_id != "owner-key" or embed_id not in embeds:
            raise RuntimeError("unavailable")
        return embeds[embed_id]

    async def unwrap(_wrapped: str, vault_key_id: str) -> bytes:
        assert vault_key_id == "owner-key"
        return key

    async def download(_s3_key: str) -> bytes:
        return ciphertext

    monkeypatch.setattr(skill, "_lookup_embed_content", lookup)
    monkeypatch.setattr(skill, "_unwrap_aes_key", unwrap)
    monkeypatch.setattr(skill, "_download_from_s3", download)
    return skill, looked_up


def _pdf_content(ref: str, name: str = PDF_NAME) -> dict:
    return {
        "type": "pdf",
        "filename": name,
        "embed_ref": ref,
        "vault_wrapped_aes_key": "wrapped-test-key",
        "ocr_data_s3_key": "test-ocr",
    }


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_read_resolves_unique_cli_filename_alias_from_owned_upload(monkeypatch):
    skill, looked_up = _skill_with_embeds(monkeypatch, {"owned-pdf": _pdf_content(PDF_REF)})

    result = await skill.execute(
        PDF_NAME,
        pages=[1],
        file_path_index={PDF_REF: "owned-pdf"},
        user_vault_key_id="owner-key",
    )

    assert result["success"] is True
    assert result["pages_returned"] == [1]
    assert "Budget total: 1115 EUR" in result["content"]
    assert looked_up == [("owned-pdf", "owner-key")]


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_exact_embed_ref_still_reads_without_alias_search(monkeypatch):
    skill, looked_up = _skill_with_embeds(monkeypatch, {"owned-pdf": _pdf_content(PDF_REF)})

    result = await skill.execute(
        PDF_REF,
        file_path_index={PDF_REF: "owned-pdf"},
        user_vault_key_id="owner-key",
    )

    assert result["success"] is True
    assert looked_up == [("owned-pdf", "owner-key")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index", "embeds", "vault_key"),
    [
        ({}, {}, "owner-key"),
        ({PDF_REF: "other-file"}, {"other-file": _pdf_content(PDF_REF, "other.pdf")}, "owner-key"),
        ({PDF_REF: "not-pdf"}, {"not-pdf": {**_pdf_content(PDF_REF), "type": "code"}}, "owner-key"),
        ({PDF_REF: "other-owner"}, {"other-owner": _pdf_content(PDF_REF)}, "other-key"),
        (
            {PDF_REF: "first", SECOND_PDF_REF: "second"},
            {
                "first": _pdf_content(PDF_REF),
                "second": _pdf_content(SECOND_PDF_REF),
            },
            "owner-key",
        ),
        ({PDF_REF: "first", SECOND_PDF_REF: "unavailable"}, {"first": _pdf_content(PDF_REF)}, "owner-key"),
        (
            {PDF_REF: "first", SECOND_PDF_REF: "incomplete"},
            {"first": _pdf_content(PDF_REF), "incomplete": {"type": "pdf", "filename": PDF_NAME}},
            "owner-key",
        ),
        (
            {PDF_REF: "first", SECOND_PDF_REF: "malformed"},
            {"first": _pdf_content(PDF_REF), "malformed": ["not metadata"]},
            "owner-key",
        ),
    ],
)
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_filename_alias_rejects_missing_wrong_type_other_owner_and_ambiguous(
    monkeypatch, index, embeds, vault_key
):
    skill, _looked_up = _skill_with_embeds(monkeypatch, embeds)

    result = await skill.execute(
        PDF_NAME,
        file_path_index=index,
        user_vault_key_id=vault_key,
    )

    assert result["success"] is False
    assert result["content"] is None


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_two_verified_uploads_with_same_filename_are_ambiguous(monkeypatch):
    skill, looked_up = _skill_with_embeds(
        monkeypatch,
        {"first": _pdf_content(PDF_REF), "second": _pdf_content(SECOND_PDF_REF)},
    )

    result = await skill.execute(
        PDF_NAME,
        file_path_index={PDF_REF: "first", SECOND_PDF_REF: "second"},
        user_vault_key_id="owner-key",
    )

    assert result["success"] is False
    assert "ambiguous" in result["error"]
    assert looked_up == [("first", "owner-key"), ("second", "owner-key")]


# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
def test_alias_candidates_require_cli_pdf_slug_and_plain_filename():
    assert _candidate_pdf_upload_refs(PDF_NAME, {PDF_REF: "owned-pdf"}) == [(PDF_REF, "owned-pdf")]
    assert _candidate_pdf_upload_refs("../community-garden-budget.pdf", {PDF_REF: "owned-pdf"}) == []
    assert _candidate_pdf_upload_refs("community-garden-budget.docx", {PDF_REF: "owned-pdf"}) == []
    assert _candidate_pdf_upload_refs(PDF_NAME, {"unrelated-pdf-deadbeef-123456": "owned-pdf"}) == []


# --- OCR readiness wait and single-flight OCR task ---
_OCR_READY = {"status": "finished", "ocr_data_s3_key": "chatfiles/x/ocr.bin", "vault_wrapped_aes_key": "vault:v1:k"}
_OCR_PENDING = {"status": "processing", "vault_wrapped_aes_key": "vault:v1:k", "page_count": 150}


class _OCR_FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _OCR_lookup(states: list[dict]):
    calls = {"count": 0}

    async def lookup() -> dict:
        calls["count"] += 1
        return states[min(calls["count"] - 1, len(states) - 1)]

    return lookup, calls


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_ready_embed_costs_no_extra_lookup_or_sleep() -> None:
    clock = _OCR_FakeClock()
    lookup, calls = _OCR_lookup([_OCR_READY])
    result = await wait_for_pdf_artefacts(
        lookup, ("ocr_data_s3_key",), initial=_OCR_READY, sleep=clock.sleep, monotonic=clock.monotonic
    )
    assert result is _OCR_READY
    assert calls["count"] == 0
    assert clock.sleeps == []


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_waits_until_ocr_finishes_then_returns_final_content() -> None:
    clock = _OCR_FakeClock()
    lookup, calls = _OCR_lookup([_OCR_PENDING, _OCR_READY])
    result = await wait_for_pdf_artefacts(
        lookup, ("ocr_data_s3_key", "vault_wrapped_aes_key"), initial=_OCR_PENDING,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert result == _OCR_READY
    assert calls["count"] == 2
    assert clock.sleeps == [2.0, 2.0]


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_reports_processing_failure_without_waiting() -> None:
    clock = _OCR_FakeClock()
    failed = {"status": "error", "error": "PDF processing failed after multiple retries. Your credits have been refunded."}
    lookup, _ = _OCR_lookup([failed])
    with pytest.raises(PdfProcessingFailedError, match="credits have been refunded"):
        await wait_for_pdf_artefacts(
            lookup, ("ocr_data_s3_key",), sleep=clock.sleep, monotonic=clock.monotonic
        )
    assert clock.sleeps == []


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_gives_up_with_actionable_message_after_the_wait_budget() -> None:
    clock = _OCR_FakeClock()
    lookup, _ = _OCR_lookup([_OCR_PENDING])
    with pytest.raises(PdfNotReadyError, match=r"150 pages.*still being processed.*ask again"):
        await wait_for_pdf_artefacts(
            lookup, ("ocr_data_s3_key",), max_wait_seconds=7.0, poll_interval_seconds=2.0,
            sleep=clock.sleep, monotonic=clock.monotonic,
        )
    assert sum(clock.sleeps) == pytest.approx(7.0)


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_view_style_requirement_waits_for_screenshots() -> None:
    clock = _OCR_FakeClock()
    with_ocr_only = {**_OCR_READY, "screenshot_s3_keys": {}}
    with_screens = {**_OCR_READY, "screenshot_s3_keys": {"1": "chatfiles/x/p1.bin"}}
    lookup, _ = _OCR_lookup([with_ocr_only, with_screens])
    result = await wait_for_pdf_artefacts(
        lookup, ("vault_wrapped_aes_key", "screenshot_s3_keys"),
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert result == with_screens


@pytest.mark.parametrize("skill_id", ["read", "search", "view"])
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
def test_pdf_skill_timeout_outlasts_the_ocr_wait(skill_id: str) -> None:
    from backend.apps.ai.processing.skill_executor import get_skill_timeout
    from backend.shared.python_utils.pdf_ocr_readiness import PDF_OCR_MAX_WAIT_SECONDS

    assert get_skill_timeout("pdf", skill_id, {}) > PDF_OCR_MAX_WAIT_SECONDS


class _OCR_FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)


class _OCR_FakeCache:
    def __init__(self, client) -> None:
        self._client = client

    @property
    async def client(self):
        return self._client


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_only_one_task_processes_an_embed_but_its_retry_may_reenter() -> None:
    from backend.apps.pdf.tasks.process_task import _claim_pdf_processing

    cache = _OCR_FakeCache(_OCR_FakeRedis())
    assert await _claim_pdf_processing(cache, "embed-1", "task-a") is True
    assert await _claim_pdf_processing(cache, "embed-1", "task-b") is False
    assert await _claim_pdf_processing(cache, "embed-1", "task-a") is True
    assert await _claim_pdf_processing(cache, "embed-2", "task-b") is True


@pytest.mark.asyncio
# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
async def test_processing_proceeds_when_the_cache_is_unreachable() -> None:
    from backend.apps.pdf.tasks.process_task import _claim_pdf_processing

    assert await _claim_pdf_processing(_OCR_FakeCache(None), "embed-1", "task-a") is True
