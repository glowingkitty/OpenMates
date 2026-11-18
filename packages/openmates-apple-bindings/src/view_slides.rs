//! Slides deck read model for the Apple shell: normalised slides markup parsed by the
//! shared client core (`openmates_sdk::client::shared_items`) and mapped to UniFFI
//! records a SwiftUI slide canvas draws directly. Mirrors `SlideCanvas.svelte` +
//! `slidesTemplates.ts` (built-in `plain` template): every element arrives with its
//! final canvas box (layout slots applied) and resolved typography, so Swift does no
//! markup parsing and no layout.

use crate::CoreError;
use openmates_sdk::client::shared_items::deck_values::CANVAS_WIDTH;
use openmates_sdk::client::shared_items::{
    DeckModel, ElementContent, ElementKind, ElementModel, SlideModel, inline_runs,
    parse_deck_markup,
};

/// Margin of the plain template in canvas units.
const MARGIN: u32 = 120;

/// One styled text stretch of a text element.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlideRunRecord {
    /// Text (`"\n"` is a line break; list items carry their marker).
    pub text: String,
    /// Bold.
    pub bold: bool,
    /// Italic.
    pub italic: bool,
    /// Underlined.
    pub underline: bool,
    /// Struck through.
    pub strike: bool,
}

/// One to-do item.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlideTodoItemRecord {
    /// Item text.
    pub label: String,
    /// Checked.
    pub done: bool,
}

/// Element kind (markup tag).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SlideElementKindRecord {
    /// Rich text box.
    Text,
    /// Image of a child embed.
    Image,
    /// Video placeholder.
    Video,
    /// Rectangle, ellipse, line or triangle.
    Shape,
    /// Notepad card.
    Notepad,
    /// To-do card.
    Todo,
    /// Link label.
    Link,
    /// Sandboxed HTML block (not rendered on Apple yet).
    Block,
}

/// One placed element with everything the canvas needs.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlideElementRecord {
    /// Stable element id.
    pub id: String,
    /// Kind.
    pub kind: SlideElementKindRecord,
    /// Final left edge in canvas units.
    pub x: u32,
    /// Final top edge.
    pub y: u32,
    /// Final width.
    pub w: u32,
    /// Final height.
    pub h: u32,
    /// Build step the element appears at (0 = always).
    pub step: u32,
    /// `fade`, `slide-in` or `appear`.
    pub animate: Option<String>,
    /// Hidden notepad/to-do (kept but not drawn).
    pub hidden: bool,
    /// Text: runs; empty for other kinds.
    pub runs: Vec<SlideRunRecord>,
    /// Text: font size in canvas units.
    pub font_size: u32,
    /// Text: bold weight from the slot or attribute.
    pub bold: bool,
    /// Text: italic from the layout slot.
    pub italic: bool,
    /// Text: `left`, `center` or `right`.
    pub align: String,
    /// Text: template colour token or `#hex`; shape: fill token or `#hex`.
    pub color: Option<String>,
    /// Text: explicit font family name, when not the template font; heading role flag below.
    pub font_family: Option<String>,
    /// Text: the title role (template heading font).
    pub is_heading: bool,
    /// Image/video: embed ref (without `embed:`) or provider id.
    pub embed_ref: Option<String>,
    /// Video provider: `embed`, `youtube` or `vimeo`.
    pub video_provider: Option<String>,
    /// Image/video alt text.
    pub alt: String,
    /// Image fit: `cover` or `contain`.
    pub fit: Option<String>,
    /// Shape kind: `rect`, `ellipse`, `line` or `triangle`.
    pub shape_kind: String,
    /// Shape stroke token or `#hex`.
    pub stroke: Option<String>,
    /// Notepad/to-do/block title.
    pub title: String,
    /// Notepad text, link label or block body.
    pub text: String,
    /// Link target.
    pub href: String,
    /// To-do items.
    pub items: Vec<SlideTodoItemRecord>,
}

