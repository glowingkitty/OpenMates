// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

fn body(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}

#[tokio::test]
async fn writes_use_fixed_routes_and_payloads() {
    let ok = || (200, json!({"success":true}));
    let (api, server) = mock(vec![ok(), ok(), ok(), ok(), ok(), ok()]).await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    client.account().report_issue("Bug", "It broke").await.unwrap();
    client.account().report_issue_status("abc-123").await.unwrap();
    client.account().set_chat_auto_delete("90d").await.unwrap();
    client.account().share_debug_logs("1h").await.unwrap();
    client
        .account()
        .set_ai_model_defaults(Some(Some("mistral/small")), Some(None), None)
        .await
        .unwrap();
    client.account().record_mates_consent().await.unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/settings/issues "));
    assert_eq!(body(&requests[0]), json!({"title":"Bug","description":"It broke"}));
    assert!(requests[1].starts_with("GET /v1/settings/issues/abc-123/status "));
    assert_eq!(body(&requests[2]), json!({"period":"90d"}));
    assert!(requests[3].starts_with("POST /v1/settings/debug-session "));
    assert_eq!(
        body(&requests[4]),
        json!({"default_ai_model_simple":"mistral/small","default_ai_model_complex":null})
    );
    assert!(requests[5].starts_with("POST /v1/settings/user/consent/mates "));
    assert_eq!(body(&requests[5]), json!({"consent":true}));
}

#[tokio::test]
async fn invalid_input_never_reaches_the_network() {
    let mut offline = Client::new("http://127.0.0.1:1", Some(session("http://127.0.0.1:1", None))).unwrap();
    assert!(matches!(offline.account().report_issue_status("a/b").await, Err(Error::Invalid(_))));
    assert!(matches!(offline.account().set_chat_auto_delete(" ").await, Err(Error::Invalid(_))));
    assert!(matches!(offline.account().set_ai_model_defaults(None, None, None).await, Err(Error::Invalid(_))));
}
