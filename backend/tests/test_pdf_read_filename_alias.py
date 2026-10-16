"""PDF read may resolve a CLI filename only through its scoped upload index.

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
