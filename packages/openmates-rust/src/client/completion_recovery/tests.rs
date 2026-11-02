//! Pure/loopback supporting proof only; no AI/provider/product execution.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};
use tokio_tungstenite::tungstenite::Message as WsMessage;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const USER: &str = "88888888-8888-4888-8888-888888888888";
fn fixture() -> Value {
    serde_json::from_str(BACKEND_FIXTURE).unwrap()
}
fn job() -> CompletionRecoveryJob {
    let raw = &fixture()["main"];
    CompletionRecoveryJob {
        kind: CompletionRecoveryKind::Main,
        job_id: raw["job_id"].as_str().unwrap().into(),
        chat_id: CHAT.into(),
        turn_id: Some(raw["turn_id"].as_str().unwrap().into()),
        assistant_message_id: Some(raw["assistant_message_id"].as_str().unwrap().into()),
        task_id: None,
        stage: None,
        chat_key_version: 1,created_at:None,
    }
}
fn metadata_job() -> CompletionRecoveryJob {
    let raw = &fixture()["metadata"];
    CompletionRecoveryJob {
        kind: CompletionRecoveryKind::Metadata,
        job_id: raw["job_id"].as_str().unwrap().into(),
        chat_id: CHAT.into(),
        turn_id: None,
        assistant_message_id: None,
        task_id: Some(raw["task_id"].as_str().unwrap().into()),
        stage: Some("initial".into()),
        chat_key_version: 1,created_at:None,
    }
}
struct State {
    selected_startup: bool,
    startup_failure: bool,
    http_paths: Vec<String>,
    row: Value,
    history: Vec<Value>,
    settled: bool,
    claims: usize,
    persists: Vec<Value>,
    frames: Vec<Value>,
    drop_ack: bool,
    lease_conflict: bool,
    deny_metadata: bool,
    metadata_terminal: bool,
    settled_jobs: std::collections::BTreeSet<String>,
    active_leases: std::collections::BTreeSet<String>,
    defer_child: bool,
}
impl State {
    fn new() -> Self {
        Self {
            selected_startup: false,
            startup_failure: false,
            http_paths: vec![],
            row: json!({"id":CHAT,"encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Synthetic chat",&[8;32]).unwrap(),"messages_v":1,"metadata_v":0,"title_v":0}),
            history: vec![
                json!({"client_message_id":USER,"chat_id":CHAT,"role":"user","encrypted_content":crypto::encrypt_combined("Synthetic prompt",&[8;32]).unwrap(),"encrypted_sender_name":crypto::encrypt_combined("User",&[8;32]).unwrap(),"created_at":1,"updated_at":1}),
            ],
            settled: false,
            claims: 0,
            persists: vec![],
            frames: vec![],
            drop_ack: false,
            lease_conflict: false,
            deny_metadata: false,
            metadata_terminal: false,
            settled_jobs: Default::default(),
            active_leases: Default::default(),
            defer_child: false,
        }
    }
}
struct Peer {
    api: String,
    state: Arc<Mutex<State>>,
    cancel: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.cancel.cancel();
        self.task.abort();
    }
}
impl Peer {
    async fn new() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let state = Arc::new(Mutex::new(State::new()));
        let shared = state.clone();
        let cancel = CancellationToken::new();
        let stopping = cancel.clone();
        let task = tokio::spawn(async move {
            loop {
                tokio::select! {_=stopping.cancelled()=>break,result=listener.accept()=>{let (socket,_)=result.unwrap();let state=shared.clone();tokio::spawn(async move{serve(socket,state).await;});}}
            }
        });
        Self {
            api,
            state,
            cancel,
            task,
        }
    }
    fn client(&self) -> Client {
        let mut client = Client::new(
            &self.api,
            Some(Session {
                api_url: self.api.clone(),
                session_id: uuid::Uuid::new_v4().to_string(),
                cookies: Default::default(),
                ws_token: Some("token".into()),
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            }),
        )
        .unwrap();
        client.set_foreground_completion_recovery(true).unwrap();
        client
    }
}
async fn serve(mut socket: TcpStream, state: Arc<Mutex<State>>) {
    let mut head = [0; 1024];
    let n = loop {
        let n = socket.peek(&mut head).await.unwrap();
        if n == 0 {
            return;
        }
        if head[..n].windows(2).any(|bytes| bytes == b"\r\n") {
            break n;
        }
        tokio::task::yield_now().await;
    };
    if String::from_utf8_lossy(&head[..n]).starts_with("GET /v1/ws?") {
        serve_ws(socket, state).await;
        return;
    }
    let mut buffer = Vec::new();
    let end = loop {
        let mut bytes = [0; 4096];
        let n = socket.read(&mut bytes).await.unwrap();
        if n == 0 {
            return;
        }
        buffer.extend_from_slice(&bytes[..n]);
        if let Some(end) = buffer.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            let header = String::from_utf8_lossy(&buffer[..end]).to_ascii_lowercase();
            let size = header
                .lines()
                .find_map(|line| {
                    line.strip_prefix("content-length:")
                        .and_then(|v| v.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if buffer.len() >= end + 4 + size {
                break end;
            }
        }
    };
    let request = String::from_utf8_lossy(&buffer[..end]);
    let path = request
        .lines()
        .next()
        .unwrap()
        .split_whitespace()
        .nth(1)
        .unwrap();
    let (status, body) = {
        let mut state = state.lock().unwrap();
        state.http_paths.push(path.to_owned());
        if path == "/v1/auth/session" {
            (
                200,
                json!({"success":true,"ws_token":"token","user":{"id":OWNER}}),
            )
        } else if path.starts_with("/v1/chats/metadata/batch") {
            if state.deny_metadata {
                (403, json!({"detail":"denied"}))
            } else {
                (200, json!({"chats":[state.row]}))
            }
        } else if path.starts_with(&format!("/v1/chats/{CHAT}/messages/window")) {
            (
                200,
                if state.selected_startup && state.history.len() > 100 {
                    let older = path.contains("direction=before");
                    let split = state.history.len() - 100;
                    let rows = if older { &state.history[..split] } else { &state.history[split..] };
                    let first = rows.first().unwrap();
                    let last = rows.last().unwrap();
                    // Match /messages/window: start_cursor is the oldest row
                    // in this page, including a nonempty terminal older page.
                    json!({"messages":rows,"has_more_before":!older,
                        "start_cursor":{"created_at":first["created_at"],"message_id":first["client_message_id"]},
                        "end_cursor":{"created_at":last["created_at"],"message_id":last["client_message_id"]}})
                } else { json!({"messages":state.history,"has_more_before":false,"next_cursor":null}) },
            )
        } else {
            panic!("unexpected synthetic recovery HTTP route {path}")
        }
    };
    let body = body.to_string();
    socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
struct CheckRecoveryCapabilities;
impl tokio_tungstenite::tungstenite::handshake::server::Callback for CheckRecoveryCapabilities {
    fn on_request(
        self,
        request: &tokio_tungstenite::tungstenite::handshake::server::Request,
        response: tokio_tungstenite::tungstenite::handshake::server::Response,
    ) -> std::result::Result<
        tokio_tungstenite::tungstenite::handshake::server::Response,
        tokio_tungstenite::tungstenite::handshake::server::ErrorResponse,
    > {
        let url = url::Url::parse(&format!("http://mock{}", request.uri())).unwrap();
        let caps = url
            .query_pairs()
            .find(|(name, _)| name == "client_capabilities")
            .unwrap()
            .1;
        assert!(caps.split(',').any(|cap| cap == "chat_metadata_recovery"));
        assert!(!caps.contains("remote_command_jobs"));
        Ok(response)
    }
}
fn iso_time(ms: u64) -> String {
    let mut days = ms / 86_400_000;
    let leap = |y| y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let mut year = 1970;
    while days >= if leap(year) { 366 } else { 365 } {
        days -= if leap(year) { 366 } else { 365 };
        year += 1;
    }
    let months = [
        31,
        if leap(year) { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let mut month = 0;
    while days >= months[month] {
        days -= months[month];
        month += 1;
    }
    format!(
        "{year:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        month + 1,
        days + 1,
        (ms / 3_600_000) % 24,
        (ms / 60_000) % 60,
        (ms / 1000) % 60,
        ms % 1000
    )
}
async fn serve_ws(socket: TcpStream, state: Arc<Mutex<State>>) {
    let mut ws = tokio_tungstenite::accept_hdr_async(socket, CheckRecoveryCapabilities)
        .await
        .unwrap();
    while let Some(Ok(WsMessage::Text(text))) = ws.next().await {
        let frame: Value = serde_json::from_str(&text).unwrap();
        let kind = frame["type"].as_str().unwrap();
        let p = &frame["payload"];
        state.lock().unwrap().frames.push(frame.clone());
        let mut outgoing = vec![];
        let mut close = false;
        {
            let mut state = state.lock().unwrap();
            match kind {
                "native_client_lifecycle" => {
                    assert_eq!(p["is_foreground"], true);
                    outgoing.push(json!({"type":"native_client_lifecycle_ack","payload":{"is_foreground":true}}));
                    if state.selected_startup {
                        let mut selected = fixture()["main"].clone(); selected["state"] = json!("AVAILABLE");
                        let mut unrelated = fixture()["main2"].clone();
                        unrelated["state"] = json!("AVAILABLE");
                        unrelated["chat_id"] = json!("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
                        outgoing.extend([
                            json!({"type":"recovery_jobs_available","payload":{"jobs":if state.settled { json!([unrelated]) } else { json!([selected,unrelated]) }}}),
                            json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}),
                            json!({"type":"recovery_outputs_discovery_complete","payload":{"status":if state.startup_failure {"failed"} else {"completed"}}}),
                        ]);
                    }
                }
                "set_active_chat" => {}
                "phased_sync_request" => {
                    let mut announced = fixture()["main"].clone();
                    announced["state"] = json!("AVAILABLE");
                    if state.defer_child {
                        outgoing.push(json!({"type":"recovery_outputs_available","payload":{"outputs":[{"record_id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee","root_chat_id":CHAT,"target_chat_id":CHAT,"turn_id":fixture()["main"]["turn_id"],"subject_id":"ffffffff-ffff-4fff-8fff-ffffffffffff","output_kind":"message","output_version":1,"chat_key_version":1}]}}));
                    }
                    outgoing.extend([json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":state.row}]}}),json!({"type":"recovery_jobs_available","payload":{"jobs":if state.settled{json!([])}else{json!([announced])}}}),json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}),json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),json!({"type":"phased_sync_complete","payload":{}})]);
                }
                "recovery_output_get" => {
                    assert!(state.defer_child);
                    close = true;
                }
                "metadata_jobs_request" => {
                    outgoing.push(json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}))
                }
                "recovery_job_claim" => {
                    state.claims += 1;
                    let first = fixture()["main"].clone();
                    let raw = if p["job_id"] == first["job_id"] {
                        first.clone()
                    } else {
                        let second = fixture()["main2"].clone();
                        assert_eq!(p["job_id"], second["job_id"]);
                        second
                    };
                    let settled = state.settled_jobs.contains(p["job_id"].as_str().unwrap())
                        || (p["job_id"] == first["job_id"] && state.settled);
                    if !settled
                        && ((state.lease_conflict && p["job_id"] == first["job_id"])
                            || state.active_leases.contains(p["job_id"].as_str().unwrap()))
                    {
                        outgoing.push(json!({"type":"error","payload":{"job_id":p["job_id"],"request_id":p["request_id"],"code":"lease_conflict"}}));
                    } else {
                        if !settled {
                            state
                                .active_leases
                                .insert(p["job_id"].as_str().unwrap().into());
                        }
                        outgoing.push(json!({"type":"recovery_job_claimed","payload":{"job_id":raw["job_id"],"chat_id":CHAT,"turn_id":raw["turn_id"],"assistant_message_id":raw["assistant_message_id"],"chat_key_version":1,"state":if settled{"TERMINAL"}else{"LEASED"},"lease_token":"synthetic-lease","lease_generation":state.claims,"lease_expires_at":iso_time(now_ms()+60_000),"sealed_payload":raw["sealed_payload"],"request_id":p["request_id"]}}));
                    }
                }
                "recovery_job_persist" => {
                    assert!(state.active_leases.contains(p["job_id"].as_str().unwrap()));
                    let encrypted = p["encrypted_assistant_message"].clone();
                    assert_eq!(p["expected_messages_v"], state.row["messages_v"]);
                    assert_eq!(encrypted["role"], "assistant");
                    assert!(p.get("inference_request").is_none());
                    if let Some(previous) = state
                        .persists
                        .iter()
                        .find(|row| row["client_message_id"] == encrypted["client_message_id"])
                    {
                        assert_eq!(previous, &encrypted)
                    }
                    let existed = state
                        .history
                        .iter()
                        .any(|row| row["client_message_id"] == encrypted["client_message_id"]);
                    if !existed {
                        state.history.push(encrypted.clone());
                        let version = state.row["messages_v"].as_u64().unwrap() + 1;
                        state.row["messages_v"] = json!(version);
                    }
                    state.persists.push(encrypted);
                    state.active_leases.remove(p["job_id"].as_str().unwrap());
                    state
                        .settled_jobs
                        .insert(p["job_id"].as_str().unwrap().to_owned());
                    if p["job_id"] == fixture()["main"]["job_id"] {
                        state.settled = true;
                    }
                    close = state.drop_ack;
                    outgoing.push(json!({"type":"recovery_job_persisted","payload":{"job_id":p["job_id"],"request_id":p["request_id"],"state":"TERMINAL","committed_messages_v":state.row["messages_v"]}}));
                }
                "metadata_job_claim" => {
                    let raw = fixture()["metadata"].clone();
                    outgoing.push(json!({"type":"metadata_job_claimed","payload":{"job_id":raw["job_id"],"chat_id":CHAT,"task_id":raw["task_id"],"stage":"initial","chat_key_version":1,"state":if state.metadata_terminal{"TERMINAL"}else{"AVAILABLE"},"sealed_payload":raw["sealed_payload"],"encrypted_fields":raw["encrypted_fields"],"request_id":p["request_id"]}}));
                }
                "metadata_job_persist" => {
                    for (field, value) in p["encrypted_metadata"].as_object().unwrap() {
                        state.row[field] = value.clone();
                    }
                    state.row["metadata_v"] = json!(1);
                    state.row["title_v"] = json!(1);
                    state.metadata_terminal = true;
                    let raw = fixture()["metadata"].clone();
                    outgoing.push(json!({"type":"metadata_job_persisted","payload":{"job_id":raw["job_id"],"chat_id":CHAT,"task_id":raw["task_id"],"stage":"initial","chat_key_version":1,"state":"TERMINAL","versions":{"metadata_v":1,"title_v":1},"encrypted_metadata":p["encrypted_metadata"],"request_id":p["request_id"]}}));
                }
                _ => panic!("unexpected synthetic recovery WS command {kind}"),
            }
        }
        if close {
            let _ = ws.close(None).await;
            break;
        }
        for outgoing in outgoing {
            if ws
                .send(WsMessage::Text(outgoing.to_string().into()))
                .await
                .is_err()
            {
                return;
            }
        }
    }
}
async fn ready(
    client: &mut Client,
    job: &CompletionRecoveryJob,
    cancel: &CancellationToken,
) -> CompletionRecoveryStage {
    match client.stage_completion_recovery(job, cancel).await.unwrap() {
        CompletionRecoveryAdmission::Ready(stage) => *stage,
        _ => panic!("expected a staged recovery"),
    }
}
async fn bounded(future: impl std::future::Future<Output = ()>) {
    tokio::time::timeout(Duration::from_secs(10), future)
        .await
        .unwrap()
}

const BACKEND_FIXTURE: &str = r#"{
  "main": {
    "protocol_version": 1,
    "job_id": "63efe7ba-6ff2-5807-99f2-b40e60d6eabc",
    "hashed_user_id": "bd7662a5eeb41614e720d477abfcb2272e19a8a70a93b7e3bc8560d44ad326e9",
    "chat_id": "22222222-2222-4222-8222-222222222222",
    "turn_id": "33333333-3333-4333-8333-333333333333",
    "preflight_id": "77777777-7777-4777-8777-777777777777",
    "inference_task_id": "66666666-6666-4666-8666-666666666666",
    "assistant_message_id": "55555555-5555-4555-8555-555555555555",
    "chat_key_version": 1,
    "sealed_payload": "{\"ciphertext\":\"kGaSq5Cu8rhmv5Vq97buJPIaSo8ObICVjFrgn97oCfMNjLCVTynExOSG69MhyyBFYNkZoMjgf-bc7CspYOUrP-ZGKdhkULWcJb8xcEYJRjhZ3uoH1czT3Kgj7fXcFSiMyO5V2HB-zJ9t0lHYVKCMYFaXX6bqhHI1VsxMIb3rZuleUY6J1XpaAb2vsaeDxSCHhE7q1WvF7PE0Prk8jsCeIheYTi6_QmcJU3SDxnUQUn0AzWVYZfiSLV5EgPl1Q2EoE389NAKpDonLBMBgonopPnILZB2eCz8HFLQbxhebQMuxDZa1aGN8_yf_qWe68kMvC_KVHfxnroYAWYkBCcJAC3byW2NvO-H3kGX6NlHNcMdwSQguLnZwx5BpPIWoWkl_Fy4bH8oAUBpJEq-w7acTO4qiDn7vIkY-2S4w1Lkahn41Ss-Rm1zFazXoV2nRfq-P2oUU3jjUy4bb2hgHtRnf4MceNgzqG6jsZBr5p9xdG3iCvrwKGaLpExPpznJJeIEEo2gNImh0MnpjSMOy3Har-A\",\"epk\":\"EPDh3EQBSnESed9kZkduKajQf0oVWuqjCa-CQMwdLXI\",\"nonce\":\"HPUuG6r5lE6-cM3z\",\"v\":1}"
  },
  "metadata": {
    "protocol_version": 1,
    "job_id": "beca38d0-dd13-5701-84b0-bf523d08b43b",
    "hashed_user_id": "bd7662a5eeb41614e720d477abfcb2272e19a8a70a93b7e3bc8560d44ad326e9",
    "chat_id": "22222222-2222-4222-8222-222222222222",
    "task_id": "66666666-6666-4666-8666-666666666666",
    "inference_task_id": "66666666-6666-4666-8666-666666666666",
    "preflight_id": "77777777-7777-4777-8777-777777777777",
    "chat_key_version": 1,
    "stage": "initial",
    "source_metadata_v": 0,
    "generated_at": "2026-10-23T00:00:00.000Z",
    "encrypted_fields": [
      "encrypted_category",
      "encrypted_title"
    ],
    "sealed_payload": "{\"ciphertext\":\"HYCC1giSzUan8Y-GWSh5W7xwFalZhRk2Pzr1-uUfMSWs5q98OfiINuzy68D_qQkE-nB4AGIeERK-1J4HKKMrzHFcS03PmM6ttANXyIysD3lHRsjzGyefbcoH87jxFu1VT_8lxSxeeBHUb9A4svjoVzV-U2hQGFHeemWNTv6j6TWa_aAdKBA4UAdVsLuxqkvg8XzP8bVS97O1pn6oB6jCEa-nko6gSUfrg991qct8AO-EWG4O_tAC011kQd6GljhGrjK6tje6L5j8dI896XZV0j03AinkxbFEXc8Fg-rg2vjiieYef79stMesAsjyTGeFtd8whoIhKDfn7_pAVq7pJe3q8qfqFDxTInJp09Yhleh4uUBnPENbeB2Uk_nO0mkExX3znOF4MJzl5UOXrWUPz8CH8g\",\"epk\":\"rAGyIJ6GNU-4UyN7XeD0-rE8f8v0M6YcAZNpYX_s8Qs\",\"nonce\":\"AwMDAwMDAwMDAwMD\",\"v\":1}"
  },
  "main2": {
    "protocol_version": 1,
    "job_id": "286ad281-ebbe-5eb5-849b-4678796e48ed",
    "hashed_user_id": "bd7662a5eeb41614e720d477abfcb2272e19a8a70a93b7e3bc8560d44ad326e9",
    "chat_id": "22222222-2222-4222-8222-222222222222",
    "turn_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "preflight_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "inference_task_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    "assistant_message_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "chat_key_version": 1,
    "sealed_payload": "{\"ciphertext\":\"G8oPxKAJ_BpK9AOj8ggLBxbPpq0qrm5lFwJdoC6fJJogSI4wB2urA2qMW03fAT9dU6jBSogwv6Lme5eGm1zMiFLfJPqIkKvSJyWbpkjQbJYU3JGPynAwXddhGdWg4_QMZT71P5bTG20ioZdSQ0jDAYkh1PfrEuDi2L9k4_IyYNoVkOl3-7eARqStgoCNVnehVOi1wNga27g9O5kV3ukMcuGx7VP9_xSZdJZJQ9z-Sn0T2BEwwIgjdbt_z7-Uceh9KNrlPAgGJx2kTB7iAvQykELDAiCyPZtV5V6Aj9eoDwIYWBR4F1dZeal0HJ8aidsacd0OGxK-0gP3aQvMpVRfCuck4oT8gnYLNhCh4S5FbQ9XiCErKOPkVbR5Y_73WUlv2mY2d28xZWPPWZxNitUuRfzRS5HcTlHeM2s9MEBUY4xHfUdJ\",\"epk\":\"tnBelDDjsBFRqgadhcGQNwjDmxq8yUjNDMg00dDeGgQ\",\"nonce\":\"ROl6V_C8hUCxCwVP\",\"v\":1}"
  }
}"#;
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn fresh_paired_reader_stages_then_durable_commit_once_without_new_turn() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        assert!(peer.state.lock().unwrap().persists.is_empty());
        let receipt = client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        assert_eq!(receipt.state, "TERMINAL");
        let mut fresh = peer.client();
        let outcome = fresh
            .resume_completion_recovery(checkpoint, &cancel)
            .await
            .unwrap();
        assert!(matches!(outcome, CompletionRecoveryAdmission::Canonical(_)));
        let state = peer.state.lock().unwrap();
        assert_eq!(state.persists.len(), 1);
        assert_eq!(
            state
                .history
                .iter()
                .filter(|row| row["role"] == "assistant")
                .count(),
            1
        );
        assert_eq!(
            state
                .history
                .iter()
                .filter(|row| row["role"] == "user")
                .count(),
            1
        );
        assert!(state.frames.iter().all(|frame| !matches!(
            frame["type"].as_str(),
            Some("new_message" | "chat_turn_prepare" | "chat_turn_enqueue")
        )));
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn discovery_captures_main_before_output_fence_without_claiming_or_decrypting() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let jobs = client
            .completion_recovery_jobs(&CancellationToken::new())
            .await
            .unwrap();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].job_id, job().job_id);
        let state = peer.state.lock().unwrap();
        assert_eq!(state.claims, 0);
        assert!(state.persists.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn local_write_failure_or_wrong_durable_digest_never_sends_canonical_persist() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        drop(stage);
        assert!(peer.state.lock().unwrap().persists.is_empty());
        // Authoritative mock server advances past the abandoned lease; SDK has
        // no clock override or force-claim escape hatch.
        peer.state.lock().unwrap().active_leases.clear();
        let mut fresh = peer.client();
        let stage = match fresh
            .resume_completion_recovery(checkpoint, &cancel)
            .await
            .unwrap()
        {
            CompletionRecoveryAdmission::Ready(stage) => *stage,
            _ => panic!("expected ready"),
        };
        assert!(matches!(
            fresh
                .commit_completion_recovery(
                    stage,
                    CompletionRecoveryDurableReceipt {
                        checkpoint_sha256: "wrong".into()
                    },
                    &cancel
                )
                .await,
            Err(Error::Conflict)
        ));
        assert!(peer.state.lock().unwrap().persists.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn uncertain_ack_resume_reconciles_terminal_before_any_second_persist() {
    bounded(async {
        let peer = Peer::new().await;
        peer.state.lock().unwrap().drop_ack = true;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        let exact = checkpoint.encrypted_candidate.clone();
        assert!(
            client
                .commit_completion_recovery(
                    stage,
                    CompletionRecoveryDurableReceipt {
                        checkpoint_sha256: checkpoint.digest().unwrap()
                    },
                    &cancel
                )
                .await
                .is_err()
        );
        let mut fresh = peer.client();
        assert!(matches!(
            fresh
                .resume_completion_recovery(checkpoint, &cancel)
                .await
                .unwrap(),
            CompletionRecoveryAdmission::Canonical(_)
        ));
        let state = peer.state.lock().unwrap();
        assert_eq!(state.persists, vec![exact]);
        assert_eq!(
            state
                .history
                .iter()
                .filter(|row| row["role"] == "assistant")
                .count(),
            1
        );
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn uncommitted_checkpoint_resumes_exact_ciphertext_without_rerandomizing() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        let original = serde_json::to_value(&checkpoint).unwrap();
        drop(stage);
        peer.state.lock().unwrap().active_leases.clear(); // server lease expiry
        let mut fresh = peer.client();
        let stage = match fresh
            .resume_completion_recovery(checkpoint, &cancel)
            .await
            .unwrap()
        {
            CompletionRecoveryAdmission::Ready(stage) => *stage,
            _ => panic!("expected ready"),
        };
        let resumed = stage.checkpoint().unwrap();
        assert_eq!(serde_json::to_value(&resumed).unwrap(), original);
        fresh
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: resumed.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        assert_eq!(
            peer.state.lock().unwrap().persists[0],
            original["encrypted_candidate"]
        );
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn existing_canonical_assistant_and_available_job_reuse_ciphertext_and_settle_without_duplicate()
 {
    bounded(async {
        let peer = Peer::new().await;
        let identity = main_identity(OWNER, &job()).unwrap();
        let envelope: Value =
            serde_json::from_str(fixture()["main"]["sealed_payload"].as_str().unwrap()).unwrap();
        let recovered = decode_main_completion(&envelope, &[8; 32], &identity).unwrap();
        let existing = encrypt_main_assistant(&recovered, &identity, 100, None, &[8; 32]).unwrap();
        {
            let mut state = peer.state.lock().unwrap();
            state.history.push(existing.clone());
            state.row["messages_v"] = json!(2);
            assert!(!state.settled);
        }
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        assert!(checkpoint.canonical_ciphertext);
        assert_eq!(checkpoint.encrypted_candidate, existing);
        client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        let state = peer.state.lock().unwrap();
        assert!(state.settled);
        assert_eq!(state.persists, vec![existing]);
        assert_eq!(
            state
                .history
                .iter()
                .filter(|row| row["role"] == "assistant")
                .count(),
            1
        );
        assert_eq!(state.row["messages_v"], 2);
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn forged_checkpoint_scope_cancel_reset_expiry_and_key_rotation_never_persist() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let caller = CancellationToken::new();
        let stage = ready(&mut client, &job(), &caller).await;
        let checkpoint = stage.checkpoint().unwrap();
        caller.cancel();
        assert!(matches!(stage.checkpoint(), Err(Error::Cancelled)));
        drop(stage);
        peer.state.lock().unwrap().active_leases.clear();
        for field in ["owner_id", "api_url", "team_id"] {
            let mut forged = serde_json::to_value(&checkpoint).unwrap();
            forged[field] = json!("foreign");
            let mut fresh = peer.client();
            let forged: CompletionRecoveryCheckpoint = serde_json::from_value(forged).unwrap();
            assert!(matches!(
                fresh
                    .resume_completion_recovery(forged, &CancellationToken::new())
                    .await,
                Err(Error::Forbidden)
            ));
        }
        let mut fresh = peer.client();
        let cancel = CancellationToken::new();
        let mut expired = ready(&mut fresh, &job(), &cancel).await;
        expired.fence.expires_at = Some(now_ms().saturating_sub(1));
        assert!(matches!(expired.checkpoint(), Err(Error::Expired)));
        drop(expired);
        peer.state.lock().unwrap().active_leases.clear();
        let reset_stage = ready(&mut fresh, &job(), &cancel).await;
        let session = fresh.clone_session().unwrap();
        fresh.reset(&peer.api, Some(session)).unwrap();
        assert!(matches!(reset_stage.checkpoint(), Err(Error::Cancelled)));
        drop(reset_stage);
        peer.state.lock().unwrap().active_leases.clear();
        let mut fresh = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut fresh, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        peer.state.lock().unwrap().row["encrypted_chat_key"] =
            json!(crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap());
        assert!(matches!(
            fresh
                .commit_completion_recovery(
                    stage,
                    CompletionRecoveryDurableReceipt {
                        checkpoint_sha256: checkpoint.digest().unwrap()
                    },
                    &cancel
                )
                .await,
            Err(Error::Crypto)
        ));
        assert!(peer.state.lock().unwrap().persists.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn explicit_foreground_mode_is_default_off_and_real_library_identity_is_preserved() {
    bounded(async {
        let peer = Peer::new().await;
        let configured = peer.client();
        let mut client = Client::new(&peer.api, configured.clone_session()).unwrap();
        assert!(client.completion_recovery_mode.is_none());
        assert!(matches!(
            client
                .stage_completion_recovery(&job(), &CancellationToken::new())
                .await,
            Err(Error::Unavailable { .. })
        ));
        assert!(peer.state.lock().unwrap().frames.is_empty());
        for identity in [
            ClientIdentity::Rust,
            ClientIdentity::Npm,
            ClientIdentity::Pip,
            ClientIdentity::Cli,
        ] {
            client.set_identity(identity);
            client.set_foreground_completion_recovery(true).unwrap();
            assert_eq!(client.options().identity, identity);
            client.set_foreground_completion_recovery(false).unwrap();
        }
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn metadata_personal_omcm1_recovery_is_separate_and_never_reinfers_main_reply() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &metadata_job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        assert_eq!(client.cached_chats().unwrap()[0].title, "Recovered title");
        let state = peer.state.lock().unwrap();
        assert!(state.metadata_terminal);
        assert!(state.persists.is_empty());
        assert!(
            state
                .frames
                .iter()
                .all(|frame| frame["type"] != "new_message")
        );
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[test]
fn metadata_aad_substitution_and_stale_version_receipts_fail_or_preserve_newer_fields() {
    let claim = fixture()["metadata"].clone();
    let decoded = decode_metadata_completion(&claim, OWNER, &metadata_job(), &[8; 32]).unwrap();
    assert_eq!(decoded["title"], "Recovered title");
    let mut wrong = metadata_job();
    wrong.stage = Some("postprocessing".into());
    assert!(decode_metadata_completion(&claim, OWNER, &wrong, &[8; 32]).is_err());
    let main = fixture()["main"].clone();
    let identity = main_identity(OWNER, &job()).unwrap();
    let envelope: Value = serde_json::from_str(claim["sealed_payload"].as_str().unwrap()).unwrap();
    assert!(decode_main_completion(&envelope, &[8; 32], &identity).is_err());
    let current = json!({"metadata_v":5,"title_v":4,"encrypted_title":"manual"});
    let stale = json!({"versions":{"metadata_v":4,"title_v":3},"encrypted_metadata":{"encrypted_title":"stale"}});
    assert_eq!(merge_metadata_receipt(&stale, &current).unwrap(), current);
    let _ = main;
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn fence_timeout_and_caller_cancellation_cover_blocked_operations() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        client.validate_session().await.unwrap();
        let caller = CancellationToken::new();
        let fence = client.recovery_fence(&caller).unwrap();
        let future = fence.run(std::future::pending::<Result<()>>());
        let cancel = async {
            tokio::task::yield_now().await;
            caller.cancel();
        };
        let (result, ()) = tokio::join!(future, cancel);
        assert_eq!(result, Err(Error::Cancelled));
        let mut lease = client.recovery_fence(&CancellationToken::new()).unwrap();
        lease.lease_expires_at = Some(now_ms() + 20);
        assert!(
            lease
                .run(std::future::pending::<Result<()>>())
                .await
                .is_err()
        );
        assert!(peer.state.lock().unwrap().persists.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement
#[test]
fn strict_server_lease_timestamp_parser_and_bounded_job_capture_match_authoritative_forms() {
    assert_eq!(iso_timestamp_ms("1970-01-01T00:00:00.000Z").unwrap(), 0);
    assert_eq!(
        iso_timestamp_ms("2000-02-29T12:34:56.789Z").unwrap(),
        951827696789
    );
    for invalid in [
        "2026-02-30T00:00:00.000Z",
        "2026-01-01T24:00:00.000Z",
        "2026-01-01T00:00:00Z",
    ] {
        assert!(iso_timestamp_ms(invalid).is_err())
    }
    let mut main = BTreeMap::new();
    let mut metadata = BTreeMap::new();
    let mut raw = fixture()["main"].clone();
    raw["state"] = json!("AVAILABLE");
    capture(
        "recovery_jobs_available",
        &json!({"jobs":[raw]}),
        &mut main,
        &mut metadata,
    )
    .unwrap();
    assert_eq!(main.len(), 1);
    assert!(
        capture(
            "recovery_jobs_available",
            &json!({"jobs":vec![json!({});101]}),
            &mut main,
            &mut metadata
        )
        .is_err()
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn metadata_team_is_explicitly_deferred_without_personal_key_fallback() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        client
            .set_team(Some("99999999-9999-4999-8999-999999999999"))
            .unwrap();
        client.set_foreground_completion_recovery(true).unwrap();
        assert!(matches!(
            client
                .stage_completion_recovery(&metadata_job(), &CancellationToken::new())
                .await
                .unwrap(),
            CompletionRecoveryAdmission::Deferred
        ));
        assert!(peer.state.lock().unwrap().frames.is_empty());
        assert!(peer.state.lock().unwrap().persists.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn staged_candidate_survives_transient_client_child_replacement() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let retained = CancellationToken::new();
        let stage = ready(&mut client, &job(), &retained).await;
        let checkpoint = stage.checkpoint().unwrap();
        client.set_operation_cancel(CancellationToken::new());
        assert!(stage.checkpoint().is_ok());
        let current = CancellationToken::new();
        client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &current,
            )
            .await
            .unwrap();
        assert_eq!(peer.state.lock().unwrap().persists.len(), 1);
    })
    .await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn deferred_old_job_does_not_prevent_new_selected_chat_recovery() {
    bounded(async {
        let peer = Peer::new().await;
        peer.state.lock().unwrap().lease_conflict = true;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        assert!(matches!(
            client
                .stage_completion_recovery(&job(), &cancel)
                .await
                .unwrap(),
            CompletionRecoveryAdmission::Deferred
        ));
        let raw = fixture()["main2"].clone();
        let second = CompletionRecoveryJob {
            kind: CompletionRecoveryKind::Main,
            job_id: raw["job_id"].as_str().unwrap().into(),
            chat_id: CHAT.into(),
            turn_id: Some(raw["turn_id"].as_str().unwrap().into()),
            assistant_message_id: Some(raw["assistant_message_id"].as_str().unwrap().into()),
            task_id: None,
            stage: None,
            chat_key_version: 1,created_at:None,
        };
        let stage = ready(&mut client, &second, &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        let state = peer.state.lock().unwrap();
        assert!(!state.settled);
        assert!(state.settled_jobs.contains(&second.job_id));
        assert_eq!(state.persists.len(), 1);
        assert_eq!(
            state.persists[0]["client_message_id"],
            second.assistant_message_id.as_deref().unwrap()
        );
    })
    .await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn assistant_encoder_preserves_raw_privacy_placeholders_without_restoring_into_ciphertext() {
    let identity = main_identity(OWNER, &job()).unwrap();
    let envelope: Value =
        serde_json::from_str(fixture()["main"]["sealed_payload"].as_str().unwrap()).unwrap();
    let mut recovered = decode_main_completion(&envelope, &[8; 32], &identity).unwrap();
    recovered["content"] = json!("Raw [PII_EMAIL_001] stays shielded");
    let encrypted = encrypt_main_assistant(&recovered, &identity, 10, None, &[8; 32]).unwrap();
    assert_eq!(
        crypto::decrypt_combined(encrypted["encrypted_content"].as_str().unwrap(), &[8; 32])
            .unwrap(),
        "Raw [PII_EMAIL_001] stays shielded"
    );
    assert!(encrypted.get("user_message_id").is_none());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn unsupported_old_key_version_is_deferred_before_claim_without_blocking_supported_job() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let mut old = job();
        old.chat_key_version = 2;
        assert!(matches!(
            client
                .stage_completion_recovery(&old, &CancellationToken::new())
                .await
                .unwrap(),
            CompletionRecoveryAdmission::Deferred
        ));
        assert!(peer.state.lock().unwrap().frames.is_empty());
        let stage = ready(&mut client, &job(), &CancellationToken::new()).await;
        assert!(stage.checkpoint().is_ok());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[test]
fn stage_is_send_and_incomplete_or_mixed_job_identity_cannot_reach_a_claim() {
    fn assert_send<T: Send>() {}
    assert_send::<CompletionRecoveryStage>();
    let mut incomplete = job();
    incomplete.turn_id = None;
    assert!(validate_job(&incomplete).is_err());
    let mut mixed = metadata_job();
    mixed.assistant_message_id = job().assistant_message_id;
    assert!(validate_job(&mixed).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn independently_deferred_child_output_cannot_hide_already_fenced_main_discovery() {
    bounded(async {
        let peer = Peer::new().await;
        peer.state.lock().unwrap().defer_child = true;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let jobs = client.completion_recovery_jobs(&cancel).await.unwrap();
        assert_eq!(jobs.len(), 1);
        let stage = ready(&mut client, &jobs[0], &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        client
            .commit_completion_recovery(
                stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: checkpoint.digest().unwrap(),
                },
                &cancel,
            )
            .await
            .unwrap();
        let state = peer.state.lock().unwrap();
        assert!(
            state
                .frames
                .iter()
                .any(|frame| frame["type"] == "recovery_output_get")
        );
        assert!(state.frames.iter().all(|frame| {
            !frame["type"]
                .as_str()
                .unwrap()
                .starts_with("recovery_output_ack")
        }));
        assert_eq!(state.persists.len(), 1);
    })
    .await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[test]
fn selected_wrapper_requires_supported_team_epoch_version_and_live_expiry() {
    let now = 10_000;
    let supported = json!({"team_key_epoch":1,"wrapper_version":1,"expires_at":11});
    assert!(validate_recovery_wrapper(&supported, true, now).is_ok());
    for (field, value) in [
        ("team_key_epoch", json!(2)),
        ("team_key_epoch", Value::Null),
        ("wrapper_version", json!(2)),
        ("wrapper_version", Value::Null),
        ("expires_at", json!(10)),
        ("expires_at", json!(9)),
    ] {
        let mut candidate = supported.clone();
        candidate[field] = value;
        assert!(matches!(
            validate_recovery_wrapper(&candidate, true, now),
            Err(Error::Conflict)
        ));
    }
    for value in [json!("11"), json!(-1), json!(u64::MAX)] {
        let mut candidate = supported.clone();
        candidate["expires_at"] = value;
        assert!(matches!(
            validate_recovery_wrapper(&candidate, true, now),
            Err(Error::Protocol)
        ));
    }
    assert!(validate_recovery_wrapper(&json!({}), false, now).is_ok());
    assert!(
        validate_recovery_wrapper(&json!({"wrapper_version":1,"expires_at":null}), false, now)
            .is_ok()
    );
    assert!(matches!(
        validate_recovery_wrapper(&json!({"wrapper_version":2}), false, now),
        Err(Error::Conflict)
    ));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn unsupported_or_expired_team_wrapper_defers_before_key_fetch_or_claim() {
    bounded(async {
        for (field,value) in [("team_key_epoch",json!(2)),("wrapper_version",json!(2)),("expires_at",json!(1))] {
            let peer = Peer::new().await;
            let team = "99999999-9999-4999-8999-999999999999";
            let mut wrapper = json!({"hashed_chat_id":sha256(CHAT),"key_type":"team","hashed_team_id":sha256(team),"team_key_epoch":1,"wrapper_version":1,"encrypted_chat_key":"must-not-decrypt"});
            wrapper[field]=value;
            peer.state.lock().unwrap().row["chat_key_wrappers"]=json!([wrapper]);
            let mut client=peer.client(); client.set_team(Some(team)).unwrap();
            client.set_foreground_completion_recovery(true).unwrap();
            assert!(matches!(client.stage_completion_recovery(&job(),&CancellationToken::new()).await.unwrap(),CompletionRecoveryAdmission::Deferred));
            let state=peer.state.lock().unwrap(); assert_eq!(state.claims,0); assert!(state.persists.is_empty());
            // The peer has no Team key route: a premature key fetch fails loudly.
        }
    }).await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn current_wrapper_is_revalidated_at_commit_before_canonical_persist() {
    bounded(async {
        for (field,value) in [("wrapper_version",json!(2)),("expires_at",json!(1))] {
            let peer=Peer::new().await;
            let mut client=peer.client(); let cancel=CancellationToken::new();
            let stage=ready(&mut client,&job(),&cancel).await;
            let digest=stage.checkpoint().unwrap().digest().unwrap();
            let mut wrapper=json!({"hashed_chat_id":sha256(CHAT),"key_type":"master","wrapper_version":1,"encrypted_chat_key":"must-not-decrypt"});
            wrapper[field]=value;
            peer.state.lock().unwrap().row["chat_key_wrappers"]=json!([wrapper]);
            assert!(matches!(client.commit_completion_recovery(stage,CompletionRecoveryDurableReceipt{checkpoint_sha256:digest},&cancel).await,Err(Error::Conflict)));
            assert!(peer.state.lock().unwrap().persists.is_empty());
        }
    }).await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn saved_checkpoint_digest_survives_exact_canonical_insert_before_job_settlement() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        let stage = ready(&mut client, &job(), &cancel).await;
        let checkpoint = stage.checkpoint().unwrap();
        let digest = checkpoint.digest().unwrap();
        assert!(!checkpoint.canonical_ciphertext);
        drop(stage);
        {
            let mut state = peer.state.lock().unwrap();
            state.active_leases.clear(); // authoritative abandoned lease expiry
            state.history.push(checkpoint.encrypted_candidate.clone());
            state.row["messages_v"] = json!(state.row["messages_v"].as_u64().unwrap() + 1);
            assert!(!state.settled);
        }
        let mut fresh = peer.client();
        let CompletionRecoveryAdmission::Ready(stage) = fresh
            .resume_completion_recovery(checkpoint.clone(), &cancel)
            .await
            .unwrap()
        else {
            panic!("Expected canonical settlement stage")
        };
        assert_eq!(stage.checkpoint().unwrap().digest().unwrap(), digest);
        fresh
            .commit_completion_recovery(
                *stage,
                CompletionRecoveryDurableReceipt {
                    checkpoint_sha256: digest,
                },
                &cancel,
            )
            .await
            .unwrap();
        let state = peer.state.lock().unwrap();
        assert_eq!(state.persists, vec![checkpoint.encrypted_candidate]);
        assert_eq!(
            state
                .history
                .iter()
                .filter(|row| row["role"] == "assistant")
                .count(),
            1
        );
    })
    .await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[test]
fn direct_metadata_does_not_require_teamwide_wrappers_or_grant_team_fallback() {
    let team = "99999999-9999-4999-8999-999999999999";
    let mut row = json!({"chat_visibility":"direct","chat_key_wrappers":[]});
    assert!(validate_selected_team_recovery_wrapper(&row, CHAT, Some(team)).is_ok());
    row["chat_visibility"] = json!("team");
    assert!(matches!(
        validate_selected_team_recovery_wrapper(&row, CHAT, Some(team)),
        Err(Error::Forbidden)
    ));
    // The production direct branch still calls load_direct_identity and
    // direct_chat_key; passing this preflight supplies no recipient key.
}


// Supporting authored real-loopback regressions. UNRUN outside parent CI.
#[tokio::test]
async fn selected_discovery_retains_unrelated_offers_without_global_sync_or_inventory() {
    let peer = Peer::new().await;
    peer.state.lock().unwrap().selected_startup = true;
    let mut client = peer.client();
    let mut prior = job(); prior.job_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb".into();
    prior.chat_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".into();
    client.completion_recovery_jobs.insert(prior.job_id.clone(), prior.clone());
    let before = client.chats.clone();
    let discovered = client.completion_recovery_jobs_for_chat(CHAT, &CancellationToken::new()).await.unwrap();
    assert_eq!(discovered.len(), 1); assert_eq!(discovered[0].chat_id, CHAT);
    assert_eq!(client.completion_recovery_jobs[&prior.job_id].chat_id, prior.chat_id);
    assert_eq!(client.chats, before);
    let state = peer.state.lock().unwrap();
    assert!(!state.frames.iter().any(|f|f["type"] == "phased_sync_request"));
    assert!(state.http_paths.iter().all(|p| p == "/v1/auth/session"));
    assert_eq!(state.claims,0);
}
#[tokio::test]
async fn selected_discovery_then_strict_read_keeps_all_140_rows_and_before_cursor() {
    let peer = Peer::new().await;
    {
        let mut state=peer.state.lock().unwrap(); state.selected_startup=true; state.settled=true;
        state.history=(0..140).map(|n|json!({
            "client_message_id":format!("00000000-0000-4000-8000-{n:012}"),"chat_id":CHAT,
            "role":"user","encrypted_content":crypto::encrypt_combined(&format!("strict-{n}"),&[8;32]).unwrap(),
            "created_at":n+1,"updated_at":n+1
        })).collect();
    }
    let mut client=peer.client(); let cancel=CancellationToken::new();
    assert!(client.completion_recovery_jobs_for_chat(CHAT,&cancel).await.unwrap().is_empty());
    client.set_foreground_completion_recovery(false).unwrap();
    let chat=client.open_chat(CHAT).await.unwrap();
    assert_eq!(chat.messages.len(),140);
    assert_eq!(chat.messages.first().unwrap().content,"strict-0");
    assert_eq!(chat.messages.last().unwrap().content,"strict-139");
    assert_eq!(client.history[CHAT].len(),140);
    for (index,message) in chat.messages.iter().enumerate() {
        assert_eq!(message.id,format!("00000000-0000-4000-8000-{index:012}"));
        assert_eq!(message.content,format!("strict-{index}"));
    }
    assert!(client.history[CHAT].iter().all(|row| row["encrypted_content"].is_string() && row.get("content").is_none()));
    let state=peer.state.lock().unwrap();
    assert!(!state.frames.iter().any(|f|f["type"] == "phased_sync_request"));
    assert_eq!(state.http_paths.iter().filter(|p|p.contains("/messages/window")).count(),2);
    assert!(state.http_paths.iter().any(|p|p.contains("direction=before")));
    let windows=state.http_paths.iter().filter(|path|path.contains("/messages/window"))
        .map(|path|url::Url::parse(&format!("http://synthetic{path}")).unwrap()
            .query_pairs().map(|(key,value)|(key.into_owned(),value.into_owned()))
            .collect::<BTreeMap<_,_>>()).collect::<Vec<_>>();
    assert_eq!(windows[0]["direction"],"latest");
    assert!(!windows[0].contains_key("before_timestamp") && !windows[0].contains_key("before_message_id"));
    assert_eq!(windows[1]["direction"],"before");
    assert_eq!(windows[1]["before_timestamp"],"41");
    assert_eq!(windows[1]["before_message_id"],"00000000-0000-4000-8000-000000000040");
    assert!(windows.iter().all(|query|query["limit"]=="100" && query["respect_compression_boundary"]=="false"));
}
#[tokio::test]
async fn cancelled_selected_discovery_does_not_connect_or_erase_other_cache() {
    let peer=Peer::new().await; let mut client=peer.client();
    client.chats.insert(CHAT.into(),json!({"id":CHAT})); let before=client.chats.clone();
    let cancel=CancellationToken::new(); cancel.cancel();
    assert!(matches!(client.completion_recovery_jobs_for_chat(CHAT,&cancel).await,Err(Error::Cancelled)));
    assert_eq!(client.chats,before); assert!(peer.state.lock().unwrap().http_paths.is_empty());
}

#[tokio::test]
async fn failed_selected_discovery_does_not_publish_or_claim_an_earlier_main_offer() {
    let peer=Peer::new().await;
    { let mut state=peer.state.lock().unwrap();state.selected_startup=true;state.startup_failure=true; }
    let mut client=peer.client();let before=client.chats.clone();
    assert!(matches!(client.completion_recovery_jobs_for_chat(CHAT,&CancellationToken::new()).await,Err(Error::Protocol)));
    assert!(client.completion_recovery_jobs.is_empty());assert_eq!(client.chats,before);
    let state=peer.state.lock().unwrap();assert_eq!(state.claims,0);
    assert!(!state.frames.iter().any(|f|f["type"] == "phased_sync_request"));
}


// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn pending_main_metadata_never_becomes_a_claimable_offer_or_an_empty_proof() {
    let mut offered = fixture()["main"].clone(); offered["state"] = json!("LEASED");
    let payload = json!({"jobs":[],"pending_jobs":[offered]});
    assert!(has_pending_main_jobs("recovery_jobs_available",&payload).unwrap());
    let mut main=BTreeMap::new();let mut metadata=BTreeMap::new();
    capture("recovery_jobs_available",&payload,&mut main,&mut metadata).unwrap();
    assert!(main.is_empty() && metadata.is_empty());
    assert!(has_pending_main_jobs("recovery_jobs_available",&json!({"jobs":[],"pending_jobs":false})).is_err());
    assert!(!has_pending_main_jobs("recovery_jobs_available",&json!({"jobs":[]})).unwrap());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,chats.message.identity-idempotent
#[tokio::test]
async fn cold_recovery_preserves_durable_created_at_and_old_checkpoint_shape() {
    bounded(async {
        let peer=Peer::new().await;let mut client=peer.client();let cancel=CancellationToken::new();
        let old=job();assert!(serde_json::to_value(&old).unwrap().get("created_at").is_none());
        let mut current=old.clone();current.created_at=Some(1_800_000_001);
        assert!(same_checkpoint_job(&old,&current));
        assert_eq!(observed_job_created_at(&client,&current).unwrap(),None,"caller metadata alone is not durable time");
        client.completion_recovery_jobs.insert(current.job_id.clone(),current.clone());
        let mut forged=current.clone();forged.created_at=Some(1_800_000_002);
        assert!(observed_job_created_at(&client,&forged).is_err());
        let stage=ready(&mut client,&current,&cancel).await;let checkpoint=stage.checkpoint().unwrap();
        assert_eq!(checkpoint.encrypted_candidate["created_at"],1_800_000_001u64);
        let receipt=client.commit_completion_recovery(stage,CompletionRecoveryDurableReceipt{checkpoint_sha256:checkpoint.digest().unwrap()},&cancel).await.unwrap();
        assert_eq!(receipt.state,"TERMINAL");
        assert_eq!(peer.state.lock().unwrap().persists[0]["created_at"],1_800_000_001u64);
    }).await;
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
#[test]
fn legacy_checkpoint_time_absence_preserves_all_original_job_identity_guards() {
    let old=job(); let mut current=old.clone(); current.created_at=Some(1_800_000_001);
    assert!(same_checkpoint_job(&old,&current) && same_checkpoint_job(&current,&old));
    let mut different=current.clone();different.created_at=Some(1_800_000_002);
    assert!(!same_checkpoint_job(&current,&different));
    let mut variants=Vec::new();
    let mut changed=current.clone();changed.kind=CompletionRecoveryKind::Metadata;variants.push(changed);
    let mut changed=current.clone();changed.job_id.push('x');variants.push(changed);
    let mut changed=current.clone();changed.chat_id.push('x');variants.push(changed);
    let mut changed=current.clone();changed.turn_id=None;variants.push(changed);
    let mut changed=current.clone();changed.assistant_message_id=None;variants.push(changed);
    let mut changed=current.clone();changed.task_id=Some("different-task".into());variants.push(changed);
    let mut changed=current.clone();changed.stage=Some("different-stage".into());variants.push(changed);
    let mut changed=current.clone();changed.chat_key_version+=1;variants.push(changed);
    for changed in variants { assert!(!same_checkpoint_job(&old,&changed)); }
    let mut main=BTreeMap::new();let mut metadata=BTreeMap::new();
    let mut legacy=fixture()["main"].clone();legacy["state"]=json!("AVAILABLE");
    let mut authentic=legacy.clone();authentic["created_at"]=json!(1_800_000_001);
    for offered in [legacy.clone(),authentic,legacy] {
        capture("recovery_jobs_available",&json!({"jobs":[offered]}),&mut main,&mut metadata).unwrap();
    }
    assert_eq!(main[&old.job_id].created_at,Some(1_800_000_001));
}
