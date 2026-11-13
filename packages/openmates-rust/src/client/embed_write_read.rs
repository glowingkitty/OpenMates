//! Read side of stored embed rows: opens the `encrypted_content`,
//! `encrypted_type` and `encrypted_text_preview` fields of one `embeds` row
//! (the separate-fields data model) with its embed key, exactly like the web
//! `EmbedStore.getFromSeparateFields` + `decryptWithEmbedKey` composition:
//! - each present (non-empty) field is base64(12-byte IV || AES-256-GCM
//!   ciphertext || tag), decoded with forgiving browser base64, empty AAD;
//! - `encrypted_content` is trimmed first (ASCII whitespace only, never URL
//!   decoded); the other two fields are used as stored;
//! - plaintext follows `TextDecoder` (lossy UTF-8, a leading BOM is dropped);
//! - an empty plaintext counts as absent (the TS caller tests truthiness), and
//!   only a failed or empty content marks the row `content_failed`.
//!
//! The AES primitive runs behind [`AeadBatchKey`] so the web worker uses
//! WebCrypto (one batched call per row) and native tests use RustCrypto.
//! Content stays the decrypted TOON string: decoding for rendering is unchanged.
use crate::crypto::aead::{AeadBatchKey, AeadOp};
use crate::crypto::master::decode_browser_base64;
use crate::error::{Error, Result};
use serde::Serialize;
use serde_json::Value;

/// Decrypted, render-ready fields of one stored embed row.
#[derive(Debug, Default, PartialEq, Eq, Serialize)]
pub struct OpenedEmbedFields {
    /// Decrypted TOON content; `None` when absent or not decryptable.
    pub content: Option<String>,
    /// True when `encrypted_content` was present but did not open to text.
    pub content_failed: bool,
    #[serde(rename = "type")]
    pub embed_type: Option<String>,
    pub text_preview: Option<String>,
}

const FIELDS: [&str; 3] = ["encrypted_content", "encrypted_type", "encrypted_text_preview"];

/// `TextDecoder().decode`: replacement characters for invalid UTF-8 and the
/// leading byte-order mark removed (`ignoreBOM: false`).
fn text_decoder(bytes: &[u8]) -> String {
    let text = String::from_utf8_lossy(bytes);
    text.strip_prefix('\u{feff}').unwrap_or(&text).to_owned()
}

/// JS `String.prototype.trim` subset relevant to base64 ciphertext.
fn trim_js(value: &str) -> &str {
    value.trim_matches(|c: char| c.is_whitespace() || c == '\u{feff}')
}

/// Opens every present field of `row` with one batched AEAD call.
pub async fn open_row_fields(key: &dyn AeadBatchKey, row: &Value) -> Result<OpenedEmbedFields> {
    if !row.is_object() {
        return Err(Error::Invalid("An embed row must be an object."));
    }
    let field = |name: &str| row.get(name).and_then(Value::as_str);
    open_fields(key, [field(FIELDS[0]), field(FIELDS[1]), field(FIELDS[2])]).await
}

/// Opens `[encrypted_content, encrypted_type, encrypted_text_preview]`
/// (`None` or `""` = absent) with one batched AEAD call.
pub async fn open_fields(key: &dyn AeadBatchKey, fields: [Option<&str>; 3]) -> Result<OpenedEmbedFields> {
    // (field index, IV, sealed bytes); fields whose base64 or length is invalid
    // fail on their own without a primitive call, like WebCrypto would.
    let mut decoded: Vec<(usize, [u8; 12], Vec<u8>)> = Vec::new();
    let mut present = [false; 3];
    for (index, value) in fields.iter().enumerate() {
        let Some(raw) = value.filter(|value| !value.is_empty()) else { continue };
        present[index] = true;
        let raw = if index == 0 { trim_js(raw) } else { raw };
        let Ok(bytes) = decode_browser_base64(raw) else { continue };
        if bytes.len() < 12 + 16 {
            continue;
        }
        let mut iv = [0u8; 12];
        iv.copy_from_slice(&bytes[..12]);
        decoded.push((index, iv, bytes[12..].to_vec()));
    }
    let ops: Vec<AeadOp<'_>> = decoded.iter().map(|(_, iv, sealed)| AeadOp { iv, input: sealed }).collect();
    let results = if ops.is_empty() { Vec::new() } else { key.decrypt_many(&ops).await };
    if results.len() != ops.len() {
        return Err(Error::Unavailable { code: "aead_provider", reason: "AEAD_BATCH_LENGTH_MISMATCH" });
    }
    let mut opened: [Option<String>; 3] = [None, None, None];
    for ((index, _, _), result) in decoded.iter().zip(results) {
        match result {
            Ok(plain) => {
                let text = text_decoder(&plain);
                if !text.is_empty() {
                    opened[*index] = Some(text);
                }
            }
            Err(Error::Crypto) => {}
            Err(other) => return Err(other),
        }
    }
    let [content, embed_type, text_preview] = opened;
    Ok(OpenedEmbedFields { content_failed: present[0] && content.is_none(), content, embed_type, text_preview })
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_write_read_tests.rs"]
mod tests;
