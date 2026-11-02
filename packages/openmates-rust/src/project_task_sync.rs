//! Headless Project Task sync foundation. The caller binds an authenticated
//! socket to an explicit scope; wire frames themselves do not authenticate it.
//! Batches publish only at their final contiguous frame. No files, profiles,
//! timers, network connections or processes are owned by this module.
use crate::{Error, Result, crypto, work};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroize;

pub const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;
pub const MAX_BATCH_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_TASKS: usize = 4096;
const MAX_PARTS: u32 = 256;
const RECORDS_PER_FRAME: usize = 20;

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskSyncWorkspace {
    Personal,
    Team(String),
}

/// Account ID is the authenticated user ID, not an email or API credential.
/// A source belongs to exactly one Project and one Personal/Team context.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskSyncScope {
    api_url: String,
    account_id: String,
    workspace: TaskSyncWorkspace,
    project_id: String,
    source_id: String,
}
impl TaskSyncScope {
    pub fn new(
        api_url: &str,
        account_id: &str,
        workspace: TaskSyncWorkspace,
        project_id: &str,
        source_id: &str,
    ) -> Result<Self> {
        let parsed = url::Url::parse(api_url).map_err(|_| Error::Protocol)?;
        if !matches!(parsed.scheme(), "https" | "http")
            || parsed.host_str().is_none()
            || !parsed.username().is_empty()
            || parsed.password().is_some()
            || parsed.query().is_some()
            || parsed.fragment().is_some()
        {
            return Err(Error::Protocol);
        }
        for id in [account_id, project_id, source_id] {
            identifier(id)?;
        }
        if let TaskSyncWorkspace::Team(id) = &workspace {
            identifier(id)?;
        }
        Ok(Self {
            api_url: parsed.as_str().trim_end_matches('/').into(),
            account_id: account_id.into(),
            workspace,
            project_id: project_id.into(),
            source_id: source_id.into(),
        })
    }
    pub fn api_url(&self) -> &str {
        &self.api_url
    }
    pub fn account_id(&self) -> &str {
        &self.account_id
    }
    pub fn workspace(&self) -> &TaskSyncWorkspace {
        &self.workspace
    }
    pub fn project_id(&self) -> &str {
        &self.project_id
    }
    pub fn source_id(&self) -> &str {
        &self.source_id
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TaskSyncFrame {
    pub project_id: String,
    pub batch_id: String,
    pub part: u32,
    #[serde(rename = "final")]
    pub final_part: bool,
    pub reset: bool,
    pub cursor: String,
    pub tasks: Vec<Value>,
    pub removed_task_ids: Vec<String>,
}

pub enum TaskSyncEvent {
    Batch(TaskSyncFrame),
    AccessRevoked { project_id: Option<String> },
    Deferred { project_id: Option<String> },
}
impl TaskSyncEvent {
    /// Parse only an actual sync envelope; reject malformed/unbounded messages.
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_FRAME_BYTES {
            return Err(Error::Protocol);
        }
        #[derive(Deserialize)]
        struct Envelope {
            r#type: String,
            payload: Value,
        }
        let envelope: Envelope = serde_json::from_slice(bytes)?;
        match envelope.r#type.as_str() {
            "project_task_sync" => {
                let frame: TaskSyncFrame = serde_json::from_value(envelope.payload)?;
                frame.validate()?;
                Ok(Self::Batch(frame))
            }
            "project_task_sync_error" => {
                let project_id = match envelope.payload.get("project_id") {
                    None => None,
                    Some(Value::String(value)) => {
                        identifier(value)?;
                        Some(value.clone())
                    }
                    _ => return Err(Error::Protocol),
                };
                match envelope.payload["code"].as_str() {
                    Some("access_revoked") => Ok(Self::AccessRevoked { project_id }),
                    Some("sync_deferred") => Ok(Self::Deferred { project_id }),
                    _ => Err(Error::Protocol),
                }
            }
            _ => Err(Error::Protocol),
        }
    }
}
impl TaskSyncFrame {
    fn validate(&self) -> Result<()> {
        identifier(&self.project_id)?;
        identifier(&self.batch_id)?;
        cursor(&self.cursor)?;
        if self.part >= MAX_PARTS
            || self.tasks.len() > RECORDS_PER_FRAME
            || self.removed_task_ids.len() > MAX_TASKS
            || (self.part != 0 && !self.removed_task_ids.is_empty())
            || serde_json::to_vec(self)?.len() > MAX_FRAME_BYTES
        {
            return Err(Error::Protocol);
        }
        for id in &self.removed_task_ids {
            identifier(id)?;
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct SyncedTask {
    encrypted: Value,
    decrypted: Value,
}
impl SyncedTask {
    pub fn encrypted(&self) -> &Value {
        &self.encrypted
    }
    pub fn decrypted(&self) -> &Value {
        &self.decrypted
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum TaskSyncConnection {
    Reconnecting,
    Connected,
    Revoked,
}

pub struct TaskSyncSnapshot<'a> {
    pub scope: &'a TaskSyncScope,
    pub cursor: Option<&'a str>,
    pub tasks: &'a BTreeMap<String, SyncedTask>,
    pub connection: TaskSyncConnection,
}

/// Local durable-publication receipt. This is never a wire acknowledgement.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskSyncCommit {
    pub batch_id: String,
    pub cursor: String,
}
/// Ciphertext-only, scope-bound resume state. Restore authenticates each record.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskSyncCheckpoint {
    scope: TaskSyncScope,
    cursor: String,
    tasks: Vec<Value>,
}
struct Prepared {
    scope: TaskSyncScope,
    receipt: TaskSyncCommit,
    tasks: BTreeMap<String, SyncedTask>,
    valid: CancellationToken,
    expires_at: Option<u64>,
}
/// Only the reducer can construct this candidate. Reading never re-decrypts it.
/// Closing/revoking/discarding the owner invalidates all outstanding views.
#[derive(Clone)]
pub(crate) struct TaskSyncPublication(Arc<Prepared>);
impl TaskSyncPublication {
    pub(crate) fn snapshot(&self) -> Result<TaskSyncSnapshot<'_>> {
        if self.0.valid.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(TaskSyncSnapshot {
            scope: &self.0.scope,
            cursor: Some(&self.0.receipt.cursor),
            tasks: &self.0.tasks,
            connection: TaskSyncConnection::Connected,
        })
    }
    pub(crate) fn expires_at(&self) -> Option<u64> {
        self.0.expires_at
    }
    pub(crate) fn receipt(&self) -> &TaskSyncCommit {
        &self.0.receipt
    }
    pub(crate) fn checkpoint(&self) -> Result<TaskSyncCheckpoint> {
        self.snapshot()?;
        Ok(TaskSyncCheckpoint {
            scope: self.0.scope.clone(),
            cursor: self.0.receipt.cursor.clone(),
            tasks: self
                .0
                .tasks
                .values()
                .map(|task| task.encrypted.clone())
                .collect(),
        })
    }
}

struct Batch {
    id: String,
    next_part: u32,
    reset: bool,
    cursor: String,
    bytes: usize,
    tasks: BTreeMap<String, SyncedTask>,
    removed: BTreeSet<String>,
}
pub struct ProjectTaskSync {
    scope: TaskSyncScope,
    project_key: crypto::Key,
    cursor: Option<String>,
    tasks: BTreeMap<String, SyncedTask>,
    pending: Option<Batch>,
    prepared: Option<TaskSyncPublication>,
    retired_epochs: BTreeSet<String>,
    connection: TaskSyncConnection,
}
impl ProjectTaskSync {
    pub fn new(scope: TaskSyncScope, project_key: crypto::Key) -> Self {
        Self {
            scope,
            project_key,
            cursor: None,
            tasks: BTreeMap::new(),
            pending: None,
            prepared: None,
            retired_epochs: BTreeSet::new(),
            connection: TaskSyncConnection::Reconnecting,
        }
    }
    pub fn snapshot(&self) -> TaskSyncSnapshot<'_> {
        TaskSyncSnapshot {
            scope: &self.scope,
            cursor: self.cursor.as_deref(),
            tasks: &self.tasks,
            connection: self.connection,
        }
    }
    /// Disconnect loses the uncommitted batch, preserving the last committed cursor.
    pub fn reconnecting(&mut self) {
        self.discard_prepared();
        self.pending = None;
        if self.connection != TaskSyncConnection::Revoked {
            self.connection = TaskSyncConnection::Reconnecting;
        }
    }
    /// The authenticated socket owner supplies its scope on every event. No
    /// payload may select an API/account/Team/source different from that scope.
    /// `now_seconds` is explicit so wrapper expiration has no hidden clock.
    pub fn accept(
        &mut self,
        scope: &TaskSyncScope,
        event: TaskSyncEvent,
        now_seconds: u64,
    ) -> Result<bool> {
        let changed = self.stage(scope, event, now_seconds)?;
        if let Some(publication) = changed {
            if let Err(error) = self.commit(publication.receipt()) {
                self.reconnecting();
                return Err(error);
            }
            Ok(true)
        } else {
            Ok(false)
        }
    }
    pub(crate) fn stage(
        &mut self,
        scope: &TaskSyncScope,
        event: TaskSyncEvent,
        now: u64,
    ) -> Result<Option<TaskSyncPublication>> {
        let result = self.accept_inner(scope, event, now);
        if result.is_err() {
            self.reconnecting();
        }
        result.map(|ready| if ready { self.prepared.clone() } else { None })
    }
    pub(crate) fn commit(&mut self, receipt: &TaskSyncCommit) -> Result<()> {
        let candidate = self.prepared.as_ref().ok_or(Error::Conflict)?;
        candidate.snapshot()?;
        if candidate.receipt() != receipt {
            return Err(Error::Conflict);
        }
        if let Some(previous) = &self.cursor {
            let (old, _) = cursor(previous)?;
            let (next, _) = cursor(&receipt.cursor)?;
            if old != next {
                if self.retired_epochs.len() >= 128 {
                    return Err(Error::Protocol);
                }
                self.retired_epochs.insert(old.into());
            }
        }
        let publication = self.prepared.take().ok_or(Error::Conflict)?;
        self.tasks = publication.0.tasks.clone();
        self.cursor = Some(receipt.cursor.clone());
        self.connection = TaskSyncConnection::Connected;
        publication.0.valid.cancel();
        Ok(())
    }
    pub(crate) fn discard_prepared(&mut self) {
        if let Some(publication) = self.prepared.take() {
            publication.0.valid.cancel();
        }
    }
    pub(crate) fn restore(&mut self, checkpoint: TaskSyncCheckpoint, now: u64) -> Result<()> {
        if checkpoint.scope != self.scope
            || self.cursor.is_some()
            || !self.tasks.is_empty()
            || checkpoint.tasks.len() > MAX_TASKS
        {
            return Err(Error::Forbidden);
        }
        let count = checkpoint.tasks.len().div_ceil(RECORDS_PER_FRAME).max(1);
        for part in 0..count {
            let frame = TaskSyncFrame {
                project_id: self.scope.project_id.clone(),
                batch_id: "checkpoint-restore".into(),
                part: part as u32,
                final_part: part == count - 1,
                reset: true,
                cursor: checkpoint.cursor.clone(),
                tasks: checkpoint
                    .tasks
                    .iter()
                    .skip(part * RECORDS_PER_FRAME)
                    .take(RECORDS_PER_FRAME)
                    .cloned()
                    .collect(),
                removed_task_ids: vec![],
            };
            self.accept(&self.scope.clone(), TaskSyncEvent::Batch(frame), now)?;
        }
        self.reconnecting();
        Ok(())
    }
    pub(crate) fn key_matches(&self, key: &[u8; 32]) -> bool {
        // Fixed-length comparison; do not select a Personal fallback key.
        self.project_key
            .iter()
            .zip(key)
            .fold(0u8, |diff, (a, b)| diff | (a ^ b))
            == 0
    }
    fn accept_inner(
        &mut self,
        scope: &TaskSyncScope,
        event: TaskSyncEvent,
        now: u64,
    ) -> Result<bool> {
        if scope != &self.scope || self.connection == TaskSyncConnection::Revoked {
            return Err(Error::Forbidden);
        }
        let frame = match event {
            TaskSyncEvent::Batch(frame) => frame,
            TaskSyncEvent::AccessRevoked { project_id } => {
                self.check_project(project_id.as_deref())?;
                self.discard_prepared();
                self.pending = None;
                self.tasks.clear();
                self.cursor = None;
                self.retired_epochs.clear();
                self.project_key.zeroize();
                self.connection = TaskSyncConnection::Revoked;
                return Ok(false);
            }
            TaskSyncEvent::Deferred { project_id } => {
                self.check_project(project_id.as_deref())?;
                self.reconnecting();
                return Ok(false);
            }
        };
        frame.validate()?;
        self.check_project(Some(&frame.project_id))?;
        // Never queue another data batch behind an uncommitted publication.
        // Reconnect discards it and resumes from the last durable cursor.
        if self.prepared.is_some() {
            return Err(Error::Conflict);
        }
        let (epoch, sequence) = cursor(&frame.cursor)?;
        if self.retired_epochs.contains(epoch) {
            return Err(Error::Conflict);
        }
        if let Some(committed) = &self.cursor {
            let (old_epoch, old_sequence) = cursor(committed)?;
            // A reconnect subscription at the current DB clock receives one
            // empty delta as its readiness ACK. It may reconnect the snapshot,
            // but must never replace data or finish an in-flight newer batch.
            if epoch == old_epoch
                && sequence == old_sequence
                && self.pending.is_none()
                && frame.part == 0
                && frame.final_part
                && !frame.reset
                && frame.tasks.is_empty()
                && frame.removed_task_ids.is_empty()
            {
                self.prepared = Some(TaskSyncPublication(Arc::new(Prepared {
                    scope: self.scope.clone(),
                    receipt: TaskSyncCommit {
                        batch_id: frame.batch_id,
                        cursor: frame.cursor,
                    },
                    expires_at: task_expiry(&self.tasks, &self.scope),
                    tasks: self.tasks.clone(),
                    valid: CancellationToken::new(),
                })));
                return Ok(true);
            }
            if (epoch == old_epoch && sequence <= old_sequence)
                || (epoch != old_epoch && !frame.reset)
            {
                return Err(Error::Conflict);
            }
        } else if !frame.reset {
            return Err(Error::Protocol);
        }
        if frame.part == 0 {
            if self.pending.is_some() {
                return Err(Error::Protocol);
            }
            self.pending = Some(Batch {
                id: frame.batch_id.clone(),
                next_part: 0,
                reset: frame.reset,
                cursor: frame.cursor.clone(),
                bytes: 0,
                tasks: BTreeMap::new(),
                removed: BTreeSet::new(),
            });
        }
        let batch = self.pending.as_mut().ok_or(Error::Protocol)?;
        if batch.id != frame.batch_id
            || batch.next_part != frame.part
            || batch.cursor != frame.cursor
            || batch.reset != frame.reset
        {
            return Err(Error::Protocol);
        }
        batch.bytes = batch
            .bytes
            .checked_add(serde_json::to_vec(&frame)?.len())
            .ok_or(Error::Protocol)?;
        if batch.bytes > MAX_BATCH_BYTES {
            return Err(Error::Protocol);
        }
        for id in frame.removed_task_ids {
            if !batch.removed.insert(id.clone()) || batch.tasks.contains_key(&id) {
                return Err(Error::Protocol);
            }
        }
        for raw in frame.tasks {
            let id = task_id(&raw)?.to_owned();
            if batch.tasks.contains_key(&id) || batch.removed.contains(&id) {
                return Err(Error::Protocol);
            }
            let task = decode_task(&self.scope, &self.project_key, raw, now)?;
            batch.tasks.insert(id, task);
        }
        if batch.tasks.len() + batch.removed.len() > MAX_TASKS {
            return Err(Error::Protocol);
        }
        batch.next_part += 1;
        if !frame.final_part {
            return Ok(false);
        }
        let batch = self.pending.take().ok_or(Error::Protocol)?;
        let mut next = if batch.reset {
            BTreeMap::new()
        } else {
            self.tasks.clone()
        };
        for id in batch.removed {
            next.remove(&id);
        }
        next.extend(batch.tasks);
        if next.len() > MAX_TASKS
            || next
                .values()
                .try_fold(0usize, |total, task| -> Result<usize> {
                    let size = serde_json::to_vec(&task.encrypted)?.len()
                        + serde_json::to_vec(&task.decrypted)?.len();
                    let sum = total.checked_add(size).ok_or(Error::Protocol)?;
                    if sum > MAX_BATCH_BYTES {
                        return Err(Error::Protocol);
                    }
                    Ok(sum)
                })?
                > MAX_BATCH_BYTES
        {
            return Err(Error::Protocol);
        }
        self.prepared = Some(TaskSyncPublication(Arc::new(Prepared {
            scope: self.scope.clone(),
            receipt: TaskSyncCommit {
                batch_id: batch.id,
                cursor: batch.cursor,
            },
            expires_at: task_expiry(&next, &self.scope),
            tasks: next,
            valid: CancellationToken::new(),
        })));
        Ok(true)
    }
    fn check_project(&self, project: Option<&str>) -> Result<()> {
        if project.is_some_and(|value| value != self.scope.project_id) {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
}

impl Drop for ProjectTaskSync {
    fn drop(&mut self) {
        self.discard_prepared();
    }
}

fn task_expiry(tasks: &BTreeMap<String, SyncedTask>, scope: &TaskSyncScope) -> Option<u64> {
    let project_hash = hash(scope.project_id());
    tasks
        .values()
        .filter_map(|task| {
            task.encrypted["key_wrappers"]
                .as_array()
                .and_then(|rows| {
                    rows.iter().find(|row| {
                        row["key_type"] == "project" && row["hashed_project_id"] == project_hash
                    })
                })
                .and_then(|row| row["expires_at"].as_u64())
        })
        .min()
}

fn identifier(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        Err(Error::Protocol)
    } else {
        Ok(())
    }
}
fn cursor(value: &str) -> Result<(&str, u64)> {
    identifier(value)?;
    let (epoch, sequence) = value.split_once(':').ok_or(Error::Protocol)?;
    if epoch.is_empty()
        || sequence.is_empty()
        || !sequence.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(Error::Protocol);
    }
    Ok((epoch, sequence.parse().map_err(|_| Error::Protocol)?))
}
fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn task_id(raw: &Value) -> Result<&str> {
    let id = raw["task_id"].as_str().ok_or(Error::Protocol)?;
    identifier(id)?;
    Ok(id)
}
fn decode_task(
    scope: &TaskSyncScope,
    project_key: &[u8; 32],
    raw: Value,
    now: u64,
) -> Result<SyncedTask> {
    let id = task_id(&raw)?;
    match &scope.workspace {
        TaskSyncWorkspace::Personal => {
            if !raw["hashed_team_id"].is_null() || raw["hashed_user_id"] != hash(&scope.account_id)
            {
                return Err(Error::Forbidden);
            }
        }
        TaskSyncWorkspace::Team(team) => {
            if raw["hashed_team_id"] != hash(team) {
                return Err(Error::Forbidden);
            }
        }
    }
    let wrappers = raw["key_wrappers"].as_array().ok_or(Error::Forbidden)?;
    let selected = wrappers
        .iter()
        .filter(|wrapper| {
            wrapper["key_type"] == "project"
                && wrapper["hashed_project_id"] == hash(&scope.project_id)
        })
        .collect::<Vec<_>>();
    if selected.len() != 1 {
        return Err(Error::Forbidden);
    }
    let wrapper = selected[0];
    if wrapper["hashed_task_id"] != hash(id)
        || ["hashed_team_id", "hashed_plan_id", "hashed_chat_id"]
            .iter()
            .any(|field| !wrapper[*field].is_null())
        || (!wrapper["expires_at"].is_null()
            && wrapper["expires_at"]
                .as_u64()
                .is_none_or(|expires| expires <= now))
        || (scope.workspace == TaskSyncWorkspace::Personal
            && wrapper["hashed_user_id"] != hash(&scope.account_id))
    {
        return Err(Error::Forbidden);
    }
    let encrypted = wrapper["encrypted_task_key"]
        .as_str()
        .ok_or(Error::Protocol)?;
    let bytes = crypto::decrypt_bytes(encrypted, project_key)?;
    let key = work::key_bytes(&bytes)?;
    if raw
        .get("dependencies")
        .is_some_and(|value| !value.is_array())
    {
        return Err(Error::Protocol);
    }
    if let Some(activity) = raw.get("latest_activity").filter(|value| !value.is_null())
        && (!activity.is_object()
            || activity["task_id"]
                .as_str()
                .is_some_and(|value| value != id)
            || activity["hashed_task_id"]
                .as_str()
                .is_some_and(|value| value != hash(id)))
    {
        return Err(Error::Forbidden);
    }
    let mut decrypted = work::decode_task_with_key(raw.clone(), key)?;
    decrypted["dependencies"] = raw
        .get("dependencies")
        .cloned()
        .unwrap_or_else(|| Value::Array(vec![]));
    Ok(SyncedTask {
        encrypted: raw,
        decrypted,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn scope() -> TaskSyncScope {
        TaskSyncScope::new(
            "https://example.invalid",
            "user",
            TaskSyncWorkspace::Personal,
            "project",
            "source",
        )
        .unwrap()
    }
    fn task(id: &str) -> Value {
        let task_key = [7; 32];
        json!({
            "task_id":id,"version":1,"status":"todo", "hashed_user_id":hash("user"),
            "encrypted_title":crypto::encrypt_combined(&format!("Title {id} {}", "long title ".repeat(30)), &task_key).unwrap(),
            "encrypted_description":crypto::encrypt_combined("Private description", &task_key).unwrap(),
            "key_wrappers":[{"key_type":"project","hashed_project_id":hash("project"),"hashed_task_id":hash(id),"hashed_user_id":hash("user"),"encrypted_task_key":crypto::encrypt_bytes(&task_key, &[3;32]).unwrap()}],
            "dependencies":[{"dependency_task_id":"another-task"}]
        })
    }
    fn frame(sequence: u64, records: Vec<Value>) -> TaskSyncFrame {
        TaskSyncFrame {
            project_id: "project".into(),
            batch_id: format!("batch-{sequence}"),
            part: 0,
            final_part: true,
            reset: true,
            cursor: format!("epoch:{sequence}"),
            tasks: records,
            removed_task_ids: vec![],
        }
    }
    fn apply(sync: &mut ProjectTaskSync, frame: TaskSyncFrame) -> Result<bool> {
        let bytes =
            serde_json::to_vec(&json!({"type":"project_task_sync","payload":frame})).unwrap();
        sync.accept(&scope(), TaskSyncEvent::parse(&bytes)?, 1000)
    }
    fn seeded() -> ProjectTaskSync {
        let mut sync = ProjectTaskSync::new(scope(), zeroize::Zeroizing::new([3; 32]));
        assert!(apply(&mut sync, frame(1, vec![task("original")])).unwrap());
        sync
    }
    fn unchanged(sync: &ProjectTaskSync) {
        assert_eq!(sync.snapshot().cursor, Some("epoch:1"));
        assert_eq!(
            sync.snapshot().tasks.keys().collect::<Vec<_>>(),
            vec!["original"]
        );
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn backend_twenty_record_frames_commit_all_45_only_after_final() {
        let mut sync = ProjectTaskSync::new(scope(), zeroize::Zeroizing::new([3; 32]));
        for part in 0..3 {
            let mut input = frame(
                1,
                (part * 20..((part + 1) * 20).min(45))
                    .map(|id| task(&id.to_string()))
                    .collect(),
            );
            input.part = part;
            input.final_part = part == 2;
            assert_eq!(apply(&mut sync, input).unwrap(), part == 2);
            assert_eq!(sync.snapshot().tasks.len(), if part == 2 { 45 } else { 0 });
            assert_eq!(
                sync.snapshot().cursor,
                if part == 2 { Some("epoch:1") } else { None }
            );
        }
        let stored = &sync.snapshot().tasks["0"];
        assert_eq!(
            stored.decrypted()["title"],
            format!("Title 0 {}", "long title ".repeat(30))
        );
        assert_eq!(stored.decrypted()["description"], "Private description");
        assert_eq!(
            stored.decrypted()["dependencies"][0]["dependency_task_id"],
            "another-task"
        );
        assert!(stored.encrypted()["encrypted_title"].as_str().is_some());
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn disconnect_drops_partial_delta_and_replays_from_committed_cursor() {
        let mut sync = seeded();
        let mut input = frame(2, vec![task("new")]);
        input.reset = false;
        input.final_part = false;
        assert!(!apply(&mut sync, input.clone()).unwrap());
        unchanged(&sync);
        sync.reconnecting();
        input.part = 1;
        input.final_part = true;
        assert!(apply(&mut sync, input).is_err());
        unchanged(&sync);
        let mut replay = frame(2, vec![task("new")]);
        replay.reset = false;
        replay.removed_task_ids = vec!["original".into()];
        assert!(apply(&mut sync, replay).unwrap());
        assert_eq!(
            sync.snapshot().tasks.keys().collect::<Vec<_>>(),
            vec!["new"]
        );
        assert_eq!(sync.snapshot().cursor, Some("epoch:2"));
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn stale_cursor_or_epoch_without_reset_never_replaces_snapshot() {
        for mut input in [frame(0, vec![]), frame(1, vec![]), frame(2, vec![])] {
            let mut sync = seeded();
            if input.cursor == "epoch:2" {
                input.cursor = "other:2".into();
                input.reset = false;
            }
            assert!(apply(&mut sync, input).is_err());
            unchanged(&sync);
        }
        let mut sync = seeded();
        let mut input = frame(0, vec![task("reset")]);
        input.cursor = "new-epoch:0".into();
        assert!(apply(&mut sync, input).unwrap());
        assert_eq!(sync.snapshot().cursor, Some("new-epoch:0"));
        assert_eq!(sync.snapshot().tasks.len(), 1);
        assert!(apply(&mut sync, frame(99, vec![task("old-epoch-replay")])).is_err());
        assert_eq!(sync.snapshot().cursor, Some("new-epoch:0"));
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn mixed_batch_identity_gap_repeat_and_changed_reset_fail_atomically() {
        for mutation in 0..7 {
            let mut sync = seeded();
            let mut first = frame(2, vec![task("new")]);
            first.final_part = false;
            assert!(!apply(&mut sync, first.clone()).unwrap());
            let mut next = first;
            next.part = 1;
            next.final_part = true;
            next.tasks = vec![];
            match mutation {
                0 => next.part = 2,
                1 => next.part = 0,
                2 => next.batch_id = "other".into(),
                3 => next.cursor = "epoch:3".into(),
                4 => next.reset = false,
                5 => next.project_id = "another-project".into(),
                _ => next.tasks = vec![task("new")],
            }
            assert!(apply(&mut sync, next).is_err());
            unchanged(&sync);
            assert!(sync.pending.is_none());
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn socket_scope_never_crosses_api_account_team_project_or_source() {
        for mutation in 0..5 {
            let mut sync = seeded();
            let mut wrong = scope();
            match mutation {
                0 => wrong.api_url = "https://other.invalid".into(),
                1 => wrong.account_id = "other".into(),
                2 => wrong.workspace = TaskSyncWorkspace::Team("team".into()),
                3 => wrong.project_id = "other".into(),
                _ => wrong.source_id = "other".into(),
            }
            assert!(matches!(
                sync.accept(&wrong, TaskSyncEvent::Batch(frame(2, vec![])), 1000),
                Err(Error::Forbidden)
            ));
            unchanged(&sync);
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn revocation_clears_committed_and_partial_content_and_cannot_resume() {
        let mut sync = seeded();
        let mut first = frame(2, vec![task("new")]);
        first.final_part = false;
        apply(&mut sync, first).unwrap();
        let event = TaskSyncEvent::parse(
            br#"{"type":"project_task_sync_error","payload":{"code":"access_revoked"}}"#,
        )
        .unwrap();
        assert!(!sync.accept(&scope(), event, 1000).unwrap());
        assert!(sync.snapshot().tasks.is_empty());
        assert!(sync.snapshot().cursor.is_none());
        assert!(sync.pending.is_none());
        assert!(sync.project_key.iter().all(|byte| *byte == 0));
        sync.reconnecting();
        assert!(matches!(
            sync.snapshot().connection,
            TaskSyncConnection::Revoked
        ));
        assert!(apply(&mut sync, frame(3, vec![task("forbidden")])).is_err());
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn decryption_or_wrapper_mutations_abort_entire_final_frame() {
        for mutation in 0..9 {
            let mut sync = seeded();
            let mut bad = task("bad");
            match mutation {
                0 => bad["key_wrappers"][0]["hashed_project_id"] = json!(hash("other")),
                1 => bad["key_wrappers"][0]["hashed_task_id"] = json!(hash("other")),
                2 => bad["key_wrappers"][0]["hashed_user_id"] = json!(hash("other")),
                3 => bad["key_wrappers"][0]["expires_at"] = json!(999),
                4 => bad["hashed_user_id"] = json!(hash("other")),
                5 => bad["hashed_team_id"] = json!(hash("team")),
                6 => {
                    bad["encrypted_title"] =
                        json!(crypto::encrypt_combined("tampered", &[8; 32]).unwrap())
                }
                7 => {
                    let duplicate = bad["key_wrappers"][0].clone();
                    bad["key_wrappers"].as_array_mut().unwrap().push(duplicate);
                }
                _ => bad["latest_activity"] = json!({"task_id":"other","kind":"comment"}),
            }
            assert!(apply(&mut sync, frame(2, vec![task("good-before-bad"), bad])).is_err());
            unchanged(&sync);
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn team_records_require_exact_team_even_with_valid_project_key() {
        let mut team_scope = scope();
        team_scope.workspace = TaskSyncWorkspace::Team("team".into());
        let mut sync = ProjectTaskSync::new(team_scope.clone(), zeroize::Zeroizing::new([3; 32]));
        for team in [None, Some("other")] {
            let mut raw = task("team-task");
            if let Some(team) = team {
                raw["hashed_team_id"] = json!(hash(team));
            }
            assert!(
                sync.accept(&team_scope, TaskSyncEvent::Batch(frame(1, vec![raw])), 1000)
                    .is_err()
            );
        }
        let mut raw = task("team-task");
        raw["hashed_team_id"] = json!(hash("team"));
        raw["hashed_user_id"] = json!(hash("another-member"));
        assert!(
            sync.accept(&team_scope, TaskSyncEvent::Batch(frame(1, vec![raw])), 1000)
                .unwrap()
        );
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn frame_and_cursor_limits_reject_before_commit() {
        for mutation in 0..8 {
            let mut sync = seeded();
            let mut input = frame(2, vec![]);
            match mutation {
                0 => input.tasks = (0..21).map(|id| task(&id.to_string())).collect(),
                1 => input.part = MAX_PARTS,
                2 => input.cursor = "epoch:not-a-number".into(),
                3 => input.cursor = "epoch:18446744073709551616".into(),
                4 => input.cursor = "epoch:1:2".into(),
                5 => input.removed_task_ids = vec!["id".into(); MAX_TASKS + 1],
                6 => input.removed_task_ids = vec!["same".into(), "same".into()],
                _ => {
                    input.tasks = vec![task("same")];
                    input.removed_task_ids = vec!["same".into()];
                }
            }
            assert!(apply(&mut sync, input).is_err());
            unchanged(&sync);
        }
        assert!(TaskSyncEvent::parse(&vec![b' '; MAX_FRAME_BYTES + 1]).is_err());
        assert!(
            TaskSyncEvent::parse(
                br#"{"type":"project_task_sync_error","payload":{"code":"unknown"}}"#
            )
            .is_err()
        );
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn total_batch_bytes_are_bounded_across_individually_valid_frames() {
        let mut sync = seeded();
        for part in 0..6 {
            let mut raw = task(&part.to_string());
            raw["opaque_padding"] = json!("x".repeat(3 * 1024 * 1024));
            let mut input = frame(2, vec![raw]);
            input.part = part;
            input.final_part = part == 5;
            let result = apply(&mut sync, input);
            if part < 5 {
                assert!(!result.unwrap());
            } else {
                assert!(result.is_err());
            }
            unchanged(&sync);
        }
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn latest_activity_is_decrypted_with_task_and_entry_aad() {
        use base64::{Engine, engine::general_purpose::STANDARD};
        let nonce = [9; 12];
        let mut bytes = nonce.to_vec();
        bytes.extend(
            crypto::encrypt_aead(
                b"Private activity",
                &[7; 32],
                &nonce,
                b"task_activity_comment:activity-task:entry:v1",
            )
            .unwrap(),
        );
        let mut raw = task("activity-task");
        raw["latest_activity"] = json!({"task_id":"activity-task","entry_id":"entry","kind":"comment","encrypted_message":STANDARD.encode(bytes)});
        let mut sync = seeded();
        assert!(apply(&mut sync, frame(2, vec![raw.clone()])).unwrap());
        assert_eq!(
            sync.snapshot().tasks["activity-task"].decrypted()["latest_activity"]["message"],
            "Private activity"
        );
        raw["latest_activity"]["entry_id"] = json!("different-entry");
        let mut sync = seeded();
        assert!(apply(&mut sync, frame(2, vec![raw])).is_err());
        unchanged(&sync);
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn malformed_typed_frames_and_foreign_revocations_fail_closed() {
        let original = serde_json::to_value(frame(2, vec![])).unwrap();
        for (field, value) in [
            ("part", json!(-1)),
            ("final", json!("true")),
            ("reset", json!(1)),
            ("tasks", json!({})),
            ("project_id", json!(null)),
        ] {
            let mut payload = original.clone();
            payload[field] = value;
            let bytes =
                serde_json::to_vec(&json!({"type":"project_task_sync","payload":payload})).unwrap();
            assert!(TaskSyncEvent::parse(&bytes).is_err());
        }
        let mut sync = seeded();
        assert!(
            sync.accept(
                &scope(),
                TaskSyncEvent::AccessRevoked {
                    project_id: Some("another-project".into())
                },
                1000
            )
            .is_err()
        );
        unchanged(&sync);
        let mut pending = frame(2, vec![task("partial")]);
        pending.final_part = false;
        apply(&mut sync, pending).unwrap();
        let deferred = TaskSyncEvent::parse(br#"{"type":"project_task_sync_error","payload":{"project_id":"project","code":"sync_deferred"}}"#).unwrap();
        sync.accept(&scope(), deferred, 1000).unwrap();
        unchanged(&sync);
        assert!(sync.pending.is_none());
    }

    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn unchanged_cursor_reconnect_ack_can_only_be_an_empty_delta() {
        let mut sync = seeded();
        sync.reconnecting();
        let mut ack = frame(1, vec![]);
        ack.reset = false;
        assert!(apply(&mut sync, ack.clone()).unwrap());
        unchanged(&sync);
        assert!(matches!(
            sync.snapshot().connection,
            TaskSyncConnection::Connected
        ));
        ack.tasks = vec![task("replayed-content")];
        assert!(apply(&mut sync, ack).is_err());
        unchanged(&sync);
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn staged_candidate_never_advances_durable_cursor_before_exact_commit() {
        let mut sync = seeded();
        let ready = sync
            .stage(
                &scope(),
                TaskSyncEvent::Batch(frame(2, vec![task("next")])),
                1000,
            )
            .unwrap()
            .unwrap();
        unchanged(&sync);
        assert_eq!(ready.snapshot().unwrap().cursor, Some("epoch:2"));
        let mut wrong = ready.receipt().clone();
        wrong.batch_id = "foreign-batch".into();
        assert!(matches!(sync.commit(&wrong), Err(Error::Conflict)));
        unchanged(&sync);
        sync.commit(ready.receipt()).unwrap();
        assert_eq!(sync.snapshot().cursor, Some("epoch:2"));
        assert!(ready.snapshot().is_err());
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn reconnect_and_revoke_invalidate_outstanding_plaintext_without_redecrypting() {
        let mut sync = seeded();
        let ready = sync
            .stage(
                &scope(),
                TaskSyncEvent::Batch(frame(2, vec![task("next")])),
                1000,
            )
            .unwrap()
            .unwrap();
        let receipt = ready.receipt().clone();
        sync.reconnecting();
        assert!(ready.snapshot().is_err());
        assert!(matches!(sync.commit(&receipt), Err(Error::Conflict)));
        unchanged(&sync);
        let ready = sync
            .stage(
                &scope(),
                TaskSyncEvent::Batch(frame(2, vec![task("next")])),
                1000,
            )
            .unwrap()
            .unwrap();
        sync.stage(
            &scope(),
            TaskSyncEvent::AccessRevoked {
                project_id: Some("project".into()),
            },
            1000,
        )
        .unwrap();
        assert!(ready.snapshot().is_err());
        assert!(sync.snapshot().tasks.is_empty());
        assert!(sync.snapshot().connection == TaskSyncConnection::Revoked);
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn readiness_same_cursor_requires_current_batch_receipt_and_bounded_backpressure() {
        let mut sync = seeded();
        sync.reconnecting();
        let mut ack = frame(1, vec![]);
        ack.reset = false;
        ack.batch_id = "new-ready".into();
        let ready = sync
            .stage(&scope(), TaskSyncEvent::Batch(ack), 1000)
            .unwrap()
            .unwrap();
        let stale = TaskSyncCommit {
            cursor: "epoch:1".into(),
            batch_id: "batch-1".into(),
        };
        assert!(matches!(sync.commit(&stale), Err(Error::Conflict)));
        assert!(sync.snapshot().connection == TaskSyncConnection::Reconnecting);
        assert!(matches!(
            sync.stage(&scope(), TaskSyncEvent::Batch(frame(2, vec![])), 1000),
            Err(Error::Conflict)
        ));
        assert!(ready.snapshot().is_err());
        unchanged(&sync);
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn ciphertext_checkpoint_restores_exact_scope_and_reauthenticates_records() {
        let mut sync = seeded();
        let ready = sync
            .stage(
                &scope(),
                TaskSyncEvent::Batch(frame(2, vec![task("next")])),
                1000,
            )
            .unwrap()
            .unwrap();
        let checkpoint = ready.checkpoint().unwrap();
        let bytes = serde_json::to_vec(&checkpoint).unwrap();
        assert!(
            !String::from_utf8(bytes.clone())
                .unwrap()
                .contains("Private description")
        );
        let mut restored = ProjectTaskSync::new(scope(), zeroize::Zeroizing::new([3; 32]));
        restored.restore(checkpoint, 1000).unwrap();
        assert_eq!(restored.snapshot().cursor, Some("epoch:2"));
        assert!(restored.snapshot().connection == TaskSyncConnection::Reconnecting);
        let mut foreign: TaskSyncCheckpoint = serde_json::from_slice(&bytes).unwrap();
        foreign.scope.source_id = "other-source".into();
        let mut target = ProjectTaskSync::new(scope(), zeroize::Zeroizing::new([3; 32]));
        assert!(matches!(
            target.restore(foreign, 1000),
            Err(Error::Forbidden)
        ));
        let mut corrupt: TaskSyncCheckpoint = serde_json::from_slice(&bytes).unwrap();
        corrupt.tasks[0]["encrypted_title"] = json!("tampered");
        assert!(target.restore(corrupt, 1000).is_err());
        assert!(target.snapshot().tasks.is_empty());
    }
}
