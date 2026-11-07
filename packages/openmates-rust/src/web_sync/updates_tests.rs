//! Replays the TypeScript-generated chat-update vectors (`updates_ts_vectors.json`,
//! produced from `chatSyncUpdatesLogic.ts`) against the Rust preview and
//! thinking-field policy, plus malformed-input refusals.
use serde_json::{Value, json};

use super as updates;

fn vectors() -> Value {
    serde_json::from_str(include_str!("updates_ts_vectors.json"))
        .expect("committed vectors are valid JSON")
}

fn parse(text: &str) -> Value {
    serde_json::from_str(text).expect("policy output is JSON")
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn message_preview_matches_typescript_for_every_vector() {
    let v = vectors();
    let cases = v["preview"].as_array().expect("preview cases");
    assert!(cases.len() >= 40);
    for case in cases {
        let got = parse(&updates::preview_json(&case["input"].to_string()).unwrap());
        assert_eq!(got["units"], case["units"], "{}", case["input"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn thinking_fields_match_typescript_for_every_vector() {
    let v = vectors();
    let cases = v["thinking"].as_array().expect("thinking cases");
    assert!(cases.len() >= 30);
    for case in cases {
        let got = parse(
            &updates::thinking_fields_json(&json!({"payload": case["request"]}).to_string())
                .unwrap(),
        );
        let want = &case["out"];
        assert_eq!(got["ok"], want["ok"], "{}", case["payload"]);
        if want["ok"] == json!(true) {
            assert_eq!(got["keys"], want["keys"], "{}", case["payload"]);
        } else {
            assert_eq!(got["code"], want["code"], "{}", case["payload"]);
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn preview_cuts_inside_a_surrogate_pair_like_substring() {
    let content = format!("a{}", "\u{1F600}".repeat(70));
    let got = parse(&updates::preview_json(&json!({"content": content}).to_string()).unwrap());
    let units = got["units"].as_array().unwrap();
    assert_eq!(units.len(), 123);
    assert_eq!(units[119], json!(0xD83D));
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn malformed_update_input_is_refused_with_protocol() {
    for input in ["", "[]", "1", r#"{"content":3}"#, r#"{"content":[]}"#] {
        assert_eq!(
            updates::preview_json(input),
            Err("protocol".to_string()),
            "{input}"
        );
    }
    for input in [
        "",
        "{}",
        r#"{"payload":3}"#,
        r#"{"payload":[]}"#,
        r#"{"payload":null}"#,
    ] {
        assert_eq!(
            updates::thinking_fields_json(input),
            Err("protocol".to_string()),
            "{input}"
        );
    }
}
