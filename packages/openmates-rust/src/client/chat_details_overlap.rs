//! Overlap the selected rich read's first concurrent round (metadata batch,
//! cached tail delta or latest window, first embeds page) with the command's
//! session admission and selected recovery discovery. The round is prepared
//! with the ordinary pre-send fences and only sent early; every post-send
//! fence, decode and cache rule still runs when the read consumes it. It is
//! consumed only for the exact session, owner, Team, Chat and request paths it
//! was sent for, and is discarded (aborted) whenever recovery touched work
//! that could change the selected Chat.
use super::*;

/// (session id, owner, Team, Chat id, metadata/messages/embeds paths).
type OverlapKey = (String, String, Option<String>, String, [String; 3]);

pub(in crate::client) struct ChatDetailsOverlap {
    key: OverlapKey,
    #[cfg(not(target_arch = "wasm32"))]
    tasks: Vec<tokio::task::JoinHandle<transport::SentRead>>,
}

#[cfg(not(target_arch = "wasm32"))]
impl Drop for ChatDetailsOverlap {
    fn drop(&mut self) {
        for task in &self.tasks {
            task.abort();
        }
    }
}

/// The paths of one first round, shared by the read and its overlap.
pub(super) struct FirstRound {
    pub metadata_path: String,
    pub messages_path: String,
    pub latest_path: String,
    pub embeds_path: String,
    pub bounded: bool,
    pub requested: usize,
    pub cached: Option<chat_details_cache::ChatDetailsCache>,
}
impl FirstRound {
    pub(super) fn requests(&self, id: &str) -> [(Method, &str, Option<Value>, bool); 3] {
        [
            (Method::POST, &self.metadata_path, Some(json!({"chat_ids":[id],"include_read_details":true})), true),
            (Method::GET, &self.messages_path, None, false),
            (Method::GET, &self.embeds_path, None, false),
        ]
    }
}

pub(super) fn history_limit(history: ChatDetailsHistory) -> Result<Option<usize>> {
    match history {
        ChatDetailsHistory::Full => Ok(None),
        ChatDetailsHistory::Latest { limit } if (1..=100).contains(&limit) => Ok(Some(limit)),
        _ => Err(Error::Invalid("Latest chat details limit must be between 1 and 100.")),
    }
}

impl Client {
    pub(super) fn chat_details_first_round(&self, id: &str, limit: Option<usize>) -> Result<FirstRound> {
        let requested = limit.unwrap_or(100);
        let bounded = limit.is_some();
        // Cache-then-delta: a cached read replaces the latest-window request by
        // a tail delta after the last cached message (same concurrent round).
        let cached = self.cached_chat_details(id, bounded);
        let latest_path = self.chat_details_messages_path(id, requested, bounded, None)?;
        let messages_path = match &cached {
            Some(cache) => self.chat_details_tail_path(id, &cache.tail, bounded)?,
            None => latest_path.clone(),
        };
        Ok(FirstRound {
            metadata_path: self.scoped("/v1/chats/metadata/batch")?,
            messages_path,
            latest_path,
            embeds_path: self.chat_details_embeds_path(id, None)?,
            bounded,
            requested,
            cached,
        })
    }

    fn chat_details_overlap_key(&self, id: &str, round: &FirstRound) -> Result<OverlapKey> {
        let session = self.require_session()?;
        Ok((
            session.session_id.clone(),
            session.hashed_email.clone(),
            self.team()?.map(str::to_owned),
            id.to_owned(),
            [round.metadata_path.clone(), round.messages_path.clone(), round.embeds_path.clone()],
        ))
    }

    /// Send the selected read's first round now, before session admission, so
    /// its connections and server work overlap admission and recovery
    /// discovery. Best effort: any pre-send refusal simply leaves the ordinary
    /// read path. A later `read_chat_details` for the same context consumes it.
    #[cfg(not(target_arch = "wasm32"))]
    pub fn prefetch_chat_details(&mut self, id: &str, options: &ChatDetailsOptions) {
        self.chat_details_overlap = None;
        let Ok(runtime) = tokio::runtime::Handle::try_current() else { return };
        let Ok(limit) = history_limit(options.history) else { return };
        let ready = (|| {
            let admission = self.full_chat_read_admission(id)?;
            AsyncCryptoScope::begin(self)?.check_chat(self, id)?;
            self.require_credentials()?;
            admission.check(self)
        })();
        let Ok(()) = ready else { return };
        let Ok(round) = self.chat_details_first_round(id, limit) else { return };
        let Ok(key) = self.chat_details_overlap_key(id, &round) else { return };
        let mut overlap = ChatDetailsOverlap { key, tasks: Vec::with_capacity(3) };
        for (method, path, body, not_found) in round.requests(id) {
            // Dropping a partial overlap aborts the requests already sent.
            let Ok(prepared) = self.prepare_read(method, path, body, not_found) else { return };
            overlap.tasks.push(runtime.spawn(prepared.send()));
        }
        self.chat_details_overlap = Some(overlap);
    }

    /// Pre-establish the TCP/TLS connection of this Client's next WebSocket
    /// (no request or credential is sent until the socket is opened).
    pub fn preconnect_socket(&self) {
        let Ok(mut url) = self.url("/v1/ws") else { return };
        if url.set_scheme(if self.base.scheme() == "https" { "wss" } else { "ws" }).is_ok() {
            crate::platform::socket::preconnect(&url);
        }
    }

    #[cfg(target_arch = "wasm32")]
    pub fn prefetch_chat_details(&mut self, _id: &str, _options: &ChatDetailsOptions) {}

    /// Abort an overlapped round. Recovery calls this before any work that may
    /// change the selected Chat (replayed outputs, deliveries or jobs).
    pub fn discard_chat_details_prefetch(&mut self) {
        self.chat_details_overlap = None;
    }

    /// The overlapped round's sent reads, in request order, when it was sent
    /// for exactly this context. Otherwise it is aborted and None returned.
    #[cfg(not(target_arch = "wasm32"))]
    pub(super) async fn take_chat_details_overlap(
        &mut self,
        id: &str,
        round: &FirstRound,
    ) -> Option<Vec<transport::SentRead>> {
        let mut overlap = self.chat_details_overlap.take()?;
        if self.chat_details_overlap_key(id, round).ok().as_ref() != Some(&overlap.key)
            || self.operation_cancel.is_cancelled()
        {
            return None;
        }
        // The consuming read is this transport operation: a proof minted
        // after the early send must not survive it (prepare_read's rule).
        self.invalidate_chat_inventory_proofs();
        let mut sent = Vec::with_capacity(overlap.tasks.len());
        for task in std::mem::take(&mut overlap.tasks) {
            sent.push(task.await.ok()?);
        }
        Some(sent)
    }

    #[cfg(target_arch = "wasm32")]
    pub(super) async fn take_chat_details_overlap(
        &mut self,
        _id: &str,
        _round: &FirstRound,
    ) -> Option<Vec<transport::SentRead>> {
        None
    }
}
