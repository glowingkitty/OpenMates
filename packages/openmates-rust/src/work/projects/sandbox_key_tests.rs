use super::sandbox_key::*;
use crate::error::Error;
use base64::{Engine as _, engine::general_purpose::STANDARD};

const NOW: i64 = 1_000_000;
const KEY: [u8; 32] = [0xA7; 32];

fn request(pair: &SandboxKeyPair) -> SandboxKeyRequest {
    SandboxKeyRequest {
        request_id: "r1".into(),
        job_id: "j1".into(),
        sandbox_id: "s1".into(),
        project_id: "p1".into(),
        chat_id: "c1".into(),
        sandbox_public_key: pair.public_key_b64(),
        expires_at: NOW + 600,
    }
}
fn binding() -> SandboxBinding {
    SandboxBinding {
        sandbox_id: "s1".into(),
        job_id: "j1".into(),
        project_id: "p1".into(),
    }
}
fn code(e: Error) -> &'static str {
    match e {
        Error::Invalid(c) => c,
        _ => "other",
    }
}

#[test]
fn round_trip_and_wrong_pair() {
    let pair = SandboxKeyPair::generate();
    let sealed = seal_project_key_grant(&request(&pair), &KEY, NOW).unwrap();
    assert_eq!(
        pair.open_grant(&sealed, &binding(), NOW)
            .unwrap()
            .as_slice(),
        &KEY
    );
    let other = SandboxKeyPair::generate();
    let e = other.open_grant(&sealed, &binding(), NOW).unwrap_err();
    assert_eq!(code(e), CODE_OPEN_FAILED);
}

#[test]
fn binding_mismatch_each_field() {
    let pair = SandboxKeyPair::generate();
    let sealed = seal_project_key_grant(&request(&pair), &KEY, NOW).unwrap();
    for i in 0..3 {
        let mut b = binding();
        match i {
            0 => b.sandbox_id = "x".into(),
            1 => b.job_id = "x".into(),
            _ => b.project_id = "x".into(),
        }
        assert_eq!(
            code(pair.open_grant(&sealed, &b, NOW).unwrap_err()),
            CODE_BINDING_MISMATCH
        );
    }
}

#[test]
fn grant_for_other_public_key_field_mismatches() {
    // Sealed to our key but claiming another sandbox public key in the plaintext.
    let pair = SandboxKeyPair::generate();
    let other = SandboxKeyPair::generate();
    let mut req = request(&pair);
    req.sandbox_public_key = other.public_key_b64();
    // Sealed to `other`; `pair` cannot open it at all.
    let sealed = seal_project_key_grant(&req, &KEY, NOW).unwrap();
    assert_eq!(
        code(pair.open_grant(&sealed, &binding(), NOW).unwrap_err()),
        CODE_OPEN_FAILED
    );
}

#[test]
fn expiry_rules() {
    let pair = SandboxKeyPair::generate();
    let sealed = seal_project_key_grant(&request(&pair), &KEY, NOW).unwrap();
    assert_eq!(
        code(pair.open_grant(&sealed, &binding(), NOW + 600).unwrap_err()),
        CODE_EXPIRED
    );
    let mut req = request(&pair);
    req.expires_at = NOW;
    assert_eq!(
        code(seal_project_key_grant(&req, &KEY, NOW).unwrap_err()),
        CODE_EXPIRED
    );
    req.expires_at = NOW + 24 * 3600 + 301;
    assert_eq!(
        code(seal_project_key_grant(&req, &KEY, NOW).unwrap_err()),
        CODE_INVALID
    );
    req.expires_at = NOW + 24 * 3600 + 300;
    assert!(seal_project_key_grant(&req, &KEY, NOW).is_ok());
}

#[test]
fn tampered_and_garbage_fail() {
    let pair = SandboxKeyPair::generate();
    let sealed = seal_project_key_grant(&request(&pair), &KEY, NOW).unwrap();
    let mut raw = STANDARD.decode(&sealed).unwrap();
    let last = raw.len() - 1;
    raw[last] ^= 1;
    let bad = STANDARD.encode(raw);
    assert_eq!(
        code(pair.open_grant(&bad, &binding(), NOW).unwrap_err()),
        CODE_OPEN_FAILED
    );
    assert_eq!(
        code(pair.open_grant("not base64!", &binding(), NOW).unwrap_err()),
        CODE_OPEN_FAILED
    );
    assert_eq!(
        code(pair.open_grant("AAAA", &binding(), NOW).unwrap_err()),
        CODE_OPEN_FAILED
    );
}

#[test]
fn frames_never_contain_key_and_seals_differ() {
    let pair = SandboxKeyPair::generate();
    let req = request(&pair);
    let frame = project_sandbox_key_grant_frame(&req, &KEY, NOW).unwrap();
    assert_eq!(frame["event"], "project_sandbox_key_grant");
    assert_eq!(frame["payload"]["request_id"], "r1");
    let text = serde_json::to_string(&frame).unwrap();
    let hex: String = KEY.iter().map(|b| format!("{b:02x}")).collect();
    assert!(!text.contains(&STANDARD.encode(KEY)));
    assert!(!text.contains(&hex));
    let raw = STANDARD
        .decode(frame["payload"]["sealed_grant"].as_str().unwrap())
        .unwrap();
    assert!(!raw.windows(32).any(|w| w == KEY));
    let a = seal_project_key_grant(&req, &KEY, NOW).unwrap();
    let b = seal_project_key_grant(&req, &KEY, NOW).unwrap();
    assert_ne!(a, b);
    let decline = project_sandbox_key_decline_frame(&req, "no_key").unwrap();
    assert_eq!(decline["event"], "project_sandbox_key_decline");
    assert!(project_sandbox_key_decline_frame(&req, "bogus").is_err());
}

#[test]
fn bad_inputs_refused() {
    let pair = SandboxKeyPair::generate();
    for len in [0usize, 31, 33] {
        let mut req = request(&pair);
        req.sandbox_public_key = STANDARD.encode(vec![1u8; len]);
        assert_eq!(
            code(seal_project_key_grant(&req, &KEY, NOW).unwrap_err()),
            CODE_INVALID
        );
    }
    assert!(seal_project_key_grant(&request(&pair), &[1u8; 31], NOW).is_err());
    let mut req = request(&pair);
    req.job_id.clear();
    assert!(seal_project_key_grant(&req, &KEY, NOW).is_err());
}
