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


def _active_chat_source() -> str:
    return ACTIVE_CHAT_PATH.read_text(encoding="utf-8")


# contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression
def test_focused_new_chat_welcome_suppression_includes_authenticated_desktop() -> None:
    expression = _hide_welcome_expression()

    assert expression.startswith("messageInputFocused&&("), expression
    assert "showWelcome||" in expression, (
        "Focused new-chat welcome suppression must include authenticated desktop, "
        "not only logged-out or narrow/touch layouts."
    )
    assert "!$authStore.isAuthenticated&&showWelcome" not in expression


# contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,landing-onboarding.uses-real-chat-shell
def test_logout_resets_composer_state_before_restoring_guest_welcome() -> None:
    source = _active_chat_source()
    helper = re.search(
        r"function\s+resetComposerWelcomeState\(clearLiveInput = true\)\s*\{(.*?)\n\s*// Cache the last measured welcome content height",
        source,
        re.S,
    )
    assert helper, "ActiveChat must keep one canonical composer welcome reset helper"
    helper_body = helper.group(1)
    for reset in (
        "messageInputFocused = false",
        "messageInputRecentlyFocused = false",
        "messageInputHasContent = false",
        "messageInputMapsOpen = false",
        "anonymousFileAttachmentPending = false",
        "liveInputText = ''",
        "suggestionsWouldOverlapWelcome = false",
        "assistantSpeechController.stop()",
        "messageInputFieldRef?.clearMessageField(false, false)",
    ):
        assert reset in helper_body, f"Logout composer reset is missing: {reset}"

    manual_logout_reset = source.index("resetComposerWelcomeState();", source.index("Skipping welcome reset after logout"))
    manual_public_preserve = source.index("Preserving static example chat after logout")
    assert manual_logout_reset < manual_public_preserve, (
        "Manual logout must reset the composer before a public example chat can be preserved"
    )

    forced_logout_reset = source.index("resetComposerWelcomeState();", source.index("Logout event received - clearing user chat"))
    forced_public_preserve = source.index("Logout event received while viewing public chat")
    assert forced_logout_reset < forced_public_preserve, (
        "Forced logout must reset the composer before a public chat can be preserved"
    )

    auth_fallback_reset = source.index("resetComposerWelcomeState();", source.index("Auth state changed to unauthenticated - clearing user chat"))
    auth_fallback_clear = source.index("currentChat = null;", auth_fallback_reset)
    assert auth_fallback_reset < auth_fallback_clear, (
        "The unauthenticated fallback must reset composer state before restoring welcome"
    )

    new_chat_reset = source.index("resetComposerWelcomeState(false);", source.index("New chat creation initiated"))
    new_chat_clear = source.index("currentChat = null;", new_chat_reset)
    assert new_chat_reset < new_chat_clear, (
        "New chat creation must reset visual state without deleting the previous chat draft"
    )


# contract-test: supporting surface=gui.web assertions=landing-onboarding.uses-real-chat-shell
def test_expanded_landing_intro_removes_covered_composer_from_layout() -> None:
    source = _active_chat_source()
    rules = re.findall(
        r"\.chat-wrapper\.landing-intro-content-covered\s+\.message-input-wrapper\s*\{([^}]*)\}",
        source,
        re.S,
    )
    assert rules, "Expanded landing intro must define a covered-composer rule"
    assert any("display:none;" in re.sub(r"\s+", "", rule) for rule in rules), (
        "Opacity alone leaves the hidden composer in layout and prevents the logout intro "
        "from covering the complete chat shell"
    )


if __name__ == "__main__":
    test_focused_new_chat_welcome_suppression_includes_authenticated_desktop()
    test_logout_resets_composer_state_before_restoring_guest_welcome()
    test_expanded_landing_intro_removes_covered_composer_from_layout()
    print("ActiveChat welcome/logout contracts: PASS")
