//! Behaviour of the E2B upload consent message policy, send policy and typed refusals.
// contract-test: supporting surface=sdks.rust assertions=code-run.e2b.upload-consent
use super::*;

#[test]
fn request_message_matches_the_wire_contract() {
    let out: Value = serde_json::from_str(
        &build_request_message_json("req-1", "chat-1", 1, 1_700_000_000).unwrap(),
    )
    .unwrap();
    assert_eq!(out["kind"], "ok");
    let message = &out["message"];
    assert_eq!(message["role"], "system");
    let content: Value = serde_json::from_str(message["content"].as_str().unwrap()).unwrap();
    assert_eq!(
        content,
        json!({
            "type": "e2b_upload_consent_request",
            "request_id": "req-1",
            "chat_id": "chat-1",
            "version": 1,
            "provider": "e2b",
            "privacy_policy_url": "https://openmates.org/privacy",
            "remote_access_command": "openmates remote-access",
            "choices": ["allow", "own_machine", "not_now"],
        })
    );
}

#[test]
fn request_without_identities_is_refused() {
    let out: Value =
        serde_json::from_str(&build_request_message_json("", "chat-1", 1, 1).unwrap()).unwrap();
    assert_eq!(out["kind"], "error");
}

#[test]
fn answered_detection_matches_only_the_same_request() {
    let answered = response_content("req-1", E2bConsentChoice::NotNow).to_string();
    let other = request_content("req-1", "chat-1", 1).unwrap().to_string();
    let list = serde_json::to_string(&vec![other, answered, String::new()]).unwrap();
    assert!(is_request_answered_json(&list, "req-1").unwrap());
    assert!(!is_request_answered_json(&list, "req-2").unwrap());
    assert!(is_request_answered_json("not json", "req-1").is_err());
}

#[test]
fn choices_use_the_contract_wire_strings_and_record_the_right_decision() {
    for (choice, wire, decision) in [
        (E2bConsentChoice::Allow, "allow", E2bDecision::Allowed),
        (
            E2bConsentChoice::OwnMachine,
            "own_machine",
            E2bDecision::Declined,
        ),
        (E2bConsentChoice::NotNow, "not_now", E2bDecision::Declined),
    ] {
        assert_eq!(choice.as_wire(), wire);
        assert_eq!(E2bConsentChoice::from_wire(wire), Some(choice));
        assert_eq!(choice.decision(), decision);
    }
    assert_eq!(E2bConsentChoice::from_wire("yes"), None);
}

#[test]
fn forbidden_detail_codes_map_to_stable_typed_errors() {
    for code in ["e2b_consent_required", "e2b_consent_declined"] {
        let object = json!({"detail": {"code": code}}).to_string();
        let plain = json!({"detail": code}).to_string();
        for body in [object, plain] {
            let error = refusal_from_body(body.as_bytes()).expect("typed error");
            assert!(matches!(error, Error::Unavailable { code: c, .. } if c == code));
            assert_eq!(error.sdk_code(), Some(code));
        }
    }
    assert!(refusal_from_body(br#"{"detail":{"code":"other"}}"#).is_none());
    assert!(refusal_from_body(b"nope").is_none());
}

#[test]
fn default_policy_never_approves_silently() {
    assert_eq!(E2bConsentPolicy::default(), E2bConsentPolicy::Caller);
    assert_eq!(E2bConsentPolicy::Caller.automatic_choice(), None);
    assert_eq!(
        E2bConsentPolicy::Reject.automatic_choice(),
        Some(E2bConsentChoice::NotNow)
    );
    assert_eq!(
        E2bConsentPolicy::Approve.automatic_choice(),
        Some(E2bConsentChoice::Allow)
    );
    assert_eq!(SendOptions::default().e2b_consent, E2bConsentPolicy::Caller);
}

#[test]
fn account_record_parses_none_allowed_and_declined() {
    let none = parse_record(&json!({"decision": null, "version": 1})).unwrap();
    assert_eq!(
        none,
        E2bConsentRecord {
            decision: None,
            decided_at: None,
            version: 1
        }
    );
    let allowed =
        parse_record(&json!({"decision": "allowed", "decided_at": 5, "version": 1})).unwrap();
    assert_eq!(allowed.decision, Some(E2bDecision::Allowed));
    assert_eq!(allowed.decided_at, Some(5));
    assert!(parse_record(&json!({"decision": "maybe", "version": 1})).is_err());
}

#[test]
fn answer_lookup_returns_the_chosen_wire_string() {
    let answered = response_content("req-1", E2bConsentChoice::OwnMachine).to_string();
    let list = serde_json::to_string(&vec![answered]).unwrap();
    assert_eq!(
        request_answer_json(&list, "req-1").unwrap(),
        Some("own_machine")
    );
    assert_eq!(request_answer_json(&list, "req-2").unwrap(), None);
}
