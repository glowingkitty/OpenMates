//! Rename/delete of hosted file links against the in-memory server: the embed is kept and the link id follows the path.
use super::moves::renamed_metadata;
use super::tests::{CHAT, FakeServer, PROJECT, create, project_key, run};
use super::*;

fn rename(path: &str, new_path: &str, op: &str) -> HostedFileMutation {
    HostedFileMutation {
        operation: HostedFileOperation::RenameFile,
        operation_id: op.into(),
        path: path.into(),
        expected_base: None,
        content: None,
        patch: None,
        new_path: Some(new_path.into()),
    }
}

fn delete(path: &str, op: &str) -> HostedFileMutation {
    HostedFileMutation {
        operation: HostedFileOperation::DeleteFile,
        operation_id: op.into(),
        path: path.into(),
        expected_base: None,
        content: None,
        patch: None,
        new_path: None,
    }
}

#[tokio::test]
async fn rename_keeps_embed_id_and_rederives_item_id() {
    let mut server = FakeServer::default();
    let created = run(&mut server, Some(&create("src/a.ts", "x\n", "op-c")), None)
        .await
        .unwrap();
    let embed = created["embed_id"].as_str().unwrap().to_owned();
    let key = project_key();
    let old_item = hosted_file_identity(&key, "src/a.ts", HostedIdentityKind::Item).unwrap();
    let renamed = run(
        &mut server,
        Some(&rename("src/a.ts", "src/b.ts", "op-r")),
        None,
    )
    .await
    .unwrap();
    assert_eq!(renamed["embed_id"], embed.as_str());
    assert_eq!(renamed["path"], "src/b.ts");
    assert_eq!(renamed["previous_path"], "src/a.ts");
    let (item, body) = &server.moves[0];
    assert_eq!(item, &old_item);
    assert_eq!(
        body["new_project_item_id"],
        hosted_file_identity(&key, "src/b.ts", HostedIdentityKind::Item).unwrap()
    );
    assert_eq!(body["operation_id"], "op-r");
    let open = |field: &str| {
        crypto::server_fields::decrypt_text(body[field].as_str().unwrap(), &key, &[]).unwrap()
    };
    assert_eq!(open("encrypted_display_name"), "src/b.ts");
    let metadata: Value = serde_json::from_str(&open("encrypted_metadata")).unwrap();
    assert_eq!(
        metadata,
        json!({"path": "src/b.ts", "source": HOSTED_SOURCE})
    );
    // The same embed is read at its new path; no revision was committed.
    let read = run(&mut server, None, Some("src/b.ts")).await.unwrap();
    assert_eq!(read["embed_id"], embed.as_str());
    assert_eq!(read["content"], "x\n");
    assert_eq!(server.commits.len(), 1);
}

#[tokio::test]
async fn rename_refuses_a_linked_target_and_protected_paths() {
    let mut server = FakeServer::default();
    for (path, op) in [("a.txt", "op-1"), ("b.txt", "op-2")] {
        run(&mut server, Some(&create(path, "x\n", op)), None)
            .await
            .unwrap();
    }
    let conflict = run(&mut server, Some(&rename("a.txt", "b.txt", "op-3")), None)
        .await
        .unwrap_err();
    assert_eq!(conflict, HostedFileError::Refused("path_conflict"));
    assert_eq!(conflict.status(), "conflict");
    let protected = run(&mut server, Some(&rename("a.txt", ".env", "op-4")), None)
        .await
        .unwrap_err();
    assert_eq!(protected, HostedFileError::Refused("protected_path"));
    let missing = run(&mut server, Some(&rename("c.txt", "d.txt", "op-5")), None)
        .await
        .unwrap_err();
    assert_eq!(missing, HostedFileError::Refused("file_not_found"));
    assert!(server.moves.is_empty());
}

