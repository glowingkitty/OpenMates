//! Core-side I/O of live items: runs the [`Action`]s of the sans-I/O [`LiveSession`] against a
//! [`LiveIo`] (WebSocket send, outbox cache, embed key and content resolution, user-revision
//! write) and routes `live_item_*` server frames into the session. Shells and bindings only
//! provide the `LiveIo` primitives and receive the resulting [`Event`]s; no live logic stays in
//! TypeScript (`live-collab.core.live-session`, `.claude/rules/client-core.md`).

use super::LiveError;
use super::LiveItemKind;
use super::engine::SealedUpdate;
use super::session::LiveSession;
use super::session_types::{Action, CheckpointRequest, CheckpointResult, Event, Status};
use serde_json::Value;

/// The status event for an item whose key or content could not be resolved on open: it can
/// neither load nor save, so it reads as offline instead of staying in "saving".
fn open_failed(item_id: &str) -> Event {
    Event::Status {
        item_id: item_id.to_owned(),
        status: Status::Offline,
    }
}

/// Server frame prefix owned by the live item layer.
pub const FRAME_PREFIX: &str = "live_item_";
/// Assistant change frames (`embed_assistant_change`, `..._undo`) belong to the live layer too.
pub const ASSISTANT_FRAME_PREFIX: &str = "embed_assistant_";

/// Key material for live writes and authenticated playback of older packets.
/// Earlier keys are retained only for boxed snapshots, updates and outboxes.
pub struct LiveKeys {
    /// The authoritative write epoch.
    pub epoch: u32,
    /// The item key for the write epoch.
    pub current: crate::crypto::Key,
    /// Older keys indexed by their own packet epoch.
    pub previous: Vec<(u32, crate::crypto::Key)>,
}

/// The platform primitives the core needs for live items. Implemented by the signed-in
/// `Client` (key unwrap, user revisions, cache) plus the shell's socket adapter, and by fakes
/// in tests. Futures need not be `Send`: the browser core is single-threaded.
#[allow(async_fn_in_trait)] // single-threaded wasm and test executors; no `Send` bound wanted
pub trait LiveIo {
    /// Sends one WebSocket frame `{"type", "payload"}` on the connection the core owns.
    ///
    /// # Errors
    /// The frame could not be queued.
    fn send(&mut self, message_type: &str, payload: &Value) -> Result<(), LiveError>;

    /// Replaces the item's stored outbox in the encrypted cache (survives restart).
    ///
    /// # Errors
    /// The cache refused the write.
    async fn persist_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
    ) -> Result<(), LiveError>;

    /// Persists a pending offline edit and the current local text together.
    ///
    /// # Errors
    /// The cache refused the write or a recovery copy could not be sealed.
    async fn persist_offline_outbox(
        &mut self,
        item_id: &str,
        entries: &[SealedUpdate],
        _item: &super::engine::LiveItem,
    ) -> Result<(), LiveError> {
        self.persist_outbox(item_id, entries).await
    }

    /// The outbox stored for `item_id` (restored on open).
    ///
    /// # Errors
    /// The cache read failed or held malformed data.
    async fn load_outbox(&mut self, item_id: &str) -> Result<Vec<SealedUpdate>, LiveError>;

    /// Resolves the embed key and its epoch; `stale` asks for a newer epoch than before.
    ///
    /// # Errors
    /// The key is not available on this device.
    async fn resolve_key(&mut self, item_id: &str, stale: bool) -> Result<LiveKeys, LiveError>;

    /// Reads the embed's current text form (seed for an empty log).
    ///
    /// # Errors
    /// The embed could not be read.
    async fn read_content(&mut self, item_id: &str) -> Result<String, LiveError>;

    /// Writes one version through the user-revisions path.
    async fn write_checkpoint(&mut self, request: &CheckpointRequest) -> CheckpointResult;

    /// Text form of one stored version of the embed (the base an assistant change read).
    ///
    /// # Errors
    /// The version could not be read; the driver then reports the change as failed.
    async fn read_version_text(
        &mut self,
        embed_id: &str,
        version: i64,
    ) -> Result<String, LiveError>;

    /// `POST /v1/embeds/{embed_id}/assistant-change-outcome` with `body`.
    ///
    /// # Errors
    /// The request failed.
    async fn post_assistant_outcome(
        &mut self,
        embed_id: &str,
        body: &Value,
    ) -> Result<(), LiveError>;

    /// An assistant change arrived for an item that is not open: the host opens the item and
    /// feeds `frame` to [`LiveDriver::on_frame`] again as `embed_assistant_change`.
    fn assistant_change_not_open(&mut self, embed_id: &str, frame: &Value);

    /// The server's current version of the embed, the base of the first checkpoint.
    async fn base_version(&mut self, item_id: &str) -> Option<i64>;

    /// The Project scope under which the item was opened, if any.
    fn opened_project(&self, _item_id: &str) -> Option<&str> {
        None
    }
}

