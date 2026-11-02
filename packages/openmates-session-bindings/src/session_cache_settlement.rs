//! Explicit cache-preferred reads. Sealed core results retain original authority
//! until the final locked foreign return; storage belongs to the caller.
use super::*;
use super::essential::EssentialGuard;
use openmates_sdk::client::{
    CacheSettlementPublication, CachedChatPublication, CanonicalChatPublication,
    ChatRefreshDurableReceipt, ChatViewRead, CachedChatWindow,
    saved_chat_read::SavedChatReadAdmission,
};
use openmates_sdk::model::Chat;
use sha2::{Digest, Sha256};
use zeroize::Zeroize;
const MAX_STAGES: usize = 100;
const MAX_OUTPUT: usize = 64 * 1024 * 1024;

struct Stage {
    guard: Arc<EssentialGuard>,
    read: ChatViewRead,
    admission: SavedChatReadAdmission,
    digest: String,
    revision: u64,
}
#[derive(Default)]
pub(super) struct Registry {
    stages: Mutex<BTreeMap<String, Stage>>,
    #[cfg(test)] pub(super) cancel_after_encode: AtomicBool,
    #[cfg(test)] pub(super) output_wiped: AtomicBool,
    #[cfg(test)] pub(super) cancel_monitor_after_encode: AtomicBool,
    #[cfg(test)] pub(super) monitor_output_wiped: AtomicBool,
}
impl Registry {
    pub(super) fn close_all(&self) {
        if let Ok(mut stages) = self.stages.lock() {
            for stage in stages.values() { stage.guard.token().cancel(); }
            stages.clear();
        }
    }
    fn discard(&self, id: &str) -> Result<()> {
        let stage = self.stages.lock().map_err(|_| BindingError::from(Error::Protocol))?
            .remove(id).ok_or(Error::Conflict).map_err(BindingError::from)?;
        stage.guard.token().cancel();
        Ok(())
    }
}
impl Drop for Registry { fn drop(&mut self) { self.close_all(); } }
struct Delivery {
    state: std::sync::Weak<State>, id: String,
    guard: Arc<EssentialGuard>, delivered: bool,
}
impl Drop for Delivery {
    fn drop(&mut self) {
        if !self.delivered {
            self.guard.token().cancel();
            if let Some(state) = self.state.upgrade() {
                let _ = state.essential.cache_reads.discard(&self.id);
            }
        }
    }
}
struct CancelOnDrop(CancellationToken);
impl Drop for CancelOnDrop { fn drop(&mut self) { self.0.cancel(); } }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt { ciphertext_sha256: String, credential_revision: u64 }
#[derive(Serialize)]
struct Scope<'a> { api_url: &'a str, account_id: &'a str, team_id: Option<&'a str> }
#[derive(Serialize)]
struct StageOutput<'a> {
    id: &'a str, source: &'a str, scope: Scope<'a>, checkpoint_json: &'a str,
    ciphertext_sha256: &'a str, credential_revision: u64, credentials_json: &'a str,
}
#[derive(Serialize)]
struct Presentation<'a> {
    source: &'static str, chat: &'a Chat, cached: bool, refreshing: bool,
    history_complete: bool, has_more_before: Option<bool>, pii_restoration: &'static str,
}
fn encoded<T: Serialize>(value: &T) -> openmates_sdk::Result<Zeroizing<String>> {
    let output = Zeroizing::new(serde_json::to_string(value).map_err(|_| Error::Protocol)?);
    if output.len() > MAX_OUTPUT { return Err(Error::Invalid("Cache read output exceeds the supported size.")); }
    Ok(output)
}
fn digest(checkpoint: &str) -> String { format!("{:x}", Sha256::digest(checkpoint.as_bytes())) }
fn source(read: &ChatViewRead) -> &'static str {
    match read {
        ChatViewRead::Canonical(_) => "canonical",
        ChatViewRead::CacheSettled(_) => "cache_settled",
        ChatViewRead::CachedOffline(_) => "cached_offline",
    }
}
impl Stage {
    fn check(&self, client: &Client) -> Result<()> {
        self.guard.check()?;
        self.admission.check(client).map_err(BindingError::from)?;
        let credentials = client.credential_snapshot().ok_or(Error::Authentication).map_err(BindingError::from)?;
        if credentials.revision != self.revision
            || digest(&serde_json::to_string(&client.ciphertext_snapshot()).map_err(|_| BindingError::from(Error::Protocol))?) != self.digest {
            return Err(Error::Cancelled.into());
        }
        match &self.read {
            ChatViewRead::Canonical(value) => client.validate_chat_view(value).map_err(BindingError::from)?,
            ChatViewRead::CacheSettled(value) => client.validate_cache_settlement(value).map_err(BindingError::from)?,
            ChatViewRead::CachedOffline(value) if value.is_valid() => {},
            ChatViewRead::CachedOffline(_) => return Err(Error::Cancelled.into()),
        }
        self.guard.check()
    }
}
enum Publication {
    Canonical(CanonicalChatPublication),
    Settled(CacheSettlementPublication),
    Offline(CachedChatPublication),
}
impl Publication {
    fn check(&self, client: &Client) -> Result<()> {
        match self {
            Self::Canonical(value) if value.is_valid() => Ok(()),
            Self::Settled(value) => client.validate_cache_settlement_publication(value).map_err(BindingError::from),
            Self::Offline(value) if value.is_valid() => Ok(()),
            _ => Err(Error::Cancelled.into()),
        }
    }
    fn encode(&self) -> Result<Zeroizing<String>> {
        let window = |source, value: &CachedChatWindow| encoded(&Presentation {
            source, chat: &value.chat, cached: true, refreshing: value.refreshing,
            // Cache provenance never attests complete server history.
            history_complete: false, has_more_before: value.has_more_before,
            pii_restoration: value.pii_restoration,
        });
        match self {
            Self::Canonical(value) => value.with_chat(|chat| encoded(&Presentation {
                source: "canonical", chat, cached: false, refreshing: false,
                history_complete: true, has_more_before: Some(false), pii_restoration: "all_user_rows",
            })),
            Self::Settled(value) => value.with_window(|value| window("cache_settled", value)),
            Self::Offline(value) => value.with_window(|value| window("cached_offline", value)),
        }.map_err(BindingError::from)
    }
}
impl SessionBridge {
    /// Stage ciphertext and explicit credentials only; no plaintext or fabricated
    /// durable receipt crosses the language boundary before the caller saves.
    pub async fn cache_chat_stage(&self, id: String, include_secrets: bool) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.cache_chat_stage_admitted(id, include_secrets, guard).await
    }
    async fn cache_chat_stage_admitted(&self, id: String, include_secrets: bool, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        if !include_secrets {
            return Err(Error::Invalid("Explicit credential storage consent is required.").into());
        }
        let stage_id = uuid::Uuid::new_v4().to_string();
        let mut delivery = Delivery { state: Arc::downgrade(&self.state), id: stage_id.clone(), guard: guard.clone(), delivered: false };
        let worker = guard.clone(); let state = self.state.clone(); let stage_key = stage_id.clone();
        let mut output = self.transaction(async move {
            let mut client = Self::live_client(&state).await?;
            worker.check()?;
            client.set_operation_cancel(worker.token());
            let read = client.read_chat_view_prefer_cache(None, &id, worker.token()).await.map_err(BindingError::from)?;
            let admission = client.saved_chat_read_admission().map_err(BindingError::from)?;
            let credentials = client.credential_snapshot().ok_or(Error::Authentication).map_err(BindingError::from)?;
            let checkpoint = Zeroizing::new(serde_json::to_string(&client.ciphertext_snapshot()).map_err(|_| BindingError::from(Error::Protocol))?);
            let digest = digest(&checkpoint);
            let revision = credentials.revision;
            match &read {
                ChatViewRead::Canonical(value) if value.credential_revision() == revision && value.ciphertext_sha256().map_err(BindingError::from)? == digest => {},
                ChatViewRead::CacheSettled(value) if value.credential_revision() == revision && value.ciphertext_sha256().map_err(BindingError::from)? == digest => {},
                ChatViewRead::CachedOffline(value) if value.is_valid() => {},
                _ => return Err(Error::Cancelled.into()),
            }
            let account = client.user()["id"].as_str().or_else(|| client.user()["user_id"].as_str()).filter(|id| !id.is_empty()).ok_or(Error::Authentication).map_err(BindingError::from)?;
            #[derive(Serialize)] struct Credentials<'a> { revision: u64, session: &'a Session }
            let credentials_json = encoded(&Credentials { revision, session: &credentials.session }).map_err(BindingError::from)?;
            let output = encoded(&StageOutput {
                id: &stage_key, source: source(&read), scope: Scope { api_url: &credentials.session.api_url, account_id: account, team_id: credentials.session.active_team_id.as_deref() },
                checkpoint_json: &checkpoint, ciphertext_sha256: &digest, credential_revision: revision, credentials_json: &credentials_json,
            }).map_err(BindingError::from)?;
            let stage = Stage { guard: worker, read, admission, digest, revision };
            stage.check(&client)?;
            let mut stages = state.essential.cache_reads.stages.lock().map_err(|_| BindingError::from(Error::Protocol))?;
            if stages.len() >= MAX_STAGES { return Err(Error::Conflict.into()); }
            stage.guard.check()?;
            stages.insert(stage_key, stage);
            Ok(output)
        }).await?;
        // Recheck the retained original candidate under current Client ownership
        // after the detached join, before releasing credentials or checkpoint.
        let client = Self::live_client(&self.state).await?;
        let stages = self.state.essential.cache_reads.stages.lock().map_err(|_| BindingError::from(Error::Protocol))?;
        stages.get(&stage_id).ok_or(Error::Cancelled).map_err(BindingError::from)?.check(&client)?;
        guard.check()?;
        delivery.delivered = true;
        Ok(std::mem::take(&mut *output))
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_cache_chat_stage(&self, id: String, include_secrets: bool) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut id = Zeroizing::new(id);
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.cache_chat_stage_admitted(std::mem::take(&mut *id), include_secrets, guard).await
        }
    }

    pub fn cache_chat_discard(&self, stage_id: String) -> Result<()> {
        self.state.essential.cache_reads.discard(&stage_id)
    }
    /// A receipt is the same explicit caller-owned exact-write attestation as
    /// monitor commit; it never independently grants authentication or history.
    pub async fn cache_chat_commit(&self, stage_id: String, receipt: String) -> Result<String> {
        let receipt = Zeroizing::new(receipt);
        if receipt.len() > 4096 { return Err(Error::Invalid("Cache read receipt exceeds the supported size.").into()); }
        let receipt: Receipt = serde_json::from_str(&receipt).map_err(|_| BindingError::from(Error::Invalid("Invalid cache read receipt.")))?;
        let stage = {
            let mut stages = self.state.essential.cache_reads.stages.lock().map_err(|_| BindingError::from(Error::Protocol))?;
            let stage = stages.get(&stage_id).ok_or(Error::Conflict).map_err(BindingError::from)?;
            if stage.digest != receipt.ciphertext_sha256 || stage.revision != receipt.credential_revision { return Err(Error::Conflict.into()); }
            stages.remove(&stage_id).ok_or(Error::Conflict).map_err(BindingError::from)?
        };
        let guard = stage.guard.clone();
        let _cancel = CancelOnDrop(guard.token());
        let state = self.state.clone();
        let (publication, admission) = self.transaction(async move {
            let mut client = Self::live_client(&state).await?;
            // Preserve the exact originally admitted operation child. A setter
            // would cancel it even with the same parent, and stale work must
            // never cancel or rebind a successor operation.
            stage.check(&client)?;
            client.acknowledge_credentials(receipt.credential_revision).map_err(BindingError::from)?;
            let receipt = ChatRefreshDurableReceipt { ciphertext_sha256: receipt.ciphertext_sha256, credential_revision: receipt.credential_revision };
            let publication = match stage.read {
                ChatViewRead::Canonical(value) => Publication::Canonical(client.commit_chat_view(value, receipt).map_err(BindingError::from)?),
                ChatViewRead::CacheSettled(value) => Publication::Settled(client.commit_cache_settlement(value, receipt).map_err(BindingError::from)?),
                ChatViewRead::CachedOffline(value) => Publication::Offline(value),
            };
            stage.guard.check()?;
            Ok((publication, stage.admission))
        }).await?;
        // No plaintext crosses the join. Keep actual original publication and
        // current Client lock alive through encoding and the last output check.
        let client = Self::live_client(&self.state).await?;
        guard.check()?; admission.check(&client).map_err(BindingError::from)?; publication.check(&client)?;
        let mut output = publication.encode()?;
        #[cfg(test)]
        if self.state.essential.cache_reads.cancel_after_encode.swap(false, Ordering::AcqRel) {
            guard.token().cancel();
        }
        let allowed = guard.check().and_then(|_| admission.check(&client).map_err(BindingError::from)).and_then(|_| publication.check(&client));
        if let Err(error) = allowed {
            output.zeroize();
            #[cfg(test)] self.state.essential.cache_reads.output_wiped.store(output.is_empty(), Ordering::Release);
            return Err(error);
        }
        Ok(std::mem::take(&mut *output))
    }
}

#[cfg(test)]
#[path = "session_cache_settlement_tests.rs"]
mod tests;
