use super::*;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
type Requests = Arc<Mutex<Vec<(String, Value)>>>;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
fn metadata() -> Value {
    json!({"app_id":"web","skill_id":"search","name":"Search","description":"Search the web","execution_available":true,"defaults":{},"input_schema":{"type":"object","required":["requests"],"additionalProperties":false,"properties":{"requests":{"type":"array","minItems":1,"items":{"type":"object","required":["query"],"properties":{"query":{"type":"string","minLength":1},"model":{"type":"string"}}}}}}})
}
fn fields() -> Value {
    json!({"app":"web","skill":"search","input":{"requests":[{"query":"fictional-sensitive-query"}]}})
}
async fn fixture(
    async_job: bool,
    cancel_on_dispatch: bool,
    fail: bool,
) -> (
    Client,
    Requests,
    tokio::task::JoinHandle<()>,
    CancellationToken,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let requests: Requests = Arc::new(Mutex::new(vec![]));
    let recorded = requests.clone();
    let cancel = CancellationToken::new();
    let cancellation = cancel.clone();
    let server = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            let mut part = [0u8; 4096];
            let (headers_end, length) = loop {
                let read = socket.read(&mut part).await.unwrap();
                if read == 0 {
                    return;
                }
                bytes.extend_from_slice(&part[..read]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                    let length = headers
                        .lines()
                        .filter_map(|l| l.split_once(':'))
                        .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                        .map(|(_, v)| v.trim().parse::<usize>().unwrap())
                        .unwrap_or(0);
                    break (end + 4, length);
                }
            };
            while bytes.len() < headers_end + length {
                let read = socket.read(&mut part).await.unwrap();
                if read == 0 {
                    return;
                }
                bytes.extend_from_slice(&part[..read]);
            }
            let headers = std::str::from_utf8(&bytes[..headers_end]).unwrap();
            let path = headers
                .lines()
                .next()
                .unwrap()
                .split_whitespace()
                .nth(1)
                .unwrap()
                .to_owned();
            let body = if length == 0 {
                Value::Null
            } else {
                serde_json::from_slice(&bytes[headers_end..headers_end + length]).unwrap()
            };
            recorded.lock().unwrap().push((path.clone(), body.clone()));
            let response = match path.as_str() {
                "/v1/apps/web/skills/search/details" => metadata(),
                "/v1/auth/session" => {
                    json!({"success":true,"ws_token":"synthetic-token","user":{"id":OWNER}})
                }
                "/v1/apps/workspace/results" => {
                    json!({"success":true,"root_embed_id":body["root_embed_id"]})
                }
                "/v1/apps/web/skills/search" => {
                    if cancel_on_dispatch {
                        cancellation.cancel()
                    }
                    if fail {
                        json!({"success":false,"error":"SYNTHETIC PRIVATE FAILURE BODY"})
                    } else if async_job {
                        json!({"success":true,"data":{"task_id":"task-1","status":"processing"}})
                    } else {
                        json!({"success":true,"data":{"results":[{"title":"A real fixture result","url":"https://example.invalid"}]}})
                    }
                }
                "/v1/tasks/task-1" => {
                    json!({"task_id":"task-1","status":"completed","result":{"results":[{"title":"Async fixture result","url":"https://example.invalid/async"}]}})
                }
                _ => panic!("unexpected synthetic endpoint"),
            };
            let body = response.to_string();
            let header = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            socket.write_all(header.as_bytes()).await.unwrap();
            socket.write_all(body.as_bytes()).await.unwrap();
        }
    });
    let base = format!("http://{address}");
    let session = Session {
        api_url: base.clone(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::new(),
        ws_token: Some("synthetic-token".into()),
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&base, Some(session)).unwrap();
    client.user = json!({"id":OWNER});
    client.set_operation_cancel(cancel.clone());
    (client, requests, server, cancel)
}

#[test]
fn canonical_metadata_schema_and_automatic_routing_controls() {
    let item = skill_item("web", "search", metadata()).unwrap();
    assert_eq!(item.fields["app"], "web");
    assert_eq!(item.fields["skill_id"], "search");
    assert_eq!(item.fields["confirmation_required"], true);
    let mut sandbox = metadata();
    sandbox["execution_mode"] = json!("sandbox");
    assert_eq!(
        skill_item("web", "search", sandbox).unwrap().fields["execution_available"],
        false
    );
    let schema = &item.fields["input_schema"];
    assert!(validate_schema(schema, schema, &fields()["input"], 0));
    assert!(!validate_schema(
        schema,
        schema,
        &json!({"requests":[{"query":42}]}),
        0
    ));
    assert!(!validate_schema(schema, schema, &json!({"requests":[]}), 0));
    assert!(!validate_schema(
        schema,
        schema,
        &json!({"requests":[{}]}),
        0
    ));
    assert_eq!(
        automatic_input(&json!({"requests":[{"query":"hello","model":"auto"}]}), 0).unwrap(),
        json!({"requests":[{"query":"hello"}]})
    );
    assert!(automatic_input(&json!({"model":"provider/model"}), 0).is_err());
    assert!(automatic_input(&json!({"requests":[{"provider":"forced"}]}), 0).is_err());
    assert_eq!(
        automatic_input(
            &json!({"query":"typed value","pii_mappings":{"original":"must remain local"}}),
            0
        )
        .unwrap(),
        json!({"query":"typed value"})
    );
    assert!(task_ids(&json!({"data":{"task_ids":["task-1","task-1"]}})).is_err());
    assert!(task_ids(&json!({"task_id":"//another-authority"})).is_err());
}

