//! Embed references are never matched by PII detection or the model-span merge.
use super::pii_detect;
use super::web_pii;
use serde_json::{Value, json};

/// CLI `createEmbedRef("<file>:<uuid>")` shape whose UUID digits look like a phone number.
const REF: &str = "x-81ede84d-0123-4567-91b3--2e1a33";
const PHONE: &str = "+49 2123 21234";

fn detect(text: &str, options: Value) -> Vec<Value> {
    let out = pii_detect::detect_json(&json!({"text": text, "options": options}).to_string())
        .expect("detect");
    serde_json::from_str::<Value>(&out)
        .expect("json")
        .as_array()
        .expect("spans")
        .clone()
}

fn spans(found: &[Value]) -> Vec<(u64, u64)> {
    found
        .iter()
        .map(|m| {
            (
                m["startIndex"].as_u64().expect("start"),
                m["endIndex"].as_u64().expect("end"),
            )
        })
        .collect()
}

fn phone_span(text: &str) -> (u64, u64) {
    let start = text.find(PHONE).expect("phone present") as u64;
    (start, start + PHONE.len() as u64)
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn bare_ref_is_phone_like_so_the_shield_is_load_bearing() {
    let found = detect(&format!("see {REF} here"), Value::Null);
    assert!(found.iter().any(|m| m["type"] == "PHONE"));
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn markdown_embed_link_is_never_matched_but_other_phone_is() {
    let text = format!("Look at this [!](embed:{REF})\ncall {PHONE} now");
    assert_eq!(spans(&detect(&text, Value::Null)), vec![phone_span(&text)]);
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn json_embed_reference_block_is_never_matched_but_other_phone_is() {
    let block = format!(
        "```json\n{}\n```",
        json!({"type": "image", "embed_id": REF})
    );
    let text = format!("{block}\ncall {PHONE} now");
    assert_eq!(spans(&detect(&text, Value::Null)), vec![phone_span(&text)]);
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn link_display_text_and_plain_json_blocks_are_still_scanned() {
    let display = format!("[call {PHONE}](embed:{REF})");
    assert_eq!(
        spans(&detect(&display, Value::Null)),
        vec![phone_span(&display)]
    );
    let code = format!("```json\n{}\n```", json!({"note": format!("call {PHONE}")}));
    assert_eq!(spans(&detect(&code, Value::Null)), vec![phone_span(&code)]);
    // A user note next to the ids of an embed reference block is human text.
    let noted = format!(
        "```json\n{}\n```",
        json!({"embed_id": REF, "embed_ids": [REF], "note": format!("call {PHONE}")})
    );
    assert_eq!(
        spans(&detect(&noted, Value::Null)),
        vec![phone_span(&noted)]
    );
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn personal_entries_never_cut_into_an_embed_ref() {
    let text = format!("[!](embed:{REF}) and 81ede84d");
    let options = json!({"personalDataEntries": [{"id": "p", "textToHide": "81ede84d", "replaceWith": "SECRET_CODE"}]});
    let start = text.rfind("81ede84d").expect("typed value") as u64;
    assert_eq!(spans(&detect(&text, options)), vec![(start, start + 8)]);
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn model_spans_inside_an_embed_ref_are_dropped() {
    let text = format!("[!](embed:{REF}) from Alice");
    let start = text.find("0123").expect("digits");
    let input = json!({
        "text": text, "nonce": "0123456789abcdef",
        "entities": [{"label": "PHONE", "original": &text[start..start + 12], "start": start, "end": start + 12, "confidence": 1}],
    });
    let out: Value =
        serde_json::from_str(&web_pii::merge_matches_json(&input.to_string()).expect("merge"))
            .expect("json");
    assert_eq!(out, json!([]));
}
