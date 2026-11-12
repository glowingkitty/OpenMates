//! Assistant Memory write jobs of a saved turn (`memory_write_jobs` capability).
//!
//! The server's internal `save_memory` tool hands a validated cleartext document
//! to the user's capable device with the chat open (contract:
//! `backend/apps/ai/processing/memory_write_tool.py`, protocol 1):
//! `memory_write_job_available` -> `memory_write_job_claim` ->
//! `memory_write_job_claim_result` (granted) -> encrypt and store with
//! [`super::memory_documents`] -> encrypted `context_entry` history notice
//! (assistant-sourced, with Undo data) -> `memory_write_job_result` ->
//! `memory_write_job_result_ack`. Shells print [`MemoryJobState::take_notices`]
//! and read the per-job records. Plan: `docs/plans/assistant-memory-writes/`.
use super::memory_documents::{
    MemoryDocumentError, MemoryResult, MemoryWriteMode, PersonalMemoryDocument,
    PreparedMemorySettings, document_sha256, prepare_memory_delete, prepare_memory_write,
    read_memory_documents, validate_memory_document,
};
use super::plaintext::Wipe;
use super::recommendations::{
    CONTEXT_ENTRY_TYPE, ContextEntryAction, ContextEntryHistoryEvent, ContextEntrySource,
    ContextEntryUndo, RecommendationAction, RecommendationKind, build_context_entry_event,
    parse_context_entry_event,
};
use super::transport::{Socket, send, wait};
use super::*;
use crate::crypto::master::MasterCapability;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::fmt;
use zeroize::Zeroizing;

/// WebSocket and turn capability that opts into assistant Memory writes.
pub(super) const MEMORY_WRITE_JOBS_CAPABILITY: &str = "memory_write_jobs";
const PROTOCOL: u64 = 1;
const AVAILABLE: &str = "memory_write_job_available";
const CLAIM: &str = "memory_write_job_claim";
const CLAIM_RESULT: &str = "memory_write_job_claim_result";
const RESULT: &str = "memory_write_job_result";
const RESULT_ACK: &str = "memory_write_job_result_ack";
/// Jobs remembered per turn (idempotency of repeated frames).
const MAX_JOBS: usize = 32;
/// The server waits 20 s for the result; the notice must confirm well before.
const NOTICE_TIMEOUT: Duration = Duration::from_secs(10);

/// Frames of this protocol that the turn loop routes here.
pub(super) fn is_job_frame(kind: &str) -> bool {
    matches!(kind, AVAILABLE | CLAIM_RESULT | RESULT_ACK)
}

/// Outcome of one job on this device.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryWriteStatus {
    /// Stored encrypted and reported `applied`.
    Applied,
    /// Reported `failed` with an `errorCode`; the Memory is unchanged.
    Failed,
    /// The server gave the job to another device (or refused the claim).
    NotGranted,
}

/// One job of the turn, as shells show it (`memoryWrites` in `--json`).
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MemoryWriteRecord {
    /// Server job id.
    pub job_id: String,
    /// `create` or `update`.
    pub action: RecommendationAction,
    /// Memory id as the server named it (reported back in the result).
    pub memory_id: String,
    /// Stored id (`personal:<uuid>`); `settings memories list` shows it as
    /// `account-memory-<uuid>`.
    pub entry_id: String,
    /// Memory title.
    pub title: String,
    /// What happened on this device.
    pub status: MemoryWriteStatus,
    /// Reported `error_code` of a failed job.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_code: Option<String>,
    /// Server reason of a refused claim or result.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Whether the server accepted the result (`None` before the ack).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub accepted: Option<bool>,
    /// Id of the encrypted `context_entry` history message.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub notice_message_id: Option<String>,
    /// True when the history notice carries Undo data.
    pub undo_available: bool,
}

