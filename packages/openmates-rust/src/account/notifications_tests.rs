// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

#[tokio::test]
async fn notification_list_and_newsletter_routes_match_npm() {
    let (api, server) = mock(vec![
        (200, json!({"notifications":[]})),
        (200, json!({"categories":{}})),
        (200, json!({"success":true})),
        (200, json!({"success":true})),
        (200, json!({"success":true})),
        (200, json!({"success":true})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let mut account = client.account();
    account.notifications(25).await.unwrap();
    account.newsletter_categories().await.unwrap();
    account
        .update_newsletter_categories(json!({"tips_and_tricks":false}))
        .await
        .unwrap();
    account
        .subscribe_newsletter("me@example.org", "de", true)
        .await
        .unwrap();
    account.confirm_newsletter("tok-1").await.unwrap();
    account.unsubscribe_newsletter("tok-2").await.unwrap();
    assert!(account.confirm_newsletter("../x").await.is_err());
    let requests = server.await.unwrap();
    for (request, expected) in requests.iter().zip([
        "GET /v1/notifications?limit=25 ",
        "GET /v1/newsletter/categories ",
        "PATCH /v1/newsletter/categories ",
        "POST /v1/newsletter/subscribe ",
        "GET /v1/newsletter/confirm/tok-1 ",
        "GET /v1/newsletter/unsubscribe/tok-2 ",
    ]) {
        assert!(request.starts_with(expected), "{request}");
    }
    assert!(requests[2].ends_with(r#"{"categories":{"tips_and_tricks":false}}"#));
    assert!(
        requests[3].ends_with(r#"{"darkmode":true,"email":"me@example.org","language":"de"}"#)
            || requests[3].contains(r#""language":"de""#)
    );
}
