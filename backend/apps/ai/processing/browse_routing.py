"""Deterministic Browse routing for interactive web pages.

Two requests need a real browser even when the bounded routing model does not
pick one: the user hands over a page link and asks to work through it
(fill in a form, sign up, apply, book), and the user answers inside a
conversation whose recent assistant turns already drive a Browse session (the
"fill a form together" flow, one question per turn). Detection is content-free
beyond the latest user text and the embed references of recent assistant turns.
Specification: feature.app-skill.web-browse (dispatch-and-routing, form-with-user).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

BROWSE_SKILL_ID = "web-browse"
# Assistant turns searched for an earlier Browse use. A form flow has turns
# without a Browse call (explaining a question, a value the user types through
# take control, a field left empty), several in a row on a long form, so a short
# window drops Browse mid-form and the model is left without the tool.
RECENT_ASSISTANT_TURNS = 12

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_PAGE_WORK = re.compile(
    r"\b(?:"
    r"fill(?:ing)?\s+(?:(?:it|this|that|them|everything|all)\s+)?(?:out|in)"
    r"|fill\s+(?:out\s+|in\s+)?(?:this|the|my|that)\s+(?:form|survey|questionnaire|application)"
    r"|(?:complete|go\s+through|walk\s+(?:me\s+)?through|work\s+through|answer)\s+"
    r"(?:this|the|that|my)\s+(?:form|survey|questionnaire|application|sign[-\s]?up)"
    r"|(?:form|survey|questionnaire|application)\s+(?:together|with\s+me)"
    r"|sign\s+(?:me\s+)?up|register\s+(?:me|for)|apply\s+(?:for|to)\s+(?:this|it)"
    r")\b",
    re.IGNORECASE,
)
# Raw embed references and their resolved TOON form both name app and skill.
_BROWSE_REF_JSON = re.compile(r'"app_id"\s*:\s*"web"\s*,\s*"skill_id"\s*:\s*"browse"')


def _role_and_content(message: Any) -> tuple[Any, Any, Any]:
    if isinstance(message, dict):
        return message.get("role"), message.get("content"), message.get("sender_name")
    return (getattr(message, "role", None), getattr(message, "content", None),
            getattr(message, "sender_name", None))


def _latest_user_text(message_history: Iterable[Any]) -> str:
    for message in reversed(list(message_history or [])):
        role, content, sender = _role_and_content(message)
        if role == "user" and sender != "async_tool_result" and isinstance(content, str):
            return content
    return ""


def asks_to_work_through_linked_page(text: str) -> bool:
    """True when the text links a web page and asks to fill in or work through it."""
    return bool(text and _URL.search(text) and _PAGE_WORK.search(text))


def _mentions_browse(content: str) -> bool:
    return bool(_BROWSE_REF_JSON.search(content)) or (
        "app_id: web" in content and "skill_id: browse" in content
    )


def recent_browse_session(message_history: Iterable[Any]) -> bool:
    """True when one of the last assistant turns used Browse in this chat."""
    seen = 0
    for message in reversed(list(message_history or [])):
        role, content, _ = _role_and_content(message)
        if role != "assistant":
            continue
        seen += 1
        if isinstance(content, str) and _mentions_browse(content):
            return True
        if seen >= RECENT_ASSISTANT_TURNS:
            break
    return False


def resolve_browse_intent(message_history: Iterable[Any], available_skill_ids: Iterable[str]) -> list[str]:
    """Return ["web-browse"] when the latest turn needs the browser, else []."""
    if BROWSE_SKILL_ID not in set(available_skill_ids or []):
        return []
    history = list(message_history or [])
    if asks_to_work_through_linked_page(_latest_user_text(history)) or recent_browse_session(history):
        return [BROWSE_SKILL_ID]
    return []
