#!/usr/bin/env python3
"""Guard native header controls against drift from the rendered web header.

The Apple shell must use the generated web menu asset at its rendered size and
must retain the guest GitHub repository action with the web-matched dimensions.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_APP_VIEW = ROOT / "apple/OpenMates/Sources/App/MainAppView.swift"
MENU_ASSET = (
    ROOT
    / "frontend/packages/ui/src/tokens/generated/swift/Icons.xcassets/menu.imageset/menu.svg"
)


def test_native_header_uses_generated_web_menu_icon() -> None:
    source = MAIN_APP_VIEW.read_text(encoding="utf-8")

    assert MENU_ASSET.is_file()
    assert 'Icon("menu", size: 25)' in source
    assert "WebHamburgerIcon" not in source


def test_native_guest_header_keeps_web_sized_github_action() -> None:
    source = MAIN_APP_VIEW.read_text(encoding="utf-8")

    assert 'Icon("github", size: 22)' in source
    assert ".frame(width: 42, height: 42)" in source
    assert '.accessibilityIdentifier("github-repo-button")' in source
