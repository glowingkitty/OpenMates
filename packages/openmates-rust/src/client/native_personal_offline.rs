//! Prior native Personal admission for local cache display only.
//! The terminal stores the receipt in its encrypted vault. It never restores
//! a live Client principal or authorizes a server call (architecture.sync).
use super::*;
use serde::{Deserialize, Serialize};

const TTL_MS: u64 = 7 * 24 * 60 * 60 * 1000;

/// Local receipt transported only through the native vault's authenticated
/// record. It is never an online credential or a grant by itself.
#[doc(hidden)]
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativePersonalOfflineReceipt {
    version: u8,
    principal: String,
    profile: [u8; 32],
    issued_at: u64,
    expires_at: u64,
}

/// Non-importable evidence produced by a live acknowledged client.
#[doc(hidden)]
pub struct NativePersonalOfflineIssuance(NativePersonalOfflineReceipt);

impl NativePersonalOfflineIssuance {
    /// Consume this online issuance at the shell's vault boundary.
    ///
    /// # Errors
    /// Protocol error if the protected payload cannot be encoded.
    pub fn into_vault_record(self) -> Result<Value> {
        serde_json::to_value(self.0).map_err(Error::from)
    }
}

impl NativePersonalOfflineReceipt {
    /// Absolute deadline for already-cached plaintext publications.
    pub fn expires_at(&self) -> u64 {
        self.expires_at
    }

    /// Whether this record applies to the current API/app/profile and key
    /// generation. A stale local record must not veto new online admission.
    pub fn belongs_to_profile(&self, client: &Client) -> bool {
        client.native_personal_profile_binding() == Ok(self.profile)
    }

    /// Reconnection may replace this local view only for the same live owner.
    pub fn matches_online_principal(&self, client: &Client) -> bool {
        native_principal(client) == Some(self.principal.as_str()) && self.belongs_to_profile(client)
    }

    pub(super) fn cache_scope(&self, client: &Client) -> Result<(String, String)> {
        let session = client.require_session()?;
        let now = now_ms();
        if self.version != 1
            || self.principal.is_empty()
            || self.principal.len() > 128
            || native_principal(client).is_some_and(|owner| owner != self.principal)
            || now < self.issued_at
            || now >= self.expires_at
            || self.expires_at.saturating_sub(self.issued_at) > TTL_MS
            || session
                .paired_session_expires_at
                .is_some_and(|expiry| self.expires_at > expiry)
            || self.profile != client.native_personal_profile_binding()?
        {
            return Err(Error::Forbidden);
        }
        Ok((
            sha256(&self.principal),
            sha256(&serde_json::to_string(&(
                client.base.as_str(),
                &session.hashed_email,
                &session.active_team_id,
            ))?),
        ))
    }
}

fn native_principal(client: &Client) -> Option<&str> {
    ["id", "user_id"]
        .into_iter()
        .find_map(|key| client.user[key].as_str().filter(|id| !id.is_empty()))
}

pub(super) fn personal_saved_row(row: &Value) -> bool {
    let unset = |field| {
        row.get(field)
            .is_none_or(|value| value.is_null() || value.as_str() == Some(""))
    };
    (unset("chat_visibility") || row["chat_visibility"].as_str() == Some("private"))
        && unset("team_id")
        && unset("hashed_team_id")
        && !sync::draft_only(row)
}

impl Client {
    fn native_personal_profile_binding(&self) -> Result<[u8; 32]> {
        use sha2::{Digest, Sha256};
        let session = self.require_session()?;
        if self.options.identity != ClientIdentity::Cli || self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        let profile = zeroize::Zeroizing::new(serde_json::to_vec(&(
            self.base.as_str(),
            self.app_url(),
            &session.session_id,
            &session.hashed_email,
            &session.user_email_salt,
            session.created_at,
        ))?);
        let mut hash = Sha256::new();
        hash.update(b"openmates-native-personal-offline-profile-v1\0");
        hash.update(profile.as_slice());
        hash.update(session.master_key.as_ref());
        Ok(hash.finalize().into())
    }

    /// Issue evidence only after genuine online admission and durable
    /// acknowledgement in the current Personal account.
    ///
    /// # Errors
    /// Expired, revoked, non-Personal, or unacknowledged clients are refused.
    #[doc(hidden)]
    pub fn issue_native_personal_offline_receipt(
        &self,
        monitor: &ChatMonitor,
    ) -> Result<NativePersonalOfflineIssuance> {
        self.verify_private_operation()?;
        let owner = self.chat_owner_lease(Some(monitor), None)?;
        let session = self.require_session()?;
        if !monitor.is_valid()
            || !owner.is_valid()
            || self.credential_ack != self.credential_revision
        {
            return Err(Error::Cancelled);
        }
        let issued_at = now_ms();
        let deadline = issued_at.saturating_add(TTL_MS);
        Ok(NativePersonalOfflineIssuance(
            NativePersonalOfflineReceipt {
                version: 1,
                principal: native_principal(self)
                    .ok_or(Error::Authentication)?
                    .to_owned(),
                profile: self.native_personal_profile_binding()?,
                issued_at,
                expires_at: deadline.min(session.paired_session_expires_at.unwrap_or(deadline)),
            },
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn personal_offline_receipt_rejects_expiry_team_and_changed_profile_or_principal() {
        let session = super::super::sdk_boundary_tests::session();
        let mut client = Client::new(&session.api_url, Some(session.clone())).unwrap();
        client.set_identity(ClientIdentity::Cli);
        let now = now_ms();
        let mut receipt = NativePersonalOfflineReceipt {
            version: 1,
            principal: "original-owner".into(),
            profile: client.native_personal_profile_binding().unwrap(),
            issued_at: now.saturating_sub(1000),
            expires_at: now + 60_000,
        };
        assert!(receipt.cache_scope(&client).is_ok());
        assert!(
            client.user().is_null(),
            "opening the receipt never installs a live owner"
        );
        client.user = json!({"id":"different-owner"});
        assert!(!receipt.matches_online_principal(&client));
        assert!(receipt.cache_scope(&client).is_err());
        client.user = json!({"id":"original-owner"});
        assert!(receipt.matches_online_principal(&client));
        receipt.expires_at = now;
        assert!(receipt.cache_scope(&client).is_err());
        receipt.expires_at = now + 60_000;

        client
            .set_team(Some("11111111-1111-4111-8111-111111111111"))
            .unwrap();
        assert!(receipt.cache_scope(&client).is_err());
        let mut rotated = session;
        rotated.master_key = zeroize::Zeroizing::new([71; 32]);
        let api = rotated.api_url.clone();
        client.reset(&api, Some(rotated)).unwrap();
        assert!(receipt.cache_scope(&client).is_err());
    }
}