/// A parsed job. The document is private and wiped on drop.
#[derive(Clone)]
struct Job {
    job_id: String,
    chat_id: String,
    message_id: String,
    action: RecommendationAction,
    memory_id: String,
    entry_id: String,
    title: Zeroizing<String>,
    document: Zeroizing<String>,
    expires_at: u64,
    /// Set when the job is well addressed but unusable; reported after the claim.
    defect: Option<&'static str>,
}

/// Per-turn state of the protocol, carried with the Project state of the turn.
#[derive(Clone, Default)]
pub(super) struct MemoryJobState {
    pending: BTreeMap<String, Job>,
    finished: BTreeSet<String>,
    records: Vec<MemoryWriteRecord>,
    notices: Vec<String>,
    /// The turn's chat key, so the notice needs no extra chat read.
    chat_key: Option<Key>,
}

impl fmt::Debug for MemoryJobState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Never print documents or the chat key.
        f.debug_struct("MemoryJobState")
            .field("pending", &self.pending.len())
            .field("records", &self.records.len())
            .finish_non_exhaustive()
    }
}

impl MemoryJobState {
    /// Remember the turn's chat key for the history notice.
    pub(super) fn set_chat_key(&mut self, key: &[u8; 32]) {
        self.chat_key = Some(Zeroizing::new(*key));
    }

    /// One-line summaries for the shell (created, updated or not saved).
    pub(super) fn take_notices(&mut self) -> Vec<String> {
        std::mem::take(&mut self.notices)
    }

    /// The turn's job records as camelCase JSON.
    pub(super) fn records(&self) -> Vec<Value> {
        self.records
            .iter()
            .filter_map(|record| serde_json::to_value(record).ok())
            .collect()
    }

    pub(super) fn clear(&mut self) {
        self.pending.clear();
        self.finished.clear();
        self.records.clear();
        self.notices.clear();
        self.chat_key = None;
    }

    fn record(&mut self, job: &Job, status: MemoryWriteStatus) -> &mut MemoryWriteRecord {
        self.records.push(MemoryWriteRecord {
            job_id: job.job_id.clone(),
            action: job.action,
            memory_id: job.memory_id.clone(),
            entry_id: job.entry_id.clone(),
            title: job.title.to_string(),
            status,
            error_code: None,
            reason: None,
            accepted: None,
            notice_message_id: None,
            undo_available: false,
        });
        self.records.last_mut().expect("a record was just pushed")
    }
}

impl Wipe for MemoryJobState {
    fn wipe(&mut self) {
        self.clear();
    }
}

/// What the job runner can do; the real one wraps [`Client`] and the turn
/// socket, tests use an in-memory runner.
pub(super) trait MemoryJobRunner {
    /// Store `document` under `entry_id`; returns the replaced document.
    async fn write(
        &mut self,
        entry_id: &str,
        document: &str,
        mode: MemoryWriteMode,
    ) -> MemoryResult<Option<Zeroizing<String>>>;
    /// Delete `entry_id` (rollback of a create).
    async fn delete(&mut self, entry_id: &str) -> MemoryResult<()>;
    /// Seal the previous document with the master key for Undo.
    async fn seal(&mut self, previous: &str) -> Result<String>;
    /// Store the encrypted `context_entry` system message and await its confirmation.
    async fn notice(
        &mut self,
        chat: &str,
        user_message: &str,
        message_id: &str,
        content: &str,
        key: Option<&[u8; 32]>,
    ) -> Result<()>;
}

fn bounded<'a>(event: &'a Value, key: &str, max: usize) -> Option<&'a str> {
    event[key]
        .as_str()
        .filter(|v| !v.is_empty() && v.len() <= max)
}

fn job_id_of<'a>(event: &'a Value, chat: &str) -> Option<&'a str> {
    let id = bounded(event, "job_id", 128).filter(|id| {
        id.chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | ':'))
    })?;
    (event["chat_id"].as_str() == Some(chat)).then_some(id)
}

