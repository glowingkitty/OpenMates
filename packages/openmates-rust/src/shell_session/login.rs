//! Hand-over of a core login to an acknowledgement-style shell profile (the
//! Apple Keychain): the session a `Client` login just installed begins on the
//! profile (`AcknowledgedCredentials::begin_session`) and its snapshot is
//! acknowledged on that client, which a pairing needs before
//! `Client::acknowledge_pair` (relay rule: persist first, then acknowledge).
//! Same order as the terminal app's login and `finish_pair` (`runtime.rs`),
//! including the wipe of a login cancelled after its store.
//! Native only. Plan `apple-client-core-migration` (A2, Apple login
//! hand-over); spec `client-core` credential rules.
use super::{AcknowledgedCredentials, CredentialPersistence};
use crate::{
    client::Client,
    error::{Error, Result},
    local_cache::ByteStore,
};
use tokio_util::sync::CancellationToken;

impl<S: ByteStore + 'static> AcknowledgedCredentials<S> {
    /// Begin the session a login just installed in `client` (password login
    /// or a prepared pairing) on this profile, then mark that exact snapshot
    /// revision acknowledged on `client`. The vault receives the payload
    /// before this returns; nothing is acknowledged on `client` unless the
    /// shell acknowledged the store.
    ///
    /// # Errors
    /// `Authentication` when `client` holds no session; otherwise as
    /// [`Self::begin_session`] (`Invalid` while another session is stored,
    /// `Locked` on an acknowledgement timeout, `Cancelled`); `Cancelled` when
    /// the client's credentials changed meanwhile.
    pub async fn begin_client_session(
        &self,
        client: &mut Client,
        cancel: &CancellationToken,
    ) -> Result<()> {
        let snapshot = client.credential_snapshot().ok_or(Error::Authentication)?;
        let revision = snapshot.revision;
        self.begin_session(snapshot, cancel).await?;
        client.acknowledge_credentials(revision)
    }

    /// Abandon a login whose session [`Self::begin_client_session`] already
    /// stored (the shell's login was cancelled afterwards), in the terminal
    /// app's order: durable revocation and the wipe of the stored
    /// credentials and cache records first (`revoke`, then `clear`), then the
    /// remote logout of `client`'s new server session. The profile ends
    /// signed out; the shell advances its blocking-queue generation and
    /// reports the sign-out itself.
    ///
    /// # Errors
    /// The local revoke or clear error. The remote logout is best effort:
    /// the local wipe has already happened and an unreachable server must
    /// not keep the profile signed in.
    pub async fn abandon_client_session(&self, client: &mut Client) -> Result<()> {
        let local = match self.revoke().await {
            Ok(()) => self.clear().await,
            Err(error) => Err(error),
        };
        // Best effort: the local wipe above is the guarantee.
        let _remote = client.logout().await;
        local
    }

    /// One finish step of a pair login on `client` (after
    /// `Client::submit_pair_pin`): `Ok(false)` while the authorizer has not
    /// delivered the key bundle yet (call again); `Ok(true)` once the paired
    /// session is begun on this profile, stored, acknowledged and the relay
    /// acknowledged (`Client::acknowledge_pair`). After a failed store or
    /// relay acknowledgement the pairing stays prepared, so a repeated call
    /// retries from the store (repeating the begin of the same session keeps
    /// its epoch).
    ///
    /// # Errors
    /// As `Client::finish_pair` (`Expired` for a failed, cancelled or lapsed
    /// pairing, `Authentication`/`Crypto` for a bundle of another account or
    /// a wrong PIN, `Protocol`), as [`Self::begin_client_session`], and as
    /// `Client::acknowledge_pair`.
    pub async fn finish_pair_session(
        &self,
        client: &mut Client,
        cancel: &CancellationToken,
    ) -> Result<bool> {
        if !client.finish_pair().await? {
            return Ok(false);
        }
        self.begin_client_session(client, cancel).await?;
        client.acknowledge_pair().await?;
        Ok(true)
    }
}
