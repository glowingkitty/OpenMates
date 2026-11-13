//! Shared TOON decoder for stored/streamed embed content (shared core, used by the
//! browser Worker through `openmates-browser-bindings` `toon_decode`).
//! Mirrors `@toon-format/toon` 4.4.0 `decode(text, { strict: false })`, the exact
//! call the web client makes (embedStore.ts `decodeToonContentLocal`,
//! chatSyncServiceHandlersAI.ts `decodeToonContentSafe`). Byte compatibility of
//! the JSON text is proven by `toon_decode_ts_vectors.json` (TS-generated).
//! Spec: specifications feature.chats (embed content stays client-decoded).
mod header;
mod parse;
mod scan;
mod value;

pub use value::{ToonObject, ToonValue};

/// Deepest container nesting the decoder accepts. The TS decoder recurses
/// without a limit; this guard keeps hostile input from exhausting the WASM
/// stack. Real embed content nests a handful of levels.
pub const MAX_NESTING: usize = 256;

/// Why TOON input was rejected. Every rejection has the single stable code
/// [`ToonDecodeError::CODE`]; `reason` is a fixed diagnostic (never input text)
/// and `line` the 1-based source line when known.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToonDecodeError {
    /// Fixed description of the rejected construct (no user content).
    pub reason: &'static str,
    /// 1-based line number of the offending line, when one applies.
    pub line: Option<usize>,
}

impl ToonDecodeError {
    /// Stable rejection code shared with the browser binding and web adapter.
    pub const CODE: &'static str = "toon_decode_failed";

    pub(crate) fn new(reason: &'static str) -> Self {
        Self { reason, line: None }
    }

    pub(crate) fn at(reason: &'static str, line: usize) -> Self {
        Self {
            reason,
            line: Some(line),
        }
    }

    /// The stable code ([`Self::CODE`]).
    pub fn code(&self) -> &'static str {
        Self::CODE
    }
}

impl std::fmt::Display for ToonDecodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.line {
            Some(line) => write!(f, "{}: line {line}: {}", Self::CODE, self.reason),
            None => write!(f, "{}: {}", Self::CODE, self.reason),
        }
    }
}

impl std::error::Error for ToonDecodeError {}

/// Decodes TOON text exactly like the TS non-strict decoder: lenient array
/// lengths, blank lines, tab/odd indentation and duplicate keys (last wins),
/// `#` comment lines skipped, and an empty document decodes to `{}`.
///
/// # Errors
/// [`ToonDecodeError`] wherever the TS decoder throws (unterminated quotes, bad
/// escapes, over-indented lines, malformed array headers, cell-count mismatch,
/// trailing content after a root array) plus nesting beyond [`MAX_NESTING`].
pub fn decode(input: &str) -> Result<ToonValue, ToonDecodeError> {
    parse::Decoder::new(scan::scan_lines(input)).decode_document()
}

/// [`decode`] rendered as the exact text `JSON.stringify` produces for the TS
/// result (JS key order and number formatting), for the web Worker boundary.
///
/// # Errors
/// As [`decode`].
pub fn decode_to_json_text(input: &str) -> Result<String, ToonDecodeError> {
    decode(input).map(|value| value.to_json_text())
}

#[cfg(test)]
mod toon_decode_tests;
