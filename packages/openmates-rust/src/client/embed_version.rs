//! Personal Cookie version-content reads. Existing API-key/opaque version APIs
//! remain independent; no CLI, credential fallback or server protocol addition.
use super::{plaintext::Plain, sync_capability::AsyncCryptoScope, *};
use crate::crypto::master::MasterCapability;
use crate::platform::time::Instant;
use std::sync::{Arc, Mutex};
const VERSION_READ_BUDGET: Duration = Duration::from_secs(20);
pub(super) struct VersionReadScope {
    crypto: AsyncCryptoScope,
    wrapper_expiry: Mutex<Option<u64>>,
    operation: CancellationToken,
    master: MasterCapability,
    authority: Arc<super::project_task_watch::WatchAuthority>,
    denial_revision: u64,
    paired_expiry: Option<u64>,
    deadline: Instant,
    private_gate: Option<Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}
impl VersionReadScope {
    pub(super) fn begin(client: &Client) -> Result<Self> {
        Self::begin_until(client, Instant::now() + VERSION_READ_BUDGET)
    }
    /// Reuse the original request deadline/resource/denial snapshot across the
    /// authoritative initial owner adoption; never restart the operation budget.
    pub(super) async fn begin_authoritative(client: &mut Client) -> Result<Self> {
        let binding = client.master_binding()?;
        let mut scope = Self::begin(client)?;
        scope.run_io(client.validate_session()).await?;
        binding.check(client)?;
        scope.crypto = AsyncCryptoScope::begin(client)?;
        scope.check(client)?;
        Ok(scope)
    }
    fn begin_until(client: &Client, deadline: Instant) -> Result<Self> {
        let value = Self {
            crypto: AsyncCryptoScope::begin(client)?,
            wrapper_expiry: Mutex::new(None),
            operation: client.operation_cancel.clone(),
            master: client.master_capability()?,
            authority: client.task_watch_authority.clone(),
            denial_revision: client.task_watch_authority.cached_denial_revision()?,
            paired_expiry: client.require_credentials()?.paired_session_expires_at,
            deadline,
            private_gate: client.options().private_operation_gate.clone(),
        };
        value.check(client)?;
        Ok(value)
    }
    pub(super) fn check(&self, client: &Client) -> Result<()> {
        client.verify_private_operation()?;
        client.require_canonical_read_profile()?;
        if client.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "cookie_embed_version_scope_unavailable",
                reason: "PERSONAL_FULL_ID_VERSION_CONTENT_ONLY",
            });
        }
        self.crypto.check(client)?;
        self.check_io()?;
        if self
            .wrapper_expiry
            .lock()
            .map_err(|_| Error::Cancelled)?
            .is_some_and(|at| at <= now_ms())
        {
            return Err(Error::Conflict);
        }
        Ok(())
    }
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    pub(super) fn check_original_negative(&self)->Result<()>{self.check_io()?;self.crypto.check_original_operation_negative()}
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    pub(super) fn begin_owned(client:&Client)->Result<Self>{
        let mut scope=Self::begin(client)?;scope.operation=client.current_operation_child();scope.check(client)?;Ok(scope)
    }
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    pub(super) fn original_deadline(&self)->Instant{self.deadline}
    fn check_io(&self) -> Result<()> {
        if self.operation.is_cancelled() || self.authority.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.master.ensure_current()?;
        if let Some(gate) = &self.private_gate {
            gate()?;
        }
        if self.denial_revision != self.authority.cached_denial_revision()? {
            return Err(Error::Cancelled);
        }
        if self.paired_expiry.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Expired);
        }
        if self
            .wrapper_expiry
            .lock()
            .map_err(|_| Error::Cancelled)?
            .is_some_and(|at| at <= now_ms())
        {
            return Err(Error::Conflict);
        }
        if Instant::now() >= self.deadline {
            return Err(Error::Offline);
        }
        Ok(())
    }
    async fn io_denial(&self) -> Error {
        loop {
            if let Err(error) = self.check_io() {
                return error;
            }
            tokio::select! {biased;
                _=self.operation.cancelled()=>return Error::Cancelled,
                _=self.master.cancelled()=>return Error::Cancelled,
                _=self.authority.cancel.cancelled()=>return Error::Cancelled,
                _=crate::platform::time::sleep(Duration::from_millis(25))=>{}
            }
        }
    }
    /// Results passed here are already owned/wiping (Plain JSON, Zeroizing key
    /// bytes), an owned Socket, or unit. Never adopt plaintext after finalcheck.
    pub(super) async fn run_io<T>(
        &self,
        future: impl std::future::Future<Output = Result<T>>,
    ) -> Result<T> {
        self.check_io()?;
        let result = tokio::select! {biased;
            error=self.io_denial()=>Err(error),
            result=crate::platform::time::timeout_at(self.deadline,future)=>result.map_err(|_|Error::Offline)?,
        };
        if matches!(&result, Err(Error::Expired | Error::Forbidden)) {
            return result;
        }
        self.check_io()?;
        result
    }
    pub(super) fn check_chat(&self, client: &Client, id: &str) -> Result<()> {
        self.check(client)?;
        self.crypto.check_chat(client, id)
    }
    pub(super) fn wrapper(&self, row: &Value) -> Result<()> {
        for name in ["wrapper_version", "team_key_epoch"] {
            if let Some(value) = row.get(name).filter(|v| !v.is_null()) {
                match value.as_u64() {
                    Some(1) => {}
                    Some(_) => return Err(Error::Conflict),
                    None => return Err(Error::Protocol),
                }
            }
        }
        if let Some(value) = row.get("expires_at").filter(|v| !v.is_null()) {
            let at = value
                .as_u64()
                .ok_or(Error::Protocol)?
                .checked_mul(1000)
                .ok_or(Error::Protocol)?;
            if at <= now_ms() {
                return Err(Error::Conflict);
            }
            let mut expiry = self.wrapper_expiry.lock().map_err(|_| Error::Cancelled)?;
            *expiry = Some(expiry.map_or(at, |old| old.min(at)));
        }
        Ok(())
    }
}
/// Restricting selected read evidence, never an authentication/storage grant.
/// Retains owner/key/op/ACL/privacy and selected-wrapper expiry to the caller's
/// last plaintext release. Not Clone/Debug/serializable.
pub struct EmbedVersionReadAdmission {
    scope: VersionReadScope,
}
impl EmbedVersionReadAdmission {
    pub fn check(&self, client: &Client) -> Result<()> {
        self.scope.check(client)
    }
}
impl Client {
    /// Additive selected Personal Cookie read, full canonical UUID only.
    /// Reconstructs the original response with the same shared Rust engine as
    /// API-key/npm/Python. Never publishes optional snapshots or a storage ACK.
    pub async fn embed_version_content(&mut self, id: &str, version: i64) -> Result<Value> {
        let (value, admission) = self
            .embed_version_content_with_admission(id, version)
            .await?;
        let value = Plain::new(value);
        admission.check(self)?;
        Ok(value.into_inner())
    }
    pub async fn embed_version_content_with_admission(
        &mut self,
        id: &str,
        version: i64,
    ) -> Result<(Value, EmbedVersionReadAdmission)> {
        if uuid::Uuid::parse_str(id)
            .ok()
            .is_none_or(|v| v.hyphenated().to_string() != id)
        {
            return Err(Error::Invalid("A canonical full embed ID is required."));
        }
        if !(1..=9_007_199_254_740_991).contains(&version) {
            return Err(Error::Invalid("Supply a positive safe integer version."));
        }
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        if self.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "cookie_embed_version_scope_unavailable",
                reason: "PERSONAL_FULL_ID_VERSION_CONTENT_ONLY",
            });
        }
        // Existing authoritative Cookie refresh admits the live owner before
        // taking a full scope; legitimate initial user adoption is not stale IO.
        let binding = self.master_binding()?;
        let mut scope = VersionReadScope::begin(self)?;
        scope.run_io(self.validate_session()).await?;
        binding.check(self)?;
        // Only the existing authoritative refresh may adopt the initial user;
        // keep the original IO deadline/resources/op/negative snapshot intact.
        scope.crypto = AsyncCryptoScope::begin(self)?;
        scope.check(self)?;
        let path = format!("/v1/embeds/{}/versions/{version}", segment(id));
        let mut status = None;
        let fetched = scope
            .run_io(async {
                self.request_task_headers_observed(
                    Method::GET,
                    &format!("{path}?capability=bounded-v1"),
                    None,
                    None,
                    None,
                    None,
                    &mut status,
                )
                .await
                .map(Plain::new)
            })
            .await;
        // Known authoritative auth denials retain their typed priority even
        // when transport revoked the current Client while receiving them.
        if matches!(&fetched, Err(Error::Expired | Error::Forbidden)) {
            return Err(fetched.err().ok_or(Error::Protocol)?);
        }
        scope.check(self)?;
        let value = match fetched {
            Err(_) if status == Some(409) => {
                let value = scope
                    .run_io(async { self.request(Method::GET, &path, None).await.map(Plain::new) })
                    .await?;
                scope.check(self)?;
                value
            }
            other => other?,
        };
        let mut response = value;
        if response["embed_id"].as_str() != Some(id)
            || response["version_number"].as_i64() != Some(version)
        {
            return Err(Error::Protocol);
        }
        if response["content"].is_string() {
            return release_server_content(response, scope, self);
        }
        let mut content = {
            let rows = response["rows"]
                .as_array()
                .filter(|v| !v.is_empty() && v.len() <= 10_000)
                .ok_or(Error::Protocol)?;
            if rows.last().and_then(|r| r["version_number"].as_i64()) != Some(version)
                || rows.iter().any(|r| {
                    r["version_number"]
                        .as_i64()
                        .is_none_or(|n| n < 1 || n > version)
                })
            {
                return Err(Error::Protocol);
            }
            let key = self.version_embed_key(id, &scope).await?;
            scope.check(self)?;
            crate::sdk_embeds::reconstruct_version_rows_with_cancel(
                rows,
                &key,
                &self.operation_cancel,
            )?
        };
        scope.check(self)?;
        response["content"] = Value::String(std::mem::take(&mut *content));
        scope.check(self)?;
        Ok((response.into_inner(), EmbedVersionReadAdmission { scope }))
    }
}
fn release_server_content(
    response: Plain<Value>,
    scope: VersionReadScope,
    client: &Client,
) -> Result<(Value, EmbedVersionReadAdmission)> {
    let content = response["content"].as_str().ok_or(Error::Protocol)?;
    if content.len() > 16 * 1024 * 1024 {
        return Err(Error::Protocol);
    }
    scope.check(client)?;
    Ok((response.into_inner(), EmbedVersionReadAdmission { scope }))
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_version_tests.rs"]
mod tests;
