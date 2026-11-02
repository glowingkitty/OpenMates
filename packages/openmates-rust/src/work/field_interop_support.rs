//! Synthetic test-only bridge into actual maintained web decoder functions.
//! No SDK operation uses Node; this exists only in native Rust unit tests.
use super::*;
use base64::{Engine, engine::general_purpose::STANDARD};
use std::{
    io::Write,
    process::{Command, Stdio},
};
pub(crate) fn case(
    label: &str,
    kind: &str,
    ciphertext: &str,
    key: &[u8; 32],
    expected: &[u8],
    aad: &str,
) -> Value {
    json!({"label":label,"kind":kind,"ciphertext":ciphertext,"key_b64":STANDARD.encode(key),"expected_b64":STANDARD.encode(expected),"aad":aad})
}
pub(crate) fn assert_web(cases: Vec<Value>) {
    let count = cases.len();
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/sdk-conformance/work-field-web-decoder.cjs");
    let mut child = Command::new("node")
        .arg(script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("actual web decoder test process required");
    child
        .stdin
        .take()
        .unwrap()
        .write_all(&serde_json::to_vec(&json!({"version":1,"cases":cases})).unwrap())
        .expect("synthetic decoder input");
    let output = child.wait_with_output().expect("web decoder terminal");
    assert!(
        output.status.success(),
        "actual web decoder rejected Work field output"
    );
    let receipt: Value = serde_json::from_slice(&output.stdout).expect("closed decoder receipt");
    assert_eq!(
        receipt,
        json!({"status":"passed","cases":count,"exportsAttempted":0})
    );
}
