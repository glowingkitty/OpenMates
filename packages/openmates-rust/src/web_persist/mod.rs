//! Web chat/message IndexedDB row policy (the shared Rust core Worker `persist`
//! unit).
//!
//! IndexedDB stays the store and the browser keeps the schema, transactions,
//! encryption and reads/writes; this module makes the row decisions with exactly
//! the semantics of the web TypeScript it replaces (`db/messageRowPolicy.ts`),
//! proven by `ts_vectors.json`. Every entry point takes and returns JSON text so
//! the wasm boundary carries one string per call.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
pub mod message_policy;

#[cfg(test)]
mod tests;
