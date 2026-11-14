//! spec: sdk.client.thin-platform-boundary
//! Embed read-side logic shared by the browser Worker (`openmates-browser-bindings`
//! `browser_embed_read`): the embed status state machine, `embed:` link targets
//! and direct embed refs, and exact replay of legacy artifact version patches.
//! Ports `embedStateMachine.ts`, `embedFragmentUtils.ts`, `embedVersionReconstruction.ts`
//! and `projectFilePatch.ts`, plus inbound event admission (`embedStateMachine.ts`) and the
//! canonical embed sender decisions (`embedSenderPolicy.ts`, `run_json`, `sender_ts_vectors.json`);
//! byte parity is proven by `embed_read_ts_vectors.json`
//! (generated from those TS sources). Spec: specifications feature.chats.
pub mod admission;
pub mod body_policy;
pub mod carousel_runs;
pub mod link;
pub mod patch;
pub mod progress;
mod sender;
pub mod status;

#[cfg(test)]
mod embed_read_tests;
#[cfg(test)]
mod sender_tests;

/// Runs one canonical embed sender decision (`op` is an `EmbedSenderOp` of the
/// web `embedSenderPolicy.ts`) on a JSON document and answers its JSON document.
/// Pure: the page keeps every IO, digest and key unwrap; no key bytes cross.
/// Parity: `sender_ts_vectors.json`.
///
/// # Errors
/// Returns `unknown_op:<name>` for an unregistered op and `missing_field:<name>`
/// or `bad_field:<name>` for a malformed document (never a silent default).
pub fn run_json(op: &str, input: &str) -> Result<String, String> {
    let input: serde_json::Value = serde_json::from_str(input).map_err(|e| format!("bad_json:{e}"))?;
    let output = sender::run(op, &input)?;
    serde_json::to_string(&output).map_err(|e| e.to_string())
}

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
