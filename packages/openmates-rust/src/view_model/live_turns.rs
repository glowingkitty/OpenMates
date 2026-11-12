//! The registry of the actor's running turns: each send registers its cancel
//! token and chat while it runs, so `SendCancelHandle`, `stop_reply` and
//! logout reach a turn whose reply streams beside the actor
//! (`send_stream.rs`), and other calls leave the client's operation token
//! alone while a turn depends on it. Native only; spec `client-core`.
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use tokio_util::sync::CancellationToken;

/// One running turn.
struct LiveTurn {
    id: u64,
    /// The turn's chat; `None` for a new chat until the server names it.
    chat_id: Option<String>,
    cancel: CancellationToken,
}

#[derive(Default)]
struct Entries {
    next: u64,
    turns: Vec<LiveTurn>,
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

impl Drop for LiveTurnGuard {
    fn drop(&mut self) {
        self.turns.entries().turns.retain(|turn| turn.id != self.id);
    }
}
