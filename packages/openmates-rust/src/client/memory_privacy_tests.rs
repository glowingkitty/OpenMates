//! Memory body anonymization: placeholders, reuse, PII settings and history restore.
use super::*;

const BODY: &str = "Reach me at jane.doe@example.org or +49 170 1234567.";

fn entry(body: &str) -> Value {
    json!({"app_id":"memory","item_key":"personal:cv","content":body})
}

fn disabled() -> Vec<Value> {
    vec![
        json!({"app_id":"privacy","item_type":"pii_detection_settings","data":{"masterEnabled":false}}),
    ]
}

#[test]
fn memory_body_contact_details_become_placeholders() {
    let mut entries = vec![entry(BODY)];
    let added = anonymize_entries(&mut entries, &[], &[]).unwrap();
    let sent = entries[0]["content"].as_str().unwrap();
    assert!(!sent.contains("jane.doe@example.org"), "{sent}");
    assert!(!sent.contains("1234567"), "{sent}");
    assert!(!added.is_empty());
    assert_eq!(entries[0]["item_key"], "personal:cv");
    // The answer echoing a placeholder restores live from the added mappings.
    let echoed = crate::privacy::restore(sent, &added).unwrap();
    assert_eq!(echoed, BODY);
}

#[test]
fn already_mapped_originals_reuse_their_placeholder() {
    let existing =
        vec![json!({"original":"jane.doe@example.org","placeholder":"[EMAIL_1]","type":"EMAIL"})];
    let mut entries = vec![entry(BODY)];
    let added = anonymize_entries(&mut entries, &[], &existing).unwrap();
    let sent = entries[0]["content"].as_str().unwrap();
    assert!(sent.contains("[EMAIL_1]"), "{sent}");
    assert!(
        added
            .iter()
            .all(|m| m["original"] != "jane.doe@example.org")
    );
}

#[test]
fn nested_string_values_are_anonymized() {
    let mut entries =
        vec![json!({"app_id":"a","item_key":"b","content":{"mail":"jane.doe@example.org","n":3}})];
    let added = anonymize_entries(&mut entries, &[], &[]).unwrap();
    assert!(!entries[0].to_string().contains("jane.doe@example.org"));
    assert_eq!(entries[0]["content"]["n"], 3);
    assert_eq!(added.len(), 1);
}

#[test]
fn disabled_pii_detection_leaves_the_body_unchanged() {
    let mut entries = vec![entry(BODY)];
    let added = anonymize_entries(&mut entries, &disabled(), &[]).unwrap();
    assert_eq!(entries[0]["content"], BODY);
    assert!(added.is_empty());
}

#[test]
fn history_restore_merges_mappings_of_the_memory_response_message() {
    let mut entries = vec![entry(BODY)];
    let added = anonymize_entries(&mut entries, &[], &[]).unwrap();
    let placeholder = added[0]["placeholder"].as_str().unwrap().to_owned();
    let response =
        json!({"type":"app_settings_memories_response","action":"included","pii_mappings":added});
    let mut chat = crate::model::Chat {
        id: "c".into(),
        title: String::new(),
        category: String::new(),
        messages: vec![
            crate::model::Message {
                id: "s".into(),
                role: "system".into(),
                content: response.to_string(),
                ..Default::default()
            },
            crate::model::Message {
                id: "a".into(),
                role: "assistant".into(),
                content: format!("Mail {placeholder}"),
                ..Default::default()
            },
        ],
    };
    crate::client::sync::restore_chat_tokens_from_rows(&mut chat, &[1; 32], &[]).unwrap();
    assert!(
        chat.messages[1].content.contains(added_original(&response)),
        "{}",
        chat.messages[1].content
    );
}

fn added_original(response: &Value) -> &str {
    response["pii_mappings"][0]["original"].as_str().unwrap()
}
