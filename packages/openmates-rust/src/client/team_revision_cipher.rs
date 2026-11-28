//! Shared core AES-GCM envelope for stored Team embed revisions after key rotation.
//! The Team epoch key derives a different key for each item, separate from its live
//! packet key and the legacy embed key. See live-collab.keys.rotation-on-removal.

use crate::client::{Client, segment};
use crate::client::embed_write::keys::{NonceSource, decrypt_text, encrypt_text};
use crate::crypto::Key;
use crate::error::{Error, Result};
use crate::work::ReplayError;
use reqwest::Method;
use serde_json::Value;
use std::collections::{HashMap, hash_map::Entry};
use zeroize::Zeroizing;

const PREFIX: &str = "OMRV1.";

/// One item's stored-revision key at a specific Team epoch. Head content and
/// its identical history snapshot share a field domain; derived text, patches
/// and preview fields use their own domain.
pub(crate) struct TeamRevisionCipher {
    key: Key,
    item_id: String,
    epoch: u32,
}

impl TeamRevisionCipher {
    /// Derives the item key from a rotated Team key. Epoch one is legacy.
    pub(in crate::client) fn new(team_key: &Key, item_id: &str, epoch: u32) -> Result<Self> {
        if !(2..=i32::MAX as u32).contains(&epoch) {
            return Err(Error::Protocol);
        }
        let hkdf =
            hkdf::Hkdf::<sha2::Sha256>::new(Some(b"openmates-team-revision-v1"), team_key.as_ref());
        let mut key = Zeroizing::new([0; 32]);
        let info = [epoch.to_be_bytes().as_slice(), item_id.as_bytes()].concat();
        hkdf.expand(&info, key.as_mut())
            .map_err(|_| Error::Crypto)?;
        Ok(Self {
            key,
            item_id: item_id.to_owned(),
            epoch,
        })
    }

    fn aad(&self, version: i64, field: &str) -> String {
        format!(
            "om-stored-revision-v1:{}:{version}:{field}:{}",
            self.epoch, self.item_id
        )
    }

    /// Seals the field using its version and item identity as associated data.
    pub(crate) fn seal(
        &self,
        version: i64,
        field: &str,
        plaintext: &str,
        nonces: &mut impl NonceSource,
    ) -> Result<String> {
        let payload = encrypt_text(
            plaintext,
            &self.key,
            Some(&self.aad(version, field)),
            nonces,
        )?;
        Ok(format!("{PREFIX}{}.{payload}", self.epoch))
    }

    /// Opens a matching field and rejects a frame from another epoch.
    pub(in crate::client) fn open(
        &self,
        version: i64,
        field: &str,
        ciphertext: &str,
    ) -> Result<Zeroizing<String>> {
        let (epoch, payload) = envelope(ciphertext)?.ok_or(Error::Crypto)?;
        if epoch != self.epoch {
            return Err(Error::Crypto);
        }
        decrypt_text(payload, &self.key, Some(&self.aad(version, field)))
    }
}

impl Client {
    /// Opens an epoch-framed Project head for a browser reader. Returns None
    /// for a legacy ciphertext, whose existing read path is still supported.
    ///
    /// # Errors
    /// Scope, membership, transport or authentication failures.
    #[doc(hidden)]
    pub async fn open_team_revision_content(
        &mut self,
        team: &str,
        embed_id: &str,
        version: i64,
        ciphertext: &str,
    ) -> Result<Option<Zeroizing<String>>> {
        let Some(epoch) = ciphertext_epoch(ciphertext)? else {
            return Ok(None);
        };
        uuid::Uuid::parse_str(team).map_err(|_| Error::Protocol)?;
        uuid::Uuid::parse_str(embed_id).map_err(|_| Error::Protocol)?;
        if !(1..=i64::from(i32::MAX)).contains(&version) {
            return Err(Error::Protocol);
        }
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        let scope = crate::client::sync_capability::AsyncCryptoScope::begin(self)?;
        let cipher = self
            .team_revision_cipher(team, embed_id, Some(epoch))
            .await?
            .ok_or(Error::Crypto)?;
        scope.check(self)?;
        self.verify_private_operation()?;
        cipher.open(version, "content", ciphertext).map(Some)
    }

    /// Opens a stored snapshot and extracts the editor's text for version history.
    ///
    /// # Errors
    /// The same errors as [`Self::open_team_revision_content`] or an invalid snapshot.
    #[doc(hidden)]
    pub async fn open_team_revision_text(
        &mut self,
        team: &str,
        embed_id: &str,
        version: i64,
        ciphertext: &str,
    ) -> Result<Option<Zeroizing<String>>> {
        let Some(raw) = self
            .open_team_revision_content(team, embed_id, version, ciphertext)
            .await?
        else {
            return Ok(None);
        };
        let fields = crate::work::decode_content_fields(&raw).ok_or(Error::Protocol)?;
        let text = ["html", "table", "slides_markup", "code", "content"]
            .into_iter()
            .find_map(|name| fields.iter().find(|(key, _)| key == name)?.1.as_str())
            .ok_or(Error::Protocol)?;
        Ok(Some(Zeroizing::new(text.to_owned())))
    }

