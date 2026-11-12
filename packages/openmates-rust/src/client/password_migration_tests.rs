//! Password migration primitives: the v2 wrapper round-trips to the master key under the synthetic account vector, key equality is exact, and a signed-out client refuses to migrate.
use super::*;

fn vector() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/account.json")).unwrap()
}

#[test]
fn a_fresh_v2_wrapper_opens_to_the_same_master_key_and_not_with_another_key() {
    let v = vector();
    let master = crypto::decode_key(v["legacy_master"].as_str().unwrap()).unwrap();
    let wrap = crypto::decode_key(v["wrap_key_v2"].as_str().unwrap()).unwrap();
    let (wrapped, iv) = crypto::wrap_master_key_with_wrapping_key(&master, &wrap).unwrap();
    let opened = crypto::unwrap_master_key_with_wrapping_key(&wrapped, &iv, &wrap).unwrap();
    assert!(same_key(&opened, &master));
    let other = crypto::decode_key(v["auth_key_v2"].as_str().unwrap()).unwrap();
    assert!(crypto::unwrap_master_key_with_wrapping_key(&wrapped, &iv, &other).is_err());
}

#[test]
fn key_equality_detects_any_differing_byte() {
    let first = [7u8; 32];
    let mut second = first;
    assert!(same_key(&first, &second));
    second[31] ^= 1;
    assert!(!same_key(&first, &second));
}

#[tokio::test]
async fn a_signed_out_client_refuses_to_migrate_before_any_request() {
    let client = Client::new("https://api.example.org", None).unwrap();
    assert!(matches!(
        client.migrate_legacy_password("synthetic password").await,
        Err(Error::Authentication)
    ));
}
