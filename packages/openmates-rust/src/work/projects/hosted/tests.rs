//! Hosted file writer: TS cross-implementation vectors (identity, digest, patch) and the executor against an in-memory server.
use super::io::{HostedIo, decode_head};
use super::job::{self, HostedContext};
use super::restore::replay_rows;
use super::*;
use std::collections::BTreeMap;

pub(super) const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
pub(super) const CHAT: &str = "22222222-2222-4222-8222-222222222222";

pub(super) fn project_key() -> [u8; 32] {
    std::array::from_fn(|i| i as u8 + 1)
}

pub(super) fn chat_key() -> [u8; 32] {
    [42; 32]
}

/// Produced by the web formula (`hostedProjectFileIdentity`) under Node 24
/// WebCrypto with the key bytes 1..=32.
#[test]
fn hosted_identity_matches_typescript_vectors() {
    let key = project_key();
    for (path, embed, item) in [
        (
            "src/main.py",
            "04fec007-56e4-50e9-a878-a90a4f1288ad",
            "ec6af1c2-d9e9-5224-8b1a-76a0207b618c",
        ),
        (
            "README.md",
            "303cc74b-8be5-5bfd-a1ce-4dca6a4d179c",
            "8360e070-80c2-553c-ae8f-f6edde7f0284",
        ),
        (
            "docs/ünï code.md",
            "84ed4ad6-c64f-5d1d-b2e2-5762c16fd3b8",
            "8a3f3439-a92c-52ae-a4d7-14e394dd642e",
        ),
    ] {
        assert_eq!(
            hosted_file_identity(&key, path, HostedIdentityKind::Embed).unwrap(),
            embed
        );
        assert_eq!(
            hosted_file_identity(&key, path, HostedIdentityKind::Item).unwrap(),
            item
        );
    }
}

/// Produced by `projectFileMutationDigest` (projectFileMutationProtocol.ts) run under Node 24.
#[test]
fn proposal_digest_matches_typescript_vectors() {
    let key = project_key();
    let create = HostedFileMutation {
        operation: HostedFileOperation::CreateFile,
        operation_id: "op-1".into(),
        path: "src/main.py".into(),
        expected_base: None,
        content: Some("print(1)\n".into()),
        patch: None,
        new_path: None,
    };
    assert_eq!(
        create.digest(&key, PROJECT, CHAT).unwrap(),
        "8a8a550f1fc2b53775288a568c4c02fa23701afbec47725643820f12c3c7f885"
    );
    let update = HostedFileMutation {
        operation: HostedFileOperation::UpdateFile,
        operation_id: "op-2".into(),
        path: "src/main.py".into(),
        expected_base: Some("a".repeat(64)),
        content: None,
        patch: Some(
            "--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-print(1)\n+print(2)\n".into(),
        ),
        new_path: None,
    };
    assert_eq!(
        update.digest(&key, PROJECT, CHAT).unwrap(),
        "f4b5cf574f922aec95501bca5dbcf46213f42569b9cd4ad7044d5e6d4843ad65"
    );
}

/// Outputs of `applyProjectFilePatch` (projectFilePatch.ts) under Node 24.
#[test]
fn exact_patch_applies_like_typescript() {
    let diff = "--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,3 @@\n line one\n-line two\n+line 2\n line three\n";
    assert_eq!(
        apply_exact_patch("line one\nline two\nline three\n", diff, "src/main.py").unwrap(),
        "line one\nline 2\nline three\n"
    );
    let no_newline =
        "--- a/x.txt\n+++ b/x.txt\n@@ -1,2 +1,3 @@\n a\n-b\n\\ No newline at end of file\n+b\n+c\n";
    assert_eq!(
        apply_exact_patch("a\nb", no_newline, "x.txt").unwrap(),
        "a\nb\nc\n"
    );
    assert_eq!(
        apply_exact_patch("line one\nline two\nline three\n", diff, "other.py"),
        Err(HostedFileError::Refused("invalid_patch"))
    );
    assert_eq!(
        apply_exact_patch("changed\n", diff, "src/main.py"),
        Err(HostedFileError::Refused("invalid_patch"))
    );
}

#[test]
fn replacement_patch_round_trips_through_exact_apply() {
    for (old, next) in [
        ("a\nb\n", "c\n"),
        ("", "new\nfile"),
        ("x", ""),
        ("same\n", "same\nmore\n"),
    ] {
        let patch = replacement_patch("dir/f.txt", old, next);
        assert_eq!(apply_exact_patch(old, &patch, "dir/f.txt").unwrap(), next);
    }
}

