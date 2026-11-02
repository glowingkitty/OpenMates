//! Foreign-language adapters call the headless Rust SDK directly. No CLI,
//! process invocation, credential discovery or independent protocol implementation.
#[cfg(feature = "napi-bindings")]
mod node;
#[cfg(feature = "napi-bindings")]
mod node_api_key;
mod privacy;
mod embed_version;
pub use embed_version::reconstruct_embed_version_json;
#[cfg(feature = "python-bindings")]
mod python;
#[cfg(feature = "python-bindings")]
mod python_api_key;
mod session;
mod task_order;
pub use privacy::privacy_json;
pub use session::{ApiKeyBridge, ApiKeyRequest, ApiKeyOutput, BindingError, BindingOptions, SessionBridge, SessionDraftReadOptions};
pub use task_order::sort_tasks_json;

mod remote_crypto;
pub use remote_crypto::{RemoteHandshakeHandle,RemoteSessionHandle};
#[cfg(feature="napi-bindings")]
mod node_remote_crypto;
#[cfg(feature="python-bindings")]
mod python_remote_crypto;
pub use session::{PreparedInitialSyncOperation, InitialSyncOperationControl, InitialSyncMetadata};

pub mod metadata_ephemeral;
pub use metadata_ephemeral::{MetadataAuthenticationHandle,MetadataClientHandle,MetadataStartupHandle,MetadataSnapshotHandle};
#[cfg(feature="napi-bindings")]
mod node_metadata_ephemeral;
#[cfg(feature="python-bindings")]
mod python_metadata_ephemeral;
