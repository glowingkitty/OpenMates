// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::settings_more::tests::{mock, parsed};
use super::*;

const TEAM: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

#[test]
fn legacy_team_syntax_routes_to_the_native_handler() {
    for args in [
        vec!["openmates", "teams", "list"],
        vec!["openmates", "teams", "show", TEAM, "--json"],
        vec!["openmates", "teams", "switch", "eng"],
        vec!["openmates", "teams", "create", "--name", "Eng", "--switch"],
        vec!["openmates", "teams", "update", TEAM, "--slug", "eng"],
        vec!["openmates", "teams", "delete", TEAM, "--yes"],
        vec![
            "openmates",
            "teams",
            "invite",
            TEAM,
            "--email",
            "bob@example.org",
            "--role",
            "viewer",
        ],
        vec![
            "openmates",
            "teams",
            "accept-invite",
            "https://app.example.org/teams/invites/i-1#key=abc",
            "--email",
            "bob@example.org",
        ],
        vec!["openmates", "teams", "decline-invite", "i-1"],
        vec![
            "openmates",
            "teams",
            "access-requests",
            TEAM,
            "--status",
            "all",
        ],
        vec!["openmates", "teams", "approve-access", TEAM, "req-1"],
        vec!["openmates", "teams", "reject-access", TEAM, "req-1"],
        vec![
            "openmates",
            "teams",
            "role",
            TEAM,
            "--user",
            "u1",
            "--role",
            "admin",
        ],
        vec!["openmates", "teams", "remove-member", TEAM, "--user", "u1"],
        vec!["openmates", "teams", "members", "list", TEAM],
        vec!["openmates", "teams", "members", "show", TEAM, "u1"],
        vec![
            "openmates",
            "teams",
            "profile",
            "edit",
            TEAM,
            "--name",
            "Bob",
        ],
        vec![
            "openmates",
            "teams",
            "profile-image",
            "generated",
            TEAM,
            "--icon",
            "rocket",
        ],
        vec!["openmates", "teams", "billing", TEAM],
        vec![
            "openmates",
            "teams",
            "storage",
            "notice",
            TEAM,
            "--limit",
            "10",
        ],
        vec!["openmates", "teams", "usage", TEAM, "--user", "u1"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        assert!(
            super::super::super::handlers::requirements(&invocation).supported,
            "{args:?}"
        );
    }
    assert_eq!(
        invite_input("https://app.example.org/teams/invites/i-1#key=abc"),
        ("i-1".into(), Some("abc".into()))
    );
    assert_eq!(invite_input("plain-id"), ("plain-id".into(), None));
}

#[tokio::test]
async fn list_show_and_members_match_legacy_output() {
    let (mut client, server) = mock(vec![
        json!({"teams":[{"team_id":TEAM,"slug":"eng","role":"owner","status":"active"}]}),
        json!({"teams":[]}),
        json!({"members":[{"user_id":"u1","hashed_user_id":"h1","role":"admin","status":"active"}]}),
        json!({"storage":{"total_bytes":2147483648u64,"free_bytes":5368709120u64,"billable_gib":0,"weekly_cost_credits":0,"credits_per_started_excess_gib_per_week":5,"measurement_at":0,"billing_status":"paid"}}),
    ])
    .await;
    let listed = execute(&parsed(&["openmates", "teams", "list"]), &mut client)
        .await
        .ok()
        .unwrap();
    assert_eq!(
        listed.stdout,
        format!(
            "{TEAM}\n  \x1b[2mslug            \x1b[0m eng\n  \x1b[2mrole            \x1b[0m owner\n  \x1b[2mstatus          \x1b[0m active\n"
        )
    );
    let empty = execute(
        &parsed(&["openmates", "teams", "list", "--json"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&empty.stdout).unwrap(),
        json!({"teams":[],"active_team_id":null})
    );
    let members = execute(
        &parsed(&["openmates", "teams", "members", "list", TEAM]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(members.stdout, "u1  admin  active  h1\n");
    let storage = execute(
        &parsed(&["openmates", "teams", "storage", TEAM]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert!(storage.stdout.starts_with("Team storage: 2.00 GiB measured 1970-01-01T00:00:00.000Z\nFree allowance: 5 GiB · 0 started excess GiB\n"));
    assert!(
        storage
            .stdout
            .ends_with("No storage payment is currently due.\n")
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/teams "));
    assert!(requests[2].starts_with(&format!("GET /v1/teams/{TEAM}/members ")));
}

#[tokio::test]
async fn validation_and_destructive_guards_fail_before_network() {
    let (mut client, server) = mock(vec![]).await;
    for (args, message) in [
        (
            vec!["openmates", "teams", "create"],
            "Missing --name <name>.",
        ),
        (
            vec!["openmates", "teams", "update", TEAM],
            "Nothing to update. Provide --name, --description, or --slug.",
        ),
        (
            vec!["openmates", "teams", "delete", TEAM],
            "Deleting a team requires --yes.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "delete",
                TEAM,
                "--yes",
                "--totp-code",
                "123456",
            ],
            "Team deletion verification codes must be entered through interactive prompts, not command-line flags.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "role",
                TEAM,
                "--user",
                "u1",
                "--role",
                "owner",
            ],
            "Team role must be admin, member, or viewer.",
        ),
        (
            vec!["openmates", "teams", "invite", TEAM, "--role", "boss"],
            "Team role must be admin, member, or viewer.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "storage",
                "notice",
                TEAM,
                "--limit",
                "0",
            ],
            "--limit must be an integer from 1 to 100",
        ),
        (
            vec![
                "openmates",
                "teams",
                "storage",
                "notice",
                TEAM,
                "--after-unit-id",
                "short",
            ],
            "--after-unit-id must be a 64-character storage unit cursor",
        ),
        (
            vec!["openmates", "teams", "add-credits", "100"],
            "Direct team credit grants are disabled. Use 'openmates teams billing bank-transfer create <team-id> --credits <amount>'.",
        ),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert_eq!(actual, message, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    drop(client);
    assert!(server.await.unwrap().is_empty());
}

#[tokio::test]
async fn switch_resolves_slugs_and_create_can_activate_the_new_team() {
    let (mut client, server) = mock(vec![
        json!({"teams":[{"team_id":TEAM,"slug":"eng"},{"team_id":"bbbbbbbb-1111-4111-8111-aabbccddeeff","slug":"ops"}]}),
        json!({"teams":[]}),
        json!({"approval_token":"approved"}),
        json!({"team":{"team_id":"cccccccc-1111-4111-8111-aabbccddeeff","slug":"new"}}),
    ])
    .await;
    let switched = execute(
        &parsed(&["openmates", "teams", "switch", "eng", "--json"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&switched.stdout).unwrap();
    assert_eq!(
        (
            value["active_team_id"].as_str(),
            value["context"].as_str(),
            value["target"].as_str()
        ),
        (Some(TEAM), Some("team"), Some("eng"))
    );
    assert_eq!(
        client.session().unwrap().active_team_id.as_deref(),
        Some(TEAM)
    );
    match execute(
        &parsed(&["openmates", "teams", "switch", "missing"]),
        &mut client,
    )
    .await
    {
        Err(CliError::Invalid(message)) => assert_eq!(
            message,
            "Team 'missing' was not found. Run 'openmates switch-to' to see available targets."
        ),
        _ => panic!("unknown Team must fail"),
    }
    let created = execute(
        &parsed(&[
            "openmates",
            "teams",
            "create",
            "--name",
            "New",
            "--switch",
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&created.stdout).unwrap();
    assert_eq!(
        value["active_team_id"],
        "cccccccc-1111-4111-8111-aabbccddeeff"
    );
    assert_eq!(server.await.unwrap().len(), 4);
}