#[test]
fn server_rejection_codes_are_filtered_like_the_web_executor() {
    assert_eq!(
        HostedFileError::rejected(Some("WRITE_POLICY_REQUIRED")).code(),
        "write_policy_required"
    );
    assert_eq!(
        HostedFileError::rejected(Some("bad code!")).code(),
        "client_execution_failed"
    );
    assert_eq!(HostedFileError::rejected(None).code(), "commit_rejected");
    assert_eq!(HostedFileError::Refused("stale_base").status(), "conflict");
    assert_eq!(
        HostedFileError::Refused("file_key_unavailable").status(),
        "waiting_for_executor"
    );
    assert_eq!(HostedFileError::Refused("invalid_patch").status(), "failed");
}

/// In-memory stand-in for the server: link rows, ciphertext heads, receipts.
#[derive(Default)]
pub(super) struct FakeServer {
    pub(super) files: Vec<HostedFile>,
    pub(super) heads: BTreeMap<String, Value>,
    pub(super) receipts: BTreeMap<String, Value>,
    pub(super) commits: Vec<Value>,
    pub(super) conflict: bool,
    /// `(item id, body)` of every rename/delete request.
    pub(super) moves: Vec<(String, Value)>,
}

impl HostedIo for FakeServer {
    async fn list_files(&mut self) -> HostedResult<Vec<HostedFile>> {
        Ok(self.files.clone())
    }
    async fn read_head(&mut self, embed_id: &str) -> HostedResult<HostedHead> {
        let response = self
            .heads
            .get(embed_id)
            .ok_or(HostedFileError::Core(Error::Invalid("missing")))?;
        decode_head(response, embed_id, PROJECT, &project_key())
    }
    async fn receipt(
        &mut self,
        _: &str,
        operation_id: &str,
        _: &str,
        _: &str,
    ) -> HostedResult<Option<Value>> {
        Ok(self.receipts.get(operation_id).cloned())
    }
    async fn commit(&mut self, payload: Value) -> HostedResult<Value> {
        self.commits.push(payload.clone());
        if self.conflict {
            return Ok(json!({"status": "conflict", "current_revision": 9}));
        }
        let embed_id = payload["embed_id"].as_str().unwrap().to_owned();
        let revision = payload["expected_revision"].as_u64().unwrap() + 1;
        let wrapper = if let Some(create) = payload.get("create") {
            let metadata = crypto::server_fields::decrypt_text(
                create["encrypted_metadata"].as_str().unwrap(),
                &project_key(),
                &[],
            )
            .unwrap();
            let path = serde_json::from_str::<Value>(&metadata).unwrap()["path"]
                .as_str()
                .unwrap()
                .to_owned();
            self.files.push(HostedFile {
                embed_id: embed_id.clone(),
                path,
                item_id: create["project_item_id"].as_str().map(str::to_owned),
                metadata: serde_json::from_str(&metadata).unwrap(),
            });
            create["key_wrappers"][0].clone()
        } else {
            self.heads[&embed_id]["embed_keys"][0].clone()
        };
        self.heads.insert(
            embed_id.clone(),
            json!({"embed": {"embed_id": embed_id, "encrypted_content": payload["head"]["encrypted_content"],
                "version_number": revision}, "embed_keys": [wrapper], "has_initial_history": true}),
        );
        Ok(json!({"status": "committed", "current_revision": revision, "embed_id": embed_id}))
    }
    async fn rename_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.moves.push((item_id.to_owned(), body.clone()));
        let metadata: Value = serde_json::from_str(
            &crypto::server_fields::decrypt_text(
                body["encrypted_metadata"].as_str().unwrap(),
                &project_key(),
                &[],
            )
            .unwrap(),
        )
        .unwrap();
        let file = self
            .files
            .iter_mut()
            .find(|f| f.item_id.as_deref() == Some(item_id))
            .ok_or(HostedFileError::Rejected("project_item_not_found".into()))?;
        file.path = metadata["path"].as_str().unwrap().to_owned();
        file.item_id = body["new_project_item_id"].as_str().map(str::to_owned);
        file.metadata = metadata;
        Ok(json!({"status": "renamed"}))
    }
    async fn delete_link(&mut self, item_id: &str, body: Value) -> HostedResult<Value> {
        self.moves.push((item_id.to_owned(), body));
        self.files.retain(|f| f.item_id.as_deref() != Some(item_id));
        Ok(json!({"status": "deleted"}))
    }
}

pub(super) fn job_for(mutation: &HostedFileMutation) -> HostedFileJob {
    HostedFileJob {
        operation_id: mutation.operation_id.clone(),
        chat_id: CHAT.into(),
        operation: mutation.operation,
        arguments: json!({"path": mutation.path}),
    }
}

