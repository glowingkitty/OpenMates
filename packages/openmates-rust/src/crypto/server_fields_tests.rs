//! Deterministic public field vectors, independent of randomized new writes.
// contract-test-file: tooling
use super::*;
use serde_json::Value;
fn vectors()->Value {serde_json::from_str(include_str!("../../tests/fixtures/server-field-codec.json")).unwrap()}
#[test]
fn legacy_and_old_native_field_vectors_authenticate_exact_plaintext_and_aad(){
    let data=vectors();for vector in data["vectors"].as_array().unwrap(){
        let key=decode_key(vector["key_b64"].as_str().unwrap()).unwrap();let expected=STANDARD.decode(vector["plaintext_b64"].as_str().unwrap()).unwrap();let aad=vector["aad"].as_str().unwrap().as_bytes();let cipher=vector["ciphertext_b64"].as_str().unwrap();
        assert_eq!(&*decrypt_bytes(cipher,&key,aad).unwrap(),&expected);
        assert!(decrypt_bytes(cipher,&[99;32],aad).is_err());
        let mut raw=STANDARD.decode(cipher).unwrap();*raw.last_mut().unwrap()^=1;assert!(decrypt_bytes(&STANDARD.encode(raw),&key,aad).is_err());
        if !aad.is_empty(){assert!(decrypt_bytes(cipher,&key,b"wrong scope").is_err());assert!(decrypt_bytes(cipher,&key,&[]).is_err());}
    }
}
#[test]
fn fresh_server_fields_write_legacy_and_do_not_change_generic_native_frames(){
    let key=[7u8;32];for plain in [vec![],b"Unicode \xe2\x9c\x93".to_vec(),(0..=255).collect::<Vec<u8>>()]{for aad in [&[][..],&b"task_activity_comment:task:entry:v1"[..]]{
        let wire=encrypt_bytes(&plain,&key,aad).unwrap();let bytes=STANDARD.decode(&wire).unwrap();assert_eq!(bytes.len(),plain.len()+28);assert_eq!(&*crypto_legacy_read(&bytes,&key,aad),&plain);assert_eq!(&*decrypt_bytes(&wire,&key,aad).unwrap(),&plain);
    }}
    let native=STANDARD.decode(super::super::encrypt_bytes(b"native vault",&key).unwrap()).unwrap();assert_eq!(&native[..2],b"OM");assert_eq!(&native[2..6],&key_fingerprint(&key));
}
fn crypto_legacy_read(wire:&[u8],key:&[u8;32],aad:&[u8])->Zeroizing<Vec<u8>>{super::super::decrypt_aead(&wire[12..],key,&wire[..12],aad).unwrap()}
#[test]
fn invalid_headers_short_tags_and_wrong_aad_never_become_plaintext(){
    let key=[7;32];for n in 0..28{assert!(decrypt_bytes(&STANDARD.encode(vec![0;n]),&key,b"context").is_err());}
    for text in ["", "not base64!", "===="]{assert!(decrypt_bytes(text,&key,b"context").is_err());}
    let cipher=encrypt_text("private synthetic",&key,b"ctx").unwrap();assert_eq!(decrypt_text(&cipher,&key,b"ctx").unwrap(),"private synthetic");assert!(decrypt_text(&cipher,&key,b"other").is_err());
}
