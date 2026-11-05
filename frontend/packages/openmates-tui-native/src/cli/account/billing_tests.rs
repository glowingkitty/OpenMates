// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use super::super::settings_more::tests::{mock, parsed};

fn invalid(result: Result<CliOutput, CliError>) -> String {
    match result {
        Err(CliError::Invalid(message)) => message,
        Err(other) => panic!("expected invalid input, got {}", other.code()),
        Ok(output) => panic!("expected invalid input, got {}", output.stdout),
    }
}

#[tokio::test]
async fn personal_billing_purchases_route_and_print_like_npm() {
    let dir = tempfile::tempdir().unwrap();
    let address = dir.path().join("address.json");
    std::fs::write(&address, r#"{"name":"A","street_line_1":"S 1","postal_code":"1","city":"C","country":"nl"}"#).unwrap();
    let address = address.to_str().unwrap();
    let commands: Vec<Vec<&str>> = vec![
        vec!["openmates", "settings", "billing", "address", "show"],
        vec!["openmates", "settings", "billing", "address", "set", "--billing-address-file", address],
        vec!["openmates", "settings", "billing", "address", "clear"],
        vec!["openmates", "settings", "billing", "buy-credits", "bank-transfer", "--credits", "110000"],
        vec!["openmates", "settings", "billing", "bank-transfer", "status", "o-1"],
        vec!["openmates", "settings", "billing", "gift-card", "buy", "bank-transfer", "--credits", "21000", "--json"],
        vec!["openmates", "settings", "billing", "gift-card", "purchase-status", "g-1"],
        vec!["openmates", "settings", "billing", "gift-card", "purchased", "--json"],
        vec!["openmates", "settings", "billing", "invoices", "refund", "inv-1", "--yes", "--json"],
        vec!["openmates", "settings", "billing", "auto-topup", "low-balance", "set", "--enabled", "off", "--amount", "1000", "--json"],
    ];
    for args in &commands {
        let invocation = parsed(args);
        assert!(supported(&invocation), "{args:?}");
        assert!(super::super::super::handlers::requirements(&invocation).supported, "{args:?}");
    }
    let (mut client, server) = mock(vec![
        json!({"buyer_address":{"country":"NL"}}),
        json!({"success":true}),
        json!({"success":true}),
        json!({"order_id":"o-1","credits_amount":110000,"amount_eur":110,"reference":"OM-1","iban":"DE00","bic":"B","bank_name":"Bank","account_holder_name":"OpenMates","expires_at":"2026-11-30"}),
        json!({"order_id":"o-1","status":"pending","credits_amount":110000,"amount_eur":110,"reference":"OM-1","expires_at":"2026-11-30"}),
        json!({"order_id":"g-1"}),
        json!({"order_id":"g-1","status":"paid","credits_amount":21000,"amount_eur":21,"reference":"OM-2","expires_at":"x","gift_card_code":"CODE-1"}),
        json!({"gift_cards":[]}),
        json!({"success":true}),
        json!({"success":true}),
    ])
    .await;
    let mut outputs = vec![];
    for args in &commands {
        outputs.push(execute(&parsed(args), &mut client).await.ok().unwrap().stdout);
    }
    assert_eq!(outputs[0], "{\n  \"buyer_address\": {\n    \"country\": \"NL\"\n  }\n}\n");
    assert_eq!(outputs[1], "Personal billing address saved.\n");
    assert_eq!(outputs[2], "Personal billing address cleared.\n");
    assert!(outputs[3].starts_with("\x1b[1mBank Transfer\x1b[0m\nOrder ID: o-1\nCredits: 110000\nAmount: EUR 110\n"));
    assert!(outputs[3].ends_with("Check status: openmates settings billing bank-transfer status o-1\n"));
    assert!(outputs[4].contains("Status: pending\n"));
    assert!(outputs[6].starts_with("\x1b[1mGift Card Purchase Status\x1b[0m") && outputs[6].ends_with("Gift-card code: CODE-1\n"));
    let requests = server.await.unwrap();
    assert!(requests[1].contains("\"country\":\"NL\""));
    assert!(requests[8].starts_with("POST /v1/payments/refund "));
    assert!(requests[9].contains("\"enabled\":false"));
    for (args, message) in [
        (vec!["openmates", "settings", "billing", "address", "set"], "Provide --billing-address-file <json-file>."),
        (vec!["openmates", "settings", "billing", "buy-credits", "bank-transfer"], "Missing --credits."),
        (vec!["openmates", "settings", "billing", "buy-credits", "bank-transfer", "--credits", "lots"], "Invalid --credits: lots"),
        (vec!["openmates", "settings", "billing", "auto-topup", "low-balance", "set", "--enabled", "on", "--amount", "5"], "Provide --email when enabling low-balance auto top-up."),
        (vec!["openmates", "settings", "billing", "auto-topup", "low-balance", "set", "--enabled", "maybe", "--amount", "5"], "Invalid low-balance auto top-up value 'maybe'. Use on/off or true/false."),
    ] {
        assert_eq!(invalid(execute(&parsed(&args), &mut client).await), message, "{args:?}");
    }
}
