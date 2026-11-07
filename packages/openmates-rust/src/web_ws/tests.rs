//! Replays the TypeScript-verified vectors (`ts_vectors.json`, checked against the
//! real `websocketService.ts` by `wsPolicyVectors.test.ts`) against the web
//! WebSocket lifecycle policy, including malformed inputs that must be refused.
use serde_json::Value;

use super::{close, liveness, PROTOCOL};

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("committed vectors are valid JSON")
}

fn replay(v: &Value, section: &str, run: fn(&str) -> Result<String, String>) {
    for case in v[section].as_array().expect("vector section") {
        let out = run(&case["in"].to_string()).expect("vector input is accepted");
        let out: Value = serde_json::from_str(&out).expect("policy output is JSON");
        assert_eq!(out, case["out"], "{section}: {}", case["in"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn close_decisions_match_typescript() {
    replay(&vectors(), "close", close::close_plan_json);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn session_result_and_backoff_match_typescript() {
    let v = vectors();
    replay(&v, "session", close::session_result_json);
    replay(&v, "reconnect", close::reconnect_plan_json);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn liveness_decisions_match_typescript() {
    let v = vectors();
    replay(&v, "pong", liveness::pong_timeout_json);
    replay(&v, "lifecycle", liveness::lifecycle_json);
    replay(&v, "periodic", liveness::periodic_retry_json);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn malformed_inputs_are_refused_with_the_protocol_code() {
    let v = vectors();
    for input in v["malformedClose"].as_array().unwrap() {
        let input = input.as_str().unwrap();
        assert_eq!(
            close::close_plan_json(input),
            Err(PROTOCOL.to_string()),
            "{input}"
        );
    }
    for input in v["malformedLifecycle"].as_array().unwrap() {
        let input = input.as_str().unwrap();
        assert_eq!(
            liveness::lifecycle_json(input),
            Err(PROTOCOL.to_string()),
            "{input}"
        );
    }
}
