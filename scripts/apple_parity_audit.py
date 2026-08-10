#!/usr/bin/env python3
"""Generate a static Apple/web parity inventory.

This script is intentionally Linux-safe: it does not call Xcode, compile Swift,
or require frontend dependencies. It extracts stable web test IDs, Apple
accessibility identifiers, and counterpart paths so parity work can start before
Mac simulator verification is available. The output is factual inventory only;
product priority stays in docs/architecture/apple/*.md.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "test-results" / "apple-parity-inventory.json"

WEB_SPEC_ROOT = REPO_ROOT / "frontend" / "apps" / "web_app" / "tests"
APPLE_SOURCE_ROOT = REPO_ROOT / "apple" / "OpenMates" / "Sources"
COUNTERPARTS_PATH = REPO_ROOT / "apple" / "SVELTE_SWIFT_COUNTERPARTS.md"

GET_BY_TEST_ID_RE = re.compile(r"getByTestId\(\s*['\"]([^'\"]+)['\"]\s*\)")
DATA_TEST_ID_RE = re.compile(r"data-testid\s*=\s*['\"]([^'\"]+)['\"]")
LOCATOR_DATA_TEST_ID_RE = re.compile(r"\[data-testid=['\"]([^'\"]+)['\"]\]")
ACCESSIBILITY_ID_RE = re.compile(r"accessibilityIdentifier\(\s*([^\n]+?)\s*\)")
STRING_LITERAL_RE = re.compile(r'"([^"]+)"')
ACCESSIBILITY_HELP_RE = re.compile(r"\.help\s*\(")
ACCESSIBILITY_LABEL_RE = re.compile(r"\.accessibilityLabel\s*\(")
MARKDOWN_PATH_RE = re.compile(r"`([^`]+\.(?:svelte|css|ts|swift))`")

APPLE_UI_PARITY_PROGRAM_SPEC = "docs/specs/apple-ui-parity-program/spec.yml"
CHAT_FIRST_SURFACES = (
    {
        "surface": "App shell and navigation",
        "matrix_status": "Partial; known visual parity risk",
        "web_sources": (
            "frontend/apps/web_app/src/routes/+page.svelte",
            "frontend/packages/ui/src/components/Header.svelte",
            "frontend/packages/ui/src/components/ChatHistory.svelte",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/App/MainAppView.swift",
            "apple/OpenMates/Sources/App/RootView.swift",
            "apple/OpenMates/Sources/Shared/Components/ChatListRow.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/apple-chat-ui-contracts.spec.ts",
            "frontend/apps/web_app/tests/chat-flow.spec.ts",
            "frontend/apps/web_app/tests/chat-header-navigation-order.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/ChatShellResponsiveParityUITests.swift",
            "apple/OpenMatesUITests/ChatResponsiveParityUITests.swift",
        ),
        "expected_ids": ("sidebar-toggle", "chat-history-panel"),
    },
    {
        "surface": "Chat list/sidebar",
        "matrix_status": "Partial; only chat-item-wrapper overlaps",
        "web_sources": (
            "frontend/packages/ui/src/components/ChatHistory.svelte",
            "frontend/packages/ui/src/components/chats/Chat.svelte",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/App/MainAppView.swift",
            "apple/OpenMates/Sources/Shared/Components/ChatListRow.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/chat-flow.spec.ts",
            "frontend/apps/web_app/tests/show-more-chats-flow.spec.ts",
            "frontend/apps/web_app/tests/hidden-chats-flow.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/ChatFlowParityUITests.swift",
            "apple/OpenMatesUITests/ChatHistoryFullParityUITests.swift",
        ),
        "expected_ids": ("chat-history-panel", "chat-item-wrapper", "chat-item", "group-title", "unread-badge"),
    },
    {
        "surface": "Chat transcript and message bubbles",
        "matrix_status": "Partial; visual parity needs screenshot proof",
        "web_sources": (
            "frontend/packages/ui/src/components/ChatMessage.svelte",
            "frontend/packages/ui/src/components/ReadOnlyMessage.svelte",
            "frontend/packages/ui/src/styles/chat.css",
            "frontend/packages/ui/src/styles/mates.css",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
            "apple/OpenMates/Sources/Shared/Components/RichMarkdownRenderer.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/chat-rendering-parity-oracle.spec.ts",
            "frontend/apps/web_app/tests/apple-chat-history-contracts.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/ChatFlowParityUITests.swift",
            "apple/OpenMatesTests/ChatHistoryRenderDocumentTests.swift",
        ),
        "expected_ids": ("message-user", "mate-message-content", "user-message-content", "mate-profile", "chat-mate-name"),
    },
    {
        "surface": "Message input/composer",
        "matrix_status": "Partial; main message-editor parity needs continued coverage",
        "web_sources": (
            "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
            "frontend/packages/ui/src/components/enter_message/ActionButtons.svelte",
            "frontend/packages/ui/src/components/enter_message/RecordAudio.svelte",
            "frontend/packages/ui/src/styles/fields.css",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
            "apple/OpenMates/Sources/Features/Chat/Views/InputActionButtons.swift",
            "apple/OpenMates/Sources/Features/Chat/Views/AttachmentPicker.swift",
            "apple/OpenMates/Sources/Features/Chat/Views/VoiceRecordingView.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/apple-ui-contracts.spec.ts",
            "frontend/apps/web_app/tests/file-attachment-flow.spec.ts",
            "frontend/apps/web_app/tests/audio-recording.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/MessageInputAttachmentUITests.swift",
            "apple/OpenMatesUITests/MessageInputAudioRecordingUITests.swift",
        ),
        "expected_ids": ("message-editor", "embed-preview", "welcome-message-input", "welcome-send-button"),
    },
    {
        "surface": "Chat management",
        "matrix_status": "Partial or unknown",
        "web_sources": (
            "frontend/packages/ui/src/components/MessageContextMenu.svelte",
            "frontend/packages/ui/src/components/ChatHeader.svelte",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/Features/Chat/Views/ChatContextMenu.swift",
            "apple/OpenMates/Sources/Features/Chat/Views/MessageContextMenu.swift",
            "apple/OpenMates/Sources/Features/Chat/ViewModels/ChatViewModel.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/chat-management-flow.spec.ts",
            "frontend/apps/web_app/tests/hidden-chats-flow.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/ChatManagementSharingParityUITests.swift",
        ),
        "expected_ids": ("chat-context-delete", "chat-context-pin", "chat-context-hide", "chat-context-mark-read"),
    },
    {
        "surface": "Search",
        "matrix_status": "Parity candidate for entry point; unknown detail parity",
        "web_sources": (
            "frontend/packages/ui/src/components/ChatSearch.svelte",
            "frontend/packages/ui/src/components/Header.svelte",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/Features/Chat/Views/ChatSearchView.swift",
            "apple/OpenMates/Sources/App/MainAppView.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/chat-search-flow.spec.ts",
            "frontend/apps/web_app/tests/search-parent-preview-stress.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesUITests/ChatFlowParityUITests.swift",
        ),
        "expected_ids": ("search-button",),
    },
    {
        "surface": "Offline/sync/resilience",
        "matrix_status": "Functional risk",
        "web_sources": (
            "frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts",
            "frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts",
        ),
        "apple_sources": (
            "apple/OpenMates/Sources/Core/Persistence/OfflineStore.swift",
            "apple/OpenMates/Sources/Core/Persistence/OfflineSyncBridge.swift",
            "apple/OpenMates/Sources/Core/Networking/WebSocketManager.swift",
        ),
        "web_specs": (
            "frontend/apps/web_app/tests/message-sync.spec.ts",
            "frontend/apps/web_app/tests/connection-resilience.spec.ts",
        ),
        "native_tests": (
            "apple/OpenMatesTests/ChatSyncParityTests.swift",
            "apple/OpenMatesTests/ChatCompletionRecoveryTests.swift",
        ),
        "expected_ids": (),
    },
)

HELP_AUDIT_ROOTS = (
    APPLE_SOURCE_ROOT / "App",
    APPLE_SOURCE_ROOT / "Features",
    APPLE_SOURCE_ROOT / "Shared" / "Components",
    APPLE_SOURCE_ROOT / "Shared" / "Extensions",
)
HELP_HELPER_PATHS = {
    APPLE_SOURCE_ROOT / "Shared" / "Extensions" / "AccessibilityModifiers.swift",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


def extract_web_test_ids() -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for path in sorted(WEB_SPEC_ROOT.rglob("*.spec.ts")):
        text = read_text(path)
        ids = []
        ids.extend(GET_BY_TEST_ID_RE.findall(text))
        ids.extend(DATA_TEST_ID_RE.findall(text))
        ids.extend(LOCATOR_DATA_TEST_ID_RE.findall(text))
        if ids:
            by_file[repo_path(path)] = unique_sorted(ids)
    return by_file


def extract_apple_accessibility_ids() -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    for path in sorted(APPLE_SOURCE_ROOT.rglob("*.swift")):
        ids = [identifier for call in ACCESSIBILITY_ID_RE.findall(read_text(path)) for identifier in STRING_LITERAL_RE.findall(call)]
        if ids:
            by_file[repo_path(path)] = unique_sorted(ids)
    return by_file


def extract_apple_help_usage() -> dict[str, list[int]]:
    by_file: dict[str, list[int]] = {}
    for root in HELP_AUDIT_ROOTS:
        for path in sorted(root.rglob("*.swift")):
            lines = read_text(path).splitlines()
            help_lines = [index for index, line in enumerate(lines, start=1) if ACCESSIBILITY_HELP_RE.search(line)]
            if help_lines:
                by_file[repo_path(path)] = help_lines
    return by_file


def extract_apple_missing_help_candidates() -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for root in HELP_AUDIT_ROOTS:
        for path in sorted(root.rglob("*.swift")):
            if path in HELP_HELPER_PATHS:
                continue
            lines = read_text(path).splitlines()
            for index, line in enumerate(lines):
                if not ACCESSIBILITY_LABEL_RE.search(line):
                    continue

                start = max(0, index - 8)
                modifier_end = min(len(lines), index + 4)
                help_window = "\n".join(lines[start:modifier_end])
                interactive_window = "\n".join(lines[start : index + 1])
                if (
                    ".help(" in help_window
                    or ".accessibleButton(" in help_window
                    or ".accessibleToggle(" in help_window
                    or ".accessibleEmbed(" in help_window
                ):
                    continue

                interactive = (
                    "Button" in interactive_window
                    or ".buttonStyle" in interactive_window
                    or ".accessibilityAddTraits(.isButton)" in interactive_window
                    or ".accessibilityAddTraits(.isToggle)" in interactive_window
                )
                if not interactive:
                    continue

                candidates.append(
                    {
                        "file": repo_path(path),
                        "line": index + 1,
                        "source": line.strip(),
                    }
                )
    return candidates


def extract_counterpart_paths() -> dict[str, object]:
    if not COUNTERPARTS_PATH.exists():
        return {
            "path": repo_path(COUNTERPARTS_PATH),
            "exists": False,
            "web_paths": [],
            "swift_paths": [],
            "missing_paths": [],
        }

    text = read_text(COUNTERPARTS_PATH)
    paths = unique_sorted(MARKDOWN_PATH_RE.findall(text))
    web_paths = [p for p in paths if p.endswith((".svelte", ".css", ".ts"))]
    swift_paths = [p for p in paths if p.endswith(".swift")]
    missing_paths = [p for p in paths if not (REPO_ROOT / p).exists()]
    return {
        "path": repo_path(COUNTERPARTS_PATH),
        "exists": True,
        "web_paths": web_paths,
        "swift_paths": swift_paths,
        "missing_paths": missing_paths,
    }


def flatten_values(mapping: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    for items in mapping.values():
        values.extend(items)
    return unique_sorted(values)


def path_matches(pattern: str) -> list[str]:
    path = REPO_ROOT / pattern
    if any(char in pattern for char in "*?[]"):
        return [repo_path(match) for match in sorted(REPO_ROOT.glob(pattern)) if match.exists()]
    if path.exists():
        return [pattern]
    return []


def missing_paths(patterns: Iterable[str]) -> list[str]:
    return [pattern for pattern in patterns if not path_matches(pattern)]


def surface_gap_types(surface: dict[str, object], web_ids: set[str], apple_ids: set[str]) -> list[str]:
    gap_types: list[str] = []
    web_sources = surface["web_sources"]  # type: ignore[index]
    apple_sources = surface["apple_sources"]  # type: ignore[index]
    web_specs = surface["web_specs"]  # type: ignore[index]
    native_tests = surface["native_tests"]  # type: ignore[index]
    expected_ids = set(surface["expected_ids"])  # type: ignore[index]

    if missing_paths(web_sources):
        gap_types.append("missing_web_source")
    if missing_paths(apple_sources):
        gap_types.append("missing_apple_source")
    if missing_paths(web_specs):
        gap_types.append("missing_web_spec")
    if missing_paths(native_tests):
        gap_types.append("missing_native_test")
    if expected_ids and expected_ids - apple_ids:
        gap_types.append("testability_gap")
    if expected_ids and not expected_ids & web_ids:
        gap_types.append("missing_web_selector_signal")
    if "Visual" in str(surface.get("matrix_status", "")) or "visual" in str(surface.get("matrix_status", "")):
        gap_types.append("visual_review_needed")
    if "Functional" in str(surface.get("matrix_status", "")) or "Functional risk" in str(surface.get("matrix_status", "")):
        gap_types.append("functional_review_needed")

    return unique_sorted(gap_types)


def build_chat_first_program_inventory(
    web_ids_by_file: dict[str, list[str]],
    apple_ids_by_file: dict[str, list[str]],
) -> dict[str, object]:
    web_ids = set(flatten_values(web_ids_by_file))
    apple_ids = set(flatten_values(apple_ids_by_file))
    chat_surfaces: list[dict[str, object]] = []

    for priority, surface in enumerate(CHAT_FIRST_SURFACES, start=1):
        expected_ids = set(surface["expected_ids"])  # type: ignore[index]
        gap_types = surface_gap_types(surface, web_ids, apple_ids)
        web_sources = tuple(surface["web_sources"])  # type: ignore[index]
        apple_sources = tuple(surface["apple_sources"])  # type: ignore[index]
        web_specs = tuple(surface["web_specs"])  # type: ignore[index]
        native_tests = tuple(surface["native_tests"])  # type: ignore[index]
        missing_expected_ids = sorted(expected_ids - apple_ids)

        chat_surfaces.append(
            {
                "surface": surface["surface"],
                "priority": priority,
                "matrix_status": surface["matrix_status"],
                "web_sources": list(web_sources),
                "apple_sources": list(apple_sources),
                "web_specs": list(web_specs),
                "native_tests": list(native_tests),
                "expected_ids": sorted(expected_ids),
                "expected_ids_present_on_web": sorted(expected_ids & web_ids),
                "expected_ids_present_on_apple": sorted(expected_ids & apple_ids),
                "expected_ids_missing_on_apple": missing_expected_ids,
                "missing_web_sources": missing_paths(web_sources),
                "missing_apple_sources": missing_paths(apple_sources),
                "missing_web_specs": missing_paths(web_specs),
                "missing_native_tests": missing_paths(native_tests),
                "gap_types": gap_types,
                "blocking_gap_count": len([gap for gap in gap_types if gap != "visual_review_needed"]),
            }
        )

    ranked_gaps = sorted(
        chat_surfaces,
        key=lambda item: (-int(item["blocking_gap_count"]), int(item["priority"])),
    )

    return {
        "id": "apple-ui-parity-program",
        "spec_path": APPLE_UI_PARITY_PROGRAM_SPEC,
        "first_rollout": "chat",
        "gate_policy": {
            "blocking_from_start": [
                "missing_mapping",
                "missing_required_identifier",
                "missing_fixture",
                "stale_fixture",
                "missing_native_test",
                "missing_known_renderer",
                "forbidden_generic_fallback",
                "broken_behavior",
                "structural_order_drift",
            ],
            "warning_from_start": [
                "unpromoted_visual_style_drift",
            ],
        },
        "chat_surfaces": chat_surfaces,
        "ranked_chat_gaps": [
            {
                "surface": item["surface"],
                "priority": item["priority"],
                "blocking_gap_count": item["blocking_gap_count"],
                "gap_types": item["gap_types"],
                "expected_ids_missing_on_apple": item["expected_ids_missing_on_apple"],
            }
            for item in ranked_gaps
        ],
        "next_surface_queue": [
            "Settings main and sub-pages",
            "Auth login/signup/recovery",
            "Billing/payments",
            "Embeds preview/fullscreen",
        ],
    }


def build_inventory() -> dict[str, object]:
    web_ids_by_file = extract_web_test_ids()
    apple_ids_by_file = extract_apple_accessibility_ids()
    web_ids = flatten_values(web_ids_by_file)
    apple_ids = flatten_values(apple_ids_by_file)
    shared_ids = sorted(set(web_ids) & set(apple_ids))
    apple_help_usage = extract_apple_help_usage()
    apple_missing_help_candidates = extract_apple_missing_help_candidates()

    web_components = sorted((REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "components").rglob("*.svelte"))
    web_routes = sorted((REPO_ROOT / "frontend" / "apps" / "web_app" / "src" / "routes").rglob("*.svelte"))
    apple_feature_swift = sorted((REPO_ROOT / "apple" / "OpenMates" / "Sources" / "Features").rglob("*.swift"))
    apple_app_swift = sorted((REPO_ROOT / "apple" / "OpenMates" / "Sources" / "App").rglob("*.swift"))

    return {
        "counts": {
            "web_svelte_components": len(web_components),
            "web_svelte_routes": len(web_routes),
            "web_playwright_specs": len(list(WEB_SPEC_ROOT.rglob("*.spec.ts"))),
            "web_unique_test_ids": len(web_ids),
            "apple_feature_swift_files": len(apple_feature_swift),
            "apple_app_swift_files": len(apple_app_swift),
            "apple_unique_accessibility_ids": len(apple_ids),
            "apple_accessibility_help_calls": sum(len(lines) for lines in apple_help_usage.values()),
            "apple_missing_help_candidates": len(apple_missing_help_candidates),
            "shared_ids": len(shared_ids),
        },
        "web_test_ids": {
            "all": web_ids,
            "by_file": web_ids_by_file,
        },
        "apple_accessibility_ids": {
            "all": apple_ids,
            "by_file": apple_ids_by_file,
        },
        "apple_accessibility_help": {
            "by_file": apple_help_usage,
            "missing_candidates": apple_missing_help_candidates,
        },
        "shared_ids": shared_ids,
        "web_ids_missing_on_apple": sorted(set(web_ids) - set(apple_ids)),
        "apple_ids_not_used_by_web_specs": sorted(set(apple_ids) - set(web_ids)),
        "counterparts": extract_counterpart_paths(),
        "programs": {
            "apple_ui_parity_program": build_chat_first_program_inventory(web_ids_by_file, apple_ids_by_file),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Apple/web parity inventory JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--check", action="store_true", help="Do not write; fail if output is stale or missing.")
    parser.add_argument("--audit-help", action="store_true", help="Fail if interactive Apple controls with accessibility labels lack .help(...).")
    args = parser.parse_args()

    inventory = build_inventory()
    if args.audit_help:
        candidates = inventory["apple_accessibility_help"]["missing_candidates"]  # type: ignore[index]
        if candidates:
            print("Apple accessibility help audit failed:")
            for candidate in candidates:
                print(f"- {candidate['file']}:{candidate['line']} {candidate['source']}")
            return 1
        print("Apple accessibility help audit passed")
        return 0

    serialized = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output

    if args.check:
        if not output.exists():
            print(f"Missing parity inventory: {output}")
            return 1
        current = read_text(output)
        if current != serialized:
            print(f"Stale parity inventory: {output}")
            return 1
        print(f"Parity inventory is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized, encoding="utf-8")
    print(f"Wrote {display_path(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
