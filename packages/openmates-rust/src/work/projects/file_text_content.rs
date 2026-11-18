//! The text of a Project code file inside its stored embed content (shared
//! core, native and web Worker). A hosted file's head content is an object
//! (`type: "code"`, `code` or legacy `content`, `filename`, `language`,
//! `version_number`, `status`, `line_count`) stored as TOON or JSON, while the
//! hosted writer (`work::projects::hosted::job`) keeps only the text in the
//! version history. A web edit stores the whole object as its history
//! snapshot, so a replayed version can come in either form. Mirrors npm
//! `parseEmbedContentObject` / `textContent`.
//! spec: specifications/features/projects (projects.history.native-commits).

use crate::{Error, Result};
use serde_json::{Value, json};
use zeroize::Zeroizing;

#[cfg(not(target_arch = "wasm32"))]
use crate::client::upload::toon_encode;
// `upload` is native-only (file IO); the encoder itself is pure, so the web
// build compiles the same file here.
#[cfg(target_arch = "wasm32")]
#[allow(dead_code)] // Only `encode_fields` is used by this module; the rest serves `upload`.
#[path = "../../client/toon_encode.rs"]
mod toon_encode;

/// The top-level fields of stored embed content, in stored order: JSON text
/// first (npm `toonEncodeContent` falls back to JSON when TOON cannot encode a
/// value), else TOON. `None` when the content is not an object.
pub(crate) fn decode_content_fields(plain: &str) -> Option<Vec<(String, Value)>> {
    if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(plain) {
        return Some(map.into_iter().collect());
    }
    match crate::toon_decode::decode(plain).ok()? {
        crate::toon_decode::ToonValue::Object(object) => Some(
            object
                .entries()
                .iter()
                .map(|(key, value)| (key.clone(), value.to_json_value()))
                .collect(),
        ),
        _ => None,
    }
}

/// The name of the text field: `code`, or a legacy `content` string when the
/// object has no `code` (TS `code === undefined && typeof content === "string"`).
fn text_field(fields: &[(String, Value)]) -> &'static str {
    let has = |name: &str| fields.iter().any(|(key, _)| key == name);
    let content_is_text = fields
        .iter()
        .any(|(key, value)| key == "content" && value.is_string());
    if !has("code") && content_is_text {
        "content"
    } else {
        "code"
    }
}

/// JS `content.split("\n").length`.
pub(crate) fn line_count(content: &str) -> usize {
    content.matches('\n').count() + 1
}

/// The file text of one replayed version. A history row holds either the
/// text itself (hosted writer) or the whole code object (web edit); only an
/// object with `type: "code"` and a string text field counts as the latter,
/// so a JSON source file such as package.json stays text.
pub(crate) fn version_text(replayed: Zeroizing<String>) -> Zeroizing<String> {
    let Some(fields) = decode_content_fields(&replayed) else {
        return replayed;
    };
    let is_code = fields
        .iter()
        .any(|(key, value)| key == "type" && value.as_str() == Some("code"));
    let field = text_field(&fields);
    let text = fields
        .iter()
        .find(|(key, _)| key == field)
        .and_then(|(_, value)| value.as_str());
    match (is_code, text) {
        (true, Some(text)) => Zeroizing::new(text.to_owned()),
        _ => replayed,
    }
}

/// The head content of version `version` that holds `text`: the current head
/// object with its text field, `version_number`, `status` and `line_count`
/// replaced, in the field order the hosted writer keeps (`{...current, code}`).
///
/// # Errors
/// `Protocol` when the head content is not an object; the TOON encoder's
/// errors.
pub(crate) fn content_with_text(
    head_plain: &str,
    text: &str,
    version: u64,
) -> Result<Zeroizing<String>> {
    let mut fields = decode_content_fields(head_plain).ok_or(Error::Protocol)?;
    let field = text_field(&fields);
    for (key, value) in [
        (field, json!(text)),
        ("version_number", json!(version)),
        ("status", json!("finished")),
        ("line_count", json!(line_count(text))),
    ] {
        match fields.iter_mut().find(|(existing, _)| existing == key) {
            Some(entry) => entry.1 = value,
            None => fields.push((key.to_owned(), value)),
        }
    }
    let ordered: Vec<(&str, Value)> = fields
        .iter()
        .map(|(key, value)| (key.as_str(), value.clone()))
        .collect();
    toon_encode::encode_fields(&ordered).map(Zeroizing::new)
}

#[cfg(test)]
#[path = "file_text_content_tests.rs"]
mod file_text_content_tests;
