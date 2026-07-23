# backend/tests/test_code_html_validation.py
#
# Contract tests for Code image-to-HTML inline output validation. The generated
# HTML is user-visible code, but it must be portable and self-contained before
# OpenMates creates a code embed or returns direct skill output.

from __future__ import annotations

import pytest

from backend.shared.python_utils.code_html_validation import validate_inline_html


def test_inline_html_with_style_and_script_passes() -> None:
    html = """
    <!doctype html>
    <html><head><style>body { color: #111; }</style></head>
    <body><button>Build</button><script>document.body.dataset.ready = '1';</script></body></html>
    """

    result = validate_inline_html(html)

    assert result.passed is True
    assert result.errors == []


def test_inline_data_urls_with_slashes_pass() -> None:
    html = """
    <!doctype html>
    <html><head><style>.logo { background-image: url(data:image/png;base64,AB//CD); }</style></head>
    <body><img src="data:image/png;base64,EF//GH" alt=""></body></html>
    """

    result = validate_inline_html(html)

    assert result.passed is True
    assert result.errors == []


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">', "external URL"),
        ('<script src="https://cdn.example.com/app.js"></script>', "external script"),
        ('<img src="http://example.com/image.png">', "external image"),
        ('<div style="background-image: url(https://example.com/bg.png)"></div>', "external URL"),
        ('<style>.hero{background:url(//example.com/bg.png)}</style>', "external URL"),
        ('<img src="/local-assets/asset.png">', "local-assets"),
    ],
)
def test_external_references_fail_with_deterministic_errors(html: str, expected: str) -> None:
    result = validate_inline_html(f"<!doctype html><html><body>{html}</body></html>")

    assert result.passed is False
    assert any(expected in error for error in result.errors)


def test_repair_prompt_summary_is_safe_and_bounded() -> None:
    result = validate_inline_html('<script src="https://cdn.example.com/app.js"></script>')

    summary = result.to_repair_prompt()

    assert "https://cdn.example.com" not in summary
    assert "external script" in summary
    assert len(summary) < 1000
