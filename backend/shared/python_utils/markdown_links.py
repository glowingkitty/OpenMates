# backend/shared/python_utils/markdown_links.py
#
# Shared markdown inline-link scanning helpers.
# Keeps backend post-processing aligned with frontend markdown rendering for
# links whose destinations contain balanced parentheses, such as wiki titles.
# Intentionally lightweight: this scans inline link syntax without rendering
# markdown or depending on frontend-only parser behavior.

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class MarkdownLink:
    label: str
    href: str
    full_start: int
    full_end: int
    href_start: int
    href_end: int


def iter_markdown_links(text: str) -> Iterator[MarkdownLink]:
    """Yield inline markdown links, supporting balanced parentheses in hrefs."""
    if not isinstance(text, str) or not text:
        return

    index = 0
    length = len(text)
    while index < length:
        open_label = text.find("[", index)
        if open_label == -1:
            return

        if open_label > 0 and text[open_label - 1] == "\\":
            index = open_label + 1
            continue

        close_label = _find_unescaped(text, "]", open_label + 1)
        if close_label == -1 or close_label + 1 >= length or text[close_label + 1] != "(":
            index = open_label + 1
            continue

        href_start = close_label + 2
        href_end = _find_link_destination_end(text, href_start)
        if href_end == -1:
            index = open_label + 1
            continue

        yield MarkdownLink(
            label=text[open_label + 1:close_label],
            href=text[href_start:href_end],
            full_start=open_label,
            full_end=href_end + 1,
            href_start=href_start,
            href_end=href_end,
        )
        index = href_end + 1


def _find_unescaped(text: str, needle: str, start: int) -> int:
    index = start
    while True:
        found = text.find(needle, index)
        if found == -1:
            return -1
        if found == 0 or text[found - 1] != "\\":
            return found
        index = found + 1


def _find_link_destination_end(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return index
            depth -= 1
        index += 1
    return -1
