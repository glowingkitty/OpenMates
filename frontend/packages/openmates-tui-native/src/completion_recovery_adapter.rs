//! Thin explicit native durability adapter. No runtime/monitor/UI orchestration.
use crate::{
    client::{
        Client, CompletionRecoveryCheckpoint, CompletionRecoveryDurableReceipt,
        CompletionRecoveryStage,
    },
    error::{Error, Result},
    runtime_store::RuntimeStore,
};
use openmates_sdk::crypto::Key;
use serde_json::Value;
// Production Store owns runtime.lock; this also serializes in-process cache
// read/merge/write across explicitly scheduled adapter operations.
static PENDING_CACHE: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
/// Captured only after matching the actual stage to current explicit credentials.
/// No Debug/serde: this value owns the native master key for encrypted storage.
pub struct CompletionCheckpointWrite {
    owner: String,
    cache_key: String,
    master: Key,
    value: Value,
    job_id: String,
    digest: String,
    store_generation: u64,
}
fn cache_key(client: &Client) -> Result<String> {
    let session = client.session().ok_or(Error::Authentication)?;
    Ok(format!(
        "completion-pending-{}",
        crate::session_runtime::cache_key(session)
    ))
}
pub fn prepare_checkpoint_write(
    client: &Client,
    stage: &CompletionRecoveryStage,
    store: &RuntimeStore,
) -> Result<CompletionCheckpointWrite> {
    let checkpoint = stage.checkpoint()?;
    let session = client.session().ok_or(Error::Authentication)?;
    let owner = client.user()["id"]
        .as_str()
        .or_else(|| client.user()["user_id"].as_str())
        .ok_or(Error::Authentication)?;
    if checkpoint.owner_id() != owner
        || checkpoint.api_url() != session.api_url.trim_end_matches('/')
        || checkpoint.team_id() != session.active_team_id.as_deref()
    {
        return Err(Error::Forbidden);
    }
    Ok(CompletionCheckpointWrite {
        owner: session.hashed_email.clone(),
        cache_key: cache_key(client)?,
        master: session.master_key.clone(),
        value: serde_json::to_value(&checkpoint)?,
        job_id: checkpoint.job().job_id.clone(),
        digest: checkpoint.digest()?,
        store_generation: store.generation(),
    })
}
/// Call after releasing any Client guard. Receipt is issued only after the
/// RuntimeStore's encrypted atomic/fsync publication actually succeeds.
pub async fn persist_checkpoint(
    store: &RuntimeStore,
    write: CompletionCheckpointWrite,
) -> Result<CompletionRecoveryDurableReceipt> {
    let _pending_guard = PENDING_CACHE.lock().await;
    if store.generation() != write.store_generation {
        return Err(Error::Cancelled);
    }
    let existing = store
        .read_cache(
            write.owner.clone(),
            write.cache_key.clone(),
            write.master.clone(),
        )
        .await
        .map_err(local_record_error)?;
    let mut pending = pending_map(existing)?;
    if pending.len() >= 100 && !pending.contains_key(&write.job_id) {
        return Err(Error::Protocol);
    }
    let candidate: CompletionRecoveryCheckpoint = serde_json::from_value(write.value)?;
    if candidate.job().job_id != write.job_id || candidate.digest()? != write.digest {
        return Err(Error::Protocol);
    }
    if let Some(existing) = pending.get(&write.job_id) {
        if existing.digest()? != write.digest {
            // An uncertain ACK may already have committed this ciphertext.
            // Preserve the durable candidate until fresh canonical reconciliation.
            return Err(Error::Conflict);
        }
    }
    pending.insert(write.job_id, candidate);
    if store.generation() != write.store_generation {
        return Err(Error::Cancelled);
    }
    store
        .write_cache(
            write.owner,
            write.cache_key,
            write.master,
            serde_json::to_value(pending)?,
        )
        .await?;
    if store.generation() != write.store_generation {
        return Err(Error::Cancelled);
    }
    Ok(CompletionRecoveryDurableReceipt {
        checkpoint_sha256: write.digest,
    })
}
/// Rehydrated checkpoint is DATA ONLY: caller must pass it to the SDK's fresh
/// resume/reconciliation path before claim, persist or success publication.
pub async fn load_pending(
    client: &Client,
    store: &RuntimeStore,
) -> Result<Vec<CompletionRecoveryCheckpoint>> {
    let session = client.session().ok_or(Error::Authentication)?;
    let generation = store.generation();
    let value = store
        .read_cache(
            session.hashed_email.clone(),
            cache_key(client)?,
            session.master_key.clone(),
        )
        .await
        .map_err(local_record_error)?;
    if store.generation() != generation {
        return Err(Error::Cancelled);
    }
    Ok(pending_map(value)?.into_values().collect())
}
/// Clear only after canonical recovery receipt AND canonical cache persistence.
pub async fn clear_pending(client: &Client, store: &RuntimeStore, job_id: &str) -> Result<()> {
    let _pending_guard = PENDING_CACHE.lock().await;
    let session = client.session().ok_or(Error::Authentication)?;
    let generation = store.generation();
    let key = cache_key(client)?;
    let value = store
        .read_cache(
            session.hashed_email.clone(),
            key.clone(),
            session.master_key.clone(),
        )
        .await
        .map_err(local_record_error)?;
    let mut pending = pending_map(value)?;
    pending.remove(job_id);
    if store.generation() != generation {
        return Err(Error::Cancelled);
    }
    store
        .write_cache(
            session.hashed_email.clone(),
            key,
            session.master_key.clone(),
            serde_json::to_value(pending)?,
        )
        .await
}

