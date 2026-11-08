// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only
use super::*;
use crate::{ApiKey, ClientOptions, SdkCredentials, SdkOptions};
use base64::{Engine, engine::general_purpose::STANDARD};

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../../tests/sdk-conformance/fixtures/sdk-api-key-memories.json"
    ))
    .unwrap()
}
fn key(fixture: &Value, name: &str) -> [u8; 32] {
    STANDARD
        .decode(fixture[name].as_str().unwrap())
        .unwrap()
        .try_into()
        .unwrap()
}
fn client(credentials: SdkCredentials) -> OpenMates {
    OpenMates::new(SdkOptions {
        api_url: "http://127.0.0.1:1".into(),
        credentials,
        device_id: "synthetic-memories-device".into(),
        client_options: ClientOptions::default(),
    })
    .unwrap()
}

#[test]
fn npm_generated_ciphertexts_decrypt_with_the_shared_master_key() {
    let f = fixture();
    let master = key(&f, "master_key_b64");
    for vector in f["vectors"].as_array().unwrap() {
        let row = json!({"id":"m1","encrypted_item_json":vector["ciphertext"],"item_version":2});
        let decoded = decrypt_row(&row, &master).unwrap();
        let expected = serde_json::from_str::<Value>(vector["plaintext"].as_str().unwrap())
            .unwrap_or_else(|_| vector["plaintext"].clone());
        assert_eq!(decoded["data"], expected, "{}", vector["name"]);
        assert_eq!(decoded["id"], "m1");
        assert_eq!(decoded["item_version"], 2);
    }
    assert_eq!(
        decrypt_row(
            &json!({"encrypted_item_json":f["vectors"][0]["ciphertext"]}),
            &[9; 32]
        )
        .unwrap()["data"],
        Value::Null
    );
    assert_eq!(
        decrypt_row(&json!({"id":"plain"}), &master).unwrap(),
        json!({"id":"plain"})
    );
}

#[test]
fn memory_plaintext_decodes_like_npm_parse_maybe_json() {
    assert_eq!(memory_data(""), Value::Null);
    assert_eq!(memory_data(r#"{"a":1}"#), json!({"a": 1}));
    assert_eq!(
        memory_data("title: Dune\ntags[2]: sci-fi,classic\nrating: 4.5"),
        json!({"title": "Dune", "tags": ["sci-fi", "classic"], "rating": 4.5})
    );
    assert_eq!(
        memory_data("items[2]{id,label}:\n  1,first\n  2,second"),
        json!({"items": [{"id": 1, "label": "first"}, {"id": 2, "label": "second"}]})
    );
}
#[test]
fn rust_ciphertext_round_trips_with_the_npm_chat_key_wrapper() {
    let f = fixture();
    let master = key(&f, "master_key_b64");
    let chat = crypto::decrypt_bytes(f["wrapped_chat_key"].as_str().unwrap(), &master).unwrap();
    assert_eq!(chat.as_slice(), key(&f, "chat_key_b64"));
    let written = crypto::encrypt_combined(r#"{"k":"v"}"#, &master).unwrap();
    assert_eq!(
        decrypt_row(&json!({"encrypted_item_json":written}), &master).unwrap()["data"]["k"],
        "v"
    );
}

#[tokio::test]
async fn confirmation_and_anonymous_refusals_precede_transport() {
    let mut api = client(SdkCredentials::ApiKey(
        ApiKey::new("sk-api-memoriesOwnerA.localSetupSuffix").unwrap(),
    ));
    assert!(matches!(
        api.memories().delete("m1", false).await,
        Err(Error::Invalid(_))
    ));
    let mut anon = client(SdkCredentials::Anonymous {
        anonymous_id: "synthetic-memories-anon".into(),
    });
    assert_eq!(anon.memories().list(&[]).await, Err(Error::Authentication));
    let cancel = tokio_util::sync::CancellationToken::new();
    cancel.cancel();
    api.set_operation_cancel(cancel);
    assert_eq!(api.memories().list(&[]).await, Err(Error::Cancelled));
}