/// One slide.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlideRecord {
    /// Stable slide id.
    pub id: String,
    /// `none`, `fade` or `slide`.
    pub transition: Option<String>,
    /// Speaker notes.
    pub notes: String,
    /// Elements in paint order.
    pub elements: Vec<SlideElementRecord>,
}

/// Whole deck.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct SlideDeckRecord {
    /// Title (may be empty).
    pub title: String,
    /// `16:9`, `16:10` or `4:3`.
    pub aspect: String,
    /// Canvas width (1920).
    pub width: u32,
    /// Canvas height for the aspect.
    pub height: u32,
    /// Template reference.
    pub template: String,
    /// Slides in order.
    pub slides: Vec<SlideRecord>,
}

/// Parses normalised slides markup into the render records.
///
/// # Errors
/// `CoreError::Invalid` with the deck error code for markup that is not normalised
/// (for example a deck that is still streaming) or holds no slide.
#[uniffi::export]
pub fn slide_deck_from_markup(markup: String) -> Result<SlideDeckRecord, CoreError> {
    let model = parse_deck_markup(&markup).map_err(|error| CoreError::Invalid {
        message: error.code().to_string(),
    })?;
    Ok(map_deck(&model))
}

fn map_deck(model: &DeckModel) -> SlideDeckRecord {
    let height = model.aspect.canvas_height();
    SlideDeckRecord {
        title: model.title.clone(),
        aspect: model.aspect.as_str().to_string(),
        width: CANVAS_WIDTH,
        height,
        template: model.template.clone(),
        slides: model.slides.iter().map(|s| map_slide(s, height)).collect(),
    }
}

/// Typography and box of a template layout slot (`plain` template).
struct Slot {
    rect: (u32, u32, u32, u32),
    size: u32,
    bold: bool,
    align: &'static str,
    italic: bool,
    color: &'static str,
}

fn centered(height: u32, top: f64, h: u32, size: u32, bold: bool, color: &'static str) -> Slot {
    Slot {
        rect: (
            MARGIN + 40,
            (f64::from(height) * top).round() as u32,
            CANVAS_WIDTH - 2 * MARGIN - 80,
            h,
        ),
        size,
        bold,
        align: "center",
        italic: false,
        color,
    }
}

fn plain(rect: (u32, u32, u32, u32), size: u32, color: &'static str) -> Slot {
    Slot {
        rect,
        size,
        bold: false,
        align: "left",
        italic: false,
        color,
    }
}

fn content_box(height: u32) -> (u32, u32, u32, u32) {
    (MARGIN, 280, CANVAS_WIDTH - 2 * MARGIN, height.saturating_sub(400))
}

fn title_top() -> Slot {
    Slot {
        bold: true,
        ..plain((MARGIN, 80, CANVAS_WIDTH - 2 * MARGIN, 150), 68, "foreground")
    }
}

fn column(index: u32, height: u32) -> Slot {
    plain((MARGIN + index * 880, 280, 800, height.saturating_sub(400)), 38, "foreground")
}

