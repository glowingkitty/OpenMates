//! Cached Personal draft projections for the view model (shared core, native
//! only): a fingerprint of every cached draft so a live refresh can tell which
//! drafts another device changed, and a network-free decode of one cached draft
//! for the composer's offline restore. The strict reads stay in `draft_read.rs`;
//! spec `client-core` (drafts capability, plan `apple-client-core-migration` A5).
use super::*;
use crate::sdk_drafts::DraftRecord;
use zeroize::Zeroize;

/// Comparable identity of one cached draft: its version and both ciphertexts.
/// Holds ciphertext only, never plaintext. Two equal fingerprints mean the
/// same draft bytes, so a server echo of this client's own save compares equal
/// and is not reported as a remote change.
#[derive(Clone, PartialEq, Eq)]
pub(crate) struct DraftFingerprint {
    draft_v: u64,
    markdown: String,
    preview: Option<String>,
}

impl Client {
    /// Fingerprints of every cached chat row that holds draft ciphertext,
    /// keyed by chat id. Empty in a team scope: drafts are Personal only and
    /// team draft reads are refused (`team_draft_read_unavailable`).
    ///
    /// # Errors
    /// `Authentication` without credentials; `Protocol` for a row whose
    /// `draft_v` or preview ciphertext is malformed.
    pub(crate) fn draft_fingerprints(&self) -> Result<BTreeMap<String, DraftFingerprint>> {
        if self.team()?.is_some() {
            return Ok(BTreeMap::new());
        }
        let mut fingerprints = BTreeMap::new();
        for (id, row) in &self.chats {
            let Some(markdown) = row["encrypted_draft_md"].as_str() else {
                continue;
            };
            let draft_v = match row.get("draft_v") {
                None | Some(Value::Null) => 0,
                Some(value) => value.as_u64().ok_or(Error::Protocol)?,
            };
            let preview = match row.get("encrypted_draft_preview") {
                None | Some(Value::Null) => None,
                Some(Value::String(value)) => Some(value.clone()),
                Some(_) => return Err(Error::Protocol),
            };
            fingerprints.insert(
                id.clone(),
                DraftFingerprint {
                    draft_v,
                    markdown: markdown.to_owned(),
                    preview,
                },
            );
        }
        Ok(fingerprints)
    }

    /// The cached draft of Personal chat `id`, decrypted without any network
    /// read; `None` when the cached row holds no draft. Unlike
    /// `get_draft(id, false)` this does not require a fresh chat-list
    /// inventory: callers use it after an authoritative read failed offline
    /// (with the host's offline-cache admission) or right after a live
    /// refresh committed the row.
    ///
    /// # Errors
    /// `Invalid` for a malformed or volatile id; draft read admission errors
    /// (`Authentication`, `Unavailable(team_draft_read_unavailable)`,
    /// `Cancelled`); `Forbidden`/`Protocol` for a row outside the owner's
    /// Personal scope; `Crypto`. Plaintext is wiped when the fence moved.
    pub(crate) async fn cached_draft(&self, id: &str) -> Result<Option<DraftRecord>> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if self.is_ephemeral_chat(id) {
            return Err(Error::Invalid("Volatile chats do not have saved drafts."));
        }
        let admission = self.draft_read_admission()?;
        let Some(row) = self
            .chats
            .get(id)
            .filter(|row| row["encrypted_draft_md"].is_string())
        else {
            return Ok(None);
        };
        let mut draft = self.decode_draft_row_with_capability(row).await?;
        if let Err(error) = admission.check(self) {
            draft.markdown.zeroize();
            draft.preview.zeroize();
            return Err(error);
        }
        Ok(Some(draft))
    }
}
