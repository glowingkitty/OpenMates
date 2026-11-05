//! Application-owned encrypted journal. SDK deliveries remain headless and
//! explicit; this layer owns durable intent, uncertain dispatch and receipts.
use crate::{
    cli::Invocation,
    crypto::Key,
    error::{Error, Result},
    runtime_store::RuntimeStore,
};
use hmac::{Hmac, Mac};
use openmates_sdk::work::{TaskCaller, TaskDelivery};
use rand::Rng;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::Sha256;
use std::collections::BTreeMap;
use zeroize::Zeroizing;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
enum Phase {
    Prepared,
    Uncertain,
    Acknowledged,
}
/// Captured from the caller actually supplied to the SDK, never inferred from
/// a later foreground process or from an unverified legacy record.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum OriginalCaller {
    Human,
    Codex {
        thread_id: String,
        as_assignee: bool,
    },
}
impl OriginalCaller {
    fn capture(caller: &TaskCaller) -> Result<Self> {
        match caller.codex_thread_id.as_deref() {
            Some(thread_id)
                if thread_id.len() == 36 && uuid::Uuid::parse_str(thread_id).is_ok() =>
            {
                Ok(Self::Codex {
                    thread_id: thread_id.into(),
                    as_assignee: caller.as_assignee,
                })
            }
            Some(_) => Err(Error::Invalid(
                "Task delivery requires its original valid Codex thread ID.",
            )),
            None if !caller.as_assignee => Ok(Self::Human),
            None => Err(Error::Forbidden),
        }
    }
    fn task_caller(&self) -> Result<TaskCaller> {
        let caller = match self {
            Self::Human => TaskCaller::default(),
            Self::Codex {
                thread_id,
                as_assignee,
            } => TaskCaller {
                codex_thread_id: Some(thread_id.clone()),
                as_assignee: *as_assignee,
            },
        };
        Self::capture(&caller)?;
        Ok(caller)
    }
}
/// Private journal policy only; this does not extend the SDK wire DTO.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplayAdmission {
    version: u8,
    caller: OriginalCaller,
    sequence: u64,
    queued_at_ms: u64,
}
impl ReplayAdmission {
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    pub fn queued_at_ms(&self) -> u64 {
        self.queued_at_ms
    }
    pub fn task_caller(&self) -> Result<TaskCaller> {
        if self.version != 1 || self.sequence == 0 || self.queued_at_ms == 0 {
            return Err(replay_quarantined());
        }
        self.caller.task_caller()
    }
}
fn replay_quarantined() -> Error {
    Error::Unavailable {
        code: "task_delivery_replay_quarantined",
        reason: "ORIGINAL_CALLER_OR_FIFO_ORDER_UNVERIFIED",
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoredDelivery {
    pub delivery: TaskDelivery,
    pub intent: String,
    context: String,
    phase: Phase,
    result: Option<Value>,
    #[serde(default)]
    retry: RetryState,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    replay: Option<ReplayAdmission>,
}
impl StoredDelivery {
    pub fn replay_admission(&self) -> Result<&ReplayAdmission> {
        let admission = self.replay.as_ref().ok_or_else(replay_quarantined)?;
        let caller = admission.task_caller()?;
        if self.delivery.actor_assignee != caller.as_assignee
            || self.delivery.creator && caller.codex_thread_id.is_none()
        {
            return Err(replay_quarantined());
        }
        Ok(admission)
    }
}
/// Ordered rows still require atomic begin_replay admission. Any quarantined
/// pending row blocks automatic replay for its selected context; it is never discarded.
pub struct ReplayQueue {
    pub ordered: Vec<StoredDelivery>,
    pub quarantined: Vec<StoredDelivery>,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RetryState {
    failures: u32,
    first_failure_at: Option<u64>,
    retry_at: u64,
    notified: bool,
}
#[derive(Clone, Serialize, Deserialize)]
pub struct Retry {
    pub retry_at: u64,
    pub persistent: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct State {
    version: u8,
    deliveries: BTreeMap<String, StoredDelivery>,
    #[serde(default)]
    retry: RetryState,
    #[serde(default)]
    last_sequence: u64,
}
impl Default for State {
    fn default() -> Self {
        Self {
            version: 1,
            deliveries: BTreeMap::new(),
            retry: RetryState::default(),
            last_sequence: 0,
        }
    }
}
impl State {
    fn load(value: Option<Value>) -> Result<Self> {
        let state = match value {
            Some(value) => serde_json::from_value(value)?,
            None => Self::default(),
        };
        if state.version != 1 || state.deliveries.len() > 4096 {
            return Err(Error::Protocol);
        }
        Ok(state)
    }
    fn row(&self, id: &str, intent: &str, context: &str) -> Result<&StoredDelivery> {
        let row = self
            .deliveries
            .get(id)
            .ok_or(Error::Invalid("Task delivery was not prepared."))?;
        if row.context != context {
            return Err(Error::Forbidden);
        }
        if row.intent != intent {
            return Err(Error::Invalid(
                "This delivery ID already belongs to a different command; its original payload was preserved.",
            ));
        }
        Ok(row)
    }
    fn replay_queue(&self, context: &str) -> ReplayQueue {
        let mut counts = BTreeMap::<u64, usize>::new();
        for row in self
            .deliveries
            .values()
            .filter(|row| row.context == context)
        {
            if let Ok(admission) = row.replay_admission() {
                *counts.entry(admission.sequence).or_default() += 1;
            }
        }
        let (mut ordered, mut quarantined) = (vec![], vec![]);
        for (id, row) in self
            .deliveries
            .iter()
            .filter(|(_, row)| row.context == context && row.phase != Phase::Acknowledged)
        {
            if id == &row.delivery.delivery_id
                && row
                    .replay_admission()
                    .is_ok_and(|a| counts.get(&a.sequence) == Some(&1))
            {
                ordered.push(row.clone());
            } else {
                quarantined.push(row.clone());
            }
        }
        ordered.sort_by_key(|row| row.replay.as_ref().map(|a| a.sequence));
        // These IDs are listing identities only, never an execution tie breaker.
        quarantined.sort_by(|a, b| a.delivery.delivery_id.cmp(&b.delivery.delivery_id));
        ReplayQueue {
            ordered,
            quarantined,
        }
    }
    fn replay_head(&self, context: &str) -> Result<Option<&StoredDelivery>> {
        let mut sequences = std::collections::BTreeSet::new();
        let mut head: Option<(&StoredDelivery, u64)> = None;
        for (id, row) in self
            .deliveries
            .iter()
            .filter(|(_, row)| row.context == context)
        {
            if id != &row.delivery.delivery_id {
                return Err(replay_quarantined());
            }
            if let Ok(admission) = row.replay_admission() {
                if !sequences.insert(admission.sequence) {
                    return Err(replay_quarantined());
                }
                if row.phase != Phase::Acknowledged
                    && head.is_none_or(|(_, sequence)| admission.sequence < sequence)
                {
                    head = Some((row, admission.sequence));
                }
            } else if row.phase != Phase::Acknowledged {
                return Err(replay_quarantined());
            }
        }
        Ok(head.map(|(row, _)| row))
    }
}
pub struct Dispatch {
    pub delivery: TaskDelivery,
    pub uncertain: bool,
    pub completed: Option<Value>,
    pub deferred: Option<Retry>,
    pub replay: Option<ReplayAdmission>,
}
pub struct Journal {
    store: RuntimeStore,
    owner: String,
    context: String,
    storage_context: String,
    key: Key,
    generation: u64,
}
impl Journal {
    pub fn new(store: RuntimeStore, owner: String, context: String, key: Key) -> Self {
        let generation = store.generation();
        // One account/API cooldown covers all Teams while every row still
        // carries its exact selected context and SDK-authenticated Team scope.
        let storage_context = serde_json::from_str::<Value>(&context)
            .ok()
            .and_then(|v| {
                v.as_array()
                    .and_then(|v| v.first())
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            })
            .unwrap_or_else(|| context.clone());
        Self {
            store,
            owner,
            context,
            storage_context,
            key,
            generation,
        }
    }
    /// Hash logical inputs with the account key. Neither a title nor an API key
    /// appears as a durable plaintext fingerprint or low-entropy plain hash.
    pub fn intent(&self, invocation: &Invocation) -> Result<String> {
        let presentation = [
            "json",
            "api-url",
            "api-key",
            "profile",
            "state-dir",
            "encrypted-vault",
            "delivery-id",
        ];
        let flags = invocation
            .flags
            .iter()
            .filter(|(key, _)| !presentation.contains(&key.as_str()))
            .collect::<BTreeMap<_, _>>();
        let raw = Zeroizing::new(serde_json::to_vec(&(
            &invocation.path,
            &invocation.positionals,
            flags,
        ))?);
        let mut mac =
            Hmac::<Sha256>::new_from_slice(self.key.as_ref()).map_err(|_| Error::Crypto)?;
        mac.update(b"openmates-task-delivery-intent-v1\0");
        mac.update(&raw);
        Ok(mac
            .finalize()
            .into_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect())
    }
    async fn access<T: Send + 'static>(
        &self,
        update: impl FnOnce(State) -> Result<(Option<State>, T)> + Send + 'static,
    ) -> Result<T> {
        self.store
            .update_private_record(
                self.owner.clone(),
                self.storage_context.clone(),
                "task-deliveries-v1".into(),
                self.key.clone(),
                self.generation,
                move |value| {
                    let (next, result) = update(State::load(value)?)?;
                    Ok((next.map(serde_json::to_value).transpose()?, result))
                },
            )
            .await
    }
    pub async fn lookup(&self, id: &str, intent: &str) -> Result<Option<StoredDelivery>> {
        let id = id.to_owned();
        let intent = intent.to_owned();
        let context = self.context.clone();
        self.access(move |state| {
            let row = if state.deliveries.contains_key(&id) {
                Some(state.row(&id, &intent, &context)?.clone())
            } else {
                None
            };
            Ok((None, row))
        })
        .await
    }
    /// Compatibility/manual preparation. Missing actor/order evidence remains
    /// quarantined from automatic replay, including after an explicit retry.
    pub async fn insert(&self, delivery: TaskDelivery, intent: String) -> Result<StoredDelivery> {
        self.insert_inner(delivery, intent, None).await
    }
    pub async fn insert_for_caller(
        &self,
        delivery: TaskDelivery,
        intent: String,
        caller: &TaskCaller,
    ) -> Result<StoredDelivery> {
        let caller = OriginalCaller::capture(caller)?;
        let original = caller.task_caller()?;
        if delivery.actor_assignee != original.as_assignee
            || delivery.creator && original.codex_thread_id.is_none()
        {
            return Err(Error::Forbidden);
        }
        self.insert_inner(delivery, intent, Some(caller)).await
    }
    async fn insert_inner(
        &self,
        delivery: TaskDelivery,
        intent: String,
        caller: Option<OriginalCaller>,
    ) -> Result<StoredDelivery> {
        let context = self.context.clone();
        self.access(move |mut state| {
            let id = delivery.delivery_id.clone();
            if state.deliveries.contains_key(&id) {
                let existing = state.row(&id, &intent, &context)?.clone();
                if let (Some(existing), Some(caller)) = (&existing.replay, &caller)
                    && &existing.caller != caller
                {
                    return Err(Error::Forbidden);
                }
                return Ok((None, existing));
            }
            if state.deliveries.len() >= 4096 {
                return Err(Error::Invalid(
                    "Task delivery journal is full; pending work was preserved.",
                ));
            }
            let replay = if let Some(caller) = caller {
                // Counter and payload commit in the same encrypted record and
                // RuntimeStore ordering lock; wall-clock rollback cannot reorder.
                let maximum = state
                    .deliveries
                    .values()
                    .filter_map(|row| row.replay.as_ref().map(|a| a.sequence))
                    .max()
                    .unwrap_or(0);
                let sequence =
                    state
                        .last_sequence
                        .max(maximum)
                        .checked_add(1)
                        .ok_or(Error::Invalid(
                            "Task delivery sequence is exhausted; queued work was preserved.",
                        ))?;
                state.last_sequence = sequence;
                Some(ReplayAdmission {
                    version: 1,
                    caller,
                    sequence,
                    queued_at_ms: now_ms(),
                })
            } else {
                None
            };
            let row = StoredDelivery {
                delivery,
                intent,
                context,
                phase: Phase::Prepared,
                result: None,
                retry: RetryState::default(),
                replay,
            };
            state.deliveries.insert(id, row.clone());
            Ok((Some(state), row))
        })
        .await
    }
    /// Commit uncertainty BEFORE releasing a payload to transport. If this
    /// future is cancelled, the RuntimeStore retains the write/ordering lock.
    pub async fn begin(&self, id: &str, intent: &str) -> Result<Dispatch> {
        self.begin_inner(id, intent, false).await
    }
    /// Admit only the first verified FIFO row. The returned sealed caller must
    /// configure Tasks::with_caller; SDK scope/ownership checks still apply.
    pub async fn begin_replay(&self, id: &str, intent: &str) -> Result<Dispatch> {
        self.begin_inner(id, intent, true).await
    }
    async fn begin_inner(&self, id: &str, intent: &str, automatic: bool) -> Result<Dispatch> {
        let id = id.to_owned();
        let intent = intent.to_owned();
        let context = self.context.clone();
        self.access(move |mut state| {
            let row = state.row(&id, &intent, &context)?.clone();
            if automatic {
                row.replay_admission()?;
                if row.phase != Phase::Acknowledged {
                    let first = state.replay_head(&context)?.ok_or(Error::Protocol)?;
                    if first.delivery.delivery_id != id {
                        return Err(Error::Conflict);
                    }
                }
            }
            if row.phase == Phase::Acknowledged {
                return Ok((
                    None,
                    Dispatch {
                        delivery: row.delivery,
                        uncertain: true,
                        completed: row.result,
                        deferred: None,
                        replay: row.replay,
                    },
                ));
            }
            if state.retry.retry_at > now_ms() {
                return Ok((
                    None,
                    Dispatch {
                        delivery: row.delivery,
                        uncertain: row.phase == Phase::Uncertain,
                        completed: None,
                        deferred: Some(Retry {
                            retry_at: state.retry.retry_at,
                            persistent: false,
                        }),
                        replay: row.replay,
                    },
                ));
            }
            let dispatch = Dispatch {
                delivery: row.delivery.clone(),
                uncertain: row.phase == Phase::Uncertain,
                completed: None,
                deferred: None,
                replay: row.replay.clone(),
            };
            state.deliveries.get_mut(&id).ok_or(Error::Protocol)?.phase = Phase::Uncertain;
            Ok((Some(state), dispatch))
        })
        .await
    }
    pub async fn defer(&self, id: &str, intent: &str) -> Result<Retry> {
        let id = id.to_owned();
        let intent = intent.to_owned();
        let context = self.context.clone();
        self.access(move |mut state| {
            if state.row(&id, &intent, &context)?.phase != Phase::Uncertain {
                return Err(Error::Protocol);
            }
            let now = now_ms();
            let first = *state.retry.first_failure_at.get_or_insert(now);
            state.retry.failures = state.retry.failures.saturating_add(1);
            let base = 5_000u64
                .saturating_mul(1u64 << state.retry.failures.saturating_sub(1).min(5))
                .min(120_000);
            state.retry.retry_at =
                now.saturating_add(base * rand::thread_rng().gen_range(800..=1200) / 1000);
            let persistent = !state.retry.notified
                && state.retry.failures >= 5
                && now.saturating_sub(first) >= 300_000;
            if persistent {
                state.retry.notified = true;
            }
            state.deliveries.get_mut(&id).ok_or(Error::Protocol)?.retry = state.retry.clone();
            let retry = Retry {
                retry_at: state.retry.retry_at,
                persistent,
            };
            Ok((Some(state), retry))
        })
        .await
    }
    pub async fn acknowledge(&self, id: &str, intent: &str, result: Value) -> Result<()> {
        let id = id.to_owned();
        let intent = intent.to_owned();
        let context = self.context.clone();
        self.access(move |mut state| {
            let previous = state.row(&id, &intent, &context)?;
            if previous.phase == Phase::Prepared {
                return Err(Error::Invalid("Task delivery was not dispatched."));
            }
            if previous.phase == Phase::Acknowledged {
                if previous.result.as_ref() != Some(&result) {
                    return Err(Error::Protocol);
                }
                return Ok((None, ()));
            }
            let row = state.deliveries.get_mut(&id).ok_or(Error::Protocol)?;
            row.phase = Phase::Acknowledged;
            row.result = Some(result);
            state.retry = RetryState::default();
            Ok((Some(state), ()))
        })
        .await
    }
    pub async fn pending(&self) -> Result<Vec<StoredDelivery>> {
        let context = self.context.clone();
        self.access(move |state| {
            Ok((
                None,
                state
                    .deliveries
                    .into_values()
                    .filter(|row| row.context == context && row.phase != Phase::Acknowledged)
                    .collect(),
            ))
        })
        .await
    }
    pub async fn pending_replay(&self) -> Result<ReplayQueue> {
        let context = self.context.clone();
        self.access(move |state| Ok((None, state.replay_queue(&context))))
            .await
    }
}
fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64
}

/// Explicit cookie owner/context shared by command admission and foreground replay.
/// Contains key material: deliberately no Debug/serde and no profile discovery.
pub struct CookieJournalContext {
    origin: String,
    owner: String,
    team: Option<String>,
    key: Key,
}
impl CookieJournalContext {
    pub fn capture(client: &crate::client::Client) -> Result<Self> {
        let session = client.session().ok_or(Error::Authentication)?;
        if session.is_expired() {
            return Err(Error::Expired);
        }
        let origin = url::Url::parse(&session.api_url)
            .map_err(|_| Error::Protocol)?
            .origin()
            .ascii_serialization();
        Ok(Self {
            origin,
            owner: session.hashed_email.clone(),
            team: session.active_team_id.clone(),
            key: session.master_key.clone(),
        })
    }
    pub fn check(&self, client: &crate::client::Client) -> Result<()> {
        let current = Self::capture(client)?;
        if self.origin != current.origin
            || self.owner != current.owner
            || self.team != current.team
            || self.key.as_ref() != current.key.as_ref()
        {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
    pub fn journal(&self, store: &RuntimeStore) -> Result<Journal> {
        Ok(Journal::new(
            store.clone(),
            self.owner.clone(),
            serde_json::to_string(&(&self.origin, &self.team))?,
            self.key.clone(),
        ))
    }
    pub(crate) fn hashed_email(&self) -> &str {
        &self.owner
    }
    pub(crate) fn project_filters(&self) -> openmates_sdk::work::ProjectFilters {
        openmates_sdk::work::ProjectFilters {
            team_id: self.team.clone(),
            personal: self.team.is_none(),
            ..Default::default()
        }
    }
    pub(crate) fn task_filters(&self) -> openmates_sdk::work::TaskFilters {
        openmates_sdk::work::TaskFilters {
            team_id: self.team.clone(),
            personal: self.team.is_none(),
            ..Default::default()
        }
    }
    pub(crate) fn check_scope(
        &self,
        scope: &openmates_sdk::project_task_sync::TaskSyncScope,
    ) -> Result<()> {
        use openmates_sdk::project_task_sync::TaskSyncWorkspace;
        let origin = url::Url::parse(scope.api_url())
            .map_err(|_| Error::Protocol)?
            .origin()
            .ascii_serialization();
        let team = match scope.workspace() {
            TaskSyncWorkspace::Personal => None,
            TaskSyncWorkspace::Team(id) => Some(id.as_str()),
        };
        if origin != self.origin || team != self.team.as_deref() {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "task_delivery_replay_tests.rs"]
mod replay_tests;
#[cfg(test)]
mod tests {
    use super::*;
    use openmates_sdk::work::TaskMutationKind;
    fn delivery() -> TaskDelivery {
        TaskDelivery {
            protocol_version: 1,
            delivery_id: "a".repeat(64),
            task_id: "00000000-0000-4000-8000-000000000001".into(),
            team_id: None,
            scope: "synthetic-scope".into(),
            kind: TaskMutationKind::Create,
            input: serde_json::json!({"encrypted_title":"original random ciphertext","version":1}),
            expected_owner_hash: None,
            creator: false,
            actor_assignee: false,
        }
    }
    fn directory() -> tempfile::TempDir {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        builder.tempdir().unwrap()
    }
    #[tokio::test]
    async fn uncertain_restart_retains_original_payload_and_completed_receipt() {
        let directory = directory();
        let path = directory.path().to_path_buf();
        let key = Zeroizing::new([42; 32]);
        let id = "a".repeat(64);
        let intent = "b".repeat(64);
        {
            let store = RuntimeStore::new(Some(path.clone()), true).await.unwrap();
            let journal = Journal::new(
                store,
                "owner".into(),
                "https://api.example.test/personal".into(),
                key.clone(),
            );
            journal.insert(delivery(), intent.clone()).await.unwrap();
            assert!(journal.lookup(&id, "different-intent").await.is_err());
            assert!(
                journal
                    .acknowledge(&id, &intent, serde_json::json!({"ok":true}))
                    .await
                    .is_err()
            );
            let first = journal.begin(&id, &intent).await.unwrap();
            assert!(!first.uncertain && first.completed.is_none());
        }
        let store = RuntimeStore::new(Some(path.clone()), true).await.unwrap();
        let journal = Journal::new(
            store.clone(),
            "owner".into(),
            "https://api.example.test/personal".into(),
            key.clone(),
        );
        let resumed = journal.begin(&id, &intent).await.unwrap();
        assert!(resumed.uncertain && resumed.completed.is_none());
        assert_eq!(
            serde_json::to_value(resumed.delivery).unwrap(),
            serde_json::to_value(delivery()).unwrap()
        );
        assert_eq!(journal.pending().await.unwrap().len(), 1);
        let receipt = serde_json::json!({"task_id":"synthetic-id","title":"private receipt title","version":1});
        journal
            .acknowledge(&id, &intent, receipt.clone())
            .await
            .unwrap();
        assert!(journal.pending().await.unwrap().is_empty());
        assert_eq!(
            journal.begin(&id, &intent).await.unwrap().completed,
            Some(receipt)
        );
        for file in std::fs::read_dir(&path).unwrap() {
            let bytes = std::fs::read(file.unwrap().path()).unwrap();
            assert!(
                !bytes
                    .windows(21)
                    .any(|window| window == b"private receipt title")
            );
            assert!(
                !bytes
                    .windows(26)
                    .any(|window| window == b"original random ciphertext")
            );
        }
        let wrong = Journal::new(
            store,
            "owner".into(),
            "https://api.example.test/personal".into(),
            Zeroizing::new([43; 32]),
        );
        assert!(matches!(
            wrong.lookup(&id, &intent).await,
            Err(Error::Crypto)
        ));
    }
    #[tokio::test]
    async fn retry_cooldown_survives_restart_and_covers_teams_without_cross_team_delivery() {
        let directory = directory();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let key = Zeroizing::new([42; 32]);
        let context =
            |team: &str| serde_json::to_string(&("https://api.example.test", team)).unwrap();
        let personal = Journal::new(
            store.clone(),
            "owner".into(),
            context("personal"),
            key.clone(),
        );
        let team = Journal::new(
            store.clone(),
            "owner".into(),
            context("team-a"),
            key.clone(),
        );
        let id = "a".repeat(64);
        let second_id = "b".repeat(64);
        personal.insert(delivery(), "intent".into()).await.unwrap();
        personal.begin(&id, "intent").await.unwrap();
        let before = now_ms();
        let retry = personal.defer(&id, "intent").await.unwrap();
        assert!((before + 4_000..=now_ms() + 6_000).contains(&retry.retry_at));
        assert!(matches!(
            team.lookup(&id, "intent").await,
            Err(Error::Forbidden)
        ));
        assert!(team.pending().await.unwrap().is_empty());
        let mut another = delivery();
        another.delivery_id = second_id.clone();
        another.team_id = Some("team-a".into());
        team.insert(another, "team-intent".into()).await.unwrap();
        let resumed = Journal::new(store, "owner".into(), context("team-a"), key);
        assert_eq!(
            resumed
                .begin(&second_id, "team-intent")
                .await
                .unwrap()
                .deferred
                .unwrap()
                .retry_at,
            retry.retry_at
        );
        personal
            .acknowledge(&id, "intent", serde_json::json!({"canonical":true}))
            .await
            .unwrap();
        assert!(
            resumed
                .begin(&second_id, "team-intent")
                .await
                .unwrap()
                .deferred
                .is_none()
        );
        // A retained successful receipt remains readable during a later outage.
        resumed.defer(&second_id, "team-intent").await.unwrap();
        assert_eq!(
            personal.begin(&id, "intent").await.unwrap().completed,
            Some(serde_json::json!({"canonical":true}))
        );
    }
    #[tokio::test]
    async fn logout_fences_a_previously_created_journal() {
        let directory = directory();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let journal = Journal::new(
            store.clone(),
            "owner".into(),
            "context".into(),
            Zeroizing::new([42; 32]),
        );
        journal.insert(delivery(), "intent".into()).await.unwrap();
        store.clear().await.unwrap();
        assert!(matches!(
            journal.begin(&"a".repeat(64), "intent").await,
            Err(Error::Cancelled)
        ));
    }
    #[tokio::test]
    async fn intent_hides_private_values_and_ignores_presentation_and_credentials() {
        let directory = directory();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let journal = Journal::new(
            store,
            "owner".into(),
            "context".into(),
            Zeroizing::new([42; 32]),
        );
        let mut invocation = Invocation {
            path: vec!["tasks".into(), "create".into()],
            positionals: vec![],
            flags: BTreeMap::from([("title".into(), serde_json::json!("private task title"))]),
        };
        let original = journal.intent(&invocation).unwrap();
        invocation.flags.insert("json".into(), Value::Bool(true));
        invocation
            .flags
            .insert("api-key".into(), serde_json::json!("never-persist-this"));
        assert_eq!(journal.intent(&invocation).unwrap(), original);
        invocation
            .flags
            .insert("title".into(), serde_json::json!("different task"));
        assert_ne!(journal.intent(&invocation).unwrap(), original);
        assert_eq!(original.len(), 64);
    }
}
