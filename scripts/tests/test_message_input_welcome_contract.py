"""Message input workspace-focus contract guards.

The approved composer behavior keeps the workspace measurable while fading and
disabling it for every user. Isolated Playwright coverage verifies the rendered
focus and dismissal transitions; these guards protect the shared predicates.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CHAT_PATH = ROOT / "frontend/packages/ui/src/components/ActiveChat.svelte"
DAILY_INSPIRATION_PATH = ROOT / "frontend/packages/ui/src/components/DailyInspirationBanner.svelte"


def _active_chat_source() -> str:
    return ACTIVE_CHAT_PATH.read_text(encoding="utf-8")


# contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression
def test_focused_workspace_fades_and_disables_controls_for_all_users() -> None:
    source = _active_chat_source()
    workspace = re.search(r'<div\s+class="chat-side"\s+(.*?)\n\s*>', source, re.S)
    assert workspace, "ActiveChat must keep a shared workspace container"
    assert "class:composer-background-faded={messageInputFocused}" in workspace.group(1)
    assert "inert={messageInputFocused}" in workspace.group(1), (
        "Focus must disable the entire workspace for guests and authenticated users"
    )
    assert "const hideWelcomeForKeyboard = false;" in source, (
        "Focus must preserve the welcome layout instead of hiding its content"
    )
    faded_rule = re.search(r"\.composer-background-faded\s*\{([^}]*)\}", source, re.S)
    assert faded_rule, "Focused workspace must define a fading rule"
    declarations = re.sub(r"\s+", "", faded_rule.group(1))
    opacity = re.search(r"opacity:([0-9.]+);", declarations)
    assert opacity and 0 < float(opacity.group(1)) < 1, (
        "Surrounding workspace must stay visible while faded"
    )
    assert "pointer-events:none;" in declarations
    assert "display:none;" not in declarations
    assert "visibility:hidden;" not in declarations


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
    manual_public_preserve = source.index("Preserving public chat after logout")
    assert manual_logout_reset < manual_public_preserve, (
        "Manual logout must reset the composer before a public chat can be preserved"
    )
    assert "isExampleChat(activeChatIdAtLogout) || currentChat?.is_shared_by_others" in source

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


# contract-test: supporting surface=gui.web assertions=daily-inspiration.guest-isolated,landing-onboarding.uses-real-chat-shell
def test_expanded_landing_intro_preserves_measurable_composer_reserve() -> None:
    source = _active_chat_source()
    banner_source = DAILY_INSPIRATION_PATH.read_text(encoding="utf-8")
    rules = re.findall(
        r"\.chat-wrapper\.landing-intro-content-covered\s+\.message-input-wrapper:not\(\.composer-focused\)\s*\{([^}]*)\}",
        source,
        re.S,
    )
    assert rules, "Expanded landing intro must cover only the unfocused composer"
    assert not any("display:none;" in re.sub(r"\s+", "", rule) for rule in rules), (
        "The covered composer must remain measurable so the landing overlay can reserve and cover its height"
    )
    assert 'bind:clientHeight={messageInputWrapperHeight}' in source
    assert 'style:--landing-intro-input-reserve={`${messageInputWrapperHeight}px`}' in source
    assert 'class:composer-focused={messageInputFocused}' in source
    assert 'inert={showWelcome && guestLandingIntroContentCovered && !messageInputFocused}' in source
    assert 'aria-hidden={showWelcome && guestLandingIntroContentCovered && !messageInputFocused}' in source
    assert "{#key guestLandingIntroResetToken}" in source
    assert source.count("resetGuestLandingIntroState();") >= 4
    assert "bottom: calc(0px - var(--landing-intro-input-reserve, 0px));" in banner_source, (
        "The landing intro overlay must extend through the measured composer reserve"
    )


if __name__ == "__main__":
    test_focused_workspace_fades_and_disables_controls_for_all_users()
    test_logout_resets_composer_state_before_restoring_guest_welcome()
    test_expanded_landing_intro_preserves_measurable_composer_reserve()
    print("ActiveChat workspace-focus/logout contracts: PASS")
