//! `LiveItem`: the core's authoritative replica of one open live item, sealed transport and
//! the outbox of local changes the server has not acknowledged. Pure; the caller supplies
//! bytes and persists [`LiveItem::outbox`] through the core cache.

use super::assistant::AssistantState;
use super::packet::{PacketType, open_packet, packet_epoch, seal_packet};
use super::sheet::{self, SheetOp};
use super::{LiveError, LiveItemKind, code, doc, new_doc, sheet_formatting};
use crate::client::shared_items::{DeckDocument, DeckOperation};
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use yrs::undo::UndoManager;
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use yrs::{Doc, ReadTxn, StateVector, Transact, Update};
use zeroize::Zeroizing;

/// Transaction origin of updates applied from peers or a mirror.
const REMOTE_ORIGIN: &str = "openmates-live-remote";

/// One sealed packet from the server log (`seq` is the server's per-item sequence).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteUpdate {
    /// Server sequence number.
    pub seq: u64,
    /// Sealed packet bytes.
    pub sealed: Vec<u8>,
}

/// A local change sealed for the server, kept until acknowledged.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealedUpdate {
    /// Client-chosen id the server echoes in `live_item_update_ack`.
    pub client_msg_id: String,
    /// Key epoch it is sealed under.
    pub epoch: u32,
    /// Sealed packet bytes (`live_item_update.payload`, base64 on the wire).
    pub sealed: Vec<u8>,
}

/// Result of applying a remote update.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ViewChange {
    /// Whether the replica changed (false for duplicates).
    pub changed: bool,
}

/// A typed local operation (sheets and decks).
#[derive(Clone, Debug)]
pub enum LocalOp {
    /// A sheet operation.
    Sheet(SheetOp),
    /// A deck operation.
    Deck(DeckOperation),
    /// Code: replaces lines `start..end` (0-based, end exclusive).
    CodeReplaceLines {
        /// First line.
        start: usize,
        /// One past the last line.
        end: usize,
        /// Replacement text.
        text: String,
    },
    /// Code: replaces the whole file text as a minimal range edit.
    CodeSetText(String),
}

/// Outcome of a local operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocalChange {
    /// Sealed update to send; `None` when nothing changed.
    pub update: Option<SealedUpdate>,
    /// Id of an inserted sheet row or column.
    pub new_id: Option<String>,
}

enum Model {
    Plain(Doc),
    Deck(Box<DeckDocument>),
}

/// The replica of one open live item.
pub struct LiveItem {
    kind: LiveItemKind,
    item_id: String,
    key: Zeroizing<[u8; 32]>,
    epoch: u32,
    previous_keys: Vec<(u32, crate::crypto::Key)>,
    model: Model,
    seen: Arc<Mutex<Vec<Vec<u8>>>>,
    /// Highest log position up to which every update is applied (no holes below it).
    head_seq: u64,
    /// Positions above `head_seq` already applied or acknowledged, waiting for a hole to fill.
    ahead: BTreeSet<u64>,
    outbox: Vec<SealedUpdate>,
    assistant: AssistantState,
    sheet_formatting_undo: Option<UndoManager<()>>,
}

/// Writer id of an item's first version. Two devices that open an item with an empty log at
/// the same time both create it from the same file text; written under one fixed id, the two
/// first versions are byte-identical and merge as one instead of doubling every row and line.
const SEED_CLIENT_ID: u32 = 1;

/// The first version of an item built from its text form, as one update under
/// [`SEED_CLIENT_ID`]. Deterministic: the same kind and text always give the same bytes.
///
/// # Errors
/// [`LiveError::InvalidText`] for a malformed sheet table, [`LiveError::Deck`] for bad deck markup.
fn seed_update(kind: LiveItemKind, text: &str) -> Result<Vec<u8>, LiveError> {
    if kind == LiveItemKind::Deck {
        let empty = DeckDocument::empty(SEED_CLIENT_ID).state_vector();
        let deck = DeckDocument::from_markup(text, SEED_CLIENT_ID)
            .map_err(|e| LiveError::Deck(e.to_string()))?;
        return deck.encode_update_since(&empty).map_err(invalid);
    }
    let seed = new_doc(SEED_CLIENT_ID);
    match kind {
        LiveItemKind::Doc => doc::from_text(&seed, text),
        LiveItemKind::Code => code::from_text(&seed, text),
        _ => sheet::from_text(&seed, text)?,
    }
    Ok(seed
        .transact()
        .encode_state_as_update_v1(&StateVector::default()))
}

