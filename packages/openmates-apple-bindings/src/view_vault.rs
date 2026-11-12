//! Adapters between the Swift stores and the core for `ViewModelCore`
//! (extracted from `view_core.rs`): the Keychain `CredentialStore` as the
//! core's `CredentialVault` and the classification of store and cache
//! directory failures. Bindings only marshal. Plan `apple-client-core-migration`.
use crate::CoreError;
use crate::core::CredentialSnapshotRecord;
use crate::view_core::CredentialStore;
use openmates_sdk::{
    error::{Error, Result},
    local_cache::ByteStoreError,
    shell_session::CredentialVault,
};
use std::sync::Arc;
use zeroize::Zeroizing;

/// Classification of a Swift store failure for the core. The Keychain can
/// only report "locked" or a store failure; anything else is a store failure.
fn store_error(error: CoreError) -> Error {
    match error {
        CoreError::Locked => Error::Locked,
        CoreError::Cancelled => Error::Cancelled,
        _ => Error::Io,
    }
}

/// Classification of a cache directory open failure: configuration mistakes
/// (relative or non-normalized container, a name that is not one plain
/// component) are `Invalid`; file-system failures keep the core mapping (`Io`).
pub(crate) fn store_open_error(error: ByteStoreError) -> CoreError {
    let message = match error {
        ByteStoreError::RelativePath => "The cache container must be an absolute path.",
        ByteStoreError::NonNormalizedPath => "The cache container must be a normalized path.",
        ByteStoreError::InvalidName => "The cache directory name must be one plain path component.",
        other => return Error::from(other).into(),
    };
    CoreError::Invalid {
        message: message.to_owned(),
    }
}

/// The Swift `CredentialStore` as the core's `CredentialVault`.
pub(crate) struct VaultBridge(pub(crate) Arc<dyn CredentialStore>);

impl CredentialVault for VaultBridge {
    fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>> {
        Ok(self.0.load().map_err(store_error)?.map(Zeroizing::new))
    }

    fn credentials_changed(&self, revision: u64, payload: &[u8]) {
        self.0.credentials_changed(CredentialSnapshotRecord {
            revision,
            payload: payload.to_vec(),
        });
    }

    fn delete(&self) -> Result<()> {
        self.0.delete().map_err(store_error)
    }
}
