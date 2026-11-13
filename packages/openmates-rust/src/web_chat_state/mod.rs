//! Web chat-list state decisions (the shared Rust core Worker `chatState` unit).
//!
//! The browser keeps IndexedDB IO, stores, local-calendar date lookups and the
//! DOM; this module owns the pure ordering and grouping of the chat list with
//! exactly the semantics of the web TypeScript it replaces
//! (`components/chats/utils/chatSortUtils.ts`, `chatGroupUtils.ts` and
//! `utils/chatTimeGroups.ts`), proven by `ts_vectors.json`. Every entry point
//! takes and returns JSON text so the wasm boundary carries one string per call.
//! Spec: `feature.chats`, `surface.sdk` (sdk.client.thin-platform-boundary).
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use serde_json::Value;

pub mod activity;
mod args;
pub mod indicators;
pub mod list;
pub mod metadata;
pub mod placement;
pub mod selection;
pub mod unread;
pub mod timeline;
pub mod window;

/// Stable error code of every malformed-input refusal (the unit's only code).
pub const PROTOCOL: &str = "protocol";

/// Maps any parse or shape failure to the unit's single refusal code.
fn protocol<E>(_: E) -> String {
    PROTOCOL.to_string()
}

/// Parses one JSON argument of a wasm entry point.
fn parse(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(protocol)
}

#[cfg(test)]
mod tests;
#[cfg(test)]
mod view_tests;
#[cfg(test)]
mod transition_tests;
