//! Slides vocabulary and value cleaners: element kinds, attribute order, clamping, escaping.
//! Shared client core. Mirrors the whitelist of `backend/shared/python_utils/slides_markup.py`
//! (`_SCHEMAS`, `_ORDER`, `_clamp_box`, `html.escape`) so the core writes exactly what the
//! backend normaliser writes. Spec: `specifications/features/slides/`, grammar in
//! `docs/architecture/apps/slides-format.md`.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Canvas width in canvas units; the height follows the deck aspect.
pub const CANVAS_WIDTH: u32 = 1920;
pub(crate) const MAX_SLIDES: usize = 200;
pub(crate) const MAX_ELEMENTS_PER_SLIDE: usize = 200;
pub(crate) const MAX_NOTES_CHARS: usize = 5000;
pub(crate) const MAX_LABEL_CHARS: usize = 300;
pub(crate) const MAX_TITLE_CHARS: usize = 200;
pub(crate) const DEFAULT_TEMPLATE: &str = "builtin:plain";

/// Geometry attributes, always written right after `id`.
pub(crate) const GEOMETRY: [&str; 4] = ["x", "y", "w", "h"];
/// Build-step attributes, always written last.
pub(crate) const TRAILING: [&str; 2] = ["animate", "step"];

const COLOR_TOKENS: [&str; 6] = [
    "background",
    "foreground",
    "accent",
    "accent-2",
    "muted",
    "surface",
];
const SAFE_FONTS: [&str; 11] = [
    "Arial",
    "Helvetica",
    "Georgia",
    "Times New Roman",
    "Courier New",
    "Verdana",
    "Trebuchet MS",
    "system-ui",
    "serif",
    "sans-serif",
    "monospace",
];
const TEXT_ROLES: [&str; 5] = ["title", "subtitle", "body", "caption", "quote"];
const ALIGNS: [&str; 4] = ["left", "center", "right", "justify"];
const SHAPE_KINDS: [&str; 4] = ["rect", "ellipse", "line", "triangle"];
const ANIMATIONS: [&str; 3] = ["fade", "slide-in", "appear"];
const TRANSITIONS: [&str; 3] = ["none", "fade", "slide"];
const FITS: [&str; 2] = ["cover", "contain"];

/// Deck aspect ratio; fixes the canvas height (the width is always 1920).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum DeckAspect {
    /// 16:9, 1080 high (the default).
    #[serde(rename = "16:9")]
    Wide,
    /// 16:10, 1200 high.
    #[serde(rename = "16:10")]
    Laptop,
    /// 4:3, 1440 high.
    #[serde(rename = "4:3")]
    Classic,
}

impl DeckAspect {
    /// Markup value (`16:9`, `16:10`, `4:3`).
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Wide => "16:9",
            Self::Laptop => "16:10",
            Self::Classic => "4:3",
        }
    }

    /// Canvas height in canvas units.
    pub fn canvas_height(self) -> u32 {
        match self {
            Self::Wide => 1080,
            Self::Laptop => 1200,
            Self::Classic => 1440,
        }
    }

    /// Parses an exact markup value.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "16:9" => Some(Self::Wide),
            "16:10" => Some(Self::Laptop),
            "4:3" => Some(Self::Classic),
            _ => None,
        }
    }
}

/// Positioned element kinds of the slides grammar.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ElementKind {
    /// Rich text box (`b i u s br ul ol li`).
    Text,
    /// Image from a child embed (`src="embed:<ref>"`).
    Image,
    /// Video from an embed, YouTube or Vimeo.
    Video,
    /// Rectangle, ellipse, line or triangle.
    Shape,
    /// Notepad filled in during a presentation.
    Notepad,
    /// To-do list with checkable items.
    Todo,
    /// https link card with a plain label.
    Link,
    /// Sandboxed free HTML/CSS/JS, stored byte-for-byte.
    Block,
}

