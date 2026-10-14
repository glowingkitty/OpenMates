"""Shared checks for code fences that should stay inline."""

import re


MIN_CODE_EMBED_CONTENT_LENGTH = 20


def _is_code_block_too_short_for_embed(code_content: str) -> bool:
    return len(code_content.strip()) < MIN_CODE_EMBED_CONTENT_LENGTH


def _is_example_only_code_block(code_content: str) -> bool:
    stripped = code_content.strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    if "example usage" in lowered and not re.search(r"\b(def|class)\b", lowered):
        return True

    non_comment_lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return (
        len(non_comment_lines) <= 2
        and any("print(" in line for line in non_comment_lines)
        and not any(re.search(r"\b(def|class)\b", line) for line in non_comment_lines)
    )


def _should_skip_code_block_for_embed(code_content: str) -> bool:
    return _is_code_block_too_short_for_embed(code_content) or _is_example_only_code_block(code_content)
