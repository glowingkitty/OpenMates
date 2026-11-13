//! Equivalence of the Rust composer ports with the TypeScript originals on
//! TS-generated vectors (`ts_vectors.json`), plus malformed-payload refusals.
use super::{paste, pii_detect, pii_text, rewrite, web_pii};
use serde_json::{Value, json};

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("vectors parse")
}

fn parse(text: &str) -> Value {
    serde_json::from_str(text).expect("op output is json")
}

fn run(group: &str, op: fn(&str) -> Result<String, String>) {
    for (n, case) in vectors()[group].as_array().expect("cases").iter().enumerate() {
        let got = op(&case["in"].to_string()).unwrap_or_else(|e| panic!("{group}[{n}] refused: {e}"));
        assert_eq!(parse(&got), case["out"], "{group}[{n}] input {}", case["in"]);
    }
}

#[test]
fn paste_classification_equals_typescript() {
    run("paste", paste::classify_pasted_content_json);
}

#[test]
fn plain_text_to_document_html_equals_typescript() {
    run("plain", paste::plain_text_to_document_html_json);
}

#[test]
fn pii_detection_equals_typescript() {
    run("detect", pii_detect::detect_json);
}

#[test]
fn pii_replace_equals_typescript() {
    run("replace", pii_text::replace_json);
}

#[test]
fn pii_restore_equals_typescript() {
    run("restore", pii_text::restore_json);
}

#[test]
fn pii_replace_originals_equals_typescript() {
    run("originals", pii_text::replace_originals_json);
}

#[test]
fn restored_positions_equal_typescript() {
    run("found", pii_text::find_restored_json);
}

#[test]
fn pii_summary_equals_typescript() {
    run("summary", pii_text::summary_json);
}

#[test]
fn known_original_rewrite_equals_typescript() {
    run("rewrite", rewrite::rewrite_json);
}

#[test]
fn model_windows_equal_typescript() {
    run("windows", web_pii::windows_json);
}

#[test]
fn window_entity_merge_equals_typescript() {
    run("mergeEntities", web_pii::merge_window_entities_json);
}

#[test]
fn model_match_merge_equals_typescript() {
    for (n, case) in vectors()["merge"].as_array().expect("cases").iter().enumerate() {
        let got = match web_pii::merge_matches_json(&case["in"].to_string()) {
            Ok(text) => parse(&text),
            Err(code) => {
                assert_eq!(code, "invalid_offsets", "merge[{n}]");
                json!({"error": "PII detector returned invalid character offsets"})
            }
        };
        assert_eq!(got, case["out"], "merge[{n}]");
    }
}

fn merged_texts(text: &str, entities: Value) -> Vec<String> {
    let got = web_pii::merge_matches_json(&json!({"text": text, "entities": entities, "nonce": "aaaaaaaabbbbcccc"}).to_string()).expect("merge");
    let units: Vec<u16> = text.encode_utf16().collect();
    parse(&got).as_array().expect("spans").iter().map(|m| {
        let (s, e) = (m["startIndex"].as_u64().expect("start") as usize, m["endIndex"].as_u64().expect("end") as usize);
        String::from_utf16_lossy(&units[s..e])
    }).collect()
}

fn name_entity(label: &str, original: &str, start: usize) -> Value {
    json!({"label": label, "original": original, "start": start, "end": start + original.len(), "confidence": 1})
}

#[test]
fn lone_common_word_given_name_is_dropped_but_full_names_stay() {
    let lone = merged_texts("Same question. Your take?", json!([name_entity("GIVEN_NAME", "Same", 0), name_entity("GIVEN_NAME", "Your", 15)]));
    assert!(lone.is_empty(), "{lone:?}");
    let full = merged_texts("Same Smith wrote to Anna.", json!([name_entity("GIVEN_NAME", "Same", 0), name_entity("SURNAME", "Smith", 5), name_entity("GIVEN_NAME", "Anna", 20)]));
    assert_eq!(full, ["Same", "Smith", "Anna"]);
}

#[test]
fn malformed_payloads_are_protocol_errors() {
    assert_eq!(paste::classify_pasted_content_json("{").unwrap_err(), "protocol");
    assert_eq!(paste::classify_pasted_content_json("{\"text\":1}").unwrap_err(), "protocol");
    assert_eq!(pii_detect::detect_json("{\"text\":\"abcdefg\",\"options\":{\"excludedIds\":[1]}}").unwrap_err(), "protocol");
    assert_eq!(pii_text::restore_json("{\"text\":\"a\",\"mappings\":[{\"placeholder\":\"[A]\"}]}").unwrap_err(), "protocol");
    assert_eq!(rewrite::rewrite_json("{\"markdown\":\"a\"}").unwrap_err(), "protocol");
    assert_eq!(web_pii::windows_json("[]").unwrap_err(), "protocol");
}

/// Provider-key formats are covered without committing key-shaped literals:
/// the committed vectors contain none, so these tests check that near-miss
/// shapes are not detected and that the pattern table keeps its structure.
#[test]
fn provider_key_near_misses_are_not_detected() {
    let key_kinds = [
        "AWS_ACCESS_KEY", "OPENAI_KEY", "ANTHROPIC_KEY", "GITHUB_PAT", "STRIPE_KEY",
        "GOOGLE_API_KEY", "SLACK_TOKEN", "SENDGRID_KEY", "HUGGINGFACE_KEY", "JWT",
    ];
    for text in [
        "prefix sk- alone", "sk-short", "AKIA short", "ghp_short", "xoxb-", "hf_short",
        "AIza short", "sk-ant-api03-short", "key_live_short", "eyJ.eyJ", "SG.short",
    ] {
        let got = parse(&pii_detect::detect_json(&json!({"text": text}).to_string()).expect("detect"));
        for span in got.as_array().expect("spans") {
            let kind = span["type"].as_str().unwrap_or_default();
            assert!(!key_kinds.contains(&kind), "{text:?} wrongly detected as {kind}");
        }
    }
}

#[test]
fn pattern_table_keeps_provider_key_kinds_in_priority_order() {
    let kinds: Vec<&str> = super::pii_table::patterns().iter().map(|p| p.kind).collect();
    assert_eq!(kinds.len(), 31);
    assert_eq!(&kinds[..7], ["AWS_ACCESS_KEY", "OPENAI_KEY", "ANTHROPIC_KEY", "GITHUB_PAT", "STRIPE_KEY", "GOOGLE_API_KEY", "SLACK_TOKEN"]);
    for p in super::pii_table::patterns() {
        assert!(!p.prefix.is_empty() && !p.label.is_empty(), "{}", p.kind);
    }
}
