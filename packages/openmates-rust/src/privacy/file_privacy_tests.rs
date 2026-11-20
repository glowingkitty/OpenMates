//! Project-file privacy: one-pass restore, refusals, redact/restore round trip, persistence.
use super::file_privacy::{FilePrivacy, open_mappings, seal_mappings};
use serde_json::{Value, json};

fn code(error: crate::error::Error) -> &'static str {
    match error {
        crate::error::Error::Unavailable { code, .. } => code,
        _ => "other",
    }
}

fn entry() -> Value {
    json!({"app_id": "privacy", "item_type": "personal_data_entry",
        "data": {"enabled": true, "textToHide": "Ada Lovelace", "replaceWith": "NAME_1"}})
}

#[test]
fn restore_is_one_pass() {
    let p = FilePrivacy::new(
        true,
        vec![],
        &[
            json!({"placeholder": "[A]", "original": "[B]"}),
            json!({"placeholder": "[B]", "original": "x"}),
        ],
    )
    .unwrap();
    assert_eq!(p.restore_text("see [A] and [B]").unwrap(), "see [B] and x");
}

#[test]
fn ambiguous_placeholder_refuses() {
    let p = FilePrivacy::new(
        true,
        vec![],
        &[
            json!({"placeholder": "[A]", "original": "1"}),
            json!({"placeholder": "[A]", "original": "2"}),
        ],
    )
    .unwrap();
    assert_eq!(
        code(p.restore_text("[A]").unwrap_err()),
        "pii_mapping_ambiguous"
    );
    assert_eq!(p.saved_mappings().len(), 2);
}

#[test]
fn unknown_generated_or_custom_token_refuses() {
    let p = FilePrivacy::new(true, vec![entry()], &[]).unwrap();
    let generated = format!("[OM_PII_{}]", "A".repeat(32));
    assert_eq!(
        code(p.restore_text(&generated).unwrap_err()),
        "pii_mapping_unavailable"
    );
    assert_eq!(
        code(p.restore_text("[NAME_1]").unwrap_err()),
        "pii_mapping_unavailable"
    );
    assert_eq!(p.restore_text("[plain]").unwrap(), "[plain]");
}

#[test]
fn redact_then_restore_round_trips_email_and_personal_entry() {
    let mut p = FilePrivacy::new(true, vec![entry()], &[]).unwrap();
    let text = "author: Ada Lovelace <ada@example.org>\nnote\n";
    let redacted = p.redact_text(text).unwrap();
    assert!(
        !redacted.contains("ada@example.org") && !redacted.contains("Lovelace"),
        "{redacted}"
    );
    assert_eq!(p.restore_text(&redacted).unwrap(), text);
}

#[test]
fn multiline_values_keep_crlf_and_reuse_tokens() {
    let mut p = FilePrivacy::new(
        false,
        vec![],
        &[json!({"placeholder": "[OM_PII_0]", "original": "l1\r\nl2\nl3"})],
    )
    .unwrap();
    let text = "a l1\r\nl2\nl3 b l1\r\nl2\nl3";
    let redacted = p.redact_text(text).unwrap();
    assert_eq!(redacted.matches("\r\n").count(), 2, "{redacted:?}");
    assert_eq!(p.saved_mappings().len(), 4);
    assert_eq!(p.restore_text(&redacted).unwrap(), text);
}

#[test]
fn same_original_reuses_its_token() {
    let mut p = FilePrivacy::new(true, vec![], &[]).unwrap();
    let out = p
        .redact_text("ada@example.org and ada@example.org")
        .unwrap();
    let tokens: Vec<&str> = out.split(" and ").collect();
    assert_eq!(tokens[0], tokens[1]);
    assert!(tokens[0].starts_with("[OM_PII_") && tokens[0].len() == "[OM_PII_]".len() + 32);
    assert_eq!(p.saved_mappings().len(), 1);
}

#[test]
fn protocol_keys_are_untouched() {
    let mut p = FilePrivacy::new(true, vec![], &[]).unwrap();
    let mut value = json!({"expected_base": "ada@example.org", "content_hash": "ada@example.org",
        "proposal_commitment": "ada@example.org", "content": "ada@example.org"});
    p.redact_value(&mut value).unwrap();
    assert_eq!(value["expected_base"], "ada@example.org");
    assert_eq!(value["proposal_commitment"], "ada@example.org");
    assert_ne!(value["content"], "ada@example.org");
}

#[test]
fn mutation_and_arguments_are_restored() {
    let p = FilePrivacy::new(
        true,
        vec![],
        &[json!({"placeholder": "[X]", "original": "real"})],
    )
    .unwrap();
    let mut args = json!({"path": "[X].txt", "other": "[X]"});
    p.restore_arguments(&mut args).unwrap();
    assert_eq!(args, json!({"path": "real.txt", "other": "[X]"}));
    let mut m = json!({"path": "[X]", "patch": "a\n[X]", "expected_base": "[X]"});
    p.restore_mutation_fields(&mut m).unwrap();
    assert_eq!(
        m,
        json!({"path": "real", "patch": "a\nreal", "expected_base": "[X]"})
    );
    let multi = FilePrivacy::new(
        true,
        vec![],
        &[json!({"placeholder": "[X]", "original": "a\nb"})],
    )
    .unwrap();
    let mut bad = json!({"path": "p", "patch": "[X]"});
    assert_eq!(
        code(multi.restore_mutation_fields(&mut bad).unwrap_err()),
        "pii_multiline_patch_token"
    );
}

#[test]
fn persisted_blob_round_trips_and_refuses_wrong_chat() {
    let key = [7u8; 32];
    let maps = vec![json!({"placeholder": "[X]", "original": "real", "type": "EMAIL"})];
    let blob = seal_mappings("chat", "proj", &maps, &key).unwrap();
    assert_eq!(open_mappings("chat", "proj", &blob, &key).unwrap(), maps);
    assert_eq!(
        code(open_mappings("other", "proj", &blob, &key).unwrap_err()),
        "pii_mapping_unavailable"
    );
    assert_eq!(
        code(open_mappings("chat", "proj", &blob, &[8u8; 32]).unwrap_err()),
        "pii_mapping_unavailable"
    );
}
