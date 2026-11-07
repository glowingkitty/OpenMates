//! Replays `embed_read_ts_vectors.json`, generated from the TS sources
//! (frontend/packages/ui/scripts/generate-embed-read-vectors.mjs).
use super::admission::{is_embed_event_admitted, EmbedEventFacts};
use super::link::{generate_direct_embed_ref, parse_embed_link_target};
use super::patch::apply_version_patch;
use super::status::{is_terminal, normalize_status, validate_transition};
use serde_json::{json, Value};

const VECTORS: &str = include_str!("../embed_read_ts_vectors.json");

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or_else(|| panic!("vector field {k}"))
}

fn opt<'a>(v: &'a Value, k: &str) -> Option<&'a str> {
    v.get(k).and_then(Value::as_str)
}

#[test]
fn matches_every_ts_generated_vector() {
    let file: Value = serde_json::from_str(VECTORS).expect("valid vectors");
    let vectors = file["vectors"].as_array().expect("vectors");
    assert!(vectors.len() > 150, "vector file lost coverage");
    let mut failures = Vec::new();
    for v in vectors {
        let kind = s(v, "kind");
        let actual: Result<String, String> = match kind {
            "transition" => Ok(validate_transition(s(v, "current"), s(v, "target")).to_string()),
            "terminal" => Ok(is_terminal(s(v, "status")).to_string()),
            "normalize" => Ok(json!(normalize_status(opt(v, "status"))).to_string()),
            "link" => parse_embed_link_target(s(v, "input"))
                .map(|f| {
                    json!({
                        "cleanRef": f.clean_ref, "lineStart": f.line_start, "lineEnd": f.line_end,
                        "highlightQuoteText": f.highlight_quote_text, "sheetRange": f.sheet_range,
                    })
                    .to_string()
                })
                .map_err(|e| e.reason.to_string()),
            "ref" => Ok(json!(generate_direct_embed_ref(
                s(v, "embed_type"),
                s(v, "embed_id"),
                opt(v, "filename"),
                opt(v, "title"),
                opt(v, "subject")
            ))
            .to_string()),
            "admission" => Ok(is_embed_event_admitted(&EmbedEventFacts {
                current_status: s(v, "current"),
                incoming_status: opt(v, "status"),
                current_version: v["current_version"].as_f64(),
                incoming_version: v["incoming_version"].as_f64(),
                version_exempt: v["exempt"].as_bool().expect("exempt flag"),
            })
            .to_string()),
            "patch" => apply_version_patch(s(v, "content"), s(v, "patch"))
                .map(|t| json!(t).to_string())
                .map_err(|e| e.reason.to_string()),
            other => panic!("unknown vector kind {other}"),
        };
        let expected = match (opt(v, "json"), opt(v, "error")) {
            (Some(j), _) => Ok(j.to_string()),
            (None, Some(e)) => Err(e.to_string()),
            _ => panic!("vector without outcome"),
        };
        // Error vectors compare as refusals; reasons must match the TS message exactly.
        // Compare as JSON values: serde_json orders object keys, JS keeps insertion order.
        let parse = |r: &Result<String, String>| {
            r.as_ref()
                .map(|t| serde_json::from_str::<Value>(t).expect("json"))
                .map_err(Clone::clone)
        };
        if parse(&actual) != parse(&expected) {
            failures.push(format!("{kind} {v}: expected {expected:?}, got {actual:?}"));
        }
    }
    assert!(
        failures.is_empty(),
        "{} mismatches:\n{}",
        failures.len(),
        failures.join("\n")
    );
}
