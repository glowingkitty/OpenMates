//! Pull-driven same-operation first-page continuation. SDK-required partial until
//! isolated cross-language conformance and product acceptance pass.
//! Host-owned exact persistence is explicit; no profile discovery or auto ACK.
use super::essential::EssentialGuard;
use super::*;
use openmates_sdk::client::{
    CacheSettlementPublication, CachedChatPublication, CanonicalChatPublication,
    ChatFirstPageCandidate, ChatFirstPagePublication, ChatFirstPageSink, ChatRefreshDurableReceipt,
    ChatViewRead, saved_chat_read::SavedChatReadAdmission,
};
use openmates_sdk::model::Chat;
use sha2::{Digest, Sha256};
use std::{pin::Pin, time::Duration};
use tokio::sync::oneshot;
use zeroize::Zeroize;
const CAP: usize = 8;
const MAX_JSON: usize = 64 * 1024 * 1024;
const WAIT: Duration = Duration::from_secs(120);
type Pull = oneshot::Sender<Result<Envelope>>;
type Check = Arc<dyn Fn() -> Result<()> + Send + Sync>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    ciphertext_sha256: String,
    credential_revision: u64,
}
enum PendingSender {
    Receipt(oneshot::Sender<Receipt>),
    Capacity(oneshot::Sender<bool>),
}
struct Pending {
    id: String,
    digest: String,
    revision: u64,
    sender: PendingSender,
}
struct Entry {
    guard: Arc<EssentialGuard>,
    pulls: mpsc::Sender<Pull>,
    pending: Mutex<Option<Pending>>,
    reading: AtomicBool,
}
impl Entry {
    fn close(&self) {
        self.guard.token().cancel();
        if let Ok(mut slot) = self.pending.lock() {
            slot.take();
        }
    }
}
#[derive(Default)]
pub(super) struct Registry {
    entries: Mutex<BTreeMap<String, Arc<Entry>>>,
    #[cfg(test)]
    pub(super) cancel_after_encode: AtomicBool,
    #[cfg(test)]
    pub(super) output_wiped: AtomicBool,
}
impl Registry {
    pub(super) fn close_all(&self) {
        if let Ok(mut entries) = self.entries.lock() {
            for entry in entries.values() {
                entry.close();
            }
            entries.clear();
        }
    }
    fn get(&self, id: &str) -> Result<Arc<Entry>> {
        self.entries
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .get(id)
            .cloned()
            .ok_or_else(|| Error::Conflict.into())
    }
    fn remove_owned(&self, id: &str, owner: &Arc<Entry>) {
        if let Ok(mut entries) = self.entries.lock() {
            if entries
                .get(id)
                .is_some_and(|entry| Arc::ptr_eq(entry, owner))
            {
                entries.remove(id);
            }
        }
    }
}
impl Drop for Registry {
    fn drop(&mut self) {
        self.close_all();
    }
}
struct Envelope {
    output: Zeroizing<String>,
    check: Check,
    released: Option<oneshot::Sender<()>>,
}
impl Envelope {
    fn release(&mut self, guard: &EssentialGuard) -> Result<String> {
        let result = guard.check().and_then(|_| (self.check)());
        if let Err(error) = result {
            self.output.zeroize();
            return Err(error);
        }
        if self
            .released
            .take()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?
            .send(())
            .is_err()
        {
            self.output.zeroize();
            return Err(Error::Cancelled.into());
        }
        Ok(std::mem::take(&mut *self.output))
    }
}
struct ReadDelivery {
    entry: Arc<Entry>,
    delivered: bool,
}
impl Drop for ReadDelivery {
    fn drop(&mut self) {
        self.entry.reading.store(false, Ordering::Release);
        if !self.delivered {
            self.entry.close();
        }
    }
}
fn encoded<T: Serialize>(value: &T) -> openmates_sdk::Result<Zeroizing<String>> {
    let output = Zeroizing::new(serde_json::to_string(value).map_err(|_| Error::Protocol)?);
    if output.len() > MAX_JSON {
        return Err(Error::Invalid(
            "First-page output exceeds the supported size.",
        ));
    }
    Ok(output)
}
fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn core(error: BindingError) -> Error {
    match error.code {
        "cancelled" => Error::Cancelled,
        "conflict" => Error::Conflict,
        "forbidden" => Error::Forbidden,
        "expired" => Error::Expired,
        "authentication" => Error::Authentication,
        _ => Error::Protocol,
    }
}
#[derive(Serialize)]
struct Scope<'a> {
    api_url: &'a str,
    account_id: &'a str,
    team_id: Option<&'a str>,
}
#[derive(Serialize)]
struct Stage<'a> {
    kind: &'static str,
    id: &'a str,
    source: &'static str,
    scope: Scope<'a>,
    checkpoint_json: &'a str,
    credentials_json: &'a str,
    ciphertext_sha256: &'a str,
    credential_revision: u64,
}
#[derive(Serialize)]
struct Presentation<'a> {
    kind: &'static str,
    source: &'static str,
    chat: &'a Chat,
    cached: bool,
    refreshing: bool,
    history_complete: bool,
    has_more_before: Option<bool>,
    pii_restoration: &'static str,
}
fn output_check(
    client: &Client,
    guard: Arc<EssentialGuard>,
    admission: Arc<SavedChatReadAdmission>,
    proof: Check,
) -> Check {
    let private = client.options().private_operation_gate.clone();
    Arc::new(move || {
        guard.check()?;
        admission
            .ensure_resource_current()
            .map_err(BindingError::from)?;
        if let Some(gate) = &private {
            gate().map_err(BindingError::from)?;
        }
        proof()?;
        guard.check()
    })
}
struct Driver {
    entry: Arc<Entry>,
    pulls: mpsc::Receiver<Pull>,
    next: Option<Pull>,
    state: Arc<State>,
}
impl Driver {
    async fn pull(&mut self) -> Result<()> {
        if self.next.is_some() {
            return Ok(());
        }
        let token = self.entry.guard.token();
        let pull = tokio::select! {
            _ = token.cancelled() => return Err(Error::Cancelled.into()),
            value = tokio::time::timeout(WAIT, self.pulls.recv()) => value.map_err(|_| BindingError::from(Error::Cancelled))?.ok_or(Error::Cancelled).map_err(BindingError::from)?,
        };
        self.entry.guard.check()?;
        self.next = Some(pull);
        Ok(())
    }
    async fn send(
        &mut self,
        client: &Client,
        admission: &SavedChatReadAdmission,
        output: Zeroizing<String>,
        check: Check,
    ) -> Result<()> {
        self.pull().await?;
        admission.check(client).map_err(BindingError::from)?;
        check()?;
        #[cfg(test)]
        if self
            .state
            .essential
            .first_pages
            .cancel_after_encode
            .swap(false, Ordering::AcqRel)
        {
            self.entry.close();
        }
        if let Err(error) = self
            .entry
            .guard
            .check()
            .and_then(|_| admission.check(client).map_err(BindingError::from))
            .and_then(|_| check())
        {
            let mut output = output;
            output.zeroize();
            #[cfg(test)]
            self.state
                .essential
                .first_pages
                .output_wiped
                .store(output.is_empty(), Ordering::Release);
            return Err(error);
        }
        let (released, receiver) = oneshot::channel();
        self.next
            .take()
            .ok_or(Error::Protocol)
            .map_err(BindingError::from)?
            .send(Ok(Envelope {
                output,
                check,
                released: Some(released),
            }))
            .map_err(|_| BindingError::from(Error::Cancelled))?;
        // Keep the SAME Client lock even for the FINAL output until the foreign
        // next has checked its ORIGINAL proof and signals successful release.
        // A dropped/rejected envelope drops this sender and cannot resume IO.
        let token = self.entry.guard.token();
        tokio::select! {
            _ = token.cancelled() => return Err(Error::Cancelled.into()),
            value = tokio::time::timeout(WAIT, receiver) => {
                value.map_err(|_|BindingError::from(Error::Cancelled))?.map_err(|_|BindingError::from(Error::Cancelled))?;
            }
        }
        self.entry.guard.check()
    }
    async fn receipt_stage(
        &mut self,
        client: &Client,
        source: &'static str,
        admission: Arc<SavedChatReadAdmission>,
        proof: Check,
        expected_digest: &str,
        expected_revision: u64,
    ) -> Result<Receipt> {
        self.pull().await?;
        admission.check(client).map_err(BindingError::from)?;
        proof()?;
        let credentials = client
            .credential_snapshot()
            .ok_or(Error::Authentication)
            .map_err(BindingError::from)?;
        let checkpoint = Zeroizing::new(
            serde_json::to_string(&client.ciphertext_snapshot())
                .map_err(|_| BindingError::from(Error::Protocol))?,
        );
        if credentials.revision != expected_revision || digest(&checkpoint) != expected_digest {
            return Err(Error::Cancelled.into());
        }
        let account = client.user()["id"]
            .as_str()
            .or_else(|| client.user()["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .ok_or(Error::Authentication)
            .map_err(BindingError::from)?;
        #[derive(Serialize)]
        struct Credentials<'a> {
            revision: u64,
            session: &'a Session,
        }
        let credentials_json = encoded(&Credentials {
            revision: credentials.revision,
            session: &credentials.session,
        })
        .map_err(BindingError::from)?;
        let id = uuid::Uuid::new_v4().to_string();
        let output = encoded(&Stage {
            kind: "stage",
            id: &id,
            source,
            scope: Scope {
                api_url: &credentials.session.api_url,
                account_id: account,
                team_id: credentials.session.active_team_id.as_deref(),
            },
            checkpoint_json: &checkpoint,
            credentials_json: &credentials_json,
            ciphertext_sha256: expected_digest,
            credential_revision: expected_revision,
        })
        .map_err(BindingError::from)?;
        let (sender, receiver) = oneshot::channel();
        {
            let mut slot = self
                .entry
                .pending
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if slot.is_some() {
                return Err(Error::Conflict.into());
            }
            *slot = Some(Pending {
                id,
                digest: expected_digest.into(),
                revision: expected_revision,
                sender: PendingSender::Receipt(sender),
            });
        }
        let check = output_check(client, self.entry.guard.clone(), admission.clone(), proof);
        self.send(client, &admission, output, check).await?;
        let token = self.entry.guard.token();
        let receipt = tokio::select! {
            _ = token.cancelled() => return Err(Error::Cancelled.into()),
            value = tokio::time::timeout(WAIT, receiver) => value.map_err(|_| BindingError::from(Error::Cancelled))?.map_err(|_| BindingError::from(Error::Cancelled))?,
        };
        admission.check(client).map_err(BindingError::from)?;
        self.entry.guard.check()?;
        Ok(receipt)
    }
    async fn capacity_stage(
        &mut self,
        client: &Client,
        checkpoint_json_bytes: usize,
    ) -> Result<bool> {
        self.pull().await?;
        let admission = Arc::new(
            client
                .saved_chat_read_admission()
                .map_err(BindingError::from)?,
        );
        admission.check(client).map_err(BindingError::from)?;
        let session = client
            .session()
            .ok_or(Error::Authentication)
            .map_err(BindingError::from)?;
        let account = client.user()["id"]
            .as_str()
            .or_else(|| client.user()["user_id"].as_str())
            .filter(|id| !id.is_empty())
            .ok_or(Error::Authentication)
            .map_err(BindingError::from)?;
        #[derive(Serialize)]
        struct Capacity<'a> {
            kind: &'static str,
            id: &'a str,
            scope: Scope<'a>,
            checkpoint_json_bytes: usize,
        }
        let id = uuid::Uuid::new_v4().to_string();
        let output = encoded(&Capacity {
            kind: "capacity",
            id: &id,
            scope: Scope {
                api_url: &session.api_url,
                account_id: account,
                team_id: session.active_team_id.as_deref(),
            },
            checkpoint_json_bytes,
        })
        .map_err(BindingError::from)?;
        let (sender, receiver) = oneshot::channel();
        {
            let mut pending = self
                .entry
                .pending
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if pending.is_some() {
                return Err(Error::Conflict.into());
            }
            *pending = Some(Pending {
                id,
                digest: String::new(),
                revision: 0,
                sender: PendingSender::Capacity(sender),
            });
        }
        // Capacity emits only scoped length metadata, never a decrypted chat,
        // credentials, ACK or invented first-page/canonical publication proof.
        let check = output_check(
            client,
            self.entry.guard.clone(),
            admission.clone(),
            Arc::new(|| Ok(())),
        );
        self.send(client, &admission, output, check).await?;
        let token = self.entry.guard.token();
        let accepted = tokio::select! {
            _ = token.cancelled()=>return Err(Error::Cancelled.into()),
            value=tokio::time::timeout(WAIT,receiver)=>value.map_err(|_|BindingError::from(Error::Cancelled))?.map_err(|_|BindingError::from(Error::Cancelled))?,
        };
        admission.check(client).map_err(BindingError::from)?;
        self.entry.guard.check()?;
        Ok(accepted)
    }
    async fn run(&mut self, chat_id: String) -> Result<()> {
        // Opening alone never starts a competing read or monopolizes Client.
        self.pull().await?;
        let state = self.state.clone();
        let token = self.entry.guard.token();
        let mut client = tokio::select! {
            _ = token.cancelled() => return Err(Error::Cancelled.into()),
            value = tokio::time::timeout(WAIT, SessionBridge::live_client(&state)) => {
                value.map_err(|_|BindingError::from(Error::Cancelled))??
            }
        };
        self.entry.guard.check()?;
        client.set_operation_cancel(self.entry.guard.token());
        let read = client
            .read_chat_view_prefer_cache_with_first_page(
                None,
                &chat_id,
                self.entry.guard.token(),
                self,
            )
            .await
            .map_err(BindingError::from)?;
        let admission = Arc::new(
            client
                .saved_chat_read_admission()
                .map_err(BindingError::from)?,
        );
        let (source, revision, expected_digest) = match &read {
            ChatViewRead::Canonical(value) => (
                "canonical",
                value.credential_revision(),
                value.ciphertext_sha256().map_err(BindingError::from)?,
            ),
            ChatViewRead::CacheSettled(value) => (
                "cache_settled",
                value.credential_revision(),
                value.ciphertext_sha256().map_err(BindingError::from)?,
            ),
            ChatViewRead::CachedOffline(_) => {
                let credentials = client
                    .credential_snapshot()
                    .ok_or(Error::Authentication)
                    .map_err(BindingError::from)?;
                (
                    "cached_offline",
                    credentials.revision,
                    digest(
                        &serde_json::to_string(&client.ciphertext_snapshot())
                            .map_err(|_| BindingError::from(Error::Protocol))?,
                    ),
                )
            }
        };
        let read = Arc::new(Mutex::new(Some(read)));
        let original = read.clone();
        let proof: Check = Arc::new(move || {
            let read = original
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            match read
                .as_ref()
                .ok_or(Error::Cancelled)
                .map_err(BindingError::from)?
            {
                ChatViewRead::Canonical(value) => value
                    .ciphertext_sha256()
                    .map(|_| ())
                    .map_err(BindingError::from),
                ChatViewRead::CacheSettled(value) => value
                    .ciphertext_sha256()
                    .map(|_| ())
                    .map_err(BindingError::from),
                ChatViewRead::CachedOffline(value) if value.is_valid() => Ok(()),
                _ => Err(Error::Cancelled.into()),
            }
        });
        validate_read(&client, &read)?;
        let receipt = self
            .receipt_stage(
                &client,
                source,
                admission.clone(),
                proof,
                &expected_digest,
                revision,
            )
            .await?;
        validate_read(&client, &read)?;
        client
            .acknowledge_credentials(receipt.credential_revision)
            .map_err(BindingError::from)?;
        let read = read
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .take()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?;
        let receipt = ChatRefreshDurableReceipt {
            ciphertext_sha256: receipt.ciphertext_sha256,
            credential_revision: receipt.credential_revision,
        };
        let publication = Arc::new(match read {
            ChatViewRead::Canonical(value) => Publication::Canonical(
                client
                    .commit_chat_view(value, receipt)
                    .map_err(BindingError::from)?,
            ),
            ChatViewRead::CacheSettled(value) => Publication::Settled(
                client
                    .commit_cache_settlement(value, receipt)
                    .map_err(BindingError::from)?,
            ),
            ChatViewRead::CachedOffline(value) => Publication::Offline(value),
        });
        self.pull().await?;
        publication.check(&client)?;
        admission.check(&client).map_err(BindingError::from)?;
        let output = publication.encode()?;
        publication.check(&client)?;
        let original = publication.clone();
        let proof: Check = Arc::new(move || original.current());
        let check = output_check(&client, self.entry.guard.clone(), admission.clone(), proof);
        self.send(&client, &admission, output, check).await
    }
}
fn validate_read(client: &Client, read: &Mutex<Option<ChatViewRead>>) -> Result<()> {
    let read = read
        .lock()
        .map_err(|_| BindingError::from(Error::Protocol))?;
    match read
        .as_ref()
        .ok_or(Error::Cancelled)
        .map_err(BindingError::from)?
    {
        ChatViewRead::Canonical(value) => {
            client.validate_chat_view(value).map_err(BindingError::from)
        }
        ChatViewRead::CacheSettled(value) => client
            .validate_cache_settlement(value)
            .map_err(BindingError::from),
        ChatViewRead::CachedOffline(value) if value.is_valid() => Ok(()),
        _ => Err(Error::Cancelled.into()),
    }
}
enum Publication {
    Canonical(CanonicalChatPublication),
    Settled(CacheSettlementPublication),
    Offline(CachedChatPublication),
}
impl Publication {
    fn current(&self) -> Result<()> {
        if match self {
            Self::Canonical(value) => value.is_valid(),
            Self::Settled(value) => value.is_valid(),
            Self::Offline(value) => value.is_valid(),
        } {
            Ok(())
        } else {
            Err(Error::Cancelled.into())
        }
    }
    fn check(&self, client: &Client) -> Result<()> {
        if let Self::Settled(value) = self {
            client
                .validate_cache_settlement_publication(value)
                .map_err(BindingError::from)?;
        }
        self.current()
    }
    fn encode(&self) -> Result<Zeroizing<String>> {
        match self {
            Self::Canonical(value) => value.with_chat(|chat| {
                encoded(&Presentation {
                    kind: "completed",
                    source: "canonical",
                    chat,
                    cached: false,
                    refreshing: false,
                    history_complete: true,
                    has_more_before: Some(false),
                    pii_restoration: "all_user_rows",
                })
            }),
            Self::Settled(value) => value.with_window(|value| {
                encoded(&Presentation {
                    kind: "completed",
                    source: "cache_settled",
                    chat: &value.chat,
                    cached: true,
                    refreshing: false,
                    history_complete: false,
                    has_more_before: value.has_more_before,
                    pii_restoration: value.pii_restoration,
                })
            }),
            Self::Offline(value) => value.with_window(|value| {
                encoded(&Presentation {
                    kind: "completed",
                    source: "cached_offline",
                    chat: &value.chat,
                    cached: true,
                    refreshing: false,
                    history_complete: false,
                    has_more_before: value.has_more_before,
                    pii_restoration: value.pii_restoration,
                })
            }),
        }
        .map_err(BindingError::from)
    }
}
impl ChatFirstPageSink for Driver {
    fn admit_checkpoint<'a>(
        &'a mut self,
        client: &'a Client,
        checkpoint_json_bytes: usize,
    ) -> Pin<Box<dyn Future<Output = openmates_sdk::Result<bool>> + Send + 'a>> {
        Box::pin(async move {
            self.capacity_stage(client, checkpoint_json_bytes)
                .await
                .map_err(core)
        })
    }
    fn first_page<'a>(
        &'a mut self,
        client: &'a mut Client,
        candidate: ChatFirstPageCandidate,
    ) -> Pin<Box<dyn Future<Output = openmates_sdk::Result<()>> + Send + 'a>> {
        Box::pin(async move {
            let revision = candidate.credential_revision();
            let expected_digest = candidate.ciphertext_sha256()?;
            client.validate_chat_first_page(&candidate)?;
            let candidate = Arc::new(Mutex::new(Some(candidate)));
            let original = candidate.clone();
            let proof: Check = Arc::new(move || {
                original
                    .lock()
                    .map_err(|_| BindingError::from(Error::Protocol))?
                    .as_ref()
                    .ok_or(Error::Cancelled)
                    .map_err(BindingError::from)?
                    .ciphertext_sha256()
                    .map(|_| ())
                    .map_err(BindingError::from)
            });
            let admission = Arc::new(client.saved_chat_read_admission()?);
            let receipt = self
                .receipt_stage(
                    client,
                    "first_page",
                    admission.clone(),
                    proof,
                    &expected_digest,
                    revision,
                )
                .await
                .map_err(core)?;
            let candidate = candidate
                .lock()
                .map_err(|_| Error::Protocol)?
                .take()
                .ok_or(Error::Cancelled)?;
            client.validate_chat_first_page(&candidate)?;
            client.acknowledge_credentials(receipt.credential_revision)?;
            let publication = Arc::new(client.commit_chat_first_page(
                candidate,
                ChatRefreshDurableReceipt {
                    ciphertext_sha256: receipt.ciphertext_sha256,
                    credential_revision: receipt.credential_revision,
                },
            )?);
            self.pull().await.map_err(core)?;
            admission.check(client)?;
            client.validate_chat_first_page_publication(&publication)?;
            let output = publication.with_chat(|chat| {
                encoded(&Presentation {
                    kind: "first_page",
                    source: "first_page",
                    chat,
                    cached: true,
                    refreshing: true,
                    history_complete: false,
                    has_more_before: Some(true),
                    pii_restoration: "page_local",
                })
            })?;
            client.validate_chat_first_page_publication(&publication)?;
            let original = publication.clone();
            let proof: Check = Arc::new(move || {
                if original.is_valid() {
                    Ok(())
                } else {
                    Err(Error::Cancelled.into())
                }
            });
            let check = output_check(client, self.entry.guard.clone(), admission.clone(), proof);
            self.send(client, &admission, output, check)
                .await
                .map_err(core)?;
            // A new pull resumes the ORIGINAL read only after the adapter has
            // observed its first page and finished its callback. No new fetch.
            self.pull().await.map_err(core)?;
            admission.check(client)?;
            client.validate_chat_first_page_publication(&publication)?;
            Ok(())
        })
    }
}
impl SessionBridge {
    /// Explicit consent covers both exact credentials/checkpoint staging and
    /// decrypted first/final outputs. Opening starts no HTTP until first pull.
    pub async fn first_page_open(
        &self,
        chat_id: String,
        include_secrets: bool,
        include_private_output: bool,
    ) -> Result<String> {
        let guard = EssentialGuard::new(self, false)?;
        self.first_page_open_admitted(chat_id, include_secrets, include_private_output, guard).await
    }
    async fn first_page_open_admitted(
        &self,
        chat_id: String,
        include_secrets: bool,
        include_private_output: bool, guard: Arc<essential::EssentialGuard>) -> Result<String> {
        guard.check()?;
        if !include_secrets || !include_private_output {
            return Err(Error::Invalid(
                "Explicit credential and private output consent is required.",
            )
            .into());
        }
        uuid::Uuid::parse_str(&chat_id)
            .map_err(|_| BindingError::from(Error::Invalid("A full chat ID is required.")))?;
        let id = uuid::Uuid::new_v4().to_string();
        let (pulls, receiver) = mpsc::channel(1);
        let entry = Arc::new(Entry {
            guard,
            pulls,
            pending: Mutex::new(None),
            reading: AtomicBool::new(false),
        });
        {
            let mut entries = self
                .state
                .essential
                .first_pages
                .entries
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            if entries.len() >= CAP {
                return Err(Error::Conflict.into());
            }
            entries.insert(id.clone(), entry.clone());
        }
        let state = self.state.clone();
        let operation = id.clone();
        let owner = entry.clone();
        tokio::spawn(async move {
            let mut driver = Driver {
                entry: owner.clone(),
                pulls: receiver,
                next: None,
                state: state.clone(),
            };
            if let Err(error) = driver.run(chat_id).await {
                let mut delivered_error = false;
                if driver.next.is_some() || driver.pull().await.is_ok() {
                    if let Some(reply) = driver.next.take() {
                        delivered_error = reply.send(Err(error)).is_ok();
                    }
                }
                // Let the receiving ReadDelivery close its own operation after
                // observing the real error. Cancelling first would race the
                // error channel and turn an Offline/Forbidden into Cancelled.
                if !delivered_error {
                    owner.close();
                }
            }
            state.essential.first_pages.remove_owned(&operation, &owner);
        });
        encoded(&json!({"id":id}))
            .map(|mut value| std::mem::take(&mut *value))
            .map_err(BindingError::from)
    }
    #[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
    pub(crate) fn capture_first_page_open(&self, chat_id: String, include_secrets: bool, include_private_output: bool) -> impl Future<Output = Result<String>> + Send + 'static {
        let mut chat_id = Zeroizing::new(chat_id);
        let original = essential::EssentialGuard::new(self, false);
        let bridge = self.clone();
        async move {
            let guard = original?;
            guard.check()?;
            bridge.first_page_open_admitted(std::mem::take(&mut *chat_id), include_secrets, include_private_output, guard).await
        }
    }

    pub async fn first_page_next(&self, id: String) -> Result<String> {
        let entry = self.state.essential.first_pages.get(&id)?;
        entry.guard.check()?;
        if entry
            .reading
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(Error::Conflict.into());
        }
        let mut delivery = ReadDelivery {
            entry: entry.clone(),
            delivered: false,
        };
        let (sender, receiver) = oneshot::channel();
        let token = entry.guard.token();
        tokio::select! {
            _ = token.cancelled() => return Err(Error::Cancelled.into()),
            value = tokio::time::timeout(WAIT,entry.pulls.send(sender)) => {
                value.map_err(|_|BindingError::from(Error::Cancelled))?.map_err(|_|BindingError::from(Error::Cancelled))?;
            }
        }
        let mut envelope = tokio::select! {_ = token.cancelled()=>return Err(Error::Cancelled.into()),value=tokio::time::timeout(WAIT,receiver)=>value.map_err(|_|BindingError::from(Error::Cancelled))?.map_err(|_|BindingError::from(Error::Cancelled))??};
        // ORIGINAL proof/admission/private gate survive the channel and are
        // rechecked immediately before private foreign output is released.
        let output = envelope.release(&entry.guard)?;
        delivery.delivered = true;
        Ok(output)
    }
    /// Receipt mailbox never locks Client. Exact pending identity prevents a
    /// stale A receipt/close from cancelling or authorizing a successor B.
    pub fn first_page_receipt(&self, id: String, stage_id: String, receipt: String) -> Result<()> {
        let input = Zeroizing::new(receipt);
        if input.len() > 4096 {
            return Err(Error::Invalid("First-page receipt exceeds the supported size.").into());
        }
        let receipt: Receipt = serde_json::from_str(&input)
            .map_err(|_| BindingError::from(Error::Invalid("Invalid first-page receipt.")))?;
        let entry = self.state.essential.first_pages.get(&id)?;
        entry.guard.check()?;
        let mut slot = entry
            .pending
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        let pending = slot
            .as_ref()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        if !matches!(&pending.sender, PendingSender::Receipt(_))
            || pending.id != stage_id
            || pending.digest != receipt.ciphertext_sha256
            || pending.revision != receipt.credential_revision
        {
            return Err(Error::Conflict.into());
        }
        entry.guard.check()?;
        let PendingSender::Receipt(sender) = slot
            .take()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?
            .sender
        else {
            return Err(Error::Conflict.into());
        };
        sender
            .send(receipt)
            .map_err(|_| BindingError::from(Error::Cancelled))
    }
    /// Explicit store-capacity metadata decision only; never an ACK or auth
    /// grant. No Client lock or arbitrary shared quota/eviction is introduced.
    pub fn first_page_capacity(&self, id: String, stage_id: String, accepted: bool) -> Result<()> {
        let entry = self.state.essential.first_pages.get(&id)?;
        entry.guard.check()?;
        let mut slot = entry
            .pending
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        let pending = slot
            .as_ref()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?;
        if pending.id != stage_id || !matches!(&pending.sender, PendingSender::Capacity(_)) {
            return Err(Error::Conflict.into());
        }
        entry.guard.check()?;
        let PendingSender::Capacity(sender) = slot
            .take()
            .ok_or(Error::Conflict)
            .map_err(BindingError::from)?
            .sender
        else {
            return Err(Error::Conflict.into());
        };
        sender
            .send(accepted)
            .map_err(|_| BindingError::from(Error::Cancelled))
    }
    pub fn first_page_close(&self, id: String) -> Result<()> {
        let entry = self.state.essential.first_pages.get(&id)?;
        self.state.essential.first_pages.remove_owned(&id, &entry);
        entry.close();
        Ok(())
    }
}
#[cfg(test)]
#[path = "session_first_page_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "session_first_page_peer_tests.rs"]
mod peer_tests;