impl ElementKind {
    /// Markup tag name.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Text => "text",
            Self::Image => "image",
            Self::Video => "video",
            Self::Shape => "shape",
            Self::Notepad => "notepad",
            Self::Todo => "todo",
            Self::Link => "link",
            Self::Block => "block",
        }
    }

    /// Kind of a markup tag name.
    pub fn parse(tag: &str) -> Option<Self> {
        Some(match tag {
            "text" => Self::Text,
            "image" => Self::Image,
            "video" => Self::Video,
            "shape" => Self::Shape,
            "notepad" => Self::Notepad,
            "todo" => Self::Todo,
            "link" => Self::Link,
            "block" => Self::Block,
            _ => return None,
        })
    }

    /// Elements written as `<tag .../>` without content.
    pub(crate) fn is_void(self) -> bool {
        matches!(
            self,
            Self::Image | Self::Video | Self::Shape | Self::Notepad
        )
    }

    /// Notepad and to-do: filled in during a presentation, cleared by Clear / Clear all.
    pub fn is_interactive(self) -> bool {
        matches!(self, Self::Notepad | Self::Todo)
    }

    /// Kind-specific attributes in normaliser output order (`_ORDER`).
    pub(crate) fn attributes(self) -> &'static [&'static str] {
        match self {
            Self::Text => &["role", "font", "size", "color", "align", "weight"],
            Self::Image => &["src", "alt", "fit"],
            Self::Video => &["src", "alt"],
            Self::Shape => &["kind", "fill", "stroke"],
            Self::Notepad | Self::Todo | Self::Block => &["title"],
            Self::Link => &["href"],
        }
    }

    /// Attribute the element is dropped without (`image`/`video` src, `link` href).
    pub(crate) fn required_attribute(self) -> Option<&'static str> {
        match self {
            Self::Image | Self::Video => Some("src"),
            Self::Link => Some("href"),
            _ => None,
        }
    }

    /// Every attribute name this kind accepts besides `id`, in output order.
    pub(crate) fn ordered_attributes(self) -> impl Iterator<Item = &'static str> {
        GEOMETRY
            .into_iter()
            .chain(self.attributes().iter().copied())
            .chain(TRAILING)
    }

    pub(crate) fn accepts(self, name: &str) -> bool {
        self.ordered_attributes().any(|known| known == name)
    }
}

/// Cleans one attribute value like the backend normaliser; `None` means the value is
/// invalid (the normaliser would drop it). Geometry is range-checked here and clamped to
/// the canvas by [`clamp_box`].
pub(crate) fn clean_attribute(kind: ElementKind, name: &str, raw: &str) -> Option<String> {
    match name {
        "x" => clean_int(raw, 0, i64::from(CANVAS_WIDTH) - 1),
        "y" => clean_int(raw, 0, 4000),
        "w" => clean_int(raw, 1, i64::from(CANVAS_WIDTH)),
        "h" => clean_int(raw, 1, 4000),
        "animate" => choice(raw, &ANIMATIONS),
        "step" => clean_int(raw, 0, 99),
        _ => match (kind, name) {
            (ElementKind::Text, "role") => choice(raw, &TEXT_ROLES),
            (ElementKind::Text, "font") => clean_font(raw),
            (ElementKind::Text, "size") => clean_int(raw, 8, 400),
            (ElementKind::Text, "color") | (ElementKind::Shape, "fill" | "stroke") => {
                clean_color(raw)
            }
            (ElementKind::Text, "align") => choice(raw, &ALIGNS),
            (ElementKind::Text, "weight") => clean_weight(raw),
            (ElementKind::Image, "src") => clean_embed_ref(raw),
            (ElementKind::Image | ElementKind::Video, "alt") => clean_label(raw),
            (ElementKind::Image, "fit") => choice(raw, &FITS),
            (ElementKind::Video, "src") => clean_video_src(raw),
            (ElementKind::Shape, "kind") => choice(raw, &SHAPE_KINDS),
            (ElementKind::Notepad | ElementKind::Todo | ElementKind::Block, "title") => {
                clean_label(raw)
            }
            (ElementKind::Link, "href") => clean_https(raw),
            _ => None,
        },
    }
}