/// `memory_write_job_available` of this chat; `None` for frames that are not
/// addressed to this turn (never claimed, the server times them out).
fn parse_job(event: &Value, chat: &str) -> Option<Job> {
    if event["protocol"].as_u64() != Some(PROTOCOL) {
        return None;
    }
    let job_id = job_id_of(event, chat)?.to_owned();
    let mut defect = None;
    let action = match event["action"].as_str() {
        Some("create") => RecommendationAction::Create,
        Some("update") => RecommendationAction::Update,
        _ => {
            defect = Some("invalid_job");
            RecommendationAction::Create
        }
    };
    let memory_id = bounded(event, "memory_id", 230)
        .unwrap_or_default()
        .to_owned();
    let title = bounded(event, "title", 720).unwrap_or_default();
    let document = event["document"].as_str().unwrap_or_default();
    if memory_id.is_empty()
        || title.trim().is_empty()
        || bounded(event, "message_id", 128).is_none()
    {
        defect = defect.or(Some("invalid_job"));
    }
    if validate_memory_document(document).is_err() {
        defect = defect.or(Some("invalid_rule_document"));
    }
    // A created Memory gets the web id form; an update names the stored id.
    let entry_id = if action == RecommendationAction::Create && !memory_id.starts_with("personal:")
    {
        format!("personal:{memory_id}")
    } else {
        memory_id.clone()
    };
    Some(Job {
        job_id,
        chat_id: chat.to_owned(),
        message_id: bounded(event, "message_id", 128)
            .unwrap_or_default()
            .to_owned(),
        action,
        memory_id,
        entry_id,
        title: Zeroizing::new(title.trim().to_owned()),
        document: Zeroizing::new(document.to_owned()),
        expires_at: event["expires_at"].as_u64().unwrap_or(0),
        defect,
    })
}

fn scope(job: &Job) -> Value {
    json!({"protocol": PROTOCOL, "job_id": job.job_id, "chat_id": job.chat_id})
}

/// `applied` when `code` is `None`, else `failed` with that lowercase code.
fn result_frame(job: &Job, code: Option<&str>) -> (&'static str, Value) {
    let mut payload = scope(job);
    payload["status"] = json!(if code.is_some() { "failed" } else { "applied" });
    payload["memory_id"] = json!(job.memory_id);
    if let Some(code) = code {
        payload["error_code"] = json!(code);
    }
    (RESULT, payload)
}

