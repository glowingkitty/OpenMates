//! Full canonical personal-saved read under SAME original recovery boundary.
//! No Client/socket clone, scope recapture, retained-cache fallback or focus write.
use super::super::completion_recovery::OriginalRecoveryRowBoundary;
use super::super::owned_operation::{ActiveOwnedClient, OwnedOperationScope};
use super::super::plaintext::Plain;
use super::super::transport::{
    CompletedOwnedRead, OwnedReadBody, OwnedReadHeaders, OwnedReadRoute, PreparedOwnedRead,
    drive_owned_read_body, send_owned_read_headers,
};
use super::super::*;
use crate::crypto::master::MasterCapability;
use std::sync::{Arc, Mutex};
use zeroize::Zeroizing;

struct RowState {
    expected: Option<Value>,
    history_before: String,
    history_after: Option<String>,
    wrappers: String,
    mutated: bool,
}
struct Data {
    key: Option<Key>,
    item: Option<Plain<Item>>,
    history: Option<super::canonical_history::CanonicalHistory>,
    chat: Option<Plain<Chat>>,
    taken: bool,
    explicit_terminal: Option<bool>,
}
struct Context {
    original: Arc<OwnedOperationScope>,
    handoff: Arc<OriginalHintRecoveryHandoff>,
    boundary: Arc<OriginalRecoveryRowBoundary>,
    id: String,
    cancel: CancellationToken,
    row: Mutex<RowState>,
    data: Mutex<Data>,
}
impl Drop for Context {
    fn drop(&mut self) {
        self.cancel.cancel();
    }
}
/// Streaming ciphertext fingerprints are negative target-only stability checks,
/// not snapshots, read grants or caller-constructible transition receipts.
fn stamp(value: &impl serde::Serialize) -> Result<String> {
    use sha2::{Digest, Sha256};
    struct Sink(Sha256);
    impl std::io::Write for Sink {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            self.0.update(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut sink = Sink(Sha256::new());
    serde_json::to_writer(&mut sink, value)?;
    Ok(crypto::hex(&sink.0.finalize()))
}
fn history_stamp(client: &Client, id: &str) -> Result<String> {
    stamp(&client.history.get(id))
}
fn wrappers_stamp(client: &Client, id: &str) -> Result<String> {
    let hash = sha256(id);
    // References only. No full Client snapshot or wrapper/key publication.
    let rows = client
        .wrappers
        .iter()
        .filter(|row| text(row, "hashed_chat_id") == hash)
        .collect::<Vec<_>>();
    stamp(&rows)
}
impl Context {
    fn negative(&self) -> Result<()> {
        self.boundary.negative()?;
        self.original.observer().check_release()?;
        if self.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.boundary.negative()
    }
    async fn cancelled(&self) {
        tokio::select! {_=self.cancel.cancelled()=>{},_=self.boundary.cancelled()=>{}}
    }
    fn check_root(&self, client: &Client) -> Result<()> {
        self.boundary
            .check_root(client, &self.original, &self.handoff)?;
        self.original.crypto.check_chat(client, &self.id)?;
        client.require_canonical_read_profile()?;
        self.negative()
    }
    fn check_row(&self, client: &Client) -> Result<()> {
        self.check_root(client)?;
        let state = self.row.lock().map_err(|_| Error::Cancelled)?;
        if client.chats.get(&self.id) != state.expected.as_ref()
            || wrappers_stamp(client, &self.id)? != state.wrappers
        {
            return Err(Error::Conflict);
        }
        drop(state);
        self.negative()
    }
    fn check_completed(&self, client: &Client) -> Result<()> {
        self.check_row(client)?;
        let state = self.row.lock().map_err(|_| Error::Cancelled)?;
        if !state.mutated
            || state.history_after.as_deref() != Some(history_stamp(client, &self.id)?.as_str())
        {
            return Err(Error::Conflict);
        }
        drop(state);
        self.negative()
    }
    fn insert_metadata(&self, client: &mut Client, row: Value) -> Result<()> {
        self.check_row(client)?;
        client.insert_chat_row(self.id.clone(), row);
        let mut state = self.row.lock().map_err(|_| Error::Cancelled)?;
        state.expected = client.chats.get(&self.id).cloned();
        state.mutated = true;
        drop(state);
        self.check_row(client)
    }
    fn finish_history(
        &self,
        client: &mut Client,
        chat: Plain<Chat>,
        history: Vec<Value>,
    ) -> Result<()> {
        self.check_row(client)?;
        let original_history = self
            .row
            .lock()
            .map_err(|_| Error::Cancelled)?
            .history_before
            .clone();
        if history_stamp(client, &self.id)? != original_history {
            return Err(Error::Conflict);
        }
        // Genuine canonical result only. Never touch active_chat or restore a
        // global focus/cache snapshot around this owned sibling operation.
        client.history.insert(self.id.clone(), history);
        client.sync_message_windows.remove(&self.id);
        client.selected_first_pages.remove(&self.id);
        let after = history_stamp(client, &self.id)?;
        self.row.lock().map_err(|_| Error::Cancelled)?.history_after = Some(after);
        self.check_completed(client)?;
        self.data.lock().map_err(|_| Error::Cancelled)?.chat = Some(chat);
        Ok(())
    }
}
/// No constructor/Clone/serde/Debug outside the actual original Client prepare.
pub(in crate::client) struct PreparedOwnedCanonicalChatRead {
    context: Option<Arc<Context>>,
}
impl Drop for PreparedOwnedCanonicalChatRead {
    fn drop(&mut self) {
        if let Some(context) = &self.context {
            context.cancel.cancel();
        }
    }
}
impl Client {
    pub(in crate::client) fn prepare_original_canonical_chat_read(
        &self,
        original: Arc<OwnedOperationScope>,
        handoff: Arc<OriginalHintRecoveryHandoff>,
        boundary: Arc<OriginalRecoveryRowBoundary>,
    ) -> Result<PreparedOwnedCanonicalChatRead> {
        if !Arc::ptr_eq(&original, &handoff.scope_arc()) {
            return Err(Error::Cancelled);
        }
        boundary.check_before_io(self, &original, &handoff)?;
        original.check(self)?;
        self.require_canonical_read_profile()?;
        let id = handoff.job().chat_id.clone();
        if self.is_ephemeral_chat(&id) {
            return Err(Error::Invalid(
                "Volatile chat history exists only in the caller's memory.",
            ));
        }
        uuid::Uuid::parse_str(&id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        // Current browser-hint recovery is personal saved only. Never await an
        // unsupported Team/Direct/draft helper under a coarse Client borrow.
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        boundary.claim_canonical_driver(self, &original, &handoff)?;
        let cancel = original.child().child_token();
        let context = Arc::new(Context {
            row: Mutex::new(RowState {
                expected: self.chats.get(&id).cloned(),
                history_before: history_stamp(self, &id)?,
                history_after: None,
                wrappers: wrappers_stamp(self, &id)?,
                mutated: false,
            }),
            data: Mutex::new(Data {
                key: None,
                item: None,
                history: None,
                chat: None,
                taken: false,
                explicit_terminal: None,
            }),
            original,
            handoff,
            boundary,
            id,
            cancel,
        });
        context.check_row(self)?;
        Ok(PreparedOwnedCanonicalChatRead {
            context: Some(context),
        })
    }
}
#[derive(Clone, Copy)]
enum Target {
    Metadata,
    Window,
}
enum ApplyKind {
    Start,
    Headers(Target, OwnedReadHeaders),
    Body(Target, CompletedOwnedRead),
    Key(Key, Plain<Item>),
    Decoded(bool),
    Rendered(Plain<Chat>, Vec<Value>),
}
enum IoKind {
    Headers(Target, PreparedOwnedRead),
    Body(Target, OwnedReadBody),
    Key(Value, MasterCapability, Zeroizing<String>),
    Decode(Value),
    Render,
}
enum Next {
    Apply(ApplyKind),
    Io(IoKind),
    Ready,
    Failed(Error),
}
pub(in crate::client) struct OwnedCanonicalChatApply {
    context: Arc<Context>,
    sequence: u64,
    kind: Option<ApplyKind>,
}
pub(in crate::client) struct OwnedCanonicalChatIo {
    context: Arc<Context>,
    sequence: u64,
    kind: Option<IoKind>,
}
pub(in crate::client) struct OwnedCanonicalChatResume {
    context: Arc<Context>,
    sequence: u64,
    next: Option<Next>,
}
pub(in crate::client) enum OwnedCanonicalChatStep {
    Apply(OwnedCanonicalChatApply),
    Io(OwnedCanonicalChatIo),
    Ready(OriginalCanonicalChatReadResult),
}
pub(in crate::client) struct OwnedCanonicalChatDriver {
    context: Arc<Context>,
    next: Option<Next>,
    sequence: u64,
    outstanding: Option<u64>,
    finished: bool,
}
impl PreparedOwnedCanonicalChatRead {
    pub(in crate::client) fn into_driver(mut self) -> Result<OwnedCanonicalChatDriver> {
        let context = self.context.take().ok_or(Error::Cancelled)?;
        context.negative()?;
        Ok(OwnedCanonicalChatDriver {
            context,
            next: Some(Next::Apply(ApplyKind::Start)),
            sequence: 0,
            outstanding: None,
            finished: false,
        })
    }
}
impl Drop for OwnedCanonicalChatDriver {
    fn drop(&mut self) {
        if !self.finished {
            self.context.cancel.cancel();
        }
    }
}
impl OwnedCanonicalChatDriver {
    pub(in crate::client) async fn next(&mut self) -> Result<OwnedCanonicalChatStep> {
        if self.finished {
            return Err(Error::Cancelled);
        }
        if self.outstanding.is_some() {
            return Err(Error::Conflict);
        }
        let next = self.next.take().ok_or(Error::Cancelled)?;
        // A real dispatched header MUST reach actual matched cookie Apply even
        // after local cancellation; it is not a plaintext/read continuation.
        if !matches!(
            &next,
            Next::Apply(ApplyKind::Headers(_, _)) | Next::Failed(_)
        ) {
            self.context.negative()?;
        }
        self.sequence = self.sequence.checked_add(1).ok_or(Error::Protocol)?;
        match next {
            Next::Apply(kind) => {
                self.outstanding = Some(self.sequence);
                Ok(OwnedCanonicalChatStep::Apply(OwnedCanonicalChatApply {
                    context: self.context.clone(),
                    sequence: self.sequence,
                    kind: Some(kind),
                }))
            }
            Next::Io(kind) => {
                self.outstanding = Some(self.sequence);
                Ok(OwnedCanonicalChatStep::Io(OwnedCanonicalChatIo {
                    context: self.context.clone(),
                    sequence: self.sequence,
                    kind: Some(kind),
                }))
            }
            Next::Ready => {
                self.finished = true;
                Ok(OwnedCanonicalChatStep::Ready(
                    OriginalCanonicalChatReadResult {
                        context: self.context.clone(),
                    },
                ))
            }
            Next::Failed(error) => {
                self.finished = true;
                Err(error)
            }
        }
    }
    pub(in crate::client) fn resume(&mut self, mut resume: OwnedCanonicalChatResume) -> Result<()> {
        if !Arc::ptr_eq(&self.context, &resume.context) || self.outstanding != Some(resume.sequence)
        {
            return Err(Error::Cancelled);
        }
        self.next = Some(resume.next.take().ok_or(Error::Cancelled)?);
        self.outstanding = None;
        Ok(())
    }
}
fn window(context: &Arc<Context>, client: &mut Client) -> Result<Next> {
    context.check_row(client)?;
    let before = {
        let data = context.data.lock().map_err(|_| Error::Cancelled)?;
        let history = data.history.as_ref().ok_or(Error::Protocol)?;
        history.before_request()?;
        history.cursor().cloned()
    };
    Ok(Next::Io(IoKind::Headers(
        Target::Window,
        client.prepare_owned_read(OwnedReadRoute::CanonicalChatMessages {
            chat_id: &context.id,
            before: before.as_ref(),
        })?,
    )))
}
impl OwnedCanonicalChatApply {
    pub(in crate::client) fn run(
        mut self,
        client: &mut Client,
    ) -> Result<OwnedCanonicalChatResume> {
        let kind = self.kind.take().ok_or(Error::Cancelled)?;
        let next = if let ApplyKind::Headers(target, headers) = kind {
            // No original-negative precheck can discard actual rotated headers.
            match client.apply_owned_read_headers(headers) {
                Ok(body) => match self.context.check_row(client) {
                    Ok(()) => Next::Io(IoKind::Body(target, body)),
                    Err(error) => Next::Failed(error),
                },
                Err(error) => Next::Failed(error),
            }
        } else {
            match self.checked(client, kind) {
                Ok(next) => next,
                Err(error) => Next::Failed(error),
            }
        };
        Ok(OwnedCanonicalChatResume {
            context: self.context.clone(),
            sequence: self.sequence,
            next: Some(next),
        })
    }
    fn checked(&self, client: &mut Client, kind: ApplyKind) -> Result<Next> {
        self.context.check_row(client)?;
        let mut active = ActiveOwnedClient::enter(client, &self.context.original)?;
        match kind {
            ApplyKind::Start => Ok(Next::Io(IoKind::Headers(
                Target::Metadata,
                active.prepare_owned_read(OwnedReadRoute::ChatMetadata {
                    chat_id: &self.context.id,
                    include_read_details: false,
                })?,
            ))),
            ApplyKind::Body(target, completed) => {
                let value = active.finish_owned_read(completed)?;
                self.context.check_row(&active)?;
                match target {
                    Target::Metadata => {
                        let metadata =
                            value.ok_or(Error::Invalid("The requested item is unavailable."))?;
                        let row = metadata["chats"]
                            .as_array()
                            .ok_or(Error::Protocol)?
                            .iter()
                            .find(|r| text(r, "id") == self.context.id)
                            .ok_or(Error::Forbidden)?
                            .clone();
                        if super::draft_only(&row) {
                            return Err(Error::Invalid(
                                "Owned canonical recovery requires a saved chat.",
                            ));
                        }
                        if text(&row, "chat_visibility") == "direct" || active.team()?.is_some() {
                            return Err(Error::Forbidden);
                        }
                        let wrapping = active.master_capability()?;
                        let encrypted = Zeroizing::new(
                            active
                                .chat_key_ciphertext_from(&row, false, &active.wrappers)?
                                .ciphertext
                                .to_owned(),
                        );
                        self.context.insert_metadata(&mut active, row.clone())?;
                        Ok(Next::Io(IoKind::Key(row, wrapping, encrypted)))
                    }
                    Target::Window => Ok(Next::Io(IoKind::Decode(value.ok_or(Error::Protocol)?))),
                }
            }
            ApplyKind::Key(key, item) => {
                {
                    let mut data = self.context.data.lock().map_err(|_| Error::Cancelled)?;
                    data.key = Some(key);
                    data.item = Some(item);
                    data.history = Some(super::canonical_history::CanonicalHistory::new(
                        &self.context.id,
                    ));
                }
                window(&self.context, &mut active)
            }
            ApplyKind::Decoded(complete) => {
                if complete {
                    Ok(Next::Io(IoKind::Render))
                } else {
                    window(&self.context, &mut active)
                }
            }
            ApplyKind::Rendered(chat, history) => {
                self.context.finish_history(&mut active, chat, history)?;
                Ok(Next::Ready)
            }
            ApplyKind::Headers(_, _) => Err(Error::Protocol),
        }
    }
}
impl OwnedCanonicalChatIo {
    pub(in crate::client) async fn drive(mut self) -> Result<OwnedCanonicalChatResume> {
        let kind = self.kind.take().ok_or(Error::Cancelled)?;
        let next = match self.drive_kind(kind).await {
            Ok(kind) => Next::Apply(kind),
            Err(error) => Next::Failed(error),
        };
        Ok(OwnedCanonicalChatResume {
            context: self.context.clone(),
            sequence: self.sequence,
            next: Some(next),
        })
    }
    async fn drive_kind(&self, kind: IoKind) -> Result<ApplyKind> {
        self.context.negative()?;
        match kind {
            IoKind::Headers(target, prepared) => {
                // Once dispatched, drain actual header IO independently of local
                // cancellation. Actual Client cookie binding still validates it.
                let dispatched = CancellationToken::new();
                let headers =
                    send_owned_read_headers(prepared, &dispatched, || self.context.negative())
                        .await?;
                Ok(ApplyKind::Headers(target, headers))
            }
            IoKind::Body(target, body) => {
                let completed = tokio::select! {biased;
                    _=self.context.cancelled()=>return Err(Error::Cancelled),
                    result=drive_owned_read_body(body,&self.context.cancel,||self.context.negative())=>result?,
                };
                Ok(ApplyKind::Body(target, completed))
            }
            IoKind::Key(row, wrapping, encrypted) => {
                let bytes = tokio::select! {biased;
                    _=self.context.cancelled()=>return Err(Error::Cancelled),
                    result=wrapping.decrypt_bytes(&encrypted)=>result?,
                };
                self.context.negative()?;
                let key = key_from_bytes(&bytes)?;
                let item = Plain::new(super::canonical_history::saved_item(&row, &key)?);
                self.context.negative()?;
                Ok(ApplyKind::Key(key, item))
            }
            IoKind::Decode(page) => {
                let complete = {
                    let mut data = self.context.data.lock().map_err(|_| Error::Cancelled)?;
                    let key = data.key.as_ref().ok_or(Error::Protocol)?.clone();
                    let history = data.history.as_mut().ok_or(Error::Protocol)?;
                    let decoded = history.decode_page(page, &key)?;
                    history.append_page(decoded)?
                };
                self.context.negative()?;
                Ok(ApplyKind::Decoded(complete))
            }
            IoKind::Render => {
                let (history, mut item, key) = {
                    let mut data = self.context.data.lock().map_err(|_| Error::Cancelled)?;
                    (
                        data.history.take().ok_or(Error::Protocol)?,
                        data.item.take().ok_or(Error::Protocol)?,
                        data.key.as_ref().ok_or(Error::Protocol)?.clone(),
                    )
                };
                let (messages, history, explicit_terminal) = history.into_parts()?;
                self.context
                    .data
                    .lock()
                    .map_err(|_| Error::Cancelled)?
                    .explicit_terminal = Some(explicit_terminal);
                let mut chat = Plain::new(Chat {
                    id: self.context.id.clone(),
                    title: std::mem::take(&mut item.title),
                    category: std::mem::take(&mut item.category),
                    messages: messages.into_inner(),
                });
                super::restore_chat_tokens_from_rows(&mut chat, &key, &history)?;
                self.context.negative()?;
                Ok(ApplyKind::Rendered(chat, history))
            }
        }
    }
}
/// Canonical completion only; metadata/DTO/checkpoint data cannot construct it.
pub(in crate::client) struct OriginalCanonicalChatReadResult {
    context: Arc<Context>,
}
pub(in crate::client) struct OriginalCanonicalRowTransition {
    context: Arc<Context>,
}
/// Exact actual canonical transcript only. No sidecar/store/hint completion.
pub(in crate::client) struct OriginalCanonicalChatArtifacts {
    context: Arc<Context>,
}
pub(in crate::client) enum CanonicalArtifactScope {
    TranscriptCiphertextRowsOnly,
}
impl OriginalCanonicalChatReadResult {
    pub(in crate::client) fn check_original(
        &self,
        client: &Client,
        original: &Arc<OwnedOperationScope>,
        handoff: &Arc<OriginalHintRecoveryHandoff>,
        boundary: &Arc<OriginalRecoveryRowBoundary>,
    ) -> Result<()> {
        if !Arc::ptr_eq(&self.context.original, original)
            || !Arc::ptr_eq(&self.context.handoff, handoff)
            || !Arc::ptr_eq(&self.context.boundary, boundary)
        {
            return Err(Error::Cancelled);
        }
        self.context.check_completed(client)
    }
    pub(in crate::client) fn take_parts(
        self,
        client: &Client,
        original: &Arc<OwnedOperationScope>,
        handoff: &Arc<OriginalHintRecoveryHandoff>,
        boundary: &Arc<OriginalRecoveryRowBoundary>,
    ) -> Result<(
        Plain<Chat>,
        Key,
        OriginalCanonicalRowTransition,
        OriginalCanonicalChatArtifacts,
    )> {
        self.check_original(client, original, handoff, boundary)?;
        let mut data = self.context.data.lock().map_err(|_| Error::Cancelled)?;
        if data.taken {
            return Err(Error::Cancelled);
        }
        data.taken = true;
        let chat = data.chat.take().ok_or(Error::Protocol)?;
        let key = data.key.take().ok_or(Error::Protocol)?;
        drop(data);
        self.context.check_completed(client)?;
        Ok((
            chat,
            key,
            OriginalCanonicalRowTransition {
                context: self.context.clone(),
            },
            OriginalCanonicalChatArtifacts {
                context: self.context.clone(),
            },
        ))
    }
}
impl OriginalCanonicalRowTransition {
    pub(in crate::client) fn check_original(
        &self,
        client: &Client,
        original: &Arc<OwnedOperationScope>,
        handoff: &Arc<OriginalHintRecoveryHandoff>,
        boundary: &Arc<OriginalRecoveryRowBoundary>,
    ) -> Result<()> {
        if !Arc::ptr_eq(&self.context.original, original)
            || !Arc::ptr_eq(&self.context.handoff, handoff)
            || !Arc::ptr_eq(&self.context.boundary, boundary)
        {
            return Err(Error::Cancelled);
        }
        self.context.check_completed(client)
    }
    pub(in crate::client) fn before_row(&self) -> &Option<Value> {
        self.context.boundary.before_row()
    }
    pub(in crate::client) fn after_row(&self) -> Result<Option<Value>> {
        Ok(self
            .context
            .row
            .lock()
            .map_err(|_| Error::Cancelled)?
            .expected
            .clone())
    }
}

impl OriginalCanonicalChatArtifacts {
    /// Existing canonical API legacy terminal semantics, DATA only. This does
    /// not assert sidecar/store/full-hint/inventory completion or grant reuse.
    pub(in crate::client) fn observed_explicit_terminal(&self) -> Result<bool> {
        self.context.negative()?;
        self.context
            .data
            .lock()
            .map_err(|_| Error::Cancelled)?
            .explicit_terminal
            .ok_or(Error::Protocol)
    }
    pub(in crate::client) fn coverage(&self) -> CanonicalArtifactScope {
        CanonicalArtifactScope::TranscriptCiphertextRowsOnly
    }
    pub(in crate::client) fn checked_ciphertext_rows<'a>(
        &'a self,
        client: &'a Client,
        original: &Arc<OwnedOperationScope>,
        handoff: &Arc<OriginalHintRecoveryHandoff>,
        boundary: &Arc<OriginalRecoveryRowBoundary>,
    ) -> Result<&'a [Value]> {
        if !Arc::ptr_eq(&self.context.original, original)
            || !Arc::ptr_eq(&self.context.handoff, handoff)
            || !Arc::ptr_eq(&self.context.boundary, boundary)
        {
            return Err(Error::Cancelled);
        }
        self.context.check_completed(client)?;
        client
            .history
            .get(&self.context.id)
            .map(Vec::as_slice)
            .ok_or(Error::Protocol)
    }
}

#[cfg(test)]
#[path = "canonical_owned_tests.rs"]
mod tests;
