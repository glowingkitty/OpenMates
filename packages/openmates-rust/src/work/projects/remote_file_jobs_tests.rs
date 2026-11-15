//! Assistant file jobs on a remote source: relay call shape, sealed mutation
//! wire form, proposal digest and the unsupported-operation refusal.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::projects::remote_files::tests::{PROJECT, host_with_write_mode};
use crate::work::tasks::tests::client;

const CHAT: &str = "chat-1";

fn create(path: &str) -> HostedFileMutation {
    HostedFileMutation {
        operation: HostedFileOperation::CreateFile,
        operation_id: "op-1".into(),
        path: path.into(),
        expected_base: None,
        content: Some("export const beds = [];\n".into()),
        patch: None,
        new_path: None,
    }
}

/// The sealed envelope of the relay request among the recorded requests.
fn opened_envelope(requests: &[String]) -> (Value, Value) {
    let send = requests
        .iter()
        .find(|r| {
            r.starts_with(&format!(
                "POST /v1/projects/{PROJECT}/sources/src/requests "
            ))
        })
        .expect("relay request sent");
    let body: Value = serde_json::from_str(send.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let opened: Value = serde_json::from_str(
        &crypto::decrypt_combined(body["encrypted_envelope"].as_str().unwrap(), &[8; 32]).unwrap(),
    )
    .unwrap();
    (body, opened)
}

#[tokio::test]
async fn a_create_reaches_the_host_sealed_with_its_digest_and_without_null_fields() {
    let reply =
        json!({"ok":true,"result":{"created":true,"path":"web-app/src/services/storage.js"}});
    let (api, server) = host_with_write_mode(reply, "apply_and_show").await;
    let mut c = client(&api);
    let mutation = create("web-app/src/services/storage.js");
    let result = c
        .projects()
        .remote_file_job(
            PROJECT,
            "src",
            CHAT,
            HostedFileOperation::CreateFile,
            &json!({}),
            Some(mutation.clone()),
        )
        .await
        .unwrap();
    assert_eq!(result["created"], true);
    let requests = server.await.unwrap();
    // apply_and_show: the relay authorizes the write, no approval is stored.
    assert!(!requests.iter().any(|r| r.contains("write-approvals")));
    let (body, opened) = opened_envelope(&requests);
    assert_eq!(body["operation"], "create_file");
    assert_eq!(body["chat_id"], CHAT);
    assert_eq!(
        body["proposal_digest"],
        mutation.digest(&[8; 32], PROJECT, CHAT).unwrap()
    );
    let sent = &opened["arguments"]["mutation"];
    assert_eq!(opened["arguments"]["chat_id"], CHAT);
    assert_eq!(sent["operation"], "create_file");
    assert_eq!(sent["expected_base"], Value::Null);
    assert!(
        sent.get("patch").is_none(),
        "the host refuses a null patch on a create"
    );
    assert!(!body.to_string().contains("beds"), "file text stays sealed");
}

#[tokio::test]
async fn an_always_ask_create_stores_the_approval_first() {
    let reply = json!({"ok":true,"result":{"created":true}});
    let (api, server) = host_with_write_mode(reply, "always_ask").await;
    let mut c = client(&api);
    c.projects()
        .remote_file_job(
            PROJECT,
            "src",
            CHAT,
            HostedFileOperation::CreateFile,
            &json!({}),
            Some(create("a.txt")),
        )
        .await
        .unwrap();
    let requests = server.await.unwrap();
    let approval = requests
        .iter()
        .position(|r| r.contains("write-approvals"))
        .expect("approval stored");
    let send = requests
        .iter()
        .position(|r| {
            r.starts_with(&format!(
                "POST /v1/projects/{PROJECT}/sources/src/requests "
            ))
        })
        .unwrap();
    assert!(approval < send);
}

#[tokio::test]
async fn a_read_passes_the_job_arguments_and_the_chat() {
    let reply = json!({"ok":true,"result":{"path":"README.md","content":"# Garden"}});
    let (api, server) = host_with_write_mode(reply, "apply_and_show").await;
    let mut c = client(&api);
    let result = c
        .projects()
        .remote_file_job(
            PROJECT,
            "src",
            CHAT,
            HostedFileOperation::ReadText,
            &json!({"path":"README.md"}),
            None,
        )
        .await
        .unwrap();
    assert_eq!(result["path"], "README.md");
    let (body, opened) = opened_envelope(&server.await.unwrap());
    assert_eq!(body["operation"], "read_text");
    assert_eq!(body["chat_id"], CHAT);
    assert_eq!(opened["arguments"], json!({"path":"README.md"}));
    assert!(body.get("proposal_digest").is_none());
}

#[tokio::test]
async fn rename_and_delete_are_refused_before_any_request() {
    let mut c = client("http://127.0.0.1:9");
    for operation in [
        HostedFileOperation::RenameFile,
        HostedFileOperation::DeleteFile,
    ] {
        let error = c
            .projects()
            .remote_file_job(
                PROJECT,
                "src",
                CHAT,
                operation,
                &json!({"path":"a.txt"}),
                None,
            )
            .await
            .unwrap_err();
        assert!(matches!(
            error,
            ProjectRequesterError::Remote { ref code, .. } if code == REMOTE_OPERATION_UNSUPPORTED
        ));
    }
}

#[test]
fn a_content_search_needs_read_and_a_file_search_does_not() {
    let content = file_job_call(
        CHAT,
        HostedFileOperation::Search,
        &json!({"include_content":true}),
        None,
    )
    .unwrap();
    let names = file_job_call(
        CHAT,
        HostedFileOperation::Search,
        &json!({"query":"bed"}),
        None,
    )
    .unwrap();
    assert_eq!((content.capability, names.capability), (Some("read"), None));
}

#[test]
fn proposal_debug_never_shows_the_path_or_text() {
    let shown = format!(
        "{:?}",
        WriteProposal::FileMutation(FileMutationProposal(create("secret/plan.txt")))
    );
    assert!(!shown.contains("secret") && !shown.contains("beds"));
}
