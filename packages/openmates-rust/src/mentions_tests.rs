use super::*;
use serde_json::{Value, json};

/// Vectors produced by the TypeScript CLI's own `parseMentions`
/// (frontend/packages/openmates-cli/src/mentions.ts) with its CHAT_MODELS,
/// MATE_NAMES and the Apps/memory fixture stored beside the vectors. To
/// regenerate, run that module under Node with the same fixture and messages.
const TS_VECTORS: &str = include_str!("mentions_ts_vectors.json");

fn fixture_context(data: &Value) -> MentionContext {
    let mut context = MentionContext::with_apps(apps_from_json(&data["apps"]));
    context.memory_entries = data["memoryEntries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|e| MemoryEntryInfo {
            id: e["id"].as_str().unwrap().into(),
            app_id: e["app_id"].as_str().unwrap().into(),
            item_type: e["item_type"].as_str().unwrap().into(),
            title: e["title"].as_str().map(Into::into),
        })
        .collect();
    context
}

#[test]
fn parse_mentions_matches_typescript_cli_vectors() {
    let data: Value = serde_json::from_str(TS_VECTORS).unwrap();
    let today = data["today"].as_str().unwrap();
    let context = fixture_context(&data);
    let vectors = data["vectors"].as_array().unwrap();
    assert!(vectors.len() >= 30);
    for vector in vectors {
        let message = vector["message"].as_str().unwrap();
        let result = parse_mentions(message, &context, today);
        let actual = json!({
            "processedMessage": result.processed_message,
            "resolved": result.resolved.iter().map(|r| json!({
                "original": r.original,
                "type": serde_json::to_value(r.kind).unwrap(),
                "wireSyntax": r.wire_syntax,
                "displayName": r.display_name,
            })).collect::<Vec<_>>(),
            "filePaths": result.file_paths,
            "unresolved": result.unresolved.iter().map(|u| json!({
                "original": u.original,
                "suggestions": u.suggestions,
            })).collect::<Vec<_>>(),
        });
        let mut expected = vector.clone();
        expected.as_object_mut().unwrap().remove("message");
        assert_eq!(actual, expected, "message {message:?}");
    }
}

#[test]
fn display_model_mention_resolves_to_wire_syntax_with_static_catalog() {
    let context = MentionContext::with_apps(vec![]);
    let result = parse_mentions("@Gemini-3.8-Flash hi", &context, "2026-11-02");
    assert_eq!(result.processed_message, "@ai-model:gemini-3.8-flash hi");
    assert!(result.unresolved.is_empty());
    // Unknown mentions keep their text and are reported, never guessed.
    let unknown = parse_mentions("@Nonexistent-Model hi", &context, "2026-11-02");
    assert_eq!(unknown.processed_message, "@Nonexistent-Model hi");
    assert_eq!(unknown.unresolved.len(), 1);
}

#[test]
fn legacy_models_expire_one_year_after_release_and_at_api_retirement() {
    let legacy = ModelInfo {
        id: "old".into(),
        name: "Old".into(),
        legacy_model: true,
        release_date: Some("2025-11-02".into()),
        ..Default::default()
    };
    assert!(is_available_chat_model(&legacy, "2026-11-02"));
    assert!(!is_available_chat_model(&legacy, "2026-11-03"));
    assert!(!is_available_chat_model(&legacy, "2025-11-01"));
    let leap = ModelInfo { release_date: Some("2027-02-28".into()), ..legacy.clone() };
    assert!(is_available_chat_model(&leap, "2028-02-29"));
    let retiring = ModelInfo { api_retirement_date: Some("2027-04-01".into()), legacy_model: false, release_date: None, ..legacy };
    assert!(is_available_chat_model(&retiring, "2027-03-31"));
    assert!(!is_available_chat_model(&retiring, "2027-04-01"));
}

#[test]
fn today_utc_is_a_valid_calendar_date() {
    assert!(valid_date(&today_utc()).is_some());
}

#[test]
fn decrypted_memory_rows_resolve_memory_entry_mentions() {
    let data: Value = serde_json::from_str(TS_VECTORS).unwrap();
    let mut context = MentionContext::with_apps(apps_from_json(&data["apps"]));
    let rows = vec![
        json!({"id":"abc123","app_id":"code","item_type":"projects","data":{"title":"MyApp"}}),
        json!({"id":"","app_id":"code","item_type":"projects","data":{"title":"Ignored"}}),
    ];
    context.memory_entries = memory_entries_from_json(&rows);
    assert_eq!(context.memory_entries.len(), 1);
    let result = parse_mentions("@Code-Projects-MyApp status", &context, "2026-11-02");
    assert_eq!(result.processed_message, "@memory-entry:code:projects:abc123 status");
    assert!(result.unresolved.is_empty());
}
