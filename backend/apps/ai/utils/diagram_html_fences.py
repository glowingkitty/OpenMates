"""Validation and metadata for source-first, inert HTML/SVG diagram fences.

The source is deliberately never rewritten. A validated original is stored in
the client-encrypted embed, while renderers use their own sandboxed copy.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from html.parser import HTMLParser


DIAGRAM_HTML_FENCE_LANGUAGES = {"openmates_diagram"}
DIAGRAM_HTML_SCHEMA_VERSION = 1
MAX_DIAGRAM_HTML_BYTES = 1024 * 1024
MAX_DIAGRAM_TAGS = 12000
MAX_EMBEDDED_FONT_BYTES = 256 * 1024
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCKED_TAGS = {
    "script", "iframe", "frame", "frameset", "object", "embed", "applet",
    "link", "base", "img", "image", "video", "audio", "source", "track",
    "form", "input", "textarea", "select", "button", "template", "portal",
    "foreignobject", "animate", "animatemotion", "animatetransform", "set",
    "discard", "feimage", "math", "noscript",
}
_RESOURCE_ATTRIBUTES = {
    "src", "srcset", "poster", "data", "action", "formaction", "background",
    "cite", "longdesc", "profile", "manifest", "codebase", "archive", "usemap",
}
_URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.IGNORECASE)
_CSS_COMMENTS_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_FRAGMENT_RE = re.compile(r"^#[A-Za-z_][A-Za-z0-9_.:-]{0,119}$")
_FONT_DATA_RE = re.compile(r"^data:font/woff2;base64,([A-Za-z0-9+/]+={0,2})$", re.IGNORECASE)
_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EDGE_SIDES = {"left", "right", "top", "bottom"}
_SVG_PATH_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\-\s]+$")


class DiagramHtmlValidationError(ValueError):
    """A diagram source cannot safely be rendered as inert HTML/SVG."""


@dataclass(frozen=True)
class DiagramHtmlMetadata:
    title: str
    diagram_kind: str
    render_width: int
    render_height: int
    schema_version: int = DIAGRAM_HTML_SCHEMA_VERSION


def is_diagram_html_fence(language: str | None) -> bool:
    return (language or "").strip().lower() in DIAGRAM_HTML_FENCE_LANGUAGES


def _fail(reason: str) -> None:
    raise DiagramHtmlValidationError(reason)


def _check_css(value: str) -> None:
    if len(value) > MAX_DIAGRAM_HTML_BYTES:
        _fail("CSS exceeds diagram limit")
    css = _CSS_COMMENTS_RE.sub("", value)
    # CSS escapes can hide resource loading tokens. The diagram profile does
    # not need them; failing closed also keeps the URL check simple.
    if "\\" in css:
        _fail("CSS escapes are not supported")
    lower = css.lower()
    if re.search(r"@\s*(?:import|namespace|document)\b|image-set\s*\(|expression\s*\(|behavior\s*:|-moz-binding\s*:", lower):
        _fail("CSS contains an active or external resource")
    spans: list[tuple[int, int]] = []
    for match in _URL_RE.finditer(css):
        spans.append(match.span())
        target = next((part for part in match.groups() if part is not None), "").strip()
        if _FRAGMENT_RE.fullmatch(target):
            continue
        font = _FONT_DATA_RE.fullmatch(target)
        if font:
            previous_close = css.rfind("}", 0, match.start())
            face_start = css.lower().rfind("@font-face", previous_close + 1, match.start())
            face_open = css.find("{", face_start + 10, match.start()) if face_start >= 0 else -1
            if face_open < 0:
                _fail("Embedded font is outside @font-face")
            try:
                font_bytes = base64.b64decode(font.group(1), validate=True)
            except (ValueError, binascii.Error):
                _fail("Invalid embedded font")
            if not font_bytes or len(font_bytes) > MAX_EMBEDDED_FONT_BYTES or not font_bytes.startswith(b"wOF2"):
                _fail("Invalid embedded WOFF2 font")
            continue
        _fail("Diagram loads an external resource")
    without_urls = list(css)
    for start, end in spans:
        without_urls[start:end] = " " * (end - start)
    if re.search(r"url\s*\(", "".join(without_urls), re.IGNORECASE):
        _fail("Malformed CSS URL")


class _DiagramParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tags = 0
        self.html = self.head = self.body = False
        self.primary_svg_size: tuple[int, int] | None = None
        self.render_size: tuple[int, int] | None = None
        self.head_title = ""
        self.svg_title = ""
        self.kind = "diagram"
        self.components: set[str] = set()
        self.edges: list[tuple[str, str]] = []
        self._text_target: str | None = None
        self._style_parts: list[str] | None = None

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() != "doctype html":
            _fail("Unsupported declaration")

    def unknown_decl(self, data: str) -> None:
        _fail("Unsupported declaration")

    def handle_pi(self, data: str) -> None:
        _fail("Processing instructions are not allowed")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.tags += 1
        if self.tags > MAX_DIAGRAM_TAGS:
            _fail("Diagram has too many elements")
        if tag in _BLOCKED_TAGS:
            _fail(f"Active element <{tag}> is not allowed")
        names = [name for name, _ in attrs]
        if len(names) != len(set(names)):
            _fail("Duplicate attribute")
        values = dict(attrs)
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if len(value) > MAX_DIAGRAM_HTML_BYTES or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
                _fail("Invalid attribute value")
            if name.startswith("on") or name in {"srcdoc", "http-equiv"} or name in _RESOURCE_ATTRIBUTES:
                _fail("Executable or loading attribute")
            if name in {"href", "xlink:href"} and not _FRAGMENT_RE.fullmatch(value):
                _fail("External link is not allowed")
            if name == "style" or "url(" in value.lower():
                _check_css(value)
            if name.startswith("data-om-") and len(value) > 120:
                _fail("Diagram edit metadata is too long")
        if tag == "meta":
            if values.get("name", "").lower() in {"diagram-kind", "openmates-diagram-kind"}:
                kind = (values.get("content") or "").strip().lower()
                if not _KIND_RE.fullmatch(kind):
                    _fail("Invalid diagram kind")
                self.kind = kind
        if tag == "html":
            if self.html or self.stack:
                _fail("Malformed HTML root")
            self.html = True
            if "data-om-render-width" in values or "data-om-render-height" in values:
                try:
                    width = int(values["data-om-render-width"])
                    height = int(values["data-om-render-height"])
                except (KeyError, TypeError, ValueError):
                    _fail("Invalid diagram render dimensions")
                if not (1 <= width <= 8192 and 1 <= height <= 8192):
                    _fail("Diagram render dimensions are outside supported range")
                self.render_size = (width, height)
        if tag == "head":
            self.head = True
        if tag == "body":
            self.body = True
        if tag == "svg":
            viewbox = values.get("viewbox")
            if not viewbox:
                _fail("SVG viewBox is required")
            parts = re.split(r"[\s,]+", viewbox.strip())
            if len(parts) != 4:
                _fail("Invalid SVG viewBox")
            try:
                width, height = float(parts[2]), float(parts[3])
            except (ValueError, binascii.Error):
                _fail("Invalid SVG viewBox")
            if not (1 <= width <= 8192 and 1 <= height <= 8192):
                _fail("SVG viewBox is outside supported dimensions")
            if "data-om-diagram" in values:
                if self.primary_svg_size is not None:
                    _fail("Diagram has multiple primary SVGs")
                kind = values["data-om-diagram"]
                if not _KIND_RE.fullmatch(kind):
                    _fail("Invalid diagram kind")
                self.kind = kind
                self.primary_svg_size = (round(width), round(height))
        if tag == "g":
            component = values.get("data-om-component")
            if component:
                if component in self.components:
                    _fail("Duplicate diagram component ID")
                self.components.add(component)
            if "data-om-edge" in values:
                source, target = values.get("data-om-from"), values.get("data-om-to")
                if not source or not target or values.get("data-om-from-side") not in _EDGE_SIDES or values.get("data-om-to-side") not in _EDGE_SIDES:
                    _fail("Invalid diagram edge metadata")
                self.edges.append((source, target))
        if tag == "path" and "data-om-path" in values:
            path = values.get("d") or ""
            if not _SVG_PATH_RE.fullmatch(path) or not re.match(r"\s*[Mm]", path):
                _fail("Editable edge path must use static SVG path commands")
        if tag == "title":
            self._text_target = "head" if "head" in self.stack else "svg" if "svg" in self.stack else None
        if tag == "style":
            self._style_parts = []
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_data(self, data: str) -> None:
        if self._style_parts is not None:
            self._style_parts.append(data)
        elif not self.stack and data.strip():
            _fail("Text outside HTML root")
        if self._text_target == "head":
            self.head_title += data
        elif self._text_target == "svg":
            self.svg_title += data

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS or not self.stack or self.stack[-1] != tag:
            _fail("Malformed HTML/SVG nesting")
        if tag == "style":
            _check_css("".join(self._style_parts or []))
            self._style_parts = None
        self.stack.pop()
        if tag == "title":
            self._text_target = None


def validate_diagram_html_source(source: str) -> DiagramHtmlMetadata:
    """Validate a complete offline HTML document and return bounded metadata."""
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > MAX_DIAGRAM_HTML_BYTES:
        _fail("Diagram HTML is empty or too large")
    parser = _DiagramParser()
    try:
        parser.feed(source)
        parser.close()
    except (UnicodeError, OverflowError) as exc:
        raise DiagramHtmlValidationError("Malformed diagram HTML") from exc
    if parser.stack or not (parser.html and parser.head and parser.body):
        _fail("Complete HTML document with inline SVG is required")
    if parser.primary_svg_size is None:
        _fail("Diagram requires one primary SVG")
    if any(source_id not in parser.components or target_id not in parser.components for source_id, target_id in parser.edges):
        _fail("Diagram edge references a missing component")
    title = (parser.head_title or parser.svg_title).strip()
    if not title or len(title) > 160:
        _fail("Diagram title is missing or too long")
    width, height = parser.render_size or parser.primary_svg_size
    return DiagramHtmlMetadata(title, parser.kind, width, height)
