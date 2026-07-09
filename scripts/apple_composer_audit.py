#!/usr/bin/env python3
"""Guard Apple product surfaces against forked message composers.

The web MessageInput is the source of truth for composer visuals. Apple hosts
may adapt container size and send plumbing, but product chat, quick capture, and
share-extension instruction fields must route through the shared native composer
contract instead of bespoke TextField/TextView styling. The editable product
field must be the local Tiptap WKWebView bridge, while transcript rendering stays
native unless a separate spec approves that scope. This audit is intentionally
small and path-scoped so future changes fail before another composer fork lands.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SurfaceRule:
    path: Path
    required_tokens: tuple[str, ...]
    forbidden_patterns: tuple[re.Pattern[str], ...]
    description: str


SWIFT_TEXT_INPUT = re.compile(r"\b(TextField|TextEditor|UITextView|NSTextView)\b")
WEBVIEW_TRANSCRIPT = re.compile(r"\b(WKWebView|TiptapComposerWebView)\b")

SURFACES = (
    SurfaceRule(
        path=Path("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"),
        required_tokens=("MessageComposerView", "TiptapComposerWebView"),
        forbidden_patterns=(),
        description="main chat composer",
    ),
    SurfaceRule(
        path=Path("apple/OpenMates/Sources/App/MainAppView.swift"),
        required_tokens=("MessageComposerView",),
        forbidden_patterns=(),
        description="new-chat welcome composer",
    ),
    SurfaceRule(
        path=Path("apple/OpenMates/Sources/App/OpenMatesApp.swift"),
        required_tokens=("MessageComposerView", "quick-capture-composer"),
        forbidden_patterns=(SWIFT_TEXT_INPUT,),
        description="menu bar quick capture composer",
    ),
    SurfaceRule(
        path=Path("apple/OpenMates/Sources/DevPreview/DevEmbedPreviewGalleryView.swift"),
        required_tokens=("MessageComposerView", "quick-capture-composer"),
        forbidden_patterns=(SWIFT_TEXT_INPUT,),
        description="quick-capture debug preview composer",
    ),
    SurfaceRule(
        path=Path("apple/OpenMatesShareExtension/ShareViewController.swift"),
        required_tokens=("message-composer", "message-field", "message-editor"),
        forbidden_patterns=(SWIFT_TEXT_INPUT,),
        description="iOS share extension composer adapter",
    ),
    SurfaceRule(
        path=Path("apple/OpenMatesShareExtensionMacOS/MacShareViewController.swift"),
        required_tokens=("message-composer", "message-field", "message-editor"),
        forbidden_patterns=(SWIFT_TEXT_INPUT,),
        description="macOS share extension composer adapter",
    ),
)

TRANSCRIPT_NATIVE_SURFACES = (
    Path("apple/OpenMates/Sources/Shared/Components/RichMarkdownRenderer.swift"),
    Path("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"),
)


def _read(path: Path) -> str:
    full_path = REPO_ROOT / path
    if not full_path.exists():
        raise FileNotFoundError(f"Missing expected surface file: {path}")
    return full_path.read_text(encoding="utf-8")


def _line_for(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def main() -> int:
    failures: list[str] = []
    shared_component = REPO_ROOT / "apple/OpenMates/Sources/Shared/Components/MessageComposerView.swift"
    shared_field_component = REPO_ROOT / "apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift"
    if not shared_component.exists():
        failures.append("Missing shared component: apple/OpenMates/Sources/Shared/Components/MessageComposerView.swift")
    if not shared_field_component.exists():
        failures.append("Missing shared field component: apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift")
    if shared_component.exists() and shared_field_component.exists():
        shared_text = shared_component.read_text(encoding="utf-8")
        shared_field_text = shared_field_component.read_text(encoding="utf-8")
        if "TiptapComposerWebView" not in (shared_text + shared_field_text):
            failures.append("Shared composer stack must host TiptapComposerWebView for the editable message editor")
        for path, text in (
            (shared_component, shared_text),
            (shared_field_component, shared_field_text),
        ):
            for match in SWIFT_TEXT_INPUT.finditer(text):
                line = _line_for(text, match.start())
                failures.append(
                    f"{path.relative_to(REPO_ROOT)}:{line}: shared composer stack contains native {match.group(1)} instead of TiptapComposerWebView"
                )

    bridge_component = REPO_ROOT / "apple/OpenMates/Sources/Shared/Components/TiptapComposerWebView.swift"
    if not bridge_component.exists():
        failures.append("Missing Tiptap bridge component: apple/OpenMates/Sources/Shared/Components/TiptapComposerWebView.swift")

    composer_resource = REPO_ROOT / "apple/OpenMates/Resources/TiptapComposer/composer.js"
    composer_index = REPO_ROOT / "apple/OpenMates/Resources/TiptapComposer/index.html"
    composer_vendor = REPO_ROOT / "apple/OpenMates/Resources/TiptapComposer/vendor/@tiptap/core@3.26.0/es2022/core.bundle.mjs"
    if not composer_resource.exists():
        failures.append("Missing local Tiptap composer script: apple/OpenMates/Resources/TiptapComposer/composer.js")
    else:
        composer_text = composer_resource.read_text(encoding="utf-8")
        for token in ("from './vendor/tiptap-core.mjs'", "from './vendor/tiptap-starter-kit.mjs'", "new Editor"):
            if token not in composer_text:
                failures.append(f"Tiptap composer script must include real local Tiptap runtime token {token!r}")
    if not composer_index.exists():
        failures.append("Missing local Tiptap composer index: apple/OpenMates/Resources/TiptapComposer/index.html")
    elif "type=\"importmap\"" not in composer_index.read_text(encoding="utf-8"):
        failures.append("Tiptap composer index must use a local import map for vendored @tiptap modules")
    if not composer_vendor.exists():
        failures.append("Missing vendored @tiptap/core module for offline WKWebView runtime")

    for rule in SURFACES:
        try:
            text = _read(rule.path)
        except FileNotFoundError as exc:
            failures.append(str(exc))
            continue

        for token in rule.required_tokens:
            if token not in text:
                failures.append(f"{rule.path}: {rule.description} must reference {token!r}")

        for pattern in rule.forbidden_patterns:
            for match in pattern.finditer(text):
                line = _line_for(text, match.start())
                failures.append(
                    f"{rule.path}:{line}: {rule.description} contains bespoke {match.group(1)} instead of MessageComposerView"
                )

    for path in TRANSCRIPT_NATIVE_SURFACES:
        try:
            text = _read(path)
        except FileNotFoundError as exc:
            failures.append(str(exc))
            continue
        if path.name == "RichMarkdownRenderer.swift" and WEBVIEW_TRANSCRIPT.search(text):
            failures.append(f"{path}: chat history renderer must remain native for this composer-only slice")

    if failures:
        print("Apple composer audit failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Apple composer audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