/// The core has already freshly reconciled canonical state. The host persists
/// that current Client state with its existing encrypted cache/session path.
/// Returning success means durable cache publication, not UI paint. No public
/// open_chat fallback is used as a substitute for a strict canonical reread.
/// The callback MUST retain its explicit owner/generation/view admission and
/// must not reuse any ChatRefresh staged before this recovery mutation.
pub trait CanonicalRecoveryPersistence {
    fn persist_reconciled_canonical<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: &'a str,
        cancel: &'a tokio_util::sync::CancellationToken,
    ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>>;
}
pub struct CompletionRecoveryPumpOptions {
    /// Some(chat) strictly limits claims to this selected chat. None allows
    /// bounded background foreground-session inventory processing.
    pub selected_chat: Option<String>,
    /// A hard per-turn bound (2..=32); remaining jobs stay discoverable/pending.
    pub max_attempts: usize,
}
#[derive(Default)]
pub struct CompletionRecoveryPumpOutcome {
    pub completed: usize,
    pub deferred: usize,
    pub attempted: usize,
    /// Caller must stage a fresh view after pump; never publish an older view.
    pub canonical_changed: bool,
    /// Present only after complete discovery and an entirely idle recovery turn.
    /// SDK revalidates issuer/context/credentials/ciphertext before list reuse.
    pub fresh_inventory: Option<crate::client::FreshChatInventory>,
}
/// Explicit foreground only. Discovery authenticates before local cache IO so
/// known auth denial cannot be hidden by a damaged/unavailable pending cache.
/// Pending checkpoints are resumed first and exclude same-job restaging even
/// after deferred or uncertain completion. No Send/inference operation exists.
pub async fn pump_completion_recovery(
    client: &mut Client,
    store: &RuntimeStore,
    options: CompletionRecoveryPumpOptions,
    cancel: &tokio_util::sync::CancellationToken,
    canonical: &mut impl CanonicalRecoveryPersistence,
) -> Result<CompletionRecoveryPumpOutcome> {
    pump_completion_recovery_with_inventory(client, store, options, cancel, canonical, false).await
}
/// Selected TUI recovery retains its two selected and six global attempt caps.
/// The SDK may certify a freshly discovered, fully empty global batch. Consume
/// that opaque evidence immediately, under this exclusive Client borrow, rather
/// than repeating the same empty discovery. It is never returned, cached, used
/// as auth, or promoted to ciphertext freshness. Any unsupported/incomplete/
/// nonempty/changed batch takes the original second global pump unchanged.
pub async fn pump_selected_and_global_completion_recovery(
    client: &mut Client,
    store: &RuntimeStore,
    selected_chat: String,
    cancel: &tokio_util::sync::CancellationToken,
    canonical: &mut impl CanonicalRecoveryPersistence,
) -> Result<CompletionRecoveryPumpOutcome> {
    let generation = store.generation();
    // Team/Direct profiles retain their original ordinary discovery policy.
    // Eligibility alone grants nothing: only the new complete SDK proof below
    // can cover the global no-work check.
    let inventory = client.supports_cached_default_chat_list();
    let mut selected = pump_completion_recovery_with_inventory(
        client,
        store,
        CompletionRecoveryPumpOptions { selected_chat: Some(selected_chat), max_attempts: 2 },
        cancel,
        canonical,
        inventory,
    ).await?;
    if cancel.is_cancelled() || store.generation() != generation {
        return Err(Error::Cancelled);
    }
    // This value came from the same Client above, not a caller or restored data.
    // Its constructor requires correlated complete empty main, metadata, Task,
    // typed-output and workflow discovery. The pump additionally requires no
    // global pending checkpoint, attempt, deferral or canonical mutation. Thus
    // there has been no canonical callback since issuance. The consuming SDK
    // check below still revalidates independently shared monitor invalidation;
    // no await follows a positive check before the covered no-work return.
    if let Some(empty) = selected.fresh_inventory.take() {
        // The keyless monitor shares network/authority invalidation even while
        // this Client is exclusively borrowed. Local Store awaits above can
        // therefore stale the proof; only the SDK can recheck all its fences.
        if empty.consume_if_current(client, cancel)? {
            if cancel.is_cancelled() || store.generation() != generation {
                return Err(Error::Cancelled);
            }
            return Ok(selected);
        }
    }
    let global = pump_completion_recovery(
        client,
        store,
        CompletionRecoveryPumpOptions { selected_chat: None, max_attempts: 6 },
        cancel,
        canonical,
    ).await?;
    selected.completed += global.completed;
    selected.deferred += global.deferred;
    selected.attempted += global.attempted;
    selected.canonical_changed |= global.canonical_changed;
    Ok(selected)
}
/// Optional proof discovery for a same-batch Chat inventory or typed full-history
/// read transaction. Recovery scope and all effect admission remain unchanged.
pub async fn pump_completion_recovery_with_inventory(
    client: &mut Client,
    store: &RuntimeStore,
    options: CompletionRecoveryPumpOptions,
    cancel: &tokio_util::sync::CancellationToken,
    canonical: &mut impl CanonicalRecoveryPersistence,
    inventory: bool,
) -> Result<CompletionRecoveryPumpOutcome> {
    pump_completion_recovery_discovery(client, store, options, cancel, canonical, inventory, false).await
}
/// CLI saved reads only: selected calls do not warm an unrelated list. Existing
/// TUI selected-plus-global scheduling retains its global-discovery semantics.
pub(crate) async fn pump_completion_recovery_for_saved_read(
    client: &mut Client,
    store: &RuntimeStore,
    options: CompletionRecoveryPumpOptions,
    cancel: &tokio_util::sync::CancellationToken,
    canonical: &mut impl CanonicalRecoveryPersistence,
    inventory: bool,
) -> Result<CompletionRecoveryPumpOutcome> {
    let selected = options.selected_chat.is_some();
    pump_completion_recovery_discovery(client, store, options, cancel, canonical, inventory, selected).await
}
async fn pump_completion_recovery_discovery(
    client: &mut Client,
    store: &RuntimeStore,
    options: CompletionRecoveryPumpOptions,
    cancel: &tokio_util::sync::CancellationToken,
    canonical: &mut impl CanonicalRecoveryPersistence,
    inventory: bool,
    selected_discovery: bool,
) -> Result<CompletionRecoveryPumpOutcome> {
    use crate::client::{CompletionRecoveryAdmission, CompletionRecoveryJob};
    if !(2..=32).contains(&options.max_attempts) {
        return Err(Error::Invalid("Invalid recovery pump bound."));
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    // This authenticates current credentials; neither stored data nor monitor
    // hints are authority to claim. Security errors propagate independently.
    let (discovered, fresh_inventory) = if let Some(id) = options.selected_chat.as_deref().filter(|_| selected_discovery) {
        // Selected foreground recovery discovers jobs on its authenticated
        // socket, without downloading unrelated working-set content or granting
        // a complete-list receipt. Durable unrelated checkpoints stay below.
        (client.completion_recovery_jobs_for_chat(id, cancel).await?, None)
    } else if inventory {
        client
            .completion_recovery_jobs_with_inventory(cancel)
            .await?
    } else {
        (client.completion_recovery_jobs(cancel).await?, None)
    };
    let pending = load_pending(client, store).await?;
    // Selection may omit another Chat's checkpoint from recovery work, but
    // that uncertainty can never admit global cached-list freshness.
    let globally_settled = pending.is_empty();
    let unresolved = pending
        .iter()
        .map(|p| p.job().job_id.clone())
        .collect::<std::collections::BTreeSet<_>>();
    enum Input {
        Saved(CompletionRecoveryCheckpoint),
        Fresh(CompletionRecoveryJob),
    }
    let eligible = |job: &CompletionRecoveryJob| {
        eligible_for_selected_chat(options.selected_chat.as_deref(), job)
    };
    let cursor_key = format!("{}-continuation", cache_key(client)?);
    let session = client.session().ok_or(Error::Authentication)?;
    let generation = store.generation();
    let continuation = store
        .read_cache(
            session.hashed_email.clone(),
            cursor_key.clone(),
            session.master_key.clone(),
        )
        .await
        .map_err(local_record_error)?;
    if store.generation() != generation || cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    let continuation = decode_continuation(continuation, false)?;
    let mut saved = pending
        .into_iter()
        .filter(|p| eligible(p.job()))
        .collect::<Vec<_>>();
    rotate_saved(&mut saved, continuation.as_deref());
    let mut work = saved.into_iter().map(Input::Saved).collect::<Vec<_>>();
    let mut fresh = discovered
        .into_iter()
        .filter(|j| eligible(j) && !unresolved.contains(&j.job_id))
        .collect::<Vec<_>>();
    let fresh_cursor_key = format!("{}-fresh-continuation", cache_key(client)?);
    let session = client.session().ok_or(Error::Authentication)?;
    let fresh_continuation = store
        .read_cache(
            session.hashed_email.clone(),
            fresh_cursor_key.clone(),
            session.master_key.clone(),
        )
        .await
        .map_err(local_record_error)?;
    if store.generation() != generation || cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    let fresh_continuation = decode_continuation(fresh_continuation, true)?;
    rotate_fresh(&mut fresh, fresh_continuation.as_deref());
    // Always leave a slot for a new recoverable job. An unsettled older job
    // cannot consume the entire bounded turn indefinitely.
    if !fresh.is_empty() {
        work.truncate(options.max_attempts - 1);
    }
    work.extend(fresh.into_iter().map(Input::Fresh));
    let mut outcome = CompletionRecoveryPumpOutcome::default();
    for input in work.into_iter().take(options.max_attempts) {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        outcome.attempted += 1;
        let admission = match input {
            Input::Saved(checkpoint) => {
                // Durable scheduling progress, separate from checkpoint data.
                // Advance even for Deferred; restart cannot retry one prefix
                // forever. Never delete or re-encrypt a candidate to rotate.
                let session = client.session().ok_or(Error::Authentication)?;
                if store.generation() != generation || cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                store
                    .write_cache(
                        session.hashed_email.clone(),
                        cursor_key.clone(),
                        session.master_key.clone(),
                        Value::String(checkpoint.job().job_id.clone()),
                    )
                    .await?;
                if store.generation() != generation || cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                client.resume_completion_recovery(checkpoint, cancel).await
            }
            Input::Fresh(job) => {
                // Unsupported/Deferred discoveries also advance durable fair
                // progress; a reserved fresh slot must not retry one ID forever.
                let session = client.session().ok_or(Error::Authentication)?;
                if store.generation() != generation || cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                store
                    .write_cache(
                        session.hashed_email.clone(),
                        fresh_cursor_key.clone(),
                        session.master_key.clone(),
                        Value::String(fresh_order_key(&job)),
                    )
                    .await?;
                if store.generation() != generation || cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                client.stage_completion_recovery(&job, cancel).await
            }
        };
        let effect: Result<Option<crate::client::CompletionRecoveryReceipt>> = async {
            match admission? {
                CompletionRecoveryAdmission::Deferred => Ok(None),
                CompletionRecoveryAdmission::Canonical(receipt) => Ok(Some(receipt)),
                CompletionRecoveryAdmission::Ready(stage) => {
                    let write = prepare_checkpoint_write(client, &stage, store)?;
                    let durable = persist_checkpoint(store, write).await?;
                    if cancel.is_cancelled() {
                        return Err(Error::Cancelled);
                    }
                    client
                        .commit_completion_recovery(*stage, durable, cancel)
                        .await
                        .map(Some)
                }
            }
        }
        .await;
        match effect {
            Ok(Some(receipt)) => {
                // A server receipt is not durable local publication. Keep its
                // checkpoint on every callback failure/cancellation for resume.
                if cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                outcome.canonical_changed = true;
                match canonical
                    .persist_reconciled_canonical(client, &receipt.chat_id, cancel)
                    .await
                {
                    Ok(()) => {}
                    Err(Error::Conflict | Error::Offline | Error::Io | Error::Protocol) => {
                        outcome.deferred += 1;
                        continue;
                    }
                    Err(error) => return Err(error),
                }
                if cancel.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                clear_pending(client, store, &receipt.job_id).await?;
                outcome.completed += 1;
                outcome.canonical_changed = true;
            }
            Ok(None) | Err(Error::Conflict | Error::Offline | Error::Io | Error::Protocol) => {
                outcome.deferred += 1
            }
            Err(error) => return Err(error),
        }
    }
    if cancel.is_cancelled() {
        return Err(Error::Cancelled);
    }
    if globally_settled
        && outcome.attempted == 0
        && outcome.deferred == 0
        && !outcome.canonical_changed
    {
        outcome.fresh_inventory = fresh_inventory;
    }
    Ok(outcome)
}

fn fresh_order_key(job: &crate::client::CompletionRecoveryJob) -> String {
    format!(
        "{}:{}",
        if matches!(job.kind, crate::client::CompletionRecoveryKind::Metadata) {
            1
        } else {
            0
        },
        job.job_id
    )
}
fn rotate_fresh(jobs: &mut [crate::client::CompletionRecoveryJob], after: Option<&str>) {
    // Main is initially first; durable continuation wraps over both kinds so
    // neither a deferred main prefix nor restart can starve later work.
    jobs.sort_by_key(fresh_order_key);
    if let Some(after) = after {
        let first = jobs.partition_point(|job| fresh_order_key(job).as_str() <= after);
        if first < jobs.len() {
            jobs.rotate_left(first)
        }
    }
}

fn rotate_saved(saved: &mut [CompletionRecoveryCheckpoint], after: Option<&str>) {
    saved.sort_by(|a, b| a.job().job_id.cmp(&b.job().job_id));
    if let Some(after) = after {
        let first = saved.partition_point(|checkpoint| checkpoint.job().job_id.as_str() <= after);
        if first < saved.len() {
            saved.rotate_left(first)
        }
    }
}

fn local_record_invalid() -> Error {
    Error::Unavailable {
        code: "completion_recovery_checkpoint_invalid",
        reason: "LOCAL_COMPLETION_CHECKPOINT_INVALID",
    }
}
fn local_record_error(error: Error) -> Error {
    match error {
        Error::Protocol => local_record_invalid(),
        other => other,
    }
}
fn decode_continuation(value: Option<Value>, fresh: bool) -> Result<Option<String>> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(id)) => {
            let raw = if fresh {
                id.strip_prefix("0:")
                    .or_else(|| id.strip_prefix("1:"))
                    .ok_or_else(local_record_invalid)?
            } else {
                id.as_str()
            };
            let parsed = uuid::Uuid::parse_str(raw).map_err(|_| local_record_invalid())?;
            if parsed.hyphenated().to_string() != raw {
                return Err(local_record_invalid());
            }
            Ok(Some(id))
        }
        _ => Err(local_record_invalid()),
    }
}
fn pending_map(
    value: Option<Value>,
) -> Result<std::collections::BTreeMap<String, CompletionRecoveryCheckpoint>> {
    let pending = match value {
        None | Some(Value::Null) => std::collections::BTreeMap::new(),
        Some(value) => {
            let object = value.as_object().ok_or_else(local_record_invalid)?;
            if object.len() > 100
                || object.values().any(|checkpoint| {
                    checkpoint["protocol_version"] != 1
                        || !checkpoint["encrypted_candidate"].is_object()
                })
            {
                return Err(local_record_invalid());
            }
            serde_json::from_value::<std::collections::BTreeMap<String,CompletionRecoveryCheckpoint>>(value).map_err(|_|local_record_invalid())?
        }
    };
    if pending
        .iter()
        .any(|(id, checkpoint)| id != &checkpoint.job().job_id)
    {
        return Err(local_record_invalid());
    }
    for checkpoint in pending.values() {
        checkpoint.digest().map_err(local_record_error)?;
    }
    Ok(pending)
}
#[cfg(test)]
mod tests {
    use super::*;
    fn data(job: &str) -> CompletionRecoveryCheckpoint {
        serde_json::from_value(serde_json::json!({"protocol_version":1,"api_url":"https://synthetic.invalid","owner_id":"11111111-1111-4111-8111-111111111111","team_id":null,"job":{"kind":"main","job_id":job,"chat_id":"22222222-2222-4222-8222-222222222222","turn_id":"33333333-3333-4333-8333-333333333333","assistant_message_id":"55555555-5555-4555-8555-555555555555","task_id":null,"stage":null,"chat_key_version":1},"encrypted_candidate":{},"wrapped_chat_key":null,"canonical_ciphertext":false})).unwrap()
    }
    // contract-test: supporting surface=cli assertions=sdk.library.explicit-headless,sdk.encryption.local-only
    #[test]
    fn pending_map_preserves_old_uncertain_candidate_while_new_job_is_added_and_cleared() {
        let old = data("44444444-4444-4444-8444-444444444444");
        let new = data("66666666-6666-4666-8666-666666666666");
        let mut map = std::collections::BTreeMap::new();
        map.insert(old.job().job_id.clone(), old.clone());
        map.insert(new.job().job_id.clone(), new.clone());
        let mut restored = pending_map(Some(serde_json::to_value(map).unwrap())).unwrap();
        assert_eq!(restored.len(), 2);
        restored.remove(&new.job().job_id);
        assert_eq!(
            restored.get(&old.job().job_id).unwrap().digest().unwrap(),
            old.digest().unwrap()
        );
    }
    // contract-test: supporting surface=cli assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
    #[test]
    fn pending_map_rejects_identity_alias_and_never_treats_data_as_recovery_authority() {
        let value = data("44444444-4444-4444-8444-444444444444");
        let aliases = std::collections::BTreeMap::from([("foreign".to_owned(), value)]);
        assert!(matches!(
            pending_map(Some(serde_json::to_value(aliases).unwrap())),
            Err(Error::Unavailable {
                code: "completion_recovery_checkpoint_invalid",
                reason: "LOCAL_COMPLETION_CHECKPOINT_INVALID"
            })
        ));
        assert!(pending_map(Some(Value::Null)).unwrap().is_empty());
    }
    // contract-test: supporting surface=cli assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn encrypted_restart_preserves_uncertain_same_job_and_rejects_changed_ciphertext() {
        tokio::time::timeout(std::time::Duration::from_secs(30), async {
            let directory = tempfile::Builder::new()
                .prefix("completion-checkpoint-")
                .tempdir()
                .unwrap();
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
                    .unwrap();
            }
            let session = crate::storage::Session {
                api_url: "https://synthetic.invalid".into(),
                session_id: "synthetic-session".into(),
                cookies: Default::default(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            };
            let passphrase = || {
                Some(zeroize::Zeroizing::new(
                    "synthetic fixture vault passphrase".to_owned(),
                ))
            };
            let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
                .await
                .unwrap();
            store.begin_session(session.clone()).await.unwrap();
            store.save(session.clone(), passphrase()).await.unwrap();
            let old = data("44444444-4444-4444-8444-444444444444");
            let make_write = |store: &RuntimeStore, checkpoint: &CompletionRecoveryCheckpoint| {
                CompletionCheckpointWrite {
                    owner: session.hashed_email.clone(),
                    cache_key: "completion-pending-sync-personal".into(),
                    master: session.master_key.clone(),
                    value: serde_json::to_value(checkpoint).unwrap(),
                    job_id: checkpoint.job().job_id.clone(),
                    digest: checkpoint.digest().unwrap(),
                    store_generation: store.generation(),
                }
            };
            persist_checkpoint(&store, make_write(&store, &old))
                .await
                .unwrap();
            store
                .write_cache(
                    session.hashed_email.clone(),
                    "completion-pending-sync-personal-continuation".into(),
                    session.master_key.clone(),
                    Value::String(old.job().job_id.clone()),
                )
                .await
                .unwrap();
            let mut fresh_jobs = (1..=9)
                .map(|n| {
                    data(&format!("{n:08}-4444-4444-8444-444444444444"))
                        .job()
                        .clone()
                })
                .collect::<Vec<_>>();
            for job in fresh_jobs.iter_mut().take(8) {
                job.chat_key_version = 2;
            } // unsupported Deferred prefix
            let fresh_key = "completion-pending-sync-personal-fresh-continuation";
            store
                .write_cache(
                    session.hashed_email.clone(),
                    fresh_key.into(),
                    session.master_key.clone(),
                    Value::String(fresh_order_key(&fresh_jobs[7])),
                )
                .await
                .unwrap();
            drop(store);
            let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
                .await
                .unwrap();
            assert!(store.load(passphrase()).await.unwrap().is_some());
            assert_eq!(
                store
                    .read_cache(
                        session.hashed_email.clone(),
                        "completion-pending-sync-personal-continuation".into(),
                        session.master_key.clone()
                    )
                    .await
                    .unwrap(),
                Some(Value::String(old.job().job_id.clone()))
            );
            let fresh_cursor = store
                .read_cache(
                    session.hashed_email.clone(),
                    fresh_key.into(),
                    session.master_key.clone(),
                )
                .await
                .unwrap()
                .unwrap();
            rotate_fresh(&mut fresh_jobs, fresh_cursor.as_str());
            assert_eq!(fresh_jobs[0].chat_key_version, 1); // later supported job survives restart/reserved-one-slot scheduling
            let read = || {
                store.read_cache(
                    session.hashed_email.clone(),
                    "completion-pending-sync-personal".into(),
                    session.master_key.clone(),
                )
            };
            let before = read().await.unwrap();
            let mut changed = serde_json::to_value(&old).unwrap();
            changed["encrypted_candidate"] =
                serde_json::json!({"encrypted_content":"different-ciphertext"});
            let changed: CompletionRecoveryCheckpoint = serde_json::from_value(changed).unwrap();
            assert!(matches!(
                persist_checkpoint(&store, make_write(&store, &changed)).await,
                Err(Error::Conflict)
            ));
            assert_eq!(read().await.unwrap(), before);
            let receipt = persist_checkpoint(&store, make_write(&store, &old))
                .await
                .unwrap();
            assert_eq!(receipt.checkpoint_sha256, old.digest().unwrap());
            let other = data("66666666-6666-4666-8666-666666666666");
            persist_checkpoint(&store, make_write(&store, &other))
                .await
                .unwrap();
            let restored = pending_map(read().await.unwrap()).unwrap();
            assert_eq!(restored.len(), 2);
            assert_eq!(
                restored[&old.job().job_id].digest().unwrap(),
                old.digest().unwrap()
            );
            // Refusal produces no DurableReceipt, so no SDK canonical commit can
            // be invoked from this failed storage effect.
        })
        .await
        .unwrap();
    }
    // contract-test: supporting surface=cli assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
    #[test]
    fn bounded_continuation_visits_saved_backlog_without_modifying_candidates() {
        let saved = (1..=9)
            .map(|n| data(&format!("{n:08}-4444-4444-8444-444444444444")))
            .collect::<Vec<_>>();
        let original = saved
            .iter()
            .map(|p| (p.job().job_id.clone(), p.digest().unwrap()))
            .collect::<std::collections::BTreeMap<_, _>>();
        let mut after = None;
        let mut visited = std::collections::BTreeSet::new();
        for _ in 0..5 {
            let mut turn = saved.clone();
            rotate_saved(&mut turn, after.as_deref());
            for item in turn.into_iter().take(2) {
                assert_eq!(item.digest().unwrap(), original[&item.job().job_id]);
                after = Some(item.job().job_id.clone());
                visited.insert(item.job().job_id.clone());
            }
        }
        assert_eq!(visited.len(), 9);
    }
    // contract-test: supporting surface=cli assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
    #[test]
    fn one_fresh_slot_advances_past_deferred_prefix_and_wraps_without_rewriting_jobs() {
        let mut jobs = (1..=9)
            .map(|n| {
                data(&format!("{n:08}-4444-4444-8444-444444444444"))
                    .job()
                    .clone()
            })
            .collect::<Vec<_>>();
        for job in jobs.iter_mut().take(8) {
            job.chat_key_version = 2;
        }
        let original = serde_json::to_value(&jobs).unwrap();
        let mut after = None;
        let mut found = false;
        for _ in 0..9 {
            let mut turn = jobs.clone();
            rotate_fresh(&mut turn, after.as_deref());
            let attempted = &turn[0]; // max-1 saved Deferred jobs, one fresh slot
            if attempted.chat_key_version == 1 {
                found = true;
            }
            after = Some(fresh_order_key(attempted));
        }
        assert!(found);
        assert_eq!(serde_json::to_value(&jobs).unwrap(), original);
        let mut next = jobs.clone();
        rotate_fresh(&mut next, after.as_deref());
        assert_eq!(next[0].job_id, jobs[0].job_id);
    }
    // contract-test: supporting surface=cli assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
    #[test]
    fn malformed_local_records_are_distinct_from_network_protocol_and_security_errors() {
        let invalid = local_record_invalid();
        for value in [
            serde_json::json!([]),
            serde_json::json!({"bad":"malformed"}),
            serde_json::json!({"alias":data("44444444-4444-4444-8444-444444444444")}),
        ] {
            assert!(matches!(pending_map(Some(value)),Err(error) if error==invalid));
        }
        let too_many = (1..=101)
            .map(|n| {
                let id = format!("{n:08}-4444-4444-8444-444444444444");
                (id.clone(), data(&id))
            })
            .collect::<std::collections::BTreeMap<_, _>>();
        assert!(
            matches!(pending_map(Some(serde_json::to_value(too_many).unwrap())),Err(error) if error==invalid)
        );
        let mut unsupported =
            serde_json::to_value(data("44444444-4444-4444-8444-444444444444")).unwrap();
        unsupported["protocol_version"] = serde_json::json!(2);
        assert!(
            matches!(pending_map(Some(serde_json::json!({"44444444-4444-4444-8444-444444444444":unsupported}))),Err(error) if error==invalid)
        );
        for fresh in [false, true] {
            for value in [
                serde_json::json!(7),
                serde_json::json!({}),
                serde_json::json!(""),
                serde_json::json!("not-a-canonical-id"),
            ] {
                assert_eq!(decode_continuation(Some(value), fresh), Err(invalid));
            }
        }
        assert!(
            decode_continuation(
                Some(Value::String("44444444-4444-4444-8444-444444444444".into())),
                false
            )
            .is_ok()
        );
        assert!(
            decode_continuation(
                Some(Value::String(
                    "0:44444444-4444-4444-8444-444444444444".into()
                )),
                true
            )
            .is_ok()
        );
        for error in [
            Error::Crypto,
            Error::Authentication,
            Error::Forbidden,
            Error::Cancelled,
            Error::Expired,
            Error::Io,
        ] {
            assert_eq!(local_record_error(error), error);
        }
        // Only explicit local read boundaries invoke this mapper.
        assert_eq!(local_record_error(Error::Protocol), invalid);
        assert_ne!(Error::Protocol, invalid);
    }
    // contract-test: supporting surface=cli assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn malformed_encrypted_records_preserve_disk_and_network_protocol_precedes_local_decode()
    {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        struct NoCanonical;
        impl CanonicalRecoveryPersistence for NoCanonical {
            fn persist_reconciled_canonical<'a>(
                &'a mut self,
                _: &'a mut Client,
                _: &'a str,
                _: &'a tokio_util::sync::CancellationToken,
            ) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<()>> + Send + 'a>>
            {
                Box::pin(async {
                    panic!("Malformed local record must not persist canonical state")
                })
            }
        }
        fn disk_records(
            root: &std::path::Path,
        ) -> std::collections::BTreeMap<std::path::PathBuf, Vec<u8>> {
            let mut files = std::collections::BTreeMap::new();
            fn read(
                root: &std::path::Path,
                dir: &std::path::Path,
                files: &mut std::collections::BTreeMap<std::path::PathBuf, Vec<u8>>,
            ) {
                for item in std::fs::read_dir(dir).unwrap() {
                    let path = item.unwrap().path();
                    if path.is_dir() {
                        read(root, &path, files)
                    } else {
                        files.insert(
                            path.strip_prefix(root).unwrap().to_path_buf(),
                            std::fs::read(path).unwrap(),
                        );
                    }
                }
            }
            read(root, root, &mut files);
            files
        }
        tokio::time::timeout(std::time::Duration::from_secs(30),async {
            let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let api=format!("http://{}",listener.local_addr().unwrap());
            let peer=tokio::spawn(async move {
                let(mut socket,_)=listener.accept().await.unwrap();let mut bytes=Vec::new();
                loop {let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.unwrap();assert!(n>0);bytes.extend_from_slice(&chunk[..n]);if bytes.windows(4).any(|p|p==b"\r\n\r\n"){break}}
                assert!(String::from_utf8_lossy(&bytes).contains("/v1/auth/session"));
                socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{").await.unwrap();
            });
            let directory=tempfile::Builder::new().prefix("invalid-completion-record-").tempdir().unwrap();
            #[cfg(unix)] {use std::os::unix::fs::PermissionsExt;std::fs::set_permissions(directory.path(),std::fs::Permissions::from_mode(0o700)).unwrap();}
            let session=crate::storage::Session {api_url:api.clone(),session_id:"synthetic-session".into(),cookies:Default::default(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic-owner".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None};
            let store=RuntimeStore::new(Some(directory.path().to_path_buf()),true).await.unwrap();store.begin_session(session.clone()).await.unwrap();store.save(session.clone(),Some(zeroize::Zeroizing::new("synthetic fixture vault passphrase".into()))).await.unwrap();
            let mut client=Client::new(&api,Some(session.clone())).unwrap();client.set_foreground_completion_recovery(true).unwrap();
            let key=cache_key(&client).unwrap();
            store.write_cache(session.hashed_email.clone(),key.clone(),session.master_key.clone(),serde_json::json!({"broken":"malformed-local-sentinel"})).await.unwrap();
            for suffix in ["-continuation","-fresh-continuation"] {store.write_cache(session.hashed_email.clone(),format!("{key}{suffix}"),session.master_key.clone(),serde_json::json!({"malformed":"cursor"})).await.unwrap();}
            let before=disk_records(directory.path());
            assert!(matches!(load_pending(&client,&store).await,Err(error) if error==local_record_invalid()));
            let candidate=data("44444444-4444-4444-8444-444444444444");
            let write=CompletionCheckpointWrite {owner:session.hashed_email.clone(),cache_key:key.clone(),master:session.master_key.clone(),value:serde_json::to_value(&candidate).unwrap(),job_id:candidate.job().job_id.clone(),digest:candidate.digest().unwrap(),store_generation:store.generation()};
            assert!(matches!(persist_checkpoint(&store,write).await,Err(error) if error==local_record_invalid()));
            assert!(matches!(clear_pending(&client,&store,&candidate.job().job_id).await,Err(error) if error==local_record_invalid()));
            for (suffix,fresh) in [("-continuation",false),("-fresh-continuation",true)] {
                let value=store.read_cache(session.hashed_email.clone(),format!("{key}{suffix}"),session.master_key.clone()).await.unwrap();
                assert_eq!(decode_continuation(value,fresh),Err(local_record_invalid()));
            }
            assert_eq!(disk_records(directory.path()),before);
            // Pump authenticates before touching malformed local records. This
            // real malformed HTTP reply stays network Protocol, not local-invalid.
            let error=pump_completion_recovery(&mut client,&store,CompletionRecoveryPumpOptions{selected_chat:None,max_attempts:2},&tokio_util::sync::CancellationToken::new(),&mut NoCanonical).await;
            assert!(matches!(error,Err(Error::Protocol)));peer.await.unwrap();
            assert_eq!(disk_records(directory.path()),before);
        }).await.unwrap();
    }
}

fn eligible_for_selected_chat(selected: Option<&str>, job: &crate::client::CompletionRecoveryJob) -> bool {
    selected.is_none_or(|id| id == job.chat_id)
}
#[cfg(test)]
#[path = "completion_recovery_selected_tests.rs"]
mod selected_tests;
