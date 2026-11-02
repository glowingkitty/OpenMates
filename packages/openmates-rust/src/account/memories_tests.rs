// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only
use super::*;
use crate::Client;
use crate::account::test_support as http;

#[test]
fn registry_and_validation_keep_legacy_order_and_messages() {
    let types = memory_types();
    assert_eq!(types[0].key, "openmates/memories");
    assert!(
        types
            .iter()
            .all(|t| t.key == format!("{}/{}", t.app_id, t.item_type))
    );
    assert!(validate_memory("books", "favorite_books", &json!({"title":"Dune"})).is_ok());
    assert_eq!(
        validate_memory("books", "favorite_books", &json!({"title":""})).unwrap_err(),
        "Missing required fields for 'books/favorite_books': title\nRequired: title"
    );
    assert!(
        validate_memory("nope", "x", &json!({}))
            .unwrap_err()
            .starts_with("Unknown memory type 'nope/x'.\n\nAvailable types:\n  openmates/memories")
    );
    let with_enum = types
        .iter()
        .find_map(|t| {
            t.properties
                .iter()
                .find(|p| p.allowed.is_some())
                .map(|p| (t, p))
        })
        .expect("registry has enum fields");
    let (schema, field) = with_enum;
    let mut value = serde_json::Map::new();
    for required in &schema.required {
        value.insert(required.clone(), json!("x"));
    }
    value.insert(field.name.clone(), json!("definitely-not-allowed"));
    let error =
        validate_memory(&schema.app_id, &schema.item_type, &Value::Object(value)).unwrap_err();
    assert!(error.starts_with(&format!(
        "Invalid value 'definitely-not-allowed' for field '{}'. Allowed values: ",
        field.name
    )));
}

#[test]
fn store_payload_encrypts_item_json_and_hashes_the_item_key() {
    let entry = memory_entry(
        "entry-1",
        "books",
        "favorite_books",
        &json!({"title":"Private title"}),
        3,
        &[7; 32],
        std::time::Duration::from_millis(1_700_000_000_123),
    )
    .unwrap();
    let wire = entry.to_string();
    assert!(!wire.contains("Private title"));
    let row = &entry["entry"];
    assert_eq!(
        row["item_key"],
        hash_item_key("books", "favorite_books", 1_700_000_000_123)
    );
    assert_eq!(row["item_key"].as_str().unwrap().len(), 32);
    assert_eq!(
        (row["created_at"].clone(), row["item_version"].clone()),
        (json!(1_700_000_000u64), json!(3))
    );
    let plain: Value = serde_json::from_str(
        &crypto::decrypt_combined(row["encrypted_item_json"].as_str().unwrap(), &[7; 32]).unwrap(),
    )
    .unwrap();
    assert_eq!(
        plain,
        json!({"title":"Private title","settings_group":"books","_original_item_key":"favorite_books","added_date":1_700_000_000u64})
    );
}

#[tokio::test]
async fn list_decrypts_rows_skips_corrupt_ones_and_appends_account_documents() {
    let row = |id: &str, ciphertext: Value| json!({"id":id,"app_id":"books","item_type":"favorite_books","item_key":"hash","item_version":2,"created_at":5,"updated_at":6,"encrypted_item_json":ciphertext});
    let good = crypto::encrypt_combined(r#"{"title":"Dune"}"#, &[7; 32]).unwrap();
    let wrong_key = crypto::encrypt_combined(r#"{"title":"x"}"#, &[1; 32]).unwrap();
    let settings = crypto::encrypt_combined(
        &json!({"memory_documents":[{"id":"personal:guide","document":"---\ntitle: 'Writing guide'\n---\nBody"}]}).to_string(),
        &[7; 32],
    )
    .unwrap();
    let (api, server) = http::mock(vec![
        (200, json!({"memories":[row("m1", json!(good)), row("m2", json!(wrong_key)), row("m3", Value::Null)]})),
        (200, json!({"success":true,"ws_token":"synthetic","user":{"id":"owner","encrypted_settings":settings}})),
    ])
    .await;
    let mut client = Client::new(&api, Some(http::session(&api, None))).unwrap();
    let memories = client.account().memories().await.unwrap();
    assert_eq!(memories.len(), 2);
    assert_eq!(
        memories[0],
        json!({"id":"m1","app_id":"books","item_type":"favorite_books","item_key_hash":"hash","item_version":2,"created_at":5,"updated_at":6,"data":{"title":"Dune"}})
    );
    assert_eq!(memories[1]["id"], "account-memory-guide");
    assert_eq!(memories[1]["data"]["title"], "Writing guide");
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/sdk/memories "));
}

#[tokio::test]
async fn team_context_and_invalid_ids_fail_before_network() {
    let mut session = http::session("http://127.0.0.1:1", None);
    session.active_team_id = Some("00000000-0000-4000-8000-000000000001".into());
    let mut client = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
    assert!(matches!(
        client.account().memories().await,
        Err(Error::Unavailable {
            code: "team_memories_unavailable",
            ..
        })
    ));
    let mut client = Client::new(
        "http://127.0.0.1:1",
        Some(http::session("http://127.0.0.1:1", None)),
    )
    .unwrap();
    assert!(matches!(
        client.account().delete_memory("not-a-uuid").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        client
            .account()
            .create_memory("books", "favorite_books", &json!({}))
            .await,
        Err(Error::Invalid(_))
    ));
}
