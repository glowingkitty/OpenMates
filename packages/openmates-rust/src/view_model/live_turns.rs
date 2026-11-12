//! The registry of the actor's running turns: each send registers its cancel
//! token and chat while it runs, so `SendCancelHandle`, `stop_reply` and
//! logout reach a turn whose reply streams beside the actor
//! (`send_stream.rs`), and other calls leave the client's operation token
//! alone while a turn depends on it. Native only; spec `client-core`.
use crate::error::Error;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use tokio_util::sync::CancellationToken;

/// One running turn.
struct LiveTurn {
    id: u64,
    /// The turn's chat; `None` for a new chat until the server names it.
    chat_id: Option<String>,
    cancel: CancellationToken,
}

/// A consent request a running turn showed and nobody answered yet.
struct PendingConsent {
    turn: u64,
    chat_id: String,
    request_id: String,
    item_ids: Vec<String>,
}

#[derive(Default)]
struct Entries {
    next: u64,
    turns: Vec<LiveTurn>,
    consents: Vec<PendingConsent>,
}

/// The running turns of one actor. Its `Arc` identity is the actor's: a
/// stream step checks it before touching actor state again.
#[derive(Default)]
pub(super) struct LiveTurns {
    entries: Mutex<Entries>,
}

impl LiveTurns {
    fn entries(&self) -> MutexGuard<'_, Entries> {
        // A poisoned lock only means a panic elsewhere; the list stays valid.
        self.entries.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Register a turn into `chat_id` cancelled by `cancel` until the guard
    /// drops.
    pub(super) fn register(
        self: &Arc<Self>,
        chat_id: Option<&str>,
        cancel: CancellationToken,
    ) -> LiveTurnGuard {
        let mut entries = self.entries();
        let id = entries.next;
        entries.next = entries.next.wrapping_add(1);
        entries.turns.push(LiveTurn {
            id,
            chat_id: chat_id.map(str::to_owned),
            cancel,
        });
        LiveTurnGuard {
            turns: self.clone(),
            id,
        }
    }

    /// Cancel every running turn; returns whether one ran.
    pub(super) fn cancel_all(&self) -> bool {
        let entries = self.entries();
        entries.turns.iter().for_each(|turn| turn.cancel.cancel());
        !entries.turns.is_empty()
    }

    /// Cancel the running turns into `chat_id`; returns whether one ran.
    pub(super) fn cancel_chat(&self, chat_id: &str) -> bool {
        let entries = self.entries();
        let mut stopped = false;
        for turn in entries
            .turns
            .iter()
            .filter(|turn| turn.chat_id.as_deref() == Some(chat_id))
        {
            turn.cancel.cancel();
            stopped = true;
        }
        stopped
    }

    /// Claim the pending consent `request_id` of `chat_id` for an answer
    /// approving `approved`: the request is removed, so it is answered once.
    ///
    /// # Errors
    /// `Invalid` for an unknown (or already answered) request, a request of
    /// another chat, or an approved id the request did not list; the request
    /// stays pending then.
    pub(super) fn claim_consent(
        &self,
        chat_id: &str,
        request_id: &str,
        approved: &[String],
    ) -> Result<(), Error> {
        let mut entries = self.entries();
        let index = entries
            .consents
            .iter()
            .position(|c| c.chat_id == chat_id && c.request_id == request_id)
            .ok_or(Error::Invalid("Unknown consent request."))?;
        if approved
            .iter()
            .any(|id| !entries.consents[index].item_ids.contains(id))
        {
            return Err(Error::Invalid("The consent request has no such item."));
        }
        entries.consents.remove(index);
        Ok(())
    }

    /// Whether a turn runs.
    pub(super) fn any(&self) -> bool {
        !self.entries().turns.is_empty()
    }
}

/// Removes its turn from the registry when the send ends or is dropped.
pub(super) struct LiveTurnGuard {
    turns: Arc<LiveTurns>,
    id: u64,
}

impl LiveTurnGuard {
    /// The server named the turn's chat (`Started`).
    pub(super) fn set_chat(&self, chat_id: &str) {
        let mut entries = self.turns.entries();
        if let Some(turn) = entries.turns.iter_mut().find(|turn| turn.id == self.id) {
            turn.chat_id = Some(chat_id.to_owned());
        }
    }
}

impl LiveTurnGuard {
    /// The turn showed a consent request in `chat_id` listing `item_ids`; it
    /// can be answered until the turn ends.
    pub(super) fn add_consent(&self, chat_id: &str, request_id: &str, item_ids: Vec<String>) {
        self.turns.entries().consents.push(PendingConsent {
            turn: self.id,
            chat_id: chat_id.to_owned(),
            request_id: request_id.to_owned(),
            item_ids,
        });
    }
}

impl Drop for LiveTurnGuard {
    fn drop(&mut self) {
        let mut entries = self.turns.entries();
        entries.turns.retain(|turn| turn.id != self.id);
        entries.consents.retain(|c| c.turn != self.id);
    }
}