/// Why a granted job was not applied.
enum Failure {
    Code(&'static str),
    Cancelled,
}

impl From<MemoryDocumentError> for Failure {
    fn from(error: MemoryDocumentError) -> Self {
        match error {
            MemoryDocumentError::Core(Error::Cancelled) => Self::Cancelled,
            other => Self::Code(other.code()),
        }
    }
}

/// The notice event: assistant-sourced, with what Undo needs.
fn notice_event(
    job: &Job,
    now_s: u64,
    previous_sealed: Option<String>,
) -> ContextEntryHistoryEvent {
    let updated = job.action == RecommendationAction::Update;
    ContextEntryHistoryEvent {
        schema_version: 1,
        event_type: CONTEXT_ENTRY_TYPE.into(),
        kind: RecommendationKind::Memory,
        action: if updated {
            ContextEntryAction::Updated
        } else {
            ContextEntryAction::Created
        },
        entry_id: job.entry_id.clone(),
        title: job.title.to_string(),
        created_at: i64::try_from(now_s).unwrap_or(i64::MAX),
        source: Some(ContextEntrySource::Assistant),
        undo: Some(ContextEntryUndo {
            job_id: job.job_id.clone(),
            action: job.action,
            written_document_sha256: document_sha256(&job.document),
            encrypted_previous_document: previous_sealed,
        }),
    }
}

/// Put the Memory back as it was before this job. Best effort: the caller
/// decides what to report when it fails.
async fn rollback<R: MemoryJobRunner>(runner: &mut R, job: &Job, previous: Option<&str>) -> bool {
    match previous {
        Some(previous) => runner
            .write(&job.entry_id, previous, MemoryWriteMode::Update)
            .await
            .is_ok(),
        None => runner.delete(&job.entry_id).await.is_ok(),
    }
}

/// Store the Memory, then the notice. Returns the notice id, or `None` when
/// the Memory is stored but neither the notice nor the rollback succeeded
/// (then `applied` is the truthful report, without Undo).
async fn write_and_notice<R: MemoryJobRunner>(
    runner: &mut R,
    job: &Job,
    now_s: u64,
    key: Option<&[u8; 32]>,
) -> std::result::Result<Option<String>, Failure> {
    if let Some(defect) = job.defect {
        return Err(Failure::Code(defect));
    }
    if job.expires_at <= now_s {
        return Err(Failure::Code("job_expired"));
    }
    let mode = match job.action {
        RecommendationAction::Create => MemoryWriteMode::Create,
        RecommendationAction::Update => MemoryWriteMode::Update,
    };
    let previous = runner.write(&job.entry_id, &job.document, mode).await?;
    let previous_text = previous.as_deref().map(String::as_str);
    let sealed = match (mode, previous_text) {
        (MemoryWriteMode::Create, _) => None,
        (MemoryWriteMode::Update, Some(text)) => match runner.seal(text).await {
            Ok(sealed) => Some(sealed),
            Err(Error::Cancelled) => return Err(Failure::Cancelled),
            Err(_) => {
                return if rollback(runner, job, previous_text).await {
                    Err(Failure::Code("undo_seal_failed"))
                } else {
                    Ok(None)
                };
            }
        },
        (MemoryWriteMode::Update, None) => return Err(Failure::Code("rule_not_found")),
    };
    let message_id = format!("context-entry-{}", job.job_id);
    let content = build_context_entry_event(&notice_event(job, now_s, sealed))
        .map(Zeroizing::new)
        .map_err(|_| Failure::Code("history_notice_failed"))?;
    match runner
        .notice(&job.chat_id, &job.message_id, &message_id, &content, key)
        .await
    {
        Ok(()) => Ok(Some(message_id)),
        Err(Error::Cancelled) => Err(Failure::Cancelled),
        Err(_) if rollback(runner, job, previous_text).await => {
            Err(Failure::Code("history_notice_failed"))
        }
        Err(_) => Ok(None),
    }
}

async fn apply<R: MemoryJobRunner>(
    runner: &mut R,
    job: Job,
    now_s: u64,
    state: &mut MemoryJobState,
) -> Result<Vec<(&'static str, Value)>> {
    let key = state.chat_key.clone();
    let outcome = write_and_notice(runner, &job, now_s, key.as_deref()).await;
    let title = job.title.to_string();
    match outcome {
        Err(Failure::Cancelled) => Err(Error::Cancelled),
        Err(Failure::Code(code)) => {
            state.record(&job, MemoryWriteStatus::Failed).error_code = Some(code.into());
            state
                .notices
                .push(format!("Memory not saved ({code}): {title}"));
            Ok(vec![result_frame(&job, Some(code))])
        }
        Ok(notice) => {
            let record = state.record(&job, MemoryWriteStatus::Applied);
            record.undo_available = notice.is_some();
            record.notice_message_id = notice;
            let verb = if job.action == RecommendationAction::Update {
                "updated"
            } else {
                "created"
            };
            state
                .notices
                .push(format!("Memory {verb} by the assistant: {title}"));
            Ok(vec![result_frame(&job, None)])
        }
    }
}

/// The frames to send for one job frame of the turn's chat `chat`.
///
/// `available` is claimed at once (the server waits 8 s); a granted claim is
/// applied and answered with the result; an ack is recorded. Repeated and
/// unaddressed frames yield nothing.
///
/// # Errors
/// Only cancellation: write and notice failures become `failed` results.
pub(super) async fn job_frames<R: MemoryJobRunner>(
    runner: &mut R,
    kind: &str,
    event: &Value,
    chat: &str,
    now_s: u64,
    state: &mut MemoryJobState,
) -> Result<Vec<(&'static str, Value)>> {
    match kind {
        AVAILABLE => {
            let Some(job) = parse_job(event, chat) else {
                return Ok(Vec::new());
            };
            if state.finished.contains(&job.job_id)
                || state.pending.contains_key(&job.job_id)
                || state.pending.len() + state.finished.len() >= MAX_JOBS
                || job.expires_at <= now_s
            {
                return Ok(Vec::new());
            }
            let claim = (CLAIM, scope(&job));
            state.pending.insert(job.job_id.clone(), job);
            Ok(vec![claim])
        }
        CLAIM_RESULT => {
            let Some(job) = job_id_of(event, chat).and_then(|id| state.pending.remove(id)) else {
                return Ok(Vec::new());
            };
            state.finished.insert(job.job_id.clone());
            if event["granted"] != true {
                let reason = bounded(event, "reason", 64).map(str::to_owned);
                state.record(&job, MemoryWriteStatus::NotGranted).reason = reason;
                return Ok(Vec::new());
            }
            apply(runner, job, now_s, state).await
        }
        RESULT_ACK => {
            let id = job_id_of(event, chat).unwrap_or_default();
            if let Some(record) = state.records.iter_mut().find(|r| r.job_id == id) {
                let accepted = event["accepted"] == true;
                record.accepted = Some(accepted);
                if !accepted {
                    record.reason = bounded(event, "reason", 64).map(str::to_owned);
                }
            }
            Ok(Vec::new())
        }
        _ => Ok(Vec::new()),
    }
}

/// The real runner: the signed-in [`Client`] plus the turn socket.
struct ClientRunner<'a> {
    client: &'a mut Client,
    ws: &'a mut Socket,
}

