// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use super::super::settings_more::tests::{mock, parsed};

fn invalid(result: Result<CliOutput, CliError>) -> String {
    match result {
        Err(CliError::Invalid(message)) => message,
        Err(_) => panic!("expected invalid input, got another error"),
        Ok(output) => panic!("expected invalid input, got {}", output.stdout),
    }
}

#[tokio::test]
async fn team_billing_export_and_import_route_like_npm() {
    let dir = tempfile::tempdir().unwrap();
    let export = dir.path().join("team.json");
    let export = export.to_str().unwrap();
    let address = dir.path().join("address.json");
    std::fs::write(&address, r#"{"name":"A","street_line_1":"S 1","postal_code":"1","city":"C","country":"de"}"#).unwrap();
    let address = address.to_str().unwrap();
    let commands: Vec<Vec<&str>> = vec![
        vec!["openmates", "teams", "billing", "address", "show", "team-1"],
        vec!["openmates", "teams", "billing", "address", "set", "team-1", "--billing-address-file", address],
        vec!["openmates", "teams", "billing", "bank-transfer", "create", "team-1", "--credits", "1000", "--json"],
        vec!["openmates", "teams", "billing", "bank-transfer", "status", "team-1", "o-1"],
        vec!["openmates", "teams", "billing", "bank-transfer", "list", "team-1", "--json"],
        vec!["openmates", "teams", "export", "team-1", "--output", export],
        vec!["openmates", "teams", "import", "--file", export, "--team", "team-2"],
    ];
    for args in &commands {
        let invocation = parsed(args);
        assert!(supported(&invocation), "{args:?}");
        assert!(super::super::super::handlers::requirements(&invocation).supported, "{args:?}");
    }
    let (mut client, server) = mock(vec![
        json!({"buyer_address":null}),
        json!({"success":true}),
        json!({"order_id":"o-1","credits_amount":1000}),
        json!({"order_id":"o-1","status":"pending","credits_amount":1000,"amount_eur":10,"reference":"R","expires_at":"soon"}),
        json!({"orders":[]}),
        json!({"artifact":{"version":1,"team":"x"}}),
        json!({"imported":true}),
    ])
    .await;
    let mut outputs = vec![];
    for args in &commands {
        outputs.push(execute(&parsed(args), &mut client).await.ok().unwrap().stdout);
    }
    assert_eq!(outputs[0], "{\n  \"buyer_address\": null\n}\n");
    assert_eq!(outputs[1], "Team billing address saved.\n");
    assert!(outputs[3].contains("Status: pending\n"));
    assert_eq!(outputs[5], format!("Team export written: {export}\n"));
    assert_eq!(serde_json::from_str::<Value>(&std::fs::read_to_string(export).unwrap()).unwrap(), json!({"version":1,"team":"x"}));
    #[cfg(unix)]
    assert_eq!(std::os::unix::fs::PermissionsExt::mode(&std::fs::metadata(export).unwrap().permissions()) & 0o777, 0o600);
    let requests = server.await.unwrap();
    assert!(requests[1].contains("\"country\":\"DE\""));
    assert!(requests[6].contains("\"artifact\":{\"team\":\"x\",\"version\":1}") || requests[6].contains("\"artifact\":{\"version\":1,\"team\":\"x\"}"));
    for (args, message) in [
        (vec!["openmates", "teams", "billing", "address", "set", "team-1"], "Provide --billing-address-file <json-file>."),
        (vec!["openmates", "teams", "billing", "bank-transfer", "create", "team-1", "--credits", "-5"], "Invalid --credits <amount>: -5"),
        (vec!["openmates", "teams", "export", "team-1"], "Missing --output <path>."),
        (vec!["openmates", "teams", "import", "--file", export], "Team import requires --team <team-id> or --new-team-name <name>."),
    ] {
        assert_eq!(invalid(execute(&parsed(&args), &mut client).await), message, "{args:?}");
    }
}

#[test]
fn switch_to_alias_parses_the_leading_team_selector() {
    let invocation = parsed(&["openmates", "teams", "acme", "switch-to"]);
    assert_eq!((invocation.path.join(" "), invocation.positionals.clone()), ("teams switch-to".to_owned(), vec!["acme".to_owned()]));
    assert!(super::super::super::handlers::requirements(&invocation).supported);
}