pub(super) fn create(path: &str, content: &str, op: &str) -> HostedFileMutation {
    HostedFileMutation {
        operation: HostedFileOperation::CreateFile,
        operation_id: op.into(),
        path: path.into(),
        expected_base: None,
        content: Some(content.into()),
        patch: None,
        new_path: None,
    }
}

fn update(path: &str, old: &str, next: &str, op: &str) -> HostedFileMutation {
    HostedFileMutation {
        operation: HostedFileOperation::UpdateFile,
        operation_id: op.into(),
        path: path.into(),
        expected_base: Some(content_hash(old)),
        content: None,
        patch: Some(replacement_patch(path, old, next)),
        new_path: None,
    }
}

pub(super) async fn run(
    server: &mut FakeServer,
    mutation: Option<&HostedFileMutation>,
    read: Option<&str>,
) -> HostedResult<Value> {
    let key = project_key();
    let chat = chat_key();
    let ctx = HostedContext {
        project_id: PROJECT,
        project_key: &key,
        chat_key: Some(&chat),
        team_id: None,
        private_paths: &[],
        ignored_read_approved: false,
    };
    let job = match (mutation, read) {
        (Some(m), _) => job_for(m),
        (None, Some(path)) => HostedFileJob {
            operation_id: "read-1".into(),
            chat_id: String::new(),
            operation: HostedFileOperation::ReadText,
            arguments: json!({"path": path}),
        },
        (None, None) => HostedFileJob {
            operation_id: "list-1".into(),
            chat_id: String::new(),
            operation: HostedFileOperation::List,
            arguments: json!({}),
        },
    };
    job::execute(server, &ctx, &job, mutation).await
}

#[tokio::test]
async fn create_commits_the_web_transaction_shape() {
    let mut server = FakeServer::default();
    let result = run(
        &mut server,
        Some(&create("src/main.py", "print(1)\n", "op-c")),
        None,
    )
    .await
    .unwrap();
    assert_eq!(result["created"], true);
    assert_eq!(result["revision"], 1);
    let payload = &server.commits[0];
    let key = project_key();
    assert_eq!(
        payload["embed_id"],
        hosted_file_identity(&key, "src/main.py", HostedIdentityKind::Embed).unwrap()
    );
    assert_eq!(payload["expected_revision"], 0);
    assert_eq!(payload["project_id"], PROJECT);
    assert_eq!(payload["chat_id"], CHAT);
    assert_eq!(
        payload["proposal_digest"],
        create("src/main.py", "print(1)\n", "op-c")
            .digest(&key, PROJECT, CHAT)
            .unwrap()
    );
    let created = &payload["create"];
    assert_eq!(
        created["project_item_id"],
        hosted_file_identity(&key, "src/main.py", HostedIdentityKind::Item).unwrap()
    );
    let open = |field: &str, k: &[u8; 32]| {
        crypto::server_fields::decrypt_text(created[field].as_str().unwrap(), k, &[]).unwrap()
    };
    assert_eq!(
        open("encrypted_metadata", &key),
        r#"{"path":"src/main.py","source":"hosted_project_file"}"#
    );
    assert_eq!(open("encrypted_display_name", &key), "src/main.py");
    assert_eq!(
        open("target_id_encrypted", &key),
        payload["embed_id"].as_str().unwrap()
    );
    let wrappers = created["key_wrappers"].as_array().unwrap();
    assert_eq!(
        wrappers
            .iter()
            .map(|w| w["key_type"].clone())
            .collect::<Vec<_>>(),
        [json!("project"), json!("chat")]
    );
    let unwrap = |w: &Value, k: &[u8; 32]| {
        crypto::server_fields::decrypt_bytes(w["encrypted_embed_key"].as_str().unwrap(), k, &[])
            .unwrap()
    };
    let embed_key = unwrap(&wrappers[0], &key);
    assert_eq!(embed_key, unwrap(&wrappers[1], &chat_key()));
    let embed_key: [u8; 32] = embed_key.as_slice().try_into().unwrap();
    assert_eq!(
        crypto::server_fields::decrypt_text(
            created["encrypted_type"].as_str().unwrap(),
            &embed_key,
            &[]
        )
        .unwrap(),
        "code-code"
    );
    let rows = payload["history_rows"].as_array().unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["version_number"], 1);
    assert_eq!(
        crypto::server_fields::decrypt_text(
            rows[0]["encrypted_snapshot"].as_str().unwrap(),
            &embed_key,
            &[]
        )
        .unwrap(),
        "print(1)\n"
    );
    let preview = crypto::server_fields::decrypt_text(
        payload["head"]["encrypted_text_preview"].as_str().unwrap(),
        &embed_key,
        &[],
    )
    .unwrap();
    assert_eq!(preview, "src/main.py (2 lines)");
}

