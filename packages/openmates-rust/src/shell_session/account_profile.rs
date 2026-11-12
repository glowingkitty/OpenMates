//! The last admitted user payload of a shell profile, kept in the core's
//! encrypted cache so a restored session that cannot reach the server
//! (offline start) still knows its account. One record per account: owner
//! `hashed_email`, logical key [`ACCOUNT_PROFILE_CACHE_KEY`], sealed with the
//! session's master key under the session context AAD like every sync cache
//! record, so another account can neither find nor open it; sign-out, account
//! switch and wipe delete it with the other `cache-*` records. Never logged.
//! Spec `client-core.cache`.
use super::ShellSession;
use crate::{
    client::Client,
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use serde_json::{Value, json};

/// Logical cache key of the admitted user record (enters the file name and
/// the record AAD; distinct from every `sync-*` key).
pub(crate) const ACCOUNT_PROFILE_CACHE_KEY: &str = "account-profile";
/// Version of the stored record shape `{"version": 1, "user": {...}}`.
const RECORD_VERSION: u64 = 1;

/// The payload names the account (`id` or `user_id`), i.e. the server
/// admitted it; a verification profile or an empty payload does not.
fn names_account(user: &Value) -> bool {
    ["id", "user_id"]
        .into_iter()
        .any(|key| user[key].as_str().is_some_and(|id| !id.is_empty()))
}

impl<S: ByteStore + 'static> ShellSession<S> {
    /// Store the client's admitted user payload as this account's cached
    /// profile, replacing the previous one. Call it after every admission.
    ///
    /// # Errors
    /// `Authentication` without a session, `Invalid` when the payload names
    /// no account (nothing written), `Cancelled` when the generation moved,
    /// cache errors.
    pub fn save_admitted_user<'a>(&'a self, client: &'a Client) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let session = client.session().ok_or(Error::Authentication)?;
            let user = client.user();
            if !names_account(user) {
                return Err(Error::Invalid("The user payload names no account."));
            }
            let record = json!({"version": RECORD_VERSION, "user": user});
            self.cache()
                .write_cache(
                    session.hashed_email.clone(),
                    ACCOUNT_PROFILE_CACHE_KEY.to_owned(),
                    session.master_key.clone(),
                    record,
                )
                .await
        })
    }

    /// This account's cached user payload from its last admission, or `None`
    /// when none is stored (never admitted on this profile, or wiped).
    ///
    /// # Errors
    /// `Authentication` without a session, `Protocol` for a record of another
    /// shape, cache errors (an unreadable or foreign record fails closed).
    pub fn cached_user<'a>(&'a self, client: &'a Client) -> BoxFuture<'a, Result<Option<Value>>> {
        Box::pin(async move {
            let session = client.session().ok_or(Error::Authentication)?;
            let read = self
                .cache()
                .read_cache(
                    session.hashed_email.clone(),
                    ACCOUNT_PROFILE_CACHE_KEY.to_owned(),
                    session.master_key.clone(),
                )
                .await?;
            let Some(mut record) = read else {
                return Ok(None);
            };
            let user = record
                .get_mut("user")
                .map(Value::take)
                .unwrap_or(Value::Null);
            if record["version"] != json!(RECORD_VERSION) || !names_account(&user) {
                return Err(Error::Protocol);
            }
            Ok(Some(user))
        })
    }
}
