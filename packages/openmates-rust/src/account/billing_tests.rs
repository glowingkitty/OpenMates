// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::Client;
use crate::account::test_support::{mock, session};

#[test]
fn buyer_address_validation_keeps_npm_messages() {
    let ok = validate_buyer_address(
        &json!({"name":"A","street_line_1":"S 1","postal_code":"1","city":"C","country":"de"}),
    )
    .unwrap();
    assert_eq!(ok["country"], "DE");
    assert_eq!(
        validate_buyer_address(&json!([])),
        Err(Error::Invalid("Billing address must be a JSON object."))
    );
    assert_eq!(
        validate_buyer_address(&json!({"name":"A"})),
        Err(Error::Invalid("Billing address requires street_line_1."))
    );
    assert_eq!(
        validate_buyer_address(
            &json!({"name":"A","street_line_1":"S","postal_code":"1","city":"C","country":"DEU"})
        ),
        Err(Error::Invalid(
            "Billing address country must be a two-letter country code."
        ))
    );
}

#[tokio::test]
async fn team_billing_routes_match_npm() {
    let (api, server) = mock(vec![
        (200, json!({"buyer_address":null})),
        (200, json!({"success":true})),
        (200, json!({"order_id":"o-1","credits_amount":1000})),
        (200, json!({"order_id":"o-1","status":"pending"})),
        (200, json!({"orders":[{"order_id":"o-1"}]})),
        (200, json!({"artifact":{"version":1}})),
        (200, json!({"imported":true})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, Some("email-key")))).unwrap();
    assert_eq!(
        client
            .account()
            .buyer_address(Some("team-1"))
            .await
            .unwrap(),
        Value::Null
    );
    client
        .account()
        .save_buyer_address(Some("team-1"), None)
        .await
        .unwrap();
    let mut teams = client.teams();
    assert_eq!(
        teams
            .create_bank_transfer("team-1", 1000.0, None)
            .await
            .unwrap()["order_id"],
        "o-1"
    );
    assert_eq!(
        teams.bank_transfer_status("team-1", "o-1").await.unwrap()["status"],
        "pending"
    );
    assert_eq!(
        teams.bank_transfer_orders("team-1").await.unwrap()[0]["order_id"],
        "o-1"
    );
    assert_eq!(
        teams.export("team-1").await.unwrap()["artifact"]["version"],
        1
    );
    assert_eq!(
        teams.import("team-2", json!({"version":1})).await.unwrap()["imported"],
        true
    );
    assert!(teams.export("../x").await.is_err());
    let requests = server.await.unwrap();
    let lines: Vec<&str> = requests.iter().map(|r| r.lines().next().unwrap()).collect();
    assert_eq!(
        lines,
        [
            "GET /v1/teams/team-1/billing/buyer-address HTTP/1.1",
            "PUT /v1/teams/team-1/billing/buyer-address HTTP/1.1",
            "POST /v1/teams/team-1/billing/bank-transfer-orders HTTP/1.1",
            "GET /v1/teams/team-1/billing/bank-transfer-orders/o-1 HTTP/1.1",
            "GET /v1/teams/team-1/billing/bank-transfer-orders HTTP/1.1",
            "POST /v1/teams/team-1/export HTTP/1.1",
            "POST /v1/teams/import HTTP/1.1",
        ]
    );
    assert!(requests[1].ends_with("{\"buyer_address\":null}"));
    assert!(
        requests[2].contains("\"email_encryption_key\":\"email-key\"")
            && requests[2].contains("\"currency\":\"eur\"")
    );
    assert!(requests[6].contains("\"destination_team_id\":\"team-2\""));
}

#[tokio::test]
async fn personal_purchases_carry_the_email_key_and_fixed_routes() {
    let (api, server) = mock(vec![
        (200, json!({"order_id":"o-1"})),
        (200, json!({"status":"pending"})),
        (200, json!({"order_id":"g-1"})),
        (200, json!({"status":"paid","gift_card_code":"CODE"})),
        (200, json!({"gift_cards":[]})),
        (200, json!({"success":true})),
        (200, json!({"success":true})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, Some("email-key")))).unwrap();
    let mut account = client.account();
    account
        .create_bank_transfer_order(110000.0, None)
        .await
        .unwrap();
    account.bank_transfer_status("o-1").await.unwrap();
    account
        .create_gift_card_bank_transfer_order(21000.0)
        .await
        .unwrap();
    account.gift_card_purchase_status("g-1").await.unwrap();
    account.purchased_gift_cards().await.unwrap();
    account.request_refund("inv-1").await.unwrap();
    assert_eq!(
        account
            .set_low_balance_auto_topup(true, 1000.0, "eur", None)
            .await,
        Err(Error::Invalid(
            "Provide --email when enabling low-balance auto top-up."
        ))
    );
    account
        .set_low_balance_auto_topup(false, 1000.0, "eur", None)
        .await
        .unwrap();
    let requests = server.await.unwrap();
    let lines: Vec<&str> = requests.iter().map(|r| r.lines().next().unwrap()).collect();
    assert_eq!(
        lines,
        [
            "POST /v1/payments/create-bank-transfer-order HTTP/1.1",
            "GET /v1/payments/bank-transfer-status/o-1 HTTP/1.1",
            "POST /v1/payments/create-gift-card-bank-transfer-order HTTP/1.1",
            "GET /v1/payments/gift-card-purchase-status/g-1 HTTP/1.1",
            "GET /v1/payments/purchased-gift-cards HTTP/1.1",
            "POST /v1/payments/refund HTTP/1.1",
            "POST /v1/settings/auto-topup/low-balance HTTP/1.1",
        ]
    );
    for index in [0, 2, 5] {
        assert!(requests[index].contains("\"email_encryption_key\":\"email-key\""));
    }
    assert!(requests[6].contains("\"threshold\":100"));
}