#[tokio::test]
async fn create_patch_read_and_restore_replay_agree() {
    let mut server = FakeServer::default();
    run(
        &mut server,
        Some(&create("src/main.py", "print(1)\n", "op-c")),
        None,
    )
    .await
    .unwrap();
    let read = run(&mut server, None, Some("src/main.py")).await.unwrap();
    assert_eq!(read["content"], "print(1)\n");
    assert_eq!(read["expected_base"], content_hash("print(1)\n"));
    assert_eq!(read["revision"], 1);
    let updated = run(
        &mut server,
        Some(&update("src/main.py", "print(1)\n", "print(2)\n", "op-u")),
        None,
    )
    .await
    .unwrap();
    assert_eq!(updated["revision"], 2);
    assert_eq!(updated["created"], false);
    assert_eq!(updated["expected_base"], content_hash("print(2)\n"));
    let read = run(&mut server, None, Some("src/main.py")).await.unwrap();
    assert_eq!(read["content"], "print(2)\n");
    let patch_rows = server.commits[1]["history_rows"].as_array().unwrap();
    assert_eq!(
        patch_rows.len(),
        1,
        "an embed with initial history gets only the patch row"
    );
    assert_eq!(patch_rows[0]["version_number"], 2);
    // The same rows the server would return rebuild both versions.
    let embed_key = run_head_key(&mut server, read["embed_id"].as_str().unwrap()).await;
    let rows: Vec<Value> = server
        .commits
        .iter()
        .flat_map(|c| c["history_rows"].as_array().unwrap().clone())
        .collect();
    assert_eq!(
        *replay_rows(&rows[..1], &embed_key, 1).unwrap(),
        "print(1)\n"
    );
    assert_eq!(*replay_rows(&rows, &embed_key, 2).unwrap(), "print(2)\n");
    assert!(replay_rows(&rows, &embed_key, 3).is_err());
    let listed = run(&mut server, None, None).await.unwrap();
    assert!(listed.to_string().contains("src/main.py"));
}

async fn run_head_key(server: &mut FakeServer, embed_id: &str) -> [u8; 32] {
    *server.read_head(embed_id).await.unwrap().embed_key
}

#[tokio::test]
async fn second_create_and_stale_update_conflict() {
    let mut server = FakeServer::default();
    run(&mut server, Some(&create("a.txt", "one\n", "op-1")), None)
        .await
        .unwrap();
    let again = run(&mut server, Some(&create("a.txt", "two\n", "op-2")), None)
        .await
        .unwrap_err();
    assert_eq!(again, HostedFileError::Refused("file_exists"));
    assert_eq!(again.status(), "conflict");
    let stale = run(
        &mut server,
        Some(&update("a.txt", "other\n", "x\n", "op-3")),
        None,
    )
    .await
    .unwrap_err();
    assert_eq!(stale, HostedFileError::Refused("stale_base"));
    let missing = run(
        &mut server,
        Some(&update("b.txt", "one\n", "x\n", "op-4")),
        None,
    )
    .await
    .unwrap_err();
    assert_eq!(missing, HostedFileError::Refused("file_not_found"));
    assert_eq!(server.commits.len(), 1, "refusals never commit");
}

#[tokio::test]
async fn committed_receipt_makes_a_retry_idempotent() {
    let mut server = FakeServer::default();
    server.receipts.insert(
        "op-r".into(),
        json!({"status": "committed", "current_revision": 4}),
    );
    let result = run(&mut server, Some(&create("a.txt", "one\n", "op-r")), None)
        .await
        .unwrap();
    assert_eq!(
        result,
        json!({"path": "a.txt", "operation_id": "op-r", "revision": 4, "idempotent": true})
    );
    assert!(server.commits.is_empty());
}

#[tokio::test]
async fn server_conflict_maps_to_revision_conflict() {
    let mut server = FakeServer {
        conflict: true,
        ..Default::default()
    };
    let error = run(&mut server, Some(&create("a.txt", "one\n", "op-1")), None)
        .await
        .unwrap_err();
    assert_eq!(error.code(), "revision_conflict");
    assert_eq!(error.status(), "conflict");
}

#[tokio::test]
async fn private_credential_files_are_refused() {
    let mut server = FakeServer::default();
    let error = run(
        &mut server,
        Some(&create(".env", "SECRET=1\n", "op-1")),
        None,
    )
    .await
    .unwrap_err();
    assert_eq!(error, HostedFileError::Refused("protected_path"));
    assert!(server.commits.is_empty());
}
