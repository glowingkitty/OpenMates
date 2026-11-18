//! Timeline decoding, ordering, path resolution and query parameters against a mock server.
use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const FILE_A: &str = "aaaaaaaa-1111-5111-8111-aabbccddeeff";
const FILE_B: &str = "bbbbbbbb-1111-5111-8111-aabbccddeeff";
const COMMIT: &str = "cccccccc-1111-4111-8111-aabbccddeeff";
const KEY: [u8; 32] = [8; 32];

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
fn links(files: &[(&str, &str)]) -> Value {
    let rows: Vec<Value> = files
        .iter()
        .map(|(target, path)| {
            json!({"item_type":"embed","target_id_hash":hash(target),"target_id_encrypted":enc(target),
            "encrypted_metadata":enc(&json!({"path":path,"source":"hosted_project_file"}).to_string())})
        })
        .collect();
    json!({"project":project(),"items":rows})
}
fn commit_raw(target: &str, path: &str) -> Value {
    let paths = json!({ hash(target): path }).to_string();
    json!({"commit_id":COMMIT,"author_kind":"assistant","encrypted_message":enc("Add file"),
        "encrypted_paths":enc(&paths),"entries":[{"target_id_hash":hash(target),"embed_version":1}],
        "hashed_chat_id":null,"restored_from_commit_id":null,"created_at":50})
}
fn version_row(id: &str, target: &str, created: u64) -> Value {
    json!({"kind":"file_version","id":id,"created_at":created,"author_kind":"user",
        "target_id_hash":hash(target),"version":2,"action":"edit","restored_from_version":null,"commit":null})
}

#[tokio::test]
async fn keeps_server_order_cursor_and_resolves_live_path() {
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"entries":[version_row("v2",FILE_A,90),version_row("v1",FILE_A,80)],"next_cursor":"abc"}),
        links(&[(FILE_A, "index.html")]),
    ])
    .await;
    let mut client = client(&api);
    let page = client
        .projects()
        .timeline(PROJECT, Some(2), Some("zzz".into()))
        .await
        .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[1].contains("limit=2") && requests[1].contains("before=zzz"));
    assert_eq!(page.next_cursor.as_deref(), Some("abc"));
    let ids: Vec<_> = page.entries.iter().map(|e| e.id.as_str()).collect();
    assert_eq!(ids, ["v2", "v1"]);
    assert_eq!(page.entries[0].path.as_deref(), Some("index.html"));
    assert_eq!(page.entries[0].path_source, ProjectTimelinePathSource::Live);
    assert_eq!(page.entries[0].action.as_deref(), Some("edit"));
}

#[tokio::test]
async fn falls_back_to_page_commit_path_for_unlinked_file() {
    let commit_row = json!({"kind":"commit","id":COMMIT,"created_at":50,"author_kind":"assistant",
        "target_id_hash":null,"version":null,"action":null,"restored_from_version":null,
        "commit":commit_raw(FILE_B,"gone.js")});
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"entries":[version_row("v1",FILE_B,60),commit_row],"next_cursor":null}),
        links(&[]),
    ])
    .await;
    let mut client = client(&api);
    let page = client
        .projects()
        .timeline(PROJECT, None, None)
        .await
        .unwrap();
    assert_eq!(
        server.await.unwrap().len(),
        3,
        "no extra commits fetch needed"
    );
    assert_eq!(page.entries[0].path.as_deref(), Some("gone.js"));
    assert_eq!(
        page.entries[0].path_source,
        ProjectTimelinePathSource::Commit
    );
    assert_eq!(page.entries[1].commit.as_ref().unwrap().message, "Add file");
}

#[tokio::test]
async fn fetches_commits_then_reports_unknown_path() {
    let (api, server) = mock(vec![
        json!({"project":project()}),
        json!({"entries":[version_row("v1",FILE_A,60),version_row("v2",FILE_B,50)],"next_cursor":null}),
        links(&[]),
        json!({"commits":[commit_raw(FILE_A,"old.md")],"next_cursor":null}),
    ])
    .await;
    let mut client = client(&api);
    let page = client
        .projects()
        .timeline(PROJECT, None, None)
        .await
        .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[3].contains("/commits"));
    assert_eq!(page.entries[0].path.as_deref(), Some("old.md"));
    assert_eq!(page.entries[1].path, None);
    assert_eq!(
        page.entries[1].path_source,
        ProjectTimelinePathSource::Unknown
    );
}

#[tokio::test]
async fn team_scope_adds_team_query_parameter() {
    let team = "dddddddd-1111-4111-8111-aabbccddeeff";
    let mut raw = encode_create(
        &ProjectCreate {
            name: "Project".into(),
            project_id: Some(PROJECT.into()),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &KEY,
        &[9; 32],
        Some(team),
    )
    .unwrap();
    raw["hashed_team_id"] = json!(hash(team));
    let wrapped = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    let (api, server) = mock(vec![
        json!({"project":raw}),
        json!({"team":{"team_id":team,"encrypted_team_key":wrapped}}),
        json!({"entries":[],"next_cursor":null}),
    ])
    .await;
    let mut client = client(&api);
    client
        .projects()
        .with_filters(ProjectFilters {
            team_id: Some(team.into()),
            ..Default::default()
        })
        .timeline(PROJECT, None, None)
        .await
        .unwrap();
    let requests = server.await.unwrap();
    assert!(requests[2].contains(&format!("/timeline?team_id={team}")));
}