/// A [`LiveSession`] plus the [`LiveIo`] that performs its actions.
pub struct LiveDriver<I: LiveIo> {
    session: LiveSession,
    io: I,
}

impl<I: LiveIo> LiveDriver<I> {
    /// A driver over a default session.
    pub fn new(io: I) -> Self {
        Self::with_session(LiveSession::default(), io)
    }

    /// A driver over an existing session.
    pub fn with_session(session: LiveSession, io: I) -> Self {
        Self { session, io }
    }

    /// The wrapped session (read access, e.g. for tests).
    pub fn session(&self) -> &LiveSession {
        &self.session
    }

    /// The wrapped session (write access for the owner's marks).
    pub fn session_mut(&mut self) -> &mut LiveSession {
        &mut self.session
    }

    /// Splits the driver back into its session and I/O (the owner keeps the session between
    /// calls when the I/O borrows a client only for one call).
    pub fn into_parts(self) -> (LiveSession, I) {
        (self.session, self.io)
    }

    /// The I/O primitives.
    pub fn io_mut(&mut self) -> &mut I {
        &mut self.io
    }

    /// Executes `actions` and every follow-up action they cause; returns the events for the
    /// shell in order.
    ///
    /// # Errors
    /// The first error of a session call or of `send`/`persist_outbox`. A failed key or
    /// content resolution is not an error here: the item cannot sync, so the run emits an
    /// `Offline` status for it and the shell stops showing "Saving".
    pub async fn run(
        &mut self,
        actions: Vec<Action>,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let mut events = Vec::new();
        let mut queue: std::collections::VecDeque<Action> = actions.into();
        while let Some(action) = queue.pop_front() {
            match action {
                Action::Emit(event) => events.push(event),
                Action::Send {
                    message_type,
                    payload,
                } => self.io.send(message_type, &payload)?,
                Action::PersistOutbox { item_id, entries } => {
                    let result = if let Some(item) = self.session.offline_replica(&item_id) {
                        self.io
                            .persist_offline_outbox(&item_id, &entries, item)
                            .await
                    } else {
                        self.io.persist_outbox(&item_id, &entries).await
                    };
                    self.session.outbox_write_result(&item_id, result.is_ok());
                    result?;
                }
                Action::NeedKey { item_id, stale } => {
                    let keys = match self.io.resolve_key(&item_id, stale).await {
                        Ok(resolved) => resolved,
                        Err(_) => {
                            events.push(open_failed(&item_id));
                            continue;
                        }
                    };
                    let outbox = if stale {
                        Vec::new()
                    } else {
                        self.io.load_outbox(&item_id).await?
                    };
                    let next = self.session.provide_keys(&item_id, keys, outbox)?;
                    if let Some(version) = self.io.base_version(&item_id).await {
                        self.session.set_base_version(&item_id, Some(version));
                    }
                    queue.extend(next);
                }
                Action::NeedContent { item_id } => {
                    let text = match self.io.read_content(&item_id).await {
                        Ok(text) => text,
                        Err(_) => {
                            events.push(open_failed(&item_id));
                            continue;
                        }
                    };
                    queue.extend(self.session.provide_content(&item_id, &text, now_ms)?);
                }
                Action::AssistantNeedBase {
                    embed_id,
                    turn_id,
                    base_version,
                } => {
                    let next = match self.io.read_version_text(&embed_id, base_version).await {
                        Ok(text) => self
                            .session
                            .provide_assistant_base(&embed_id, &turn_id, &text, now_ms)?,
                        Err(_) => self
                            .session
                            .fail_assistant_base(&embed_id, &turn_id, now_ms),
                    };
                    queue.extend(next);
                }
                Action::PostAssistantOutcome { embed_id, body } => {
                    self.io.post_assistant_outcome(&embed_id, &body).await?;
                }
                Action::AssistantChangeNotOpen { embed_id, frame } => {
                    self.io.assistant_change_not_open(&embed_id, &frame);
                }
                Action::WriteCheckpoint(request) => {
                    let result = self.io.write_checkpoint(&request).await;
                    if let CheckpointResult::Written(version) = &result {
                        events.push(Event::VersionWritten {
                            item_id: request.item_id.clone(),
                            version: *version,
                            text: request.text.clone(),
                        });
                    }
                    queue.extend(
                        self.session
                            .checkpoint_result(&request.item_id, result, now_ms),
                    );
                }
            }
        }
        Ok(events)
    }

