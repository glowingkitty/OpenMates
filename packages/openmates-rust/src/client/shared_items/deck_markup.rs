//! Plain deck model and the normalised slides markup it is read from and written as.
//! Shared client core. The writer reproduces `normalise_slides_markup` output byte for byte
//! (`backend/shared/python_utils/slides_markup.py`, grammar in
//! `docs/architecture/apps/slides-format.md`); the reader accepts only that normalised form
//! and is not a sanitiser for untrusted assistant output (the backend normaliser stays that).

use super::deck_error::DeckError;
use super::deck_inline::parse_inline;
use super::deck_values::{
    DeckAspect, ElementKind, GEOMETRY, clamp_box, clean_attribute, clean_layout, clean_note_text,
    clean_title, clean_transition, escape_attr, escape_text, is_valid_id, is_valid_template,
    unescape,
};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::sync::LazyLock;

/// Whole deck: what the markup holds and what the view model renders.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeckModel {
    /// Deck title (may be empty).
    pub title: String,
    /// Aspect ratio; fixes the canvas height.
    pub aspect: DeckAspect,
    /// `builtin:<name>` or `library:<ref>`.
    pub template: String,
    /// Slides in display order.
    pub slides: Vec<SlideModel>,
}

/// One slide.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SlideModel {
    /// Stable slide id (`s<n>` for generated ids).
    pub id: String,
    /// Template layout name.
    pub layout: Option<String>,
    /// `none`, `fade` or `slide`.
    pub transition: Option<String>,
    /// Speaker notes; empty when none.
    pub notes: String,
    /// Elements in paint order.
    pub elements: Vec<ElementModel>,
}

/// One positioned element.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ElementModel {
    /// Stable element id (`e<n>` for generated ids).
    pub id: String,
    /// Element kind (markup tag).
    pub kind: ElementKind,
    /// Left edge in canvas units, when set.
    pub x: Option<u32>,
    /// Top edge in canvas units, when set.
    pub y: Option<u32>,
    /// Width in canvas units, when set.
    pub w: Option<u32>,
    /// Height in canvas units, when set.
    pub h: Option<u32>,
    /// Every other attribute (`role`, `font`, `src`, `animate`, ...), already validated.
    pub attributes: BTreeMap<String, String>,
    /// Content between the start and end tag.
    pub content: ElementContent,
}

/// Content of an element, by kind.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", content = "value", rename_all = "snake_case")]
pub enum ElementContent {
    /// Void elements (`image`, `video`, `shape`).
    Empty,
    /// `notepad`: plain text body; empty text is written as a self-closing tag.
    Plain(String),
    /// `text`: normalised inline markup (`b i u s br ul ol li`, escaped text).
    RichText(String),
    /// `link`: plain label.
    Label(String),
    /// `todo`: items in order.
    Items(Vec<TodoItem>),
    /// `block`: verbatim HTML/CSS/JS, never interpreted by the core.
    Verbatim(String),
}

/// One to-do item.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TodoItem {
    /// Plain item text.
    pub text: String,
    /// Checked state.
    pub done: bool,
}

impl ElementModel {
    /// All attributes including geometry, as markup strings.
    pub(crate) fn all_attributes(&self) -> BTreeMap<String, String> {
        let mut attrs = self.attributes.clone();
        for (name, value) in GEOMETRY.iter().zip([self.x, self.y, self.w, self.h]) {
            if let Some(value) = value {
                attrs.insert((*name).to_string(), value.to_string());
            }
        }
        attrs
    }

    /// Builds an element from markup attributes, splitting off geometry.
    pub(crate) fn from_attributes(
        id: String,
        kind: ElementKind,
        mut attrs: BTreeMap<String, String>,
        content: ElementContent,
    ) -> Self {
        let mut take = |name: &str| attrs.remove(name).and_then(|v| v.parse::<u32>().ok());
        let (x, y, w, h) = (take("x"), take("y"), take("w"), take("h"));
        Self {
            id,
            kind,
            x,
            y,
            w,
            h,
            attributes: attrs,
            content,
        }
    }
}

