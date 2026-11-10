"""Slides markup parser and normaliser.

Single backend entry point for the ```slides fence format (grammar documented
in docs/architecture/apps/slides-format.md). The assistant output is untrusted:
``normalise_slides_markup`` parses it with the stdlib HTML tokenizer, keeps only
the known element/attribute vocabulary with validated values, assigns stable ids
and re-serialises one element per line.

Security contract (assertion slides.security.host-rendered-and-isolated):
outside ``<block>`` no script, style, iframe, object, unknown element, ``on*``
attribute, unknown attribute or external URL survives (the only external
address is the https ``href`` of ``<link>``). ``<block>`` bodies are extracted
before parsing and re-emitted byte-for-byte; the backend never interprets them.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

CANVAS_WIDTH = 1920
ASPECT_HEIGHTS: Dict[str, int] = {"16:9": 1080, "16:10": 1200, "4:3": 1440}
DEFAULT_ASPECT = "16:9"
DEFAULT_TEMPLATE = "builtin:plain"

MAX_SOURCE_CHARS = 1_000_000
MAX_SLIDES = 200
MAX_ELEMENTS_PER_SLIDE = 200
MAX_NOTE_CHARS = 5000

COLOR_TOKENS = {"background", "foreground", "accent", "accent-2", "muted", "surface"}
SAFE_FONTS = {
    f.lower(): f
    for f in (
        "Arial", "Helvetica", "Georgia", "Times New Roman", "Courier New",
        "Verdana", "Trebuchet MS", "system-ui", "serif", "sans-serif", "monospace",
    )
}
FONT_ROLES = {"heading", "body"}
TEXT_ROLES = {"title", "subtitle", "body", "caption", "quote"}
ALIGNS = {"left", "center", "right", "justify"}
SHAPE_KINDS = {"rect", "ellipse", "line", "triangle"}
ANIMATIONS = {"fade", "slide-in", "appear"}
TRANSITIONS = {"none", "fade", "slide"}
INLINE_TAGS = {"b", "i", "u", "s", "br", "ul", "ol", "li"}
ELEMENT_TAGS = {"text", "image", "video", "shape", "notepad", "todo", "link", "block"}
# Elements that never have children: they auto-close without an end tag.
VOID_TAGS = {"image", "video", "shape", "br"}
# Dropped together with their whole subtree; every other unknown element is unwrapped.
DANGEROUS_TAGS = {
    "script", "style", "iframe", "object", "embed", "template", "noscript",
    "svg", "math", "frame", "frameset", "applet",
}

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_LAYOUT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_TEMPLATE_RE = re.compile(r"^(builtin|library):[A-Za-z0-9._-]{1,64}$")
_EMBED_REF_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_YOUTUBE_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_VIMEO_RE = re.compile(r"^[0-9]{3,12}$")
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_INT_RE = re.compile(r"^-?[0-9]{1,6}(?:\.[0-9]+)?$")
_BLOCK_START_RE = re.compile(r"<block(?=[\s/>])", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</block\s*>", re.IGNORECASE)
_BLOCK_MARK = "data-om-block-index"


class SlidesMarkupError(ValueError):
    """Raised when markup cannot be turned into a deck at all."""


@dataclass(frozen=True)
class NormalisedDeck:
    markup: str
    title: str
    slide_count: int
    aspect: str


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: Dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: List[Union["_Node", str]] = []


class _TreeBuilder(HTMLParser):
    """Builds a tolerant element tree; unknown content is judged later."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._stack: List[_Node] = [self.root]

    def _open(self, tag: str, attrs: List[Tuple[str, Optional[str]]], selfclose: bool) -> None:
        # A notepad holds plain text only; an unclosed one ends where the next element starts.
        if self._stack[-1].tag == "notepad" and (tag in ELEMENT_TAGS or tag in {"slide", "notes", "deck"}):
            self._stack.pop()
        values: Dict[str, str] = {}
        for name, value in attrs:
            values.setdefault(name.lower(), value or "")
        node = _Node(tag, values)
        self._stack[-1].children.append(node)
        if not selfclose and tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._open(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _extract_blocks(source: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Replace every ``<block>`` with an empty marked tag; return (source, blocks).

    Each block is (start-tag attribute text, verbatim body). Unterminated blocks
    are discarded.
    """
    out: List[str] = []
    blocks: List[Tuple[str, str]] = []
    pos = 0
    while True:
        match = _BLOCK_START_RE.search(source, pos)
        if not match:
            out.append(source[pos:])
            break
        out.append(source[pos:match.start()])
        i = match.end()
        quote = ""
        while i < len(source):
            ch = source[i]
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == ">":
                break
            i += 1
        if i >= len(source):
            break  # unterminated start tag: drop the rest
        attr_text = source[match.end():i]
        pos = i + 1
        if attr_text.rstrip().endswith("/"):
            attr_text, body = attr_text.rstrip()[:-1], ""
        else:
            end = _BLOCK_END_RE.search(source, pos)
            if not end:
                break  # unterminated block: drop it
            body = source[pos:end.start()]
            pos = end.end()
        blocks.append((attr_text, body))
        out.append(f'<block {_BLOCK_MARK}="{len(blocks) - 1}" {attr_text}></block>')
    return "".join(out), blocks


# ---------------------------------------------------------------- attributes

def _clean_int(value: str, low: int, high: int) -> Optional[str]:
    if not _INT_RE.match(value.strip()):
        return None
    return str(max(low, min(high, int(float(value)))))


def _clean_color(value: str) -> Optional[str]:
    value = value.strip()
    if value.lower() in COLOR_TOKENS:
        return value.lower()
    return value.lower() if _HEX_RE.match(value) else None


def _clean_font(value: str) -> Optional[str]:
    value = value.strip()
    if value.lower() in FONT_ROLES:
        return value.lower()
    return SAFE_FONTS.get(value.lower())


def _clean_weight(value: str) -> Optional[str]:
    value = value.strip().lower()
    if value in {"normal", "bold"}:
        return value
    return value if value in {str(n) for n in range(100, 1000, 100)} else None


def _choice(options: set) -> Callable[[str], Optional[str]]:
    return lambda value: value.strip().lower() if value.strip().lower() in options else None


def _clean_label(value: str) -> Optional[str]:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:300] if value else None


def _clean_hidden(value: str) -> Optional[str]:
    return "true" if value.strip().lower() == "true" else None


def _clean_note(text: str) -> str:
    """Notepad body: control chars (except newline/tab) dropped, trimmed, 5000 chars max."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text.strip()[:MAX_NOTE_CHARS].rstrip()


def _clean_embed_ref(value: str) -> Optional[str]:
    value = value.strip()
    if not value.startswith("embed:"):
        return None
    ref = value[len("embed:"):]
    return value if _EMBED_REF_RE.match(ref) else None


def _clean_https(value: str) -> Optional[str]:
    value = value.strip()
    if len(value) > 2000 or re.search(r"[\s\x00-\x1f\x7f<>\"']", value):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme.lower() == "https" and parsed.netloc and "@" not in parsed.netloc else None


def _clean_video_src(value: str) -> Optional[str]:
    value = value.strip()
    if value.startswith("embed:"):
        return _clean_embed_ref(value)
    if value.startswith("youtube:") and _YOUTUBE_RE.match(value[8:]):
        return value
    if value.startswith("vimeo:") and _VIMEO_RE.match(value[6:]):
        return value
    return None


def _geom(low: int, high: int) -> Callable[[str], Optional[str]]:
    return lambda value: _clean_int(value, low, high)


_COMMON: Dict[str, Callable[[str], Optional[str]]] = {
    "x": _geom(0, CANVAS_WIDTH - 1), "y": _geom(0, 4000),
    "w": _geom(1, CANVAS_WIDTH), "h": _geom(1, 4000),
    "animate": _choice(ANIMATIONS), "step": _geom(0, 99),
}
_SCHEMAS: Dict[str, Dict[str, Callable[[str], Optional[str]]]] = {
    "text": {
        "role": _choice(TEXT_ROLES), "font": _clean_font, "size": _geom(8, 400),
        "color": _clean_color, "align": _choice(ALIGNS), "weight": _clean_weight,
    },
    "image": {"src": _clean_embed_ref, "alt": _clean_label, "fit": _choice({"cover", "contain"})},
    "video": {"src": _clean_video_src, "alt": _clean_label},
    "shape": {"kind": _choice(SHAPE_KINDS), "fill": _clean_color, "stroke": _clean_color},
    "notepad": {"title": _clean_label, "hidden": _clean_hidden},
    "todo": {"title": _clean_label, "hidden": _clean_hidden},
    "link": {"href": _clean_https},
    "block": {"title": _clean_label},
}
_ORDER = {
    "text": ("role", "font", "size", "color", "align", "weight"),
    "image": ("src", "alt", "fit"), "video": ("src", "alt"),
    "shape": ("kind", "fill", "stroke"), "notepad": ("title", "hidden"), "todo": ("title", "hidden"),
    "link": ("href",), "block": ("title",),
}


def _attrs_for(node: _Node, tag: str, ids: "_IdAllocator") -> Dict[str, str]:
    """Validated attributes in stable order, with id first."""
    clean: Dict[str, str] = {"id": ids.element(node.attrs.get("id"))}
    schema = _SCHEMAS[tag]
    for name in ("x", "y", "w", "h"):
        cleaned = _COMMON[name](node.attrs[name]) if name in node.attrs else None
        if cleaned is not None:
            clean[name] = cleaned
    for name in _ORDER[tag]:
        cleaned = schema[name](node.attrs[name]) if name in node.attrs else None
        if cleaned is not None:
            clean[name] = cleaned
    for name in ("animate", "step"):
        cleaned = _COMMON[name](node.attrs[name]) if name in node.attrs else None
        if cleaned is not None:
            clean[name] = cleaned
    return clean


def _clamp_box(attrs: Dict[str, str], height: int) -> None:
    if "x" in attrs:
        attrs["x"] = str(min(int(attrs["x"]), CANVAS_WIDTH - 1))
    if "y" in attrs:
        attrs["y"] = str(min(int(attrs["y"]), height - 1))
    if "w" in attrs:
        attrs["w"] = str(min(int(attrs["w"]), CANVAS_WIDTH - int(attrs.get("x", "0"))))
    if "h" in attrs:
        attrs["h"] = str(min(int(attrs["h"]), height - int(attrs.get("y", "0"))))


def _fmt(tag: str, attrs: Dict[str, str], closing: str) -> str:
    rendered = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in attrs.items())
    return f"<{tag}{rendered}{closing}"


class _IdAllocator:
    def __init__(self, source_ids: set) -> None:
        self._used: set = set()
        self._source_ids = source_ids
        self._counters = {"s": 0, "e": 0}

    def _take(self, prefix: str, wanted: Optional[str]) -> str:
        if wanted and _ID_RE.match(wanted) and wanted not in self._used:
            self._used.add(wanted)
            return wanted
        while True:
            self._counters[prefix] += 1
            candidate = f"{prefix}{self._counters[prefix]}"
            if candidate not in self._used and candidate not in self._source_ids:
                self._used.add(candidate)
                return candidate

    def slide(self, wanted: Optional[str]) -> str:
        return self._take("s", wanted)

    def element(self, wanted: Optional[str]) -> str:
        return self._take("e", wanted)


# ------------------------------------------------------------------- content

def _flatten(children: List[Union[_Node, str]]) -> List[Union[_Node, str]]:
    """Unwrap unknown non-dangerous elements, drop dangerous subtrees."""
    flat: List[Union[_Node, str]] = []
    for child in children:
        if isinstance(child, str):
            flat.append(child)
        elif child.tag in DANGEROUS_TAGS:
            continue
        else:
            flat.append(child)
    return flat


def _plain_text(children: List[Union[_Node, str]]) -> str:
    parts: List[str] = []
    for child in children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in DANGEROUS_TAGS:
            parts.append(_plain_text(child.children))
    return "".join(parts)


def _rich_text(children: List[Union[_Node, str]]) -> str:
    parts: List[str] = []
    for child in children:
        if isinstance(child, str):
            parts.append(html.escape(re.sub(r"\s+", " ", child), quote=False))
        elif child.tag in DANGEROUS_TAGS:
            continue
        elif child.tag == "br":
            parts.append("<br/>")
        elif child.tag in INLINE_TAGS:
            parts.append(f"<{child.tag}>{_rich_text(child.children)}</{child.tag}>")
        else:
            parts.append(_rich_text(child.children))
    return "".join(parts)


def _tidy_inline(markup: str) -> str:
    markup = re.sub(r"(<(?:ul|ol)>)\s+|\s+(</(?:ul|ol)>)|(</li>)\s+(?=<li>)", r"\1\2\3", markup)
    return markup.strip()


def _collect(children: List[Union[_Node, str]], tag: str) -> List[_Node]:
    found: List[_Node] = []
    for child in children:
        if isinstance(child, str) or child.tag in DANGEROUS_TAGS:
            continue
        if child.tag == tag:
            found.append(child)
        else:
            found.extend(_collect(child.children, tag))
    return found


def _element_lines(
    node: _Node, blocks: List[Tuple[str, str]], ids: _IdAllocator, height: int
) -> Optional[str]:
    tag = node.tag
    if tag not in ELEMENT_TAGS:
        return None
    if tag == "video":
        raw = node.attrs.get("src", "").strip()
        if _clean_video_src(raw) is None:
            link_href = _clean_https(raw)
            if link_href is None:
                return None
            node = _Node("link", {**node.attrs, "href": link_href})
            node.children = [node.attrs.get("alt") or link_href]
            tag = "link"
    if tag == "block":
        index = node.attrs.get(_BLOCK_MARK, "")
        if not index.isdigit() or int(index) >= len(blocks):
            return None
        attrs = _attrs_for(_block_node(blocks[int(index)][0]), "block", ids)
        _clamp_box(attrs, height)
        return _fmt("block", attrs, ">") + blocks[int(index)][1] + "</block>"
    attrs = _attrs_for(node, tag, ids)
    if tag in {"image", "video"} and "src" not in attrs:
        return None
    if tag == "link" and "href" not in attrs:
        return None
    _clamp_box(attrs, height)
    if tag == "text":
        return _fmt(tag, attrs, ">") + _tidy_inline(_rich_text(node.children)) + "</text>"
    if tag == "link":
        label = html.escape(re.sub(r"\s+", " ", _plain_text(node.children)).strip()[:300], quote=False)
        return _fmt(tag, attrs, ">") + label + "</link>"
    if tag == "todo":
        items = []
        for item in _collect(node.children, "item"):
            done = "true" if item.attrs.get("done", "").strip().lower() == "true" else "false"
            label = html.escape(re.sub(r"\s+", " ", _plain_text(item.children)).strip()[:300], quote=False)
            items.append(f'<item done="{done}">{label}</item>')
        return _fmt(tag, attrs, ">") + "".join(items) + "</todo>"
    if tag == "notepad":
        body = _clean_note(_plain_text(node.children))
        if body:
            return _fmt(tag, attrs, ">") + html.escape(body, quote=False) + "</notepad>"
    return _fmt(tag, attrs, "/>")


def _block_node(attr_text: str) -> _Node:
    parser = _TreeBuilder()
    parser.feed(f"<block {attr_text}>")
    parser.close()
    return parser.root.children[0] if parser.root.children and isinstance(parser.root.children[0], _Node) else _Node("block", {})


def _all_ids(node: _Node) -> set:
    found = {node.attrs["id"]} if "id" in node.attrs else set()
    for child in node.children:
        if isinstance(child, _Node):
            found |= _all_ids(child)
    return found


def _find_deck(root: _Node) -> _Node:
    for child in _flatten(root.children):
        if isinstance(child, _Node):
            if child.tag == "deck":
                return child
            nested = _find_deck(child)
            if nested.tag == "deck":
                return nested
    return root


def _slides_of(deck: _Node) -> List[_Node]:
    return _collect(deck.children, "slide")


def _slide_children(slide: _Node) -> List[_Node]:
    """Elements of a slide, unwrapping unknown wrappers but not nested slides."""
    found: List[_Node] = []
    for child in slide.children:
        if isinstance(child, str) or child.tag in DANGEROUS_TAGS:
            continue
        if child.tag in ELEMENT_TAGS or child.tag == "notes":
            found.append(child)
        elif child.tag not in {"slide", "deck"}:
            found.extend(_slide_children(child))
    return found


def normalise_slides_markup(source: str) -> NormalisedDeck:
    """Parse, sanitise and re-serialise a slides deck.

    Raises SlidesMarkupError when the input is empty, too large or holds no slide.
    """
    if not isinstance(source, str) or not source.strip():
        raise SlidesMarkupError("slides markup is empty")
    if len(source) > MAX_SOURCE_CHARS:
        raise SlidesMarkupError("slides markup is too large")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    stripped, blocks = _extract_blocks(source)
    parser = _TreeBuilder()
    parser.feed(stripped)
    parser.close()
    deck = _find_deck(parser.root)
    slides = _slides_of(deck)
    if not slides:
        raise SlidesMarkupError("slides markup contains no slide")
    slides = slides[:MAX_SLIDES]

    aspect = deck.attrs.get("aspect", "").strip()
    aspect = aspect if aspect in ASPECT_HEIGHTS else DEFAULT_ASPECT
    height = ASPECT_HEIGHTS[aspect]
    title = re.sub(r"\s+", " ", deck.attrs.get("title", "")).strip()[:200]
    template = deck.attrs.get("template", "").strip()
    template = template if _TEMPLATE_RE.match(template) else DEFAULT_TEMPLATE
    ids = _IdAllocator(_all_ids(deck) | {_block_node(a).attrs.get("id", "") for a, _ in blocks})

    deck_attrs = {"title": title, "aspect": aspect, "template": template}
    lines = [_fmt("deck", deck_attrs, ">")]
    for slide in slides:
        slide_attrs: Dict[str, str] = {"id": ids.slide(slide.attrs.get("id"))}
        layout = slide.attrs.get("layout", "").strip().lower()
        if _LAYOUT_RE.match(layout):
            slide_attrs["layout"] = layout
        transition = slide.attrs.get("transition", "").strip().lower()
        if transition in TRANSITIONS:
            slide_attrs["transition"] = transition
        lines.append("  " + _fmt("slide", slide_attrs, ">"))
        notes = ""
        count = 0
        for node in _slide_children(slide):
            if node.tag == "notes":
                notes = notes or _plain_text(node.children).strip()
                continue
            count += 1
            if count > MAX_ELEMENTS_PER_SLIDE:
                break
            rendered = _element_lines(node, blocks, ids, height)
            if rendered is not None:
                lines.append("    " + rendered)
        if notes:
            lines.append("    <notes>" + html.escape(notes[:5000], quote=False) + "</notes>")
        lines.append("  </slide>")
    lines.append("</deck>")
    return NormalisedDeck("\n".join(lines) + "\n", title, len(slides), aspect)
