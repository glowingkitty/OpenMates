"""What a chat-completion push shows, decided server-side before sealing.

Everything returned here that is not generic text is sealed to the device key
(iOS/macOS notification service extension decrypts it); APNs, FCM and push
services only ever see the generic alert and ciphertext.

Layout (owner decision, 27 Nov: the chat and the answer are what matter, not
which Mate answered):

* title: the chat title (one bold line on the iOS lock screen and in macOS
  Notification Center).
* body: the first lines of the answer as plain text (its line breaks kept), as
  many as the 4096-byte APNs payload allows; the last line that only partly
  fits is cut at a word boundary with an ellipsis. iOS shows the first lines
  collapsed and the whole body when expanded.

The user's `push_notification_preferences` switches:

* `includeAnswerText` (default on): the answer excerpt is the body.
* `includeChatTitle` (default on): the chat title is the title; otherwise
  "OpenMates".

Without an excerpt the body is the localized "New message received" text, so
the notification is never empty. Hidden chats never get content notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from backend.core.api.app.services.notification_email_preferences import (
    push_chat_title_enabled,
    push_preview_enabled,
)

GENERIC_PUSH_TITLE = "OpenMates"
CHAT_TITLE_CHARS = 120
# Upper bound before the byte-exact APNs fit; iOS expanded notifications show
# roughly this much, more is cut by the system anyway.
EXCERPT_CHARS = 1200


@dataclass(frozen=True)
class PushContent:
    """`title` is what non-sealing channels show; `sealed_title` (the chat title)
    and `body` (the answer excerpt, empty when off or missing) are sealed to the
    device. `context` is an optional extra last body line, unused for chat replies."""
    title: str
    body: str
    sealed_title: Optional[str]
    context: Optional[str]


def truncate_at_word(text: str, limit: int) -> str:
    """Cut `text` to at most `limit` characters at a word boundary, adding "…".

    Line breaks count as word boundaries, so whole leading lines are kept.
    """
    if len(text) <= limit:
        return text
    if limit <= 1:
        return ""
    cut = text[: limit - 1]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    if boundary >= 0 and not text[limit - 1].isspace():
        head = cut[:boundary]
        # Keep a hard cut for one very long word instead of dropping everything.
        if len(head) >= limit // 2:
            cut = head
    return cut.rstrip(" \n,;:-–—") + "…"


def compose_push_content(
    *, preferences: Any, chat_title: Optional[str], preview_text: str, hidden: bool,
) -> PushContent:
    """Return what to seal, or the generic text when nothing is allowed."""
    if hidden:
        return PushContent(GENERIC_PUSH_TITLE, "", None, None)
    title = " ".join((chat_title or "").split())
    sealed_title = truncate_at_word(title, CHAT_TITLE_CHARS) if title and push_chat_title_enabled(preferences) else None
    body = preview_text.strip() if push_preview_enabled(preferences) and preview_text else ""
    body = truncate_at_word(body, EXCERPT_CHARS)
    return PushContent(sealed_title or GENERIC_PUSH_TITLE, body, sealed_title, None)