/// Parses normalised slides markup.
///
/// # Errors
/// [`DeckError::MarkupNotNormalised`] when the input is not exactly what the backend
/// normaliser writes (including when writing the parsed model back would differ by one
/// byte), [`DeckError::NoSlides`] for a deck without slides.
pub fn parse_deck_markup(markup: &str) -> Result<DeckModel, DeckError> {
    let model = Parser {
        src: markup,
        pos: 0,
    }
    .deck()?;
    if model.slides.is_empty() {
        return Err(DeckError::NoSlides);
    }
    // The parser checks structure and values; this guard pins byte stability (attribute
    // order, escaping, whitespace) so a hydrated replica always saves the same bytes.
    if serialise_deck_markup(&model) != markup {
        return Err(DeckError::markup(
            0,
            "re-serialised markup differs from input",
        ));
    }
    Ok(model)
}

/// Writes a deck as normalised slides markup (one element per line, stable attribute
/// order `id`, `x y w h`, kind attributes, `animate step`; trailing newline).
pub fn serialise_deck_markup(model: &DeckModel) -> String {
    let mut out = format!(
        "<deck title=\"{}\" aspect=\"{}\" template=\"{}\">\n",
        escape_attr(&model.title),
        model.aspect.as_str(),
        escape_attr(&model.template)
    );
    for slide in &model.slides {
        out.push_str("  <slide id=\"");
        out.push_str(&escape_attr(&slide.id));
        out.push('"');
        for (name, value) in [("layout", &slide.layout), ("transition", &slide.transition)] {
            if let Some(value) = value {
                out.push_str(&format!(" {name}=\"{}\"", escape_attr(value)));
            }
        }
        out.push_str(">\n");
        for element in &slide.elements {
            out.push_str("    ");
            write_element(element, &mut out);
            out.push('\n');
        }
        if !slide.notes.is_empty() {
            out.push_str("    <notes>");
            out.push_str(&escape_text(&slide.notes));
            out.push_str("</notes>\n");
        }
        out.push_str("  </slide>\n");
    }
    out.push_str("</deck>\n");
    out
}

fn write_element(element: &ElementModel, out: &mut String) {
    let tag = element.kind.as_str();
    let attrs = element.all_attributes();
    out.push('<');
    out.push_str(tag);
    out.push_str(&format!(" id=\"{}\"", escape_attr(&element.id)));
    for name in element.kind.ordered_attributes() {
        if let Some(value) = attrs.get(name) {
            out.push_str(&format!(" {name}=\"{}\"", escape_attr(value)));
        }
    }
    let empty_note = matches!(&element.content, ElementContent::Plain(text) if text.is_empty());
    if element.kind.is_void() || empty_note {
        out.push_str("/>");
        return;
    }
    out.push('>');
    match &element.content {
        ElementContent::RichText(markup) => out.push_str(markup),
        ElementContent::Label(label) => out.push_str(&escape_text(label)),
        ElementContent::Items(items) => {
            for item in items {
                out.push_str(&format!(
                    "<item done=\"{}\">{}</item>",
                    item.done,
                    escape_text(&item.text)
                ));
            }
        }
        ElementContent::Verbatim(body) => out.push_str(body),
        ElementContent::Plain(text) => out.push_str(&escape_text(text)),
        ElementContent::Empty => {}
    }
    out.push_str("</");
    out.push_str(tag);
    out.push('>');
}

static BLOCK_END: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)</block\s*>").expect("static pattern is valid"));

/// Strict reader for the normalised layout; every check names the byte offset.
struct Parser<'a> {
    src: &'a str,
    pos: usize,
}

type Attrs = Vec<(String, String)>;

impl<'a> Parser<'a> {
    fn fail<T>(&self, reason: &'static str) -> Result<T, DeckError> {
        Err(DeckError::markup(self.pos, reason))
    }

    fn eat(&mut self, literal: &str) -> bool {
        if self.src[self.pos..].starts_with(literal) {
            self.pos += literal.len();
            true
        } else {
            false
        }
    }

    fn expect(&mut self, literal: &str, reason: &'static str) -> Result<(), DeckError> {
        if self.eat(literal) {
            Ok(())
        } else {
            self.fail(reason)
        }
    }

