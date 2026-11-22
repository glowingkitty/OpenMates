use super::*;
use crate::work::sandbox_key::{SandboxBinding, SandboxKeyPair};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use zeroize::Zeroizing;

const NOW: i64 = 1_000_000;
const RAW: [u8; 32] = [0xA7; 32];

fn request(pair: &SandboxKeyPair, expires_at: i64) -> SandboxKeyRequest {
    SandboxKeyRequest {
        request_id: "r1".into(),
        job_id: "j1".into(),
        sandbox_id: "s1".into(),
        project_id: "p1".into(),
        chat_id: "c1".into(),
        sandbox_public_key: pair.public_key_b64(),
        expires_at,
    }
}

#[test]
fn grant_opens_in_sandbox_and_never_carries_the_key() {
    let pair = SandboxKeyPair::generate();
    let req = request(&pair, NOW + 600);
    let frame = answer_frame(&req, NOW, KeyLookup::Key(Zeroizing::new(RAW))).unwrap();
    assert_eq!(frame["event"], "project_sandbox_key_grant");
    let text = frame.to_string();
    let hex: String = RAW.iter().map(|b| format!("{b:02x}")).collect();
    for needle in [STANDARD.encode(RAW), hex, "\u{a7}".repeat(8)] {
        assert!(!text.contains(&needle));
    }
    let binding = SandboxBinding {
        sandbox_id: "s1".into(),
        job_id: "j1".into(),
        project_id: "p1".into(),
    };
    let sealed = frame["payload"]["sealed_grant"].as_str().unwrap();
    assert_eq!(&pair.open_grant(sealed, &binding, NOW).unwrap()[..], &RAW[..]);
}

#[test]
fn declines_map_to_the_reason() {
    let pair = SandboxKeyPair::generate();
    let reason = |req: &SandboxKeyRequest, lookup| {
        answer_frame(req, NOW, lookup).unwrap()["payload"]["reason"].clone()
    };
    let ok = request(&pair, NOW + 600);
    assert_eq!(reason(&ok, KeyLookup::NoKey), "no_key");
    assert_eq!(reason(&ok, KeyLookup::Invalid), "invalid");
    let expired = request(&pair, NOW - 1);
    assert_eq!(reason(&expired, KeyLookup::Key(Zeroizing::new(RAW))), "expired");
    let far = request(&pair, NOW + 10 * 24 * 3600);
    assert_eq!(reason(&far, KeyLookup::Key(Zeroizing::new(RAW))), "invalid");
    let mut bad = request(&pair, NOW + 600);
    bad.sandbox_public_key = "AAAA".into();
    assert_eq!(reason(&bad, KeyLookup::Key(Zeroizing::new(RAW))), "invalid");
    let decline = answer_frame(&ok, NOW, KeyLookup::NoKey).unwrap();
    assert_eq!(decline["event"], "project_sandbox_key_decline");
    assert_eq!(decline["payload"]["request_id"], "r1");
    assert_eq!(decline["payload"]["job_id"], "j1");
}