fn invalid(error: impl ToString) -> LiveError {
    LiveError::InvalidUpdate(error.to_string())
}

impl LiveItem {
    /// Forks the current CRDT state into a new replica without sharing its outbox.
    /// A proposed restore can compute its update here before committing the version.
    pub(super) fn fork(&self) -> Result<Self, LiveError> {
        let mut fork = Self::new(self.kind, &self.item_id, &self.key, self.epoch);
        let full = self.encode_update_since(&StateVector::default().encode_v1())?;
        fork.apply_bytes(&full)?;
        Ok(fork)
    }

    fn new(kind: LiveItemKind, item_id: &str, key: &[u8; 32], epoch: u32) -> Self {
        // Never the seed writer: only the first version is written under that id.
        let client_id = rand::random::<u32>().max(SEED_CLIENT_ID + 1);
        let seen = Arc::new(Mutex::new(Vec::new()));
        let model = match kind {
            LiveItemKind::Deck => Model::Deck(Box::new(DeckDocument::empty(client_id))),
            _ => Model::Plain(new_doc(client_id)),
        };
        let doc = match &model {
            Model::Plain(doc) => doc,
            Model::Deck(deck) => deck.document(),
        };
        let sink = Arc::clone(&seen);
        let _ = doc.observe_update_v1("openmates-live-outbox", move |_, event| {
            if let Ok(mut updates) = sink.lock() {
                updates.push(event.update.clone());
            }
        });
        Self {
            kind,
            item_id: item_id.to_string(),
            key: Zeroizing::new(*key),
            epoch,
            previous_keys: Vec::new(),
            model,
            seen,
            head_seq: 0,
            ahead: BTreeSet::new(),
            outbox: Vec::new(),
            assistant: AssistantState::default(),
            sheet_formatting_undo: None,
        }
    }

    /// Runs a change against the shared replica with access to assistant undo state.
    /// All resulting transactions are sealed as one update.
    ///
    /// # Errors
    /// Returns a mutation or sealing error.
    pub(super) fn assistant_edit<R>(
        &mut self,
        change: impl FnOnce(&Doc, &mut AssistantState) -> Result<R, LiveError>,
    ) -> Result<(R, Option<SealedUpdate>), LiveError> {
        let mut state = std::mem::take(&mut self.assistant);
        let mut result = None;
        let sealed = self.mutate(|model| {
            let doc = match model {
                Model::Plain(doc) => doc,
                Model::Deck(deck) => deck.document(),
            };
            result = Some(change(doc, &mut state)?);
            Ok(())
        });
        self.assistant = state;
        Ok((result.ok_or(LiveError::Empty)?, sealed?))
    }

    /// The assistant lock and undo state of this item.
    pub(super) fn assistant_state(&mut self) -> &mut AssistantState {
        &mut self.assistant
    }

    /// Opens an item from the server state: an optional snapshot and the updates after it.
    ///
    /// # Errors
    /// Packet errors ([`LiveError::Authentication`], [`LiveError::EpochMismatch`], ...) or
    /// [`LiveError::InvalidUpdate`].
    pub fn open(
        kind: LiveItemKind,
        item_id: &str,
        key: &[u8; 32],
        epoch: u32,
        snapshot: Option<&RemoteUpdate>,
        updates: &[RemoteUpdate],
    ) -> Result<Self, LiveError> {
        Self::open_with_history(kind, item_id, key, epoch, &[], snapshot, updates)
    }

