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
        Box::pin(async move {
            let ops = session.ops().clone();
            let generation = ops.generation();
            let admitted = {
                let validation = async {
                    current(client, &ops, generation, cancel)?;
                    let handoff = client.validate_session_for_recovery(cancel).await?;
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
