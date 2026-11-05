// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

#[test]
fn processing_times_and_schedule_match_the_npm_rules() {
    assert_eq!(
        normalize_processing_times(&json!("18:00, 09:00,09:00")).unwrap(),
        ["09:00", "18:00"]
    );
    assert_eq!(normalize_processing_times(&Value::Null).unwrap(), ["09:00"]);
    assert_eq!(
        normalize_processing_times(&json!("9:00")).unwrap_err(),
        "Invalid IdeaBucket processing time '9:00'. Expected HH:MM in 24-hour format."
    );
    assert!(normalize_processing_times(&json!("01:00,02:00,03:00,04:00")).is_err());
    let day = 1_700_006_400; // 2023-11-15T00:00:00Z
    assert_eq!(
        next_send_at(day + 10 * 3600, &["09:00".into(), "18:00".into()]),
        day + 18 * 3600
    );
    assert_eq!(
        next_send_at(day + 19 * 3600, &["09:00".into(), "18:00".into()]),
        day + 86_400 + 9 * 3600
    );
    assert_eq!(today(day), "2023-11-15");
}

#[tokio::test]
async fn status_and_process_use_the_bucket_routes() {
    let (api, server) = mock(vec![
        (200, json!({"status":"idle"})),
        (200, json!({"status":"queued"})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    client
        .account()
        .ideabucket_status(Some("2026-11-02"))
        .await
        .unwrap();
    client
        .account()
        .process_ideabucket("2026-11-02", true)
        .await
        .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/ideabucket/buckets/2026-11-02 "));
    assert!(requests[1].starts_with("POST /v1/ideabucket/buckets/2026-11-02/process "));
    assert!(requests[1].ends_with(r#"{"now":true}"#));
}

#[test]
fn text_capture_encrypts_the_draft_and_future_message() {
    let chat = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
    let (draft, result) = text_draft(
        chat,
        "2026-11-02",
        123,
        "Prompt",
        "Private idea",
        100,
        &[7; 32],
        &[9; 32],
    )
    .unwrap();
    assert!(!draft.to_string().contains("Private idea"));
    let open = |field: &str, key: &[u8; 32]| {
        crate::crypto::decrypt_combined(draft[field].as_str().unwrap(), key).unwrap()
    };
    let markdown = "Prompt\n\n----- Idea 1 -----\nPrivate idea\n-----------------";
    assert_eq!(open("encrypted_draft_md", &[7; 32]), markdown);
    assert_eq!(
        open("client_encrypted_future_user_message", &[9; 32]),
        markdown
    );
    assert_eq!(
        open("encrypted_draft_preview", &[7; 32]),
        "IdeaBucket 2026-11-02: Private idea"
    );
    assert_eq!(
        crate::crypto::decrypt_bytes(draft["encrypted_chat_key"].as_str().unwrap(), &[7; 32])
            .unwrap()
            .as_slice(),
        [9; 32]
    );
    assert_eq!(
        (
            draft["ideabucket"].clone(),
            draft["scheduled_send_at"].clone()
        ),
        (json!(true), json!(123))
    );
    assert_eq!(result["markdown"], markdown);
    assert_eq!(result["payloadHash"].as_str().unwrap().len(), 64);
}
