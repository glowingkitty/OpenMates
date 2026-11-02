//! Application-owned durable credential boundary shared by command and terminal
//! consumers. The SDK only emits explicit credential snapshots; it performs no
//! profile discovery, prompts, keyring access or credential persistence.
use crate::{
    client::Client,
    error::{Error, Result},
    runtime_store::RuntimeStore,
    storage::Session,
};
use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub fn cache_key(session: &Session) -> String {
    format!(
        "sync-{}",
        session.active_team_id.as_deref().unwrap_or("personal")
    )
}

// Digests bind protected restoration to the exact loaded credential snapshot.
// The temporary serialized credential bytes are wiped and never exposed.
fn credential_digest(client: &Client) -> Result<[u8; 32]> {
    let session = client.session().ok_or(Error::Authentication)?;
    session_digest(session)
}
fn session_digest(session: &Session) -> Result<[u8; 32]> {
    let encoded = Zeroizing::new(serde_json::to_vec(session)?);
    Ok(Sha256::digest(encoded.as_slice()).into())
}
fn current(
    client: &Client,
    store: &RuntimeStore,
    generation: u64,
    cancel: &CancellationToken,
) -> Result<()> {
    if cancel.is_cancelled() || store.generation() != generation {
        return Err(Error::Cancelled);
    }
    let session = client.session().ok_or(Error::Authentication)?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::Protocol)?
        .as_millis();
    if session
        .paired_session_expires_at
        .is_some_and(|expires| u128::from(expires) <= now)
    {
        return Err(Error::Expired);
    }
    Ok(())
}

