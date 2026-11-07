//! Equivalence of the Rust suggestion helpers with the TypeScript originals on
//! TS-generated vectors (`suggestion_ts_vectors.json`), plus malformed payloads.
use super::{mentions, suggestions};
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("suggestion_ts_vectors.json")).expect("vectors parse")
}

fn run(group: &str, op: fn(&str) -> Result<String, String>) {
    for (n, case) in vectors()[group].as_array().expect("cases").iter().enumerate() {
        let got = op(&case["in"].to_string()).unwrap_or_else(|e| panic!("{group}[{n}] refused: {e}"));
        let got: Value = serde_json::from_str(&got).expect("op output is json");
        assert_eq!(got, case["out"], "{group}[{n}] input {}", case["in"]);
    }
}

#[test]
fn mention_ranking_equals_typescript() {
    run("mentions", mentions::rank_mentions_json);
}

#[test]
fn saved_embed_ranking_equals_typescript() {
    run("saved", mentions::rank_saved_embeds_json);
}

#[test]
fn ghost_suggestion_validation_equals_typescript() {
    run("ghosts", suggestions::ghost_validate_json);
}

#[test]
fn vectors_carry_no_provider_key_shapes() {
    let text = include_str!("suggestion_ts_vectors.json");
    for needle in ["sk-", "AKIA", "ghp_", "xox", "AIza", "eyJ", "SG.", "hf_", "BEGIN"] {
        assert!(!text.contains(needle), "vectors contain {needle}");
    }
}

#[test]
fn malformed_payloads_are_protocol_errors() {
    assert_eq!(mentions::rank_mentions_json("{").unwrap_err(), "protocol");
    assert_eq!(mentions::rank_mentions_json("{\"query\":\"a\",\"limit\":1,\"candidates\":[{\"searchTerms\":[1]}]}").unwrap_err(), "protocol");
    assert_eq!(mentions::rank_mentions_json("{\"query\":\"a\",\"candidates\":[]}").unwrap_err(), "protocol");
    assert_eq!(mentions::rank_saved_embeds_json("{\"query\":\"a\",\"limit\":1,\"entries\":[{\"title\":\"t\"}]}").unwrap_err(), "protocol");
    assert_eq!(suggestions::ghost_validate_json("{\"value\":1}").unwrap_err(), "protocol");
    assert_eq!(suggestions::ghost_validate_json("[]").unwrap_err(), "protocol");
}
