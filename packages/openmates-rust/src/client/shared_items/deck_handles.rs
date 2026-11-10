//! `DeckDocuments`: a table of open [`DeckDocument`] replicas keyed by a numeric handle,
//! with a JSON-text / byte surface for shells that cannot hold Rust values (the web shared
//! Worker `deckDocument` unit through `openmates-browser-bindings`). Shared client core
//! (`live-collab.core.one-shared-model`); the binding only marshals, every decision stays in
//! [`DeckDocument`]. Wire shapes are the serde shapes of `DeckView`, `DeckOperation` and
//! `DeckOutcome`, pinned by `deck_wire_fixture.json` (Rust and vitest both read it).

use super::deck::{DeckDocument, DeckView};
use super::deck_error::DeckError;
use super::deck_operations::{DeckOperation, DeckOutcome};
use serde::Serialize;
use std::collections::HashMap;
use std::fmt;

/// Why a handle-table call failed. Every variant has a stable `code()` that crosses the
/// binding unchanged; deck errors keep the core's own code.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DeckHandleError {
    /// No open document under this handle (never opened, or already closed).
    UnknownHandle(u32),
    /// The operation JSON is not a `DeckOperation` (unknown `op`, missing or mistyped field).
    InvalidOperation(String),
    /// The deck refused the call; see [`DeckError::code`].
    Deck(DeckError),
}

impl DeckHandleError {
    /// Stable machine code, the same on every shell.
    pub fn code(&self) -> &'static str {
        match self {
            Self::UnknownHandle(_) => "shared_item_unknown_handle",
            Self::InvalidOperation(_) => "slides_invalid_operation",
            Self::Deck(error) => error.code(),
        }
    }
}

impl fmt::Display for DeckHandleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownHandle(handle) => write!(f, "no open deck under handle {handle}"),
            Self::InvalidOperation(reason) => write!(f, "invalid deck operation: {reason}"),
            Self::Deck(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for DeckHandleError {}

impl From<DeckError> for DeckHandleError {
    fn from(error: DeckError) -> Self {
        Self::Deck(error)
    }
}

#[derive(Serialize)]
struct Opened<'a> {
    handle: u32,
    view: &'a DeckView,
}

#[derive(Serialize)]
struct Applied<'a> {
    outcome: &'a DeckOutcome,
    view: &'a DeckView,
}

#[derive(Serialize)]
struct Stepped<'a> {
    changed: bool,
    view: &'a DeckView,
}

#[derive(Serialize)]
struct Viewed<'a> {
    view: &'a DeckView,
}

/// Serialises a result built only from owned strings, numbers, bools, options, vectors and
/// string-keyed maps; `serde_json` cannot fail on such values.
fn to_json<T: Serialize>(value: &T) -> String {
    serde_json::to_string(value).expect("deck wire values hold only JSON-representable data")
}

/// Open deck replicas of one shell connection, keyed by handle.
///
/// Handles start at 1 and are never reused while open. Dropping the table drops every
/// replica (the web unit frees it when its port closes), so nothing outlives the page.
#[derive(Default)]
pub struct DeckDocuments {
    next: u32,
    open: HashMap<u32, DeckDocument>,
}

impl DeckDocuments {
    /// An empty table.
    pub fn new() -> Self {
        Self::default()
    }

    /// Number of open documents.
    pub fn len(&self) -> usize {
        self.open.len()
    }

    /// No document is open.
    pub fn is_empty(&self) -> bool {
        self.open.is_empty()
    }

    fn deck(&self, handle: u32) -> Result<&DeckDocument, DeckHandleError> {
        self.open
            .get(&handle)
            .ok_or(DeckHandleError::UnknownHandle(handle))
    }

    fn deck_mut(&mut self, handle: u32) -> Result<&mut DeckDocument, DeckHandleError> {
        self.open
            .get_mut(&handle)
            .ok_or(DeckHandleError::UnknownHandle(handle))
    }

    fn next_handle(&mut self) -> u32 {
        // Skip 0 and any handle still open after a (theoretical) u32 wrap-around.
        loop {
            self.next = self.next.wrapping_add(1);
            if self.next != 0 && !self.open.contains_key(&self.next) {
                return self.next;
            }
        }
    }