/// `_clamp_box`: keeps the box inside the canvas of the given height. Applied on every
/// write and again on every read, because concurrent per-property writes (x from one
/// member, w from another) can combine into a box the normaliser would clamp.
pub(crate) fn clamp_box(attrs: &mut BTreeMap<String, String>, height: u32) {
    let int = |attrs: &BTreeMap<String, String>, key: &str| -> Option<i64> {
        attrs.get(key).and_then(|v| v.parse::<i64>().ok())
    };
    let height = i64::from(height);
    let width = i64::from(CANVAS_WIDTH);
    if let Some(x) = int(attrs, "x") {
        attrs.insert("x".into(), x.min(width - 1).to_string());
    }
    if let Some(y) = int(attrs, "y") {
        attrs.insert("y".into(), y.min(height - 1).to_string());
    }
    let x = int(attrs, "x").unwrap_or(0);
    let y = int(attrs, "y").unwrap_or(0);
    if let Some(w) = int(attrs, "w") {
        attrs.insert("w".into(), w.min(width - x).to_string());
    }
    if let Some(h) = int(attrs, "h") {
        attrs.insert("h".into(), h.min(height - y).to_string());
    }
}

/// `_INT_RE` + `int(float(v))` + range clamp.
pub(crate) fn clean_int(raw: &str, low: i64, high: i64) -> Option<String> {
    let value = raw.trim();
    let (negative, body) = match value.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, value),
    };
    let (int_part, frac) = match body.split_once('.') {
        Some((int_part, frac)) => (int_part, Some(frac)),
        None => (body, None),
    };
    let digits_ok = |s: &str| !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit());
    if !digits_ok(int_part) || int_part.len() > 6 || frac.is_some_and(|f| !digits_ok(f)) {
        return None;
    }
    // At most 6 digits, so this cannot overflow; truncation toward zero like int(float()).
    let magnitude: i64 = int_part.parse().ok()?;
    let number = if negative { -magnitude } else { magnitude };
    Some(number.clamp(low, high).to_string())
}

fn choice(raw: &str, options: &[&str]) -> Option<String> {
    let value = raw.trim().to_lowercase();
    options.contains(&value.as_str()).then_some(value)
}

fn clean_color(raw: &str) -> Option<String> {
    let value = raw.trim().to_lowercase();
    if COLOR_TOKENS.contains(&value.as_str()) {
        return Some(value);
    }
    let hex = value.strip_prefix('#')?;
    (matches!(hex.len(), 3 | 4 | 6 | 8) && hex.bytes().all(|b| b.is_ascii_hexdigit()))
        .then_some(value)
}

fn clean_font(raw: &str) -> Option<String> {
    let value = raw.trim().to_lowercase();
    if value == "heading" || value == "body" {
        return Some(value);
    }
    SAFE_FONTS
        .iter()
        .find(|font| font.to_lowercase() == value)
        .map(|font| (*font).to_string())
}

fn clean_weight(raw: &str) -> Option<String> {
    let value = raw.trim().to_lowercase();
    let numeric =
        value.len() == 3 && value.ends_with("00") && matches!(value.as_bytes()[0], b'1'..=b'9');
    (value == "normal" || value == "bold" || numeric).then_some(value)
}

/// `_clean_label`: whitespace collapsed, trimmed, at most 300 characters, never empty.
pub(crate) fn clean_label(raw: &str) -> Option<String> {
    let value = truncate_chars(collapse_whitespace(raw).trim(), MAX_LABEL_CHARS);
    (!value.is_empty()).then_some(value)
}

fn token_ok(value: &str, min: usize, max: usize, extra: &[u8]) -> bool {
    (min..=max).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || extra.contains(&b))
}

fn clean_embed_ref(raw: &str) -> Option<String> {
    let value = raw.trim();
    let reference = value.strip_prefix("embed:")?;
    token_ok(reference, 1, 128, b"._-").then(|| value.to_string())
}

fn clean_video_src(raw: &str) -> Option<String> {
    let value = raw.trim();
    if value.starts_with("embed:") {
        return clean_embed_ref(value);
    }
    if let Some(id) = value.strip_prefix("youtube:") {
        return token_ok(id, 6, 20, b"_-").then(|| value.to_string());
    }
    if let Some(id) = value.strip_prefix("vimeo:") {
        let digits = (3..=12).contains(&id.len()) && id.bytes().all(|b| b.is_ascii_digit());
        return digits.then(|| value.to_string());
    }
    None
}

