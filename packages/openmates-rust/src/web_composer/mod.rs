//! Web composer decisions on the shared Rust core Worker `composer` unit:
//! paste classification, PII detection/redaction/restoration, known-original
//! placeholder rewrite, local-model PII span windows/merge, and the suggestion
//! helpers (mention/saved-embed ranking, ghost-suggestion validation), and the
//! code-language and URL-kind helpers.
//! Pure ports of `frontend/packages/ui/src/components/enter_message/services/*`
//! with TypeScript-generated vectors (`ts_vectors.json`). All offsets are UTF-16
//! code units, exactly what Svelte/ProseMirror use; the JSON ops never return
//! matched text, the page slices it from its own string.
//! spec: specifications/features/pii-protection#pii.composer.detect-redact-exclude

pub mod code_language;
pub(crate) mod embed_refs;
pub mod mentions;
pub mod paste;
pub mod pii_detect;
pub(crate) mod pii_table;
pub mod pii_text;
pub mod rewrite;
pub mod suggestions;
pub mod url_kinds;
pub(crate) mod utf16;
pub mod web_pii;

#[cfg(test)]
mod embed_refs_tests;
#[cfg(test)]
mod language_url_tests;
#[cfg(test)]
mod suggestion_tests;
#[cfg(test)]
mod tests;

/// Stable error code for any malformed op payload.
pub(crate) fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}
