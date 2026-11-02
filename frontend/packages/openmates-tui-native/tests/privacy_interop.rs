use openmates_tui_native::privacy::{prepare, restore};
use serde_json::{Value, json};

#[test]
fn canonical_types_validators_and_shields_match_shared_source_vectors() {
    // contract-test: supporting surface=cli assertions=privacy.cli.default-local-anonymization
    let fixture: Value =
        serde_json::from_str(include_str!("privacy_fixtures/deterministic.json")).unwrap();
    for vector in fixture["vectors"].as_array().unwrap() {
        let input = vector["input"].as_str().unwrap();
        let result = prepare(input, &[], &[]).unwrap();
        let observed: Vec<Value> = result
            .mappings
            .iter()
            .map(|m| json!({"original":m["original"],"type":m["type"]}))
            .collect();
        assert_eq!(
            observed,
            vector["expected"].as_array().unwrap().to_vec(),
            "{}",
            vector["name"]
        );
        let mut restored = result.text.clone();
        for mapping in &result.mappings {
            let token = mapping["placeholder"].as_str().unwrap();
            assert!(token.starts_with("[OM_PII_") && token.len() == 41);
            assert!(!result.text.contains(mapping["original"].as_str().unwrap()));
            restored = restored.replace(token, mapping["original"].as_str().unwrap());
        }
        assert_eq!(restored, input, "{}", vector["name"]);
    }
}

#[test]
fn known_mappings_remain_stable_and_prevent_placeholder_collisions() {
    let known = json!({"original":"fictional@example.invalid","placeholder":"[EMAIL_1_com]","type":"EMAIL"});
    let result = prepare(
        "Contact fictional@example.invalid using [EMAIL_1_com].",
        &[],
        std::slice::from_ref(&known),
    )
    .unwrap();
    assert_eq!(result.text, "Contact [EMAIL_1_com] using [EMAIL_1_com].");
    assert_eq!(result.mappings, vec![known]);
    let unknown = "[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]";
    let result = prepare(unknown, &[], &[]).unwrap();
    assert_ne!(result.text, unknown);
    assert_eq!(result.mappings[0]["original"], unknown);
    assert!(
        prepare(
            "[EMAIL_1_com]",
            &[],
            &[
                json!({"original":"one","placeholder":"[EMAIL_1_com]"}),
                json!({"original":"two","placeholder":"[EMAIL_1_com]"}),
            ]
        )
        .is_err()
    );
}

#[test]
fn personal_data_memories_case_unicode_addresses_and_category_settings_are_applied() {
    let memories = [
        json!({"id":"synthetic","app_id":"privacy","item_type":"personal_data_entry","data":{
            "enabled":true,"textToHide":"Fictional Person","replaceWith":"PERSON","addressLines":{"street":"42 Synthetic Lane","city":"München"}
        }}),
    ];
    let result = prepare(
        "Meet FICTIONAL PERSON at 42 Synthetic Lane, München.",
        &memories,
        &[],
    )
    .unwrap();
    assert_eq!(result.mappings.len(), 3);
    for secret in ["FICTIONAL PERSON", "42 Synthetic Lane", "München"] {
        assert!(!result.text.contains(secret))
    }
    let disabled = [
        json!({"app_id":"privacy","item_type":"pii_detection_settings","data":{"masterEnabled":true,"categories":{"email_addresses":false}}}),
    ];
    assert_eq!(
        prepare("fictional@example.invalid", &disabled, &[])
            .unwrap()
            .text,
        "fictional@example.invalid"
    );
    let master_disabled = [
        json!({"app_id":"privacy","item_type":"pii_detection_settings","data":{"masterEnabled":false}}),
    ];
    let original = "fictional@example.invalid";
    assert_eq!(
        prepare(original, &master_disabled, &[]).unwrap().text,
        original
    );
    let known = [json!({"original":original,"placeholder":"[KNOWN_VALUE]","type":"EMAIL"})];
    assert_eq!(
        prepare(original, &master_disabled, &known).unwrap().text,
        "[KNOWN_VALUE]"
    );
}

#[test]
fn custom_personal_data_covers_suffix_left_after_a_known_value() {
    let memories = [
        json!({"app_id":"privacy","item_type":"personal_data_entry","data":{"enabled":true,"textToHide":"Fictional Person","replaceWith":"PERSON"}}),
    ];
    let existing = [json!({"original":"Fictional","placeholder":"[KNOWN_NAME]","type":"OTHER"})];
    let result = prepare("Fictional Person", &memories, &existing).unwrap();
    assert!(result.text.starts_with("[KNOWN_NAME]"));
    assert!(!result.text.contains("Person"));
    assert_eq!(result.mappings[1]["original"], " Person");
}

#[test]
fn restoration_is_one_pass_and_fails_closed_for_missing_or_ambiguous_tokens() {
    let mappings = [json!({"placeholder":"[KNOWN]","original":"literal [EMAIL_1_com]"})];
    assert_eq!(
        restore("[KNOWN]", &mappings).unwrap(),
        "literal [EMAIL_1_com]"
    );
    assert!(restore("[EMAIL_1_com]", &[]).is_err());
    assert!(
        restore(
            "[KNOWN]",
            &[
                json!({"placeholder":"[KNOWN]","original":"one"}),
                json!({"placeholder":"[KNOWN]","original":"two"})
            ]
        )
        .is_err()
    );
}