/// The nth slot of `role` in `layout` (clamped to the last), like `placeElements`.
fn slot_for(layout: &str, role: &str, index: usize, height: u32) -> Option<Slot> {
    let body = || plain(content_box(height), 40, "foreground");
    let subtitle = || plain(content_box(height), 44, "muted");
    let slots: Vec<Slot> = match (layout, role) {
        ("title", "title") => vec![centered(height, 0.3, 220, 104, true, "foreground")],
        ("title", "subtitle") => vec![centered(height, 0.55, 120, 48, false, "muted")],
        ("title", "caption") => vec![centered(height, 0.8, 80, 32, false, "muted")],
        ("section", "title") => vec![centered(height, 0.38, 200, 92, true, "accent")],
        ("section", "subtitle") => vec![centered(height, 0.6, 120, 44, false, "muted")],
        ("two-column", "title") => vec![title_top()],
        ("two-column", "subtitle") => vec![subtitle()],
        ("two-column", "body") => vec![column(0, height), column(1, height)],
        ("quote", "title") => vec![title_top()],
        ("quote", "quote") => vec![Slot {
            italic: true,
            ..centered(height, 0.28, 360, 64, false, "foreground")
        }],
        ("quote", "caption") => vec![centered(height, 0.7, 80, 34, false, "muted")],
        (_, "title") => vec![title_top()],
        (_, "subtitle") => vec![subtitle()],
        (_, "caption") => vec![plain((MARGIN, height.saturating_sub(110), 1680, 60), 28, "muted")],
        _ => Vec::new(),
    };
    let slots = if slots.is_empty() && role != "body" {
        return slot_for(layout, "body", index, height);
    } else if slots.is_empty() {
        vec![body()]
    } else {
        slots
    };
    let last = slots.len() - 1;
    slots.into_iter().nth(index.min(last))
}

fn map_slide(slide: &SlideModel, height: u32) -> SlideRecord {
    let layout = match slide.layout.as_deref() {
        Some(name @ ("title" | "title-and-content" | "section" | "two-column" | "quote")) => name,
        _ => "title-and-content",
    };
    let mut used: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    let elements = slide
        .elements
        .iter()
        .map(|element| {
            let slot = (element.kind == ElementKind::Text).then(|| {
                let role = element
                    .attributes
                    .get("role")
                    .cloned()
                    .unwrap_or_else(|| "body".to_string());
                let index = used.entry(role.clone()).or_insert(0);
                let slot = slot_for(layout, &role, *index, height);
                *index += 1;
                slot
            });
            map_element(element, slot.flatten(), height)
        })
        .collect();
    SlideRecord {
        id: slide.id.clone(),
        transition: slide.transition.clone(),
        notes: slide.notes.clone(),
        elements,
    }
}

