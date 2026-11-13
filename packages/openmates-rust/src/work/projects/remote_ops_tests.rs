//! Requester side of run_command and Git operations: digest formulas, sealed
//! envelope shape, approval order, result decoding and error mapping.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::projects::remote_files::tests::{PROJECT, host};
use crate::work::tasks::tests::client;

const KEY: [u8; 32] = [7; 32];
const CHAT: &str = "chat-1";

fn hex_hmac(message: &str) -> String {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&KEY).unwrap();
    mac.update(message.as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn command() -> WriteProposal {
    WriteProposal::Command {
        operation_id: "op-1".into(),
        argv: vec!["npm".into(), "test".into()],
        cwd: ".".into(),
        timeout_ms: 5000,
        max_output_bytes: None,
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn command_digest_matches_the_host_tuple_and_binds_each_field() {
    // Same literal tuple as the host test `digest_is_the_keyed_hmac_of_the_exact_proposal`.
    let expected = hex_hmac(
        r#"["openmates-remote-command-proposal-v1","project-1","chat-1","run_command","op-1",["npm","test"],".",5000,null]"#,
    );
    assert_eq!(command().digest(&KEY, "project-1", CHAT).unwrap(), expected);
    let changed = WriteProposal::Command {
        operation_id: "op-1".into(),
        argv: vec!["npm".into(), "test".into(), "--watch".into()],
        cwd: ".".into(),
        timeout_ms: 5000,
        max_output_bytes: None,
    };
    assert_ne!(changed.digest(&KEY, "project-1", CHAT).unwrap(), expected);
    assert!(command().digest(&KEY, "", CHAT).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn git_digest_matches_the_host_tuple() {
    let commit = WriteProposal::Git {
        operation: "git_commit",
        operation_id: "op-1".into(),
        message: Some("Add feature".into()),
    };
    let land = WriteProposal::Git {
        operation: "git_land",
        operation_id: "op-1".into(),
        message: None,
    };
    assert_eq!(
        commit.digest(&KEY, "p1", CHAT).unwrap(),
        hex_hmac(
            r#"["openmates-remote-git-proposal-v1","p1","chat-1","git_commit","op-1","Add feature"]"#
        )
    );
    assert_eq!(
        land.digest(&KEY, "p1", CHAT).unwrap(),
        hex_hmac(r#"["openmates-remote-git-proposal-v1","p1","chat-1","git_land","op-1",null]"#)
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn arguments_use_the_host_bootstrap_shape() {
    assert_eq!(
        command().arguments(CHAT),
        json!({"chat_id":CHAT,"command":{"operation_id":"op-1","argv":["npm","test"],"cwd":".","timeout_ms":5000}})
    );
    let commit = WriteProposal::Git {
        operation: "git_commit",
        operation_id: "op-2".into(),
        message: Some("m".into()),
    };
    assert_eq!(
        commit.arguments(CHAT),
        json!({"chat_id":CHAT,"git":{"operation_id":"op-2","message":"m"}})
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn results_decode_and_land_conflict_is_a_value() {
    let result: RemoteCommandResult = serde_json::from_value(json!({
        "exit_code":null,"signal":9,"timed_out":true,"duration_ms":10,"stdout":"","stderr":"x",
        "stdout_truncated":false,"stderr_truncated":true,"sandbox":"bwrap","root":"worktree","cwd":"."
    }))
    .unwrap();
    assert_eq!(result.exit_code, None);
    assert!(result.timed_out && result.stderr_truncated);
    let conflict: GitLandOutcome = serde_json::from_value(json!({
        "landed":false,"code":"land_conflict","conflicting_paths":["a.rs"]
    }))
    .unwrap();
    assert_eq!(
        conflict,
        GitLandOutcome::Conflict {
            landed: false,
            code: "land_conflict".into(),
            conflicting_paths: vec!["a.rs".into()]
        }
    );
    let landed: GitLandOutcome = serde_json::from_value(json!({
        "landed":true,"commit":"abc","commits":2,"target_branch":"main","checked_out":false
    }))
    .unwrap();
    assert!(matches!(landed, GitLandOutcome::Landed { commits: 2, .. }));
    let none: GitStatusResult = serde_json::from_value(json!({"exists":false})).unwrap();
    assert!(!none.exists && none.changed_files.is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn host_codes_map_to_the_enum() {
    for (wire, code) in [
        (
            "confinement_unavailable",
            RemoteOpCode::ConfinementUnavailable,
        ),
        (
            "write_authorization_denied",
            RemoteOpCode::WriteAuthorizationDenied,
        ),
        ("nothing_to_commit", RemoteOpCode::NothingToCommit),
        ("worktree_dirty", RemoteOpCode::WorktreeDirty),
        ("no_worktree", RemoteOpCode::NoWorktree),
    ] {
        assert_eq!(RemoteOpCode::from_wire(wire), code);
    }
    assert_eq!(
        RemoteOpCode::from_wire("brand_new"),
        RemoteOpCode::Other("brand_new".into())
    );
    let mapped = RemoteOpError::from(ProjectRequesterError::Remote {
        code: "land_failed".into(),
        message: "m".into(),
    });
    assert!(matches!(
        mapped,
        RemoteOpError::Host {
            code: RemoteOpCode::LandFailed,
            ..
        }
    ));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[tokio::test]
async fn run_command_stores_the_approval_then_sends_the_sealed_request() {
    let reply = json!({"ok":true,"result":{
        "exit_code":0,"signal":null,"timed_out":false,"duration_ms":3,"stdout":"ok\n","stderr":"",
        "stdout_truncated":false,"stderr_truncated":false,"sandbox":"bwrap","root":"worktree","cwd":"."}});
    let (api, server) = host(reply).await;
    let mut c = client(&api);
    let result = c
        .projects()
        .run_remote_command(
            PROJECT,
            None,
            CHAT,
            "op-1",
            &RemoteCommand {
                argv: vec!["npm".into(), "test".into()],
                cwd: None,
                timeout_ms: 5000,
                max_output_bytes: None,
            },
        )
        .await
        .unwrap();
    assert_eq!(result.stdout, "ok\n");
    let requests = server.await.unwrap();
    let approval = requests
        .iter()
        .position(|r| r.starts_with(&format!("POST /v1/projects/{PROJECT}/write-approvals ")))
        .expect("approval stored");
    let send = requests
        .iter()
        .position(|r| {
            r.starts_with(&format!(
                "POST /v1/projects/{PROJECT}/sources/src/requests "
            ))
        })
        .expect("request sent");
    assert!(approval < send, "approval precedes the request");
    let body: Value =
        serde_json::from_str(requests[send].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let digest = command().digest(&[8; 32], PROJECT, CHAT).unwrap();
    assert_eq!(body["proposal_digest"], digest);
    assert_eq!(body["operation"], "run_command");
    assert_eq!(body["chat_id"], CHAT);
    assert_eq!(body["operation_id"], "op-1");
    let opened: Value = serde_json::from_str(
        &crypto::decrypt_combined(body["encrypted_envelope"].as_str().unwrap(), &[8; 32]).unwrap(),
    )
    .unwrap();
    assert_eq!(opened["arguments"], command().arguments(CHAT));
    assert!(!requests[send].contains("npm"), "argv stays sealed");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[tokio::test]
async fn git_status_carries_the_chat_for_the_relay_and_no_digest() {
    let (api, server) = host(json!({"ok":true,"result":{"exists":false}})).await;
    let mut c = client(&api);
    let status = c.projects().git_status(PROJECT, None, CHAT).await.unwrap();
    assert!(!status.exists);
    let requests = server.await.unwrap();
    let send = requests
        .iter()
        .find(|r| {
            r.starts_with(&format!(
                "POST /v1/projects/{PROJECT}/sources/src/requests "
            ))
        })
        .unwrap();
    let body: Value = serde_json::from_str(send.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["chat_id"], CHAT);
    assert!(body.get("proposal_digest").is_none());
    assert!(!requests.iter().any(|r| r.contains("write-approvals")));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[tokio::test]
async fn host_refusal_surfaces_as_a_typed_code() {
    let (api, _server) = host(json!({"ok":false,"error":"nothing_to_commit"})).await;
    let mut c = client(&api);
    let error = c
        .projects()
        .git_commit(PROJECT, None, CHAT, "op-3", "msg")
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        RemoteOpError::Host {
            code: RemoteOpCode::NothingToCommit,
            ..
        }
    ));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[cfg(feature = "workflow-yaml")]
#[test]
fn digests_equal_the_host_functions() {
    use crate::source_host::{commands, git_ops};
    let host_command = commands::CommandProposal {
        operation_id: "op-1".into(),
        argv: vec!["npm".into(), "test".into()],
        cwd: "sub".into(),
        timeout_ms: 5000,
        max_output_bytes: Some(2048),
    };
    let ours = WriteProposal::Command {
        operation_id: "op-1".into(),
        argv: vec!["npm".into(), "test".into()],
        cwd: "sub".into(),
        timeout_ms: 5000,
        max_output_bytes: Some(2048),
    };
    assert_eq!(
        ours.digest(&KEY, "p1", CHAT).unwrap(),
        commands::digest(&KEY, "p1", CHAT, &host_command).unwrap()
    );
    for (operation, message) in [("git_commit", Some("m".to_owned())), ("git_land", None)] {
        let host_git = git_ops::GitProposal {
            operation_id: "op-9".into(),
            message: message.clone(),
        };
        let ours = WriteProposal::Git {
            operation,
            operation_id: "op-9".into(),
            message,
        };
        assert_eq!(
            ours.digest(&KEY, "p1", CHAT).unwrap(),
            git_ops::digest(&KEY, "p1", CHAT, operation, &host_git).unwrap()
        );
    }
}