    /// Opens an item and runs key resolution, subscription and seeding.
    ///
    /// # Errors
    /// As [`Self::run`].
    pub async fn open(
        &mut self,
        item_id: &str,
        kind: LiveItemKind,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.open(item_id, kind);
        self.run(actions, now_ms).await
    }

    /// Update bytes from the shell's Yjs mirror.
    ///
    /// # Errors
    /// As [`Self::run`] and the session's local-change errors.
    pub async fn apply_mirror_update(
        &mut self,
        item_id: &str,
        bytes: &[u8],
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.apply_mirror_update(item_id, bytes, now_ms)?;
        self.run(actions, now_ms).await
    }

    /// One typed local operation.
    ///
    /// # Errors
    /// As [`Self::run`] and the session's local-change errors.
    pub async fn apply_local_op(
        &mut self,
        item_id: &str,
        op: super::engine::LocalOp,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.apply_local_op(item_id, op, now_ms)?;
        self.run(actions, now_ms).await
    }

    /// Local presence JSON, sealed and relayed.
    ///
    /// # Errors
    /// As [`Self::run`] and sealing errors.
    pub async fn set_presence(
        &mut self,
        item_id: &str,
        presence_json: &str,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.set_presence(item_id, presence_json)?;
        self.run(actions, now_ms).await
    }

    /// Closes the items the core opened for an assistant change once their update is
    /// acknowledged (their outcome was posted when the change was applied).
    ///
    /// # Errors
    /// As [`Self::run`].
    pub async fn close_settled_headless(&mut self, now_ms: u64) -> Result<Vec<Event>, LiveError> {
        let mut events = Vec::new();
        for id in self.session.take_settled_headless() {
            // An assistant change stores its own version; closing it writes no session version.
            let actions = self.session.close(&id);
            events.extend(self.run(actions, now_ms).await?);
        }
        Ok(events)
    }

    /// Closes an item.
    ///
    /// # Errors
    /// As [`Self::run`].
    pub async fn close(&mut self, item_id: &str, now_ms: u64) -> Result<Vec<Event>, LiveError> {
        let first = self.session.checkpoint_before_close(item_id);
        let mut events = self.run(first, now_ms).await?;
        let actions = self.session.close(item_id);
        events.extend(self.run(actions, now_ms).await?);
        Ok(events)
    }

