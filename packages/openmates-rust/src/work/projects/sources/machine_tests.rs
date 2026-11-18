//! New-folder-on-a-machine requester: placeholder parsing, the keyed digest and
//! sealed arguments of `create_source`, machine grouping and the new host codes.
// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
use super::super::remote_ops::{RemoteOpCode, WriteProposal};
use super::machine::group_machine_hosts;
use super::*;
use hmac::{Hmac, Mac};
use sha2::Sha256;

const KEY: [u8; 32] = [7; 32];

fn enc(text: &str) -> String {
    crypto::server_fields::encrypt_text(text, &KEY, &[]).expect("encrypt")
}

fn hex_hmac(message: &str) -> String {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&KEY).expect("key");
    mac.update(message.as_bytes());
    mac.finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

fn placeholder_row() -> Value {
    json!({"source_id":"src_abc","hashed_project_id":hash("project-1"),
        "hashed_user_id":hash("owner"),"hashed_team_id":null,"source_type":"local_folder",
        "encrypted_display_name":enc("Kitchen renovation"),"encrypted_metadata":enc("{}"),
        "capabilities":["create_source"],"status":"creation_pending","created_at":1,
        "updated_at":1,"last_indexed_at":null,"host_device_hash":"a".repeat(64)})
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn parses_a_creation_pending_placeholder_with_its_machine() {
    let source =
        source_decode(&placeholder_row(), "project-1", "owner", None, &KEY).expect("decode");
    assert!(source.status == ProjectSourceStatus::CreationPending);
    assert!(source.capabilities == vec![ProjectSourceCapability::CreateSource]);
    assert_eq!(
        source.host_device_hash.as_deref(),
        Some("a".repeat(64).as_str())
    );
    assert_eq!(source.display_name, "Kitchen renovation");
    assert_eq!(
        serde_json::to_value(ProjectSourceCapability::CreateSource).expect("wire"),
        json!("create_source")
    );
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn legacy_rows_without_a_machine_decode_with_none() {
    let mut row = placeholder_row();
    row["status"] = json!("offline");
    row["capabilities"] = json!(["read"]);
    row.as_object_mut()
        .expect("object")
        .remove("host_device_hash");
    let source = source_decode(&row, "project-1", "owner", None, &KEY).expect("decode");
    assert_eq!(source.host_device_hash, None);
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn create_source_digest_matches_the_host_tuple_and_binds_the_name() {
    let proposal = WriteProposal::CreateSource {
        operation_id: "op-1".into(),
        project_name: "Kitchen renovation".into(),
    };
    assert_eq!(
        proposal.digest(&KEY, "p1", "chat-1").expect("digest"),
        hex_hmac(
            r#"["openmates-remote-create-source-proposal-v1","p1","chat-1","create_source","op-1","Kitchen renovation"]"#
        )
    );
    let other = WriteProposal::CreateSource {
        operation_id: "op-1".into(),
        project_name: "Garden".into(),
    };
    assert_ne!(
        other.digest(&KEY, "p1", "chat-1").expect("digest"),
        proposal.digest(&KEY, "p1", "chat-1").expect("digest")
    );
    assert!(proposal.digest(&KEY, "p1", "").is_err());
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn create_source_arguments_use_the_host_bootstrap_shape() {
    let proposal = WriteProposal::CreateSource {
        operation_id: "op-1".into(),
        project_name: "Kitchen renovation".into(),
    };
    assert_eq!(
        proposal.arguments("chat-1"),
        json!({"chat_id":"chat-1","create":{"operation_id":"op-1","project_name":"Kitchen renovation"}})
    );
    assert_eq!(proposal.operation_id(), "op-1");
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn machines_are_grouped_from_connected_sources_only() {
    let row = |name: &str, device: &str, status: &str| json!({"encrypted_display_name":enc(name),"host_device_hash":device,"status":status});
    let (a, b) = ("a".repeat(64), "b".repeat(64));
    let rows = vec![
        row("web-shop", &a, "connected"),
        row("api", &a, "connected"),
        row("laptop-notes", &b, "connected"),
        row("old", &b, "offline"),
        json!({"encrypted_display_name":enc("legacy"),"status":"connected"}),
    ];
    let hosts = group_machine_hosts(&rows, &KEY).expect("group");
    assert_eq!(hosts.len(), 2);
    assert_eq!(hosts[0].host_device_hash, a);
    assert_eq!(
        hosts[0].source_names,
        vec!["api".to_owned(), "web-shop".to_owned()]
    );
    assert_eq!(hosts[1].source_names, vec!["laptop-notes".to_owned()]);
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[test]
fn creation_codes_map_to_typed_variants() {
    for (wire, code) in [
        (
            "creation_not_configured",
            RemoteOpCode::CreationNotConfigured,
        ),
        ("invalid_project_name", RemoteOpCode::InvalidProjectName),
        (
            "creation_folder_unavailable",
            RemoteOpCode::CreationFolderUnavailable,
        ),
        ("target_exists", RemoteOpCode::TargetExists),
        (
            "creation_completion_failed",
            RemoteOpCode::CreationCompletionFailed,
        ),
        ("identity_missing", RemoteOpCode::IdentityMissing),
    ] {
        assert_eq!(RemoteOpCode::from_wire(wire), code);
    }
}

// contract-test: supporting surface=cli assertions=projects.creation.machine-folder
#[tokio::test]
async fn create_waits_until_the_machine_binds_the_fresh_placeholder() {
    use crate::work::projects::remote_files::tests::{PROJECT, raw, read_request};
    use tokio::io::AsyncWriteExt;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind");
    let api = format!("http://{}", listener.local_addr().expect("addr"));
    let server = tokio::spawn(async move {
        let mut lists = 0;
        loop {
            let (mut socket, _) = listener.accept().await.expect("accept");
            let request = read_request(&mut socket).await;
            let line = request.lines().next().expect("line").to_owned();
            let body = if line.starts_with(&format!("GET /v1/projects/{PROJECT}/sources")) {
                lists += 1;
                // The host binds the placeholder only on its next rescan.
                let mut row = json!({"source_id":"src","status":"creation_pending"});
                if lists > 1 {
                    row["source_session_id"] = json!("sess");
                    row["key_epoch"] = json!(1);
                }
                json!({"sources":[row]})
            } else if line.starts_with(&format!("GET /v1/projects/{PROJECT} ")) {
                json!({"project":raw()})
            } else {
                panic!("unexpected request {line}");
            }
            .to_string();
            socket
                .write_all(format!("HTTP/1.1 200 Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes())
                .await
                .expect("write");
            if lists == 2 {
                return lists;
            }
        }
    });
    let mut c = crate::work::tasks::tests::client(&api);
    c.projects()
        .wait_for_placeholder_binding(PROJECT, "src")
        .await
        .expect("bound");
    assert_eq!(
        server.await.expect("server"),
        2,
        "polled until the placeholder was bound"
    );
}
