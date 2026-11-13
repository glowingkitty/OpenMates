//! Key-management JSON envelope: round trips, typed refusals and no secret echo.
use super::*;

fn call(input: Value) -> Result<Value, BindingError> {
    key_management_json(input.to_string()).map(|output| {
        serde_json::from_str(&output).unwrap_or_else(|_| panic!("binding output is JSON"))
    })
}

#[test]
fn encodes_decodes_and_round_trips_combined_ciphertext() {
    let raw: Vec<u8> = (0u8..32).collect();
    let encoded =
        call(json!({"operation":"encode_key","key":raw})).unwrap_or_else(|_| panic!("encode"));
    let decoded = call(json!({"operation":"decode_key","value":encoded["value"]}))
        .unwrap_or_else(|_| panic!("decode"));
    assert_eq!(decoded["key"], json!(raw));
    let sealed = call(json!({"operation":"encrypt_combined","text":"synthetic","key":raw}))
        .unwrap_or_else(|_| panic!("encrypt"));
    let opened =
        call(json!({"operation":"decrypt_combined","ciphertext":sealed["ciphertext"],"key":raw}))
            .unwrap_or_else(|_| panic!("decrypt"));
    assert_eq!(opened["text"], "synthetic");
    let fingerprint = call(json!({"operation":"key_fingerprint","key":raw}))
        .unwrap_or_else(|_| panic!("fingerprint"));
    assert_eq!(fingerprint["fingerprint"].as_array().map(Vec::len), Some(4));
    let random = call(json!({"operation":"random_key"})).unwrap_or_else(|_| panic!("random"));
    assert_eq!(random["key"].as_array().map(Vec::len), Some(32));
}

#[test]
fn refuses_short_keys_unknown_fields_and_wrong_keys_without_echo() {
    let short = call(json!({"operation":"encode_key","key":[1,2,3]}))
        .err()
        .map(|e| e.code);
    assert_eq!(short, Some("invalid_argument"));
    let unknown =
        call(json!({"operation":"hash_email","email":"synthetic-secret","extra":1})).err();
    assert!(
        unknown.as_ref().is_some_and(
            |e| e.code == "invalid_argument" && !e.message.contains("synthetic-secret")
        )
    );
    let raw: Vec<u8> = vec![7; 32];
    let sealed = call(json!({"operation":"encrypt_combined","text":"synthetic-secret","key":raw}))
        .unwrap_or_else(|_| panic!("encrypt"));
    let wrong = call(json!({"operation":"decrypt_combined","ciphertext":sealed["ciphertext"],"key":vec![8u8;32]})).err();
    assert!(wrong.is_some_and(|e| e.code == "crypto" && !e.message.contains("synthetic-secret")));
}
