//! Shared native/wasm wire-policy regression vectors, authored for Rust CI.
//! These public placeholders contain no account material and grant no authority.
//! Keep legacy version handling and strict base64 behavior identical on targets.
//! WebCrypto is a primitive implementation, never a second protocol parser.
//! Exact32-byte master output and AES-GCM tag/nonce validation are mandatory.
use super::*;
fn vectors() -> serde_json::Value { serde_json::from_str(include_str!("../../tests/crypto_fixtures/browser-legacy-password.json")).unwrap() }
#[test]
fn shared_legacy_static_vectors_match_unchanged_native_work_factor() {
    for v in vectors()["vectors"].as_array().unwrap() {
        for version in [0, 1] {
            let result = unwrap_password_master_key(v["password"].as_str().unwrap(), version,
                v["ciphertext"].as_str().unwrap(), v["salt"].as_str().unwrap(), v["iv"].as_str().unwrap()).unwrap();
            assert_eq!(encode_key(&result), v["master"]);
        }
    }
}
#[test]
fn shared_wire_parser_refuses_bad_iv_ciphertext_base64_and_non32_output() {
    let fixture = vectors(); let v = &fixture["vectors"][0]; let ct = v["ciphertext"].as_str().unwrap();
    for iv in [STANDARD.encode([0; 11]), STANDARD.encode([0; 13]), "not-base64".into()] {
        assert!(password_master_envelope(ct, &iv).is_err());
    }
    for ct in [STANDARD.encode([0; 15]), format!("{ct} "), "%%%".into()] {
        assert!(password_master_envelope(&ct, v["iv"].as_str().unwrap()).is_err());
    }
    for len in [0, 31, 33] { assert!(password_master_from_plaintext(&vec![7; len]).is_err()); }
    assert_eq!(password_master_from_plaintext(&[7; 32]).unwrap().as_ref(), &[7; 32]);
}
#[test]
fn legacy_wrong_password_tag_and_version_stay_failures() {
    let fixture = vectors(); let v = &fixture["vectors"][0]; let salt = v["salt"].as_str().unwrap(); let iv = v["iv"].as_str().unwrap(); let ct = v["ciphertext"].as_str().unwrap();
    assert!(unwrap_password_master_key("wrong password", 1, ct, salt, iv).is_err());
    assert!(unwrap_password_master_key("unused", 3, ct, salt, iv).is_err());
    let mut corrupted = STANDARD.decode(ct).unwrap(); *corrupted.last_mut().unwrap() ^= 1;
    assert!(unwrap_password_master_key(v["password"].as_str().unwrap(), 1, &STANDARD.encode(corrupted), salt, iv).is_err());
}
