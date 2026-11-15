//! Voice-call lifecycle: byte-for-byte content, ids and notice parsing against vectors generated from the real web TypeScript.
use super::*;
use serde_json::Value;

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/ts_voice_call_lifecycle.json"
    ))
    .unwrap()
}

fn action(s: &str) -> VoiceCallAction {
    if s == "started" {
        VoiceCallAction::Started
    } else {
        VoiceCallAction::Ended
    }
}

#[test]
fn voice_call_lifecycle_build_matches_web() {
    for b in fixture()["builds"].as_array().unwrap() {
        let e = VoiceCallLifecycleEvent::new(
            action(b["action"].as_str().unwrap()),
            b["call_id"].as_str().unwrap(),
            b["occurred_at"].as_i64().unwrap(),
            b["elapsed"].as_f64().unwrap(),
        )
        .unwrap();
        assert_eq!(e.to_content_json(), b["content"].as_str().unwrap());
        assert_eq!(e.message_id(), b["message_id"].as_str().unwrap());
    }
}

#[test]
fn voice_call_lifecycle_parse_matches_web() {
    for p in fixture()["parses"].as_array().unwrap() {
        let got = parse_notice("system", p["content"].as_str().unwrap());
        match p["notice"].as_object() {
            None => assert!(got.is_none(), "{}", p["content"]),
            Some(n) => {
                let e = got.unwrap_or_else(|| panic!("{}", p["content"]));
                assert_eq!(e.action, action(n["action"].as_str().unwrap()));
                assert_eq!(e.call_id, n["call_id"].as_str().unwrap());
                assert_eq!(e.created_at, n["created_at"].as_i64().unwrap());
                assert_eq!(
                    e.active_elapsed_seconds,
                    n["active_elapsed_seconds"].as_u64()
                );
            }
        }
    }
}

#[test]
fn voice_call_lifecycle_rejects_non_system_and_invalid_input() {
    let c = r#"{"schema_version":1,"type":"voice_call","action":"started","call_id":"call_abc12345","created_at":1,"active_elapsed_seconds":0}"#;
    assert!(parse_notice("system", c).is_some());
    assert!(parse_notice("user", c).is_none());
    assert_eq!(
        VoiceCallLifecycleEvent::new(VoiceCallAction::Ended, "short", 1, 0.0),
        Err(VoiceCallLifecycleError::InvalidCallId)
    );
    assert_eq!(
        VoiceCallLifecycleEvent::new(VoiceCallAction::Ended, "call_abc12345", 0, 0.0),
        Err(VoiceCallLifecycleError::InvalidCreatedAt)
    );
    assert_eq!(
        VoiceCallLifecycleEvent::new(VoiceCallAction::Ended, "call_abc12345", 1, -1.0),
        Err(VoiceCallLifecycleError::InvalidElapsed)
    );
}
