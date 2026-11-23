"""Short Discord push text: cleaning, length limits and the shortening fallback chain.

Discord pushes must fit on a phone lock screen. The chat writes the short text itself; this module
only enforces the limit:

1. ``clean_text`` removes what never belongs in a push: markdown, icons the chat wrote itself (the
   caller adds exactly one), Task and chat ids, commit hashes and list markers.
2. ``fit`` accepts text within the limit. Longer text is rejected with ``SummaryTooLong`` (an
   instruction to rewrite it) for the first ``MAX_REJECTIONS`` attempts; after that one cheap
   LLM call shortens it (``shorten`` callback, platform cost), and if that fails or stays too long
   the text is cut at a word boundary with "…". Nothing is ever truncated silently before that.
3. ``alert`` builds the one-line pushes of scripts that compose their own text (production
   monitoring): icon plus cleaned text, cut at a word boundary.

Limits are in characters after the title prefix; a link counts as one character.
Callers: scripts/agent_question.py, scripts/prod_email_health.py, scripts/prod_tls_health.py.
"""

from __future__ import annotations

import re
from typing import Callable

SUMMARY_MAX = 110  # one done sentence; the lock screen shows about 140 characters with icon and title
ASK_MAX = 120  # question and recommendation together
ALERT_MAX = 140  # monitoring pushes, including the icon
TITLE_MAX = 30
MAX_REJECTIONS = 2
ICONS = ("✅", "❓", "🚨", "⚠️", "⚠", "✔️", "✔", "☑️", "❗", "❌", "🔴", "🟢")
_LINK_MARK = 0xF0000  # private use plane: one character per link while counting and cutting
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_HASH = re.compile(r"\b(?:[0-9a-f]{40}|[0-9a-f]{64}|(?=[0-9a-f]*\d)[0-9a-f]{7,12}(?=\s|[,.;)]|$))\b")
_TASK_ID = re.compile(r"\b(?:TASK|ISSUE|PR)[-\s#]*\d+\b|(?<!\w)#\d+\b", re.I)
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_LINK_MD = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_TITLE_TASK_PREFIX = re.compile(r"^\s*(?:TASK[-\s#]*\d+|[0-9a-f]{8}-[0-9a-f-]{27})\s*[:\-–—]*\s*", re.I)


class SummaryTooLong(ValueError):
    """The text is over the limit; the message tells the chat how to rewrite it."""


class ShortenFailed(RuntimeError):
    """The shortening LLM call failed or returned unusable text."""


def _protect_links(text: str) -> tuple[str, list[str]]:
    links: list[str] = []

    def hold(match: re.Match[str]) -> str:
        links.append(match.group(0))
        return chr(_LINK_MARK + len(links) - 1)

    return _URL.sub(hold, text), links


def _restore_links(text: str, links: list[str]) -> str:
    return "".join(links[ord(c) - _LINK_MARK] if _LINK_MARK <= ord(c) < _LINK_MARK + len(links) else c
                   for c in text)


def strip_icons(text: str) -> str:
    """Remove status icons anywhere, so the one the caller adds is never doubled."""
    for icon in ICONS:
        text = text.replace(icon, " ")
    return text


def clean_text(text: str, title: str = "") -> str:
    """Plain one-line text: no markdown, icons, ids, hashes, list markers or repeated title prefix."""
    text, links = _protect_links(text)
    text = _LIST_MARKER.sub("", text)
    text = _LINK_MD.sub(r"\1", text)
    text = re.sub(r"[`*_~]{1,3}(?=\S)|(?<=\S)[`*_~]{1,3}", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = strip_icons(text)
    for pattern in (_UUID, _TASK_ID, _HASH):
        text = re.sub(r"(?i)(?:\b(?:see|task|chat|commit|issue)\s+)?" + pattern.pattern, "", text)
    text = re.sub(r"\(\s*[,;\s]*\)", "", text)  # parentheses emptied by removed ids
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)  # separators left behind by removed ids
    text = re.sub(r"[,;:]+(?=[.!?]*$)", "", text).strip(" ,;:-–—")
    head = " ".join(clean_title_text(title).split()).lower()
    if head and text.lower().startswith(head + ":"):
        text = text[len(head) + 1:].strip()
    return _restore_links(text, links)


def clean_title_text(title: str) -> str:
    """A chat title without a leading Task id or UUID."""
    return _TITLE_TASK_PREFIX.sub("", strip_icons(title)).strip()


def counted_length(text: str) -> int:
    """Characters on screen: a link counts as one."""
    return len(_protect_links(text)[0])


def cut(text: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word boundary with "…" (a link counts as one)."""
    marked, links = _protect_links(text)
    if len(marked) > limit:
        space = marked.rfind(" ", 0, limit)
        marked = marked[:space if space > 0 else limit - 1].rstrip(" ,;:-–—") + "…"
    return _restore_links(marked, links)


def short_title(title: str, limit: int = TITLE_MAX) -> str:
    """The chat title for the push prefix: Task id removed, cut at a word boundary to ``limit``."""
    return cut(" ".join(clean_title_text(title).split()) or "unnamed chat", limit)


def rejection_message(length: int, limit: int, what: str) -> str:
    return (f"{what} is {length} characters: rewrite it in under {limit} characters, one sentence in plain "
            "words (no markdown, no ids, no lists, no details; details belong in the chat and its Task), "
            "then run the command again.")


def fit(text: str, limit: int, *, rejections: int, shorten: Callable[[str, int], str] | None = None,
        what: str = "the push text", note: Callable[[str], None] = lambda _: None) -> str:
    """Text within ``limit``: accepted as is, rejected for a rewrite, or shortened (see module doc).

    ``rejections`` is how many times this chat already got a rejection for this push. ``shorten``
    is the cheap LLM call (text, limit) -> shorter text; ``note`` receives one line about the fallback used."""
    length = counted_length(text)
    if length <= limit:
        return text
    if rejections < MAX_REJECTIONS:
        raise SummaryTooLong(rejection_message(length, limit, what))
    if shorten is not None:
        try:
            shorter = clean_text(shorten(text, limit))
        except ShortenFailed as error:
            note(f"shortening model unavailable ({error}); cutting at a word boundary")
        else:
            if shorter and counted_length(shorter) <= limit:
                note("shortened by the fallback model")
                return shorter
            note("shortening model result unusable; cutting at a word boundary")
    return cut(text, limit)


def alert(icon: str, text: str, limit: int = ALERT_MAX) -> str:
    """One-line alert push for scripts that compose their own text: '<icon> <text>' within ``limit``."""
    return f"{icon} {cut(clean_text(text), limit - len(icon) - 1)}"
