//! Replays TypeScript-generated vectors of generatedImageRecovery.ts against `image_recovery`.
use super::image_recovery::{lost_image_parents, recover_generated_images};
use serde_json::Value;

#[test]
fn image_recovery_equals_typescript() {
    let v: Value = serde_json::from_str(include_str!("image_recovery_ts_vectors.json")).unwrap();
    let cases = v["cases"].as_array().unwrap();
    assert!(cases.len() > 10);
    for case in cases {
        let source = &case["source"];
        let ids = lost_image_parents(source);
        assert_eq!(serde_json::to_value(&ids).unwrap(), case["parents"], "parents {case}");
        // Parents are aligned with the ids Rust asked for; unknown ids resolve to null.
        let resolved: Vec<Value> = ids.iter().map(|id| case["resolved"].get(id).cloned().unwrap_or(Value::Null)).collect();
        let recovered = recover_generated_images(source, &resolved).unwrap_or(Value::Null);
        assert_eq!(recovered, case["document"], "document {case}");
    }
}
