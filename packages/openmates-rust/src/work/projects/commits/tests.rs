use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const FILE_A: &str = "aaaaaaaa-1111-5111-8111-aabbccddeeff";
const FILE_B: &str = "bbbbbbbb-1111-5111-8111-aabbccddeeff";
const COMMIT: &str = "cccccccc-1111-4111-8111-aabbccddeeff";
const KEY: [u8; 32] = [8; 32];

fn file(target: &str, path: &str, version: u64) -> ProjectCommitFile {
    ProjectCommitFile {
        target_id: target.into(),
        path: path.into(),
        embed_version: version,
    }
}
fn input(files: Vec<ProjectCommitFile>) -> ProjectCommitCreate {
    ProjectCommitCreate {
        message: "Add recipe search".into(),
        author: ProjectCommitAuthor::Assistant,
        chat_id: Some("chat-1".into()),
        files,
        commit_id: Some(COMMIT.into()),
        created_at: Some(50),
    }
}
fn project() -> Value {
    encode_create(
        &ProjectCreate {
            name: "Project".into(),
            project_id: Some(PROJECT.into()),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &KEY,
        &[7; 32],
        None,
    )
    .unwrap()
}
fn enc(text: &str) -> String {
    crypto::server_fields::encrypt_text(text, &KEY, &[]).unwrap()
}
fn item(target: &str, metadata: Value) -> Value {
    json!({"item_type":"embed","target_id_hash":hash(target),"target_id_encrypted":enc(target),
        "encrypted_metadata":enc(&metadata.to_string())})
}
fn stored(files: Vec<ProjectCommitFile>) -> Value {
    let mut raw = commit_wire(&input(files), &KEY, COMMIT, 1).unwrap();
    raw["hashed_chat_id"] = json!(hash("chat-1"));
    raw["restored_from_commit_id"] = Value::Null;
    raw
}
fn body_of(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}

#[test]
fn wire_encrypts_message_and_paths_and_keeps_only_pointers_in_clear() {
    let wire = commit_wire(
        &input(vec![file(FILE_A, "src/secret.rs", 3)]),
        &KEY,
        COMMIT,
        1,
    )
    .unwrap();
    let text = wire.to_string();
    for private in ["Add recipe search", "src/secret.rs", FILE_A] {
        assert!(!text.contains(private), "{private} leaked");
    }
    assert_eq!(
        wire["entries"],
        json!([{"target_id_hash":hash(FILE_A),"embed_version":3}])
    );
    assert_eq!(wire["author_kind"], "assistant");
    assert_eq!(wire["created_at"], 50);
    let decoded = commit_decode(&stored(vec![file(FILE_A, "src/secret.rs", 3)]), &KEY).unwrap();
    assert_eq!(decoded.message, "Add recipe search");
    assert_eq!(decoded.files[0].path.as_deref(), Some("src/secret.rs"));
    assert!(commit_decode(&stored(vec![file(FILE_A, "a", 1)]), &[9; 32]).is_err());
}

#[test]
fn input_validation_rejects_empty_duplicate_and_zero_version() {
    for bad in [
        ProjectCommitCreate {
            message: " ".into(),
            ..input(vec![file(FILE_A, "a", 1)])
        },
        input(vec![file(FILE_A, "a", 0)]),
        input(vec![file(FILE_A, "a", 1), file(FILE_A, "b", 2)]),
        ProjectCommitCreate {
            commit_id: Some("nope".into()),
            ..input(vec![])
        },
    ] {
        assert!(validate_input(&bad).is_err());
    }
    assert!(commit_wire(&input(vec![]), &KEY, COMMIT, 1).is_err());
}

#[test]
fn hosted_files_ignore_other_items_and_reject_forged_target_hash() {
    let items = json!([
        item(FILE_A, json!({"path":"index.html","source":"hosted_project_file"})),
        item(FILE_B, json!({"path":"notes.md","source":"upload"})),
        {"item_type":"chat","target_id_encrypted":enc("chat")},
    ]);
    assert_eq!(
        hosted_files(&items, &KEY).unwrap(),
        vec![(FILE_A.to_owned(), "index.html".to_owned())]
    );
    let mut forged = items.clone();
    forged[0]["target_id_hash"] = json!(hash("other"));
    assert!(matches!(hosted_files(&forged, &KEY), Err(Error::Forbidden)));
}

#[tokio::test]
async fn create_snapshots_hosted_heads_and_rejects_unacknowledged_ciphertext() {
    let items = json!([
        item(
            FILE_A,
            json!({"path":"index.html","source":"hosted_project_file"})
        ),
        item(
            FILE_B,
            json!({"path":"app.js","source":"hosted_project_file"})
        ),
    ]);
    let forged = stored(vec![
        file(FILE_A, "index.html", 4),
        file(FILE_B, "app.js", 2),
    ]);
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"project":project(),"items":items}),
        json!({"current_version":4}),
        json!({"current_version":2}),
        json!({"commit":forged}),
    ])
    .await;
    let mut client = client(&api);
    let result = client
        .projects()
        .create_commit(PROJECT, input(vec![]))
        .await;
    // Independently encrypted ciphertext is not the exact acknowledged write.
    assert!(matches!(result, Err(Error::Forbidden)));
    let requests = server.await.unwrap();
    assert!(
        requests[2].contains(&format!("/v1/embeds/{FILE_A}/versions"))
            && requests[2].contains("project_id=")
    );
    assert!(requests[4].starts_with(&format!("POST /v1/projects/{PROJECT}/commits ")));
    let body = body_of(&requests[4]);
    assert_eq!(
        body["entries"],
        json!([
        {"target_id_hash":hash(FILE_A),"embed_version":4},{"target_id_hash":hash(FILE_B),"embed_version":2}])
    );
    assert_eq!(
        crypto::decrypt_combined(body["encrypted_message"].as_str().unwrap(), &KEY).unwrap(),
        "Add recipe search"
    );
    assert!(!body.to_string().contains("index.html"));
}

