use _native::SessionBridge;
use serde_json::{Value, json};
fn options() -> String {
    json!({"api_url":"https://api.example.invalid","app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()
}
fn session() -> Value {
    json!({"api_url":"https://api.example.invalid","session_id":"synthetic-session","cookies":{"auth_refresh_token":"synthetic-cookie"},"ws_token":null,"master_key":"AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=","hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})
}
#[tokio::test]
async fn direct_sdk_session_import_export_and_policy_refusal() {
    let bridge = SessionBridge::new(&options()).unwrap_or_else(|_| panic!("construct"));
    bridge
        .import_session(session().to_string())
        .await
        .unwrap_or_else(|_| panic!("import"));
    assert_eq!(
        bridge.export_session(false).await.err().map(|e| e.code),
        Some("forbidden")
    );
    let snapshot: Value = serde_json::from_str(
        &bridge
            .export_session(true)
            .await
            .unwrap_or_else(|_| panic!("export")),
    )
    .unwrap();
    assert_eq!(snapshot["session"], session());
    let id = bridge
        .start_send("Synthetic test".into(), None)
        .await
        .unwrap_or_else(|_| panic!("send"));
    let event: Value = serde_json::from_str(
        &bridge
            .next_event(id)
            .await
            .unwrap_or_else(|_| panic!("event")),
    )
    .unwrap();
    assert_eq!(event["type"], "error");
    assert_eq!(event["error"]["code"], "forbidden");
    assert_eq!(
        bridge
            .consent("invented-request".into(), vec![])
            .err()
            .map(|e| e.code),
        Some("forbidden")
    );
    bridge.close().await.unwrap_or_else(|_| panic!("close"));
    assert_eq!(
        bridge.export_session(true).await.err().map(|e| e.code),
        Some("cancelled")
    );
}
#[tokio::test]
async fn imported_session_cannot_change_the_explicit_endpoint() {
    let bridge = SessionBridge::new(&options()).unwrap_or_else(|_| panic!("construct"));
    let mut value = session();
    value["api_url"] = json!("https://other.example.invalid");
    assert_eq!(
        bridge
            .import_session(value.to_string())
            .await
            .err()
            .map(|e| e.code),
        Some("forbidden")
    );
    assert_eq!(
        bridge.export_session(true).await.err().map(|e| e.code),
        Some("authentication")
    );
}
#[test]
fn invalid_options_and_unsupported_enhanced_privacy_fail_closed() {
    assert_eq!(
        SessionBridge::new(r#"{"api_url":"https://api.example.invalid"}"#)
            .err()
            .map(|e| e.code),
        Some("invalid_argument")
    );
    let mut value: Value = serde_json::from_str(&options()).unwrap();
    value["enhanced_privacy"] = json!(true);
    assert_eq!(
        SessionBridge::new(&value.to_string()).err().map(|e| e.code),
        Some("invalid_argument")
    );
    value["enhanced_privacy"] = json!(false);
    value["api_url"] = json!("https://synthetic-secret@api.example.invalid");
    let error = SessionBridge::new(&value.to_string()).err().unwrap();
    assert!(!error.json().contains("synthetic-secret"));
}

#[tokio::test]
async fn cancellation_and_stream_ids_cannot_orphan_or_cross_a_turn() {
    let bridge = SessionBridge::new(&options()).unwrap_or_else(|_| panic!("construct"));
    bridge
        .import_session(session().to_string())
        .await
        .unwrap_or_else(|_| panic!("import"));
    let id = bridge
        .start_send("Synthetic".into(), None)
        .await
        .unwrap_or_else(|_| panic!("start"));
    assert_eq!(
        bridge
            .start_send("Concurrent".into(), None)
            .await
            .err()
            .map(|e| e.code),
        Some("conflict")
    );
    bridge.cancel().unwrap_or_else(|_| panic!("cancel"));
    assert_eq!(
        bridge
            .next_event("wrong-stream".into())
            .await
            .err()
            .map(|e| e.code),
        Some("conflict")
    );
    let event: Value = serde_json::from_str(
        &bridge
            .next_event(id)
            .await
            .unwrap_or_else(|_| panic!("event")),
    )
    .unwrap();
    assert_eq!(event["type"], "error");
    assert_eq!(event["error"]["code"], "cancelled");
    let second = bridge
        .start_send("Next".into(), None)
        .await
        .unwrap_or_else(|_| panic!("second"));
    let event: Value = serde_json::from_str(
        &bridge
            .next_event(second)
            .await
            .unwrap_or_else(|_| panic!("next")),
    )
    .unwrap();
    assert_eq!(event["error"]["code"], "forbidden");
    bridge.close().await.unwrap_or_else(|_| panic!("close"));
}
