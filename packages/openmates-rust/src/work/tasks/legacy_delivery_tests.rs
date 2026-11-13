//! npm legacy Task outbox adoption, proven against records written by the real npm code (`legacy_outbox_fixture.json`).
use super::super::tests::{client, mock};
use super::*;

const FIXTURE: &str = include_str!("legacy_outbox_fixture.json");

fn record(suffix: &str) -> Value {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let (_, text) = fixture["files"]
        .as_object()
        .unwrap()
        .iter()
        .find(|(path, _)| path.ends_with(suffix))
        .unwrap();
    serde_json::from_str(text.as_str().unwrap()).unwrap()
}
fn id(digit: char) -> String {
    std::iter::repeat_n(digit, 64).collect()
}
fn body(request: &str) -> Value {
    serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap()
}

#[tokio::test]
async fn npm_create_is_adopted_without_plaintext_and_its_ciphertext_decrypts() {
    let npm = record(&format!("{}.json", id('1')));
    assert_eq!(npm["uncertain"], true);
    assert_eq!(
        npm["mutation"]["input"]["plaintext_title"],
        "Legacy private title"
    );
    let mut created = npm["mutation"]["input"].clone();
    created
        .as_object_mut()
        .unwrap()
        .retain(|k, _| !k.starts_with("plaintext_"));
    let (api, server) = mock(vec![json!({"task":created})]).await;
    let mut client = client(&api);
    let mut tasks = client.tasks();
    let delivery = tasks
        .adopt_npm_mutation(&npm["mutation"], &id('1'))
        .await
        .unwrap()
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::Create);
    let wire = serde_json::to_string(&delivery).unwrap();
    assert!(!wire.contains("plaintext_") && !wire.contains("Legacy private"));
    let task = tasks.execute_delivery(&delivery, false).await.unwrap();
    assert_eq!(task["title"], "Legacy private title");
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/user-tasks "));
    let sent = body(&requests[0]);
    // Plaintext is re-derived from the npm ciphertext with the same master key.
    assert_eq!(sent["plaintext_title"], "Legacy private title");
    assert_eq!(sent["plaintext_description"], "Legacy private details");
    assert_eq!(
        sent["encrypted_title"],
        npm["mutation"]["input"]["encrypted_title"]
    );
}

#[tokio::test]
async fn npm_update_and_complete_keep_original_ciphertext_and_version() {
    let mut client = client("http://127.0.0.1:9");
    let mut tasks = client.tasks();
    let update = record(&format!("{}.json", id('2')));
    let delivery = tasks
        .adopt_npm_mutation(&update["mutation"], &id('2'))
        .await
        .unwrap()
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::Update);
    assert_eq!(delivery.input, update["mutation"]["input"]);
    let complete = record(&format!("{}.json", id('3')));
    let delivery = tasks
        .adopt_npm_mutation(&complete["mutation"], &id('3'))
        .await
        .unwrap()
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::Complete);
    assert_eq!(delivery.input, json!({"version":3,"team_id":null}));
}

#[tokio::test]
async fn npm_records_without_provable_caller_or_shape_are_refused() {
    let mut client = client("http://127.0.0.1:9");
    let mut tasks = client.tasks();
    let codex = record(&format!("{}.json", id('4')));
    assert_eq!(
        tasks
            .adopt_npm_mutation(&codex["mutation"], &id('4'))
            .await
            .unwrap()
            .err()
            .unwrap(),
        LegacyRefusal::UnverifiedCaller
    );
    let mut wrong = record(&format!("{}.json", id('1')))["mutation"].clone();
    wrong["taskId"] = json!("cccccccc-1111-4111-8111-aabbccddeeff");
    assert_eq!(
        tasks
            .adopt_npm_mutation(&wrong, &id('1'))
            .await
            .unwrap()
            .err()
            .unwrap(),
        LegacyRefusal::Malformed
    );
    assert_eq!(
        tasks
            .adopt_npm_mutation(
                &json!({"kind":"wipe","taskId":"cccccccc-1111-4111-8111-aabbccddeeff"}),
                &id('9')
            )
            .await
            .unwrap()
            .err()
            .unwrap(),
        LegacyRefusal::Malformed
    );
    let assignee = record(&format!("pending/{}.json", id('6')));
    let task = "bbbbbbbb-1111-4111-8111-aabbccddeeff";
    assert_eq!(
        tasks
            .adopt_npm_activity(task, "assignee", &assignee, &id('6'))
            .await
            .unwrap()
            .err()
            .unwrap(),
        LegacyRefusal::UnverifiedCaller
    );
}

#[tokio::test]
async fn npm_user_activity_is_adopted_byte_for_byte() {
    let mut client = client("http://127.0.0.1:9");
    let mut tasks = client.tasks();
    let npm = record(&format!("pending/{}.json", id('5')));
    let task = "bbbbbbbb-1111-4111-8111-aabbccddeeff";
    let delivery = tasks
        .adopt_npm_activity(task, "user", &npm, &id('5'))
        .await
        .unwrap()
        .unwrap();
    assert!(delivery.kind == TaskMutationKind::Activity);
    assert_eq!(delivery.input, npm["input"]);
    assert_eq!(
        tasks
            .adopt_npm_activity(task, "user", &npm, &id('6'))
            .await
            .unwrap()
            .err()
            .unwrap(),
        LegacyRefusal::Malformed,
        "entry id must equal the npm delivery id"
    );
}
