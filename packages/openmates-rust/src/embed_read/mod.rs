//! spec: sdk.client.thin-platform-boundary
//! Embed read-side logic shared by the browser Worker (`openmates-browser-bindings`
//! `browser_embed_read`): the embed status state machine, `embed:` link targets
//! and direct embed refs, and exact replay of legacy artifact version patches.
//! Ports `embedStateMachine.ts`, `embedFragmentUtils.ts`, `embedVersionReconstruction.ts`
//! and `projectFilePatch.ts`; byte parity is proven by `embed_read_ts_vectors.json`
//! (generated from those TS sources). Spec: specifications feature.chats.
pub mod link;
pub mod patch;
pub mod status;

#[cfg(test)]
mod embed_read_tests;

/// Why an embed read operation refused its input. `reason` is the fixed
/// diagnostic the TS implementation threw (never user content).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbedReadError {
    /// Fixed description of the refusal.
    pub reason: &'static str,
}

impl EmbedReadError {
    pub(crate) fn new(reason: &'static str) -> Self {
        Self { reason }
    }
}

impl std::fmt::Display for EmbedReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.reason)
    }
}

impl std::error::Error for EmbedReadError {}
