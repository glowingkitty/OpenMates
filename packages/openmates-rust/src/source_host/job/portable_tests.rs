//! Portable request parsing, canonical byte-compat (node-generated vectors),
//! claim binding and digest verification.

use super::portable::*;
use super::wire::{Approval, ClaimedRequest, LeaseResponse};
use crate::crypto;
use crate::remote_command_review::request_digest;
use serde_json::Value;

fn fixture() -> (Vec<u8>, Vec<Value>) {
    let raw: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/remote_command_portable_vectors.json"
    ))
    .unwrap();
    let key = hex(raw["project_key_hex"].as_str().unwrap());
    (key, raw["vectors"].as_array().unwrap().clone())
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

fn claimed(request: &PortableRequest, key: &[u8; 32], canonical: &str) -> ClaimedRequest {
    ClaimedRequest {
        execution_id: request.execution_id.clone(),
        chat_id: request.chat_id.clone(),
        project_id: request.project_id.clone(),
        source_id: request.source_id.clone(),
        state: "LEASED".into(),
        encrypted_request: crypto::encrypt_combined(canonical, key).unwrap(),
        request_digest: request_digest(canonical, key).unwrap(),
        approval: request.approval.clone(),
        key_epoch: 1,
        lease: LeaseResponse {
            lease_token: "t".repeat(16),
            lease_generation: 1,
            lease_expires_at: 10,
            last_sequence: -1,
            launch_allowed: true,
            stop_requested: false,
        },
    }
}

#[test]
fn canonical_form_and_digest_match_node_vectors() {
    let (key, vectors) = fixture();
    for vector in vectors {
        let canonical = vector["canonical"].as_str().unwrap();
        let parsed = parse_portable_request(canonical).expect("vector parses");
        assert_eq!(canonical_request(&parsed), canonical);
        assert_eq!(
            request_digest(canonical, &key).unwrap(),
            vector["request_digest"].as_str().unwrap()
        );
    }
}

#[test]
fn non_ascii_vector_keeps_unicode_argv() {
    let (_, vectors) = fixture();
    let parsed = parse_portable_request(vectors[1]["canonical"].as_str().unwrap()).unwrap();
    assert!(parsed.policy.argv[1].contains('\u{2603}'));
    assert_eq!(parsed.policy.cwd, "caf\u{e9}/src");
}

#[test]
fn opens_claimed_request_and_rejects_tampering() {
    let (key, vectors) = fixture();
    let key: [u8; 32] = key.try_into().unwrap();
    let canonical = vectors[2]["canonical"].as_str().unwrap();
    let request = parse_portable_request(canonical).unwrap();
    let good = claimed(&request, &key, canonical);
    assert_eq!(open_claimed_request(&good, &key).unwrap(), request);

    let mut bad_digest = good.clone();
    bad_digest.request_digest = request_digest("{}", &key).unwrap();
    assert_eq!(
        open_claimed_request(&bad_digest, &key),
        Err(PortableError::DigestMismatch)
    );

    let mut other_exec = good.clone();
    other_exec.execution_id = "exec-2".into();
    assert_eq!(
        open_claimed_request(&other_exec, &key),
        Err(PortableError::ClaimMismatch)
    );

    let mut other_approval = good.clone();
    other_approval.approval = Approval::OneRun;
    assert_eq!(
        open_claimed_request(&other_approval, &key),
        Err(PortableError::ClaimMismatch)
    );

    assert_eq!(
        open_claimed_request(&good, &[7u8; 32]),
        Err(PortableError::Decrypt)
    );
}

#[test]
fn rejects_non_canonical_and_unknown_keys() {
    let (_, vectors) = fixture();
    let canonical = vectors[0]["canonical"].as_str().unwrap();
    let spaced = canonical.replacen(',', ", ", 1);
    assert_eq!(
        parse_portable_request(&spaced),
        Err(PortableError::NotCanonical)
    );
    let extra = canonical.replacen("\"policy\"", "\"extra\":1,\"policy\"", 1);
    assert!(matches!(
        parse_portable_request(&extra),
        Err(PortableError::Invalid(_))
    ));
}

#[test]
fn rejects_policy_limits() {
    let (_, vectors) = fixture();
    let policy = &vectors[0]["request"]["policy"];
    let with = |edit: &dyn Fn(&mut Value)| {
        let mut p = policy.clone();
        edit(&mut p);
        parse_policy(&p)
    };
    assert!(parse_policy(policy).is_ok());
    assert!(with(&|p| p["argv"] = serde_json::json!([])).is_err());
    assert!(with(&|p| p["argv"] = serde_json::json!([""])).is_err());
    assert!(with(&|p| p["argv"] = serde_json::json!(["x".repeat(16 * 1024 + 1)])).is_err());
    assert!(with(&|p| p["argv"] = Value::Array(vec!["a".into(); 129])).is_err());
    assert!(with(&|p| p["deadline_ms"] = 99.into()).is_err());
    assert!(with(&|p| p["deadline_ms"] = 86_400_001.into()).is_err());
    assert!(with(&|p| p["mode"] = "daemon".into()).is_err());
    assert!(with(&|p| p["network_profile"] = 5.into()).is_err());
    assert!(
        with(&|p| {
            p.as_object_mut().unwrap().remove("cwd");
        })
        .is_err()
    );
}
