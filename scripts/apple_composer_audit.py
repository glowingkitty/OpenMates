#!/usr/bin/env python3
"""Guard every Apple composer host against WebView regressions.

The rendered web MessageInput remains the visual and behavioral source of truth,
but Apple editing is implemented with the shared native TextKit 2 contract.
This path-scoped audit permits unrelated embed WKWebViews while rejecting any
composer bridge, bundled Tiptap runtime, or bespoke product-host editor fork.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSER_WEBVIEW = re.compile(r"\b(WKWebView|TiptapComposerWebView|WKScriptMessageHandler)\b")


@dataclass(frozen=True)
class SurfaceRule:
    path: Path
    required_tokens: tuple[str, ...]
    forbidden_patterns: tuple[re.Pattern[str], ...]
    description: str


SURFACES = (
    SurfaceRule(
        Path("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"),
        ("MessageComposerView",),
        (COMPOSER_WEBVIEW,),
        "main chat composer",
    ),
    SurfaceRule(
        Path("apple/OpenMates/Sources/App/MainAppView.swift"),
        ("MessageComposerView",),
        (COMPOSER_WEBVIEW,),
        "new-chat composer",
    ),
    SurfaceRule(
        Path("apple/OpenMates/Sources/App/OpenMatesApp.swift"),
        ("MessageComposerView", "quick-capture-composer"),
        (COMPOSER_WEBVIEW,),
        "quick-capture composer",
    ),
    SurfaceRule(
        Path("apple/OpenMatesShareExtension/ShareViewController.swift"),
        ("NativeComposerSession", "NativeComposerTextView", "share-extension-message-input"),
        (COMPOSER_WEBVIEW,),
        "iOS share composer",
    ),
    SurfaceRule(
        Path("apple/OpenMatesShareExtensionMacOS/MacShareViewController.swift"),
        ("NativeComposerSession", "NativeComposerTextView", "share-extension-message-input"),
        (COMPOSER_WEBVIEW,),
        "macOS share composer",
    ),
)

REMOVED_ARTIFACTS = (
    Path("apple/OpenMates/Sources/Shared/Components/TiptapComposerWebView.swift"),
    Path("apple/OpenMates/Resources/TiptapComposer"),
    Path("apple/OpenMatesTests/TiptapComposerBridgeTests.swift"),
)


def forbidden_webview_matches(text: str) -> list[str]:
    """Return forbidden composer-webview symbols for focused fixture tests."""
    return [match.group(1) for match in COMPOSER_WEBVIEW.finditer(text)]


def _read(root: Path, path: Path) -> str:
    full_path = root / path
    if not full_path.exists():
        raise FileNotFoundError(f"Missing expected surface file: {path}")
    return full_path.read_text(encoding="utf-8")


def audit(root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    shared_field = Path("apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift")
    native_bridge = Path("apple/OpenMates/Sources/Shared/Composer/NativeComposerTextView.swift")
    project = Path("apple/OpenMates.xcodeproj/project.pbxproj")

    for path, token in (
        (shared_field, "NativeComposerEditorView"),
        (native_bridge, "usingTextLayoutManager: true"),
    ):
        try:
            text = _read(root, path)
        except FileNotFoundError as exc:
            failures.append(str(exc))
            continue
        if token not in text:
            failures.append(f"{path}: shared native composer must reference {token!r}")
        for symbol in forbidden_webview_matches(text):
            failures.append(f"{path}: shared native composer contains forbidden {symbol}")

    for path in REMOVED_ARTIFACTS:
        full_path = root / path
        contains_artifact = full_path.is_file() or (
            full_path.is_dir() and any(candidate.is_file() for candidate in full_path.rglob("*"))
        )
        if contains_artifact:
            failures.append(f"Removed composer WebView artifact exists: {path}")

    try:
        project_text = _read(root, project)
    except FileNotFoundError as exc:
        failures.append(str(exc))
    else:
        if "TiptapComposer" in project_text:
            failures.append(f"{project}: still contains Tiptap composer target membership")

    for rule in SURFACES:
        try:
            text = _read(root, rule.path)
        except FileNotFoundError as exc:
            failures.append(str(exc))
            continue
        for token in rule.required_tokens:
            if token not in text:
                failures.append(f"{rule.path}: {rule.description} must reference {token!r}")
        for pattern in rule.forbidden_patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(
                    f"{rule.path}:{line}: {rule.description} contains forbidden {match.group(1)}"
                )
    return failures


def main() -> int:
    failures = audit()
    if failures:
        print("Apple composer audit failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("Apple composer audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
