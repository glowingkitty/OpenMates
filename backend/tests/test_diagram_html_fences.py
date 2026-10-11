"""Whole-document validation for source-first client-encrypted HTML diagrams."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.apps.ai.utils.diagram_html_fences import (
    DiagramHtmlValidationError,
    is_diagram_html_fence,
    validate_diagram_html_source,
)


SOURCE = """<!DOCTYPE html><html data-om-render-width="960" data-om-render-height="560">
<head><title>Revenue flow</title><style>
:root { --ink: #223344; } .node { fill: var(--ink); }
</style></head><body><svg data-om-diagram="flowchart" viewBox="0 0 800 400" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="arrow" markerWidth="8" markerHeight="6"><path d="M0 0L8 3L0 6"/></marker></defs>
<g data-om-component="source" data-om-editable="true"><rect x="10" y="10" width="100" height="40"/>
<text data-om-text="source-label" data-om-editable="text">Source</text></g>
<g data-om-component="target" data-om-editable="true"><rect x="200" y="10" width="100" height="40"/></g>
<g data-om-edge="source-target" data-om-from="source" data-om-to="target"
data-om-from-side="right" data-om-to-side="left"><path data-om-path d="M 110,30 H 200" marker-end="url(#arrow)"/></g>
</svg></body></html>"""


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_fence_detection_and_original_source_metadata() -> None:
    assert is_diagram_html_fence("openmates_diagram")
    assert not is_diagram_html_fence("html")
    metadata = validate_diagram_html_source(SOURCE)
    assert metadata.title == "Revenue flow"
    assert metadata.diagram_kind == "flowchart"
    assert (metadata.render_width, metadata.render_height, metadata.schema_version) == (960, 560, 1)
    assert "data-om-edge" in SOURCE and "url(#arrow)" in SOURCE


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_decorative_svg_before_primary_does_not_select_metadata() -> None:
    decorative = '<svg viewBox="0 0 1600 900"><rect width="20" height="20"/></svg>'
    source = SOURCE.replace(' data-om-render-width="960" data-om-render-height="560"', '')
    source = source.replace('<body><svg data-om-diagram=', f'<body>{decorative}<svg data-om-diagram=')
    metadata = validate_diagram_html_source(source)
    assert metadata.diagram_kind == "flowchart"
    assert (metadata.render_width, metadata.render_height) == (800, 400)


@pytest.mark.parametrize("invalid", [
    SOURCE.replace(' data-om-diagram="flowchart"', ''),
    SOURCE.replace('</svg></body>', '</svg><svg data-om-diagram="second" viewBox="0 0 20 20"></svg></body>'),
    SOURCE.replace('data-om-diagram="flowchart"', 'data-om-diagram=""'),
])
# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_requires_exactly_one_primary_svg(invalid: str) -> None:
    with pytest.raises(DiagramHtmlValidationError):
        validate_diagram_html_source(invalid)


@pytest.mark.parametrize("invalid", [
    SOURCE.replace("</svg>", ""),
    SOURCE.replace("data-om-to=\"target\"", "data-om-to=\"missing\""),
    SOURCE.replace("M 110,30 H 200", "M 110,30 C 120,40 180,40 200,30"),
    SOURCE.replace("<title>Revenue flow</title>", ""),
    SOURCE.replace("<rect x=", "<rect onclick=\"alert(1)\" x=", 1),
    SOURCE.replace("<defs>", "<script>alert(1)</script><defs>"),
    SOURCE.replace("url(#arrow)", "url(https://example.com/arrow.svg)"),
    SOURCE.replace("<defs>", "<image href=\"https://example.com/a.png\"/><defs>"),
    SOURCE.replace("--ink: #223344", "@import url(https://example.com/x.css); --ink: #223344"),
    SOURCE.replace("<defs>", "<foreignObject><div>active</div></foreignObject><defs>"),
])
# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_rejects_malformed_active_or_external_document(invalid: str) -> None:
    with pytest.raises(DiagramHtmlValidationError):
        validate_diagram_html_source(invalid)


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_bounded_inline_woff2_font_and_source_limit() -> None:
    data = base64.b64encode(b"wOF2" + b"x" * 32).decode()
    with_font = SOURCE.replace(":root {", f"@font-face {{ font-family: 'Diagram'; src: url(data:font/woff2;base64,{data}); }} :root {{")
    assert validate_diagram_html_source(with_font).title == "Revenue flow"
    invalid_data = base64.b64encode(b"xxxx" + b"x" * 32).decode()
    with pytest.raises(DiagramHtmlValidationError):
        validate_diagram_html_source(with_font.replace(data, invalid_data))
    with pytest.raises(DiagramHtmlValidationError):
        validate_diagram_html_source(SOURCE + " " * (1024 * 1024))


# contract-test: supporting surface=rest_api assertions=chats.rendering.assistant-document-convergence
def test_first_party_full_source_example_is_valid() -> None:
    example = Path(__file__).resolve().parents[2] / "frontend/packages/ui/src/components/embeds/diagrams/diagramHtmlExampleLight.html"
    source = example.read_text()
    metadata = validate_diagram_html_source(source)
    assert metadata.diagram_kind == "architecture"
    assert metadata.render_width == 1240
    assert metadata.render_height == 900