    /// Resolves a stored revision's historical key, or the currently committed
    /// Team key for a new revision. Pending rotations refuse new seals.
    pub(crate) async fn team_revision_cipher(
        &mut self,
        team: &str,
        embed_id: &str,
        historical_epoch: Option<u32>,
    ) -> Result<Option<TeamRevisionCipher>> {
        let row = self.team_key_row(team).await?;
        if historical_epoch.is_none() && row["rotation_pending"] == true {
            return Err(Error::Conflict);
        }
        let epoch = row["team_key_epoch"]
            .as_u64()
            .and_then(|epoch| u32::try_from(epoch).ok())
            .filter(|epoch| *epoch >= 1)
            .ok_or(Error::Protocol)?;
        let requested = historical_epoch.unwrap_or(epoch);
        if requested > epoch {
            return Err(Error::Protocol);
        }
        if requested == 1 {
            return Ok(None);
        }
        let claimed = self.claim_sealed_team_key(team, &row).await?;
        let wrapper = claimed
            .as_deref()
            .or_else(|| row["encrypted_team_key"].as_str())
            .ok_or(Error::Protocol)?;
        let current_key = self.work_unwrap_with_master(wrapper).await?;
        let key = if requested == epoch {
            current_key
        } else {
            let chain = row["encrypted_previous_team_keys"]
                .as_str()
                .ok_or(Error::Protocol)?;
            crate::client::previous_team_keys(chain, &current_key)?
                .into_iter()
                .find_map(|(older, key)| (older == u64::from(requested)).then_some(key))
                .ok_or(Error::Crypto)?
        };
        Ok(Some(TeamRevisionCipher::new(&key, embed_id, requested)?))
    }

    /// Reads a Team chat revision through the membership-checked history route.
    /// The supplied embed key opens only the legacy rows in the returned chain.
    pub(in crate::client) async fn read_team_chat_revision(
        &mut self,
        team: &str,
        chat: &str,
        embed_id: &str,
        version: i64,
        key: &Key,
    ) -> Result<Zeroizing<String>> {
        if !(1..=i64::from(i32::MAX)).contains(&version) {
            return Err(Error::Protocol);
        }
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        let scope = crate::client::sync_capability::AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat)?;
        let path = format!(
            "/v1/embeds/{}/versions/{version}?team_id={}&chat_id={}",
            segment(embed_id),
            segment(team),
            segment(chat),
        );
        let bounded = format!("{path}&capability=bounded-v1");
        let response = match self.request(Method::GET, &bounded, None).await {
            Err(Error::Conflict) => {
                scope.check_chat(self, chat)?;
                self.request(Method::GET, &path, None).await?
            }
            other => other?,
        };
        scope.check_chat(self, chat)?;
        if response["embed_id"] != embed_id || response["version_number"].as_i64() != Some(version) {
            return Err(Error::Protocol);
        }
        let rows = response["rows"].as_array().ok_or(Error::Protocol)?;
        let content = self
            .replay_stored_revision_history(Some(team), embed_id, rows, key, version as u64)
            .await
            .map_err(|error| match error {
                ReplayError::Core(error) => error,
                ReplayError::InvalidPatch => Error::Protocol,
            })?;
        scope.check_chat(self, chat)?;
        self.verify_private_operation()?;
        Ok(content)
    }

    /// Replay mixed legacy and Team-epoch rows of an authorized embed.
    pub(in crate::client) async fn replay_stored_revision_history(
        &mut self,
        team: Option<&str>,
        embed_id: &str,
        rows: &[Value],
        key: &[u8; 32],
        version: u64,
    ) -> std::result::Result<Zeroizing<String>, ReplayError> {
        let mut ciphers = HashMap::new();
        for row in rows {
            for ciphertext in ["encrypted_snapshot", "encrypted_patch"]
                .iter()
                .filter_map(|field| row[field].as_str())
            {
                if let Some(epoch) = ciphertext_epoch(ciphertext)?
                    && let Entry::Vacant(entry) = ciphers.entry(epoch)
                {
                    let team = team.ok_or(Error::Forbidden)?;
                    let cipher = self
                        .team_revision_cipher(team, embed_id, Some(epoch))
                        .await?
                        .ok_or(Error::Crypto)?;
                    entry.insert(cipher);
                }
            }
        }
        crate::work::replay_rows_with(rows, version, |number, field, ciphertext| {
            match ciphertext_epoch(ciphertext)? {
                Some(epoch) => {
                    let number = i64::try_from(number).map_err(|_| Error::Protocol)?;
                    ciphers
                        .get(&epoch)
                        .ok_or(Error::Crypto)?
                        .open(number, field, ciphertext)
                }
                None => crate::crypto::server_fields::decrypt_text(ciphertext, key, &[])
                    .map(Zeroizing::new),
            }
        })
    }
}

/// The declared epoch, before authentication, for looking up the applicable key.
pub(in crate::client) fn ciphertext_epoch(ciphertext: &str) -> Result<Option<u32>> {
    Ok(envelope(ciphertext)?.map(|(epoch, _)| epoch))
}

fn envelope(ciphertext: &str) -> Result<Option<(u32, &str)>> {
    let Some(rest) = ciphertext.strip_prefix(PREFIX) else {
        return Ok(None);
    };
    let (tag, payload) = rest.split_once('.').ok_or(Error::Crypto)?;
    let epoch = tag.parse::<u32>().map_err(|_| Error::Crypto)?;
    if !(2..=i32::MAX as u32).contains(&epoch) || tag != epoch.to_string() || payload.is_empty() {
        return Err(Error::Crypto);
    }
    Ok(Some((epoch, payload)))
}

#[cfg(test)]
#[path = "team_revision_cipher_tests.rs"]
mod tests;