#[tokio::test]
async fn delete_removes_only_the_link() {
    let mut server = FakeServer::default();
    let created = run(&mut server, Some(&create("a.txt", "x\n", "op-c")), None)
        .await
        .unwrap();
    let deleted = run(&mut server, Some(&delete("a.txt", "op-d")), None)
        .await
        .unwrap();
    assert_eq!(deleted["deleted"], true);
    assert_eq!(deleted["embed_id"], created["embed_id"]);
    assert_eq!(server.moves[0].1, json!({"operation_id": "op-d"}));
    assert!(server.files.is_empty());
    assert!(
        server
            .heads
            .contains_key(created["embed_id"].as_str().unwrap())
    );
}

#[test]
fn server_issued_rename_and_delete_arguments_become_mutations() {
    let job = |operation, arguments| HostedFileJob {
        operation_id: "op-j".into(),
        chat_id: CHAT.into(),
        operation,
        arguments,
    };
    let renamed = super::api::job_mutation(&job(
        HostedFileOperation::RenameFile,
        json!({"path": "web-app/a.ts", "new_path": "web-app/b.ts"}),
    ))
    .unwrap()
    .unwrap();
    assert!(renamed == rename("web-app/a.ts", "web-app/b.ts", "op-j"));
    let deleted = super::api::job_mutation(&job(
        HostedFileOperation::DeleteFile,
        json!({"path": "web-app/a.ts"}),
    ))
    .unwrap()
    .unwrap();
    assert!(deleted == delete("web-app/a.ts", "op-j"));
}

#[tokio::test]
async fn move_results_name_the_link_ids() {
    let mut server = FakeServer::default();
    run(&mut server, Some(&create("a.txt", "x\n", "op-c")), None)
        .await
        .unwrap();
    let key = project_key();
    let old_item = hosted_file_identity(&key, "a.txt", HostedIdentityKind::Item).unwrap();
    let new_item = hosted_file_identity(&key, "b.txt", HostedIdentityKind::Item).unwrap();
    let renamed = run(&mut server, Some(&rename("a.txt", "b.txt", "op-r")), None)
        .await
        .unwrap();
    assert_eq!(renamed["project_item_id"], new_item.as_str());
    assert_eq!(renamed["previous_project_item_id"], old_item.as_str());
    let deleted = run(&mut server, Some(&delete("b.txt", "op-d")), None)
        .await
        .unwrap();
    assert_eq!(deleted["project_item_id"], new_item.as_str());
    // Every client-derived file item id is a UUIDv5 (the server's file pattern).
    assert_eq!(new_item.as_bytes()[14], b'5');
}

#[test]
fn rename_and_delete_mutations_validate_their_shape() {
    assert!(rename("a", "b", "op").validate().is_ok());
    assert!(delete("a", "op").validate().is_ok());
    let mut bad = rename("a", "b", "op");
    bad.patch = Some("x".into());
    assert_eq!(
        bad.validate(),
        Err(HostedFileError::Refused("invalid_file_mutation"))
    );
    let mut bad = delete("a", "op");
    bad.new_path = Some("b".into());
    assert_eq!(
        bad.validate(),
        Err(HostedFileError::Refused("invalid_file_mutation"))
    );
    let mut bad = create("a", "x", "op");
    bad.new_path = Some("b".into());
    assert_eq!(
        bad.validate(),
        Err(HostedFileError::Refused("invalid_file_mutation"))
    );
    // Renames bind their target in the commitment; deletes do not change the
    // create/update tuple.
    let key = project_key();
    assert_ne!(
        rename("a", "b", "op").digest(&key, PROJECT, CHAT).unwrap(),
        rename("a", "c", "op").digest(&key, PROJECT, CHAT).unwrap()
    );
}

#[test]
fn renamed_metadata_tracks_the_application_folder() {
    let adopted = json!({"path": "web-app/src/a.ts", "source": HOSTED_SOURCE,
        "application_embed_id": "app", "application_path": "src/a.ts"});
    assert_eq!(
        renamed_metadata("web-app/src/a.ts", "web-app/src/b.ts", &adopted),
        json!({"path": "web-app/src/b.ts", "source": HOSTED_SOURCE,
            "application_embed_id": "app", "application_path": "src/b.ts"})
    );
    assert_eq!(
        renamed_metadata("web-app/src/a.ts", "docs/a.ts", &adopted),
        json!({"path": "docs/a.ts", "source": HOSTED_SOURCE})
    );
}
