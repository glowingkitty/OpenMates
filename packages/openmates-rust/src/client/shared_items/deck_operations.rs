//! Typed deck operations: the only way a slides editor changes a deck replica.
//! Shared client core (`live-collab.core.one-shared-model`; slides Phase 5 editor in
//! `docs/plans/slides-core/plan.yml`). This module holds the wire types (operation,
//! outcome, element spec); `deck_apply` validates and writes them.

use super::deck_markup::{ElementContent, TodoItem};
use super::deck_values::ElementKind;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// One named change to a deck. Serialised with an `op` tag (`{"op":"set_geometry",...}`)
/// so every shell sends the same JSON through its binding.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum DeckOperation {
    /// Replace a text box's content with inline markup (`b i u s br ul ol li`).
    SetTextContent {
        /// Slide id.
        slide_id: String,
        /// Text element id.
        element_id: String,
        /// Inline markup; whitespace is normalised like the backend does.
        markup: String,
    },
    /// Change font, size, colour, alignment or weight of a text box.
    SetTextStyle {
        /// Slide id.
        slide_id: String,
        /// Text element id.
        element_id: String,
        /// Values to set and names to remove.
        style: TextStyle,
    },
    /// Move and/or resize an element (drag end). Values are clamped into the canvas
    /// exactly like the normaliser clamps them.
    SetGeometry {
        /// Slide id.
        slide_id: String,
        /// Element id.
        element_id: String,
        /// Left edge.
        x: i64,
        /// Top edge.
        y: i64,
        /// Width.
        w: i64,
        /// Height.
        h: i64,
    },
    /// Replace an image (`src="embed:<ref>"`) and optionally its alt text.
    SetImageSource {
        /// Slide id.
        slide_id: String,
        /// Image element id.
        element_id: String,
        /// `embed:<ref>`.
        src: String,
        /// New alt text; `Some("")` removes it, `None` keeps it.
        alt: Option<String>,
    },
    /// Add an element; it gets a fresh `e<n>` id.
    AddElement {
        /// Slide id.
        slide_id: String,
        /// Paint-order position; `None` puts it on top.
        index: Option<usize>,
        /// The new element.
        element: ElementSpec,
    },
    /// Delete an element.
    DeleteElement {
        /// Slide id.
        slide_id: String,
        /// Element id.
        element_id: String,
    },
    /// Copy an element (same geometry, new id) directly above the original.
    DuplicateElement {
        /// Slide id.
        slide_id: String,
        /// Element id.
        element_id: String,
    },
    /// Move an element to a new paint-order position within its slide (z-order: the
    /// last element is drawn on top; indices past the end move it to the top).
    MoveElement {
        /// Slide id.
        slide_id: String,
        /// Element id.
        element_id: String,
        /// Target position in the slide's element order.
        to_index: usize,
    },
    /// Add an empty slide with a fresh `s<n>` id.
    AddSlide {
        /// Position; `None` appends.
        index: Option<usize>,
        /// Template layout name.
        layout: Option<String>,
    },
    /// Copy a slide with all its elements (new ids) right after the original.
    DuplicateSlide {
        /// Slide id.
        slide_id: String,
    },
    /// Delete a slide; the last slide cannot be deleted.
    DeleteSlide {
        /// Slide id.
        slide_id: String,
    },
    /// Move a slide to a new position (indices past the end move it last).
    MoveSlide {
        /// Slide id.
        slide_id: String,
        /// Target position in the slide order.
        to_index: usize,
    },
    /// Set or remove (`None`) a slide's layout.
    SetSlideLayout {
        /// Slide id.
        slide_id: String,
        /// Layout name.
        layout: Option<String>,
    },
    /// Set speaker notes; an empty value removes them.
    SetSpeakerNotes {
        /// Slide id.
        slide_id: String,
        /// Plain text, trimmed, at most 5000 characters.
        notes: String,
    },
    /// Replace the text of a notepad (empty text clears it).
    SetNotepadText {
        /// Slide id.
        slide_id: String,
        /// Notepad element id.
        element_id: String,
        /// Text.
        text: String,
    },
    /// Replace all items of a to-do list.
    SetTodoItems {
        /// Slide id.
        slide_id: String,
        /// To-do element id.
        element_id: String,
        /// Items in order.
        items: Vec<TodoItem>,
    },
    /// Check or uncheck one to-do item.
    SetTodoItemDone {
        /// Slide id.
        slide_id: String,
        /// To-do element id.
        element_id: String,
        /// Item position.
        index: usize,
        /// Checked state.
        done: bool,
    },
    /// Clear one notepad or to-do element (to-do: all items removed).
    ClearInteractiveElement {
        /// Slide id.
        slide_id: String,
        /// Notepad or to-do element id.
        element_id: String,
    },
    /// Clear every notepad and to-do element in the deck; slides and elements stay.
    ClearAllInteractive,
    /// Hide or show one notepad or to-do element (`hidden="true"` attribute).
    SetInteractiveHidden {
        /// Slide id.
        slide_id: String,
        /// Notepad or to-do element id.
        element_id: String,
        /// Hidden state.
        hidden: bool,
    },
    /// Hide or show every notepad and to-do element.
    SetAllInteractiveHidden {
        /// Hidden state.
        hidden: bool,
    },
}

/// Text style change; `None` fields stay as they are.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextStyle {
    /// `heading`, `body` or a safe font name.
    #[serde(default)]
    pub font: Option<String>,
    /// 8-400 (clamped).
    #[serde(default)]
    pub size: Option<i64>,
    /// Colour token or `#hex`.
    #[serde(default)]
    pub color: Option<String>,
    /// `left`, `center`, `right`, `justify`.
    #[serde(default)]
    pub align: Option<String>,
    /// `normal`, `bold` or `100`-`900`.
    #[serde(default)]
    pub weight: Option<String>,
    /// Style attributes to remove (`font`, `size`, `color`, `align`, `weight`, `role`).
    #[serde(default)]
    pub remove: Vec<String>,
}

/// A new element for `DeckOperation::AddElement`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ElementSpec {
    /// Element kind.
    pub kind: ElementKind,
    /// Left edge (clamped).
    #[serde(default)]
    pub x: Option<i64>,
    /// Top edge (clamped).
    #[serde(default)]
    pub y: Option<i64>,
    /// Width (clamped).
    #[serde(default)]
    pub w: Option<i64>,
    /// Height (clamped).
    #[serde(default)]
    pub h: Option<i64>,
    /// Kind attributes (`role`, `src`, `fill`, `title`, `animate`, ...).
    #[serde(default)]
    pub attributes: BTreeMap<String, String>,
    /// Content matching the kind (`empty` for void kinds).
    pub content: ElementContent,
}

/// What an applied operation did.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum DeckOutcome {
    /// The deck changed (one undo step).
    Applied,
    /// Valid, but the deck already had this state; no undo step is added.
    Unchanged,
    /// A slide was added under this id.
    SlideCreated {
        /// New slide id.
        slide_id: String,
    },
    /// An element was added under this id.
    ElementCreated {
        /// New element id.
        element_id: String,
    },
    /// Clear all emptied this many elements.
    Cleared {
        /// Number of elements whose content was removed.
        elements: usize,
    },
}
