//! Durable action intents: ciphertext-only journaling, exact dispatch and read-before-retry reconciliation.
use super::super::tests::{client, mock};
use super::*;
const TASK: &str = "aabbccdd-1111-4111-8111-aabbccddeeff";
const OTHER: &str = "bbbbbbbb-1111-4111-8111-aabbccddeeff";
const ID: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn raw() -> Value {
    encrypt_create(
        &TaskCreate {
            title: "Private task".into(),
            description: "Private details".into(),
            task_id: Some(TASK.into()),
            ..Default::default()
        },
        &[7; 32],
        &[7; 32],
        None,
    )
    .unwrap()
}
fn row(version: u64, status: &str, extra: Value) -> Value {
    let mut row = raw();
    row["version"] = json!(version);
    row["status"] = json!(status);
    for (key, value) in extra.as_object().unwrap() {
        row[key] = value.clone();
    }
    row
}
fn body(request: &str) -> Value {
    serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=tasks.surface.semantic-parity
#[tokio::test]
async fn block_intent_journals_only_ciphertext_and_dispatches_exact_body() {
    let blocked = row(2, "blocked", json!({"blocked_reason_code":"other"}));
    let (api, server) = mock(vec![json!({"task":raw()}), json!({"task":blocked})]).await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_block(TASK, "Other", Some("Private reason"), ID)
        .await
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::Block);
    let wire = serde_json::to_string(&delivery).unwrap();
    assert!(!wire.contains("Private reason") && !wire.contains("Private task"));
    assert_eq!(delivery.input["version"], 1);
    assert_eq!(delivery.input["blocked_reason_code"], "other");
    let task = tasks.execute_delivery(&delivery, false).await.unwrap();
    assert_eq!(task["status"], "blocked");
    assert_eq!(task["title"], "Private task");
    let requests = server.await.unwrap();
    assert!(requests[1].starts_with(&format!("POST /v1/user-tasks/{TASK}/block ")));
    assert_eq!(body(&requests[1]), delivery.input);
}

#[tokio::test]
async fn uncertain_action_already_applied_is_acknowledged_without_resending() {
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"task":row(2,"todo",json!({"queue_state":"none","blocked_reason_code":null}))}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_transition(TASK, TaskMutationKind::Unblock, ID)
        .await
        .unwrap();
    let task = tasks.execute_delivery(&delivery, true).await.unwrap();
    assert_eq!(task["status"], "todo");
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 2, "no second unblock may be sent");
    assert!(requests[1].starts_with(&format!("GET /v1/user-tasks/{TASK} ")));
}

#[tokio::test]
async fn uncertain_action_with_untouched_version_resends_identical_intent() {
    let skipped = row(2, "backlog", json!({"queue_state":"skipped"}));
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"task":raw()}),
        json!({"task":skipped}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_transition(TASK, TaskMutationKind::Skip, ID)
        .await
        .unwrap();
    let task = tasks.execute_delivery(&delivery, true).await.unwrap();
    assert_eq!(task["status"], "backlog");
    let requests = server.await.unwrap();
    assert!(requests[2].starts_with(&format!("POST /v1/user-tasks/{TASK}/skip ")));
    assert_eq!(body(&requests[2]), delivery.input);
}

#[tokio::test]
async fn uncertain_action_after_newer_edit_is_retained_as_conflict() {
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"task":row(3,"todo",json!({}))}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_restore(TASK, "history-entry", RestoreState::Before, ID)
        .await
        .unwrap();
    assert!(matches!(
        tasks.execute_delivery(&delivery, true).await,
        Err(Error::Conflict)
    ));
    assert_eq!(server.await.unwrap().len(), 2);
}

#[tokio::test]
async fn uncertain_reorder_with_matching_position_returns_task_list() {
    // prepare: resolve for the move + resolve for the pinned version; then
    // the uncertain read-back shows the position already applied.
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"task":raw()}),
        json!({"task":row(2,"todo",json!({"position":200}))}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_reorder(
            TASK,
            TaskMove {
                position: Some(200),
                ..Default::default()
            },
            ID,
        )
        .await
        .unwrap();
    assert_eq!(
        delivery.input,
        json!({"moves":[{"task_id":TASK,"version":1,"position":200}],"team_id":null})
    );
    let value = tasks.execute_delivery(&delivery, true).await.unwrap();
    assert_eq!(value[0]["position"], 200);
    assert_eq!(server.await.unwrap().len(), 3, "no reorder may be resent");
}

#[tokio::test]
async fn uncertain_dependency_add_reconciles_existing_edge() {
    let edge = json!({"target_ref":format!("task:{OTHER}"),"edge_id":"e1"});
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"dependencies":[edge],"blockers":[]}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_dependency(
            TASK,
            &DependencyTarget {
                kind: WorkKind::Task,
                id: OTHER.into(),
            },
            true,
            ID,
        )
        .await
        .unwrap();
    let value = tasks.execute_delivery(&delivery, true).await.unwrap();
    assert_eq!(value["dependency"]["edge_id"], "e1");
    let requests = server.await.unwrap();
    assert!(requests[1].starts_with(&format!("GET /v1/user-tasks/{TASK}/dependencies ")));
}

#[tokio::test]
async fn uncertain_activity_delete_acknowledges_existing_tombstone() {
    let tombstone = json!({"entry_id":"entry-1","kind":"tombstone","deleted_at":5,"task_id":TASK});
    let (api, server) = mock(vec![
        json!({"task":raw()}),
        json!({"task":raw()}),
        json!({"entries":[tombstone],"next_cursor":null}),
    ])
    .await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .prepare_activity_delete(TASK, "entry-1", ID)
        .await
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::ActivityDelete);
    let value = tasks.execute_delivery(&delivery, true).await;
    assert!(value.is_ok(), "existing tombstone proves the delete");
    assert_eq!(server.await.unwrap().len(), 3);
}

#[test]
fn start_intent_never_contains_private_plaintext() {
    let mut client = client("https://api.example.org");
    let tasks = client.tasks();
    let task = decrypt(raw(), &[7; 32], &[7; 32], None).unwrap();
    let intent = tasks.start_intent(&task);
    assert!(!intent.to_string().contains("Private"));
    assert!(
        intent
            .as_object()
            .unwrap()
            .keys()
            .all(|k| !k.starts_with("plaintext_"))
    );
    let mut body = intent.clone();
    add_start_plaintext(&mut body, &task);
    assert_eq!(body["plaintext_title"], "Private task");
}

#[test]
fn blocked_reason_normalizes_like_npm_and_rejects_unknown_codes() {
    assert_eq!(
        blocked_reason(" Needs user-input ").unwrap(),
        "needs_user_input"
    );
    assert!(blocked_reason("because").is_err());
}
