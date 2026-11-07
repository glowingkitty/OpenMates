//! Web message-parsing block model (the shared Rust core Worker `parse` unit).
//!
//! The browser keeps the markdown/TipTap document compiler
//! (`compileAssistantDisplayMessage`, which calls `parse_message`) and the
//! ProseMirror diff; every decision about how an assistant message is split
//! into committed blocks and a mutable tail, which block ids and operations
//! follow from the previous plan, and the semantic summary of a compiled plan
//! is made here with exactly the semantics of `streamingMessageBlocks.ts`
//! (proven by `web_parse/blocks_ts_vectors.json`). Compiled documents are
//! opaque JSON for this module.
//!
//! Positions are byte offsets: every delimiter is ASCII, so slices cut at the
//! same characters as the UTF-16 offsets of the TypeScript original.

/// Pure block partitioning, id assignment, operations and normalization.
pub mod blocks;

/// Voice-delivery cue stripping of the assistant read projection.
pub mod voice_cues;

#[cfg(test)]
mod blocks_tests;
#[cfg(test)]
mod voice_cues_tests;
