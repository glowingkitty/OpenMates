//! `DeckDocument`: the core's authoritative `yrs` replica of one open deck.
//! Shared client core (`live-collab.core.one-shared-model`; plan `live-collaboration-crdt`
//! Phase 1, slides-core Phase 5 core half). Owns hydration from and saving to normalised
//! slides markup, typed operations, per-operation undo/redo, the render view model and the
//! Yjs v1 update bytes later phases sync and a rich-text mirror attaches through.

use super::deck_apply::apply_operation;
use super::deck_error::DeckError;
use super::deck_markup::{DeckModel, SlideModel, parse_deck_markup, serialise_deck_markup};
use super::deck_operations::{DeckOperation, DeckOutcome};
use super::deck_store::{DeckRoots, read_model, roots, write_model};
use super::deck_values::{CANVAS_WIDTH, DeckAspect};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::Arc;
use yrs::block::ClientID;
use yrs::undo::{Options as UndoOptions, UndoManager};
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use yrs::{Doc, OffsetKind, Options, ReadTxn, StateVector, Transact, Update};

/// Transaction origin of local typed operations; the only origin the undo manager tracks,
/// so remote updates and hydration never become someone's undo step.
const LOCAL_ORIGIN: &str = "openmates-local-op";
/// Transaction origin of updates applied from peers or a mirror.
const REMOTE_ORIGIN: &str = "openmates-remote";

/// Render model of a deck for a shell: everything an editor draws, plus undo state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeckView {
    /// Deck title.
    pub title: String,
    /// Aspect ratio.
    pub aspect: DeckAspect,
    /// Template reference.
    pub template: String,
    /// Canvas width (always 1920).
    pub canvas_width: u32,
    /// Canvas height for the aspect.
    pub canvas_height: u32,
    /// Slides in display order.
    pub slides: Vec<SlideModel>,
    /// An undo step is available.
    pub can_undo: bool,
    /// A redo step is available.
    pub can_redo: bool,
}

/// One open deck as a Yjs document plus its local undo history.
///
/// Every operation is one transaction and one undo step (capture timeout 0). Reads go
/// through the same whitelist as markup input, so `to_markup` always returns normalised
/// markup even after arbitrary peer updates.
pub struct DeckDocument {
    doc: Doc,
    roots: DeckRoots,
    undo: UndoManager<()>,
}

impl DeckDocument {
    /// An empty replica (no slides yet) that is filled by [`Self::apply_update`]. Use this
    /// for every replica except the one that hydrates the deck, so ids are not duplicated.
    ///
    /// `client_id` must be unique per replica of this item; Yjs (JS) reads it as a 32-bit
    /// value, hence `u32`. [`Self::random_client_id`] gives one.
    pub fn empty(client_id: u32) -> Self {
        let mut options = Options::with_client_id(ClientID::new(u64::from(client_id)));
        // Yjs counts text offsets in UTF-16 code units; yrs defaults to bytes, which would
        // corrupt positions exchanged with a JS rich-text mirror.
        options.offset_kind = OffsetKind::Utf16;
        let doc = Doc::with_options(options);
        let roots = {
            let mut txn = doc.transact_mut();
            roots(&mut txn)
        };
        let undo = undo_manager(&doc, &roots);
        Self { doc, roots, undo }
    }

    /// A random client id for [`Self::empty`] / [`Self::from_markup`].
    pub fn random_client_id() -> u32 {
        rand::random::<u32>()
    }

    /// Hydrates a replica from normalised slides markup. Hydration is not undoable.
    ///
    /// # Errors
    /// [`DeckError::MarkupNotNormalised`] or [`DeckError::NoSlides`] (see
    /// [`parse_deck_markup`]).
    pub fn from_markup(markup: &str, client_id: u32) -> Result<Self, DeckError> {
        let model = parse_deck_markup(markup)?;
        let deck = Self::empty(client_id);
        {
            // No origin: the undo manager only tracks LOCAL_ORIGIN.
            let mut txn = deck.doc.transact_mut();
            write_model(&mut txn, &deck.roots, &model)?;
        }
        Ok(deck)
    }

    /// A replica built from a full state update (e.g. [`Self::encode_state`] of a peer).
    ///
    /// # Errors
    /// [`DeckError::InvalidUpdate`] for bytes that are not a Yjs v1 update.
    pub fn from_update(update: &[u8], client_id: u32) -> Result<Self, DeckError> {
        let mut deck = Self::empty(client_id);
        deck.apply_update(update)?;
        Ok(deck)
    }

