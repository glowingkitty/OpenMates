//! Draining npm-written Task outbox fixtures into the native journal: locks, scope matching, migration marking.
use super::*;
use crate::{client::Client, runtime_store::RuntimeStore};
use crate::storage::Session;
use zeroize::Zeroizing;

const FIXTURE: &str = include_str!(
    "../../../../../packages/openmates-rust/src/work/tasks/legacy_outbox_fixture.json"
);
const API: &str = "https://api.example.org";

fn private_dir() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().unwrap()
}
fn npm_outbox() -> tempfile::TempDir {
    let root = private_dir();
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    for (path, text) in fixture["files"].as_object().unwrap() {
        let target = root.path().join(path);
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::write(target, text.as_str().unwrap()).unwrap();
    }
    root
}
fn client() -> Client {
    Client::new(
        API,
        Some(Session {
            api_url: API.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "fixture-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
async fn journal(dir: &tempfile::TempDir) -> Journal {
    let store = RuntimeStore::new(Some(dir.path().to_path_buf()), true)
        .await
        .unwrap();
    Journal::new(
        store,
        "fixture-owner".into(),
        "context".into(),
        Zeroizing::new([42; 32]),
    )
}
fn id(digit: char) -> String {
    std::iter::repeat_n(digit, 64).collect()
}
fn record(root: &Path, suffix: &str) -> Value {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let path = fixture["files"]
        .as_object()
        .unwrap()
        .keys()
        .find(|path| path.ends_with(suffix))
        .unwrap()
        .clone();
    read_json(&root.join(path)).ok().unwrap()
}
const SCOPE: LegacyScope<'static> = LegacyScope {
    api_url: "https://api.example.org/",
    hashed_email: "fixture-owner",
    team: None,
};

#[tokio::test]
async fn npm_outbox_records_move_into_native_journal_exactly_once() {
    let npm = npm_outbox();
    let native = private_dir();
    let journal = journal(&native).await;
    let mut client = client();
    let mut tasks = client.tasks();
    let adoption = adopt(&mut tasks, &journal, npm.path(), &SCOPE)
        .await
        .ok()
        .unwrap();
    let adopted = adoption
        .adopted
        .iter()
        .map(|(id, _)| id.clone())
        .collect::<Vec<_>>();
    assert_eq!(adopted, vec![id('1'), id('2'), id('3'), id('5')]);
    let mut refused = adoption.refused.clone();
    refused.sort();
    assert_eq!(
        refused,
        vec![
            (id('4'), "legacy_task_outbox_unverified_caller"),
            (id('6'), "legacy_task_outbox_unverified_caller"),
        ]
    );
    assert_eq!(journal.pending().await.unwrap().len(), 4);
    // npm now treats migrated records as terminal; private plaintext is gone.
    let create = record(npm.path(), &format!("{}.json", id('1')));
    assert_eq!(create["rejected"], MIGRATED);
    assert!(create["mutation"]["input"]["plaintext_title"].is_null());
    assert!(!create.to_string().contains("Legacy private"));
    assert_eq!(
        record(npm.path(), &format!("pending/{}.json", id('5')))["rejected"],
        MIGRATED
    );
    // Refused records are left exactly as npm wrote them.
    assert!(record(npm.path(), &format!("{}.json", id('4')))["rejected"].is_null());
    assert!(record(npm.path(), &format!("pending/{}.json", id('6')))["rejected"].is_null());
    // No npm lock is left behind.
    let again = adopt(&mut tasks, &journal, npm.path(), &SCOPE)
        .await
        .ok()
        .unwrap();
    assert!(again.adopted.is_empty());
    assert_eq!(journal.pending().await.unwrap().len(), 4);
}

#[tokio::test]
async fn locked_or_foreign_scope_npm_records_are_not_touched() {
    let npm = npm_outbox();
    let native = private_dir();
    let journal = journal(&native).await;
    let mut client = client();
    let mut tasks = client.tasks();
    let foreign = LegacyScope {
        api_url: API,
        hashed_email: "someone-else",
        team: None,
    };
    let none = adopt(&mut tasks, &journal, npm.path(), &foreign)
        .await
        .ok()
        .unwrap();
    assert_eq!(none, Adoption::default());
    let team = LegacyScope {
        api_url: API,
        hashed_email: "fixture-owner",
        team: Some("team-1"),
    };
    assert_eq!(
        adopt(&mut tasks, &journal, npm.path(), &team)
            .await
            .ok()
            .unwrap(),
        Adoption::default()
    );
    let mutation_dir = record_dir(npm.path(), &format!("{}.json", id('2')));
    fs::create_dir_all(mutation_dir.join("locks").join(format!("{}.lock", id('2')))).unwrap();
    let adoption = adopt(&mut tasks, &journal, npm.path(), &SCOPE)
        .await
        .ok()
        .unwrap();
    assert!(
        !adoption
            .adopted
            .iter()
            .any(|(adopted, _)| *adopted == id('2'))
    );
    assert!(record(npm.path(), &format!("{}.json", id('2')))["rejected"].is_null());
}
fn record_dir(root: &Path, suffix: &str) -> PathBuf {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let path = fixture["files"]
        .as_object()
        .unwrap()
        .keys()
        .find(|path| path.ends_with(suffix))
        .unwrap()
        .clone();
    root.join(path).parent().unwrap().to_path_buf()
}
