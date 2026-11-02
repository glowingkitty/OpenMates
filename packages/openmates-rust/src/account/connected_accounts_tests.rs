// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

fn transfer(passcode: &str, payload: &Value) -> String {
    let salt = [3u8; 16];
    let iv = [4u8; 12];
    let mut key = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(passcode.as_bytes(), &salt, ITERATIONS, &mut key);
    let text = crypto::encrypt_aead(payload.to_string().as_bytes(), &key, &iv, &[]).unwrap();
    let envelope = json!({"version":1,"kdf":{"name":"PBKDF2-SHA256","iterations":ITERATIONS,"salt":URL_SAFE_NO_PAD.encode(salt)},
        "cipher":{"name":"AES-256-GCM","iv":URL_SAFE_NO_PAD.encode(iv),"text":URL_SAFE_NO_PAD.encode(text)}});
    format!("{PREFIX}{}", URL_SAFE_NO_PAD.encode(envelope.to_string()))
}
fn payload() -> Value {
    json!({"version":1,"provider_id":"google_calendar","app_id":"google_calendar","label":"Work","capabilities":["read","write"],
        "runtime_modes":{},"refresh_token_bundle":{"refresh_token":"secret-refresh","scopes":["calendar"]},"created_at":"2026-11-02"})
}

#[tokio::test]
async fn import_reencrypts_the_transfer_with_the_master_key_and_never_sends_plaintext_tokens() {
    let (api, server) = mock(vec![
        (200, json!({"valid":true,"provider_id":"google_calendar"})),
        (
            200,
            json!({"success":true,"ws_token":"synthetic","user":{"id":"owner"}}),
        ),
        (200, json!({"id":"stored-1","sync_version":1})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let result = client
        .account()
        .import_connected_account(&transfer("1234", &payload()), "1234")
        .await
        .unwrap();
    assert_eq!(
        (result["id"].as_str(), result["app_id"].as_str()),
        (Some("stored-1"), Some("google_calendar"))
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/connected-accounts/validate-import "));
    assert!(requests[2].starts_with("POST /v1/connected-accounts "));
    assert!(!requests[2].contains("secret-refresh"));
    let row: Value = serde_json::from_str(requests[2].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let open =
        |field: &str| crypto::decrypt_combined(row[field].as_str().unwrap(), &[7; 32]).unwrap();
    assert_eq!(open("encrypted_provider_type"), "google_calendar");
    assert_eq!(
        serde_json::from_str::<Value>(&open("encrypted_app_permissions")).unwrap(),
        json!({"app_id":"calendar","allowed_actions":["read","write","update"],"scopes":["calendar"]})
    );
    assert_eq!(row["hashed_user_id"], sha256_hex("owner"));
}

#[test]
fn transfer_errors_keep_npm_messages() {
    assert_eq!(
        decrypt_connected_account_transfer("nope", "1"),
        Err(Error::Invalid(
            "Connected account import payload must start with OMCA1."
        ))
    );
    assert_eq!(
        decrypt_connected_account_transfer(&transfer("1234", &payload()), "9999"),
        Err(Error::Invalid(
            "Could not decrypt connected account import payload. Check the passcode and payload."
        ))
    );
    let mut missing = payload();
    missing["refresh_token_bundle"] = json!({});
    assert_eq!(
        decrypt_connected_account_transfer(&transfer("1", &missing), "1"),
        Err(Error::Invalid(
            "Import payload is missing refresh token material."
        ))
    );
}

#[test]
fn revolut_consent_url_matches_npm_url_search_params() {
    assert_eq!(
        revolut_business_consent_url(false, " cid ", None, None).unwrap(),
        "https://sandbox-business.revolut.com/app-confirm?client_id=cid&redirect_uri=https%3A%2F%2Fapp.dev.openmates.org%2Foauth%2Frevolut-business%2Fcallback&response_type=code&scope=READ"
    );
    assert_eq!(
        revolut_business_consent_url(true, "c", Some("https://x.test/cb"), Some("READ WRITE"))
            .unwrap(),
        "https://business.revolut.com/app-confirm?client_id=c&redirect_uri=https%3A%2F%2Fx.test%2Fcb&response_type=code&scope=READ+WRITE"
    );
    assert_eq!(
        revolut_business_consent_url(false, " ", None, None),
        Err(Error::Invalid("Missing Revolut Business client ID."))
    );
}

/// Node crypto (PBKDF2-SHA256 + AES-256-GCM, the npm envelope) generated vector.
pub(crate) const NODE_TRANSFER: &str = "OMCA1.eyJ2ZXJzaW9uIjoxLCJrZGYiOnsibmFtZSI6IlBCS0RGMi1TSEEyNTYiLCJpdGVyYXRpb25zIjoxMDAwMDAsInNhbHQiOiJDUWtKQ1FrSkNRa0pDUWtKQ1FrSkNRIn0sImNpcGhlciI6eyJuYW1lIjoiQUVTLTI1Ni1HQ00iLCJpdiI6IkNBZ0lDQWdJQ0FnSUNBZ0kiLCJ0ZXh0IjoiWndVeVgwRl9LM1dFV3phQ3hIaERZS19FNWVDUWZIR2ZUY1MxaXJNc1piaElacnE2TXFkMU5YTnoza1d1aGdza1BGTVpVWk12SGlIam9aa1pXY3E4Rzh3azkyRC1OblBrZHVOYnR2emtRSlN4cURtVklWM214a2RYUHZJQV9WREpaVk5aS2w5UXFYckpXbGo2a28yY250YzZHSnp6Mk9GWjFTWGE2NUF6OXFQYXF2Qjh3eENtaEpZbzFHWUVjZ1ljdXE1SWZkLVRjOV92Mk1OMTVGM1dmMFdNbl8zNnM0ZlB3Q0RpdWdZeUJVWF9wcnpaaTBRTlJ4LVl1UE43Zldydkt5WVBFRFFPU1NQVXN0WEU1V2JXYWxOVHBianFfaVVZaUdGbndnN1ZHbmg1RF9tVjMxSHRqY21CNVc5QzlucTNhemtXRFgwQUpvczV3SHlHIn19";
#[test]
fn node_generated_transfer_decrypts() {
    let value = decrypt_connected_account_transfer(NODE_TRANSFER, "2468").unwrap();
    assert_eq!(
        value["refresh_token_bundle"]["refresh_token"],
        "secret-refresh"
    );
    assert_eq!(value["label"], "Work");
}
