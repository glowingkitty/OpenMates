//! wasm32 stand-in for the native-only `client::upload` module: the browser
//! build needs only the TOON content encoder (hosted Project file writes,
//! `work/projects/hosted/job.rs`), so it compiles that same source file and
//! nothing of the native upload pipeline.
//! Browser build of `client::upload`: there is no upload transport on wasm32,
//! only the TOON field encoder the hosted Project file executor shares.

#[path = "toon_encode.rs"]
pub(crate) mod toon_encode;
