//! Replays TypeScript-generated vectors against `strip_voice_cues`.
use super::voice_cues::strip_voice_cues;
use serde_json::Value;

#[test]
fn strip_voice_cues_equals_typescript() {
    let v: Value = serde_json::from_str(include_str!("voice_cues_ts_vectors.json")).unwrap();
    let cases = v["strip"].as_array().unwrap();
    assert!(cases.len() > 25);
    for case in cases {
        assert_eq!(strip_voice_cues(case["in"].as_str().unwrap()), case["out"].as_str().unwrap(), "{case}");
    }
}
