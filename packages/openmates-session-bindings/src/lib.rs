//! Direct SDK bindings over the shared Rust core: Node-API and PyO3 (native
//! session, API-key and stateless operations) plus a portable WebAssembly entry
//! for the npm SDK. Each binding uses the same JSON contracts and error envelope.
mod error;
pub use error::BindingError;
mod wipe;

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
#[cfg(feature = "python-bindings")]
mod python_future;
#[cfg(not(target_arch = "wasm32"))]
mod session;
mod task_order;
mod key_management;
/// Stateless key-management primitives (JSON envelope) shared by foreign SDK entries.
pub use key_management::key_management_json;
mod models;
/// Stateless decrypted presentation models (JSON envelope) shared by foreign SDK entries.
pub use models::models_json;
pub use privacy::privacy_json;
#[cfg(not(target_arch = "wasm32"))]
pub use session::{ApiKeyBridge, ApiKeyRequest, ApiKeyOutput, BindingOptions, SessionBridge, SessionDraftReadOptions};
pub use task_order::sort_tasks_json;

mod remote_crypto;
pub use remote_crypto::{RemoteHandshakeHandle,RemoteSessionHandle};
#[cfg(feature="napi-bindings")]
mod node_remote_crypto;
#[cfg(feature="python-bindings")]
mod python_remote_crypto;
#[cfg(not(target_arch = "wasm32"))]
pub use session::{PreparedInitialSyncOperation, InitialSyncOperationControl, InitialSyncMetadata};

#[cfg(not(target_arch = "wasm32"))]
pub mod metadata_ephemeral;
#[cfg(not(target_arch = "wasm32"))]
pub use metadata_ephemeral::{MetadataAuthenticationHandle,MetadataClientHandle,MetadataStartupHandle,MetadataSnapshotHandle};
#[cfg(feature="napi-bindings")]
mod node_metadata_ephemeral;
#[cfg(feature="python-bindings")]
mod python_metadata_ephemeral;

#[cfg(all(feature = "wasm-bindings", target_arch = "wasm32"))]
mod wasm;
