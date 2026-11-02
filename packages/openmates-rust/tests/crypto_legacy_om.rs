//! Regression coverage for authenticated legacy IV/header ambiguity.
// contract-test-file: tooling
use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
use base64::{Engine, engine::general_purpose::STANDARD};
use openmates_sdk::crypto::{decrypt_bytes, encrypt_bytes, key_fingerprint};

#[test]
fn binary_legacy_om_ivs_authenticate_before_any_format_is_accepted() {
    let key = [7u8; 32];
    for marker in [
        [0xde, 0xad, 0xbe, 0xef],
        key_fingerprint(&key),
        [1, 0, 0, 0],
    ] {
        let mut iv = [0u8; 12];
        iv[..2].copy_from_slice(b"OM");
        iv[2..6].copy_from_slice(&marker);
        iv[6..].copy_from_slice(&[6, 7, 8, 9, 10, 11]);
        let cipher = Aes256Gcm::new_from_slice(&key).unwrap();
        for plain in [vec![], (0..=255).collect::<Vec<u8>>()] {
            let encrypted = cipher.encrypt(&Nonce::from(iv), plain.as_slice()).unwrap();
            let combined = [iv.as_slice(), encrypted.as_slice()].concat();
            assert_eq!(
                decrypt_bytes(&STANDARD.encode(&combined), &key)
                    .unwrap()
                    .as_slice(),
                plain
            );
            let framed = [
                b"OM".as_slice(),
                key_fingerprint(&key).as_slice(),
                combined.as_slice(),
            ]
            .concat();
            assert_eq!(
                decrypt_bytes(&STANDARD.encode(&framed), &key)
                    .unwrap()
                    .as_slice(),
                plain
            );
            assert!(decrypt_bytes(&STANDARD.encode(&combined), &[8; 32]).is_err());
            let mut tampered = combined;
            let last = tampered.len() - 1;
            tampered[last] ^= 1;
            assert!(decrypt_bytes(&STANDARD.encode(tampered), &key).is_err());
        }
    }
}
#[test]
fn forged_headers_and_truncated_tags_never_bypass_authentication_or_change_writes() {
    let key = [7u8; 32];
    for marker in [
        key_fingerprint(&key),
        [1, 0, 0, 0],
        [0xde, 0xad, 0xbe, 0xef],
    ] {
        let forged = [b"OM".as_slice(), marker.as_slice(), [0u8; 28].as_slice()].concat();
        assert!(decrypt_bytes(&STANDARD.encode(forged), &key).is_err());
    }
    for length in 0..28 {
        assert!(decrypt_bytes(&STANDARD.encode(vec![0u8; length]), &key).is_err());
    }
    let fresh = STANDARD.decode(encrypt_bytes(b"", &key).unwrap()).unwrap();
    assert_eq!(&fresh[..2], b"OM");
    assert_eq!(&fresh[2..6], key_fingerprint(&key));
}
