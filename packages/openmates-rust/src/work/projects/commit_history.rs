//! Committed-version history reads shared by the chat restore (native) and the
//! user restore (native and browser): the encrypted rows that rebuild one
//! embed version, the file's embed key from its Project wrapper, and their
//! replay to text. Pure HTTP plus decryption; nothing here depends on the
//! native-only hosted file writer.

use super::*;
use zeroize::Zeroizing;

/// Why a history replay failed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ReplayError {
    /// A transport, protocol (gapped or empty chain) or crypto failure.
    Core(Error),
    /// A stored patch does not apply; the stable code is `invalid_patch`.
    InvalidPatch,
}

impl From<Error> for ReplayError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}

/// Replay decrypted history rows to the text of their last version: the first
/// row must carry a snapshot, later snapshots restart the chain and patches
/// apply with the stored-version diff rules (`applyVersionPatch`).
///
/// # Errors
/// `Core(Protocol)` for a gapped or empty chain, `Core(Crypto)` for a row the
/// embed key does not open, `InvalidPatch` for a patch that does not apply.
pub(crate) fn replay_rows(
    rows: &[Value],
    embed_key: &[u8; 32],
    version: u64,
) -> std::result::Result<Zeroizing<String>, ReplayError> {
    replay_rows_with(rows, version, |_, _, ciphertext| {
        crypto::server_fields::decrypt_text(ciphertext, embed_key, &[]).map(Zeroizing::new)
    })
}

/// Rebuild a version with a field opener that can resolve mixed encryption epochs.
pub(crate) fn replay_rows_with(
    rows: &[Value],
    version: u64,
    mut open: impl FnMut(u64, &str, &str) -> Result<Zeroizing<String>>,
) -> std::result::Result<Zeroizing<String>, ReplayError> {
    let mut content: Option<Zeroizing<String>> = None;
    let mut expected = None;
    for row in rows {
        let number = row["version_number"]
            .as_u64()
            .filter(|v| *v >= 1)
            .ok_or(Error::Protocol)?;
        if expected.is_some_and(|e| e != number) {
            return Err(Error::Protocol.into());
        }
        expected = Some(number + 1);
        content = Some(
            match (
                row["encrypted_snapshot"].as_str().filter(|s| !s.is_empty()),
                &content,
            ) {
                (Some(snapshot), _) => open(number, "content", snapshot)?,
                (None, Some(previous)) => {
                    let cipher = row["encrypted_patch"].as_str().ok_or(Error::Protocol)?;
                    let patch = open(number, "patch", cipher)?;
                    Zeroizing::new(
                        crate::embed_read::patch::apply_version_patch(previous, &patch)
                            .map_err(|_| ReplayError::InvalidPatch)?,
                    )
                }
                (None, None) => return Err(Error::Protocol.into()),
            },
        );
    }
    if expected != Some(version + 1) {
        return Err(Error::Protocol.into());
    }
    content.ok_or_else(|| Error::Protocol.into())
}

/// The embed key of a Project file from the `project` wrapper of a
/// `/v1/embeds/{id}/encrypted` answer: the wrapper of `project_id` (or one
/// without a project hash, as the server may omit it), sealed with
/// `server_fields` under the Project key, as hosted file writes and adoption
/// store it. `None` when the answer has no such wrapper (an older link whose
/// key only a chat or master wrapper opens).
///
/// # Errors
/// `Forbidden` for an answer about another embed; `Crypto` when the wrapper
/// does not open with the Project key or is not 32 bytes.
pub(crate) fn project_wrapped_embed_key(
    response: &Value,
    embed_id: &str,
    project_id: &str,
    project_key: &[u8; 32],
) -> Result<Option<Key>> {
    if response["embed"]["embed_id"]
        .as_str()
        .is_some_and(|id| id != embed_id)
    {
        return Err(Error::Forbidden);
    }
    let wanted = hash(project_id);
    let wrapper = response["embed_keys"].as_array().and_then(|rows| {
        rows.iter().find_map(|row| {
            let matches = row["key_type"] == "project"
                && row["hashed_project_id"]
                    .as_str()
                    .is_none_or(|h| h == wanted);
            matches
                .then(|| row["encrypted_embed_key"].as_str())
                .flatten()
        })
    });
    let Some(wrapper) = wrapper else {
        return Ok(None);
    };
    let raw = Zeroizing::new(crypto::server_fields::decrypt_bytes(
        wrapper,
        project_key,
        &[],
    )?);
    key_bytes(&raw).map(Some)
}

impl Projects<'_> {
    /// The fresh encrypted head of a file of Project `project_id`
    /// (`GET /v1/embeds/{id}/encrypted`, with this view's Team filter). The route admits
    /// every member of the Project, not only the embed's author.
    ///
    /// # Errors
    /// `Invalid` for a malformed id, `Forbidden` for an answer about another embed,
    /// transport errors.
    pub(crate) async fn project_embed_head(
        &mut self,
        project_id: &str,
        embed_id: &str,
    ) -> Result<Value> {
        uuid(embed_id)?;
        let route = self.path(
            &format!("/v1/embeds/{embed_id}/encrypted"),
            &[("project_id".into(), project_id.into())],
        );
        let response = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if response["embed"]["embed_id"]
            .as_str()
            .is_some_and(|id| id != embed_id)
        {
            return Err(Error::Forbidden);
        }
        Ok(response)
    }

    /// Embed key of a file of Project `project_id` through its Project
    /// wrapper (see [`project_wrapped_embed_key`]). Works in the web Worker:
    /// the Project key is unwrapped through the master binding, and no chat
    /// of the embed needs to be cached.
    ///
    /// # Errors
    /// The Project and embed reads' errors and the wrapper errors.
    pub(crate) async fn project_embed_key(
        &mut self,
        project_id: &str,
        embed_id: &str,
    ) -> Result<Option<Key>> {
        let project = self.resolve(project_id).await?;
        let response = self.project_embed_head(project_id, embed_id).await?;
        project_wrapped_embed_key(&response, embed_id, project_id, &project.key)
    }

    /// Encrypted rows that rebuild `version`: the bounded window from the
    /// nearest snapshot, or the full chain when the server answers that the
    /// window has no snapshot yet (`409 snapshot_required`).
    ///
    /// # Errors
    /// Transport errors, and `Forbidden` when the answer is for another embed
    /// or version.
    pub(crate) async fn version_rows(
        &mut self,
        project_id: &str,
        embed_id: &str,
        version: u64,
    ) -> Result<Vec<Value>> {
        let base = format!("/v1/embeds/{embed_id}/versions/{version}");
        let bounded = self.path(
            &base,
            &[
                ("project_id".into(), project_id.into()),
                ("capability".into(), "bounded-v1".into()),
            ],
        );
        let response = match self
            .backend
            .request(Method::GET, &bounded, None, None)
            .await
        {
            Err(Error::Conflict) => {
                let full = self.path(&base, &[("project_id".into(), project_id.into())]);
                self.backend.request(Method::GET, &full, None, None).await?
            }
            other => other?,
        };
        if response["embed_id"] != embed_id || response["version_number"].as_u64() != Some(version)
        {
            return Err(Error::Forbidden);
        }
        response["rows"].as_array().cloned().ok_or(Error::Protocol)
    }
}

#[cfg(test)]
#[path = "commit_history_tests.rs"]
mod tests;