    /// Replay older packets using the exact historical key for each authenticated epoch.
    pub(super) fn open_with_history(
        kind: LiveItemKind,
        item_id: &str,
        key: &[u8; 32],
        epoch: u32,
        previous_keys: &[(u32, crate::crypto::Key)],
        snapshot: Option<&RemoteUpdate>,
        updates: &[RemoteUpdate],
    ) -> Result<Self, LiveError> {
        let mut item = Self::new(kind, item_id, key, epoch);
        item.previous_keys = previous_keys.to_vec();
        if let Some(snapshot) = snapshot {
            item.apply_snapshot(snapshot)?;
        }
        for update in updates {
            item.apply_remote(update.seq, &update.sealed)?;
        }
        item.drain_seen();
        Ok(item)
    }

    /// Creates a brand-new item from its text form; the initial content is in the outbox.
    ///
    /// # Errors
    /// [`LiveError::InvalidText`] (or a deck markup error) for text the kind rejects.
    pub fn create(
        kind: LiveItemKind,
        item_id: &str,
        key: &[u8; 32],
        epoch: u32,
        text: &str,
    ) -> Result<Self, LiveError> {
        let seed = seed_update(kind, text)?;
        let mut item = Self::new(kind, item_id, key, epoch);
        item.mutate(|model| match model {
            Model::Plain(d) => {
                let update = Update::decode_v1(&seed).map_err(invalid)?;
                d.transact_mut().apply_update(update).map_err(invalid)
            }
            Model::Deck(deck) => deck.apply_update(&seed).map_err(invalid),
        })?;
        Ok(item)
    }

    /// Sheet row and column ids in order, for a view model or typed operations.
    ///
    /// # Errors
    /// [`LiveError::WrongKind`] for other kinds.
    pub fn sheet_ids(&self) -> Result<(Vec<String>, Vec<String>), LiveError> {
        match (&self.model, self.kind) {
            (Model::Plain(d), LiveItemKind::Sheet) => {
                let (rows, cols, _) = sheet::grid(d);
                Ok((rows, cols))
            }
            _ => Err(LiveError::WrongKind { kind: self.kind }),
        }
    }

    /// The Yjs doc of a document, sheet or code item (`None` for decks).
    pub(crate) fn plain_doc(&self) -> Option<&Doc> {
        match &self.model {
            Model::Plain(d) => Some(d),
            Model::Deck(_) => None,
        }
    }

    /// The deck replica (`None` for the other kinds).
    pub(crate) fn deck(&self) -> Option<&DeckDocument> {
        match &self.model {
            Model::Deck(deck) => Some(deck),
            Model::Plain(_) => None,
        }
    }

    /// Kind of this item.
    pub fn kind(&self) -> LiveItemKind {
        self.kind
    }

    /// Highest server sequence applied.
    pub fn head_seq(&self) -> u64 {
        self.head_seq
    }

    /// Whether the update at log position `seq` is already applied (or was our own, acknowledged).
    /// A replay after a hole uses it to apply only the missing positions.
    pub fn has_seq(&self, seq: u64) -> bool {
        seq <= self.head_seq || self.ahead.contains(&seq)
    }

    /// Records `seq` as applied and moves the head over every position now without a hole, so a
    /// resubscribe from the head replays an update that was missed (CRDT updates may arrive out
    /// of order; Yjs holds the later ones until the missing one is applied).
    fn mark_seen(&mut self, seq: u64) {
        if seq <= self.head_seq {
            return;
        }
        self.ahead.insert(seq);
        while self.ahead.remove(&(self.head_seq + 1)) {
            self.head_seq += 1;
        }
    }

    /// Merge a newer authenticated snapshot into a replica with local edits.
    /// Its sequence covers holes that compaction removed from the update log.
    pub(super) fn apply_snapshot(&mut self, snapshot: &RemoteUpdate) -> Result<(), LiveError> {
        let bytes = self.open_as(PacketType::Snapshot, &snapshot.sealed)?;
        self.apply_bytes(&bytes)?;
        self.drain_seen();
        self.head_seq = self.head_seq.max(snapshot.seq);
        self.ahead.retain(|seq| *seq > self.head_seq);
        while self.ahead.remove(&(self.head_seq + 1)) {
            self.head_seq += 1;
        }
        Ok(())
    }

