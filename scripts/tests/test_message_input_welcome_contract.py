"""Message input welcome-suppression contract guards.

These tests protect the Svelte predicate that decides whether new-chat welcome
UI stays visible while the composer is focused. The full Playwright coverage
verifies rendered behavior after deploy; this file catches the cheap static
regression where authenticated desktop is accidentally exempted again.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CHAT_PATH = ROOT / "frontend/packages/ui/src/components/ActiveChat.svelte"


def _hide_welcome_expression() -> str:
    source = ACTIVE_CHAT_PATH.read_text(encoding="utf-8")
    match = re.search(r"let\s+hideWelcomeForKeyboard\s*=\s*\$derived\((.*?)\n\s*\);", source, re.S)
    assert match, "hideWelcomeForKeyboard derived expression was not found"
    return re.sub(r"\s+", "", match.group(1))


# contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression
def test_focused_new_chat_welcome_suppression_includes_authenticated_desktop() -> None:
    expression = _hide_welcome_expression()

    assert expression.startswith("messageInputFocused&&("), expression
    assert "showWelcome||" in expression, (
        "Focused new-chat welcome suppression must include authenticated desktop, "
        "not only logged-out or narrow/touch layouts."
    )
    assert "!$authStore.isAuthenticated&&showWelcome" not in expression
