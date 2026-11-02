//! Synthetic loopback/capability regressions, authored but not executed here.
//! No account, browser CryptoKey, backend authorization or performance claim.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use base64::{Engine, engine::general_purpose::STANDARD};
use futures_util::{SinkExt, StreamExt};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    sync::Notify,
    task::JoinHandle,
};
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const EMBED: &str = "33333333-3333-4333-8333-333333333333";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";
const OWNER: &str = "55555555-5555-4555-8555-555555555555";
#[derive(Default)]
struct Gate {
    entered: Notify,
    release: Notify,
    dropped: AtomicBool,
}
struct InFlight(Arc<Gate>);
impl Drop for InFlight {
    fn drop(&mut self) {
        self.0.dropped.store(true, Ordering::SeqCst);
    }
}
struct Port {
    key: Key,
    gate: Option<Arc<Gate>>,
}
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            let _inflight = self.gate.as_ref().map(|gate| InFlight(gate.clone()));
            if let Some(gate) = &self.gate {
                gate.entered.notify_one();
                gate.release.notified().await;
            }
            crypto::encrypt_aead(plain, &self.key, iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &self.key, iv, &[]) })
    }
}
fn fixture(api: &str, opaque: bool, gate: Option<Arc<Gate>>) -> Client {
    let session = Session {
        api_url: api.into(),
        session_id: "synthetic-persistence".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(api, Some(session)).unwrap();
    client.user = json!({"id":OWNER});
    if opaque {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        credentials.master = MasterCapability::opaque_for_test(Arc::new(Port {
            key: zeroize::Zeroizing::new([7; 32]),
            gate,
        }));
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: OWNER.into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
    }
    client
}
fn input() -> BTreeMap<String, Value> {
    BTreeMap::from([(
        EMBED.into(),
        json!({"message_id":MESSAGE,"content":"title: Synthetic artifact\nvalue: synthetic","type":"code","text_preview":"Synthetic preview","version_number":1,"version_history_rows":[{"embed_id":EMBED,"version_number":1,"snapshot":"Synthetic snapshot"}]}),
    )])
}
fn checkpoint() -> Value {
    json!({"chat_id":CHAT,"checkpoint_id":"synthetic-checkpoint","summary_content":"Synthetic summary","compressed_up_to_message_id":MESSAGE,"covered_message_ids":[MESSAGE]})
}
fn legacy_open(cipher: &str, key: &[u8; 32]) -> zeroize::Zeroizing<Vec<u8>> {
    let raw = STANDARD.decode(cipher).unwrap();
    assert!(raw.len() >= 28);
    crypto::decrypt_aead(&raw[12..], key, &raw[..12], &[]).unwrap()
}
struct Peer {
    api: String,
    ws: Socket,
    frames: Arc<Mutex<Vec<Value>>>,
    http: JoinHandle<()>,
    socket: JoinHandle<()>,
}
impl Peer {
    async fn start() -> Self {
        Self::with_canonical(false).await
    }
    async fn with_canonical(replay: bool) -> Self {
        let key = crypto::derive_embed_key(&[9; 32], EMBED).unwrap();
        // A previously accepted native OM head remains readable on replay.
        let canonical=replay.then(||json!({"hashed_chat_id":sha256(CHAT),"hashed_embed_id":sha256(EMBED),"hashed_message_id":sha256(MESSAGE),"version_number":1,"encrypted_content":crypto::encrypt_combined(input()[EMBED]["content"].as_str().unwrap(),&key).unwrap(),"encrypted_type":crypto::encrypt_combined("code",&key).unwrap()}));
        let history = crypto::encrypt_combined("Synthetic snapshot", &key).unwrap();
        let head = Arc::new(Mutex::new(canonical));
        let http_head = head.clone();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let http = tokio::spawn(async move {
            for index in 0..(if replay { 2 } else { 3 }) {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut raw = Vec::new();
                loop {
                    let mut chunk = [0u8; 2048];
                    let n = stream.read(&mut chunk).await.unwrap();
                    assert!(n > 0);
                    raw.extend_from_slice(&chunk[..n]);
                    assert!(raw.len() < 16384);
                    if raw.windows(4).any(|v| v == b"\r\n\r\n") {
                        break;
                    }
                }
                let request = std::str::from_utf8(&raw).unwrap();
                assert!(request.starts_with("GET /v1/embeds/"));
                let (status, body) = if replay && index == 1 {
                    (
                        200,
                        json!({"embed_id":EMBED,"version_number":1,"rows":[{"version_number":1,"encrypted_snapshot":history}]}),
                    )
                } else if (replay && index == 0) || (!replay && index == 1) {
                    (
                        200,
                        json!({"embed":http_head.lock().unwrap().clone().unwrap(),"embed_keys":[]}),
                    )
                } else {
                    (404, json!({"detail":"synthetic missing"}))
                };
                let body = body.to_string();
                stream.write_all(format!("HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            }
        });
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let frames = Arc::new(Mutex::new(Vec::<Value>::new()));
        let seen = frames.clone();
        let socket = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            while let Some(Ok(frame)) = ws.next().await {
                if !frame.is_text() {
                    continue;
                }
                let request: Value = serde_json::from_str(frame.to_text().unwrap()).unwrap();
                seen.lock().unwrap().push(request.clone());
                let p = &request["payload"];
                let response = match request["type"].as_str().unwrap() {
                    "store_embed" => {
                        // Directus create_embed derives this canonical identity;
                        // it is not part of the client's store_embed payload.
                        let mut stored = p.clone();
                        stored["hashed_embed_id"] = json!(sha256(p["embed_id"].as_str().unwrap()));
                        *head.lock().unwrap() = Some(stored);
                        json!({"type":"store_embed_confirmed","payload":{"request_id":p["request_id"],"embed_id":p["embed_id"],"canonical_source":"head","canonical_digest":sha256(p["encrypted_content"].as_str().unwrap())}})
                    }
                    "store_embed_keys" => {
                        json!({"type":"store_embed_keys_confirmed","payload":{"request_id":p["request_id"],"failed_count":0,"created_count":2}})
                    }
                    "store_embed_diff" => {
                        json!({"type":"store_embed_diff_confirmed","payload":{"request_id":p["request_id"],"embed_id":p["embed_id"],"version_number":p["version_number"],"canonical_source":"version_row","canonical_digest":sha256(&json!([p["encrypted_snapshot"],null]).to_string())}})
                    }
                    "store_chat_compression_checkpoint" => {
                        json!({"type":"chat_compression_checkpoint_stored","payload":{"chat_id":CHAT,"checkpoint":{"id":p["checkpoint_id"],"compressed_up_to_message_id":p["compressed_up_to_message_id"],"covered_message_ids":p["covered_message_ids"]}}})
                    }
                    _ => panic!("unexpected synthetic persistence frame"),
                };
                ws.send(Frame::text(response.to_string())).await.unwrap();
            }
        });
        let (ws, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        Self {
            api,
            ws: super::super::transport::test_socket(ws),
            frames,
            http,
            socket,
        }
    }
    fn stop(&self) {
        self.http.abort();
        self.socket.abort();
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.stop();
    }
}
#[tokio::test]
async fn genuine_native_and_opaque_streams_write_browser_metadata_and_keep_message_summary_om() {
    for opaque in [false, true] {
        let mut peer = Peer::start().await;
        let mut client = fixture(&peer.api, opaque, None);
        let embeds = input();
        let checkpoints = [checkpoint()];
        let result = client
            .persist_stream_artifacts(
                &mut peer.ws,
                CHAT,
                MESSAGE,
                &[9; 32],
                "",
                &embeds,
                &checkpoints,
            )
            .await
            .unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].title, "Synthetic artifact");
        assert_eq!(client.credential_ack, 0);
        if opaque {
            assert!(client.session().is_none());
            assert!(client.native_master_key().is_err());
            assert!(client.credential_snapshot().is_none());
        }
        let frames = peer.frames.lock().unwrap();
        assert_eq!(
            frames
                .iter()
                .map(|v| v["type"].as_str().unwrap())
                .collect::<Vec<_>>(),
            [
                "store_embed",
                "store_embed_keys",
                "store_embed_diff",
                "store_chat_compression_checkpoint"
            ]
        );
        let key = crypto::derive_embed_key(&[9; 32], EMBED).unwrap();
        let head = &frames[0]["payload"];
        for (field, expected) in [
            (
                "encrypted_content",
                embeds[EMBED]["content"].as_str().unwrap(),
            ),
            ("encrypted_type", "code"),
            ("encrypted_text_preview", "Synthetic preview"),
        ] {
            assert_eq!(
                legacy_open(head[field].as_str().unwrap(), &key).as_slice(),
                expected.as_bytes()
            );
        }
        let wrappers = frames[1]["payload"]["keys"].as_array().unwrap();
        assert_eq!(
            legacy_open(
                wrappers[0]["encrypted_embed_key"].as_str().unwrap(),
                &[7; 32]
            )
            .as_slice(),
            key.as_ref()
        );
        assert_eq!(
            legacy_open(
                wrappers[1]["encrypted_embed_key"].as_str().unwrap(),
                &[9; 32]
            )
            .as_slice(),
            key.as_ref()
        );
        assert_eq!(
            legacy_open(
                frames[2]["payload"]["encrypted_snapshot"].as_str().unwrap(),
                &key
            )
            .as_slice(),
            b"Synthetic snapshot"
        );
        let summary = frames[3]["payload"]["encrypted_summary"].as_str().unwrap();
        assert!(STANDARD.decode(summary).unwrap().starts_with(b"OM"));
        assert_eq!(
            crypto::decrypt_combined(summary, &[9; 32]).unwrap(),
            "Synthetic summary"
        );
    }
}
#[tokio::test]
async fn revoked_master_operation_and_chat_denial_stop_before_wrapper_send_or_publication() {
    for mode in ["master", "operation", "chat"] {
        let mut peer = Peer::start().await;
        let gate = Arc::new(Gate::default());
        let mut client = fixture(&peer.api, true, Some(gate.clone()));
        let master = client.master_capability().unwrap();
        let operation = client.operation_cancel.clone();
        let authority = client.task_watch_authority.clone();
        let embeds = input();
        let frames = peer.frames.clone();
        let mutate = async {
            gate.entered.notified().await;
            match mode {
                "master" => master.invalidate(),
                "operation" => operation.cancel(),
                "chat" => authority.deny_cached_chat(Some(CHAT)).unwrap(),
                _ => unreachable!(),
            };
            gate.release.notify_one();
        };
        let (result, _) = tokio::join!(
            client.persist_stream_artifacts(
                &mut peer.ws,
                CHAT,
                MESSAGE,
                &[9; 32],
                "",
                &embeds,
                &[]
            ),
            mutate
        );
        assert!(matches!(result, Err(Error::Cancelled | Error::Forbidden)));
        assert!(client.embeds.is_empty() && client.embed_keys.is_empty());
        assert_eq!(client.credential_ack, 0);
        assert!(gate.dropped.load(Ordering::SeqCst));
        assert_eq!(frames.lock().unwrap().len(), 1);
    }
}
#[tokio::test]
async fn dropping_pending_opaque_wrapper_future_releases_scratch_and_publishes_nothing() {
    let mut peer = Peer::start().await;
    let gate = Arc::new(Gate::default());
    let mut client = fixture(&peer.api, true, Some(gate.clone()));
    let embeds = input();
    let mut pending = Box::pin(client.persist_stream_artifacts(
        &mut peer.ws,
        CHAT,
        MESSAGE,
        &[9; 32],
        "",
        &embeds,
        &[],
    ));
    tokio::select! {_ = gate.entered.notified()=>{},_ = &mut pending=>panic!("must suspend inside opaque encrypt")};
    drop(pending);
    assert!(gate.dropped.load(Ordering::SeqCst));
    assert!(client.embeds.is_empty() && client.embed_keys.is_empty());
    assert_eq!(peer.frames.lock().unwrap().len(), 1);
    assert_eq!(client.credential_ack, 0);
}

#[tokio::test]
async fn canonical_replay_accepts_existing_native_fields_without_master_wrap_or_ws_rewrite() {
    let mut peer = Peer::with_canonical(true).await;
    let gate = Arc::new(Gate::default());
    let mut client = fixture(&peer.api, true, Some(gate.clone()));
    let embeds = input();
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        client.persist_stream_artifacts(&mut peer.ws, CHAT, MESSAGE, &[9; 32], "", &embeds, &[]),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(result.len(), 1);
    assert_eq!(result[0].title, "Synthetic artifact");
    assert_eq!(peer.frames.lock().unwrap().len(), 0);
    assert_eq!(client.embeds.len(), 1);
    assert_eq!(client.credential_ack, 0);
    assert!(!gate.dropped.load(Ordering::SeqCst));
    assert!(client.native_master_key().is_err());
}

#[test]
fn decoded_artifact_moves_original_plaintext_allocation_into_guarded_item() {
    let decoded = Plain::new(
        json!({"title":"Synthetic title","payload":"Synthetic private allocation ".repeat(8)}),
    );
    let allocation = decoded["payload"].as_str().unwrap().as_ptr();
    let item = stream_artifact_item(EMBED.into(), "code", decoded);
    assert_eq!(item.id, EMBED);
    assert_eq!(item.title, "Synthetic title");
    assert_eq!(item.category, "code");
    assert_eq!(item.fields["type"], "code");
    assert_eq!(
        item.fields["content"]["payload"].as_str().unwrap().as_ptr(),
        allocation
    );
    assert_eq!(
        item.fields["content"]["payload"].as_str().unwrap(),
        "Synthetic private allocation ".repeat(8)
    );
}