/// Restore only the selected durable profile's protected ciphertext before its
/// first save. This publishes no output and grants no server authentication.
/// Read/shape/context failures preserve the existing on-disk profile and cache.
pub async fn restore_protected_cache(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<()> {
    let generation = store.generation();
    current(client, store, generation, cancel)?;
    // RuntimeStore authenticates its envelope/AAD. Also require that envelope's
    // current session to be the one loaded into this Client, including API,
    // Team, owner, key, creation time and paired-session deadline.
    let durable = store.load(passphrase).await?.ok_or(Error::Authentication)?;
    if session_digest(&durable)? != credential_digest(client)? {
        return Err(Error::Cancelled);
    }
    let snapshot = store
        .read_cache(
            durable.hashed_email.clone(),
            cache_key(&durable),
            durable.master_key.clone(),
        )
        .await?;
    current(client, store, generation, cancel)?;
    if let Some(snapshot) = snapshot {
        if let Err(error) = client.restore_authenticated_ciphertext_snapshot(&snapshot) {
            // SDK restoration can parse several fields before a later failure.
            client.forget_session();
            return Err(error);
        }
    }
    if let Err(error) = current(client, store, generation, cancel) {
        client.forget_session();
        return Err(error);
    }
    Ok(())
}

/// Conservative native command admission. The immediately following initial
/// FreshSessionAdmission save durably publishes this removal before dispatch.
/// Whoami and eligible same-scope Personal lists are the preservation paths.
/// A list cache miss separately revokes durably before foreground recovery.
pub fn prepare_command_cache_admission(client: &mut Client, invocation: &crate::cli::Invocation) {
    let preserve =
        invocation.command_path() == "whoami" || same_personal_chat_list_scope(client, invocation);
    if !preserve {
        client.invalidate_chat_list_freshness();
    }
}

/// Explicit --personal is scope-equivalent only while the admitted profile is
/// already Personal and contains no Direct rows. Eligibility grants no auth,
/// freshness, recovery clearance or output publication; those guards stay in
/// the existing warm read. Real Team transitions keep the foreground path and
/// SDK set_team retains its unconditional invalidation semantics.
pub(crate) fn same_personal_chat_list_scope(
    client: &Client,
    invocation: &crate::cli::Invocation,
) -> bool {
    invocation.command_path() == "chats list"
        && !invocation.has("team")
        && (!invocation.has("personal") || invocation.boolean("personal"))
        && client.supports_cached_default_chat_list()
}

/// A durable pre-dispatch fence for recovery, TUI and other uncertain effects.
/// Failure refuses dispatch; a crash afterwards restores no stale receipt even
/// if neither a completion checkpoint nor the final operation save exists yet.
pub async fn revoke_chat_cache_before_dispatch(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<()> {
    let generation = store.generation();
    current(client, store, generation, cancel)?;
    client.invalidate_chat_list_freshness();
    persist(client, store, passphrase).await?;
    current(client, store, generation, cancel)
}

/// Single-use evidence of fresh server admission and durable initial save.
/// The exclusive borrow owns the validated Client lane until consumption; no
/// caller can substitute or mutate that Client through this guard.
///
/// A separately authenticated Client cannot be supplied to the formatter:
/// ```compile_fail
/// use openmates::{client::Client, cli::Invocation,
///     runtime_store::RuntimeStore, session_runtime::FreshSessionAdmission};
/// use tokio_util::sync::CancellationToken;
/// async fn replace(client: &mut Client, other: &Client, store: &RuntimeStore,
///     invocation: &Invocation, cancel: &CancellationToken) {
///     let admission = FreshSessionAdmission::admit(client, store, None, cancel).await.unwrap();
///     let _ = admission.whoami_output(invocation, other);
/// }
/// ```
/// The admitted Client cannot change account or Team while its guard exists:
/// ```compile_fail
/// use openmates::{client::Client, cli::Invocation,
///     runtime_store::RuntimeStore, session_runtime::FreshSessionAdmission};
/// use tokio_util::sync::CancellationToken;
/// async fn mutate(client: &mut Client, store: &RuntimeStore,
///     invocation: &Invocation, cancel: &CancellationToken) {
///     let admission = FreshSessionAdmission::admit(client, store, None, cancel).await.unwrap();
///     client.set_team(None).unwrap();
///     let _ = admission.whoami_output(invocation);
/// }
/// ```
pub struct FreshSessionAdmission<'a> {
    client: &'a mut Client,
    auth_handoff: Option<crate::client::FreshSessionHandoff>,
    generation: u64,
    store: RuntimeStore,
    cancel: CancellationToken,
}
impl<'a> FreshSessionAdmission<'a> {
    pub async fn admit(
        client: &'a mut Client,
        store: &RuntimeStore,
        passphrase: Option<Zeroizing<String>>,
        cancel: &CancellationToken,
    ) -> Result<Self> {
        let generation = store.generation();
        let admitted = {
            let validation = async {
                current(client, store, generation, cancel)?;
                let handoff = client.validate_session_for_recovery(cancel).await?;
                current(client, store, generation, cancel)?;
                Ok(handoff)
            };
            tokio::pin!(validation);
            tokio::select! {
                biased;
                result = &mut validation => result,
                _ = cancel.cancelled() => tokio::time::timeout(
                    std::time::Duration::from_secs(2), &mut validation
                ).await.unwrap_or(Err(Error::Cancelled)),
            }
        };
        // Header-first rotation is durable even if validation/body/cancellation
        // fails. This save stays OUTSIDE the bounded validation future, with
        // the original priority: persistence failure wins validation failure.
        let saved = persist(client, store, passphrase).await;
        let auth_handoff = match (admitted, saved) {
            (_, Err(error)) | (Err(error), Ok(())) => return Err(error),
            (Ok(handoff), Ok(())) => handoff,
        };
        current(client, store, generation, cancel)?;
        Ok(Self {
            client,
            auth_handoff,
            generation,
            store: store.clone(),
            cancel: cancel.clone(),
        })
    }
    /// Consume fresh server admission only after its durable initial save and
    /// protected-account check. The SDK retains all one-use/current-op checks.
    pub fn prepare_recovery(mut self) -> Result<()> {
        current(self.client, &self.store, self.generation, &self.cancel)?;
        if let Some(handoff) = self.auth_handoff.take() {
            self.client
                .use_fresh_session_for_recovery(handoff, &self.cancel)?;
        }
        Ok(())
    }
    pub fn user(&self) -> Result<&serde_json::Value> {
        current(self.client, &self.store, self.generation, &self.cancel)?;
        Ok(self.client.user())
    }
    /// Consume the original admitted Client lane after the trusted-account
    /// check. The application retains its final PendingOutput persistence fence.
    pub fn whoami_output(
        self,
        invocation: &crate::cli::Invocation,
    ) -> std::result::Result<crate::cli::CliOutput, crate::cli::CliError> {
        current(self.client, &self.store, self.generation, &self.cancel)?;
        crate::cli::admitted_whoami_output(invocation, self.client.user())
    }
}

/// Acknowledge precisely the revision that was saved, only after durable cache
/// publication succeeds. Pairing admission cannot acknowledge an unsaved grant.
pub async fn persist(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
) -> Result<()> {
    if let Some(snapshot) = client.credential_snapshot() {
        let session = snapshot.session;
        // Capacity refusal must precede credential replacement as well as cache
        // publication. Reuse this exact snapshot; no additional history clone.
        let generation = store.generation_guard();
        let cache = store.prepare_cache(client.ciphertext_snapshot()).await?;
        if !generation.is_current() { return Err(Error::Cancelled); }
        store.save(session.clone(), passphrase).await?;
        if !generation.is_current() { return Err(Error::Cancelled); }
        store
            .write_prepared_cache(
                session.hashed_email.clone(),
                cache_key(&session),
                session.master_key.clone(),
                cache,
            )
            .await?;
        if !generation.is_current() { return Err(Error::Cancelled); }
        client.acknowledge_credentials(snapshot.revision)?;
    } else {
        // A revocation response can clear the SDK credentials before an error
        // returns. Never leave the previously persisted session restorable.
        store.clear().await?;
    }
    Ok(())
}

/// Local revocation runs even if remote logout is unavailable. Store ordering
/// fences earlier started writes, while SDK logout drops live key material.
pub async fn logout(client: &mut Client, store: &RuntimeStore) -> Result<()> {
    let (local, remote) = tokio::join!(store.clear(), client.logout());
    local?;
    remote
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn cleared_sdk_credentials_remove_durable_session_and_owner_cache() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let store = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let session = Session {
            api_url: "https://api.example.test".into(),
            session_id: "synthetic-session".into(),
            cookies: std::collections::BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let mut client = Client::new(&session.api_url.clone(), Some(session)).unwrap();
        let secret = Some(Zeroizing::new("synthetic vault password".to_owned()));
        persist(&mut client, &store, secret.clone()).await.unwrap();
        assert!(directory.path().join("session.json").exists());
        assert!(std::fs::read_dir(directory.path()).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("cache-")
        }));
        client.take_session();
        persist(&mut client, &store, secret).await.unwrap();
        assert!(store.load(None).await.unwrap().is_none());
        assert!(!directory.path().join("session.json").exists());
        assert!(!std::fs::read_dir(directory.path()).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("cache-")
        }));
    }
}
