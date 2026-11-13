//! Answering a consent request of a running turn. The stream shows
//! `StreamEvent::Consent`; the shell answers through a [`ConsentAnswerer`]
//! that bypasses the actor lock (the waiting turn holds it) and feeds the
//! client's consent receiver (`Client::set_consent_receiver`), exactly like the
//! TUI. Native only; spec `client-core`.
use super::live_turns::LiveTurns;
use crate::error::{Error, Result};
use std::sync::Arc;
use tokio::sync::mpsc::UnboundedSender;

/// Most items one answer may approve (the client's own request limit).
const MAX_APPROVED: usize = 64;

/// Cloneable handle that answers consent requests of the actor's turns.
#[derive(Clone)]
pub struct ConsentAnswerer {
    turns: Arc<LiveTurns>,
    decisions: UnboundedSender<(String, Vec<String>)>,
}

impl ConsentAnswerer {
    pub(super) fn new(
        turns: Arc<LiveTurns>,
        decisions: UnboundedSender<(String, Vec<String>)>,
    ) -> Self {
        Self { turns, decisions }
    }

    /// Answer consent request `request_id` of `chat_id`, approving exactly
    /// `approved_item_ids` (an empty list declines). A request is answered
    /// once; it ends with its turn.
    ///
    /// # Errors
    /// `Invalid` for an unknown, already answered or ended request, a request
    /// of another chat, an item the request did not list, or more than 64
    /// items; `Cancelled` when no turn reads decisions any more (the client's
    /// receiver was replaced or the session ended).
    pub fn answer(
        &self,
        chat_id: &str,
        request_id: &str,
        approved_item_ids: Vec<String>,
    ) -> Result<()> {
        if approved_item_ids.len() > MAX_APPROVED {
            return Err(Error::Invalid("Too many approved consent items."));
        }
        self.turns
            .claim_consent(chat_id, request_id, &approved_item_ids)?;
        self.decisions
            .send((request_id.to_owned(), approved_item_ids))
            .map_err(|_| Error::Cancelled)
    }
}
