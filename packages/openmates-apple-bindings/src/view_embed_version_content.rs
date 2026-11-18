//! Reconstructed content of one embed version for the Apple shell. The core
//! (`Client::embed_version_content`) owns the bounded-v1 fetch, response
//! validation, key lookup, decryption and snapshot/patch reconstruction; this
//! module only marshals the plaintext and maps refusals to `EmbedEditError`
//! (`Transport { protocol }` for an invalid or oversized response,
//! `Unavailable` for Team scope, `AccessDenied`/`Authentication` when access
//! changed, `Cancelled`). Replaces the Swift `EmbedVersionReconstruction`.
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_embeds::{EmbedEditError, EmbedScopeRecord};
use openmates_sdk::error::Error;
use std::sync::Arc;
use zeroize::Zeroizing;

/// One reconstructed embed version.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedVersionContentRecord {
    /// Version the content belongs to.
    pub version: i64,
    /// The embed's stored plaintext (TOON/JSON string) at that version.
    pub content: String,
}

#[uniffi::export]
impl ViewModelCore {
    /// Read the plaintext of `version` of `embed_id`, reconstructed in the
    /// core. `scope` is accepted for call-site symmetry with
    /// `embedVersionHistory`; the core reads the Personal account only and
    /// refuses Team accounts as `Unavailable`.
    ///
    /// # Errors
    /// `Validation` for a non canonical embed id or version below 1;
    /// `Transport { protocol }` for an invalid or too large response;
    /// `AccessDenied`/`Authentication`/`SessionExpired` when access changed;
    /// `Unavailable` for Team scope; `Offline`; `Cancelled`.
    pub async fn embed_version_content(
        &self,
        embed_id: String,
        scope: Option<EmbedScopeRecord>,
        version: i64,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<EmbedVersionContentRecord, EmbedEditError> {
        let _ = scope;
        self.embed_command(cancellation, move |client| {
            Box::pin(async move {
                let value = client.embed_version_content(&embed_id, version).await?;
                let content =
                    Zeroizing::new(value["content"].as_str().ok_or(Error::Protocol)?.to_owned());
                Ok(EmbedVersionContentRecord {
                    version,
                    content: content.to_string(),
                })
            })
        })
        .await
    }
}
