// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::tasks::tests::client;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
pub(in crate::work::projects) const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";

fn raw() -> Value {
    encode_create(
        &ProjectCreate {
            project_id: Some(PROJECT.into()),
            name: "Private Project".into(),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &[8; 32],
        &[7; 32],
        None,
    )
    .unwrap()
}
async fn read_request(socket: &mut tokio::net::TcpStream) -> String {
    let mut buf = Vec::new();
    loop {
        let mut bytes = [0; 8192];
        let n = socket.read(&mut bytes).await.unwrap();
        assert!(n > 0);
        buf.extend_from_slice(&bytes[..n]);
        if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
            let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
            let size = head
                .lines()
                .find_map(|l| {
                    l.strip_prefix("content-length:")
                        .and_then(|n| n.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if buf.len() >= end + 4 + size {
                return String::from_utf8(buf).unwrap();
            }
        }
    }
}
/// A loopback relay plus simulated source host: it opens the requester's
/// Project-key envelope, completes the authenticated handshake as the source
/// and seals `reply` for the exact request.
pub(in crate::work::projects) async fn host(
    reply: Value,
) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        let mut pending: Option<(String, String, Handshake)> = None;
        let mut polls = 0;
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let request = read_request(&mut socket).await;
            let line = request.lines().next().unwrap().to_owned();
            let body = request.split("\r\n\r\n").nth(1).unwrap_or("");
            let (status, response) = if line
                .starts_with(&format!("GET /v1/projects/{PROJECT}/sources "))
            {
                (
                    200,
                    json!({"sources":[{"source_id":"src","status":"connected","source_session_id":"sess","key_epoch":1,"capabilities":["read","run_command"]}]}),
                )
            } else if line.starts_with(&format!("GET /v1/projects/{PROJECT} ")) {
                (200, json!({"project":raw()}))
            } else if line.starts_with(&format!("POST /v1/projects/{PROJECT}/write-approvals ")) {
                (200, json!({"stored":true}))
            } else if line.starts_with("POST /v1/auth/session ") {
                (
                    200,
                    json!({"success":true,"ws_token":"synthetic","user":{"id":"owner"}}),
                )
            } else if line.starts_with(&format!(
                "POST /v1/projects/{PROJECT}/sources/src/requests "
            )) {
                let input: Value = serde_json::from_str(body).unwrap();
                let opened: Value = serde_json::from_str(
                    &crypto::decrypt_combined(
                        input["encrypted_envelope"].as_str().unwrap(),
                        &[8; 32],
                    )
                    .unwrap(),
                )
                .unwrap();
                assert_eq!(opened["operation"], input["operation"]);
                let handshake =
                    Handshake::from_json(opened["requester_handshake"].to_string().as_bytes())
                        .unwrap();
                pending = Some((
                    input["request_id"].as_str().unwrap().into(),
                    input["requesting_client_id"].as_str().unwrap().into(),
                    handshake,
                ));
                (200, json!({"source_session_id":"sess","key_epoch":1}))
            } else if line.starts_with(&format!("GET /v1/projects/{PROJECT}/sources/src/requests/"))
            {
                polls += 1;
                if polls == 1 {
                    (404, json!({"detail":"request_not_found"}))
                } else {
                    let (request_id, client_id, handshake) = pending.take().unwrap();
                    let identity = Identity {
                        owner_id: "owner".into(),
                        context_type: None,
                        context_id: None,
                        project_id: PROJECT.into(),
                        source_id: "src".into(),
                        source_session_id: "sess".into(),
                        requesting_client_id: client_id,
                        host_member_id: None,
                        host_device_id: None,
                        requester_member_id: None,
                        requester_device_id: None,
                        key_epoch: 1,
                    };
                    let source = HandshakeState::new(&[8; 32], identity, Role::Source).unwrap();
                    let source_handshake = source.handshake();
                    let mut session = source.finish(&handshake).unwrap();
                    let sealed = session
                        .seal(&request_id, reply.to_string().as_bytes())
                        .unwrap();
                    let envelope =
                        json!({"source_handshake":source_handshake,"envelope":sealed}).to_string();
                    (
                        200,
                        json!({"status":"completed","encrypted_envelope":envelope}),
                    )
                }
            } else {
                panic!("unexpected request {line}");
            };
            requests.push(request);
            let response = response.to_string();
            socket.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}", response.len()).as_bytes()).await.unwrap();
            if status == 200 && line.contains("/requests/") {
                return requests;
            }
        }
    });
    (api, handle)
}

#[tokio::test]
async fn read_text_round_trips_through_the_authenticated_source_session() {
    let (api, server) =
        host(json!({"ok":true,"result":{"content":"fn main() {}\n","path":"src/main.rs"}})).await;
    let mut c = client(&api);
    let value = c
        .projects()
        .source_file_operation(
            PROJECT,
            None,
            ProjectFileOperation::ReadText {
                path: "src/main.rs".into(),
            },
        )
        .await
        .unwrap();
    assert_eq!(
        value,
        json!({"project_id":PROJECT,"source_id":"src","result":{"content":"fn main() {}\n","path":"src/main.rs"}})
    );
    let requests = server.await.unwrap();
    assert!(
        !requests
            .iter()
            .any(|r| r.contains("src/main.rs") && r.starts_with("POST")),
        "the path stays inside the encrypted envelope"
    );
}

#[tokio::test]
async fn source_errors_keep_npm_codes_and_messages() {
    let (api, _server) = host(json!({"ok":false,"error":"protected_path"})).await;
    let mut c = client(&api);
    let error = c
        .projects()
        .source_file_operation(
            PROJECT,
            None,
            ProjectFileOperation::List {
                path: ".".into(),
                depth: 1,
            },
        )
        .await
        .unwrap_err();
    assert_eq!(
        error,
        ProjectRequesterError::Remote {
            code: "protected_path".into(),
            message: "The requested path is protected or ignored.".into()
        }
    );
    assert!(safe_relative_path("../x").is_err() && safe_relative_path("/abs").is_err());
    assert_eq!(safe_relative_path("a\\b").unwrap(), "a/b");
    let sources = [
        json!({"source_id":"a","status":"connected"}),
        json!({"source_id":"b","status":"connected"}),
    ];
    assert!(
        matches!(select_source(&sources, None), Err(ProjectRequesterError::Remote { code, .. }) if code == "source_selection_required")
    );
    assert!(
        matches!(select_source(&sources, Some("c")), Err(ProjectRequesterError::Remote { code, .. }) if code == "source_not_found")
    );
    assert_eq!(
        select_source(&sources[..1], None).unwrap()["source_id"],
        "a"
    );
}
