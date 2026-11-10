//! Shared items: the core-owned CRDT replicas of open documents, sheets and decks.
//! Shared client core (plan `live-collaboration-crdt`, Phase 1). Per the decision recorded in
//! `docs/plans/live-collaboration-crdt/spike.md` the core holds the authoritative `yrs` (Yjs v1)
//! replica of each open item and owns structure, merge, undo and serialisation; editors send
//! typed operations and render the view model. Implements `live-collab.core.one-shared-model`
//! (`specifications/features/live-collaboration/`). Decks only so far (single-user, no transport).

pub mod deck;
mod deck_apply;
pub mod deck_error;
pub mod deck_handles;
mod deck_inline;
pub mod deck_markup;
pub mod deck_operations;
mod deck_store;
pub mod deck_values;

pub use deck::{DeckDocument, DeckView};
pub use deck_error::DeckError;
pub use deck_markup::{
    DeckModel, ElementContent, ElementModel, SlideModel, TodoItem, parse_deck_markup,
    serialise_deck_markup,
};
pub use deck_operations::{DeckOperation, DeckOutcome, ElementSpec, TextStyle};
pub use deck_values::{DeckAspect, ElementKind};

#[cfg(test)]
mod deck_convergence_tests;
#[cfg(test)]
mod deck_handles_tests;
#[cfg(test)]
mod deck_markup_tests;
#[cfg(test)]
mod deck_operations_tests;
