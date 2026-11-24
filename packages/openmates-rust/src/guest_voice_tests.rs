//! Shared guest call wire contracts and bounded spoken reply preparation.

use super::*;

fn plan(input: Value) -> Value {
    serde_json::from_str(&plan_json(&input.to_string()).expect("valid guest command"))
        .expect("serializable guest plan")
}

#[test]
fn opens_guest_socket_with_encoded_identity_and_privacy_ack() {
    let result = plan(json!({
        "operation":"connect","base":"https://api.example.org/","anonymous_id":"user+test"
    }));
    assert_eq!(
        result["url"],
        "wss://api.example.org/v1/voice-call/guest?anonymous_id=user%2Btest"
    );
    assert_eq!(
        serde_json::from_str::<Value>(result["start"].as_str().unwrap()).unwrap(),
        json!({"type":"start","privacy_ack_version":3})
    );
}

#[test]
fn maps_allowance_and_final_transcript_events() {
    let event = |frame: Value| plan(json!({"operation":"receive", "frame":frame.to_string()}));
    assert_eq!(
        event(json!({"type":"error","signup_required":true})),
        json!({"type":"limit"})
    );
    assert_eq!(
        event(json!({"type":"transcript","final":true,"turn_id":2,"text":" Hello "})),
        json!({"type":"transcript","submitted":true,"messageId":"2","text":"Hello"})
    );
}

#[test]
fn speech_contains_no_markdown_urls_or_oversized_request() {
    let result = plan(json!({
        "operation":"speech","base":"https://api.example.org","anonymous_id":"test",
        "language":"en","markdown":format!("**Hello** [link](https://example.com) {}", "a".repeat(4500)),
    }));
    assert_eq!(result["url"], "https://api.example.org/v1/anonymous/speech");
    let bodies = result["bodies"].as_array().expect("speech request bodies");
    assert!(bodies.len() > 1);
    for body in bodies {
        let request: Value = serde_json::from_str(body.as_str().unwrap()).unwrap();
        let text = request["text"].as_str().unwrap();
        assert!(text.chars().count() <= 4000);
        assert!(!text.contains("https://"));
        assert_eq!(request["anonymous_id"], "test");
    }
}