/// `_clean_https`: https only, a host, no credentials, no whitespace or quotes.
fn clean_https(raw: &str) -> Option<String> {
    let value = raw.trim();
    let forbidden = |c: char| c.is_whitespace() || c.is_control() || "<>\"'".contains(c);
    if value.chars().count() > 2000 || value.chars().any(forbidden) {
        return None;
    }
    let (scheme, rest) = value.split_once("://")?;
    if !scheme.eq_ignore_ascii_case("https") {
        return None;
    }
    let host = rest.split(['/', '?', '#']).next().unwrap_or_default();
    (!host.is_empty() && !host.contains('@')).then(|| value.to_string())
}

/// `^[a-z][a-z0-9-]{0,31}$`: slide and element ids.
pub(crate) fn is_valid_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (1..=32).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}

/// Slide layout name after trim + lowercase (`^[a-z0-9][a-z0-9-]{0,39}$`).
pub(crate) fn clean_layout(raw: &str) -> Option<String> {
    let value = raw.trim().to_lowercase();
    let bytes = value.as_bytes();
    let ok = (1..=40).contains(&bytes.len())
        && (bytes[0].is_ascii_lowercase() || bytes[0].is_ascii_digit())
        && bytes
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-');
    ok.then_some(value)
}

/// Slide transition after trim + lowercase.
pub(crate) fn clean_transition(raw: &str) -> Option<String> {
    choice(raw, &TRANSITIONS)
}

/// `^(builtin|library):[A-Za-z0-9._-]{1,64}$`.
pub(crate) fn is_valid_template(value: &str) -> bool {
    let name = value
        .strip_prefix("builtin:")
        .or_else(|| value.strip_prefix("library:"));
    name.is_some_and(|name| token_ok(name, 1, 64, b"._-"))
}

/// Deck title: whitespace collapsed, trimmed, at most 200 characters.
pub(crate) fn clean_title(raw: &str) -> String {
    truncate_chars(collapse_whitespace(raw).trim(), MAX_TITLE_CHARS)
}

/// Speaker notes: trimmed, at most 5000 characters (inner newlines are kept).
pub(crate) fn clean_notes(raw: &str) -> String {
    truncate_chars(raw.trim(), MAX_NOTES_CHARS)
}

/// To-do item or link label: whitespace collapsed, trimmed, at most 300 characters.
pub(crate) fn clean_item_label(raw: &str) -> String {
    truncate_chars(collapse_whitespace(raw).trim(), MAX_LABEL_CHARS)
}

/// `re.sub(r"\s+", " ", value)` without trimming.
pub(crate) fn collapse_whitespace(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    let mut in_space = false;
    for c in raw.chars() {
        if c.is_whitespace() {
            if !in_space {
                out.push(' ');
            }
            in_space = true;
        } else {
            out.push(c);
            in_space = false;
        }
    }
    out
}

pub(crate) fn truncate_chars(value: &str, max: usize) -> String {
    value.chars().take(max).collect()
}

/// `html.escape(value, quote=False)`.
pub(crate) fn escape_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

/// `html.escape(value, quote=True)`.
pub(crate) fn escape_attr(value: &str) -> String {
    escape_text(value)
        .replace('"', "&quot;")
        .replace('\'', "&#x27;")
}

/// Reverses [`escape_attr`]/[`escape_text`]. Normalised markup contains no other
/// character reference, so any other `&...` is refused (`None`).
pub(crate) fn unescape(value: &str) -> Option<String> {
    let mut out = String::with_capacity(value.len());
    let mut rest = value;
    while let Some(index) = rest.find('&') {
        out.push_str(&rest[..index]);
        rest = &rest[index..];
        let (decoded, len) = [
            ("&amp;", '&'),
            ("&lt;", '<'),
            ("&gt;", '>'),
            ("&quot;", '"'),
            ("&#x27;", '\''),
        ]
        .into_iter()
        .find(|(entity, _)| rest.starts_with(entity))
        .map(|(entity, c)| (c, entity.len()))?;
        out.push(decoded);
        rest = &rest[len..];
    }
    out.push_str(rest);
    Some(out)
}