impl MemoryJobRunner for ClientRunner<'_> {
    async fn write(
        &mut self,
        entry_id: &str,
        document: &str,
        mode: MemoryWriteMode,
    ) -> MemoryResult<Option<Zeroizing<String>>> {
        self.client
            .save_personal_memory_document(entry_id, document, mode)
            .await
    }

    async fn delete(&mut self, entry_id: &str) -> MemoryResult<()> {
        self.client
            .delete_personal_memory_document(entry_id)
            .await
            .map(drop)
    }

    async fn seal(&mut self, previous: &str) -> Result<String> {
        self.client
            .master_capability()?
            .encrypt_server_bytes(previous.as_bytes())
            .await
    }

    async fn notice(
        &mut self,
        chat: &str,
        user_message: &str,
        message_id: &str,
        content: &str,
        key: Option<&[u8; 32]>,
    ) -> Result<()> {
        let key = match key {
            Some(key) => Zeroizing::new(*key),
            None => self.client.work_chat_key(chat).await?,
        };
        // Same shape as the web `chat_system_message_added` write
        // (contextEntryEvents.ts) plus the turn's user message id.
        let mut payload = json!({"chat_id": chat, "message": {
            "message_id": message_id, "chat_id": chat, "role": "system",
            "user_message_id": user_message,
            "encrypted_content": crypto::encrypt_combined(content, &key)?,
            "created_at": now_ms() / 1000, "status": "synced"}});
        if let Some(team) = self.client.team()? {
            payload["team_id"] = json!(team);
        }
        send(self.ws, "chat_system_message_added", payload).await?;
        crate::platform::time::timeout(
            NOTICE_TIMEOUT,
            wait(
                self.ws,
                "system_message_confirmed",
                "message_id",
                message_id,
            ),
        )
        .await
        .map_err(|_| Error::Offline)??;
        Ok(())
    }
}

/// Result of [`Client::undo_assistant_memory_write`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryUndoOutcome {
    /// The created Memory was deleted.
    Deleted,
    /// The updated Memory holds its previous document again.
    Restored,
}

