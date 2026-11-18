# backend/shared/python_utils/svg_sanitizer.py
#
# Cleans an SVG document before it is stored (spec rule
# slides.media.svg-declarative-animation). The cleaned SVG keeps its declarative
# animation (SMIL animate/animateTransform/animateMotion/mpath/set and CSS
# @keyframes in <style>) but loses everything that could run code or load
# something from outside the document: scripts, event handlers, foreign
# objects, frames, links, external images, url() other than local fragments,
# @import and @font-face. The web client still shows it only as an <img>.
# Parsing uses defusedxml, so DOCTYPE, entities and processing instructions
# are rejected.

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_HREF_ATTRS = {"href", f"{{{XLINK_NS}}}href"}

_DROPPED_ELEMENTS = {
    "script", "foreignobject", "iframe", "object", "embed", "audio", "video",
    "handler", "listener",
}
_UNWRAPPED_ELEMENTS = {"a"}
_HREF_ELEMENTS = {"image", "feimage", "use"}
_ANIMATION_ELEMENTS = {"set", "animate"}

_URL_FUNC = re.compile(r"url\(\s*(['\"]?)\s*([^)'\"]*?)\s*\1\s*\)", re.IGNORECASE)
_AT_IMPORT = re.compile(r"@import\b[^;{]*;?", re.IGNORECASE)
_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}", re.IGNORECASE)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class SvgSanitizeError(ValueError):
    """The bytes are not a well-formed, safe-to-parse SVG document."""


def _local(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _clean_css(text: str) -> str:
    text = _CSS_COMMENT.sub("", text)
    text = _FONT_FACE.sub("", text)
    text = _AT_IMPORT.sub("", text)
    return _URL_FUNC.sub(
        lambda m: m.group(0) if m.group(2).startswith("#") else "none", text
    )


def _has_foreign_url(value: str) -> bool:
    return any(not m.group(2).startswith("#") for m in _URL_FUNC.finditer(value)) or (
        "url(" in value.lower() and not _URL_FUNC.search(value)
    )


def _clean_attributes(element: ET.Element) -> None:
    for name in list(element.attrib):
        value = element.attrib[name]
        local = _local(name)
        if local.startswith("on"):
            del element.attrib[name]
        elif name in _HREF_ATTRS or local == "href":
            if not value.strip().startswith("#"):
                del element.attrib[name]
        elif local == "style":
            element.attrib[name] = _clean_css(value)
        elif "url(" in value.lower() and _has_foreign_url(value):
            del element.attrib[name]


def _is_unsafe_animation(element: ET.Element) -> bool:
    if _local(element.tag) not in _ANIMATION_ELEMENTS:
        return False
    target = (element.get("attributeName") or "").strip().lower()
    target = target.rsplit(":", 1)[-1]
    return target in {"href", "style"} or target.startswith("on")


def _clean_children(parent: ET.Element) -> None:
    cleaned: list[ET.Element] = []
    for child in list(parent):
        local = _local(child.tag)
        keep = True
        if not isinstance(child.tag, str) or local in _DROPPED_ELEMENTS:
            keep = False
        elif _is_unsafe_animation(child):
            keep = False
        elif local in _HREF_ELEMENTS:
            href = child.get("href") or child.get(f"{{{XLINK_NS}}}href") or ""
            if local != "use" or href:
                keep = href.strip().startswith("#")
        if local in _UNWRAPPED_ELEMENTS:
            _clean_children(child)
            cleaned.extend(child)
            continue
        if keep:
            _clean_attributes(child)
            if local == "style":
                child.text = _clean_css(child.text or "")
                for sub in list(child):
                    child.remove(sub)
            else:
                _clean_children(child)
            cleaned.append(child)
    for child in list(parent):
        parent.remove(child)
    parent.extend(cleaned)


def sanitize_svg(svg_bytes: bytes) -> bytes:
    """Return a cleaned UTF-8 copy of an SVG, or raise SvgSanitizeError."""
    try:
        root = SafeElementTree.fromstring(svg_bytes)
    except (ET.ParseError, DefusedXmlException, UnicodeDecodeError, ValueError) as exc:
        raise SvgSanitizeError(f"SVG could not be parsed: {exc}") from exc
    if _local(root.tag) != "svg":
        raise SvgSanitizeError("document root is not an svg element")
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    _clean_attributes(root)
    _clean_children(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)

