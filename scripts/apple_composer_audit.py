#!/usr/bin/env python3
"""Guard Apple product surfaces against forked message composers.

The web MessageInput is the source of truth for composer visuals. Apple hosts
may adapt container size and send plumbing, but product chat, quick capture, and
share-extension instruction fields must route through the shared native composer
contract instead of bespoke TextField/TextView styling. This audit is intentionally
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

SURFACES = (
    SurfaceRule(
        path=Path("apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift"),
        required_tokens=("MessageComposerView",),
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
        forbidden_patterns=(),
        description="iOS share extension composer adapter",
    ),
    SurfaceRule(
        path=Path("apple/OpenMatesShareExtensionMacOS/MacShareViewController.swift"),
        required_tokens=("message-composer", "message-field", "message-editor"),
        forbidden_patterns=(),
        description="macOS share extension composer adapter",
    ),
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
    if not shared_component.exists():
        failures.append("Missing shared component: apple/OpenMates/Sources/Shared/Components/MessageComposerView.swift")

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

    if failures:
        print("Apple composer audit failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Apple composer audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