/// Undo data of a valid assistant-written Memory event.
fn undo_data(event: &ContextEntryHistoryEvent) -> MemoryResult<&ContextEntryUndo> {
    let valid = build_context_entry_event(event).is_ok();
    match (&event.undo, valid) {
        (Some(undo), true) => Ok(undo),
        _ => Err(MemoryDocumentError::NotUndoable),
    }
}

/// What Undo does to the current Memory, refusing when it was edited since
/// the assistant's write (its document no longer hashes to the written one).
///
/// # Errors
/// `NotUndoable`, `NotFound` (already deleted), `Changed`.
pub fn undo_decision(
    event: &ContextEntryHistoryEvent,
    current: Option<&PersonalMemoryDocument>,
) -> MemoryResult<MemoryUndoOutcome> {
    let undo = undo_data(event)?;
    let current = current
        .filter(|d| d.id == event.entry_id)
        .ok_or(MemoryDocumentError::NotFound)?;
    if document_sha256(&current.document) != undo.written_document_sha256 {
        return Err(MemoryDocumentError::Changed);
    }
    Ok(match undo.action {
        RecommendationAction::Create => MemoryUndoOutcome::Deleted,
        RecommendationAction::Update => MemoryUndoOutcome::Restored,
    })
}

/// Encrypted settings that undo the write `event` announces, for a shell that
/// posts them itself (web Worker); [`Client::undo_assistant_memory_write`] uses
/// the same step. Reads the current Memories from `ciphertext`, refuses an
/// edited Memory ([`undo_decision`]) and opens the master-key sealed previous
/// document of an update only in memory (zeroized on drop).
///
/// # Errors
/// See [`undo_decision`]; `SettingsUnavailable` when the sealed previous
/// document or the settings cannot be opened; the write/delete errors of
/// `memory_documents`.
pub async fn prepare_memory_undo(
    master: &MasterCapability,
    ciphertext: Option<&str>,
    event: &ContextEntryHistoryEvent,
) -> MemoryResult<(MemoryUndoOutcome, PreparedMemorySettings)> {
    let documents = read_memory_documents(master, ciphertext).await?;
    let current = documents.iter().find(|d| d.id == event.entry_id);
    let outcome = undo_decision(event, current)?;
    let prepared =
        match outcome {
            MemoryUndoOutcome::Deleted => {
                prepare_memory_delete(master, ciphertext, &event.entry_id).await?
            }
            MemoryUndoOutcome::Restored => {
                let sealed = undo_data(event)?
                    .encrypted_previous_document
                    .as_deref()
                    .ok_or(MemoryDocumentError::NotUndoable)?;
                let previous = Zeroizing::new(master.decrypt_text(sealed).await.map_err(
                    |error| match error {
                        Error::Crypto => MemoryDocumentError::SettingsUnavailable,
                        other => other.into(),
                    },
                )?);
                prepare_memory_write(
                    master,
                    ciphertext,
                    &event.entry_id,
                    &previous,
                    MemoryWriteMode::Update,
                )
                .await?
            }
        };
    Ok((outcome, prepared))
}

/// `type` of the undone marker, a chat-key encrypted `role: system` message.
pub const MEMORY_WRITE_UNDONE_TYPE: &str = "memory_write_undone";

/// Persisted "this assistant write was undone" marker of one job.
///
/// Stored as its own system message ([`memory_write_undone_message_id`]),
/// because the server never rewrites a stored message (duplicate message ids
/// are skipped). Shells hide the marker row, show the matching
/// `context_entry` notice as undone, and never send it to the AI.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryWriteUndoneEvent {
    /// Always 1.
    pub schema_version: u8,
    /// Always [`MEMORY_WRITE_UNDONE_TYPE`].
    #[serde(rename = "type")]
    pub event_type: String,
    /// Job id of the undone write (the notice's `undo.job_id`).
    pub job_id: String,
    /// Memory id of the notice.
    pub entry_id: String,
    /// Unix seconds of the Undo.
    pub undone_at: i64,
}

