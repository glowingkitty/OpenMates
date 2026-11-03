// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::super::super::settings_more::tests::{mock, parsed};
use super::*;
use serde_json::{Value, json};

const TEAM: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";
const FLOW: &str = "bbbbbbbb-2222-4222-8222-bbccddeeff00";

fn command_failed(result: Result<CliOutput, CliError>) -> String {
    match result {
        Err(CliError::Contract {
            code: "command_failed",
            message,
        }) => message,
        Err(other) => panic!("expected command_failed, got {other}"),
        Ok(output) => panic!("expected an error, got {}", output.stdout),
    }
}

#[tokio::test]
async fn move_validation_matches_npm_before_any_network() {
    let (mut client, server) = mock(vec![]).await;
    for (args, message) in [
        (
            vec!["openmates", "teams", "move", TEAM, "--id", FLOW, "--yes"],
            "Missing --type <chat|project|task|plan|workflow>.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "move",
                TEAM,
                "--type",
                "folder",
                "--id",
                FLOW,
                "--yes",
            ],
            "Workspace type must be chat, project, task, plan, or workflow.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "move",
                TEAM,
                "--type",
                "task",
                "--yes",
            ],
            "Missing --id <resource-id>.",
        ),
        (
            vec![
                "openmates",
                "teams",
                "move",
                TEAM,
                "--type",
                "task",
                "--id",
                FLOW,
            ],
            "Moving a workspace resource requires --yes.",
        ),
    ] {
        let result = execute(&parsed(&args), &mut client).await;
        let error = command_failed(result);
        assert_eq!(error, message, "{args:?}");
    }
    let unsupported = execute(
        &parsed(&[
            "openmates",
            "teams",
            "move",
            TEAM,
            "--type",
            "chat",
            "--id",
            FLOW,
            "--yes",
        ]),
        &mut client,
    )
    .await;
    match unsupported {
        Err(error @ CliError::Unsupported { .. }) => assert_eq!(error.exit_code(), 1),
        _ => panic!("chat moves must fail explicitly"),
    }
    drop(client);
    assert!(server.await.unwrap().is_empty());
}

#[test]
fn positional_type_and_id_follow_the_npm_rest_indices() {
    // The catalog grammar currently declares only <team-id>, so the npm
    // positional forms are exercised on a direct Invocation.
    let direct = |positionals: &[&str], flags: Value| Invocation {
        path: vec!["teams".into(), "move".into()],
        positionals: positionals.iter().map(|p| (*p).to_owned()).collect(),
        flags: serde_json::from_value(flags).unwrap(),
    };
    match move_input(&direct(&[], json!({"yes":true}))) {
        Err(CliError::Contract { message, .. }) => assert_eq!(message, "Missing --team <team-id>."),
        _ => panic!("missing team must fail"),
    }
    // `--team` wins over the first positional; type/id keep their npm indices.
    let flagged = move_input(&direct(
        &["ignored", "task", "T-1"],
        json!({"team":TEAM,"confirm":true}),
    ))
    .ok()
    .unwrap();
    assert_eq!(
        (flagged.0.as_str(), flagged.1, flagged.2.as_str()),
        (TEAM, WorkspaceMoveType::Task, "T-1")
    );
    let (team, kind, id) = move_input(&direct(&[TEAM, "plan", "PLAN-12"], json!({"yes":true})))
        .ok()
        .unwrap();
    assert_eq!(
        (team.as_str(), kind, id.as_str()),
        (TEAM, WorkspaceMoveType::Plan, "PLAN-12")
    );
    assert!(super::super::supported(&parsed(&[
        "openmates",
        "teams",
        "move",
        TEAM,
        "--type",
        "task",
        "--id",
        FLOW,
        "--yes",
    ])));
}

#[tokio::test]
async fn workflow_move_rekeys_the_slug_index_with_the_team_key() {
    let team_key = [9u8; 32];
    // The mock session master key is [7; 32].
    let wrapped = openmates_sdk::crypto::encrypt_bytes(&team_key, &[7; 32]).unwrap();
    let (mut client, server) = mock(vec![
        json!({"team":{"team_id":TEAM,"encrypted_team_key":wrapped}}),
        json!({"workflow":{"id":FLOW,"title":"Weekly Review","slug":"weekly-review"}}),
        json!({"workflow_id":FLOW,"team_id":TEAM}),
    ])
    .await;
    let output = execute(
        &parsed(&[
            "openmates",
            "teams",
            "move",
            TEAM,
            "--type",
            "workflow",
            "--id",
            FLOW,
            "--yes",
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output.stdout).unwrap(),
        json!({"success":true,"workflow_id":FLOW,"team_id":TEAM})
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/teams/{TEAM} ")));
    assert!(requests[1].starts_with(&format!("GET /v1/workflows/{FLOW} ")));
    assert!(requests[2].starts_with(&format!("POST /v1/workflows/{FLOW}/move ")));
    let body: Value = serde_json::from_str(requests[2].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["team_id"], TEAM);
    assert_eq!(body["confirmed"], true);
    assert!(body["moved_at"].as_u64().is_some());
    assert_eq!(
        body["slug_lookup_hash"],
        openmates_sdk::crypto::object_slug_lookup_hash("weekly-review", &team_key).unwrap()
    );
    assert_eq!(
        openmates_sdk::crypto::decrypt_combined(
            body["encrypted_slug"].as_str().unwrap(),
            &team_key
        )
        .unwrap(),
        "weekly-review"
    );
    assert!(body.get("team_project_key_wrapper").is_none());
}

#[tokio::test]
async fn missing_team_key_uses_the_npm_message() {
    let (mut client, server) = mock(vec![json!({"team":{"team_id":TEAM}})]).await;
    let result = execute(
        &parsed(&[
            "openmates",
            "teams",
            "move",
            TEAM,
            "--type",
            "workflow",
            "--id",
            FLOW,
            "--yes",
        ]),
        &mut client,
    )
    .await;
    assert_eq!(
        command_failed(result),
        format!(
            "Team key not available locally for team '{TEAM}'. Run 'openmates teams show {TEAM}' and try again."
        )
    );
    assert_eq!(server.await.unwrap().len(), 1);
}

#[tokio::test]
async fn human_output_names_the_type_team_and_selector() {
    let wrapped = openmates_sdk::crypto::encrypt_bytes(&[9u8; 32], &[7; 32]).unwrap();
    let (mut client, _server) = mock(vec![
        json!({"team":{"team_id":TEAM,"encrypted_team_key":wrapped}}),
        json!({"workflow":{"id":FLOW}}),
        json!({}),
    ])
    .await;
    let output = execute(
        &parsed(&[
            "openmates",
            "teams",
            "move",
            TEAM,
            "--type",
            "workflow",
            "--id",
            FLOW,
            "--yes",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        output.stdout,
        format!("workflow moved to team {TEAM}: {FLOW}\n")
    );
}
