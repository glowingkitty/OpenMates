//! Conversion between a live item's text form (document HTML, markdown table, slides markup,
//! file text) and the embed's stored plaintext (the TOON string `encrypted_content` opens to).
//!
//! The stored form is a TOON object whose kind-specific field holds the text form and whose
//! other fields (title, language, version_number, ...) are kept as they are. The field names
//! are the ones the editors' save paths write: `html` (document), `table` (sheet, mirrored in
//! `code` when the stored content already has one), `slides_markup` (deck), `code` (code file).

use super::{LiveError, LiveItemKind};
use serde_json::Value;

#[path = "../toon_encode.rs"]
mod toon_encode;

/// The stored-content field that holds the text form of `kind`.
pub fn content_field(kind: LiveItemKind) -> &'static str {
    match kind {
        LiveItemKind::Doc => "html",
        LiveItemKind::Sheet => "table",
        LiveItemKind::Deck => "slides_markup",
        LiveItemKind::Code => "code",
    }
}

/// The live kind of an embed `type` string, `None` for embeds that are not live-editable.
/// Accepts the stored (backend) names `document`, `sheet`, `deck`, `code` and the frontend
/// names `docs-doc`, `sheets-sheet`, `slides-deck`, `code-code` (`-` or `_`); exact matches
/// only, so other types that merely contain such a word are refused.
pub fn kind_of_embed_type(embed_type: &str) -> Option<LiveItemKind> {
    match embed_type.to_ascii_lowercase().replace('_', "-").as_str() {
        "document" | "docs-doc" => Some(LiveItemKind::Doc),
        "sheet" | "sheets-sheet" => Some(LiveItemKind::Sheet),
        "deck" | "slides-deck" => Some(LiveItemKind::Deck),
        "code" | "code-code" => Some(LiveItemKind::Code),
        _ => None,
    }
}

/// Text form held in decoded stored `content`.
///
/// # Errors
/// [`LiveError::Empty`] when the kind's field is missing or not a string.
pub fn text_from_content(kind: LiveItemKind, content: &Value) -> Result<String, LiveError> {
    content
        .get(content_field(kind))
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or(LiveError::Empty)
}

/// The stored plaintext (TOON) of the next version: `base` with the kind's field set to
/// `text` and `version_number` set to `version`.
///
/// # Errors
/// [`LiveError::Io`] `live_content_unencodable` when `base` holds a value the TOON encoder
/// cannot lay out (the write then fails rather than guessing a layout).
pub fn stored_with_text(
    kind: LiveItemKind,
    base: &Value,
    text: &str,
    version: i64,
) -> Result<String, LiveError> {
    let mut map = base.as_object().cloned().unwrap_or_default();
    let field = content_field(kind);
    map.insert(field.to_owned(), Value::String(text.to_owned()));
    if kind == LiveItemKind::Sheet && map.get("code").is_some_and(Value::is_string) {
        map.insert("code".to_owned(), Value::String(text.to_owned()));
    }
    if kind == LiveItemKind::Code {
        let without_final_newline = text.strip_suffix('\n').unwrap_or(text);
        let line_count = if without_final_newline.is_empty() {
            0
        } else {
            without_final_newline.split('\n').count()
        };
        map.insert("line_count".to_owned(), Value::from(line_count));
    }
    map.insert("version_number".to_owned(), Value::from(version));
    let fields: Vec<(&str, Value)> = map.iter().map(|(k, v)| (k.as_str(), v.clone())).collect();
    toon_encode::encode_fields(&fields).map_err(|_| LiveError::Io("live_content_unencodable"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn round_trip(kind: LiveItemKind, base: Value, text: &str) {
        let stored = stored_with_text(kind, &base, text, 7).expect("encode");
        let decoded = crate::client::toon::decode(&stored).expect("decode");
        assert_eq!(text_from_content(kind, &decoded).as_deref(), Ok(text));
        assert_eq!(decoded["version_number"], json!(7));
        assert_eq!(decoded["title"], base["title"]);
    }

    #[test]
    fn doc_html_round_trips() {
        let html = "<h1>Plan</h1><p>Line \"one\"</p>\n<ul><li>a, b</li></ul>";
        round_trip(
            LiveItemKind::Doc,
            json!({"title": "Notes", "html": "<p>old</p>"}),
            html,
        );
    }

    #[test]
    fn sheet_table_round_trips_and_mirrors_code() {
        let table = "| a | b |\n| --- | --- |\n| 1 | x: y |";
        let base = json!({"title": "Budget", "table": "old", "code": "old"});
        let stored = stored_with_text(LiveItemKind::Sheet, &base, table, 2).unwrap();
        let decoded = crate::client::toon::decode(&stored).unwrap();
        assert_eq!(decoded["code"], json!(table));
        round_trip(LiveItemKind::Sheet, base, table);
    }

    #[test]
    fn deck_markup_round_trips() {
        round_trip(
            LiveItemKind::Deck,
            json!({"title": "Pitch", "slides_markup": ""}),
            "# One\n\n---\n\n# Two\n- point",
        );
    }

    #[test]
    fn code_text_round_trips() {
        round_trip(
            LiveItemKind::Code,
            json!({"title": "main.py", "language": "python", "code": ""}),
            "def f():\n    return \"a\\nb\"\n",
        );
    }

    #[test]
    fn embed_types_map_to_kinds() {
        assert_eq!(
            kind_of_embed_type("sheets-sheet"),
            Some(LiveItemKind::Sheet)
        );
        assert_eq!(kind_of_embed_type("docs_doc"), Some(LiveItemKind::Doc));
        assert_eq!(kind_of_embed_type("slides-deck"), Some(LiveItemKind::Deck));
        assert_eq!(kind_of_embed_type("code-code"), Some(LiveItemKind::Code));
        assert_eq!(kind_of_embed_type("image"), None);
        for (name, kind) in [
            ("document", LiveItemKind::Doc),
            ("sheet", LiveItemKind::Sheet),
            ("deck", LiveItemKind::Deck),
            ("code", LiveItemKind::Code),
        ] {
            assert_eq!(kind_of_embed_type(name), Some(kind));
        }
        assert_eq!(kind_of_embed_type("docker"), None);
        assert_eq!(kind_of_embed_type("app_skill_use"), None);
    }

    #[test]
    fn missing_field_is_empty() {
        assert_eq!(
            text_from_content(LiveItemKind::Doc, &json!({"title": "x"})),
            Err(LiveError::Empty)
        );
    }
}
