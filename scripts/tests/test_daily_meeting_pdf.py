# contract-test-file: tooling
"""Markdown subset used by the daily meeting briefing renders to the expected HTML."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_meeting_pdf  # noqa: E402 - scripts dir added to path above


def test_markdown_subset_renders_headings_lists_tables_code_and_soft_wraps():
    html = daily_meeting_pdf.markdown_to_html(
        "# Title\n\nline one\nline two  \nnext\n\n- **bold** item\n1. first\n\n"
        "| Week | Phase |\n|---|---|\n| 2 Nov | Marketing |\n\n```\nDECISIONS <date>\n```\n"
        "See [docs](https://example.invalid/x) and `code`.\n")
    assert "<h1>Title</h1>" in html
    assert "<p>line one line two<br>next</p>" in html
    assert "<ul><li><strong>bold</strong> item</li></ul><ol><li>first</li></ol>" in html
    assert "<th>Week</th>" in html and "<td>Marketing</td>" in html
    assert "<pre>DECISIONS &lt;date&gt;</pre>" in html
    assert '<a href="https://example.invalid/x">docs</a>' in html and "<code>code</code>" in html