    /// Key epoch this item seals under.
    pub fn epoch(&self) -> u32 {
        self.epoch
    }

    /// Local updates the server has not acknowledged, oldest first.
    pub fn outbox(&self) -> &[SealedUpdate] {
        &self.outbox
    }

    /// Re-applies persisted outbox entries after a restart (they were not yet in the log).
    ///
    /// # Errors
    /// Packet errors for entries sealed under another key.
    pub fn restore_outbox(&mut self, entries: Vec<SealedUpdate>) -> Result<(), LiveError> {
        for mut entry in entries {
            let bytes = Zeroizing::new(self.open_as(PacketType::Update, &entry.sealed)?);
            if entry.epoch != self.epoch {
                entry.sealed = self.seal_as(PacketType::Update, &bytes)?;
                entry.epoch = self.epoch;
            }
            self.apply_bytes(&bytes)?;
            self.outbox.push(entry);
        }
        self.drain_seen();
        Ok(())
    }

    /// Drops the outbox entry the server acknowledged and advances the head.
    pub fn ack(&mut self, client_msg_id: &str, seq: u64) {
        self.outbox.retain(|e| e.client_msg_id != client_msg_id);
        self.mark_seen(seq);
    }

    /// Re-seals the whole outbox under `key`/`epoch` after a key rotation (`key_epoch_stale`).
    ///
    /// # Errors
    /// Packet errors when an entry cannot be opened with the old key.
    pub fn rekey(&mut self, key: &[u8; 32], epoch: u32) -> Result<(), LiveError> {
        if epoch < self.epoch || (epoch == self.epoch && *key != *self.key) {
            return Err(LiveError::EpochMismatch {
                expected: self.epoch,
                found: epoch,
            });
        }
        if epoch == self.epoch {
            return Ok(());
        }
        let mut resealed = Vec::with_capacity(self.outbox.len());
        for entry in &self.outbox {
            let bytes = Zeroizing::new(self.open_as(PacketType::Update, &entry.sealed)?);
            resealed.push(SealedUpdate {
                client_msg_id: entry.client_msg_id.clone(),
                epoch,
                sealed: seal_packet(
                    key,
                    &self.item_id,
                    self.kind,
                    epoch,
                    PacketType::Update,
                    &bytes,
                )?,
            });
        }
        self.previous_keys.push((
            self.epoch,
            std::mem::replace(&mut self.key, Zeroizing::new(*key)),
        ));
        self.epoch = epoch;
        self.outbox = resealed;
        Ok(())
    }

    /// Applies one packet from the server log.
    ///
    /// # Errors
    /// Packet errors or [`LiveError::InvalidUpdate`].
    pub fn apply_remote(&mut self, seq: u64, sealed: &[u8]) -> Result<ViewChange, LiveError> {
        let bytes = self.open_as(PacketType::Update, sealed)?;
        self.drain_seen();
        self.apply_bytes(&bytes)?;
        let changed = !self.drain_seen().is_empty() || matches!(self.model, Model::Deck(_));
        self.mark_seen(seq);
        Ok(ViewChange { changed })
    }

    /// Applies update bytes from the JS Yjs mirror (documents and code) and seals them.
    ///
    /// # Errors
    /// [`LiveError::WrongKind`] for sheets and decks, [`LiveError::InvalidUpdate`].
    pub fn apply_mirror_update(&mut self, bytes: &[u8]) -> Result<SealedUpdate, LiveError> {
        if !matches!(self.kind, LiveItemKind::Doc | LiveItemKind::Code) {
            return Err(LiveError::WrongKind { kind: self.kind });
        }
        self.enqueue_replica_update(bytes)
    }

