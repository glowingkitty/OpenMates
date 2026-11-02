// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::settings_more::tests::{mock, parsed};
use super::*;

const TEAM: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

#[tokio::test]
async fn team_flag_selects_the_team_like_npm() {
    let invocation = parsed(&["openmates", "teams", "show", "--team", TEAM, "--json"]);
    assert_eq!(
        team_id(&team_flag_selector(&invocation).unwrap()).ok(),
        Some(TEAM)
    );
    let (mut client, server) = mock(vec![
        json!({"key":{"version":1}}),
        json!({"team":{"team_id":TEAM,"slug":"eng"}}),
    ])
    .await;
    let output = execute(&invocation, &mut client).await.ok().unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output.stdout).unwrap()["team"]["slug"],
        "eng"
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/account/chat-encryption-key "));
    assert!(requests[1].starts_with(&format!("GET /v1/teams/{TEAM} ")));
}

#[tokio::test]
async fn list_publishes_the_direct_chat_identity_only_for_team_members() {
    let (mut client, server) = mock(vec![
        json!({"teams":[{"team_id":TEAM,"slug":"eng"}]}),
        json!({"key":{"version":1}}),
        json!({"teams":[]}),
    ])
    .await;
    execute(&parsed(&["openmates", "teams", "list"]), &mut client)
        .await
        .ok()
        .unwrap();
    let empty = execute(
        &parsed(&["openmates", "teams", "list", "--json"]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&empty.stdout).unwrap()["teams"],
        json!([])
    );
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[1].starts_with("GET /v1/account/chat-encryption-key "));
    let flagged =
        team_flag_selector(&parsed(&["openmates", "teams", "billing", "--team", TEAM])).unwrap();
    assert_eq!(
        (flagged.positionals.as_slice(), flagged.has("team")),
        ([TEAM.to_owned()].as_slice(), false)
    );
    assert!(team_flag_selector(&parsed(&["openmates", "teams", "list"])).is_none());
}

#[tokio::test]
async fn list_show_members_and_storage_match_legacy_output_with_identity_publication() {
    let (mut client, server) = mock(vec![
        json!({"teams":[{"team_id":TEAM,"slug":"eng","role":"owner","status":"active"}]}),
        json!({"key":{"version":1}}),
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
    assert!(requests[1].starts_with("GET /v1/account/chat-encryption-key "));
    assert!(requests[3].starts_with(&format!("GET /v1/teams/{TEAM}/members ")));
}
