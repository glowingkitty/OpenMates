//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
//! Replays the TypeScript-generated vectors (`ts_vectors.json`, checked against
//! the web services by `streamRecoveryVectors.test.ts` and the stream cases of
//! `chatSyncServiceHandlersAI.test.ts`) against the web stream decisions.
use serde_json::{json, Value};

use super::assembler::StreamAssembler;
use super::recovery;

fn vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors.json")).expect("committed vectors are valid JSON")
}
fn stream_vectors() -> Value {
    serde_json::from_str(include_str!("ts_vectors_stream.json"))
        .expect("committed stream vectors are valid JSON")
}
/// Every key the TypeScript observation names must match; Rust may add context keys.
fn assert_has(actual: &Value, expected: &Value, context: &Value) {
    match expected {
        Value::Object(map) => map
            .iter()
            .for_each(|(k, e)| assert_has(&actual[k], e, context)),
        _ => assert_same(actual, expected, context),
    }
}
fn run(f: fn(&str) -> Result<String, String>, input: &Value) -> Value {
    serde_json::from_str(&f(&input.to_string()).expect("vector input is valid"))
        .expect("output is JSON")
}
fn cases<'a>(v: &'a Value, name: &str) -> &'a Vec<Value> {
    v[name]
        .as_array()
        .unwrap_or_else(|| panic!("vector set {name} is missing"))
}
/// JSON equality that compares numbers as `f64` (JS has one number type).
fn same(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => x.as_f64() == y.as_f64(),
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| same(p, q))
        }
        (Value::Object(x), Value::Object(y)) => {
            x.len() == y.len() && x.iter().all(|(k, p)| y.get(k).is_some_and(|q| same(p, q)))
        }
        _ => a == b,
    }
}
fn assert_same(actual: &Value, expected: &Value, context: &Value) {
    assert!(
        same(actual, expected),
        "{context}\n actual: {actual}\nexpected: {expected}"
    );
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn version_fence_matches_typescript() {
    let v = vectors();
    for case in cases(&v, "apply") {
        let input = json!({ "latest": case["latest"], "committedVersion": case["committedVersion"], "now": case["now"] });
        assert_same(&run(recovery::apply_json, &input), &case["out"], case);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn authoritative_version_responses_match_typescript() {
    let v = vectors();
    for case in cases(&v, "windowVersion") {
        assert_same(
            &run(recovery::window_version_json, case),
            &case["out"],
            case,
        );
    }
    for case in cases(&v, "assistantVersion") {
        assert_same(
            &run(recovery::assistant_version_json, case),
            &case["out"],
            case,
        );
    }
    for case in cases(&v, "initialDiff") {
        assert_same(&run(recovery::initial_diff_json, case), &case["out"], case);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn recovered_embed_identity_and_source_match_typescript() {
    let v = vectors();
    for case in cases(&v, "catalog") {
        let got = run(recovery::catalog_json, case);
        let mapped = match got["kind"].as_str().unwrap() {
            "none" => Value::Null,
            "invalid" => json!({ "error": "Recovered embed catalog identity was invalid." }),
            _ => json!({ "app_id": got["app_id"], "skill_id": got["skill_id"] }),
        };
        assert_same(&mapped, &case["out"], case);
    }
    for case in cases(&v, "historySource") {
        let got = run(recovery::history_source_json, case);
        let mapped = match got["kind"].as_str().unwrap() {
            "source" => got["source"].clone(),
            // The page prints the model itself; the field choice must name the same value.
            "json_model" => {
                let model = &case["decoded"][got["field"].as_str().unwrap()];
                let printed: Value =
                    serde_json::from_str(case["out"].as_str().expect("model source is text"))
                        .expect("model JSON");
                assert_same(model, &printed, case);
                case["out"].clone()
            }
            _ => json!({ "error": match got["code"].as_str().unwrap() {
                "mismatch" => "Sealed embed does not contain the expected historical source.",
                "mail_fields" => "Sealed mail source has invalid fields.",
                "document_body" => "Sealed document source has no supported historical body.",
                _ => "Historical recovery does not know this embed source format.",
            } }),
        };
        assert_same(&mapped, &case["out"], case);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn final_timestamps_expire_and_stay_bounded_like_typescript() {
    let v = vectors();
    let mut assembler = StreamAssembler::default();
    for step in cases(&v, "finalTimestamps") {
        if step["op"] == "record" {
            let out = assembler.dispatch(
                "finalTimestampRecord",
                &json!({ "event": step["event"], "now": step["now"] }).to_string(),
            );
            assert!(out.is_ok(), "{step}");
        } else {
            let input = json!({ "chat_id": step["chat_id"], "message_id": step["message_id"], "job_id": step["job_id"], "turn_id": step["turn_id"], "now": step["now"] });
            let got: Value = serde_json::from_str(
                &assembler
                    .dispatch("finalTimestampGet", &input.to_string())
                    .unwrap(),
            )
            .unwrap();
            assert_same(&got, &step["out"], step);
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn thinking_stream_and_final_plan_match_typescript() {
    let v = stream_vectors();
    for scenario in cases(&v, "thinking") {
        let mut assembler = StreamAssembler::default();
        for step in scenario["steps"].as_array().unwrap() {
            let got: Value = serde_json::from_str(
                &assembler
                    .dispatch(step["op"].as_str().unwrap(), &step["in"].to_string())
                    .unwrap(),
            )
            .unwrap();
            if let Some(expected) = step.get("out") {
                assert_has(&got, expected, step);
            }
        }
    }
    for case in cases(&v, "finalPlan") {
        let mut assembler = StreamAssembler::default();
        let got: Value = serde_json::from_str(
            &assembler
                .dispatch("finalChunkPlan", &case["in"].to_string())
                .unwrap(),
        )
        .unwrap();
        assert_has(&got, &case["out"], case);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn malformed_input_is_refused_with_the_protocol_code() {
    assert_eq!(recovery::apply_json("not json"), Err("protocol".into()));
    assert_eq!(recovery::apply_json("{}"), Err("protocol".into()));
    assert_eq!(
        StreamAssembler::default().dispatch("nope", "{}"),
        Err("protocol".into())
    );
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn retained_admission_frames_match_typescript() {
    let v: Value = serde_json::from_str(include_str!("context_frame_ts_vectors.json"))
        .expect("committed context-frame vectors are valid JSON");
    for case in cases(&v, "contextFrame") {
        assert_same(&run(recovery::context_frame_json, case), &case["out"], case);
    }
}
