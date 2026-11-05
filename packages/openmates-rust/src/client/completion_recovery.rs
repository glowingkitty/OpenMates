//! Explicit foreground main/metadata recovery. No inference or filesystem API.
use super::{plaintext::Plain, sync_capability::AsyncCryptoScope};
use super::{
    project_task_watch::WatchAuthority,
    transport::{Socket, receive_ephemeral, send},
    *,
};
use crate::crypto::master::MasterCapability;
use crate::platform::time::Instant;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
#[path="completion_recovery_phase_runtime.rs"]
mod phase_runtime;
#[path="completion_recovery_algorithm.rs"]
mod phase_algorithm;
#[path="completion_recovery_io_algorithm.rs"]
mod phase_io;
#[path="completion_recovery_key_algorithm.rs"]
mod phase_key;
#[path="completion_recovery_reconcile.rs"]
mod phase_reconcile;
#[path="completion_recovery_owned.rs"]
mod owned;
pub(crate) use owned::{OriginalRecoveryCheckpointIoTicket,BrowserRecoveryPortRoot};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use owned::{OriginalMetadataRecoveryRetirement,OriginalMainRecoveryJournalObservation};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(crate) use owned::OriginalRecoveryRetirementTicket;
#[cfg(target_arch="wasm32")]
pub(in crate::client) use owned::{OriginalHintRecoveryDurableReceipt,OriginalRecoveryNativeWrite,OriginalRecoveryNativeWriteResult,OriginalRecoveryReadbackCrypto,OriginalRecoveryVerifiedWrite};
pub(in crate::client) use owned::{OriginalRecoveryActiveState,OriginalRecoveryActivePermit,OriginalRecoveryRowBoundary,OriginalRecoveryRowTransition,OwnedRecoveryArtifacts,PreparedOwnedRecovery,OwnedRecoveryDriver,OwnedRecoveryStep,OwnedRecoveryApply,OwnedRecoveryIo,OwnedRecoveryResume,OwnedRecoveryControl,OwnedRecoveryPendingPersistence,PreparedOriginalRecoveryCheckpoint,OriginalRecoveryCheckpointCrypto,PreparedOriginalRecoveryCheckpointWrite,OriginalRecoveryPersistenceFailure};
const MAX_JOBS: usize = 100;
const IO_BUDGET: Duration = Duration::from_secs(20);
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CompletionRecoveryKind {
    Main,
    Metadata,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompletionRecoveryJob {
    pub kind: CompletionRecoveryKind,
    pub job_id: String,
    pub chat_id: String,
    pub turn_id: Option<String>,
    pub assistant_message_id: Option<String>,
    pub task_id: Option<String>,
    pub stage: Option<String>,
    pub chat_key_version: u32,
    /// Durable completion creation time, when supplied by the authenticated job offer.
    /// Older checkpoints omit this additive metadata field byte-for-byte.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub created_at: Option<u64>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompletionRecoveryCheckpoint {
    protocol_version: u32,
    api_url: String,
    owner_id: String,
    team_id: Option<String>,
    job: CompletionRecoveryJob,
    encrypted_candidate: Value,
    wrapped_chat_key: Option<String>,
    canonical_ciphertext: bool,
}
impl CompletionRecoveryCheckpoint {
    pub fn digest(&self) -> Result<String> {
        Ok(sha256(&serde_json::to_string(self)?))
    }
    pub fn job(&self) -> &CompletionRecoveryJob {
        &self.job
    }
    pub fn api_url(&self) -> &str {
        &self.api_url
    }
    pub fn owner_id(&self) -> &str {
        &self.owner_id
    }
    pub fn team_id(&self) -> Option<&str> {
        self.team_id.as_deref()
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompletionRecoveryDurableReceipt {
    pub checkpoint_sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CompletionRecoveryReceipt {
    pub job_id: String,
    pub chat_id: String,
    pub assistant_message_id: Option<String>,
    pub messages_version: Option<u64>,
    pub metadata_version: Option<u64>,
    pub title_version: Option<u64>,
    pub state: String,
}
pub enum CompletionRecoveryAdmission {
    Ready(Box<CompletionRecoveryStage>),
    Canonical(CompletionRecoveryReceipt),
    Deferred,
}
// Nonserializable result of the ACTUAL existing canonical terminal/commit
// path. Public Clone/serde receipts remain DTOs and cannot construct this.
pub(in crate::client) struct OriginalForegroundRecoveryResult {
    receipt:CompletionRecoveryReceipt,job:CompletionRecoveryJob,fence:RecoveryFence,
    owned_transition:Option<owned::OriginalRecoveryRowTransition>,
    owned_artifacts:Option<owned::OwnedRecoveryArtifacts>,
    owned_socket:Option<Socket>,
}
impl OriginalForegroundRecoveryResult {
    pub(in crate::client) fn check_original(&self,client:&Client)->Result<()> {
        self.fence.check_client(client)?;
        if self.receipt.job_id!=self.job.job_id||self.receipt.chat_id!=self.job.chat_id
            ||!matches!(self.receipt.state.as_str(),"TERMINAL"|"SUPERSEDED"){return Err(Error::Protocol)}
        if let Some(witness)=&self.owned_transition {
            witness.check_client(client)?;
            if self.job.kind==CompletionRecoveryKind::Main&&self.owned_artifacts.is_none(){return Err(Error::Protocol)}
        }
        if let Some(artifacts)=&self.owned_artifacts{artifacts.check_client(client)?;}
        self.fence.check_client(client)?;
        if let Some(witness)=&self.owned_transition{witness.check_original_negative()?;}
        Ok(())
    }
    pub(in crate::client) fn into_witnessed_parts(self)->Result<(CompletionRecoveryReceipt,owned::OriginalRecoveryRowTransition,Option<owned::OwnedRecoveryArtifacts>)>{
        if self.owned_socket.is_some(){return Err(Error::Conflict)}
        Ok((self.receipt,self.owned_transition.ok_or(Error::Cancelled)?,self.owned_artifacts))
    }
    pub(in crate::client) fn job(&self)->&CompletionRecoveryJob{&self.job}
    // Data projection only. Existing public SDK methods retain their exact DTO.
    fn into_receipt(self)->CompletionRecoveryReceipt{self.receipt}
}
pub(in crate::client) enum OriginalForegroundRecoveryAdmission {
    Ready(Box<CompletionRecoveryStage>),Canonical(OriginalForegroundRecoveryResult),Deferred,DeferredWithSocket(Socket),
}
impl OriginalForegroundRecoveryAdmission {
    fn into_public(self)->CompletionRecoveryAdmission{match self{
        Self::Ready(stage)=>CompletionRecoveryAdmission::Ready(stage),
        Self::Canonical(result)=>CompletionRecoveryAdmission::Canonical(result.into_receipt()),
        Self::Deferred|Self::DeferredWithSocket(_)=>CompletionRecoveryAdmission::Deferred,
    }}
}
pub struct CompletionRecoveryStage {
    socket: Socket,
    checkpoint: CompletionRecoveryCheckpoint,
    key: Key,
    fence: RecoveryFence,
    lease_token: Option<zeroize::Zeroizing<String>>,
    lease_generation: Option<u64>,
    // Fresh in-memory proof, never restored from checkpoint DTO authority.
    canonical_settlement: bool,
}
impl CompletionRecoveryStage {
    pub fn checkpoint(&self) -> Result<CompletionRecoveryCheckpoint> {
        self.fence.check()?;
        let checkpoint = self.checkpoint.clone();
        self.fence.check()?;
        Ok(checkpoint)
    }
}
#[derive(Clone)]
struct RecoveryFence {
    authority: Arc<WatchAuthority>,
    mode: CancellationToken,
    caller: CancellationToken,
    operation: CancellationToken,
    expires_at: Option<u64>,
    lease_expires_at: Option<u64>,
    master: MasterCapability,
    binding: Arc<credentials::MasterBinding>,
    credential_context: String,
}
impl RecoveryFence {
    fn check(&self) -> Result<()> {
        if self.authority.cancel.is_cancelled()
            || self.mode.is_cancelled()
            || self.caller.is_cancelled()
            || self.operation.is_cancelled()
        {
            return Err(Error::Cancelled);
        }
        if self.expires_at.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Expired);
        }
        if self.lease_expires_at.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Conflict);
        }
        self.master.ensure_current()?;
        Ok(())
    }
    fn check_client(&self, client: &Client) -> Result<()> {
        self.check()?;
        client.require_canonical_read_profile()?;
        self.binding.check(client)?;
        if !Arc::ptr_eq(&self.authority, &client.task_watch_authority)
            || self.credential_context != recovery_credential_context(client)?
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    async fn run_plain<T: super::plaintext::Wipe>(
        &self,
        operation: impl std::future::Future<Output = Result<T>>,
    ) -> Result<Plain<T>> {
        self.run(async { operation.await.map(Plain::new) }).await
    }
    async fn run<T>(&self, operation: impl std::future::Future<Output = Result<T>>) -> Result<T> {
        self.check()?;
        let deadline_ms = [self.expires_at, self.lease_expires_at]
            .into_iter()
            .flatten()
            .min();
        let mut deadline = Instant::now() + IO_BUDGET;
        if let Some(at) = deadline_ms {
            deadline =
                deadline.min(Instant::now() + Duration::from_millis(at.saturating_sub(now_ms())))
        }
        let result = tokio::select! {biased;_=self.authority.cancel.cancelled()=>Err(Error::Cancelled),_=self.mode.cancelled()=>Err(Error::Cancelled),_=self.caller.cancelled()=>Err(Error::Cancelled),_=self.operation.cancelled()=>Err(Error::Cancelled),result=crate::platform::time::timeout_at(deadline,operation)=>match result {Ok(result)=>result,Err(_)=>Err(Error::Offline)}};
        self.check()?;
        result
    }
}
// Persisted checkpoints remain ciphertext-only data. This in-memory digest
// restricts a staged continuation to its original credential/generation/denial
// context without retaining a routine per-call operation child. User adoption
// remains the existing authoritative validate_session/sync policy; each crypto
// call captures its own full AsyncCryptoScope after that admission.
fn recovery_credential_context(client: &Client) -> Result<String> {
    let credentials = client.require_credentials()?;
    Ok(sha256(&serde_json::to_string(&(
        credentials.api_url,
        credentials.session_id,
        credentials.hashed_email,
        credentials.active_team_id,
        client.generation,
        client.task_watch_authority.cached_denial_revision()?,
    ))?))
}
fn canonical_uuid(value: &str) -> Result<()> {
    if uuid::Uuid::parse_str(value)
        .ok()
        .is_none_or(|id| id.hyphenated().to_string() != value)
    {
        Err(Error::Protocol)
    } else {
        Ok(())
    }
}
fn validate_job(job: &CompletionRecoveryJob) -> Result<()> {
    canonical_uuid(&job.job_id)?;
    canonical_uuid(&job.chat_id)?;
    if job.created_at.is_some_and(|at| at == 0 || at > 9_007_199_254_740_991) { return Err(Error::Protocol); }
    if job.chat_key_version == 0 {
        return Err(Error::Protocol);
    }
    match job.kind {
        CompletionRecoveryKind::Main => {
            canonical_uuid(job.turn_id.as_deref().ok_or(Error::Protocol)?)?;
            canonical_uuid(job.assistant_message_id.as_deref().ok_or(Error::Protocol)?)?;
            if job.task_id.is_some() || job.stage.is_some() {
                return Err(Error::Protocol);
            }
        }
        CompletionRecoveryKind::Metadata => {
            canonical_uuid(job.task_id.as_deref().ok_or(Error::Protocol)?)?;
            if !matches!(job.stage.as_deref(), Some("initial" | "postprocessing"))
                || job.turn_id.is_some()
                || job.assistant_message_id.is_some()
            {
                return Err(Error::Protocol);
            }
        }
    }
    Ok(())
}
fn owner(client: &Client) -> Result<String> {
    client.user()["id"]
        .as_str()
        .filter(|id| !id.is_empty())
        .or_else(|| {
            client.user()["user_id"]
                .as_str()
                .filter(|id| !id.is_empty())
        })
        .map(str::to_owned)
        .ok_or(Error::Authentication)
}
fn same_job(job: &CompletionRecoveryJob, value: &Value) -> Result<()> {
    for (field, expected) in [
        ("job_id", Some(job.job_id.as_str())),
        ("chat_id", Some(job.chat_id.as_str())),
        ("turn_id", job.turn_id.as_deref()),
        ("assistant_message_id", job.assistant_message_id.as_deref()),
        ("task_id", job.task_id.as_deref()),
        ("stage", job.stage.as_deref()),
    ] {
        if let Some(expected) = expected {
            if value[field] != expected {
                return Err(Error::Protocol);
            }
        }
    }
    if value["chat_key_version"] != job.chat_key_version {
        return Err(Error::Protocol);
    }
    Ok(())
}
/// A live lease is not an available offer and cannot prove no completed work.
/// Validate its existing job metadata without inserting it into claimable jobs.
pub(super) fn has_pending_main_jobs(kind: &str, payload: &Value) -> Result<bool> {
    if kind != "recovery_jobs_available" { return Ok(false); }
    let Some(pending) = payload.get("pending_jobs") else { return Ok(false); };
    let pending = pending.as_array().ok_or(Error::Protocol)?;
    if pending.len() > MAX_JOBS { return Err(Error::Protocol); }
    let mut main = BTreeMap::new(); let mut metadata = BTreeMap::new();
    capture(kind, &json!({"jobs":pending}), &mut main, &mut metadata)?;
    Ok(!pending.is_empty())
}
/// Timestamp metadata may be absent in old durable checkpoints. Every original
/// authority/identity field stays exact; two supplied timestamps must agree.
fn same_checkpoint_job(a: &CompletionRecoveryJob, b: &CompletionRecoveryJob) -> bool {
    a.kind == b.kind && a.job_id == b.job_id && a.chat_id == b.chat_id
        && a.turn_id == b.turn_id && a.assistant_message_id == b.assistant_message_id
        && a.task_id == b.task_id && a.stage == b.stage && a.chat_key_version == b.chat_key_version
        && (a.created_at.is_none() || b.created_at.is_none() || a.created_at == b.created_at)
}
/// A public/caller Job timestamp alone never supplies the durable time. Only
/// the same current Client's authenticated discovery may provide this metadata.
fn observed_job_created_at(client:&Client,job:&CompletionRecoveryJob)->Result<Option<u64>> {
    validate_job(job)?;
    match client.completion_recovery_jobs.get(&job.job_id) {
        Some(observed) if same_checkpoint_job(observed,job)=>Ok(observed.created_at),
        Some(_)=>Err(Error::Protocol),None=>Ok(None),
    }
}
pub(super) fn capture(
    kind: &str,
    payload: &Value,
    main: &mut BTreeMap<String, CompletionRecoveryJob>,
    metadata: &mut BTreeMap<String, CompletionRecoveryJob>,
) -> Result<bool> {
    let (kind, target) = match kind {
        "recovery_jobs_available" => (CompletionRecoveryKind::Main, main),
        "metadata_jobs_available" => (CompletionRecoveryKind::Metadata, metadata),
        _ => return Ok(false),
    };
    let rows = payload["jobs"].as_array().ok_or(Error::Protocol)?;
    if rows.len() > MAX_JOBS {
        return Err(Error::Protocol);
    }
    for row in rows {
        let job_id = required(row, "job_id")?.to_owned();
        let chat_id = required(row, "chat_id")?.to_owned();
        canonical_uuid(&job_id)?;
        canonical_uuid(&chat_id)?;
        let version = row["chat_key_version"]
            .as_u64()
            .filter(|v| *v > 0 && *v <= u64::from(u32::MAX))
            .ok_or(Error::Protocol)? as u32;
        let mut job = if kind == CompletionRecoveryKind::Main {
            let turn = required(row, "turn_id")?.to_owned();
            let assistant = required(row, "assistant_message_id")?.to_owned();
            canonical_uuid(&turn)?;
            canonical_uuid(&assistant)?;
            if !matches!(row["state"].as_str(), Some("AVAILABLE" | "LEASED")) {
                return Err(Error::Protocol);
            }
            CompletionRecoveryJob {
                kind,
                job_id,
                chat_id,
                turn_id: Some(turn),
                assistant_message_id: Some(assistant),
                task_id: None,
                stage: None,
                chat_key_version: version,
                created_at: row["created_at"].as_u64().filter(|at| *at > 0 && *at <= 9_007_199_254_740_991),
            }
        } else {
            let task = required(row, "task_id")?.to_owned();
            canonical_uuid(&task)?;
            let stage = required(row, "stage")?.to_owned();
            if !matches!(stage.as_str(), "initial" | "postprocessing") {
                return Err(Error::Protocol);
            }
            CompletionRecoveryJob {
                kind,
                job_id,
                chat_id,
                turn_id: None,
                assistant_message_id: None,
                task_id: Some(task),
                stage: Some(stage),
                chat_key_version: version,
                created_at: row["created_at"].as_u64().filter(|at| *at > 0 && *at <= 9_007_199_254_740_991),
            }
        };
        if target.len() >= MAX_JOBS && !target.contains_key(&job.job_id) {
            return Err(Error::Protocol);
        }
        if let Some(previous) = target.get(&job.job_id) {
            if !same_checkpoint_job(previous, &job) {
                return Err(Error::Crypto);
            }
            // Missing legacy time is metadata absence, never a new identity.
            // A later legacy replay cannot erase richer authenticated time.
            if job.created_at.is_none() { job.created_at = previous.created_at; }
        }
        target.insert(job.job_id.clone(), job);
    }
    Ok(true)
}
impl Client {
    pub fn set_foreground_completion_recovery(&mut self, enabled: bool) -> Result<()> {
        if !enabled {
            if let Some(mode) = self.completion_recovery_mode.take() {
                mode.cancel()
            }
            self.completion_recovery_jobs.clear();
            self.metadata_recovery_jobs.clear();
            return Ok(());
        }
        self.require_canonical_read_profile()?;
        if self
            .completion_recovery_mode
            .as_ref()
            .is_none_or(CancellationToken::is_cancelled)
        {
            self.completion_recovery_mode = Some(CancellationToken::new())
        }
        Ok(())
    }
    fn recovery_fence(&self, cancel: &CancellationToken) -> Result<RecoveryFence> {
        self.recovery_fence_with_operation(cancel,self.operation_cancel.clone())
    }
    fn recovery_fence_with_operation(&self,cancel:&CancellationToken,operation:CancellationToken)->Result<RecoveryFence> {
        self.require_canonical_read_profile()?;
        let session = self.require_credentials()?;
        let mode = self
            .completion_recovery_mode
            .as_ref()
            .filter(|token| !token.is_cancelled())
            .ok_or(Error::Unavailable {
                code: "completion_recovery_unavailable",
                reason: "COMPLETION_RECOVERY_REQUIRES_EXPLICIT_FOREGROUND",
            })?;
        let fence = RecoveryFence {
            authority: self.task_watch_authority.clone(),
            mode: mode.clone(),
            caller: cancel.clone(),
            operation,
            expires_at: session.paired_session_expires_at,
            lease_expires_at: None,
            master: self.master_capability()?,
            binding: Arc::new(self.master_binding()?),
            credential_context: recovery_credential_context(self)?,
        };
        fence.check_client(self)?;
        Ok(fence)
    }
    fn check_recovery_owner(
        &self,
        checkpoint: &CompletionRecoveryCheckpoint,
        fence: &RecoveryFence,
    ) -> Result<()> {
        fence.check_client(self)?;
        if !Arc::ptr_eq(&fence.authority, &self.task_watch_authority)
            || self
                .completion_recovery_mode
                .as_ref()
                .is_none_or(CancellationToken::is_cancelled)
        {
            return Err(Error::Cancelled);
        }
        if checkpoint.protocol_version != 1
            || checkpoint.api_url != self.base.as_str().trim_end_matches('/')
            || checkpoint.owner_id != owner(self)?
            || checkpoint.team_id.as_deref() != self.team()?
        {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
    pub async fn completion_recovery_jobs(
        &mut self,
        cancel: &CancellationToken,
    ) -> Result<Vec<CompletionRecoveryJob>> {
        self.discover_completion_recovery(cancel, false)
            .await
            .map(|(jobs, _)| jobs)
    }
    /// Discover recovery work and retain optional proof of the same fully
    /// completed fresh sync. Partial discovery still returns jobs, never proof.
    /// Keep this opaque value in memory; persist credentials/ciphertext through
    /// the caller's existing durability contract before publishing private output.
    pub async fn completion_recovery_jobs_with_inventory(
        &mut self,
        cancel: &CancellationToken,
    ) -> Result<(Vec<CompletionRecoveryJob>, Option<FreshChatInventory>)> {
        let (jobs, complete) = self.discover_completion_recovery(cancel, true).await?;
        let inventory = if complete {
            self.fresh_chat_inventory(cancel)?
        } else {
            None
        };
        Ok((jobs, inventory))
    }
    async fn discover_completion_recovery(
        &mut self,
        cancel: &CancellationToken,
        inventory: bool,
    ) -> Result<(Vec<CompletionRecoveryJob>, bool)> {
        let fence = self.recovery_fence(cancel)?;
        self.completion_recovery_jobs.clear();
        self.metadata_recovery_jobs.clear();
        let refresh = async {
            if inventory {
                self.refresh_chat_metadata_for_inventory().await
            } else {
                self.refresh_chat_metadata(0).await.map(|_| false)
            }
        };
        let complete = match fence.run(refresh).await {
            Ok(complete) => complete,
            Err(Error::Offline | Error::Conflict | Error::Protocol)
                if !self.completion_recovery_jobs.is_empty() =>
            {
                // The sync transaction already published fenced job discovery.
                // An independently durable typed-output replay can be deferred
                // until main persistence; it must not hide the only main job.
                false
            }
            Err(error) => return Err(error),
        };
        fence.check_client(self)?;
        let personal = self.team()?.is_none();
        let jobs = self
            .completion_recovery_jobs
            .values()
            .chain(self.metadata_recovery_jobs.values().filter(|_| personal))
            .cloned()
            .collect();
        fence.check_client(self)?;
        Ok((jobs, complete))
    }
    async fn recovery_current_key(
        &mut self,
        id: &str,
        fence: &RecoveryFence,
    ) -> Result<(Value, Key)> {
        phase_key::current_key(&mut phase_runtime::BorrowedRecoveryPhases { client:self }, id, fence).await
    }
    async fn recovery_unwrap_key(
        &self,
        encrypted: &str,
        wrapping: &MasterCapability,
        fence: &RecoveryFence,
        scope: &AsyncCryptoScope,
        id: &str,
    ) -> Result<Key> {
        phase_key::borrowed_unwrap(&mut phase_key::BorrowedKeyChecks { client:self,scope,fence,id },encrypted,wrapping,fence).await
    }
    #[allow(clippy::too_many_arguments)]
    async fn recovery_unwrap_selected_key(
        &self,
        encrypted: &str,
        wrapping: &MasterCapability,
        fence: &RecoveryFence,
        scope: &AsyncCryptoScope,
        id: &str,
        wrapper: &Value,
        team: bool,
    ) -> Result<Key> {
        phase_key::borrowed_selected(&mut phase_key::BorrowedKeyChecks { client:self,scope,fence,id },encrypted,wrapping,fence,wrapper,team).await
    }
    async fn recovery_exchange(
        &mut self,
        ws: &mut Socket,
        kind: &str,
        mut payload: Value,
        reply: &str,
        job_id: &str,
        fence: &RecoveryFence,
    ) -> Result<Value> {
        phase_io::exchange(&mut phase_runtime::BorrowedRecoveryPhases { client:self }, ws, kind, payload, reply, job_id, fence).await
    }
    async fn recovery_foreground_socket(&mut self, fence: &RecoveryFence) -> Result<Socket> {
        phase_io::foreground_socket(&mut phase_runtime::BorrowedRecoveryPhases { client:self }, fence).await
    }
    async fn reconcile_main(
        &mut self,
        job: &CompletionRecoveryJob,
        key: &[u8; 32],
        fence: &RecoveryFence,
    ) -> Result<Option<CompletionRecoveryReceipt>> {
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, &job.chat_id)?;
        fence.check_client(self)?;
        let chat = fence.run_plain(self.open_chat_live(&job.chat_id)).await?;
        scope.check_chat(self, &job.chat_id)?;
        fence.check_client(self)?;
        // open_chat_live freshly resolves wrappers again. A changed key may not
        // validate a checkpoint produced under the earlier current-key lookup.
        let row = self.chats.get(&job.chat_id).ok_or(Error::Protocol)?;
        let wrapping = self.cached_wrapping_capability()?;
        let current_key = fence
            .run(self.chat_key_with_capability(row, &wrapping))
            .await?;
        scope.check_chat(self, &job.chat_id)?;
        fence.check_client(self)?;
        phase_reconcile::reconcile_actual(job,&chat,&current_key,key,row)
    }
    fn canonical_main_candidate(&self, job: &CompletionRecoveryJob) -> Result<Option<Value>> {
        let expected = job.assistant_message_id.as_deref().ok_or(Error::Protocol)?;
        let rows = self
            .history
            .get(&job.chat_id)
            .into_iter()
            .flatten()
            .filter(|row| {
                ["client_message_id", "message_id", "id"]
                    .iter()
                    .find_map(|field| row[*field].as_str().filter(|id| !id.is_empty()))
                    == Some(expected)
            })
            .collect::<Vec<_>>();
        let raw = match rows.as_slice() {
            [] => return Ok(None),
            [row] => *row,
            _ => return Err(Error::Protocol),
        };
        if raw["role"] != "assistant" {
            return Err(Error::Protocol);
        }
        let mut candidate =
            json!({"client_message_id":expected,"chat_id":job.chat_id,"role":"assistant"});
        for field in [
            "encrypted_content",
            "encrypted_sender_name",
            "created_at",
            "updated_at",
            "encrypted_category",
            "encrypted_model_name",
            "encrypted_thinking_content",
            "encrypted_thinking_signature",
        ] {
            if let Some(value) = raw.get(field).filter(|value| !value.is_null()) {
                candidate[field] = value.clone();
            }
        }
        Ok(Some(candidate))
    }
    pub async fn stage_completion_recovery(
        &mut self,
        job: &CompletionRecoveryJob,
        cancel: &CancellationToken,
    ) -> Result<CompletionRecoveryAdmission> {
        self.stage_recovery(job, None, cancel).await
    }
    pub async fn resume_completion_recovery(
        &mut self,
        checkpoint: CompletionRecoveryCheckpoint,
        cancel: &CancellationToken,
    ) -> Result<CompletionRecoveryAdmission> {
        // Stored DTO is only ciphertext/data. Its identity is rechecked against
        // fresh explicit credentials and canonical state before a claim/send.
        let job = checkpoint.job.clone();
        self.stage_recovery(&job, Some(checkpoint), cancel).await
    }
    async fn stage_recovery(&mut self,job:&CompletionRecoveryJob,
        saved:Option<CompletionRecoveryCheckpoint>,cancel:&CancellationToken,
    )->Result<CompletionRecoveryAdmission>{
        self.stage_recovery_original(job,saved,cancel).await.map(OriginalForegroundRecoveryAdmission::into_public)
    }
    /// Internal same-Client foreground path, not a passive-monitor grant. The
    /// existing actual method still admits mode/auth/socket/canonical policy.
    pub(in crate::client) async fn stage_hint_completion_recovery(&mut self,job:&CompletionRecoveryJob,
        cancel:&CancellationToken,
    )->Result<OriginalForegroundRecoveryAdmission>{self.stage_recovery_original(job,None,cancel).await}
    async fn stage_recovery_original(
        &mut self,
        job: &CompletionRecoveryJob,
        saved: Option<CompletionRecoveryCheckpoint>,
        cancel: &CancellationToken,
    ) -> Result<OriginalForegroundRecoveryAdmission> {
        phase_algorithm::stage(&mut phase_runtime::BorrowedRecoveryPhases { client:self }, job, saved, cancel).await
    }
    pub async fn commit_completion_recovery(&mut self,stage:CompletionRecoveryStage,
        durable:CompletionRecoveryDurableReceipt,cancel:&CancellationToken,
    )->Result<CompletionRecoveryReceipt>{
        self.commit_hint_completion_recovery(stage,durable,cancel).await.map(OriginalForegroundRecoveryResult::into_receipt)
    }
    pub(in crate::client) async fn commit_hint_completion_recovery(
        &mut self,
        mut stage: CompletionRecoveryStage,
        durable: CompletionRecoveryDurableReceipt,
        cancel: &CancellationToken,
    ) -> Result<OriginalForegroundRecoveryResult> {
        phase_algorithm::commit(&mut phase_runtime::BorrowedRecoveryPhases { client:self }, stage, durable, cancel).await
    }
}
fn main_identity(owner: &str, job: &CompletionRecoveryJob) -> Result<crypto::RecoveryIdentity> {
    Ok(crypto::RecoveryIdentity {
        owner_id: owner.into(),
        chat_id: job.chat_id.clone(),
        turn_id: job.turn_id.clone().ok_or(Error::Protocol)?,
        job_id: job.job_id.clone(),
        assistant_message_id: job.assistant_message_id.clone().ok_or(Error::Protocol)?,
        key_version: job.chat_key_version,
    })
}
pub(super) fn decode_main_completion(
    envelope: &Value,
    key: &[u8; 32],
    identity: &crypto::RecoveryIdentity,
) -> Result<Value> {
    let pair = crypto::recovery_keypair(key, &identity.chat_id, identity.key_version)?;
    let plain = crypto::open_recovery_envelope(envelope, &pair.private_key, identity)?;
    let recovered: Value = serde_json::from_slice(&plain)?;
    let recovered =
        admit_recovery_plain(recovered, |value| validate_main_plaintext(value, identity))?;
    Ok(recovered.into_inner())
}
// The guard is installed before validation so well-formed but rejected
// decrypted JSON (including nested strings) is wiped on every error path.
fn admit_recovery_plain<T: super::plaintext::Wipe>(
    value: T,
    validate: impl FnOnce(&T) -> Result<()>,
) -> Result<Plain<T>> {
    let value = Plain::new(value);
    validate(&value)?;
    Ok(value)
}
fn validate_main_plaintext(value: &Value, identity: &crypto::RecoveryIdentity) -> Result<()> {
    let object = value.as_object().ok_or(Error::Protocol)?;
    let required_fields = [
        "assistant_message_id",
        "category",
        "chat_id",
        "content",
        "job_id",
        "key_version",
        "model_name",
        "turn_id",
    ];
    let optional = [
        "thinking_content",
        "thinking_signature",
        "has_thinking",
        "thinking_token_count",
        "thinking_duration_seconds",
    ];
    if required_fields
        .iter()
        .any(|field| !object.contains_key(*field))
        || object.keys().any(|field| {
            !required_fields.contains(&field.as_str()) && !optional.contains(&field.as_str())
        })
    {
        return Err(Error::Protocol);
    }
    for (field, expected) in [
        ("assistant_message_id", &identity.assistant_message_id),
        ("chat_id", &identity.chat_id),
        ("turn_id", &identity.turn_id),
        ("job_id", &identity.job_id),
    ] {
        if value[field] != *expected {
            return Err(Error::Protocol);
        }
    }
    if value["key_version"] != identity.key_version
        || !value["content"].is_string()
        || ["category", "model_name"]
            .iter()
            .any(|field| !value[field].is_null() && !value[field].is_string())
    {
        return Err(Error::Protocol);
    }
    for field in ["thinking_content", "thinking_signature"] {
        if value.get(field).is_some_and(|value| !value.is_string()) {
            return Err(Error::Protocol);
        }
    }
    if value
        .get("has_thinking")
        .is_some_and(|value| !value.is_boolean())
        || value
            .get("thinking_token_count")
            .is_some_and(|value| value.as_u64().is_none())
        || value
            .get("thinking_duration_seconds")
            .is_some_and(|value| value.as_f64().is_none_or(|value| value < 0.0))
    {
        return Err(Error::Protocol);
    }
    Ok(())
}
pub(super) fn encrypt_main_assistant(
    recovered: &Value,
    identity: &crypto::RecoveryIdentity,
    created: u64,
    user_message: Option<&str>,
    key: &[u8; 32],
) -> Result<Value> {
    validate_main_plaintext(recovered, identity)?;
    let mut encrypted = json!({"client_message_id":identity.assistant_message_id,"chat_id":identity.chat_id,"role":"assistant","encrypted_content":crypto::encrypt_combined(recovered["content"].as_str().ok_or(Error::Protocol)?,key)?,"encrypted_sender_name":crypto::encrypt_combined("Assistant",key)?,"created_at":created,"updated_at":created});
    if let Some(user_message) = user_message {
        encrypted["user_message_id"] = json!(user_message)
    }
    for (field, target) in [
        ("category", "encrypted_category"),
        ("model_name", "encrypted_model_name"),
        ("thinking_content", "encrypted_thinking_content"),
        ("thinking_signature", "encrypted_thinking_signature"),
    ] {
        if let Some(value) = recovered.get(field).and_then(Value::as_str) {
            encrypted[target] = json!(crypto::encrypt_combined(value, key)?)
        }
    }
    Ok(encrypted)
}
fn metadata_aad(owner: &str, job: &CompletionRecoveryJob) -> Result<Vec<u8>> {
    let mut aad = b"OMCM1".to_vec();
    for value in [
        owner,
        job.chat_id.as_str(),
        job.task_id.as_deref().ok_or(Error::Protocol)?,
        job.job_id.as_str(),
    ] {
        canonical_uuid(value)?;
        aad.extend((value.len() as u32).to_be_bytes());
        aad.extend(value.as_bytes());
    }
    let stage = job.stage.as_deref().ok_or(Error::Protocol)?;
    if !matches!(stage, "initial" | "postprocessing") {
        return Err(Error::Protocol);
    }
    aad.extend((stage.len() as u32).to_be_bytes());
    aad.extend(stage.as_bytes());
    aad.extend(job.chat_key_version.to_be_bytes());
    Ok(aad)
}
fn metadata_field(field: &str) -> Result<&'static str> {
    match field {
        "title" => Ok("encrypted_title"),
        "summary" => Ok("encrypted_chat_summary"),
        "category" => Ok("encrypted_category"),
        "icon" => Ok("encrypted_icon"),
        _ => Err(Error::Protocol),
    }
}
fn decode_metadata_completion(
    claim: &Value,
    owner: &str,
    job: &CompletionRecoveryJob,
    key: &[u8; 32],
) -> Result<Value> {
    let serialized = required(claim, "sealed_payload")?;
    if serialized.len() > 100_000 {
        return Err(Error::Protocol);
    }
    let envelope: Value = serde_json::from_str(serialized)?;
    let pair = crypto::recovery_keypair(key, &job.chat_id, job.chat_key_version)?;
    let plain = crypto::open_recovery_with_aad(
        &envelope,
        &pair.private_key,
        &metadata_aad(owner, job)?,
        1,
        64 * 1024,
    )?;
    let mut value = Plain::new(serde_json::from_slice::<Value>(&plain)?);
    let identity = json!({"owner_id":owner,"chat_id":job.chat_id,"task_id":job.task_id,"job_id":job.job_id,"stage":job.stage,"key_version":job.chat_key_version});
    let object = value.as_object().ok_or(Error::Protocol)?;
    if object.len() != 7
        || identity
            .as_object()
            .ok_or(Error::Protocol)?
            .iter()
            .any(|(field, expected)| value[field] != *expected)
    {
        return Err(Error::Protocol);
    }
    let metadata = value["metadata"].as_object().ok_or(Error::Protocol)?;
    if metadata.is_empty()
        || metadata.iter().any(|(field, value)| {
            metadata_field(field).is_err() || value.as_str().is_none_or(|value| value.is_empty())
        })
    {
        return Err(Error::Protocol);
    }
    let declared = claim["encrypted_fields"]
        .as_array()
        .ok_or(Error::Protocol)?;
    let fields = metadata
        .keys()
        .map(|field| metadata_field(field).map(str::to_owned))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    let actual = declared
        .iter()
        .map(|value| value.as_str().map(str::to_owned).ok_or(Error::Protocol))
        .collect::<Result<std::collections::BTreeSet<_>>>()?;
    if actual.len() != declared.len() || actual != fields {
        return Err(Error::Protocol);
    }
    Ok(std::mem::take(&mut value["metadata"]))
}
fn encrypt_metadata_fields(metadata: &Value, key: &[u8; 32]) -> Result<Value> {
    let mut encrypted = serde_json::Map::new();
    for (field, value) in metadata.as_object().ok_or(Error::Protocol)? {
        encrypted.insert(
            metadata_field(field)?.into(),
            json!(crypto::encrypt_combined(
                value.as_str().ok_or(Error::Protocol)?,
                key
            )?),
        );
    }
    if encrypted.is_empty() {
        return Err(Error::Protocol);
    }
    Ok(Value::Object(encrypted))
}
fn validate_checkpoint_candidate(
    checkpoint: &CompletionRecoveryCheckpoint,
    key: &[u8; 32],
    recovered: Option<&Value>,
) -> Result<()> {
    if checkpoint.protocol_version != 1 || checkpoint.job.chat_key_version != 1 {
        return Err(Error::Protocol);
    }
    let candidate = checkpoint
        .encrypted_candidate
        .as_object()
        .ok_or(Error::Protocol)?;
    if checkpoint.job.kind == CompletionRecoveryKind::Metadata {
        if checkpoint.team_id.is_some()
            || checkpoint.wrapped_chat_key.is_none()
            || candidate.is_empty()
        {
            return Err(Error::Forbidden);
        }
        let fields = [
            ("title", "encrypted_title"),
            ("summary", "encrypted_chat_summary"),
            ("category", "encrypted_category"),
            ("icon", "encrypted_icon"),
        ];
        for (field, cipher) in candidate {
            if !fields.iter().any(|(_, allowed)| field.as_str() == *allowed) {
                return Err(Error::Protocol);
            }
            let plain = zeroize::Zeroizing::new(crypto::decrypt_combined(
                cipher.as_str().ok_or(Error::Protocol)?,
                key,
            )?);
            if let Some(recovered) = recovered {
                let name = fields
                    .iter()
                    .find(|(_, encrypted)| *encrypted == field.as_str())
                    .ok_or(Error::Protocol)?
                    .0;
                if recovered[name] != plain.as_str() {
                    return Err(Error::Crypto);
                }
            }
        }
        if let Some(recovered) = recovered {
            if recovered.as_object().ok_or(Error::Protocol)?.len() != candidate.len() {
                return Err(Error::Protocol);
            }
        }
        return Ok(());
    }
    let allowed = [
        "client_message_id",
        "chat_id",
        "role",
        "encrypted_content",
        "encrypted_sender_name",
        "created_at",
        "updated_at",
        "encrypted_category",
        "encrypted_model_name",
        "encrypted_thinking_content",
        "encrypted_thinking_signature",
    ];
    if candidate
        .keys()
        .any(|field| !allowed.contains(&field.as_str()))
        || checkpoint.encrypted_candidate["client_message_id"].as_str()
            != checkpoint.job.assistant_message_id.as_deref()
        || checkpoint.encrypted_candidate["chat_id"] != checkpoint.job.chat_id
        || checkpoint.encrypted_candidate["role"] != "assistant"
        || checkpoint.encrypted_candidate["created_at"]
            .as_u64()
            .is_none()
        || checkpoint.encrypted_candidate["updated_at"]
            .as_u64()
            .is_none()
    {
        return Err(Error::Protocol);
    }
    let sender = zeroize::Zeroizing::new(crypto::decrypt_combined(
        required(&checkpoint.encrypted_candidate, "encrypted_sender_name")?,
        key,
    )?);
    if sender.is_empty() || !checkpoint.canonical_ciphertext && sender.as_str() != "Assistant" {
        return Err(Error::Crypto);
    }
    for (field, source) in [
        ("encrypted_content", "content"),
        ("encrypted_category", "category"),
        ("encrypted_model_name", "model_name"),
        ("encrypted_thinking_content", "thinking_content"),
        ("encrypted_thinking_signature", "thinking_signature"),
    ] {
        if let Some(cipher) = candidate.get(field) {
            let plain = zeroize::Zeroizing::new(crypto::decrypt_combined(
                cipher.as_str().ok_or(Error::Protocol)?,
                key,
            )?);
            if let Some(recovered) = recovered {
                if recovered[source] != plain.as_str() {
                    return Err(Error::Crypto);
                }
            }
        } else if field == "encrypted_content"
            || recovered.is_some_and(|recovered| recovered[source].is_string())
        {
            return Err(Error::Protocol);
        }
    }
    Ok(())
}
fn merge_metadata_receipt(receipt: &Value, current: &Value) -> Result<Value> {
    let versions = receipt["versions"].as_object().ok_or(Error::Protocol)?;
    if versions.len() != 2 {
        return Err(Error::Protocol);
    }
    let metadata = receipt["versions"]["metadata_v"]
        .as_u64()
        .ok_or(Error::Protocol)?;
    let title = receipt["versions"]["title_v"]
        .as_u64()
        .ok_or(Error::Protocol)?;
    let old_metadata = current["metadata_v"].as_u64().ok_or(Error::Protocol)?;
    let old_title = current["title_v"].as_u64().ok_or(Error::Protocol)?;
    let fields = receipt["encrypted_metadata"]
        .as_object()
        .ok_or(Error::Protocol)?;
    if fields.iter().any(|(field, value)| {
        ![
            "encrypted_title",
            "encrypted_chat_summary",
            "encrypted_category",
            "encrypted_icon",
        ]
        .contains(&field.as_str())
            || !value.is_string()
    }) {
        return Err(Error::Protocol);
    }
    let mut updated = current.clone();
    if metadata >= old_metadata {
        for (field, value) in fields {
            if field != "encrypted_title" || title >= old_title {
                updated[field] = value.clone();
            }
        }
        updated["metadata_v"] = json!(metadata);
        updated["title_v"] = json!(title.max(old_title));
    }
    Ok(updated)
}
fn metadata_receipt(
    job: &CompletionRecoveryJob,
    receipt: &Value,
    current: &Value,
) -> Result<CompletionRecoveryReceipt> {
    let mut metadata_version = current["metadata_v"].as_u64().ok_or(Error::Protocol)?;
    let mut title_version = current["title_v"].as_u64().ok_or(Error::Protocol)?;
    if let Some(versions) = receipt.get("versions") {
        let object = versions.as_object().ok_or(Error::Protocol)?;
        if object.len() != 2 {
            return Err(Error::Protocol);
        }
        metadata_version =
            metadata_version.max(versions["metadata_v"].as_u64().ok_or(Error::Protocol)?);
        title_version = title_version.max(versions["title_v"].as_u64().ok_or(Error::Protocol)?);
        let fields = receipt["encrypted_metadata"]
            .as_object()
            .ok_or(Error::Protocol)?;
        if fields.iter().any(|(field, value)| {
            ![
                "encrypted_title",
                "encrypted_chat_summary",
                "encrypted_category",
                "encrypted_icon",
            ]
            .contains(&field.as_str())
                || !value.is_string()
        }) {
            return Err(Error::Protocol);
        }
    }
    Ok(CompletionRecoveryReceipt {
        job_id: job.job_id.clone(),
        chat_id: job.chat_id.clone(),
        assistant_message_id: None,
        messages_version: None,
        metadata_version: Some(metadata_version),
        title_version: Some(title_version),
        state: required(receipt, "state")?.into(),
    })
}
fn iso_timestamp_ms(value: &str) -> Result<u64> {
    // Directus JS Date.toJSON emits exactly this UTC millisecond form.
    if value.len() != 24
        || [4, 7, 10, 13, 16, 19, 23].iter().any(|index| {
            value.as_bytes()[*index]
                != match index {
                    4 | 7 => b'-',
                    10 => b'T',
                    13 | 16 => b':',
                    19 => b'.',
                    _ => b'Z',
                }
        })
    {
        return Err(Error::Protocol);
    }
    let number = |start, end| {
        value
            .get(start..end)
            .filter(|value| value.bytes().all(|b| b.is_ascii_digit()))
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or(Error::Protocol)
    };
    let (year, month, day, hour, minute, second, millis) = (
        number(0, 4)?,
        number(5, 7)?,
        number(8, 10)?,
        number(11, 13)?,
        number(14, 16)?,
        number(17, 19)?,
        number(20, 23)?,
    );
    let leap = |year: u64| year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let days_in_month = [
        31,
        if leap(year) { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    if year < 1970
        || !(1..=12).contains(&month)
        || day == 0
        || day > days_in_month[(month - 1) as usize]
        || hour > 23
        || minute > 59
        || second > 59
    {
        return Err(Error::Protocol);
    }
    let leaps = |year: u64| year / 4 - year / 100 + year / 400;
    let days = (year - 1970) * 365 + leaps(year - 1) - leaps(1969)
        + days_in_month[..(month - 1) as usize].iter().sum::<u64>()
        + day
        - 1;
    Ok((((days * 24 + hour) * 60 + minute) * 60 + second) * 1000 + millis)
}
#[cfg(test)]
mod tests;

// Team wrappers have an explicit supported epoch/version. Personal legacy rows
// may omit these migration fields; an explicit unsupported value never grants.
fn validate_recovery_wrapper(wrapper: &Value, team: bool, now: u64) -> Result<()> {
    for field in if team {
        &["team_key_epoch", "wrapper_version"][..]
    } else {
        &["wrapper_version"][..]
    } {
        match wrapper.get(*field).filter(|v| !v.is_null()) {
            Some(value) if value.as_u64() == Some(1) => {}
            None if !team => {}
            Some(value) if value.as_u64().is_none() => return Err(Error::Protocol),
            _ => return Err(Error::Conflict),
        }
    }
    if let Some(expiry) = wrapper.get("expires_at").filter(|v| !v.is_null()) {
        let seconds = expiry.as_u64().ok_or(Error::Protocol)?;
        let expiry_ms = seconds.checked_mul(1000).ok_or(Error::Protocol)?;
        if expiry_ms <= now {
            return Err(Error::Conflict);
        }
    }
    Ok(())
}

fn validate_selected_team_recovery_wrapper(
    row: &Value,
    id: &str,
    team: Option<&str>,
) -> Result<()> {
    // Direct recipient envelopes are a separate strict resolver. Canonical
    // direct metadata deliberately has no Team-wide wrappers.
    if text(row, "chat_visibility") == "direct" {
        return Ok(());
    }
    if let Some(team_id) = team {
        let selected = row["chat_key_wrappers"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|wrapper| {
                text(wrapper, "hashed_chat_id") == sha256(id)
                    && text(wrapper, "key_type") == "team"
                    && text(wrapper, "hashed_team_id") == sha256(team_id)
            })
            .collect::<Vec<_>>();
        match selected.as_slice() {
            [wrapper] => validate_recovery_wrapper(wrapper, true, now_ms())?,
            _ => return Err(Error::Forbidden),
        }
    }
    Ok(())
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "completion_recovery/opaque_tests.rs"]
mod opaque_tests;

// Selected discovery never mints global inventory or list freshness.
#[path = "completion_recovery/selected.rs"]
mod selected;
