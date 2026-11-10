//! Typed errors of the core-owned deck replica (markup hydration, operations, update bytes).
//! Shared client core; each variant has a stable `code()` that crosses bindings unchanged.
//! Spec: `specifications/features/slides/` and `live-collab.core.one-shared-model`.

use std::fmt;

/// Why a deck could not be hydrated, changed or synced. Nothing is applied when an
/// operation returns an error (each operation runs in one transaction that only writes
/// after validation).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeckError {
    /// The input is not normalised slides markup (the output of
    /// `normalise_slides_markup`); `offset` is the byte position where parsing stopped.
    MarkupNotNormalised {
        /// Byte offset in the input.
        offset: usize,
        /// Short English reason for logs and tests.
        reason: &'static str,
    },
    /// The deck holds no slide; slides markup requires at least one.
    NoSlides,
    /// No slide with this id.
    SlideNotFound(String),
    /// No element with this id on the given slide.
    ElementNotFound(String),
    /// The element exists but the operation does not apply to its kind.
    WrongElementKind {
        /// Element id.
        element_id: String,
        /// Kind the operation needs (`text`, `todo`, ...).
        expected: &'static str,
    },
    /// An attribute name this element kind does not have.
    UnknownAttribute(String),
    /// A value the slides grammar does not accept (attribute, layout, rich text, ...).
    InvalidValue {
        /// Attribute or field name.
        field: String,
        /// Short English reason.
        reason: &'static str,
    },
    /// The 200 slides per deck or 200 elements per slide limit would be exceeded.
    LimitReached(&'static str),
    /// The last slide cannot be deleted: a deck always has one slide.
    LastSlide,
    /// A to-do item index outside the list.
    ItemOutOfRange(usize),
    /// Update or state-vector bytes that are not valid Yjs v1 encoding.
    InvalidUpdate(String),
}

impl DeckError {
    /// Stable machine code, the same on every shell.
    pub fn code(&self) -> &'static str {
        match self {
            Self::MarkupNotNormalised { .. } => "slides_markup_not_normalised",
            Self::NoSlides => "slides_deck_has_no_slide",
            Self::SlideNotFound(_) => "slides_slide_not_found",
            Self::ElementNotFound(_) => "slides_element_not_found",
            Self::WrongElementKind { .. } => "slides_wrong_element_kind",
            Self::UnknownAttribute(_) => "slides_unknown_attribute",
            Self::InvalidValue { .. } => "slides_invalid_value",
            Self::LimitReached(_) => "slides_limit_reached",
            Self::LastSlide => "slides_last_slide",
            Self::ItemOutOfRange(_) => "slides_item_out_of_range",
            Self::InvalidUpdate(_) => "shared_item_invalid_update",
        }
    }

    pub(crate) fn markup(offset: usize, reason: &'static str) -> Self {
        Self::MarkupNotNormalised { offset, reason }
    }

    pub(crate) fn invalid(field: &str, reason: &'static str) -> Self {
        Self::InvalidValue {
            field: field.to_string(),
            reason,
        }
    }
}

impl fmt::Display for DeckError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MarkupNotNormalised { offset, reason } => {
                write!(
                    f,
                    "slides markup is not normalised at byte {offset}: {reason}"
                )
            }
            Self::NoSlides => f.write_str("deck has no slide"),
            Self::SlideNotFound(id) => write!(f, "slide {id} not found"),
            Self::ElementNotFound(id) => write!(f, "element {id} not found"),
            Self::WrongElementKind {
                element_id,
                expected,
            } => write!(f, "element {element_id} is not a {expected} element"),
            Self::UnknownAttribute(name) => write!(f, "unknown attribute {name}"),
            Self::InvalidValue { field, reason } => write!(f, "invalid {field}: {reason}"),
            Self::LimitReached(what) => write!(f, "limit reached: {what}"),
            Self::LastSlide => f.write_str("the last slide cannot be deleted"),
            Self::ItemOutOfRange(index) => write!(f, "to-do item {index} does not exist"),
            Self::InvalidUpdate(reason) => write!(f, "invalid update bytes: {reason}"),
        }
    }
}

impl std::error::Error for DeckError {}
