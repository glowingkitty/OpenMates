//! AUTHORED UNRUN: actual native dispatch and SDK HTTP/crypto, not self-echo receipts.
use super::*;
use sha2::{Digest, Sha256};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const FLOW: &str = "11111111-1111-4111-8111-111111111111";
const PROJECT: &str = "22222222-2222-4222-8222-222222222222";
const CHAT: &str = "33333333-3333-4333-8333-333333333333";
const ITEM: &str = "44444444-4444-4444-8444-444444444444";
const OWNER: &str = "55555555-5555-4555-8555-555555555555";
fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(crate::storage::Session {
            api_url: api.into(),
            session_id: "fixture-session".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: "fixture".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn invocation(file: &str, json: bool) -> Invocation {
    Invocation {
        path: vec!["workflows".into(), "update".into()],
        positionals: vec![FLOW.into()],
        flags: BTreeMap::from([
            ("file".into(), json!(file)),
            ("json".into(), json!(json)),
            ("yes".into(), json!(true)),
        ]),
    }
}
fn workflow() -> Value {
    json!({"id":FLOW,"title":"Updated","slug":"updated","status":"disabled","enabled":false,"source_chat_id":CHAT,"current_version_id":"version-2","run_content_retention":"last_5","graph":{"version":1,"trigger_node_id":null,"nodes":[],"edges":[]}})
}
fn project() -> Value {
    json!({"project_id":PROJECT,"hashed_user_id":digest(OWNER),"hashed_team_id":null,"encrypted_project_key":openmates_sdk::crypto::encrypt_bytes(&[2;32],&[1;32]).unwrap(),"encrypted_name":openmates_sdk::crypto::encrypt_combined("Fixture",&[2;32]).unwrap()})
}
async fn request(socket: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = vec![];
    let mut chunk = [0; 4096];
    let (header, length) = loop {
        let count = socket.read(&mut chunk).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&chunk[..count]);
        assert!(bytes.len() < 2 * 1024 * 1024);
        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            let head = std::str::from_utf8(&bytes[..end]).unwrap();
            let length = head
                .lines()
                .find_map(|line| {
                    line.to_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            break (end + 4, length);
        }
    };
    while bytes.len() < header + length {
        let count = socket.read(&mut chunk).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&chunk[..count]);
    }
    let line = std::str::from_utf8(&bytes[..header])
        .unwrap()
        .lines()
        .next()
        .unwrap()
        .to_owned();
    let body = if length == 0 {
        Value::Null
    } else {
        serde_json::from_slice(&bytes[header..header + length]).unwrap()
    };
    (line, body)
}
async fn reply(socket: &mut tokio::net::TcpStream, status: &str, body: Value) {
    let body = body.to_string();
    socket.write_all(format!("HTTP/1.1 {status}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}

async fn run_case(
    remote_status: &'static str,
    deny_metadata: bool,
    approve: bool,
    slug: bool,
) -> (Result<CliOutput, CliError>, Vec<String>, Value) {
    use openmates_sdk::remote_access_crypto::{Handshake, HandshakeState, Identity, Role};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let mut lines = vec![];
        let mut sealed = None;
        let mut saved_content = String::new();
        let mut saved_metadata = Value::Null;
        let mut workflow_reads = 0;
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let (line, body) = request(&mut socket).await;
            let parts: Vec<_> = line.split_whitespace().collect();
            let url = url::Url::parse(&format!("http://fixture{}", parts[1])).unwrap();
            let path = url.path();
            let method = parts[0];
            lines.push(line.clone());
            assert!(lines.len() < 25);
            let response = match (method, path) {
                ("POST", p) if p == format!("/v1/workflows/{FLOW}/yaml") => {
                    assert_eq!(body["source"], "title: Updated\n");
                    json!({"workflow":workflow(),"validation":{"draft_valid":true,"enable_ready":false,"diagnostics":[{"path":"$","message":"review bindings"}]},"warnings":[{"code":"review","message":"Review this Workflow"}]})
                }
                ("PATCH", p) if p == format!("/v1/workflows/{FLOW}") => {
                    assert!(slug);
                    assert!(body.get("slug").is_none());
                    let mut flow = workflow();
                    flow["encrypted_slug"] = body["encrypted_slug"].clone();
                    json!({"workflow":flow,"warnings":[]})
                }
                ("GET", p) if p == format!("/v1/workflows/{FLOW}") => {
                    workflow_reads += 1;
                    let mut flow = workflow();
                    if remote_status == "version-changed" && workflow_reads >= 3 {
                        flow["current_version_id"] = json!("version-3");
                    }
                    json!({"workflow":flow})
                }
                ("GET", "/v1/projects") => json!({"projects":[project()]}),
                ("GET", p) if p == format!("/v1/projects/{PROJECT}/items") => {
                    json!({"folders":[],"items":[{"project_item_id":ITEM,"item_type":"workflow","hashed_project_id":digest(PROJECT),"hashed_user_id":digest(OWNER),"hashed_team_id":null,"target_id_hash":digest(FLOW),"target_id_encrypted":openmates_sdk::crypto::encrypt_combined(FLOW,&[2;32]).unwrap(),"encrypted_metadata":openmates_sdk::crypto::encrypt_combined(&json!({"legacy":{"preserve":"private extra"},"remote_workflow_file":{"project_id":PROJECT,"source_id":"source","folder_path":"workflows"}}).to_string(),&[2;32]).unwrap()}]})
                }
                ("GET", p) if p == format!("/v1/projects/{PROJECT}/sources") => {
                    if remote_status == "missing-source" {
                        json!({"sources":[]})
                    } else {
                        json!({"sources":[{"source_id":"source","status":if remote_status=="offline"{"disconnected"}else{"connected"},"source_session_id":"source-session","key_epoch":1}]})
                    }
                }
                ("GET", "/v1/projects/focus/current") => {
                    assert!(url.query().unwrap().contains(CHAT));
                    json!({"focus":{"project_id":PROJECT}})
                }
                ("GET", p) if p == format!("/v1/projects/{PROJECT}/settings") => {
                    json!({"settings":{"write_mode":"always_ask"}})
                }
                ("POST", p) if p == format!("/v1/projects/{PROJECT}/write-approvals") => {
                    assert!(approve);
                    assert_eq!(body["chat_id"], CHAT);
                    assert_eq!(body["proposal_digest"].as_str().unwrap().len(), 64);
                    json!({"success":true})
                }
                ("POST", "/v1/auth/session") => {
                    if remote_status == "auth-denied" {
                        reply(
                            &mut socket,
                            "401 Unauthorized",
                            json!({"detail":"private denial"}),
                        )
                        .await;
                        return (lines, saved_metadata);
                    }
                    json!({"success":true,"ws_token":"fixture-token","user":{"id":OWNER}})
                }
                ("POST", p) if p == format!("/v1/projects/{PROJECT}/sources/source/requests") => {
                    assert!(approve);
                    let text = openmates_sdk::crypto::decrypt_combined(
                        body["encrypted_envelope"].as_str().unwrap(),
                        &[2; 32],
                    )
                    .unwrap();
                    let plain: Value = serde_json::from_str(&text).unwrap();
                    assert_eq!(plain["operation"], "create_file");
                    assert_eq!(plain["arguments"]["chat_id"], CHAT);
                    let mutation = &plain["arguments"]["mutation"];
                    assert_eq!(mutation["path"], "workflows/updated.workflow.yml");
                    assert_eq!(mutation["expected_base"], Value::Null);
                    saved_content = mutation["content"].as_str().unwrap().into();
                    assert!(saved_content.contains("Updated"));
                    assert!(!body.to_string().contains("folder_path"));
                    let identity = Identity {
                        owner_id: OWNER.into(),
                        context_type: None,
                        context_id: None,
                        project_id: PROJECT.into(),
                        source_id: "source".into(),
                        source_session_id: "source-session".into(),
                        requesting_client_id: body["requesting_client_id"].as_str().unwrap().into(),
                        host_member_id: None,
                        host_device_id: None,
                        requester_member_id: None,
                        requester_device_id: None,
                        key_epoch: 1,
                    };
                    let source = HandshakeState::new(&[2; 32], identity, Role::Source).unwrap();
                    let handshake = source.handshake();
                    let requester: Handshake =
                        serde_json::from_value(plain["requester_handshake"].clone()).unwrap();
                    let mut channel = source.finish(&requester).unwrap();
                    let payload = json!({"ok":true,"result":{"status":if remote_status=="version-changed"{"completed"}else{remote_status}}});
                    let envelope = channel
                        .seal(
                            body["request_id"].as_str().unwrap(),
                            payload.to_string().as_bytes(),
                        )
                        .unwrap();
                    sealed =
                        Some(json!({"source_handshake":handshake,"envelope":envelope}).to_string());
                    json!({"source_session_id":"source-session","key_epoch":1})
                }
                ("GET", p)
                    if p.starts_with(&format!(
                        "/v1/projects/{PROJECT}/sources/source/requests/"
                    )) =>
                {
                    json!({"status":"completed","encrypted_envelope":sealed.take().unwrap()})
                }
                ("PATCH", p) if p == format!("/v1/projects/{PROJECT}/items/{ITEM}") => {
                    assert!(!body.to_string().contains("private extra"));
                    let text = openmates_sdk::crypto::decrypt_combined(
                        body["encrypted_metadata"].as_str().unwrap(),
                        &[2; 32],
                    )
                    .unwrap();
                    saved_metadata = serde_json::from_str(&text).unwrap();
                    assert_eq!(saved_metadata["legacy"]["preserve"], "private extra");
                    if approve && remote_status == "completed" {
                        assert_eq!(saved_metadata["remote_file_status"], "saved");
                        assert_eq!(
                            saved_metadata["remote_workflow_file"]["saved_content"],
                            saved_content
                        );
                        assert_eq!(
                            saved_metadata["remote_workflow_file"]["base_hash"],
                            digest(&saved_content)
                        );
                    } else if remote_status == "version-changed" {
                        assert_eq!(saved_metadata["remote_file_status"], "conflict");
                        assert_eq!(
                            saved_metadata["remote_file_error"],
                            "workflow_version_changed"
                        );
                        assert_eq!(
                            saved_metadata["remote_workflow_file"]["base_hash"],
                            digest(&saved_content)
                        );
                    } else {
                        assert_ne!(saved_metadata["remote_file_status"], "saved");
                        assert!(
                            saved_metadata["remote_workflow_file"]
                                .get("base_hash")
                                .is_none()
                        );
                    }
                    if deny_metadata {
                        reply(
                            &mut socket,
                            "500 Internal Server Error",
                            json!({"detail":"fixture"}),
                        )
                        .await;
                    } else {
                        reply(&mut socket, "200 OK", json!({"item":{}})).await;
                    }
                    return (lines, saved_metadata);
                }
                _ => panic!("unexpected synthetic route {method} {path}"),
            };
            reply(&mut socket, "200 OK", response).await;
        }
    });
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("workflow.yml");
    std::fs::write(&path, "title: Updated\n").unwrap();
    let mut invocation = invocation(path.to_str().unwrap(), true);
    invocation.flags.insert("yes".into(), json!(approve));
    if slug {
        invocation.flags.insert("slug".into(), json!("replacement"));
    }
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        super::super::execute(&invocation, &mut client(&api), CancellationToken::new()),
    )
    .await
    .unwrap();
    let (lines, metadata) = tokio::time::timeout(std::time::Duration::from_secs(2), server)
        .await
        .unwrap()
        .unwrap();
    (result, lines, metadata)
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,workflows.authoring.atomic-update,chats.persistence.client-encrypted
#[tokio::test]
async fn native_update_saves_only_after_authenticated_host_result_and_encrypted_metadata_ack() {
    let (result, lines, metadata) = run_case("completed", false, true, false).await;
    let output = result.ok().unwrap();
    let text = output.stdout;
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["remote_file_saves"][0]["status"], "saved");
    assert!(value["validation"]["diagnostics"].is_array());
    assert_eq!(
        metadata["remote_workflow_file"]["workflow_version_id"],
        "version-2"
    );
    assert_eq!(
        lines
            .iter()
            .filter(|line| line.starts_with("POST") && line.contains("/yaml "))
            .count(),
        1
    );
    assert_eq!(
        lines
            .iter()
            .filter(|line| line.starts_with("POST") && line.contains("/requests "))
            .count(),
        1
    );
    assert!(!text.contains("private extra"));
    assert!(!text.contains("saved_content"));
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,workflows.authoring.atomic-update
#[tokio::test]
async fn queued_and_conflicting_remote_results_are_never_announced_saved() {
    for state in ["queued", "conflict", "failed"] {
        let (result, _, metadata) = run_case(state, false, true, false).await;
        assert!(result.is_ok());
        assert_eq!(
            metadata["remote_file_status"],
            if state == "queued" { "pending" } else { state }
        );
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.authoritative-enforcement
#[tokio::test]
async fn json_without_yes_leaves_approval_pending_without_approval_or_mutation_request() {
    let (result, lines, metadata) = run_case("completed", false, false, false).await;
    assert!(result.is_ok());
    assert_eq!(metadata["remote_file_error"], "write_approval_required");
    assert!(
        !lines
            .iter()
            .any(|line| line.contains("write-approvals") || line.contains("/requests"))
    );
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,workflows.authoring.atomic-update
#[tokio::test]
async fn metadata_patch_failure_does_not_return_a_success_output_or_retry() {
    let (result, lines, _) = run_case("completed", true, true, false).await;
    assert!(result.is_err());
    assert_eq!(
        lines
            .iter()
            .filter(|line| line.starts_with("PATCH"))
            .count(),
        1
    );
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.slugs.local-resolution-id-transport
#[tokio::test]
async fn optional_slug_patch_uses_existing_encrypted_wire_before_bound_file_sync() {
    let (result, lines, _) = run_case("completed", false, true, true).await;
    let value: Value = serde_json::from_str(&result.ok().unwrap().stdout).unwrap();
    assert_eq!(value["workflow"]["slug"], "replacement");
    let slug = lines
        .iter()
        .position(|line| line.starts_with(&format!("PATCH /v1/workflows/{FLOW} ")))
        .unwrap();
    let projects = lines
        .iter()
        .position(|line| line.starts_with("GET /v1/projects "))
        .unwrap();
    assert!(slug < projects);
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.authoritative-enforcement
#[tokio::test]
async fn cancelled_and_missing_file_refuse_before_any_remote_effect() {
    let cancel = CancellationToken::new();
    cancel.cancel();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("workflow.yml");
    std::fs::write(&path, "title: Fixture\n").unwrap();
    let error = execute(
        &invocation(path.to_str().unwrap(), true),
        &mut client("http://127.0.0.1:1"),
        cancel,
    )
    .await;
    assert!(matches!(error, Err(CliError::Client(Error::Cancelled))));
    assert!(
        execute(
            &invocation(directory.path().join("absent.yml").to_str().unwrap(), true),
            &mut client("http://127.0.0.1:1"),
            CancellationToken::new()
        )
        .await
        .is_err()
    );
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.authoritative-enforcement
#[tokio::test]
async fn missing_or_offline_source_retains_pending_binding_without_remote_creation() {
    for kind in ["missing-source", "offline"] {
        let (result, lines, metadata) = run_case(kind, false, true, false).await;
        assert!(result.is_ok());
        assert_eq!(metadata["remote_file_status"], "pending");
        assert_eq!(
            metadata["remote_file_error"],
            if kind == "missing-source" {
                "source_selection_required"
            } else {
                "source_offline"
            }
        );
        assert!(
            !lines
                .iter()
                .any(|line| line.starts_with("POST") && line.contains("/requests "))
        );
        assert!(metadata["remote_workflow_file"].get("base_hash").is_none());
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,workflows.authoring.atomic-update
#[tokio::test]
async fn concurrent_version_change_keeps_confirmed_remote_hash_but_reports_conflict() {
    let (result, _, metadata) = run_case("version-changed", false, true, false).await;
    assert!(result.is_ok());
    assert_eq!(metadata["remote_file_status"], "conflict");
    assert_eq!(
        metadata["remote_workflow_file"]["workflow_version_id"],
        "version-2"
    );
    assert!(metadata["remote_workflow_file"]["base_hash"].is_string());
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[tokio::test]
async fn actual_fresh_session_denial_cannot_publish_saved_or_persist_metadata() {
    let (result, lines, metadata) = run_case("auth-denied", false, true, false).await;
    assert!(result.is_err());
    assert!(metadata.is_null());
    assert!(
        !lines
            .iter()
            .any(|line| line.starts_with("PATCH") || line.contains("/requests "))
    );
}
