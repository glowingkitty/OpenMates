"""
Bank transfer reference helpers.

SEPA references are copied between OpenMates, banking apps, and operator tools,
so generated codes avoid the most ambiguous glyph pair (`0` and `O`). Lookup
helpers keep matching tolerant for legacy references that used lowercase UUID
fragments and may be uppercased by banks.
"""

from __future__ import annotations

import secrets


BANK_TRANSFER_REFERENCE_ALPHABET = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
AMBIGUOUS_REFERENCE_CHARS = {"0", "O"}
DEFAULT_REFERENCE_SEGMENT_LENGTH = 8


def _random_reference_segment(length: int = DEFAULT_REFERENCE_SEGMENT_LENGTH) -> str:
    return "".join(secrets.choice(BANK_TRANSFER_REFERENCE_ALPHABET) for _ in range(length))


def _safe_static_segment(value: str | None) -> str | None:
    segment = (value or "").strip().upper()
    if not segment or any(char in AMBIGUOUS_REFERENCE_CHARS for char in segment):
        return None
    return segment


def generate_bank_transfer_reference(prefix: str, middle: str | None = None, middle_length: int = 8) -> str:
    """Generate an uppercase human-safe bank-transfer reference."""

    prefix_segment = (prefix or "").strip().upper()
    if not prefix_segment:
        raise ValueError("Bank transfer reference prefix is required")

    middle_segment = _safe_static_segment(middle)
    if not middle_segment:
        middle_segment = _random_reference_segment(max(1, middle_length))
    suffix_segment = _random_reference_segment()
    return f"{prefix_segment}-{middle_segment}-{suffix_segment}"


def bank_transfer_reference_lookup_variants(reference: str) -> list[str]:
    """Return likely case variants for exact-match legacy reference lookup."""

    cleaned = (reference or "").strip()
    if not cleaned:
        return []

    variants: list[str] = []

    def add(value: str) -> None:
        if value and value not in variants:
            variants.append(value)

    add(cleaned)
    add(cleaned.upper())
    add(cleaned.lower())

    parts = cleaned.split("-")
    if len(parts) >= 3:
        add("-".join([parts[0].upper(), *[part.upper() for part in parts[1:-1]], parts[-1].lower()]))
        add("-".join([parts[0].upper(), *[part.lower() for part in parts[1:]]]))

    return variants