    /// The deck as a plain model.
    pub fn model(&self) -> DeckModel {
        read_model(&self.doc.transact(), &self.roots)
    }

    /// The render view model.
    pub fn view(&self) -> DeckView {
        let model = self.model();
        DeckView {
            canvas_width: CANVAS_WIDTH,
            canvas_height: model.aspect.canvas_height(),
            title: model.title,
            aspect: model.aspect,
            template: model.template,
            slides: model.slides,
            can_undo: self.undo.can_undo(),
            can_redo: self.undo.can_redo(),
        }
    }

    /// Normalised slides markup to save as the deck's next version.
    ///
    /// # Errors
    /// [`DeckError::NoSlides`] while the replica holds no slide (not yet synced).
    pub fn to_markup(&self) -> Result<String, DeckError> {
        let model = self.model();
        if model.slides.is_empty() {
            return Err(DeckError::NoSlides);
        }
        Ok(serialise_deck_markup(&model))
    }

    /// Applies one typed operation as one undo step.
    ///
    /// # Errors
    /// The operation's [`DeckError`]; the deck is unchanged then.
    pub fn apply(&mut self, operation: DeckOperation) -> Result<DeckOutcome, DeckError> {
        let mut txn = self.doc.transact_mut_with(LOCAL_ORIGIN);
        apply_operation(&mut txn, &self.roots, operation)
    }

    /// Reverts the latest local operation; `false` when there is none. Peers' changes
    /// are never undone.
    pub fn undo(&mut self) -> bool {
        self.undo.undo_blocking()
    }

    /// Re-applies the latest undone operation; `false` when there is none.
    pub fn redo(&mut self) -> bool {
        self.undo.redo_blocking()
    }

    /// An undo step is available.
    pub fn can_undo(&self) -> bool {
        self.undo.can_undo()
    }

    /// A redo step is available.
    pub fn can_redo(&self) -> bool {
        self.undo.can_redo()
    }

    /// Yjs v1 encoded state vector (what this replica has seen).
    pub fn state_vector(&self) -> Vec<u8> {
        self.doc.transact().state_vector().encode_v1()
    }

    /// Yjs v1 update with everything the holder of `state_vector` lacks.
    ///
    /// # Errors
    /// [`DeckError::InvalidUpdate`] for bytes that are not a v1 state vector.
    pub fn encode_update_since(&self, state_vector: &[u8]) -> Result<Vec<u8>, DeckError> {
        let remote = StateVector::decode_v1(state_vector)
            .map_err(|error| DeckError::InvalidUpdate(error.to_string()))?;
        Ok(self.doc.transact().encode_diff_v1(&remote))
    }

    /// Yjs v1 update with the full state (snapshot for a new replica).
    pub fn encode_state(&self) -> Vec<u8> {
        self.doc
            .transact()
            .encode_state_as_update_v1(&StateVector::default())
    }

    /// Applies a Yjs v1 update from a peer or the rich-text mirror. Duplicates and
    /// out-of-order delivery are fine (yrs buffers missing dependencies). Not undoable
    /// locally.
    ///
    /// # Errors
    /// [`DeckError::InvalidUpdate`] for undecodable or inapplicable bytes.
    pub fn apply_update(&mut self, update: &[u8]) -> Result<(), DeckError> {
        let update = Update::decode_v1(update)
            .map_err(|error| DeckError::InvalidUpdate(error.to_string()))?;
        self.doc
            .transact_mut_with(REMOTE_ORIGIN)
            .apply_update(update)
            .map_err(|error| DeckError::InvalidUpdate(error.to_string()))
    }
}

/// Undo manager over the three deck roots, tracking only [`LOCAL_ORIGIN`]. Capture
/// timeout 0 and a constant clock make each operation its own step on every platform
/// (`UndoManager::new` and the system clock are unavailable on wasm32-unknown-unknown).
fn undo_manager(doc: &Doc, roots: &DeckRoots) -> UndoManager<()> {
    let options = UndoOptions {
        capture_timeout_millis: 0,
        tracked_origins: HashSet::new(),
        capture_transaction: None,
        timestamp: Arc::new(|| 0),
        init_undo_stack: Vec::new(),
        init_redo_stack: Vec::new(),
    };
    let mut undo = UndoManager::with_options(options);
    undo.expand_scope(doc, &roots.meta);
    undo.expand_scope(doc, &roots.order);
    undo.expand_scope(doc, &roots.slides);
    undo.include_origin(LOCAL_ORIGIN);
    undo
}