    /// Raw text up to `literal`, consuming the literal.
    fn until(&mut self, literal: &str, reason: &'static str) -> Result<&'a str, DeckError> {
        let Some(index) = self.src[self.pos..].find(literal) else {
            return self.fail(reason);
        };
        let raw = &self.src[self.pos..self.pos + index];
        self.pos += index + literal.len();
        Ok(raw)
    }

    fn name(&mut self) -> &'a str {
        let rest = &self.src[self.pos..];
        let len = rest
            .bytes()
            .take_while(|b| b.is_ascii_lowercase() || *b == b'-')
            .count();
        self.pos += len;
        &rest[..len]
    }

    /// `<name( key="value")*>` or `.../>`; returns (name, attributes, self-closing).
    fn start_tag(&mut self) -> Result<(&'a str, Attrs, bool), DeckError> {
        self.expect("<", "expected a tag")?;
        let name = self.name();
        let mut attrs = Attrs::new();
        loop {
            if self.eat("/>") {
                return Ok((name, attrs, true));
            }
            if self.eat(">") {
                return Ok((name, attrs, false));
            }
            self.expect(" ", "expected an attribute")?;
            let key = self.name().to_string();
            self.expect("=\"", "expected a quoted attribute value")?;
            let raw = self.until("\"", "unterminated attribute value")?;
            let Some(value) = unescape(raw) else {
                return self.fail("unknown character reference");
            };
            if attrs.iter().any(|(existing, _)| *existing == key) {
                return self.fail("duplicate attribute");
            }
            attrs.push((key, value));
        }
    }

