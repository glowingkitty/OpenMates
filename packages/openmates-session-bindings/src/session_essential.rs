//! Private essential draft: actual typed SDK calls; UNCOMPILED/UNRUN.
//! Storage remains caller-owned. Reading an iterator never acknowledges a write.
use super::*;
#[path = "session_startup_sync.rs"]
mod startup_sync;
pub use startup_sync::{PreparedInitialSyncOperation, InitialSyncOperationControl, InitialSyncMetadata};
use openmates_sdk::client::{
    ChatInvalidation, ChatMonitor, ChatMonitorAccessDenial, ChatPublication, ChatRefresh,
    ChatRefreshDurableReceipt, ChatSelectionUpdate, CompletionRecoveryAdmission,
    CompletionRecoveryCheckpoint, CompletionRecoveryDurableReceipt, CompletionRecoveryJob,
    CompletionRecoveryStage,
};
use tokio::sync::Mutex as AsyncMutex;
use zeroize::Zeroize;
const CAP: usize = 100;
const MAX_JSON: usize = 64 * 1024 * 1024;
fn decode<T: serde::de::DeserializeOwned>(encoded: String) -> Result<T> {
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > MAX_JSON {
        return Err(Error::Invalid("Essential input is too large.").into());
    }
    serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed essential input.").into())
}
fn encoded<T: Serialize>(value: &T) -> Result<String> {
    let mut output =
        serde_json::to_string(value).map_err(|_| BindingError::from(Error::Protocol))?;
    if output.len() > MAX_JSON {
        output.zeroize();
        return Err(Error::Invalid("Essential output is too large.").into());
    }
    Ok(output)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MonitorReceipt {
    ciphertext_sha256: String,
    credential_revision: u64,
}
pub(super) struct EssentialGuard {
    work: Arc<work::WorkGuard>,
    state: std::sync::Weak<State>,
    epoch: u64,
    recovery_epoch: Option<u64>,
}
impl EssentialGuard {
    pub(super) fn new(bridge: &SessionBridge, recovery: bool) -> Result<Arc<Self>> {
        let epoch = bridge.state.essential.epoch.load(Ordering::Acquire);
        let recovery_epoch = recovery.then(|| {
            bridge
                .state
                .essential
                .recovery_epoch
                .load(Ordering::Acquire)
        });
        let work = Arc::new(bridge.admit_work()?);
        let value = Arc::new(Self {
            work,
            state: Arc::downgrade(&bridge.state),
            epoch,
            recovery_epoch,
        });
        value.check()?;
        if recovery {
            let mut controls = bridge
                .state
                .essential
                .recovery_controls
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            value.check()?;
            controls.retain(|entry| entry.strong_count() > 0);
            controls.push(Arc::downgrade(&value));
        }
        Ok(value)
    }
    pub(super) fn check(&self) -> Result<()> {
        work::work_authority(&self.work)?;
        let state = self
            .state
            .upgrade()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        if self.epoch != state.essential.epoch.load(Ordering::Acquire)
            || self.recovery_epoch.is_some_and(|epoch| {
                epoch != state.essential.recovery_epoch.load(Ordering::Acquire)
            })
        {
            return Err(Error::Cancelled.into());
        }
        Ok(())
    }
    pub(super) fn token(&self) -> CancellationToken {
        self.work.token()
    }
    fn cancel(&self) {
        self.work.cancel();
    }
}
enum DeliveryKind {
    Open,
    Recovery,
    Refresh {
        monitor: Arc<Monitor>,
        id: String,
        cancel: CancellationToken,
    },
}
struct Delivery {
    state: std::sync::Weak<State>,
    guard: Arc<EssentialGuard>,
    kind: DeliveryKind,
    delivered: bool,
}
impl Delivery {
    fn new(state: &Arc<State>, guard: Arc<EssentialGuard>, kind: DeliveryKind) -> Self {
        Self {
            state: Arc::downgrade(state),
            guard,
            kind,
            delivered: false,
        }
    }
}
impl Drop for Delivery {
    fn drop(&mut self) {
        if self.delivered {
            return;
        }
        match &self.kind {
            DeliveryKind::Refresh {
                monitor,
                id,
                cancel,
            } => {
                cancel.cancel();
                let pending = monitor.refresh.lock().ok().and_then(|mut slot| {
                    if slot.as_ref().is_some_and(|entry| &entry.id == id) {
                        slot.take()
                    } else {
                        None
                    }
                });
                if let Some(pending) = pending {
                    let _ = monitor.core.requeue(pending.hint);
                }
            }
            DeliveryKind::Open => {
                self.guard.cancel();
                if let Some(state) = self.state.upgrade() {
                    state.essential.remove_monitor_owner(&self.guard);
                }
            }
            DeliveryKind::Recovery => {
                self.guard.cancel();
                if let Some(state) = self.state.upgrade() {
                    if let Ok(mut entries) = state.essential.recovery.lock() {
                        entries.retain(|_, entry| !Arc::ptr_eq(&entry.guard, &self.guard));
                    }
                    if let Ok(mut entries) = state.essential.jobs.lock() {
                        entries.retain(|_, entry| !Arc::ptr_eq(&entry.guard, &self.guard));
                    }
                }
            }
        }
    }
}
struct MonitorRefresh {
    id: String,
    value: ChatRefresh,
    digest: String,
    revision: u64,
    hint: ChatInvalidation,
    prefer_cache: bool,
}
struct Monitor {
    id: String,
    guard: Arc<EssentialGuard>,
    core: Arc<ChatMonitor>,
    hints: AsyncMutex<Option<ChatInvalidation>>,
    errors: AsyncMutex<mpsc::Receiver<Error>>,
    refresh: Mutex<Option<MonitorRefresh>>,
    reading: AtomicBool,
    refreshing: AtomicBool,
}
impl Monitor {
    fn valid(&self) -> Result<()> {
        self.guard.check()?;
        if !self.core.is_valid() {
            return Err(Error::Cancelled.into());
        }
        Ok(())
    }
    fn close(&self) {
        self.guard.cancel();
        self.core.close();
        if let Ok(mut pending) = self.refresh.lock() {
            pending.take();
        }
    }
}
struct Reading(Arc<Monitor>);
impl Drop for Reading {
    fn drop(&mut self) {
        self.0.reading.store(false, Ordering::Release);
    }
}
struct PendingHint {
    core: Arc<ChatMonitor>,
    value: Option<ChatInvalidation>,
}
impl Drop for PendingHint {
    fn drop(&mut self) {
        if let Some(hint) = self.value.take() {
            let _ = self.core.requeue(hint);
        }
    }
}
struct Refreshing(Arc<Monitor>);
impl Drop for Refreshing {
    fn drop(&mut self) {
        self.0.refreshing.store(false, Ordering::Release);
    }
}
enum MonitorSlot {
    Starting(Arc<EssentialGuard>),
    Active(Arc<Monitor>),
}
struct Job {
    value: CompletionRecoveryJob,
    guard: Arc<EssentialGuard>,
}
struct Recovery {
    value: Box<CompletionRecoveryStage>,
    guard: Arc<EssentialGuard>,
}
#[cfg(test)]
#[derive(Default)]
struct EnableGate {
    entered: tokio::sync::Notify,
    resume: tokio::sync::Notify,
    finished: tokio::sync::Notify,
}
#[cfg(test)]
struct GateFinished(Arc<EnableGate>);
#[cfg(test)]
impl Drop for GateFinished {
    fn drop(&mut self) {
        self.0.finished.notify_one();
    }
}
#[cfg(test)]
#[derive(Default)]
struct ReaperProbe {
    entered: tokio::sync::Notify,
    inspect: tokio::sync::Notify,
    removed: tokio::sync::Notify,
}
#[derive(Default)]
pub(super) struct Registry {
    #[cfg(test)]
    enable_gate: Mutex<Option<Arc<EnableGate>>>,
    #[cfg(test)]
    open_gate: Mutex<Option<Arc<EnableGate>>>,
    #[cfg(test)]
    enable_mutations: AtomicU64,
    #[cfg(test)]
    reaper_probe: Mutex<Option<Arc<ReaperProbe>>>,
    epoch: AtomicU64,
    recovery_epoch: AtomicU64,
    recovery_controls: Mutex<Vec<std::sync::Weak<EssentialGuard>>>,
    monitor: Mutex<Option<MonitorSlot>>,
    jobs: Mutex<BTreeMap<String, Job>>,
    recovery: Mutex<BTreeMap<String, Recovery>>,
    pub(super) cache_reads: super::cache_settlement::Registry,
    pub(super) first_pages: super::first_page::Registry,
}
impl Registry {
    // No Client lane is acquired here. The closure is a synchronous publication
    // under the same lock that protects Starting identity.
    fn publish_monitor_start<F>(&self, guard: &Arc<EssentialGuard>, publish: F) -> Result<()>
    where
        F: FnOnce(&mut Option<MonitorSlot>) -> Result<()>,
    {
        let mut slot = self
            .monitor
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        guard.check()?;
        if !matches!(slot.as_ref(), Some(MonitorSlot::Starting(owner)) if Arc::ptr_eq(owner, guard))
        {
            return Err(Error::Cancelled.into());
        }
        publish(&mut slot)
    }
    fn remove_monitor_owner(&self, guard: &Arc<EssentialGuard>) {
        let removed = if let Ok(mut slot) = self.monitor.lock() {
            let matches = match slot.as_ref() {
                Some(MonitorSlot::Starting(owner)) => Arc::ptr_eq(owner, guard),
                Some(MonitorSlot::Active(handle)) => Arc::ptr_eq(&handle.guard, guard),
                None => false,
            };
            if matches { slot.take() } else { None }
        } else {
            None
        };
        // Drop/close only our old handle, outside the registry lock.
        match removed {
            Some(MonitorSlot::Starting(owner)) => owner.cancel(),
            Some(MonitorSlot::Active(handle)) => handle.close(),
            None => {}
        }
    }

    fn monitor(&self, id: &str) -> Result<Arc<Monitor>> {
        let entries = self
            .monitor
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        match entries.as_ref() {
            Some(MonitorSlot::Active(value)) if value.id == id => Ok(value.clone()),
            _ => Err(Error::Cancelled.into()),
        }
    }
    pub(super) fn close_recovery(&self) {
        self.recovery_epoch.fetch_add(1, Ordering::AcqRel);
        let pending = if let Ok(mut controls) = self.recovery_controls.lock() {
            let pending = controls
                .iter()
                .filter_map(std::sync::Weak::upgrade)
                .collect::<Vec<_>>();
            controls.clear();
            pending
        } else {
            vec![]
        };
        for guard in pending {
            guard.cancel();
        }
        if let Ok(mut jobs) = self.jobs.lock() {
            for value in jobs.values() {
                value.guard.cancel();
            }
            jobs.clear();
        }
        if let Ok(mut stages) = self.recovery.lock() {
            for value in stages.values() {
                value.guard.cancel();
            }
            stages.clear();
        }
    }
    pub(super) fn close_all(&self) {
        self.epoch.fetch_add(1, Ordering::AcqRel);
        self.cache_reads.close_all();
        self.first_pages.close_all();
        if let Ok(mut monitor) = self.monitor.lock() {
            match monitor.take() {
                Some(MonitorSlot::Starting(guard)) => guard.cancel(),
                Some(MonitorSlot::Active(handle)) => handle.close(),
                None => {}
            }
        }
        self.close_recovery();
    }
}
impl Drop for Registry {
    fn drop(&mut self) {
        self.close_all();
    }
}
fn denial(handle: &Monitor) -> Result<Option<String>> {
    handle.guard.check()?;
    handle
        .core
        .access_denial()
        .map_err(BindingError::from)?
        .map(|value| {
            encoded(&match value {
                ChatMonitorAccessDenial::Expired => {
                    json!({"kind":"access_denial","reason":"expired"})
                }
                ChatMonitorAccessDenial::ScopeRevoked => {
                    json!({"kind":"access_denial","reason":"scope_revoked"})
                }
                ChatMonitorAccessDenial::ChatUnavailable { chat_id } => {
                    json!({"kind":"access_denial","reason":"chat_unavailable","chat_id":chat_id})
                }
            })
        })
        .transpose()
}
fn prepare_publication(
    client: &mut Client,
    value: ChatRefresh,
    receipt: MonitorReceipt,
    #[cfg(test)] probe: (&EssentialGuard, &super::cache_settlement::Registry),
) -> Result<(Zeroizing<String>, ChatPublication)> {
    client
        .validate_chat_refresh(&value)
        .map_err(BindingError::from)?;
    client
        .acknowledge_credentials(receipt.credential_revision)
        .map_err(BindingError::from)?;
    let publication = client
        .commit_chat_refresh(
            value,
            ChatRefreshDurableReceipt {
                ciphertext_sha256: receipt.ciphertext_sha256,
                credential_revision: receipt.credential_revision,
            },
        )
        .map_err(BindingError::from)?;
    let models = publication.models().map_err(BindingError::from)?;
    // Borrow every plaintext field directly; json! would allocate intermediate
    // owned Values whose plaintext drops would not be wiped.
    #[derive(Serialize)]
    #[serde(tag = "kind", rename_all = "snake_case")]
    enum Selection<'a> {
        Unchanged,
        Updated { chat: &'a openmates_sdk::model::Chat },
        CacheSettled { chat: &'a openmates_sdk::model::Chat, history_complete: bool, pii_restoration: &'static str },
        Unavailable { chat_id: &'a str },
    }
    #[derive(Serialize)]
    struct Output<'a, T: Serialize> { items: &'a [T], selection: Selection<'a> }
    let selection = match &models.selection {
        ChatSelectionUpdate::Unchanged => Selection::Unchanged,
        ChatSelectionUpdate::Updated(chat) => Selection::Updated { chat },
        ChatSelectionUpdate::CacheSettled(chat) => Selection::CacheSettled {
            chat, history_complete: false, pii_restoration: "all_cached_user_rows",
        },
        ChatSelectionUpdate::Unavailable { chat_id } => Selection::Unavailable { chat_id },
    };
    let mut output = Zeroizing::new(encoded(&Output { items: models.items.as_slice(), selection })?);
    #[cfg(test)]
    if probe.1.cancel_monitor_after_encode.swap(false, Ordering::AcqRel) { probe.0.token().cancel(); }
    if let Err(error) = client.validate_chat_publication(&publication) {
        output.zeroize();
        #[cfg(test)] probe.1.monitor_output_wiped.store(output.is_empty(), Ordering::Release);
        return Err(error.into());
    }
    Ok((output, publication))
}
fn release_encoded(guard: &EssentialGuard, output: &mut String) -> Result<String> {
    if let Err(error) = guard.check() {
        output.zeroize();
        return Err(error);
    }
    work::release_work_output(&guard.work, output)
}
fn release(guard: &EssentialGuard, output: Result<String>) -> Result<String> {
    let mut output = output?;
    release_encoded(guard, &mut output)
}
impl SessionBridge {
    pub async fn chat_monitor_open(&self) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.chat_monitor_open_admitted(guard).await
    }
    async fn chat_monitor_open_admitted(&self, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        let mut delivery = Delivery::new(&self.state, guard.clone(), DeliveryKind::Open);
        {
            let mut slot = self
                .state
                .essential
                .monitor
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            guard.check()?;
            if slot.is_some() {
                return Err(Error::Conflict.into());
            }
            *slot = Some(MonitorSlot::Starting(guard.clone()));
        }
        let state = self.state.clone();
        let worker_guard = guard.clone();
        let result = self
            .transaction(async move {
                let (errors, receiver) = mpsc::channel(1);
                #[cfg(test)]
                let _finished = {
                    let gate = state.essential.open_gate.lock().map_err(|_| BindingError::from(Error::Protocol))?.clone();
                    if let Some(gate) = gate {
                        gate.entered.notify_one();
                        gate.resume.notified().await;
                        Some(GateFinished(gate))
                    } else { None }
                };

                let mut client = Self::live_client(&state).await?;
                worker_guard.check()?;
                client.set_operation_cancel(worker_guard.token());
                let core = client
                    .start_chat_monitor(worker_guard.token(), errors)
                    .await
                    .map_err(BindingError::from)?;
                let handle = Arc::new(Monitor {
                    id: uuid::Uuid::new_v4().to_string(),
                    guard: worker_guard,
                    core: Arc::new(core),
                    hints: AsyncMutex::new(None),
                    errors: AsyncMutex::new(receiver),
                    refresh: Mutex::new(None),
                    reading: AtomicBool::new(false),
                    refreshing: AtomicBool::new(false),
                });
                if let Err(error) = state.essential.publish_monitor_start(&handle.guard, |slot| {
                    handle.valid()?;
                    *slot = Some(MonitorSlot::Active(handle.clone()));
                    Ok(())
                }) {
                    handle.close();
                    return Err(error);
                }
                let credentials = client.credential_snapshot().ok_or(Error::Authentication).map_err(BindingError::from)?;
                let account = client.user()["id"].as_str().or_else(||client.user()["user_id"].as_str()).filter(|id|!id.is_empty()).ok_or(Error::Authentication).map_err(BindingError::from)?;
                encoded(&json!({"id":handle.id,"scope":{"api_url":credentials.session.api_url.clone(),"account_id":account,"team_id":credentials.session.active_team_id}}))
            })
            .await;
        if result.is_err() {
            self.state.essential.remove_monitor_owner(&guard);
        }
        let output = release(&guard, result)?;
        delivery.delivered = true;
        Ok(output)
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_chat_monitor_open(&self) -> impl Future<Output = Result<String>> + Send + 'static {
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.chat_monitor_open_admitted(guard).await
        }
    }

    pub fn chat_monitor_close(&self, id: String) -> Result<()> {
        let mut slot = self
            .state
            .essential
            .monitor
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        let selected = match slot.as_ref() {
            Some(MonitorSlot::Active(value)) if value.id == id => Some(value.clone()),
            _ => None,
        };
        if let Some(handle) = selected {
            slot.take();
            drop(slot);
            handle.close();
        }
        Ok(())
    }
    pub fn chat_monitor_access_denial(&self, id: String) -> Result<String> {
        let handle = self.state.essential.monitor(&id)?;
        handle.guard.check()?;
        denial(&handle).and_then(|value| value.map_or_else(|| Ok("null".into()), Ok))
    }
    pub async fn chat_monitor_next(&self, id: String) -> Result<String> {
        let handle = self.state.essential.monitor(&id)?;
        handle.guard.check()?;
        if let Some(event) = denial(&handle)? {
            return Ok(event);
        }
        handle.valid()?;
        if handle.reading.swap(true, Ordering::AcqRel) {
            return Err(Error::Conflict.into());
        }
        let reading = Reading(handle.clone());
        let operation = async {
            let mut hints = handle.hints.lock().await;
            if hints.is_some() {
                return Err(Error::Conflict.into());
            }
            let mut errors = handle.errors.lock().await;
            let cancelled = handle.guard.token();
            tokio::select! { biased;
                _ = cancelled.cancelled() => return Err(Error::Cancelled.into()),
                error = errors.recv() => return Err(error.unwrap_or(Error::Cancelled).into()),
                ready = handle.core.changed() => ready.map_err(BindingError::from)?,
            }
            handle.valid()?;
            let hint = handle
                .core
                .take_pending()
                .map_err(BindingError::from)?
                .ok_or(Error::Conflict)
                .map_err(BindingError::from)?;
            let recovery_chats = hint.recovery_chats().map(str::to_owned).collect::<Vec<_>>();
            *hints = Some(hint);
            encoded(&json!({"kind":"invalidation","recovery_chat_ids":recovery_chats}))
        }
        .await;
        drop(reading);
        if operation.is_err() {
            if let Some(event) = denial(&handle)? {
                return release(&handle.guard, Ok(event));
            }
        }
        let mut output = release(&handle.guard, operation)?;
        if let Err(error) = handle.valid() {
            output.zeroize();
            return Err(error);
        }
        Ok(output)
    }
    pub async fn chat_monitor_validate(&self, id: String) -> Result<()> {
        let handle = self.state.essential.monitor(&id)?;
        handle.valid()?;
        let state = self.state.clone();
        let worker = handle.clone();
        self.transaction(async move {
            let mut client = Self::live_client(&state).await?;
            worker.valid()?;
            client.set_operation_cancel(worker.guard.token());
            client
                .validate_chat_monitor(&worker.core)
                .await
                .map_err(BindingError::from)
        })
        .await?;
        handle.valid()
    }
    pub async fn chat_monitor_stage(
        &self,
        id: String,
        selected: Option<String>,
        include_secrets: bool,
    ) -> Result<String> {
        self.chat_monitor_stage_policy(id, selected, include_secrets, false).await
    }
    /// Explicit cache preference; existing strict stage remains unchanged.
    pub async fn chat_monitor_stage_prefer_cache(
        &self, id: String, selected: Option<String>, include_secrets: bool,
    ) -> Result<String> {
        self.chat_monitor_stage_policy(id, selected, include_secrets, true).await
    }
    async fn chat_monitor_stage_policy(
        &self, id: String, selected: Option<String>, include_secrets: bool, prefer_cache: bool,
    ) -> Result<String> {
        if !include_secrets {
            return Err(Error::Invalid("Explicit credential storage consent is required.").into());
        }
        let handle = self.state.essential.monitor(&id)?;
        handle.valid()?;
        if handle.refreshing.swap(true, Ordering::AcqRel) {
            return Err(Error::Conflict.into());
        }
        let _refreshing = Refreshing(handle.clone());
        if handle
            .refresh
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .is_some()
        {
            return Err(Error::Conflict.into());
        }
        let hint = handle
            .hints
            .lock()
            .await
            .take()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        let state = self.state.clone();
        let worker = handle.clone();
        let stage_id = uuid::Uuid::new_v4().to_string();
        let cancel = handle.guard.token().child_token();
        let mut delivery = Delivery::new(
            &self.state,
            handle.guard.clone(),
            DeliveryKind::Refresh {
                monitor: handle.clone(),
                id: stage_id.clone(),
                cancel: cancel.clone(),
            },
        );
        let pending_hint = PendingHint {
            core: worker.core.clone(),
            value: Some(hint),
        };
        let result = self.transaction(async move {
            let mut pending_hint = pending_hint;
            let mut client = Self::live_client(&state).await?; worker.valid()?;
            if cancel.is_cancelled() { return Err(Error::Cancelled.into()); }
            client.set_operation_cancel(cancel.clone());
            let hint = pending_hint.value.as_ref().ok_or(Error::Conflict).map_err(BindingError::from)?;
            let refresh = if prefer_cache {
                client.refresh_chat_monitor_prefer_cache(&worker.core, hint, selected.as_deref()).await
            } else {
                client.refresh_chat_monitor(&worker.core, hint, selected.as_deref()).await
            }.map_err(BindingError::from)?;
            let digest = refresh.ciphertext_sha256().map_err(BindingError::from)?;
            let revision = refresh.credential_revision();
            let credentials = client.credential_snapshot().ok_or(Error::Authentication).map_err(BindingError::from)?;
            if credentials.revision != revision { return Err(Error::Cancelled.into()); }
            let account = client.user()["id"].as_str().or_else(||client.user()["user_id"].as_str()).filter(|id|!id.is_empty()).ok_or(Error::Authentication).map_err(BindingError::from)?.to_owned();
            let output = Zeroizing::new(encoded(&json!({"id":stage_id,"scope":{"api_url":credentials.session.api_url.clone(),"account_id":account,"team_id":credentials.session.active_team_id.clone()},
                "checkpoint_json":encoded(refresh.ciphertext_snapshot().map_err(BindingError::from)?)?,"ciphertext_sha256":digest,
                "credential_revision":revision,"credentials_json":encoded(&json!({"revision":credentials.revision,"session":credentials.session}))?}))?);
            worker.valid()?;
            let mut slot = worker.refresh.lock().map_err(|_| BindingError::from(Error::Protocol))?;
            if cancel.is_cancelled() { return Err(Error::Cancelled.into()); }
            if slot.is_some() { return Err(Error::Conflict.into()); }
            *slot = Some(MonitorRefresh { id:stage_id,value:refresh,digest,revision,hint:pending_hint.value.take().ok_or(Error::Conflict).map_err(BindingError::from)?,prefer_cache });
            Ok(output)
        }).await;
        let mut output = result?;
        handle.guard.check()?;
        if let Err(error) = handle.valid() {
            output.zeroize();
            return Err(error);
        }
        let output = release_encoded(&handle.guard, &mut output)?;
        delivery.delivered = true;
        Ok(output)
    }
    pub fn chat_monitor_discard(&self, id: String, stage_id: String) -> Result<()> {
        let handle = self.state.essential.monitor(&id)?;
        let mut slot = handle
            .refresh
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        if !slot.as_ref().is_some_and(|stage| stage.id == stage_id) {
            return Err(Error::Conflict.into());
        }
        let pending = slot
            .take()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        handle.valid()?;
        handle
            .core
            .requeue(pending.hint)
            .map_err(BindingError::from)
    }
    pub async fn chat_monitor_commit(
        &self,
        id: String,
        stage_id: String,
        receipt: String,
    ) -> Result<String> {
        let receipt: MonitorReceipt = decode(receipt)?;
        let handle = self.state.essential.monitor(&id)?;
        handle.valid()?;
        let stage = {
            let mut slot = handle
                .refresh
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if !slot.as_ref().is_some_and(|stage| {
                stage.id == stage_id
                    && stage.digest == receipt.ciphertext_sha256
                    && stage.revision == receipt.credential_revision
            }) {
                return Err(Error::Conflict.into());
            }
            slot.take()
                .ok_or(Error::Conflict)
                .map_err(BindingError::from)?
        };
        let state = self.state.clone();
        let worker = handle.clone();
        let joined = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                worker.valid()?;
                // Cache refresh captured its exact operation child at stage.
                // Rebinding would cancel it and could disrupt successor work.
                if !stage.prefer_cache { client.set_operation_cancel(worker.guard.token()); }
                let MonitorRefresh { value, hint, .. } = stage;
                match prepare_publication(&mut client, value, receipt,
                    #[cfg(test)] (&worker.guard, &state.essential.cache_reads),
                ) {
                    Ok((output, publication)) => Ok((output, publication, hint)),
                    Err(error) => {
                        if worker.valid().is_ok() {
                            let _ = worker.core.requeue(hint);
                        }
                        Err(error)
                    }
                }
            })
            .await?;
        let (mut output, publication, hint) = joined;
        // Retain current Client ownership through the actual return expression,
        // including the original publication check and final guard release.
        let client = match Self::live_client(&self.state).await {
            Ok(client) => client,
            Err(error) => {
                if handle.valid().is_ok() { let _ = handle.core.requeue(hint); }
                output.zeroize();
                return Err(error);
            }
        };
        let check = handle.valid()
            .and_then(|_| client.validate_chat_publication(&publication).map_err(BindingError::from))
            .and_then(|_| handle.guard.check());
        if let Err(error) = check {
            if handle.valid().is_ok() {
                let _ = handle.core.requeue(hint);
            }
            output.zeroize();
            return Err(error);
        }
        release_encoded(&handle.guard, &mut output)
    }
    pub async fn completion_recovery_enable(&self, enabled: bool) -> Result<()> {
        self.state.essential.close_recovery();
        let guard = EssentialGuard::new(self, true)?;
        self.completion_recovery_enable_admitted(enabled, guard).await
    }
    async fn completion_recovery_enable_admitted(&self, enabled: bool, guard: Arc<essential::EssentialGuard>) -> Result<()> {
        guard.check()?;
        let worker = guard.clone();
        let state = self.state.clone();
        self.transaction(async move {
            worker.check()?;
            #[cfg(test)]
            if enabled {
                let gate = state
                    .essential
                    .enable_gate
                    .lock()
                    .map_err(|_| BindingError::from(Error::Protocol))?
                    .clone();
                if let Some(gate) = gate {
                    gate.entered.notify_one();
                    gate.resume.notified().await;
                }
            }
            let mut client = Self::live_client(&state).await?;
            worker.check()?;
            #[cfg(test)]
            state
                .essential
                .enable_mutations
                .fetch_add(1, Ordering::AcqRel);
            client
                .set_foreground_completion_recovery(enabled)
                .map_err(BindingError::from)
        })
        .await?;
        guard.check()
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_completion_recovery_enable(&self, enabled: bool) -> impl Future<Output = Result<()>> + Send + 'static {
        let original = (|| { self.available()?; self.state.essential.close_recovery(); essential::EssentialGuard::new(self, true) })();
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.completion_recovery_enable_admitted(enabled, guard).await
        }
    }

    pub async fn completion_recovery_jobs(&self) -> Result<String> {
        self.completion_recovery_discover(None).await
    }
    /// Exact selected discovery; never global inventory or list TTL authority.
    pub async fn completion_recovery_jobs_for_chat(&self, chat_id: String) -> Result<String> {
        self.completion_recovery_discover(Some(chat_id)).await
    }
    async fn completion_recovery_discover(&self, selected: Option<String>) -> Result<String> {
        let guard = EssentialGuard::new(self, true)?;
        self.completion_recovery_discover_admitted(selected, guard).await
    }
    async fn completion_recovery_discover_admitted(&self, selected: Option<String>, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        let mut delivery = Delivery::new(&self.state, guard.clone(), DeliveryKind::Recovery);
        let worker = guard.clone();
        let state = self.state.clone();
        let result = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                worker.check()?;
                client.set_operation_cancel(worker.token());
                let found = if let Some(chat_id) = selected.as_deref() {
                    client.completion_recovery_jobs_for_chat(chat_id, &worker.token()).await
                } else {
                    client.completion_recovery_jobs(&worker.token()).await
                }.map_err(BindingError::from)?;
                if found.len() > CAP {
                    return Err(Error::Protocol.into());
                }
                let mut jobs = state
                    .essential
                    .jobs
                    .lock()
                    .map_err(|_| BindingError::from(Error::Protocol))?;
                worker.check()?;
                replace_discovered_selection(&mut jobs, selected.as_deref(), found.len())?;
                let mut output = vec![];
                for value in found {
                    let id = uuid::Uuid::new_v4().to_string();
                    output.push(json!({"id":id,"job":value}));
                    jobs.insert(
                        id,
                        Job {
                            value,
                            guard: worker.clone(),
                        },
                    );
                }
                encoded(&output)
            })
            .await;
        let output = release(&guard, result)?;
        delivery.delivered = true;
        Ok(output)
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_completion_recovery_discover(&self, selected: Option<String>) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut selected = Zeroizing::new(selected);
        let original = essential::EssentialGuard::new(self, true);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.completion_recovery_discover_admitted(std::mem::take(&mut *selected), guard).await
        }
    }

    pub async fn completion_recovery_stage(&self, id: String) -> Result<String> {
        let job = self
            .state
            .essential
            .jobs
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .remove(&id)
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        job.guard.check()?;
        let guard = EssentialGuard::new(self, true)?;
        let mut delivery = Delivery::new(&self.state, guard.clone(), DeliveryKind::Recovery);
        let worker = guard.clone();
        let state = self.state.clone();
        let result = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                worker.check()?;
                client.set_operation_cancel(worker.token());
                let admission = client
                    .stage_completion_recovery(&job.value, &worker.token())
                    .await
                    .map_err(BindingError::from)?;
                admission_output(&state, worker, admission)
            })
            .await;
        let output = release(&guard, result)?;
        delivery.delivered = true;
        Ok(output)
    }
    pub async fn completion_recovery_resume(&self, checkpoint: String) -> Result<String> {
        let checkpoint: CompletionRecoveryCheckpoint = decode(checkpoint)?;
        let guard = EssentialGuard::new(self, true)?;
        let mut delivery = Delivery::new(&self.state, guard.clone(), DeliveryKind::Recovery);
        let worker = guard.clone();
        let state = self.state.clone();
        let result = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                worker.check()?;
                client.set_operation_cancel(worker.token());
                let admission = client
                    .resume_completion_recovery(checkpoint, &worker.token())
                    .await
                    .map_err(BindingError::from)?;
                admission_output(&state, worker, admission)
            })
            .await;
        let output = release(&guard, result)?;
        delivery.delivered = true;
        Ok(output)
    }
    pub fn completion_recovery_discard(&self, id: String) -> Result<()> {
        if let Some(stage) = self
            .state
            .essential
            .recovery
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .remove(&id)
        {
            stage.guard.cancel();
        }
        Ok(())
    }
    pub async fn completion_recovery_commit(&self, id: String, receipt: String) -> Result<String> {
        let receipt: CompletionRecoveryDurableReceipt = decode(receipt)?;
        let stage = self
            .state
            .essential
            .recovery
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .remove(&id)
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        let guard = stage.guard;
        guard.check()?;
        let worker = guard.clone();
        let state = self.state.clone();
        let result = self
            .transaction(async move {
                let mut client = Self::live_client(&state).await?;
                worker.check()?;
                client.set_operation_cancel(worker.token());
                let result = client
                    .commit_completion_recovery(*stage.value, receipt, &worker.token())
                    .await
                    .map_err(BindingError::from)?;
                encoded(&result)
            })
            .await;
        release(&guard, result)
    }
}
fn admission_output(
    state: &Arc<State>,
    guard: Arc<EssentialGuard>,
    admission: CompletionRecoveryAdmission,
) -> Result<String> {
    guard.check()?;
    match admission {
        CompletionRecoveryAdmission::Deferred => encoded(&json!({"kind":"deferred"})),
        CompletionRecoveryAdmission::Canonical(receipt) => {
            encoded(&json!({"kind":"canonical","receipt":receipt}))
        }
        CompletionRecoveryAdmission::Ready(value) => {
            let checkpoint = value.checkpoint().map_err(BindingError::from)?;
            let digest = checkpoint.digest().map_err(BindingError::from)?;
            let id = uuid::Uuid::new_v4().to_string();
            let output = encoded(
                &json!({"kind":"ready","id":id,"checkpoint_json":encoded(&checkpoint)?,"checkpoint_sha256":digest}),
            )?;
            let mut stages = state
                .essential
                .recovery
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            guard.check()?;
            if stages.len() >= CAP {
                return Err(Error::Conflict.into());
            }
            stages.insert(id.clone(), Recovery { value, guard });
            let weak = Arc::downgrade(state);
            #[cfg(test)]
            let probe = state
                .essential
                .reaper_probe
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?
                .clone();
            tokio::spawn(async move {
                loop {
                    #[cfg(test)]
                    if let Some(probe) = &probe {
                        probe.entered.notify_one();
                        probe.inspect.notified().await;
                    } else {
                        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    }
                    #[cfg(not(test))]
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    let Some(state) = weak.upgrade() else {
                        break;
                    };
                    let Ok(mut stages) = state.essential.recovery.lock() else {
                        break;
                    };
                    let Some(stage) = stages.get(&id) else {
                        break;
                    };
                    if stage.guard.check().is_err() || stage.value.checkpoint().is_err() {
                        if let Some(stage) = stages.remove(&id) {
                            stage.guard.cancel();
                            drop(stage);
                        }
                        #[cfg(test)]
                        if let Some(probe) = &probe {
                            probe.removed.notify_one();
                        }
                        break;
                    }
                }
            });
            Ok(output)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn bridge() -> SessionBridge {
        SessionBridge::new(&json!({"api_url":"http://127.0.0.1:1","enhanced_privacy":false,"allow_private_operations":true}).to_string()).ok().unwrap()
    }
    #[test]
    fn team_or_owner_intent_invalidates_inflight_guard_before_registry_publication() {
        let bridge = bridge();
        let guard = EssentialGuard::new(&bridge, false).ok().unwrap();
        bridge.state.essential.close_all();
        assert!(guard.check().is_err());
    }
    #[test]
    fn recovery_disable_does_not_revoke_unrelated_monitor_admission() {
        let bridge = bridge();
        let monitor = EssentialGuard::new(&bridge, false).ok().unwrap();
        let recovery = EssentialGuard::new(&bridge, true).ok().unwrap();
        bridge.state.essential.close_recovery();
        assert!(recovery.check().is_err());
        assert!(recovery.token().is_cancelled());
        assert!(monitor.check().is_ok());
    }
    #[test]
    fn opaque_registry_guard_does_not_cycle_or_retain_client_after_last_owner_drop() {
        let bridge = bridge();
        let weak = Arc::downgrade(&bridge.state);
        let guard = EssentialGuard::new(&bridge, false).ok().unwrap();
        let token = guard.token();
        *bridge.state.essential.monitor.lock().ok().unwrap() = Some(MonitorSlot::Starting(guard));
        drop(bridge);
        assert!(weak.upgrade().is_none());
        assert!(token.is_cancelled());
    }
    #[test]
    fn rejected_serialized_foreign_return_is_wiped_after_lifecycle_change() {
        let bridge = bridge();
        let guard = EssentialGuard::new(&bridge, false).ok().unwrap();
        bridge.state.essential.close_all();
        let mut encoded = "synthetic-private-return".to_owned();
        assert!(release_encoded(&guard, &mut encoded).is_err());
        assert!(encoded.is_empty());
    }
    #[tokio::test]
    async fn old_monitor_admission_cannot_overwrite_reopened_slot_or_publish_private_output() {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            let bridge = bridge();
            let old = EssentialGuard::new(&bridge, false).ok().unwrap();
            *bridge.state.essential.monitor.lock().ok().unwrap() =
                Some(MonitorSlot::Starting(old.clone()));
            let (ready_tx, ready_rx) = tokio::sync::oneshot::channel();
            let (resume_tx, resume_rx) = tokio::sync::oneshot::channel();
            let state = bridge.state.clone();
            let stale = old.clone();
            let private_published = Arc::new(AtomicBool::new(false));
            let publication = private_published.clone();
            let worker = tokio::spawn(async move {
                stale.check()?;
                ready_tx.send(()).ok();
                resume_rx
                    .await
                    .map_err(|_| BindingError::from(Error::Cancelled))?;
                state.essential.publish_monitor_start(&stale, |_| {
                    publication.store(true, Ordering::Release);
                    Ok(())
                })
            });
            ready_rx.await.ok().unwrap();
            bridge.state.essential.close_all();
            let fresh = EssentialGuard::new(&bridge, false).ok().unwrap();
            *bridge.state.essential.monitor.lock().ok().unwrap() =
                Some(MonitorSlot::Starting(fresh.clone()));
            resume_tx.send(()).ok().unwrap();
            assert!(worker.await.ok().unwrap().is_err());
            bridge.state.essential.remove_monitor_owner(&old);
            assert!(!private_published.load(Ordering::Acquire));
            assert!(
                bridge
                    .state
                    .essential
                    .publish_monitor_start(&fresh, |_| Ok(()))
                    .is_ok()
            );
        })
        .await
        .ok()
        .unwrap();
    }
    #[tokio::test]
    async fn late_recovery_enable_cannot_undo_newer_disable_after_client_admission() {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            let bridge = bridge();
            let gate = Arc::new(EnableGate::default());
            *bridge.state.essential.enable_gate.lock().ok().unwrap() = Some(gate.clone());
            let old = bridge.clone();
            let worker = tokio::spawn(async move { old.completion_recovery_enable(true).await });
            gate.entered.notified().await;
            // A newer disable enters the real Client lane and succeeds without
            // a Cookie; the older enable must fail before require_session().
            assert!(bridge.completion_recovery_enable(false).await.is_ok());
            assert_eq!(
                bridge
                    .state
                    .essential
                    .enable_mutations
                    .load(Ordering::Acquire),
                1
            );
            gate.resume.notify_one();
            let error = worker.await.ok().unwrap().err().unwrap();
            assert_eq!(error.code, "cancelled");
            assert_eq!(
                bridge
                    .state
                    .essential
                    .enable_mutations
                    .load(Ordering::Acquire),
                1
            );
        })
        .await
        .ok()
        .unwrap();
    }
    #[test]
    fn abandoned_open_cleans_only_its_admission_and_rejects_detached_completion() {
        let bridge = bridge();
        let old = EssentialGuard::new(&bridge, false).ok().unwrap();
        *bridge.state.essential.monitor.lock().ok().unwrap() =
            Some(MonitorSlot::Starting(old.clone()));
        let delivery = Delivery::new(&bridge.state, old.clone(), DeliveryKind::Open);
        drop(delivery);
        assert!(
            bridge
                .state
                .essential
                .monitor
                .lock()
                .ok()
                .unwrap()
                .is_none()
        );
        let fresh = EssentialGuard::new(&bridge, false).ok().unwrap();
        *bridge.state.essential.monitor.lock().ok().unwrap() =
            Some(MonitorSlot::Starting(fresh.clone()));
        assert!(
            bridge
                .state
                .essential
                .publish_monitor_start(&old, |_| panic!("stale completion"))
                .is_err()
        );
        bridge.state.essential.remove_monitor_owner(&old);
        assert!(
            bridge
                .state
                .essential
                .publish_monitor_start(&fresh, |_| Ok(()))
                .is_ok()
        );
    }
    #[test]
    fn abandoned_recovery_delivery_cancels_and_releases_only_own_discovery() {
        let bridge = bridge();
        let old = EssentialGuard::new(&bridge, true).ok().unwrap();
        let fresh = EssentialGuard::new(&bridge, true).ok().unwrap();
        let job: CompletionRecoveryJob = serde_json::from_value(json!({"kind":"main","job_id":"44444444-4444-4444-8444-444444444444","chat_id":"22222222-2222-4222-8222-222222222222","turn_id":null,"assistant_message_id":null,"task_id":null,"stage":null,"chat_key_version":1})).ok().unwrap();
        bridge.state.essential.jobs.lock().ok().unwrap().insert(
            "old".into(),
            Job {
                value: job.clone(),
                guard: old.clone(),
            },
        );
        bridge.state.essential.jobs.lock().ok().unwrap().insert(
            "fresh".into(),
            Job {
                value: job,
                guard: fresh.clone(),
            },
        );
        drop(Delivery::new(
            &bridge.state,
            old.clone(),
            DeliveryKind::Recovery,
        ));
        let entries = bridge.state.essential.jobs.lock().ok().unwrap();
        assert!(!entries.contains_key("old"));
        assert!(entries.contains_key("fresh"));
        assert!(old.token().is_cancelled());
        assert!(fresh.check().is_ok());
    }
    #[tokio::test]
    async fn dropped_real_open_future_reclaims_its_starting_slot_before_detached_worker_resumes() {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            let bridge = bridge();
            let gate = Arc::new(EnableGate::default());
            *bridge.state.essential.open_gate.lock().ok().unwrap() = Some(gate.clone());
            let caller = bridge.clone();
            let pending = tokio::spawn(async move { caller.chat_monitor_open().await });
            gate.entered.notified().await;
            pending.abort();
            assert!(pending.await.err().unwrap().is_cancelled());
            assert!(
                bridge
                    .state
                    .essential
                    .monitor
                    .lock()
                    .ok()
                    .unwrap()
                    .is_none()
            );
            let fresh = EssentialGuard::new(&bridge, false).ok().unwrap();
            *bridge.state.essential.monitor.lock().ok().unwrap() =
                Some(MonitorSlot::Starting(fresh.clone()));
            gate.resume.notify_one();
            gate.finished.notified().await;
            assert!(
                bridge
                    .state
                    .essential
                    .publish_monitor_start(&fresh, |_| Ok(()))
                    .is_ok()
            );
        })
        .await
        .ok()
        .unwrap();
    }
}

#[cfg(test)]
#[path = "session_essential/reclamation_tests.rs"]
mod reclamation_tests;

// Bounded registry admission precedes mutation. Quota refusal preserves ALL old
// handles; successful selected replacement touches only its original selection.
fn replace_discovered_selection(jobs: &mut BTreeMap<String, Job>, selected: Option<&str>, found: usize) -> Result<()> {
    let retained = selected.map_or(0, |chat| jobs.values().filter(|entry|entry.value.chat_id != chat).count());
    if retained.checked_add(found).is_none_or(|count|count > CAP) { return Err(Error::Protocol.into()); }
    if let Some(chat)=selected { jobs.retain(|_,entry|entry.value.chat_id != chat); } else { jobs.clear(); }
    Ok(())
}
#[cfg(test)]
#[path = "session_essential/selected_tests.rs"]
mod selected_tests;
