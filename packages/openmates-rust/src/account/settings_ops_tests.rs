// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

fn body(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}

#[tokio::test]
async fn reminder_mutations_use_fixed_routes_and_reject_unsafe_ids() {
    let (api, server) = mock(vec![
        (200, json!({"success":true})),
        (200, json!({"success":true})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let id = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
    client
        .account()
        .update_reminder(id, json!({"enabled":false}))
        .await
        .unwrap();
    client.account().delete_reminder(id).await.unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("PATCH /v1/settings/reminders/{id} ")));
    assert_eq!(body(&requests[0]), json!({"enabled":false}));
    assert!(requests[1].starts_with(&format!("DELETE /v1/settings/reminders/{id} ")));
    let mut offline = Client::new(
        "http://127.0.0.1:1",
        Some(session("http://127.0.0.1:1", None)),
    )
    .unwrap();
    for bad in ["../users", "a/b", "", "id?x=1", ".."] {
        assert!(
            matches!(
                offline.account().delete_reminder(bad).await,
                Err(Error::Invalid(_))
            ),
            "{bad}"
        );
    }
    assert!(matches!(
        offline.account().update_reminder(id, json!({})).await,
        Err(Error::Invalid(_))
    ));
}

#[tokio::test]
async fn gift_card_redemption_sends_the_session_email_key_or_derives_it_locally() {
    let (api, server) = mock(vec![(
        200,
        json!({"success":true,"credits_added":100,"current_credits":250,"message":"ok"}),
    )])
    .await;
    let mut client = Client::new(&api, Some(session(&api, Some("session-email-key")))).unwrap();
    let value = client
        .account()
        .redeem_gift_card(" GIFT-1234 ")
        .await
        .unwrap();
    assert_eq!(value["credits_added"], 100);
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/payments/redeem-gift-card "));
    assert_eq!(
        body(&requests[0]),
        json!({"code":"GIFT-1234","email_encryption_key":"session-email-key"})
    );

    let encrypted = crypto::encrypt_combined("person@example.org", &[7; 32]).unwrap();
    let (api, server) = mock(vec![
        (200, json!({"success":true,"ws_token":"synthetic","user":{"id":"owner","encrypted_email_with_master_key":encrypted}})),
        (200, json!({"success":true})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    client.account().redeem_gift_card("GIFT").await.unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/auth/session "));
    assert_eq!(
        body(&requests[1])["email_encryption_key"],
        crypto::derive_email_key("person@example.org", "c2FsdA==").unwrap()
    );
    assert!(!requests[1].contains("person@example.org"));
}

#[tokio::test]
async fn billing_and_export_reads_use_legacy_routes_and_shapes() {
    let (api, server) = mock(vec![
        (200, json!({})),
        (200, json!({"invoices":[{"id":"in_1"}]})),
        (200, json!([])),
        (200, json!({"cards":[]})),
        (200, json!({"export":{"export_id":"exp-1"}})),
        (200, json!({"manifest":{}})),
        (200, json!({"manifest":{}})),
        (200, json!({"chunks":[]})),
        (200, json!({"chunk":{"chunk_id":"c-1"}})),
        (200, json!({"export":{"status":"cancelled"}})),
        (200, json!({"export":{"status":"accepted"}})),
        (200, json!({"data":{}})),
        (200, json!({"preview":true})),
        (200, json!({"deleted":3})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let mut account = client.account();
    assert_eq!(account.invoices().await.unwrap(), json!({"invoices":[]}));
    assert_eq!(
        account.invoices().await.unwrap()["invoices"][0]["id"],
        "in_1"
    );
    account.bank_transfer_orders().await.unwrap();
    account.redeemed_gift_cards().await.unwrap();
    account.account_export("exp-1").await.unwrap();
    account
        .account_export_manifest(Some("exp-1"))
        .await
        .unwrap();
    account.account_export_manifest(None).await.unwrap();
    account.account_export_chunks("exp-1").await.unwrap();
    assert_eq!(
        account.account_export_chunk("exp-1", "c-1").await.unwrap(),
        json!({"chunk_id":"c-1"})
    );
    account.cancel_account_export("exp-1").await.unwrap();
    account
        .accept_partial_account_export("exp-1")
        .await
        .unwrap();
    account.account_export_data().await.unwrap();
    account.delete_account_preview().await.unwrap();
    account
        .delete_stored_files(StoredFileDeletion::Category("images"))
        .await
        .unwrap();
    let requests = server.await.unwrap();
    let lines = requests
        .iter()
        .map(|r| r.lines().next().unwrap().to_owned())
        .collect::<Vec<_>>();
    for (line, expected) in lines.iter().zip([
        "GET /v1/payments/invoices ",
        "GET /v1/payments/invoices ",
        "GET /v1/payments/bank-transfer-pending ",
        "GET /v1/payments/redeemed-gift-cards ",
        "GET /v1/account-exports/exp-1 ",
        "GET /v1/account-exports/exp-1/manifest ",
        "GET /v1/settings/export-account-manifest ",
        "GET /v1/account-exports/exp-1/chunks ",
        "GET /v1/account-exports/exp-1/chunks/c-1 ",
        "POST /v1/account-exports/exp-1/cancel ",
        "POST /v1/account-exports/exp-1/accept-partial ",
        "GET /v1/settings/export-account-data ",
        "GET /v1/settings/delete-account-preview ",
        "DELETE /v1/settings/storage/files ",
    ]) {
        assert!(line.starts_with(expected), "{line} != {expected}");
    }
    assert_eq!(
        body(&requests[13]),
        json!({"scope":"category","category":"images"})
    );
}