    /// Restores a document or sheet version through the open replica and encrypted revision writer.
    /// A stale selection, unavailable version or failed checkpoint returns a typed error.
    pub async fn restore_version(
        &mut self,
        item_id: &str,
        source: i64,
        head: i64,
        now_ms: u64,
    ) -> Result<(Vec<Event>, i64, String), LiveError> {
        let base = self.io.read_version_text(item_id, head).await?;
        let restored = self.io.read_version_text(item_id, source).await?;
        let prepared = self
            .session
            .prepare_version_restore(item_id, source, head, &base, &restored)?;
        let version = match self.io.write_checkpoint(&prepared.checkpoint).await {
            CheckpointResult::Written(version) => version,
            CheckpointResult::Conflict(_) => return Err(LiveError::Io("live_restore_stale")),
            CheckpointResult::Failed => {
                return Err(LiveError::Io("live_restore_checkpoint_failed"));
            }
        };
        let actions = self
            .session
            .finish_version_restore(&prepared, version, now_ms)?;
        let events = self.run(actions, now_ms).await?;
        Ok((events, version, prepared.checkpoint.text))
    }

    /// Undoes the most recent assistant edit when it follows local typing.
    ///
    /// # Errors
    /// The undo transaction or its sealed update could not be applied.
    pub async fn undo_latest_assistant(
        &mut self,
        item_id: &str,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let Some(turn_id) = self.session.take_assistant_undo(item_id) else {
            return Ok(Vec::new());
        };
        let op = super::ops_json::AssistantOp::Undo { turn_id };
        let actions = self.session.apply_assistant_op(item_id, op, now_ms)?;
        self.run(actions, now_ms).await
    }

    /// The core's connection state changed; resubscribes and resends on connect.
    ///
    /// # Errors
    /// As [`Self::run`].
    pub async fn set_connected(
        &mut self,
        connected: bool,
        now_ms: u64,
    ) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.set_connected(connected);
        self.run(actions, now_ms).await
    }

    /// Routes one server frame. Frames whose type does not start with [`FRAME_PREFIX`] are
    /// not live frames: `Ok(None)` is returned so the caller dispatches them elsewhere.
    ///
    /// # Errors
    /// As [`Self::run`] and the session's frame errors.
    pub async fn on_frame(
        &mut self,
        message_type: &str,
        payload: &Value,
        now_ms: u64,
    ) -> Result<Option<Vec<Event>>, LiveError> {
        if !message_type.starts_with(FRAME_PREFIX)
            && !message_type.starts_with(ASSISTANT_FRAME_PREFIX)
        {
            return Ok(None);
        }
        if message_type == "embed_assistant_project_commit" {
            let Some((item, project, operation, revision)) = payload["embed_id"]
                .as_str()
                .zip(payload["project_id"].as_str())
                .zip(payload["operation_id"].as_str())
                .zip(payload["current_revision"].as_i64().filter(|v| *v > 1))
                .map(|(((item, project), operation), revision)| {
                    (item, project, operation, revision)
                })
            else {
                return Ok(Some(Vec::new()));
            };
            if self.io.opened_project(item) != Some(project)
                || !self.session.accepts_project_commit(item, revision)
            {
                return Ok(Some(Vec::new()));
            }
            let base = self.io.read_version_text(item, revision - 1).await?;
            let committed = self.io.read_version_text(item, revision).await?;
            let actions = self
                .session
                .adopt_project_commit(item, operation, revision, &base, &committed, now_ms)?;
            return self.run(actions, now_ms).await.map(Some);
        }
        let actions = self.session.on_frame(message_type, payload, now_ms)?;
        self.run(actions, now_ms).await.map(Some)
    }

    /// Periodic clock tick (the host calls it every 2 seconds): presence expiry and due
    /// checkpoints.
    ///
    /// # Errors
    /// As [`Self::run`].
    pub async fn tick(&mut self, now_ms: u64) -> Result<Vec<Event>, LiveError> {
        let actions = self.session.tick(now_ms);
        self.run(actions, now_ms).await
    }
}
