# backend/tests/test_svg_sanitizer.py
#
# Tests for the SVG cleaner used on uploaded and generated SVGs.

import pytest

from backend.core.api.app.utils.image_processing import (
    is_sanitized_svg,
    process_svg_for_storage,
)
from backend.shared.python_utils.svg_sanitizer import SvgSanitizeError, sanitize_svg

NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _clean(body: str) -> str:
    return sanitize_svg(f"<svg {NS}>{body}</svg>".encode()).decode()


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_keeps_declarative_animation() -> None:
    out = _clean(
        '<style>@keyframes spin{from{opacity:0}to{opacity:1}}</style>'
        '<circle id="c" r="5"><animate attributeName="r" from="1" to="5" dur="1s"/>'
        '<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="2s"/>'
        '<animateMotion dur="3s"><mpath xlink:href="#p"/></animateMotion>'
        '<set attributeName="fill" to="red"/></circle><path id="p" d="M0 0"/>'
    )
    for part in ("<animate ", "<animateTransform", "<animateMotion", "<set ", "<mpath", "@keyframes spin"):
        assert part in out


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_strips_scripts_handlers_and_foreign_content() -> None:
    out = _clean(
        '<script>alert(1)</script><foreignObject><div/></foreignObject>'
        '<circle r="5" onload="x()" onclick="y()"/>'
        '<image href="https://example.org/a.png"/>'
        '<use href="https://example.org/a.svg#x"/>'
        '<use href="#ok"/>'
    )
    assert "script" not in out.lower()
    assert "foreignObject" not in out
    assert "onload" not in out and "onclick" not in out
    assert "example.org" not in out
    assert 'href="#ok"' in out


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_strips_external_urls_imports_and_unsafe_animation_targets() -> None:
    out = _clean(
        '<style>@import url(https://example.org/a.css); @font-face{src:url(https://example.org/f.woff)}'
        ' .a{fill:url(https://example.org/p.png)} .b{fill:url(#g)}</style>'
        '<rect fill="url(https://example.org/p.png)" width="1" height="1"/>'
        '<rect fill="url(#g)" style="fill:url(//example.org/x)" width="1" height="1"/>'
        '<set attributeName="href" to="https://example.org"/>'
        '<animate attributeName="xlink:href" to="https://example.org"/>'
        '<animate attributeName="onclick" to="x"/>'
    )
    assert "example.org" not in out
    assert "@import" not in out and "@font-face" not in out
    assert "url(#g)" in out
    assert "attributeName" not in out


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_malformed_or_entity_xml_raises() -> None:
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(b"<svg><g></svg>")
    with pytest.raises(SvgSanitizeError):
        sanitize_svg(b'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>')


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_generated_svg_original_is_sanitized() -> None:
    svg = f'<svg {NS} width="10" height="10"><script>x()</script><rect width="10" height="10"/></svg>'.encode()
    original = process_svg_for_storage(svg)["original"]
    assert b"script" not in original
    assert is_sanitized_svg(original)
    assert not is_sanitized_svg(b"not svg")


# contract-test: direct surface=rest_api assertions=slides.media.svg-declarative-animation
def test_upload_route_marks_vector_sanitized() -> None:
    from backend.upload.routes import upload_route

    fields = upload_route.FileVariantMetadata.model_fields
    assert "sanitized" in fields
    meta = upload_route.FileVariantMetadata(
        s3_key="k", width=1, height=1, size_bytes=1, format="svg", sanitized=True
    )
    assert meta.sanitized is True
    assert upload_route.sanitize_svg is sanitize_svg
