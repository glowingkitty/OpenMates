//! `apply_changes` against the in-memory server: order, diffs, refusals, retry.
use super::job::{self, HostedContext};
use super::tests::{CHAT, FakeServer, chat_key, create, project_key, run};
use super::*;

async fn apply(server: &mut FakeServer, op: &str, changes: Value) -> HostedResult<Value> {
    apply_with(server, op, changes, &[]).await
}

async fn apply_with(
    server: &mut FakeServer,
    op: &str,
    changes: Value,
    private: &[String],
) -> HostedResult<Value> {
    let (key, chat) = (project_key(), chat_key());
    let ctx = HostedContext {
        project_id: super::tests::PROJECT,
        project_key: &key,
        chat_key: Some(&chat),
        team_id: None,
        private_paths: private,
        ignored_read_approved: false,
    };
    let job = HostedFileJob {
        operation_id: op.into(),
        chat_id: CHAT.into(),
        operation: HostedFileOperation::ApplyChanges,
        arguments: json!({"origin": "command", "execution_id": "exec-1", "changes": changes}),
    };
    job::execute(server, &ctx, &job, None).await
}

#[tokio::test]
async fn applies_create_update_delete_in_order_with_diff() {
    let mut server = FakeServer::default();
    for (p, c, o) in [("lock.json", "v1\n", "s1"), ("gone.txt", "x\n", "s2")] {
        run(&mut server, Some(&create(p, c, o)), None)
            .await
            .unwrap();
    }
    let result = apply(
        &mut server,
        "job-1",
        json!([
            {"path": "lock.json", "kind": "update", "expected_base": content_hash("v1\n"), "content": "v2\n"},
            {"path": "gen/new.ts", "kind": "create", "expected_base": null, "content": "export {}\n"},
            {"path": "gone.txt", "kind": "delete", "expected_base": content_hash("x\n")},
        ]),
    )
    .await
    .unwrap();
    assert_eq!(
        (result["applied"].clone(), result["refused"].clone()),
        (json!(3), json!(0))
    );
    assert_eq!(result["origin"], "command");
    assert!(result["proposal_commitment"].as_str().unwrap().len() >= 32);
    assert_eq!(result["execution_id"], "exec-1");
    let rows = result["results"].as_array().unwrap();
    assert_eq!(rows[0]["kind"], "update");
    assert_eq!(rows[0]["revision"], 2);
    assert_eq!(
        rows[0]["applied_diff"],
        replacement_patch("lock.json", "v1\n", "v2\n")
    );
    assert_eq!(rows[1]["created"], true);
    assert_eq!(rows[2]["status"], "applied");
    let read = run(&mut server, None, Some("lock.json")).await.unwrap();
    assert_eq!(read["content"], "v2\n");
    assert!(server.files.iter().all(|f| f.path != "gone.txt"));
}

#[tokio::test]
async fn stale_base_is_refused_and_later_entries_still_apply() {
    let mut server = FakeServer::default();
    run(&mut server, Some(&create("a.txt", "one\n", "s1")), None)
        .await
        .unwrap();
    let commits = server.commits.len();
    let result = apply(
        &mut server,
        "job-2",
        json!([
            {"path": "a.txt", "kind": "update", "expected_base": content_hash("other\n"), "content": "two\n"},
            {"path": "b.txt", "kind": "create", "expected_base": null, "content": "b\n"},
        ]),
    )
    .await
    .unwrap();
    assert_eq!(result["results"][0]["status"], "refused");
    assert_eq!(result["results"][0]["reason"], "stale_base");
    assert_eq!(result["results"][1]["status"], "applied");
    assert_eq!(server.commits.len(), commits + 1);
    let read = run(&mut server, None, Some("a.txt")).await.unwrap();
    assert_eq!(read["content"], "one\n");
}

#[tokio::test]
async fn private_ignored_and_control_paths_are_refused() {
    let mut server = FakeServer::default();
    let private = vec!["secret/**".to_owned()];
    // Seed a root `.gitignore` link (the write path itself refuses control files).
    run(
        &mut server,
        Some(&create("seed.txt", "build/\n", "s0")),
        None,
    )
    .await
    .unwrap();
    server.files[0].path = ".gitignore".into();
    let result = apply_with(
        &mut server,
        "job-3",
        json!([
            {"path": "secret/key.txt", "kind": "create", "expected_base": null, "content": "k\n"},
            {"path": ".gitignore", "kind": "create", "expected_base": null, "content": "*\n"},
            {"path": "build/x.js", "kind": "create", "expected_base": null, "content": "x\n"},
            {"path": "ok.txt", "kind": "create", "expected_base": null, "content": "ok\n"},
        ]),
        &private,
    )
    .await
    .unwrap();
    let reasons: Vec<_> = result["results"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| r["reason"].as_str().unwrap_or("-").to_owned())
        .collect();
    assert_eq!(reasons[0], "protected_path");
    assert_eq!(reasons[1], "protected_path");
    assert_eq!(reasons[2], "ignored_path_requires_approval");
    assert_eq!(reasons[3], "-");
    assert_eq!(server.commits.len(), 2);
}

#[tokio::test]
async fn more_than_twenty_entries_are_refused_whole() {
    let mut server = FakeServer::default();
    let many: Vec<Value> = (0..21)
        .map(|i| json!({"path": format!("f{i}.txt"), "kind": "create", "expected_base": null, "content": "x\n"}))
        .collect();
    let error = apply(&mut server, "job-4", json!(many)).await.unwrap_err();
    assert_eq!(error.code(), "too_many_changes");
    assert!(server.commits.is_empty());
}

#[tokio::test]
async fn retried_job_writes_nothing_twice() {
    let mut server = FakeServer::default();
    run(&mut server, Some(&create("a.txt", "one\n", "s1")), None)
        .await
        .unwrap();
    let changes = json!([
        {"path": "a.txt", "kind": "update", "expected_base": content_hash("one\n"), "content": "two\n"},
        {"path": "b.txt", "kind": "create", "expected_base": null, "content": "b\n"},
    ]);
    apply(&mut server, "job-5", changes.clone()).await.unwrap();
    let commits = server.commits.len();
    let retry = apply(&mut server, "job-5", changes).await.unwrap();
    assert_eq!(retry["applied"], 2);
    assert_eq!(retry["results"][0]["idempotent"], true);
    assert_eq!(server.commits.len(), commits);
}

#[test]
fn entry_operation_ids_are_deterministic_and_bounded() {
    assert_eq!(super::apply_changes::entry_operation_id("j", 3), "j:3");
    let long = "x".repeat(128);
    let id = super::apply_changes::entry_operation_id(&long, 12);
    assert!(id.len() <= 128);
    assert_eq!(id, super::apply_changes::entry_operation_id(&long, 12));
}
