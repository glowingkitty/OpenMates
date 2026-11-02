// contract-test: supporting surface=cli assertions=tasks.content.client-encrypted,tasks.lifecycle.visible
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::{WebSocketStream, tungstenite::Message as Frame};
const TASK: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const USER: &str = "33333333-3333-4333-8333-333333333333";
const JOB: &str = "task-update-job-44444444-4444-4444-8444-444444444444";
const OWNER: &str = "55555555-5555-4555-8555-555555555555";
type ServerSocket = WebSocketStream<tokio::net::TcpStream>;
fn client(api: &str) -> Client {
    let mut client = Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    client.user = json!({"id":OWNER});
    client
}
fn summary(revision: u64) -> Value {
    json!({"job_id":JOB,"task_id":TASK,"chat_id":CHAT,"revision":revision,"task_key_version":1,"expires_at":now_ms()/1000+120})
}
fn jobs(revision: u64) -> BTreeMap<String, Value> {
    BTreeMap::from([(JOB.into(), summary(revision))])
}
fn events() -> Vec<Value> {
    vec![
        json!({"event_id":"event-1","task_id":TASK,"chat_id":CHAT,"message_id":USER,"event_type":"created","title":"Private Task","created_at":now_ms()/1000,"task_update_job_id":JOB}),
    ]
}
fn claim(revision: u64) -> Value {
    json!({"job_id":JOB,"task_id":TASK,"chat_id":CHAT,"message_id":USER,"operation":if revision==0{"create"}else{"update"},"state":"LEASED","lease_token":"opaque_lease-token","lease_generation":2,"lease_expires_at":now_ms()/1000+60,"expected_task_version":revision,"task_key_version":1,"private_patch":{"title":"Private Task","description":"Private details"},"safe_metadata":{"status":"todo","primary_chat_id":CHAT,"updated_at":now_ms()/1000}})
}
fn raw_task(version: u64) -> Value {
    json!({"task_id":TASK,"version":version,"updated_at":42,"encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"key_wrappers":[{"key_type":"master","encrypted_task_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap()}],"encrypted_title":crypto::encrypt_combined("Private Task",&[9;32]).unwrap(),"encrypted_description":crypto::encrypt_combined("Private details",&[9;32]).unwrap(),"linked_project_ids":[],"primary_chat_id":CHAT,"status":"todo","priority":0})
}
async fn sockets() -> (Socket, ServerSocket) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        tokio_tungstenite::accept_async(stream).await.unwrap()
    });
    let (stream, _) = tokio_tungstenite::connect_async(format!("ws://{addr}"))
        .await
        .unwrap();
    (
        super::super::transport::test_socket(stream),
        server.await.unwrap(),
    )
}
async fn receive(ws: &mut ServerSocket) -> Value {
    serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap()
}
async fn reply(ws: &mut ServerSocket, kind: &str, request: &Value, mut payload: Value) {
    payload["request_id"] = request["payload"]["request_id"].clone();
    ws.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}
