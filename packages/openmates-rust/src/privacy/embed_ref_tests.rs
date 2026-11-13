//! The native message privacy boundary never alters embed references.
use super::prepare;
use serde_json::json;

/// CLI-style upload ref whose UUID digits look like a phone number.
const REF: &str = "x-81ede84d-0123-4567-91b3--2e1a33";
const PHONE: &str = "+49 2123 21234";

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn appended_reference_block_survives_while_phone_is_redacted() {
    let link = format!("[!](embed:{REF})");
    let prepared = prepare(&format!("call {PHONE}\n\n{link}"), &[], &[]).expect("prepare");
    assert!(prepared.text.ends_with(&link), "{}", prepared.text);
    assert!(!prepared.text.contains(PHONE));
}

// contract-test: supporting surface=sdks.rust assertions=pii.composer.embed-references-not-scanned
#[test]
fn json_reference_block_and_known_values_inside_it_are_untouched() {
    let block = format!(
        "```json\n{}\n```",
        json!({"type": "image", "embed_id": REF})
    );
    let existing = [json!({"placeholder": "[OM_PII_0123]", "original": "4567", "type": "OTHER"})];
    let prepared = prepare(&format!("{block}\nmy code 4567"), &[], &existing).expect("prepare");
    assert!(prepared.text.starts_with(&block), "{}", prepared.text);
    assert!(
        prepared.text.ends_with("my code [OM_PII_0123]"),
        "{}",
        prepared.text
    );
}
