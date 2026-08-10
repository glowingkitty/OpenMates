"""Verify format-preserving security code generation across backend surfaces.

The tests pin approved alphabets and issuance shapes while retaining exact
legacy verification for historical values containing 0 or uppercase O. They
also invoke the repository audit that guards non-Python client implementations
and documents protocol-controlled randomness exemptions.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import audit_crypto_randomness
from backend.shared.python_utils.security_random import (
    HUMAN_CODE_ALPHABET,
    HUMAN_DIGIT_ALPHABET,
    generate_grouped_code,
    generate_random_string,
)
from scripts.audit_crypto_randomness import audit_human_code_randomness


ROOT = Path(__file__).resolve().parents[2]


def test_shared_generators_preserve_shapes_and_approved_alphabets() -> None:
    def highest_index(upper_bound: int) -> int:
        return upper_bound - 1

    assert generate_random_string(7, HUMAN_CODE_ALPHABET, randbelow=highest_index) == "8" * 7
    assert generate_random_string(6, HUMAN_DIGIT_ALPHABET, randbelow=highest_index) == "9" * 6
    assert generate_grouped_code(3, 4, HUMAN_CODE_ALPHABET, randbelow=highest_index) == "8888-8888-8888"
    assert "0" not in HUMAN_CODE_ALPHABET + HUMAN_DIGIT_ALPHABET
    assert "O" not in HUMAN_CODE_ALPHABET + HUMAN_DIGIT_ALPHABET


def test_backup_codes_use_unambiguous_shape_and_legacy_hashes_still_verify() -> None:
    source = (ROOT / "backend/core/api/app/routes/auth_routes/auth_2fa_utils.py").read_text(encoding="utf-8")
    generated = generate_grouped_code(3, 4, HUMAN_CODE_ALPHABET, randbelow=lambda upper_bound: upper_bound - 1)

    assert re.fullmatch(r"[ABCDEFGHJKLMNPQRTUVWXY3468]{4}(?:-[ABCDEFGHJKLMNPQRTUVWXY3468]{4}){2}", generated)
    assert "argon2_hasher.verify(hashed_code, code)" in source
    assert ".upper()" not in source
    assert ".replace(" not in source


def test_human_code_randomness_audit_has_no_findings() -> None:
    assert audit_human_code_randomness() == []


def test_randomness_audit_rejects_missing_rejection_guard(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "biased_sampler.ts"
    source_path.write_text("const value = randomByte % alphabet.length;", encoding="utf-8")
    monkeypatch.setattr(audit_crypto_randomness, "HUMAN_CODE_RULES", {})
    monkeypatch.setattr(
        audit_crypto_randomness,
        "REJECTION_SAMPLING_RULES",
        {"biased_sampler.ts": ("maxUnbiasedValue", "value < maxUnbiasedValue")},
    )

    assert audit_crypto_randomness.audit_human_code_randomness(tmp_path) == [
        "biased_sampler.ts:rejection_sampling_guard_missing"
    ]
