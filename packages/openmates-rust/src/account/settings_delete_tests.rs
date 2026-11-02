// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

#[tokio::test]
async fn account_deletion_sends_the_verified_method_and_forgets_the_session() {
    let (api, server) = mock(vec![
        (200, json!({"success":true})),
        (200, json!({"success":true})),
        (200, json!({"has_2fa":true})),
        (200, json!({"success":true,"message":"Deletion scheduled"})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, Some("email-key")))).unwrap();
    client.account().request_action_email_code(VerifiedAction::DeleteAccount).await.unwrap();
    client.account().verify_action_email_code(VerifiedAction::DeleteAccount, "123456").await.unwrap();
    assert_eq!(client.account().auth_methods().await.unwrap()["has_2fa"], true);
    client.account().delete_account(Some("654321")).await.unwrap();
    assert!(client.session().is_none(), "the deleted account's credentials are dropped");
    let requests = server.await.unwrap();
    let body = |i: usize| serde_json::from_str::<Value>(requests[i].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert!(requests[0].starts_with("POST /v1/settings/request-action-verification "));
    assert_eq!(body(0), json!({"action":"delete_account","email_encryption_key":"email-key"}));
    assert_eq!(body(1), json!({"action":"delete_account","code":"123456"}));
    assert!(requests[2].starts_with("GET /v1/auth/methods "));
    assert_eq!(
        body(3),
        json!({"confirm_data_deletion":true,"auth_method":"2fa_otp","auth_code":"654321","email_encryption_key":"email-key","require_email_verification":true})
    );
}
