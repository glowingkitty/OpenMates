//! Replays TypeScript-generated vectors (web_search_ts_vectors.json) against the
//! Rust ports through the same JSON boundary the browser worker uses.
use crate::web_search_json::*;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_search_ts_vectors.json")).unwrap()
}

#[test]
fn match_ranges_equal_typescript() {
    for case in vectors()["matchRanges"].as_array().unwrap() {
        let got: Value = serde_json::from_str(&find_match_ranges_json(case["text"].as_str().unwrap(), case["query"].as_str().unwrap()).unwrap()).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
    assert_eq!(find_match_ranges_json("abc", "").unwrap(), "[]");
}

#[test]
fn snippets_equal_typescript() {
    for case in vectors()["snippets"].as_array().unwrap() {
        let got: Value = serde_json::from_str(&build_snippet_json(
            case["content"].as_str().unwrap(),
            case["start"].as_u64().unwrap() as usize,
            case["length"].as_u64().unwrap() as usize,
        ))
        .unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn snippet_cut_inside_surrogate_pair_keeps_lone_surrogate_escape() {
    let text = format!("{}\u{1F600}{}", "a ".repeat(30), " b".repeat(30));
    let json = build_snippet_json(&text, 55, 1);
    assert!(json.contains("\\ud83d") || json.contains("\\ude00") || !json.contains("\u{FFFD}"));
}

#[test]
fn saved_embed_memories_equal_typescript() {
    for case in vectors()["savedEmbeds"].as_array().unwrap() {
        let got = search_saved_embed_memories_json(
            &case["entries"].to_string(),
            case["query"].as_str().unwrap(),
            case["limit"].as_i64().unwrap(),
        )
        .unwrap();
        let got: Value = serde_json::from_str(&got).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn pii_aliases_equal_typescript() {
    for case in vectors()["piiAliases"].as_array().unwrap() {
        let got = create_pii_display_aliases_json(
            &case["source"].to_string(),
            &case["mappings"].to_string(),
            &case["configured"].to_string(),
        )
        .unwrap();
        let got: Value = serde_json::from_str(&got).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn malformed_json_is_a_protocol_error() {
    assert_eq!(search_saved_embed_memories_json("{", "q", 6), Err("protocol".to_string()));
    assert_eq!(create_pii_display_aliases_json("null", "x", "[]"), Err("protocol".to_string()));
}
