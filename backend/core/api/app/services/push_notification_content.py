"""What a chat-completion push shows, decided server-side before sealing.

Everything returned here that is not generic text is sealed to the device key
(iOS notification service extension decrypts it); APNs, FCM and push services
only ever see the generic alert and ciphertext. The two switches live in the
user's `push_notification_preferences`:

* `includeChatTitle` (default on): title = "<icon> <summary>", body = `in "<chat title>"`.
  Without a summary the title falls back to "<Mate> in <chat title>", and without a
  title to the generic text.
* `includePreview` (default off): the first lines of the answer are added to the body.

Hidden chats never get content notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.core.api.app.services.notification_email_preferences import (
    notification_headline,
    push_chat_title_enabled,
    push_preview_enabled,
)

GENERIC_PUSH_TITLE = "OpenMates"
PREVIEW_CHARS = 160  # about two lines on a phone lock screen


@dataclass(frozen=True)
class PushContent:
    """`body` is the answer preview only (empty unless opted in); `context` and
    `sealed_title` are sealed separately so a chat title is never run through
    the answer-text projection."""
    title: str
    body: str
    sealed_title: Optional[str]
    context: Optional[str]


def _short_preview(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) <= PREVIEW_CHARS:
        return text
    return text[:PREVIEW_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def compose_push_content(
    *, preferences: Any, headline: Optional[str], chat_title: Optional[str],
    mate_name: str, preview_text: str, hidden: bool,
) -> PushContent:
    """Return what to seal, or the generic text when nothing is allowed."""
    if hidden:
        return PushContent(GENERIC_PUSH_TITLE, "", None, None)
    title = " ".join((chat_title or "").split())[:60]
    sealed_title: Optional[str] = None
    context: Optional[str] = None
    if push_chat_title_enabled(preferences):
        if headline:
            sealed_title = headline
            context = f'in "{title}"' if title else None
        elif title:
            sealed_title = notification_headline(mate_name, title) or None
    body = _short_preview(preview_text) if push_preview_enabled(preferences) else ""
    return PushContent(sealed_title or GENERIC_PUSH_TITLE, body, sealed_title, context)