    fn deck(mut self) -> Result<DeckModel, DeckError> {
        let (name, attrs, self_closing) = self.start_tag()?;
        if name != "deck" || self_closing {
            return self.fail("expected <deck>");
        }
        let get = |key: &str| attrs.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone());
        let (Some(title), Some(aspect), Some(template)) =
            (get("title"), get("aspect"), get("template"))
        else {
            return self.fail("deck needs title, aspect and template");
        };
        let Some(aspect) = DeckAspect::parse(&aspect) else {
            return self.fail("unknown aspect");
        };
        if clean_title(&title) != title || !is_valid_template(&template) {
            return self.fail("invalid deck title or template");
        }
        self.expect("\n", "expected a newline")?;
        let mut ids = HashSet::new();
        let mut slides = Vec::new();
        while !self.eat("</deck>\n") {
            self.expect("  ", "expected a slide")?;
            slides.push(self.slide(aspect, &mut ids)?);
        }
        if self.pos != self.src.len() {
            return self.fail("content after </deck>");
        }
        Ok(DeckModel {
            title,
            aspect,
            template,
            slides,
        })
    }

    fn take_id(&self, id: Option<String>, ids: &mut HashSet<String>) -> Result<String, DeckError> {
        match id {
            Some(id) if is_valid_id(&id) && ids.insert(id.clone()) => Ok(id),
            _ => self.fail("missing, invalid or duplicate id"),
        }
    }

    fn slide(
        &mut self,
        aspect: DeckAspect,
        ids: &mut HashSet<String>,
    ) -> Result<SlideModel, DeckError> {
        let (name, attrs, self_closing) = self.start_tag()?;
        if name != "slide" || self_closing {
            return self.fail("expected <slide>");
        }
        let mut id = None;
        let (mut layout, mut transition) = (None, None);
        for (key, value) in attrs {
            let cleaned = match key.as_str() {
                "id" => Some(value.clone()),
                "layout" => clean_layout(&value),
                "transition" => clean_transition(&value),
                _ => return self.fail("unknown slide attribute"),
            };
            if cleaned.as_deref() != Some(value.as_str()) {
                return self.fail("invalid slide attribute");
            }
            match key.as_str() {
                "id" => id = Some(value),
                "layout" => layout = Some(value),
                _ => transition = Some(value),
            }
        }
        let id = self.take_id(id, ids)?;
        self.expect("\n", "expected a newline")?;
        let mut elements = Vec::new();
        let mut notes = String::new();
        while !self.eat("  </slide>\n") {
            self.expect("    ", "expected an element")?;
            if self.eat("<notes>") {
                let raw = self.until("</notes>", "unterminated notes")?;
                let Some(text) = unescape(raw) else {
                    return self.fail("unknown character reference");
                };
                notes = text;
                self.expect("\n", "expected a newline")?;
                self.expect("  </slide>\n", "notes must be the last line of a slide")?;
                break;
            }
            elements.push(self.element(aspect, ids)?);
            self.expect("\n", "expected a newline")?;
        }
        Ok(SlideModel {
            id,
            layout,
            transition,
            notes,
            elements,
        })
    }

    fn element(
        &mut self,
        aspect: DeckAspect,
        ids: &mut HashSet<String>,
    ) -> Result<ElementModel, DeckError> {
        let (name, attrs, self_closing) = self.start_tag()?;
        let Some(kind) = ElementKind::parse(name) else {
            return self.fail("unknown element");
        };
        if self_closing != kind.is_void() && kind != ElementKind::Notepad {
            return self.fail("wrong void/content form for element");
        }
        let mut id = None;
        let mut clean = BTreeMap::new();
        for (key, value) in attrs {
            if key == "id" {
                id = Some(value);
                continue;
            }
            if !kind.accepts(&key) {
                return self.fail("unknown element attribute");
            }
            if clean_attribute(kind, &key, &value).as_deref() != Some(value.as_str()) {
                return self.fail("invalid element attribute value");
            }
            clean.insert(key, value);
        }
        let id = self.take_id(id, ids)?;
        let mut clamped = clean.clone();
        clamp_box(&mut clamped, aspect.canvas_height());
        if clamped != clean {
            return self.fail("element box is outside the canvas");
        }
        if let Some(required) = kind.required_attribute()
            && !clean.contains_key(required)
        {
            return self.fail("element misses a required attribute");
        }
        let content = if self_closing && kind == ElementKind::Notepad {
            ElementContent::Plain(String::new())
        } else {
            self.content(kind)?
        };
        Ok(ElementModel::from_attributes(id, kind, clean, content))
    }

    fn content(&mut self, kind: ElementKind) -> Result<ElementContent, DeckError> {
        Ok(match kind {
            ElementKind::Text => {
                let raw = self.until("</text>", "unterminated text")?;
                if parse_inline(raw).is_err() {
                    return self.fail("text holds markup outside b i u s br ul ol li");
                }
                ElementContent::RichText(raw.to_string())
            }
            ElementKind::Link => {
                let raw = self.until("</link>", "unterminated link")?;
                let Some(label) = unescape(raw) else {
                    return self.fail("unknown character reference");
                };
                ElementContent::Label(label)
            }
            ElementKind::Todo => {
                let mut items = Vec::new();
                while !self.eat("</todo>") {
                    self.expect("<item done=\"", "expected a to-do item")?;
                    let done = if self.eat("true") {
                        true
                    } else if self.eat("false") {
                        false
                    } else {
                        return self.fail("done must be true or false");
                    };
                    self.expect("\">", "expected end of item tag")?;
                    let raw = self.until("</item>", "unterminated item")?;
                    let Some(text) = unescape(raw) else {
                        return self.fail("unknown character reference");
                    };
                    items.push(TodoItem { text, done });
                }
                ElementContent::Items(items)
            }
            ElementKind::Block => {
                let body = self.until("</block>", "unterminated block")?;
                // The backend cuts a block at the first `</block\s*>` in any case, so a
                // body containing one cannot come from the normaliser.
                if BLOCK_END.is_match(body) {
                    return self.fail("block body contains a block end tag");
                }
                ElementContent::Verbatim(body.to_string())
            }
            ElementKind::Notepad => {
                let raw = self.until("</notepad>", "unterminated notepad")?;
                let Some(text) = unescape(raw) else {
                    return self.fail("unknown character reference");
                };
                if text.is_empty() || clean_note_text(&text) != text {
                    return self.fail("notepad text is empty or not normalised");
                }
                ElementContent::Plain(text)
            }
            ElementKind::Image | ElementKind::Video | ElementKind::Shape => ElementContent::Empty,
        })
    }
}
