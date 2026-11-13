//! Shared TS-derived vectors for the signup/pair/recovery-print policy: every
//! expected value was produced from, and is re-checked against, the deployed
//! TypeScript in `webAuthFlow.test.ts`, plus every refusal branch.
use super::flow_call;
use crate::error::Error;
use serde_json::{Value, json};

const VECTORS: &str = include_str!("../../../frontend/packages/ui/src/services/rustCore/auth/__tests__/webAuthFlowVectors.json");

/// Integers and floats compare equal across JSON parse and `serde_json::to_value`.
fn normalize(value: Value) -> Value {
    match value {
        Value::Number(number) => json!(number.as_f64()),
        Value::Array(items) => Value::Array(items.into_iter().map(normalize).collect()),
        Value::Object(map) => Value::Object(map.into_iter().map(|(key, item)| (key, normalize(item))).collect()),
        other => other,
    }
}

#[test]
fn flow_calls_match_the_typescript_vectors() {
    let file: Value = serde_json::from_str(VECTORS).expect("vectors parse");
    for vector in file["vectors"].as_array().expect("vectors array") {
        let got = flow_call(vector["op"].as_str().expect("op"), &vector["args"]).unwrap_or_else(|_| panic!("refused: {vector}"));
        assert_eq!(normalize(got), normalize(vector["expect"].clone()), "{vector}");
    }
}

#[test]
fn flow_calls_refuse_bad_input_with_stable_codes() {
    let file: Value = serde_json::from_str(VECTORS).expect("vectors parse");
    for vector in file["refusals"].as_array().expect("refusals array") {
        let code = match flow_call(vector["op"].as_str().expect("op"), &vector["args"]) {
            Err(Error::Invalid(code)) => code,
            other => panic!("expected refusal for {vector}, got {other:?}"),
        };
        assert_eq!(code, vector["expect"].as_str().expect("code"), "{vector}");
    }
}
