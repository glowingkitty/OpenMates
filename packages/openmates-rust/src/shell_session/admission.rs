//! Fresh server admission of a restored session, bound to its durable initial
//! save. Moved unchanged from the TUI `session_runtime.rs`
//! (`FreshSessionAdmission`); the CLI keeps only its `whoami` formatting.
//! Spec: `client-core` (session authority stays in the shared core).
use super::{CredentialPersistence, ShellSession, current};
use crate::{
    client::{Client, FreshSessionHandoff},
    error::{Error, Result},
    local_cache::{ByteStore, OrderedBlocking},
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Single-use evidence of fresh server admission and durable initial save.
/// The exclusive borrow owns the validated client lane until consumption; no
/// caller can substitute or mutate that client through this guard, and the
/// client cannot change account or Team while the guard exists.
pub struct FreshSessionAdmission<'a> {
    client: &'a mut Client,
    auth_handoff: Option<FreshSessionHandoff>,
    generation: u64,
    ops: OrderedBlocking,
    cancel: CancellationToken,
}

impl<'a> FreshSessionAdmission<'a> {
    /// Validate the session with the server (cancellation waits at most two
    /// seconds for an in-flight validation), then persist. Both must succeed;
    /// a failed save wins over a failed validation. The guard is issued only
    /// while the generation it started at is still current.
    ///
    /// # Errors
    /// `Cancelled`, `Expired`, server authentication errors, persist errors.
    pub fn admit<'b, S: ByteStore + 'static>(
        client: &'a mut Client,
        session: &'b ShellSession<S>,
        credentials: &'b dyn CredentialPersistence,
        cancel: &'b CancellationToken,
    ) -> BoxFuture<'b, Result<Self>>
    where
        'a: 'b,
    {
        Self::admit_for_principal(client, session, credentials, cancel, None, None)
    }

    /// Admit a restored account whose previously authorized local profile is
    /// already visible. Match its principal before saving validation results and
    /// close the temporary local profile read as soon as validation settles.
    ///
    /// # Errors
    /// Admission and persistence errors, or `Expired` if the principal changed.
    pub fn admit_restored<'b, S: ByteStore + 'static>(
        client: &'a mut Client,
        session: &'b ShellSession<S>,
        credentials: &'b dyn CredentialPersistence,
        cancel: &'b CancellationToken,
        principal: String,
        close_local_profile: &'b (dyn Fn() + Send + Sync),
    ) -> BoxFuture<'b, Result<Self>>
    where
        'a: 'b,
    {
        Self::admit_for_principal(
            client, session, credentials, cancel, Some(principal), Some(close_local_profile),
        )
    }

    /// Revalidate an existing client while retaining its in-memory window.
    /// The network response must authenticate the same principal before its
    /// credentials or account state can be persisted.
    ///
    /// # Errors
    /// Admission and persistence errors, or `Expired` if the principal changed.
    pub fn readmit_existing<'b, S: ByteStore + 'static>(
        client: &'a mut Client,
        session: &'b ShellSession<S>,
        credentials: &'b dyn CredentialPersistence,
        cancel: &'b CancellationToken,
    ) -> BoxFuture<'b, Result<Self>>
    where
        'a: 'b,
    {
        let expected = Self::principal(client).map(str::to_owned);
        Box::pin(async move {
            let expected = expected.ok_or(Error::Authentication)?;
            Self::admit_for_principal(client, session, credentials, cancel, Some(expected), None).await
        })
    }

    fn principal(client: &Client) -> Option<&str> {
        ["id", "user_id"]
            .into_iter()
            .filter_map(|key| client.user()[key].as_str())
            .find(|id| !id.is_empty())
    }

    fn admit_for_principal<'b, S: ByteStore + 'static>(
        client: &'a mut Client,
        session: &'b ShellSession<S>,
        credentials: &'b dyn CredentialPersistence,
        cancel: &'b CancellationToken,
        expected: Option<String>,
        close_local_profile: Option<&'b (dyn Fn() + Send + Sync)>,
    ) -> BoxFuture<'b, Result<Self>>
    where
        'a: 'b,
    {
        Box::pin(async move {
            let ops = session.ops().clone();
            let generation = ops.generation();
            let admitted = {
                let validation = async {
                    current(client, &ops, generation, cancel)?;
                    let validation = client.validate_session_for_recovery(cancel).await;
                    if let Some(expected) = expected.as_deref()
                        && (close_local_profile.is_none() || validation.is_ok())
                        && client.session().is_some()
                        && Self::principal(client) != Some(expected)
                    {
                        client.forget_session();
                        return Err(Error::Expired);
                    }
                    let handoff = validation?;
                    current(client, &ops, generation, cancel)?;
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
            if let Some(close_local_profile) = close_local_profile {
                close_local_profile();
            }
            let saved = session.persist(client, credentials).await;
            let auth_handoff = match (admitted, saved) {
                (_, Err(error)) | (Err(error), Ok(())) => return Err(error),
                (Ok(handoff), Ok(())) => handoff,
            };
            current(client, &ops, generation, cancel)?;
            Ok(Self {
                client,
                auth_handoff,
                generation,
                ops,
                cancel: cancel.clone(),
            })
        })
    }

    /// Consume fresh server admission only after its durable initial save and
    /// protected-account check. The SDK retains all one-use/current-op checks.
    ///
    /// # Errors
    /// `Cancelled`/`Expired` when no longer current, SDK refusals.
    pub fn prepare_recovery(mut self) -> Result<()> {
        current(self.client, &self.ops, self.generation, &self.cancel)?;
        if let Some(handoff) = self.auth_handoff.take() {
            self.client
                .use_fresh_session_for_recovery(handoff, &self.cancel)?;
        }
        Ok(())
    }

    /// The admitted account's user record while the admission is current.
    ///
    /// # Errors
    /// `Cancelled`/`Expired`/`Authentication` when no longer current.
    pub fn user(&self) -> Result<&serde_json::Value> {
        current(self.client, &self.ops, self.generation, &self.cancel)?;
        Ok(self.client.user())
    }

    /// Consume the admission for the admitted user record (the CLI formats
    /// `whoami` from it). Checked current at consumption.
    ///
    /// # Errors
    /// As [`Self::user`].
    pub fn into_user(self) -> Result<&'a serde_json::Value> {
        current(self.client, &self.ops, self.generation, &self.cancel)?;
        let client: &'a Client = self.client;
        Ok(client.user())
    }
}
