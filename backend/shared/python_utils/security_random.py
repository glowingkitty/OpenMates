"""Shared format-preserving generators for human-transcribed security values.

All selection delegates to secrets.randbelow, which is OS-backed and unbiased.
Callers own their stable prefixes and lengths while sharing canonical variable
alphabets. Existing validators must remain broad enough for historical values.
"""

from __future__ import annotations

from collections.abc import Callable
import secrets


HUMAN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRTUVWXY3468"
HUMAN_DIGIT_ALPHABET = "123456789"


def generate_random_string(
    length: int,
    alphabet: str = HUMAN_CODE_ALPHABET,
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> str:
    if length < 0 or not alphabet or len(set(alphabet)) != len(alphabet):
        raise ValueError("length and alphabet must define a valid random string")
    return "".join(alphabet[randbelow(len(alphabet))] for _ in range(length))


def generate_digit_code(length: int = 6) -> str:
    return generate_random_string(length, HUMAN_DIGIT_ALPHABET)


def generate_grouped_code(
    groups: int,
    group_length: int,
    alphabet: str = HUMAN_CODE_ALPHABET,
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> str:
    if groups <= 0 or group_length <= 0:
        raise ValueError("groups and group length must be positive")
    return "-".join(
        generate_random_string(group_length, alphabet, randbelow=randbelow)
        for _ in range(groups)
    )
