//! Explicit initial startup over the original authenticated monitor. No CLI,
//! row DTO, caller count, physical-store receipt or full-hint ACK authority.
use super::*;
use openmates_sdk::client::InitialSyncMetadataBatch;

struct Start { bridge: SessionBridge, guard: Arc<EssentialGuard>, monitor: Arc<Monitor> }
/// Captured synchronously before foreign scheduling; consumed once by run.
pub struct PreparedInitialSyncOperation { start: Option<Start> }
/// This control can only revoke its original request.
pub struct InitialSyncOperationControl(Arc<EssentialGuard>);
impl InitialSyncOperationControl { pub fn cancel(&self) { self.0.cancel(); } }
impl Drop for PreparedInitialSyncOperation {
    fn drop(&mut self) { if let Some(start) = &self.start { start.guard.cancel(); } }
}
impl PreparedInitialSyncOperation {
    pub fn control(&self) -> InitialSyncOperationControl {
        InitialSyncOperationControl(self.start.as_ref().expect("unconsumed original startup").guard.clone())
    }
    pub async fn run(mut self) -> Result<InitialSyncMetadata> {
        let start = self.start.take().ok_or(Error::Conflict).map_err(BindingError::from)?;
        let bridge = start.bridge.clone();
        // The detached task retains this original until actual actor IO ends.
        // Err/Drop never grants storage, global settlement or ACK authority.
        bridge.transaction(async move {
            start.guard.check()?;
            start.monitor.valid()?;
            let pending = {
                let client = start.bridge.state.client.lock().await;
                start.guard.check()?;
                start.monitor.valid()?;
                client.prepare_initial_sync(start.monitor.core.clone(), start.guard.token()).map_err(BindingError::from)?
            };
            // No Client/auth lock is held across socket IO.
            let read = pending.wait().await.map_err(BindingError::from)?;
            let client = start.bridge.state.client.lock().await;
            start.guard.check()?;
            start.monitor.valid()?;
            let batch = read.retain(&client).map_err(BindingError::from)?;
            start.guard.check()?;
            drop(client);
            Ok(InitialSyncMetadata { inner: Arc::new(Metadata {
                bridge: start.bridge, guard: start.guard, monitor: start.monitor,
                batch: Mutex::new(Some(batch)),
            }) })
        }).await
    }
}
struct Metadata {
    bridge: SessionBridge,
    guard: Arc<EssentialGuard>,
    monitor: Arc<Monitor>,
    batch: Mutex<Option<InitialSyncMetadataBatch>>,
}
impl Drop for Metadata {
    fn drop(&mut self) {
        self.guard.cancel();
        if let Ok(slot) = self.batch.get_mut() { if let Some(batch) = slot.take() { batch.cancel(); } }
    }
}
/// Aliases retain the same original batch; no row getter, replacement Client,
/// constructor, serde, native commit or ACK method is exposed.
#[derive(Clone)]
pub struct InitialSyncMetadata { inner: Arc<Metadata> }
impl InitialSyncMetadata {
    pub fn cancel(&self) { self.inner.guard.cancel(); }
    /// Observed DATA only, never authoritative account total or store readiness.
    pub async fn received_metadata_count(&self) -> Result<u32> {
        self.inner.guard.check()?;
        self.inner.monitor.valid()?;
        let client = self.inner.bridge.state.client.lock().await;
        self.inner.guard.check()?;
        self.inner.monitor.valid()?;
        let slot = self.inner.batch.lock().map_err(|_| BindingError::from(Error::Protocol))?;
        let count = slot.as_ref().ok_or(Error::Cancelled).map_err(BindingError::from)?
            .received_metadata_count(&client).map_err(BindingError::from)?;
        self.inner.guard.check()?;
        u32::try_from(count).map_err(|_| Error::Protocol.into())
    }
}
impl SessionBridge {
    /// id selects only this Bridge's genuine registered monitor, never an
    /// arbitrary caller root, account key, intent/status or readiness DTO.
    pub fn prepare_initial_sync(&self, id: String) -> Result<PreparedInitialSyncOperation> {
        let guard = EssentialGuard::new(self, false)?;
        let monitor = self.state.essential.monitor(&id)?;
        guard.check()?;
        monitor.valid()?;
        Ok(PreparedInitialSyncOperation { start: Some(Start { bridge: self.clone(), guard, monitor }) })
    }
}
