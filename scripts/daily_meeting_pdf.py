#!/usr/bin/env python3
"""Render the daily meeting briefing Markdown as a PDF (the Claude app reads PDFs whole).

Only the Markdown subset the briefing uses: headings, paragraphs, bullet and
numbered lists, pipe tables, fenced code blocks, **bold**, `code` and [links](url).
Rendering reuses the repository's headless Chromium launcher.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import html
from pathlib import Path
import re
import sys

STYLE = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
body { font: 10.5pt/1.45 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #1d232a; }
h1 { font-size: 18pt; margin: 0 0 8px; }
h2 { font-size: 13.5pt; margin: 18px 0 6px; padding-bottom: 3px; border-bottom: 1px solid #d5dbe1; }
h3 { font-size: 11.5pt; margin: 12px 0 4px; }
p { margin: 5px 0; }
ul, ol { margin: 4px 0 6px; padding-left: 20px; }
li { margin: 1px 0; }
code { font: 9pt ui-monospace, Menlo, Consolas, monospace; background: #f1f3f5; padding: 0 3px; border-radius: 3px; }
pre { font: 9pt/1.4 ui-monospace, Menlo, Consolas, monospace; background: #f1f3f5; padding: 8px 10px;
      border-radius: 4px; white-space: pre-wrap; break-inside: avoid; }
a { color: #1f5fbf; text-decoration: none; }
table { border-collapse: collapse; margin: 6px 0; font-size: 9.5pt; }
th, td { border: 1px solid #d5dbe1; padding: 2px 8px; text-align: left; }
th { background: #f1f3f5; }
"""


def _inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        part = html.escape(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<em>\1</em>", part)
        part = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', part)
        out.append(part)
    return "".join(out)


def _paragraph(lines: list[str]) -> str:
    """Soft-wrapped lines join with a space; a trailing double space is a line break."""
    text = ""
    for line in lines:
        text += _inline(line.rstrip()) + ("<br>" if line.endswith("  ") else " ")
    return f"<p>{text.strip()}</p>"


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_to_html(markdown: str, title: str = "Daily meeting briefing") -> str:
    body: list[str] = []
    list_tag = ""
    paragraph: list[str] = []
    lines = markdown.splitlines()
    index = 0

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            body.append(_paragraph(paragraph))
            paragraph.clear()
        if list_tag:
            body.append(f"</{list_tag}>")
            list_tag = ""

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush()
            block = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            body.append(f"<pre>{html.escape(chr(10).join(block))}</pre>")
        elif line.startswith("|") and index + 1 < len(lines) and re.match(r"\|[\s:|-]+\|?$", lines[index + 1]):
            flush()
            rows = [f"<tr>{''.join(f'<th>{_inline(c)}</th>' for c in _cells(line))}</tr>"]
            index += 2
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(f"<tr>{''.join(f'<td>{_inline(c)}</td>' for c in _cells(lines[index]))}</tr>")
                index += 1
            body.append(f"<table>{''.join(rows)}</table>")
            continue
        elif heading := re.match(r"(#{1,3}) (.*)", line):
            flush()
            level = len(heading.group(1))
            body.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif item := re.match(r"\s*(- |\d+\. )(.*)", line):
            tag = "ul" if item.group(1) == "- " else "ol"
            if paragraph:
                body.append(_paragraph(paragraph))
                paragraph.clear()
            if list_tag != tag:
                if list_tag:
                    body.append(f"</{list_tag}>")
                body.append(f"<{tag}>")
                list_tag = tag
            body.append(f"<li>{_inline(item.group(2))}</li>")
        elif not line.strip():
            flush()
        else:
            if list_tag:
                body.append(f"</{list_tag}>")
                list_tag = ""
            paragraph.append(line)
        index += 1
    flush()
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{STYLE}</style></head><body>{''.join(body)}</body></html>")


def render_pdf(markdown_path: Path, pdf_path: Path) -> Path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.playwright_visual_smoke import launch_browser

    document = markdown_to_html(markdown_path.read_text(), markdown_path.stem)
    playwright, browser = launch_browser()
    try:
        page = browser.new_page()
        page.set_content(document, wait_until="load")
        page.pdf(path=str(pdf_path), format="A4", print_background=True, display_header_footer=True,
                 margin={"top": "16mm", "right": "15mm", "bottom": "18mm", "left": "15mm"},
                 header_template="<span></span>",
                 footer_template=('<div style="font:8px Arial,sans-serif;color:#6b7785;text-align:center;'
                                  'width:100%;"><span class="pageNumber"></span> / '
                                  '<span class="totalPages"></span></div>'))
    finally:
        browser.close()
        playwright.stop()
    pdf_path.chmod(0o600)
    return pdf_path


if __name__ == "__main__":
    source = Path(sys.argv[1])
    print(render_pdf(source, source.with_suffix(".pdf")))