    /// Hydrates a replica from normalised slides markup; answers `{"handle","view"}`.
    ///
    /// # Errors
    /// [`DeckHandleError::Deck`] with the hydration error of [`DeckDocument::from_markup`].
    pub fn open(&mut self, markup: &str) -> Result<String, DeckHandleError> {
        let deck = DeckDocument::from_markup(markup, DeckDocument::random_client_id())?;
        let handle = self.next_handle();
        let json = to_json(&Opened {
            handle,
            view: &deck.view(),
        });
        self.open.insert(handle, deck);
        Ok(json)
    }

    /// Applies one `DeckOperation` JSON as one undo step; answers `{"outcome","view"}`.
    ///
    /// # Errors
    /// Unknown handle, operation JSON that does not parse, or the operation's
    /// [`DeckError`] (the deck is unchanged then).
    pub fn apply(&mut self, handle: u32, operation_json: &str) -> Result<String, DeckHandleError> {
        let deck = self.deck_mut(handle)?;
        let operation: DeckOperation = serde_json::from_str(operation_json)
            .map_err(|error| DeckHandleError::InvalidOperation(error.to_string()))?;
        let outcome = deck.apply(operation)?;
        Ok(to_json(&Applied {
            outcome: &outcome,
            view: &deck.view(),
        }))
    }

    /// Reverts the latest local operation; answers `{"changed","view"}`.
    ///
    /// # Errors
    /// [`DeckHandleError::UnknownHandle`].
    pub fn undo(&mut self, handle: u32) -> Result<String, DeckHandleError> {
        let deck = self.deck_mut(handle)?;
        let changed = deck.undo();
        Ok(to_json(&Stepped {
            changed,
            view: &deck.view(),
        }))
    }

    /// Re-applies the latest undone operation; answers `{"changed","view"}`.
    ///
    /// # Errors
    /// [`DeckHandleError::UnknownHandle`].
    pub fn redo(&mut self, handle: u32) -> Result<String, DeckHandleError> {
        let deck = self.deck_mut(handle)?;
        let changed = deck.redo();
        Ok(to_json(&Stepped {
            changed,
            view: &deck.view(),
        }))
    }

    /// The current render view model; answers `{"view"}`.
    ///
    /// # Errors
    /// [`DeckHandleError::UnknownHandle`].
    pub fn view(&self, handle: u32) -> Result<String, DeckHandleError> {
        Ok(to_json(&Viewed {
            view: &self.deck(handle)?.view(),
        }))
    }

    /// Normalised slides markup to save (plain text, not JSON).
    ///
    /// # Errors
    /// Unknown handle or [`DeckError::NoSlides`].
    pub fn to_markup(&self, handle: u32) -> Result<String, DeckHandleError> {
        Ok(self.deck(handle)?.to_markup()?)
    }

    /// Yjs v1 state vector of the replica.
    ///
    /// # Errors
    /// [`DeckHandleError::UnknownHandle`].
    pub fn state_vector(&self, handle: u32) -> Result<Vec<u8>, DeckHandleError> {
        Ok(self.deck(handle)?.state_vector())
    }

    /// Yjs v1 update with everything the holder of `state_vector` lacks.
    ///
    /// # Errors
    /// Unknown handle or [`DeckError::InvalidUpdate`].
    pub fn encode_update_since(
        &self,
        handle: u32,
        state_vector: &[u8],
    ) -> Result<Vec<u8>, DeckHandleError> {
        Ok(self.deck(handle)?.encode_update_since(state_vector)?)
    }

    /// Applies a Yjs v1 update from a peer or the rich-text mirror; answers `{"view"}`.
    ///
    /// # Errors
    /// Unknown handle or [`DeckError::InvalidUpdate`].
    pub fn apply_update(&mut self, handle: u32, update: &[u8]) -> Result<String, DeckHandleError> {
        let deck = self.deck_mut(handle)?;
        deck.apply_update(update)?;
        Ok(to_json(&Viewed { view: &deck.view() }))
    }

    /// Drops the replica; `false` when the handle was not open.
    pub fn close(&mut self, handle: u32) -> bool {
        self.open.remove(&handle).is_some()
    }
}