async fn event_acks(ws: &mut ServerSocket) {
    let system = receive(ws).await;
    assert_eq!(system["type"], "chat_system_message_added");
    assert_eq!(system["payload"]["message"]["task_update_job_id"], JOB);
    assert!(
        crypto::decrypt_combined(
            system["payload"]["message"]["encrypted_content"]
                .as_str()
                .unwrap(),
            &[8; 32]
        )
        .unwrap()
        .contains("Private Task")
    );
    reply(
        ws,
        "system_message_confirmed",
        &system,
        json!({"chat_id":CHAT,"message_id":system["payload"]["message"]["message_id"]}),
    )
    .await;
    let confirm = receive(ws).await;
    assert_eq!(confirm["type"], "task_update_job_event_confirmed");
    reply(
        ws,
        "task_update_job_event_confirmed",
        &confirm,
        json!({"job_id":JOB,"task_id":TASK,"state":"TERMINAL"}),
    )
    .await;
}
async fn task_http(raw: Value) -> (String, tokio::task::JoinHandle<String>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = vec![];
        loop {
            let mut chunk = [0; 4096];
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        let body = json!({"task":raw}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        String::from_utf8(bytes).unwrap()
    });
    (api, server)
}
async fn readback_http(
    tamper: bool,
) -> (
    String,
    tokio::sync::oneshot::Sender<Value>,
    tokio::task::JoinHandle<Vec<String>>,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (tx, rx) = tokio::sync::oneshot::channel::<Value>();
    let server = tokio::spawn(async move {
        let mut canonical = rx.await.unwrap();
        canonical["hashed_user_id"] = json!(crate::work::hash(OWNER));
        canonical["linked_project_hashes"] = json!([]);
        let original_version = canonical["version"].as_u64().unwrap();
        canonical["version"] = json!(if original_version == 1 {
            1
        } else {
            original_version + 1
        });
        if tamper {
            let key = key_from_bytes(
                &crypto::decrypt_bytes(canonical["encrypted_task_key"].as_str().unwrap(), &[7; 32])
                    .unwrap(),
            )
            .unwrap();
            canonical["encrypted_title"] =
                json!(crypto::encrypt_combined("Concurrent private write", &key).unwrap());
        }
        let wrappers = canonical["key_wrappers"].clone();
        let mut requests = vec![];
        for response in [json!({"task":canonical}), json!({"key_wrappers":wrappers})] {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            loop {
                let mut chunk = [0; 4096];
                let n = stream.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                    break;
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            let body = response.to_string();
            stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, tx, server)
}
#[tokio::test]
async fn create_encrypts_task_before_persist_and_confirms_event_after_receipt_even_on_cancel() {
    let (api, tx, http) = readback_http(false).await;
    let mut client = client(&api);
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    let (socket, mut server) = sockets().await;
    let mut socket = socket;
    let server = tokio::spawn(async move {
        let request = receive(&mut server).await;
        assert_eq!(request["type"], "task_update_job_claim");
        reply(&mut server, "task_update_job_claimed", &request, claim(0)).await;
        let persist = receive(&mut server).await;
        assert_eq!(persist["type"], "task_update_job_persist");
        assert!(!persist.to_string().contains("Private"));
        let task = &persist["payload"]["encrypted_task_payload"];
        let key = key_from_bytes(
            &crypto::decrypt_bytes(task["encrypted_task_key"].as_str().unwrap(), &[7; 32]).unwrap(),
        )
        .unwrap();
        assert_ne!(*key, [7; 32]);
        assert_eq!(
            crypto::decrypt_combined(task["encrypted_title"].as_str().unwrap(), &key).unwrap(),
            "Private Task"
        );
        let wrapper = task["key_wrappers"]
            .as_array()
            .unwrap()
            .iter()
            .find(|w| w["key_type"] == "chat")
            .unwrap();
        assert_eq!(
            &*crypto::decrypt_bytes(wrapper["encrypted_task_key"].as_str().unwrap(), &[8; 32])
                .unwrap(),
            key.as_ref()
        );
        tx.send(task.clone()).unwrap();
        reply(
            &mut server,
            "task_update_job_persisted",
            &persist,
            json!({"job_id":JOB,"task_id":TASK,"state":"TASK_PERSISTED"}),
        )
        .await;
        cancel.cancel();
        event_acks(&mut server).await;
    });
    let handled = client
        .persist_task_jobs(
            &mut socket,
            &jobs(0),
            &events(),
            Some((CHAT, &[8; 32], USER)),
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert!(handled.contains(JOB));
    server.await.unwrap();
    let requests = http.await.unwrap();
    assert_eq!(requests.len(), 2);
    assert!(
        requests
            .iter()
            .all(|request| request.starts_with("GET /v1/user-tasks/"))
    );
    assert_eq!(
        client
            .request(Method::POST, "/v1/user-tasks", Some(json!({})))
            .await,
        Err(Error::Cancelled)
    );
}
#[tokio::test]
async fn receipt_with_concurrent_private_ciphertext_cannot_confirm_the_event() {
    let (api, tx, http) = readback_http(true).await;
    let mut client = client(&api);
    let (mut socket, mut server) = sockets().await;
    let server = tokio::spawn(async move {
        let request = receive(&mut server).await;
        reply(&mut server, "task_update_job_claimed", &request, claim(0)).await;
        let persist = receive(&mut server).await;
        tx.send(persist["payload"]["encrypted_task_payload"].clone())
            .unwrap();
        reply(
            &mut server,
            "task_update_job_persisted",
            &persist,
            json!({"job_id":JOB,"task_id":TASK,"state":"TASK_PERSISTED"}),
        )
        .await;
        assert!(
            tokio::time::timeout(Duration::from_millis(250), server.next())
                .await
                .is_err()
        );
    });
    assert_eq!(
        client
            .persist_task_jobs(
                &mut socket,
                &jobs(0),
                &events(),
                Some((CHAT, &[8; 32], USER)),
                &CancellationToken::new()
            )
            .await,
        Err(Error::Conflict)
    );
    http.await.unwrap();
    server.await.unwrap();
}
#[tokio::test]
async fn persisted_recovery_reads_canonical_task_and_never_repeats_task_ciphertext() {
    let (api, http) = task_http(raw_task(4)).await;
    let mut client = client(&api);
    let (mut socket, mut server) = sockets().await;
    let server = tokio::spawn(async move {
        let request = receive(&mut server).await;
        let mut claim = claim(3);
        claim["state"] = json!("TASK_PERSISTED");
        claim["lease_expires_at"] = json!(1);
        claim["safe_metadata"]["updated_at"] = json!(42);
        reply(&mut server, "task_update_job_claimed", &request, claim).await;
        event_acks(&mut server).await;
    });
    let handled = client
        .persist_task_jobs(
            &mut socket,
            &jobs(3),
            &events(),
            Some((CHAT, &[8; 32], USER)),
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert!(handled.contains(JOB));
    server.await.unwrap();
    assert!(
        http.await
            .unwrap()
            .starts_with(&format!("GET /v1/user-tasks/{TASK} "))
    );
}
#[tokio::test]
async fn events_from_another_turn_never_authorize_a_claim() {
    let mut client = client("http://127.0.0.1:1");
    let (mut socket, _server) = sockets().await;
    let mut events = events();
    events[0]["message_id"] = json!("another-turn");
    assert_eq!(
        client
            .persist_task_jobs(
                &mut socket,
                &jobs(0),
                &events,
                Some((CHAT, &[8; 32], USER)),
                &CancellationToken::new()
            )
            .await,
        Err(Error::Forbidden)
    );
    assert!(
        client
            .persist_task_jobs(
                &mut socket,
                &jobs(0),
                &[],
                Some((CHAT, &[8; 32], USER)),
                &CancellationToken::new()
            )
            .await
            .unwrap()
            .is_empty()
    );
}
#[tokio::test]
async fn lost_task_receipt_replays_only_the_event_without_regenerating_task_ciphertext() {
    let mut first = client("http://127.0.0.1:1");
    let (mut socket, mut server) = sockets().await;
    let server = tokio::spawn(async move {
        let request = receive(&mut server).await;
        reply(&mut server, "task_update_job_claimed", &request, claim(0)).await;
        let persisted = receive(&mut server).await;
        assert_eq!(persisted["type"], "task_update_job_persist");
        let saved = persisted["payload"]["encrypted_task_payload"].clone();
        server.close(None).await.unwrap();
        saved
    });
    assert_eq!(
        first
            .persist_task_jobs(
                &mut socket,
                &jobs(0),
                &events(),
                Some((CHAT, &[8; 32], USER)),
                &CancellationToken::new()
            )
            .await,
        Err(Error::Offline)
    );
    let saved = server.await.unwrap();
    let (api, http) = task_http(saved.clone()).await;
    let mut fresh = client(&api);
    let (mut socket, mut server) = sockets().await;
    let server = tokio::spawn(async move {
        let request = receive(&mut server).await;
        let mut recovered = claim(0);
        recovered["state"] = json!("TASK_PERSISTED");
        recovered["lease_expires_at"] = json!(1);
        recovered["safe_metadata"]["updated_at"] = saved["updated_at"].clone();
        reply(&mut server, "task_update_job_claimed", &request, recovered).await;
        event_acks(&mut server).await;
    });
    assert!(
        fresh
            .persist_task_jobs(
                &mut socket,
                &jobs(0),
                &events(),
                Some((CHAT, &[8; 32], USER)),
                &CancellationToken::new()
            )
            .await
            .unwrap()
            .contains(JOB)
    );
    http.await.unwrap();
    server.await.unwrap();
}
#[test]
fn canonical_existing_event_is_reused_and_inconsistent_recovery_is_refused() {
    let mut client = client("http://127.0.0.1:1");
    let claim = TaskJobClaim::parse(
        &claim(3),
        &summary(3),
        None,
        Some(CHAT),
        Some(USER),
        now_ms() / 1000,
    )
    .unwrap();
    let cipher = crypto::encrypt_combined("Private Task created", &[8; 32]).unwrap();
    client.history.insert(CHAT.into(),vec![json!({"message_id":"task-event-original-random","chat_id":CHAT,"role":"system","user_message_id":USER,"task_update_job_id":JOB,"encrypted_content":cipher,"created_at":42})]);
    let reused = client.existing_task_event(&claim).unwrap().unwrap();
    assert_eq!(reused["message_id"], "task-event-original-random");
    assert_eq!(reused["encrypted_content"], cipher);
    let mut current = json!({"task_id":TASK,"version":4,"title":"Private Task","description":"Private details","status":"todo","primary_chat_id":CHAT,"updated_at":claim.safe_metadata["updated_at"]});
    verify_persisted_claim(&claim, &current).unwrap();
    current["title"] = json!("Concurrent private write");
    assert_eq!(
        verify_persisted_claim(&claim, &current),
        Err(Error::Conflict)
    );
    current["version"] = json!(5);
    assert_eq!(
        verify_persisted_claim(&claim, &current),
        Err(Error::Conflict)
    );
    client.history.get_mut(CHAT).unwrap()[0]["user_message_id"] = json!("another-user-message");
    assert_eq!(client.existing_task_event(&claim), Err(Error::Forbidden));
}