    /// Seals and applies the update generated by the core's restore fork.
    pub(super) fn enqueue_replica_update(
        &mut self,
        bytes: &[u8],
    ) -> Result<SealedUpdate, LiveError> {
        self.drain_seen();
        self.apply_bytes(bytes)?;
        self.drain_seen();
        self.enqueue(bytes.to_vec())
    }

    /// Merges plain Yjs update bytes obtained through state vectors
    /// ([`Self::encode_update_since`]), without queueing them for the server. Used on
    /// reconnect to catch up before the outbox is sent.
    ///
    /// # Errors
    /// [`LiveError::InvalidUpdate`].
    pub fn merge_update(&mut self, bytes: &[u8]) -> Result<ViewChange, LiveError> {
        self.drain_seen();
        self.apply_bytes(bytes)?;
        Ok(ViewChange {
            changed: !self.drain_seen().is_empty(),
        })
    }

    /// Applies a typed operation and seals the resulting change.
    ///
    /// # Errors
    /// [`LiveError::WrongKind`] when the op does not match the kind, plus the op's own errors.
    pub fn apply_local_op(&mut self, op: LocalOp) -> Result<LocalChange, LiveError> {
        let kind = self.kind;
        let mut new_id = None;
        let mut formatting_undo = self.sheet_formatting_undo.take();
        let result = self.mutate(|model| match (model, op) {
            (Model::Plain(d), LocalOp::Sheet(op @ SheetOp::Format(_)))
                if kind == LiveItemKind::Sheet =>
            {
                let undo = formatting_undo.get_or_insert_with(|| sheet_formatting::undo_manager(d));
                undo.reset();
                sheet::apply_op_with_origin(d, &op, Some(sheet_formatting::LOCAL_ORIGIN))?;
                Ok(())
            }
            (Model::Plain(_), LocalOp::Sheet(SheetOp::UndoFormatting))
                if kind == LiveItemKind::Sheet =>
            {
                if let Some(undo) = &mut formatting_undo {
                    undo.undo_blocking();
                }
                Ok(())
            }
            (Model::Plain(d), LocalOp::Sheet(op)) if kind == LiveItemKind::Sheet => {
                new_id = sheet::apply_op(d, &op)?;
                Ok(())
            }
            (Model::Deck(deck), LocalOp::Deck(op)) => deck
                .apply(op)
                .map(|_| ())
                .map_err(|e| LiveError::Deck(e.to_string())),
            (Model::Plain(d), LocalOp::CodeReplaceLines { start, end, text })
                if kind == LiveItemKind::Code =>
            {
                code::replace_lines(d, start, end, &text)
            }
            (Model::Plain(d), LocalOp::CodeSetText(text)) if kind == LiveItemKind::Code => {
                code::set_text(d, &text);
                Ok(())
            }
            _ => Err(LiveError::WrongKind { kind }),
        });
        self.sheet_formatting_undo = formatting_undo;
        Ok(LocalChange {
            update: result?,
            new_id,
        })
    }

    pub(super) fn can_undo_sheet_formatting(&self) -> bool {
        self.sheet_formatting_undo
            .as_ref()
            .is_some_and(UndoManager::can_undo)
    }

    /// Seals the full state as a snapshot covering everything up to `head_seq`.
    ///
    /// # Errors
    /// Sealing errors.
    pub fn seal_snapshot(&self) -> Result<(u64, Vec<u8>), LiveError> {
        let state = match &self.model {
            Model::Plain(d) => d
                .transact()
                .encode_state_as_update_v1(&StateVector::default()),
            Model::Deck(deck) => deck.encode_state(),
        };
        Ok((self.head_seq, self.seal_as(PacketType::Snapshot, &state)?))
    }

    /// Encoded Yjs state vector (what a peer needs to compute the diff for us).
    pub fn state_vector(&self) -> Vec<u8> {
        match &self.model {
            Model::Plain(d) => d.transact().state_vector().encode_v1(),
            Model::Deck(deck) => deck.state_vector(),
        }
    }