fn map_element(element: &ElementModel, slot: Option<Slot>, height: u32) -> SlideElementRecord {
    let attr = |name: &str| element.attributes.get(name).cloned();
    let fallback = slot.as_ref().map_or_else(|| content_box(height), |s| s.rect);
    let int = |name: &str| attr(name).and_then(|v| v.parse::<u32>().ok());
    let step = int("step").unwrap_or(0);
    let animate = attr("animate");
    let (kind, runs, text, items) = match &element.content {
        ElementContent::RichText(markup) => (
            SlideElementKindRecord::Text,
            inline_runs(markup)
                .into_iter()
                .map(|run| SlideRunRecord {
                    text: run.text,
                    bold: run.bold,
                    italic: run.italic,
                    underline: run.underline,
                    strike: run.strike,
                })
                .collect(),
            String::new(),
            Vec::new(),
        ),
        ElementContent::Plain(body) => (SlideElementKindRecord::Notepad, Vec::new(), body.clone(), Vec::new()),
        ElementContent::Label(label) => (SlideElementKindRecord::Link, Vec::new(), label.clone(), Vec::new()),
        ElementContent::Verbatim(body) => (SlideElementKindRecord::Block, Vec::new(), body.clone(), Vec::new()),
        ElementContent::Items(list) => (
            SlideElementKindRecord::Todo,
            Vec::new(),
            String::new(),
            list.iter()
                .map(|item| SlideTodoItemRecord { label: item.text.clone(), done: item.done })
                .collect(),
        ),
        ElementContent::Empty => (
            match element.kind {
                ElementKind::Image => SlideElementKindRecord::Image,
                ElementKind::Video => SlideElementKindRecord::Video,
                _ => SlideElementKindRecord::Shape,
            },
            Vec::new(),
            String::new(),
            Vec::new(),
        ),
    };
    let src = attr("src").unwrap_or_default();
    let (video_provider, embed_ref) = match element.kind {
        ElementKind::Image => (None, src.strip_prefix("embed:").map(str::to_string)),
        ElementKind::Video => {
            if let Some(rest) = src.strip_prefix("embed:") {
                (Some("embed".to_string()), Some(rest.to_string()))
            } else if let Some(rest) = src.strip_prefix("youtube:") {
                (Some("youtube".to_string()), Some(rest.to_string()))
            } else if let Some(rest) = src.strip_prefix("vimeo:") {
                (Some("vimeo".to_string()), Some(rest.to_string()))
            } else {
                (None, None)
            }
        }
        _ => (None, None),
    };
    let role = attr("role").unwrap_or_default();
    let font = attr("font");
    let is_shape = element.kind == ElementKind::Shape;
    let color = if is_shape {
        attr("fill").or_else(|| Some("accent".to_string()))
    } else {
        attr("color").or_else(|| slot.as_ref().map(|s| s.color.to_string()))
    };
    SlideElementRecord {
        id: element.id.clone(),
        kind: if element.kind == ElementKind::Text { SlideElementKindRecord::Text } else { kind },
        x: element.x.unwrap_or(fallback.0),
        y: element.y.unwrap_or(fallback.1),
        w: element.w.unwrap_or(fallback.2),
        h: element.h.unwrap_or(fallback.3),
        step,
        animate,
        hidden: matches!(attr("hidden").as_deref(), Some("true" | "1")),
        runs,
        font_size: int("size").or_else(|| slot.as_ref().map(|s| s.size)).unwrap_or(40),
        bold: match attr("weight") {
            Some(weight) => weight == "bold",
            None => slot.as_ref().is_some_and(|s| s.bold),
        },
        italic: slot.as_ref().is_some_and(|s| s.italic),
        align: attr("align").unwrap_or_else(|| slot.as_ref().map_or("left", |s| s.align).to_string()),
        color,
        font_family: font.filter(|f| f != "heading" && f != "body"),
        is_heading: role == "title",
        embed_ref,
        video_provider,
        alt: attr("alt").unwrap_or_default(),
        fit: attr("fit"),
        shape_kind: attr("kind").unwrap_or_else(|| "rect".to_string()),
        stroke: attr("stroke"),
        title: attr("title").unwrap_or_default(),
        text,
        href: attr("href").unwrap_or_default(),
        items,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const DECK: &str = "<deck title=\"Demo\" aspect=\"16:9\" template=\"builtin:plain\">\n  <slide id=\"s1\" layout=\"title\">\n    <text id=\"e1\" role=\"title\">Hello <b>world</b></text>\n    <shape id=\"e2\" x=\"0\" y=\"1000\" w=\"1920\" h=\"80\" kind=\"rect\" fill=\"accent\"/>\n    <todo id=\"e3\" x=\"10\" y=\"10\" w=\"500\" h=\"300\" title=\"Next\"><item done=\"true\">Ship</item></todo>\n    <notes>Say hi</notes>\n  </slide>\n</deck>\n";

    #[test]
    fn maps_deck_slots_runs_and_items() {
        let deck = slide_deck_from_markup(DECK.to_string()).expect("deck parses");
        assert_eq!((deck.width, deck.height, deck.slides.len()), (1920, 1080, 1));
        let slide = &deck.slides[0];
        assert_eq!(slide.notes, "Say hi");
        let title = &slide.elements[0];
        assert_eq!((title.font_size, title.bold, title.align.as_str()), (104, true, "center"));
        assert_eq!(title.y, 324);
        assert!(title.is_heading);
        assert_eq!(title.runs.len(), 2);
        assert!(title.runs[1].bold);
        assert_eq!(slide.elements[1].color.as_deref(), Some("accent"));
        assert_eq!(slide.elements[2].items[0].label, "Ship");
    }

    #[test]
    fn refuses_unnormalised_markup() {
        assert!(slide_deck_from_markup("<deck><slide>".to_string()).is_err());
    }
}