#[tokio::test]
async fn list_decodes_page_and_show_binds_commit_id() {
    let raw = stored(vec![file(FILE_A, "index.html", 4)]);
    let mut other = raw.clone();
    other["commit_id"] = json!(FILE_A);
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"commits":[raw.clone()],"next_cursor":20}),
        json!({"project":project()}),
        json!({"commit":other}),
    ])
    .await;
    let mut client = client(&api);
    let page = client
        .projects()
        .list_commits(PROJECT, 20, 0)
        .await
        .unwrap();
    assert_eq!((page.commits.len(), page.next_cursor), (1, Some(20)));
    assert_eq!(page.commits[0].message, "Add recipe search");
    assert!(matches!(
        client.projects().show_commit(PROJECT, COMMIT).await,
        Err(Error::Forbidden)
    ));
    let requests = server.await.unwrap();
    assert!(requests[1].contains("limit=20") && requests[1].contains("cursor=0"));
    assert!(client.projects().list_commits(PROJECT, 0, 0).await.is_err());
}

#[tokio::test]
async fn restore_plan_marks_changed_unchanged_and_unlinked_files() {
    let raw = stored(vec![
        file(FILE_A, "index.html", 4),
        file(FILE_B, "gone.js", 2),
    ]);
    let items = json!([item(
        FILE_A,
        json!({"path":"index.html","source":"hosted_project_file"})
    )]);
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"commit":raw}),
        json!({"project":project()}),
        json!({"project":project(),"items":items}),
        json!({"current_version":6}),
    ])
    .await;
    let mut client = client(&api);
    let plan = client
        .projects()
        .restore_commit_plan(PROJECT, COMMIT)
        .await
        .unwrap();
    server.await.unwrap();
    assert_eq!(plan.files.len(), 2);
    assert_eq!(
        (plan.files[0].current_version, plan.files[0].unchanged),
        (Some(6), false)
    );
    assert_eq!(plan.files[0].target_id.as_deref(), Some(FILE_A));
    assert_eq!(
        (
            plan.files[1].target_id.clone(),
            plan.files[1].current_version
        ),
        (None, None)
    );
}

#[tokio::test]
async fn api_key_clients_cannot_use_commits() {
    let mut sdk = OpenMates::new(crate::SdkOptions {
        api_url: "http://127.0.0.1:1".into(),
        credentials: crate::SdkCredentials::ApiKey(
            crate::ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), "c".repeat(32))).unwrap(),
        ),
        device_id: "fixture".into(),
        client_options: Default::default(),
    })
    .unwrap();
    assert!(matches!(
        sdk.projects().list_commits(PROJECT, 10, 0).await,
        Err(Error::Unavailable {
            code: "project_commits_unavailable",
            ..
        })
    ));
}
