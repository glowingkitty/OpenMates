"""Focused regression tests for the Apple composer host audit.

Fixtures prove native TextKit hosts remain allowed while composer WebView
symbols are rejected. The repository-level check protects target membership,
all production hosts, and removal of the vendored Tiptap runtime.
"""

from scripts import apple_composer_audit


def test_forbidden_webview_fixture_is_rejected() -> None:
    text = "let editor = WKWebView(); TiptapComposerWebView(); WKScriptMessageHandler"
    assert apple_composer_audit.forbidden_webview_matches(text) == [
        "WKWebView",
        "TiptapComposerWebView",
        "WKScriptMessageHandler",
    ]


def test_native_textkit_fixture_is_allowed() -> None:
    text = "UITextView(usingTextLayoutManager: true); NSTextView(usingTextLayoutManager: true)"
    assert apple_composer_audit.forbidden_webview_matches(text) == []


def test_repository_composer_hosts_pass_audit() -> None:
    assert apple_composer_audit.audit() == []
