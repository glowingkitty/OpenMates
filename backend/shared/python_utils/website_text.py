"""Deterministic website-read quality and bounded, link-preserving text diffs."""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

MAX_PAGE_BYTES = 1_000_000
MAX_DIFF_CHARS = 18_000
_BLOCKED = re.compile(
    r"(?:verify (?:that )?you are human|checking your browser|just a moment[.!]?|"
    r"access denied|enable javascript and cookies to continue|"
    r"(?:complete|solve) (?:the )?captcha|captcha (?:challenge|verification)|"
    r"cloudflare ray id|(?:sign|log) in to (?:continue|view|read|access)|"
    r"accept (?:all )?cookies to continue|consent required)", re.I,
)


def normalize_page_text(text: str) -> str:
    # Preserve markdown links, line order, punctuation and meaningful whitespace.
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def website_read_status(page: dict[str, Any]) -> str:
    status = page.get("http_status")
    if isinstance(status, int) and status >= 400:
        return "blocked" if status in {401, 403, 429} else "failed"
    if page.get("error"):
        return "failed"
    text = page.get("markdown")
    if not isinstance(text, str) or not text.strip():
        return "empty"
    if page.get("warnings") or page.get("partial"):
        return "partial"
    if len(text.encode("utf-8")) > MAX_PAGE_BYTES:
        return "too_large"
    # A phrase inside a genuine article is not sufficient evidence of a block.
    title = str(page.get("title") or "")
    if _BLOCKED.search(title) or title.strip().lower() == "captcha" or (len(text) < 2000 and _BLOCKED.search(text)):
        return "blocked"
    if not re.search(r"\w", text, re.UNICODE):
        return "empty"
    return "usable"


def website_text_diff(previous: str, current: str) -> str:
    diff = "\n".join(difflib.unified_diff(
        previous.splitlines(), current.splitlines(), fromfile="previous page",
        tofile="current page", lineterm="", n=2,
    ))
    if len(diff) > MAX_DIFF_CHARS:
        raise ValueError("WORKFLOW_WEBSITE_DIFF_TOO_LARGE")
    return diff