#[tokio::test]
async fn synchronous_skill_keeps_private_retention_encrypted_and_returns_real_content() {
    let (mut client, requests, server, _) = fixture(false, false, false).await;
    let item = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        item.fields["content"]["results"][0]["title"],
        "A real fixture result"
    );
    let requests = requests.lock().unwrap();
    let dispatch = requests
        .iter()
        .position(|(p, _)| p == "/v1/apps/web/skills/search")
        .unwrap();
    let saved = requests
        .iter()
        .position(|(p, _)| p == "/v1/apps/workspace/results")
        .unwrap();
    assert!(saved < dispatch);
    assert_eq!(requests[dispatch].1, fields()["input"]);
    for (path, body) in requests
        .iter()
        .filter(|(path, _)| path == "/v1/apps/workspace/results")
    {
        assert!(
            !body.to_string().contains("fictional-sensitive-query"),
            "{path}"
        );
        let key = key_from_bytes(
            &crypto::decrypt_bytes(text(body, "encrypted_embed_key"), &[7; 32]).unwrap(),
        )
        .unwrap();
        let content =
            crypto::decrypt_combined(text(&body["embeds"][0], "encrypted_content"), &key).unwrap();
        assert!(content.contains("fictional-sensitive-query"));
    }
    drop(requests);
    server.abort();
}

#[tokio::test]
async fn asynchronous_skill_polls_actual_task_and_preserves_admission() {
    let (mut client, requests, server, _) = fixture(true, false, false).await;
    let item = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        item.fields["content"]["results"][0]["title"],
        "Async fixture result"
    );
    assert!(
        requests
            .lock()
            .unwrap()
            .iter()
            .any(|(path, _)| path == "/v1/tasks/task-1")
    );
    server.abort();
}

#[tokio::test]
async fn cancellation_after_post_retains_task_receipt_without_retry_or_poll() {
    let (mut client, requests, server, _) = fixture(true, true, false).await;
    assert!(matches!(
        client.run_app_skill_with_gate(fields(), || Ok(())).await,
        Err(Error::Cancelled)
    ));
    let requests = requests.lock().unwrap();
    assert_eq!(
        requests
            .iter()
            .filter(|(path, _)| path == "/v1/apps/web/skills/search")
            .count(),
        1
    );
    assert!(
        !requests
            .iter()
            .any(|(path, _)| path.starts_with("/v1/tasks/"))
    );
    let (_, saved) = requests
        .iter()
        .rev()
        .find(|(path, _)| path == "/v1/apps/workspace/results")
        .unwrap();
    let key = key_from_bytes(
        &crypto::decrypt_bytes(text(saved, "encrypted_embed_key"), &[7; 32]).unwrap(),
    )
    .unwrap();
    let content: Value = serde_json::from_str(
        &crypto::decrypt_combined(text(&saved["embeds"][0], "encrypted_content"), &key).unwrap(),
    )
    .unwrap();
    assert_eq!(content["task_ids"], json!(["task-1"]));
    drop(requests);
    server.abort();
}

#[tokio::test]
async fn cancellation_after_synchronous_post_still_persists_the_completed_result() {
    let (mut client, requests, server, _) = fixture(false, true, false).await;
    assert!(matches!(
        client.run_app_skill_with_gate(fields(), || Ok(())).await,
        Err(Error::Cancelled)
    ));
    let requests = requests.lock().unwrap();
    let (_, saved) = requests
        .iter()
        .rev()
        .find(|(path, _)| path == "/v1/apps/workspace/results")
        .unwrap();
    assert_eq!(saved["embeds"][0]["status"], "finished");
    let key = key_from_bytes(
        &crypto::decrypt_bytes(text(saved, "encrypted_embed_key"), &[7; 32]).unwrap(),
    )
    .unwrap();
    let content: Value = serde_json::from_str(
        &crypto::decrypt_combined(text(&saved["embeds"][0], "encrypted_content"), &key).unwrap(),
    )
    .unwrap();
    assert_eq!(content["results"][0]["title"], "A real fixture result");
    drop(requests);
    server.abort();
}

#[tokio::test]
async fn enhanced_mode_and_upstream_failures_are_fail_closed_and_redacted() {
    let (mut client, requests, server, _) = fixture(false, false, true).await;
    let error = client
        .run_app_skill_with_gate(fields(), || {
            Err(Error::Invalid("Enhanced mode unavailable."))
        })
        .await
        .err()
        .unwrap();
    assert_eq!(error.to_string(), "Enhanced mode unavailable.");
    assert!(requests.lock().unwrap().is_empty());
    let error = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .err()
        .unwrap();
    assert!(!error.to_string().contains("PRIVATE FAILURE"));
    server.abort();
}