fn valid_job_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | ':'))
}

fn valid_undone(event: &MemoryWriteUndoneEvent) -> bool {
    event.schema_version == 1
        && event.event_type == MEMORY_WRITE_UNDONE_TYPE
        && valid_job_id(&event.job_id)
        && !event.entry_id.is_empty()
        && event.entry_id.len() <= 240
        && event.undone_at >= 0
}

/// Stable id of the undone marker message of `job_id` (one marker per job).
pub fn memory_write_undone_message_id(job_id: &str) -> String {
    format!("context-entry-undone-{job_id}")
}

/// Content of the undone marker for the notice `event`.
///
/// # Errors
/// `NotUndoable` when `event` carries no valid assistant Undo data.
pub fn build_memory_write_undone_event(
    event: &ContextEntryHistoryEvent,
    undone_at: i64,
) -> MemoryResult<String> {
    let undo = undo_data(event)?;
    let marker = MemoryWriteUndoneEvent {
        schema_version: 1,
        event_type: MEMORY_WRITE_UNDONE_TYPE.into(),
        job_id: undo.job_id.clone(),
        entry_id: event.entry_id.clone(),
        undone_at,
    };
    if !valid_undone(&marker) {
        return Err(MemoryDocumentError::NotUndoable);
    }
    serde_json::to_string(&marker).map_err(|_| MemoryDocumentError::NotUndoable)
}

/// The marker of system message content, or `None` for anything else.
pub fn parse_memory_write_undone_event(content: &str) -> Option<MemoryWriteUndoneEvent> {
    serde_json::from_str::<MemoryWriteUndoneEvent>(content)
        .ok()
        .filter(valid_undone)
}

impl Client {
    /// Handle one memory write job frame of the turn and send what follows.
    ///
    /// # Errors
    /// Socket failures and cancellation.
    pub(in crate::client) async fn memory_write_job_event(
        &mut self,
        ws: &mut Socket,
        kind: &str,
        event: &Value,
        chat: &str,
        state: &mut MemoryJobState,
    ) -> Result<()> {
        let frames = {
            let mut runner = ClientRunner { client: self, ws };
            job_frames(&mut runner, kind, event, chat, now_ms() / 1000, state).await?
        };
        for (name, payload) in frames {
            send(ws, name, payload).await?;
        }
        Ok(())
    }

    /// Undo an assistant Memory write announced by `event`: delete a created
    /// Memory or restore the previous document of an updated one.
    ///
    /// # Errors
    /// See [`prepare_memory_undo`]; the save errors of `memory_documents`.
    pub async fn undo_assistant_memory_write(
        &mut self,
        event: &ContextEntryHistoryEvent,
    ) -> MemoryResult<MemoryUndoOutcome> {
        let ciphertext = self.settings_ciphertext().await?;
        let master = self.master_capability()?;
        let (outcome, prepared) =
            prepare_memory_undo(&master, ciphertext.as_deref(), event).await?;
        self.post_settings(&prepared).await?;
        Ok(outcome)
    }

    /// Assistant-written Memory notices of a chat (with Undo data), oldest first.
    ///
    /// # Errors
    /// Errors of opening the chat.
    pub async fn assistant_memory_writes(
        &mut self,
        chat_id: &str,
    ) -> Result<Vec<ContextEntryHistoryEvent>> {
        let chat = self.open_chat(chat_id).await?;
        Ok(chat
            .messages
            .iter()
            .filter(|m| m.role == "system")
            .filter_map(|m| parse_context_entry_event(&m.content))
            .filter(|event| event.undo.is_some())
            .collect())
    }
}

#[cfg(test)]
#[path = "memory_write_jobs_tests.rs"]
mod tests;
