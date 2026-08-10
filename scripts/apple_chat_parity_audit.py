#!/usr/bin/env python3
"""Audit Apple chat-flow scalability and parity guardrails.

This deterministic check protects the Apple chat opening contract before a Mac
simulator run is available. It intentionally checks source-level invariants that
previously regressed: opening a chat must not pass complete per-chat arrays into
ChatView, local offline boot must use bounded windows, and visible chat-flow
identifiers must stay aligned with web data-testid concepts.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import apple_parity_audit


REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_APP = REPO_ROOT / "apple/OpenMates/Sources/App/MainAppView.swift"
CHAT_STORE = REPO_ROOT / "apple/OpenMates/Sources/Core/Persistence/ChatStore.swift"
OFFLINE_STORE = REPO_ROOT / "apple/OpenMates/Sources/Core/Persistence/OfflineStore.swift"
OFFLINE_BRIDGE = REPO_ROOT / "apple/OpenMates/Sources/Core/Persistence/OfflineSyncBridge.swift"
CHAT_VIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"
CHAT_VIEW_MODEL = REPO_ROOT / "apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift"
EMBED_PREVIEW = REPO_ROOT / "apple/OpenMates/Sources/Features/Embeds/Views/EmbedPreviewCard.swift"
CHAT_CSS = REPO_ROOT / "frontend/packages/ui/src/styles/chat.css"
FIELDS_CSS = REPO_ROOT / "frontend/packages/ui/src/styles/fields.css"
UNIFIED_EMBED_PREVIEW = REPO_ROOT / "frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte"
CHAT_RENDERING_ORACLE_SPEC = REPO_ROOT / "frontend/apps/web_app/tests/chat-rendering-parity-oracle.spec.ts"
APPLE_REAL_ACCOUNT_TEST = REPO_ROOT / "apple/OpenMatesUITests/ChatFlowRealAccountUITests.swift"
CHAT_RENDERING_COMPARATOR = REPO_ROOT / "scripts/compare_chat_render_parity.py"
CHAT_RENDERING_PARITY_DOC = REPO_ROOT / "docs/architecture/apple/chat-rendering-parity.md"
APPLE_UI_PARITY_PROGRAM_SPEC = REPO_ROOT / "docs/specs/apple-ui-parity-program/spec.yml"
APPLE_CHAT_UI_CONTRACT_SPEC = REPO_ROOT / "frontend/apps/web_app/tests/apple-chat-ui-contracts.spec.ts"
PARITY_INVENTORY = REPO_ROOT / "test-results/apple-parity-inventory.json"


REQUIRED_IDENTIFIERS = {
    "chat-history-panel": MAIN_APP,
    "message-editor": REPO_ROOT / "apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift",
    "chat-item-wrapper": REPO_ROOT / "apple/OpenMates/Sources/Shared/Components/ChatListRow.swift",
    "embed-preview": REPO_ROOT / "apple/OpenMates/Sources/Features/Embeds/Views/EmbedPreviewCard.swift",
}

ACCESSIBILITY_ID_RE = re.compile(r"accessibilityIdentifier\(\s*([^\n]+?)\s*\)")
STRING_LITERAL_RE = re.compile(r'"([^"]+)"')


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fail(message: str) -> str:
    return f"FAIL: {message}"


def audit_chat_loading() -> list[str]:
    failures: list[str] = []
    main_app = read(MAIN_APP)
    chat_store = read(CHAT_STORE)
    offline_store = read(OFFLINE_STORE)
    offline_bridge = read(OFFLINE_BRIDGE)
    chat_view_model = read(CHAT_VIEW_MODEL)

    if "initialMessages: isPublic ? [] : chatStore.messages(for: chatId)" in main_app:
        failures.append(fail("MainAppView still passes full chatStore.messages(for:) into ChatView"))
    if "initialEmbeds: isPublic ? [] : chatStore.embeds(for: chatId)" in main_app:
        failures.append(fail("MainAppView still passes full chatStore.embeds(for:) into ChatView"))
    if "chatStore.initialMessageWindow(for: chatId)" not in main_app:
        failures.append(fail("MainAppView does not use ChatStore.initialMessageWindow for initial open"))
    if "chatStore.initialEmbedsForVisibleWindow(for: chatId, messages: initialWindow)" not in main_app:
        failures.append(fail("MainAppView does not use lightweight visible-window embeds"))

    for symbol in (
        "initialMessageWindow",
        "olderMessageWindow",
        "initialEmbedsForVisibleWindow",
        "boundedWindowSize",
    ):
        if symbol not in chat_store:
            failures.append(fail(f"ChatStore missing {symbol}"))

    for symbol in ("loadLatestMessageWindow", "loadOlderMessageWindow"):
        if symbol not in offline_store:
            failures.append(fail(f"OfflineStore missing bounded {symbol}"))

    if "offlineStore.loadMessages(chatId:" in offline_bridge:
        failures.append(fail("OfflineSyncBridge cold boot still loads full messages for recent chats"))
    if "offlineStore.loadLatestMessageWindow" not in offline_bridge:
        failures.append(fail("OfflineSyncBridge does not use bounded latest message windows"))

    if "ChatOpeningMetrics" not in chat_view_model:
        failures.append(fail("ChatViewModel missing ChatOpeningMetrics counters"))
    if "rawMessages[start..<rawMessages.count]" in chat_view_model:
        failures.append(fail("ChatViewModel anchored visibleWindow can exceed the configured page size"))

    return failures


def audit_chat_flow_identifiers() -> list[str]:
    failures: list[str] = []
    for identifier, path in REQUIRED_IDENTIFIERS.items():
        source = read(path)
        identifiers = {
            match
            for call in ACCESSIBILITY_ID_RE.findall(source)
            for match in STRING_LITERAL_RE.findall(call)
        }
        if identifier not in identifiers:
            failures.append(fail(f"Missing Apple accessibilityIdentifier matching web data-testid '{identifier}' in {path.relative_to(REPO_ROOT)}"))
    return failures


def audit_forbidden_controls() -> list[str]:
    failures: list[str] = []
    chat_view = read(CHAT_VIEW)
    forbidden_patterns = {
        r"\bForm\s*\(": "Form is forbidden for Apple product UI",
        r"\bList\s*\(": "List is forbidden for Apple product UI",
        r"\.navigationTitle\s*\(": "native navigationTitle is forbidden for Apple product UI",
        r"\.toolbar\s*\(": "native toolbar is forbidden for Apple product UI",
    }
    for pattern, message in forbidden_patterns.items():
        if re.search(pattern, chat_view):
            failures.append(fail(message))
    return failures


def _require(source: str, needle: str, message: str) -> str | None:
    if needle not in source:
        return fail(message)
    return None


def audit_web_to_apple_constants() -> list[str]:
    failures: list[str] = []
    chat_css = read(CHAT_CSS)
    fields_css = read(FIELDS_CSS)
    unified_embed_preview = read(UNIFIED_EMBED_PREVIEW)
    chat_view = read(CHAT_VIEW)
    embed_preview = read(EMBED_PREVIEW)

    checks = [
        (chat_css, "border-radius: 13px;", "Web chat bubble radius is no longer 13px"),
        (chat_css, "padding: 12px;", "Web chat bubble padding is no longer 12px"),
        (chat_css, "filter: drop-shadow(0 4px 4px rgba(0, 0, 0, 0.25));", "Web chat bubble shadow contract changed"),
        (chat_css, "background-color: var(--color-grey-blue);", "Web user bubble color token changed"),
        (chat_css, "background-color: var(--color-grey-0);", "Web assistant bubble color token changed"),
        (chat_css, "max-width: calc(100% - 100px);", "Web desktop user message width cap changed"),
        (chat_css, "max-width: calc(100% - 20px);", "Web compact user message width cap changed"),
        (chat_css, "max-width: calc(100% - 70px);", "Web assistant message width cap changed"),
        (fields_css, "border-radius: 24px;", "Web input radius contract changed"),
        (fields_css, "border-color: var(--color-button-primary);", "Web input focus border token changed"),
        (fields_css, "rgba(255, 85, 59, 0.22)", "Web input focus glow changed"),
        (unified_embed_preview, "Desktop: 300x200px", "Web embed preview desktop size contract changed"),
        (chat_view, "RoundedRectangle(cornerRadius: 13)", "Apple chat bubble radius does not map to web 13px"),
        (chat_view, ".padding(.spacing6)", "Apple chat bubble padding does not map to web 12px/.spacing6"),
        (chat_view, ".background(Color.greyBlue)", "Apple user bubble does not map to web grey-blue token"),
        (chat_view, ".background(Color.grey0)", "Apple assistant bubble does not map to web grey-0 token"),
        (chat_view, ".shadow(color: .black.opacity(0.25), radius: 4, x: 0, y: 4)", "Apple chat bubble shadow does not map to web drop shadow"),
        (embed_preview, "static let compactWidth: CGFloat = 300", "Apple embed preview width does not map to web 300px"),
        (embed_preview, "static let compactHeight: CGFloat = 200", "Apple embed preview height does not map to web 200px"),
        (embed_preview, "static let cornerRadius: CGFloat = 30", "Apple embed preview radius does not map to web card radius"),
    ]
    for source, needle, message in checks:
        failure = _require(source, needle, message)
        if failure:
            failures.append(failure)
    return failures


def audit_loaded_chat_parity_harness() -> list[str]:
    failures: list[str] = []
    required_files = [
        CHAT_RENDERING_ORACLE_SPEC,
        APPLE_REAL_ACCOUNT_TEST,
        CHAT_RENDERING_COMPARATOR,
        CHAT_RENDERING_PARITY_DOC,
    ]
    for path in required_files:
        if not path.exists():
            failures.append(fail(f"Missing loaded-chat parity harness file {path.relative_to(REPO_ROOT)}"))
            return failures

    web_oracle = read(CHAT_RENDERING_ORACLE_SPEC)
    apple_test = read(APPLE_REAL_ACCOUNT_TEST)
    comparator = read(CHAT_RENDERING_COMPARATOR)
    parity_doc = read(CHAT_RENDERING_PARITY_DOC)

    checks = [
        (web_oracle, "surface: 'loaded-user-chats'", "Web oracle no longer exports the loaded-user-chats surface"),
        (web_oracle, "web-loaded-chats-manifest.json", "Web oracle no longer writes the web loaded-chats manifest"),
        (web_oracle, "web-opened-chats-manifest.json", "Web oracle no longer writes the opened-chats manifest"),
        (web_oracle, "opened-user-chats", "Web oracle no longer exports opened-chat rendering parity"),
        (web_oracle, "account_email_hash", "Web oracle no longer records the hashed account identity"),
        (web_oracle, "web-loaded-chats-sidebar.png", "Web oracle no longer captures the loaded-chats screenshot"),
        (apple_test, "testPasswordOtpLoginLoadsRecentChatsForWebParityManifest", "Apple real-account test no longer emits the loaded-chats parity manifest"),
        (apple_test, "apple-loaded-chats-manifest.json", "Apple test no longer writes the loaded-chats manifest"),
        (apple_test, "apple-opened-chats-manifest.json", "Apple test no longer writes the opened-chats manifest"),
        (apple_test, "account_email_hash", "Apple test no longer records the hashed account identity"),
        (apple_test, "CHAT_RENDERING_PARITY_ACCOUNT_SLOT", "Apple parity test no longer supports explicit account-slot selection"),
        (comparator, 'LOADED_CHAT_SURFACE = "loaded-user-chats"', "Comparator no longer validates the loaded-user-chats surface"),
        (comparator, 'OPENED_CHAT_SURFACE = "opened-user-chats"', "Comparator no longer validates the opened-user-chats surface"),
        (comparator, "compare_opened_manifests", "Comparator no longer compares opened-chat render manifests"),
        (comparator, "account mismatch", "Comparator no longer rejects mixed-account manifests"),
        (parity_doc, "chat-rendering-parity-oracle.spec.ts", "Parity doc no longer references the web oracle spec"),
        (parity_doc, "--account 1", "Parity doc no longer documents pinned web account selection"),
        (parity_doc, "CHAT_RENDERING_PARITY_ACCOUNT_SLOT=1", "Parity doc no longer documents pinned Apple account selection"),
        (parity_doc, "compare_chat_render_parity.py", "Parity doc no longer references the comparator"),
    ]
    for source, needle, message in checks:
        failure = _require(source, needle, message)
        if failure:
            failures.append(failure)
    return failures


def audit_program_inventory() -> list[str]:
    failures: list[str] = []
    if not APPLE_UI_PARITY_PROGRAM_SPEC.exists():
        return [fail(f"Missing Apple UI parity program spec {APPLE_UI_PARITY_PROGRAM_SPEC.relative_to(REPO_ROOT)}")]
    if not APPLE_CHAT_UI_CONTRACT_SPEC.exists():
        failures.append(fail(f"Missing broad chat UI contract spec {APPLE_CHAT_UI_CONTRACT_SPEC.relative_to(REPO_ROOT)}"))

    expected_inventory = json.dumps(apple_parity_audit.build_inventory(), indent=2, sort_keys=True) + "\n"
    if not PARITY_INVENTORY.exists():
        failures.append(fail(f"Missing parity inventory {PARITY_INVENTORY.relative_to(REPO_ROOT)}; run scripts/apple_parity_audit.py"))
        return failures
    if PARITY_INVENTORY.read_text(encoding="utf-8") != expected_inventory:
        failures.append(fail(f"Stale parity inventory {PARITY_INVENTORY.relative_to(REPO_ROOT)}; run scripts/apple_parity_audit.py"))
        return failures

    inventory = json.loads(expected_inventory)
    program = inventory.get("programs", {}).get("apple_ui_parity_program")
    if not isinstance(program, dict):
        failures.append(fail("Parity inventory missing programs.apple_ui_parity_program"))
        return failures
    if program.get("spec_path") != "docs/specs/apple-ui-parity-program/spec.yml":
        failures.append(fail("Apple UI parity program inventory points at the wrong spec path"))
    if program.get("first_rollout") != "chat":
        failures.append(fail("Apple UI parity program inventory no longer prioritizes chat first"))

    chat_surfaces = program.get("chat_surfaces")
    if not isinstance(chat_surfaces, list) or not chat_surfaces:
        failures.append(fail("Apple UI parity program inventory has no chat surfaces"))
        return failures

    all_web_specs = {
        web_spec
        for surface in chat_surfaces
        if isinstance(surface, dict)
        for web_spec in surface.get("web_specs", [])
    }
    if "frontend/apps/web_app/tests/apple-chat-ui-contracts.spec.ts" not in all_web_specs:
        failures.append(fail("Chat-first program inventory does not include apple-chat-ui-contracts.spec.ts"))

    ranked_gaps = program.get("ranked_chat_gaps")
    if not isinstance(ranked_gaps, list) or not ranked_gaps:
        failures.append(fail("Apple UI parity program inventory has no ranked chat gaps"))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Apple chat-flow scalability and parity guardrails")
    parser.add_argument("--surface", choices=("chat-flow",), default="chat-flow")
    args = parser.parse_args()

    failures = []
    if args.surface == "chat-flow":
        failures.extend(audit_chat_loading())
        failures.extend(audit_chat_flow_identifiers())
        failures.extend(audit_forbidden_controls())
        failures.extend(audit_web_to_apple_constants())
        failures.extend(audit_loaded_chat_parity_harness())
        failures.extend(audit_program_inventory())

    if failures:
        print("Apple chat parity audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Apple chat parity audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