    /// Update bytes a peer with `state_vector` lacks (plain Yjs v1; not sealed).
    ///
    /// # Errors
    /// [`LiveError::InvalidUpdate`] for an undecodable vector.
    pub fn encode_update_since(&self, state_vector: &[u8]) -> Result<Vec<u8>, LiveError> {
        match &self.model {
            Model::Plain(d) => {
                let sv = StateVector::decode_v1(state_vector).map_err(invalid)?;
                Ok(d.transact().encode_diff_v1(&sv))
            }
            Model::Deck(deck) => deck.encode_update_since(state_vector).map_err(invalid),
        }
    }

    /// The item's text form (document HTML, markdown table, slides markup or file text).
    ///
    /// # Errors
    /// [`LiveError::Empty`] when a sheet or deck has no content yet.
    pub fn text_form(&self) -> Result<String, LiveError> {
        match (&self.model, self.kind) {
            (Model::Plain(d), LiveItemKind::Doc) => doc::to_text(d),
            (Model::Plain(d), LiveItemKind::Code) => Ok(code::to_text(d)),
            (Model::Plain(d), _) => sheet::to_text(d),
            (Model::Deck(deck), _) => deck.to_markup().map_err(|_| LiveError::Empty),
        }
    }

    /// Add the older item keys available to this client after rotation.
    pub(super) fn add_previous_keys(&mut self, keys: &[(u32, crate::crypto::Key)]) {
        for (epoch, key) in keys {
            if *epoch < self.epoch && !self.previous_keys.iter().any(|(stored, _)| stored == epoch)
            {
                self.previous_keys.push((*epoch, key.clone()));
            }
        }
    }

    fn open_as(&self, ty: PacketType, sealed: &[u8]) -> Result<Vec<u8>, LiveError> {
        let epoch = packet_epoch(sealed)?;
        if epoch == self.epoch {
            return open_packet(&self.key, &self.item_id, self.kind, epoch, ty, sealed);
        }
        let (_, key) = self
            .previous_keys
            .iter()
            .find(|(previous, _)| *previous == epoch)
            .ok_or(LiveError::EpochMismatch {
                expected: self.epoch,
                found: epoch,
            })?;
        open_packet(key, &self.item_id, self.kind, epoch, ty, sealed)
    }

    fn seal_as(&self, ty: PacketType, bytes: &[u8]) -> Result<Vec<u8>, LiveError> {
        seal_packet(&self.key, &self.item_id, self.kind, self.epoch, ty, bytes)
    }

    fn apply_bytes(&mut self, bytes: &[u8]) -> Result<(), LiveError> {
        match &mut self.model {
            Model::Plain(d) => {
                let update = Update::decode_v1(bytes).map_err(invalid)?;
                d.transact_mut_with(REMOTE_ORIGIN)
                    .apply_update(update)
                    .map_err(invalid)
            }
            Model::Deck(deck) => deck.apply_update(bytes).map_err(invalid),
        }
    }

    fn drain_seen(&self) -> Vec<Vec<u8>> {
        self.seen
            .lock()
            .map(|mut v| std::mem::take(&mut *v))
            .unwrap_or_default()
    }

    /// Runs one mutation and seals what it changed.
    fn mutate<F>(&mut self, change: F) -> Result<Option<SealedUpdate>, LiveError>
    where
        F: FnOnce(&mut Model) -> Result<(), LiveError>,
    {
        self.drain_seen();
        change(&mut self.model)?;
        let updates = self.drain_seen();
        let update = match updates.len() {
            0 => None,
            1 => updates.into_iter().next(),
            _ => Some(yrs::merge_updates_v1(&updates).map_err(invalid)?),
        };
        update.map(|bytes| self.enqueue(bytes)).transpose()
    }

    fn enqueue(&mut self, bytes: Vec<u8>) -> Result<SealedUpdate, LiveError> {
        let sealed = SealedUpdate {
            client_msg_id: format!("{:032x}", rand::random::<u128>()),
            epoch: self.epoch,
            sealed: self.seal_as(PacketType::Update, &bytes)?,
        };
        self.outbox.push(sealed.clone());
        Ok(sealed)
    }
}
