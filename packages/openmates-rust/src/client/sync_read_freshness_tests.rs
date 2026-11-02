// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
//! Draft real-Client correlated discovery and canonical full-history transactions.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::atomic::{AtomicU64, AtomicUsize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OTHER: &str = "33333333-3333-4333-8333-333333333333";

struct Peer {
    api: String,
    auth: Arc<AtomicUsize>,
    sync: Arc<AtomicUsize>,
    metadata: Arc<AtomicUsize>,
    pages: Arc<AtomicUsize>,
    mode: Arc<AtomicUsize>,
    arrived: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Notify>,
    stop: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}
fn row(id: &str) -> Value {
    json!({"id":id,"messages_v":1,"chat_visibility":"private",
        "encrypted_chat_key":crypto::encrypt_bytes(&[8;32], &[1;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined("Synthetic selected chat", &[8;32]).unwrap()})
}
fn message(id: &str, content: &str) -> Value {
    json!({"id":id,"chat_id":CHAT,"role":"assistant",
        "encrypted_content":crypto::encrypt_combined(content, &[8;32]).unwrap()})
}
async fn request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = vec![];
    loop {
        let mut part = [0; 4096];
        let n = stream.read(&mut part).await.unwrap();
        assert!(n > 0 && data.len() + n < 16384);
        data.extend_from_slice(&part[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..end]);
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|n| n.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if data.len() == end + 4 + length {
                return String::from_utf8(data).unwrap();
            }
        }
    }
}
async fn respond(stream: &mut tokio::net::TcpStream, status: u16, value: Value, cookie: bool) {
    let body = value.to_string();
    let cookie = if cookie {
        "Set-Cookie: rotated=once; HttpOnly\r\n"
    } else {
        ""
    };
    // Cancellation/drop may close this peer's HTTP request after its barrier.
    // Successful read tests independently require the full decoded response.
    let _ = stream.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\n{cookie}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await;
}
impl Peer {
    async fn start() -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let auth = Arc::new(AtomicUsize::new(0));
        let sync = Arc::new(AtomicUsize::new(0));
        let metadata = Arc::new(AtomicUsize::new(0));
        let pages = Arc::new(AtomicUsize::new(0));
        let mode = Arc::new(AtomicUsize::new(0));
        let arrived = Arc::new(tokio::sync::Notify::new());
        let release = Arc::new(tokio::sync::Notify::new());
        let stop = CancellationToken::new();
        let (a, s, m, p, k, ready, resume, stopping) = (
            auth.clone(),
            sync.clone(),
            metadata.clone(),
            pages.clone(),
            mode.clone(),
            arrived.clone(),
            release.clone(),
            stop.clone(),
        );
        let task = tokio::spawn(async move {
            let mut children = tokio::task::JoinSet::new();
            loop {
                let (mut stream, _) = tokio::select! {biased;_=stopping.cancelled()=>break,v=listener.accept()=>v.unwrap()};
                let (a, s, m, p, k, ready, resume) = (
                    a.clone(),
                    s.clone(),
                    m.clone(),
                    p.clone(),
                    k.clone(),
                    ready.clone(),
                    resume.clone(),
                );
                children.spawn(async move {
                    let mut head=[0;8192];
                    let n=loop {let n=stream.peek(&mut head).await.unwrap();assert!(n>0);if head[..n].contains(&b'\n') {break n;}tokio::task::yield_now().await;};
                    let first=String::from_utf8_lossy(&head[..n]);
                    if first.starts_with("GET /v1/ws?") {
                        let mut nonce=None;
                        let mut ws=tokio_tungstenite::accept_hdr_async(stream,|req:&tokio_tungstenite::tungstenite::handshake::server::Request,response|{
                            nonce=url::form_urlencoded::parse(req.uri().query().unwrap().as_bytes()).find(|(name,_)|name=="inventory_request_id").map(|(_,v)|v.into_owned());Ok(response)
                        }).await.unwrap();
                        let lifecycle:Value=serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
                        assert_eq!(lifecycle["type"],"native_client_lifecycle");
                        if let Some(nonce)=nonce {
                            let query:Value=serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
                            assert_eq!(query["type"],"phased_sync_request");assert_eq!(query["payload"]["inventory_request_id"],nonce);
                            s.fetch_add(1,Ordering::SeqCst);
                            let mut frames=vec![
                                json!({"type":"server_capabilities","payload":{"capabilities":[]}}),
                                json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":row(CHAT)},{"chat_details":row(OTHER)}]}}),
                                json!({"type":"recovery_jobs_available","payload":{"jobs":[]}}),
                                json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}),
                                json!({"type":"task_update_jobs_available","payload":{"jobs":[],"complete":true}}),
                                json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
                                json!({"type":"phased_sync_complete","payload":{"phase":"all"}}),
                            ];
                            for frame in &mut frames {frame["payload"]["inventory_request_id"]=json!(nonce);ws.send(tokio_tungstenite::tungstenite::Message::Text(frame.to_string().into())).await.unwrap();}
                        }
                        while let Some(event)=ws.next().await {
                            let event=event.unwrap();if event.is_close() {break;}
                            ws.send(event).await.unwrap();
                        }
                        let _=ws.close(None).await;
                        return;
                    }
                    let req=request(&mut stream).await;
                    assert!(req.to_ascii_lowercase().contains("x-openmates-sdk: rust"));
                    let mode=k.load(Ordering::SeqCst);
                    if req.starts_with("POST /v1/auth/session ") {
                        a.fetch_add(1,Ordering::SeqCst);respond(&mut stream,200,json!({"success":true,"ws_token":"synthetic","user":{"id":"owner"}}),false).await;
                    } else if req.starts_with("POST /v1/chats/metadata/batch ") {
                        assert_eq!(serde_json::from_str::<Value>(req.split_once("\r\n\r\n").unwrap().1).unwrap(),json!({"chat_ids":[CHAT]}));
                        let mut metadata=row(CHAT);
                        if mode==8 {
                            metadata.as_object_mut().unwrap().remove("encrypted_chat_key");
                            metadata["encrypted_draft_md"]=json!(crypto::encrypt_combined("draft",&[1;32]).unwrap());
                            metadata["encrypted_title"]=json!(crypto::encrypt_combined("Draft title",&[1;32]).unwrap());
                        }
                        m.fetch_add(1,Ordering::SeqCst);respond(&mut stream,200,json!({"chats":[metadata]}),mode==5).await;
                    } else {
                        assert!(req.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?")));
                        let index=p.fetch_add(1,Ordering::SeqCst);
                        if mode==6 && index%2==1 {ready.notify_one();resume.notified().await;}
                        if mode==1 {return;} // Offline live page, never a live seal.
                        if mode==2 {respond(&mut stream,200,json!({"messages":[]}),false).await;return;}
                        if mode==3 {respond(&mut stream,200,json!({"messages":[{"id":"invalid","role":"assistant","encrypted_content":"broken"}],"has_more_before":false}),false).await;return;}
                        if mode==4 {respond(&mut stream,200,json!({"messages":[],"has_more_before":true,"start_cursor":{"created_at":1,"message_id":"same"}}),false).await;return;}
                        if mode==7 {
                            let mut invalid=message("bad-mapping","valid content");
                            invalid["encrypted_pii_mappings"]=json!(crypto::encrypt_combined("not-json",&[8;32]).unwrap());
                            respond(&mut stream,200,json!({"messages":[invalid],"has_more_before":false}),false).await;return;
                        }
                        if mode==9 {
                            respond(&mut stream,200,json!({"chat_id":CHAT,"messages":[],"has_more_before":false,"has_more_after":false,
                                "start_cursor":null,"end_cursor":null,"anchor_found":false,"oversized_message":false,
                                "oversized_message_cursor":null,"payload_bytes":0}),false).await;return;
                        }
                        if mode==10 {
                            respond(&mut stream,200,json!({"messages":[],"has_more_before":true,"start_cursor":{"created_at":index+1,"message_id":format!("cursor-{index}")}}),false).await;return;
                        }
                        if index%2==0 {
                            assert!(req.contains("direction=latest"));
                            respond(&mut stream,200,json!({"messages":[message("recent","recent plaintext")],"has_more_before":true,"start_cursor":{"created_at":2,"message_id":"recent"}}),false).await;
                        } else {
                            assert!(req.contains("direction=before"));
                            respond(&mut stream,200,json!({"messages":[message("older","older plaintext")],"has_more_before":false}),false).await;
                        }
                    }
                });
            }
            children.abort_all();
            while let Some(result) = children.join_next().await {
                if let Err(error) = result {
                    assert!(error.is_cancelled());
                }
            }
        });
        Self {
            api,
            auth,
            sync,
            metadata,
            pages,
            mode,
            arrived,
            release,
            stop,
            task,
        }
    }
    fn client(&self, ticks: &Arc<AtomicU64>, cancel: &CancellationToken) -> Client {
        let mut session = crate::client::sdk_boundary_tests::session();
        session.api_url = self.api.clone();
        let mut c = Client::new(&self.api, Some(session)).unwrap();
        c.set_operation_cancel(cancel.clone());
        let ticks = ticks.clone();
        c.set_chat_cache_clock_provider(Some(Arc::new(move || {
            CacheClockEvidence::from_platform(
                "boot".into(),
                ticks.load(Ordering::SeqCst),
                ticks.load(Ordering::SeqCst),
            )
        })));
        c
    }
    async fn proof(&self, c: &mut Client, cancel: &CancellationToken) -> FreshChatInventory {
        c.set_foreground_completion_recovery(true).unwrap();
        let (jobs, proof) = c
            .completion_recovery_jobs_with_inventory(cancel)
            .await
            .unwrap();
        assert!(jobs.is_empty());
        c.set_foreground_completion_recovery(false).unwrap();
        proof.expect("actual correlated issuer")
    }
    async fn finish(self) {
        self.stop.cancel();
        self.task.await.unwrap();
    }
}
#[tokio::test]
async fn correlated_full_history_rebinds_final_snapshot_at_original_clock_only() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let proof = peer.proof(&mut c, &cancel).await;
        ticks.store(2000, Ordering::SeqCst);
        let chat = c
            .open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
            .await
            .unwrap();
        assert_eq!(
            chat.messages
                .iter()
                .map(|m| m.content.as_str())
                .collect::<Vec<_>>(),
            vec!["older plaintext", "recent plaintext"]
        );
        assert!(c.try_cached_default_chat_list(false).unwrap().is_some());
        let snapshot = c.ciphertext_snapshot();
        assert_eq!(snapshot["history"][CHAT].as_array().unwrap().len(), 2);
        let encoded = snapshot.to_string();
        assert!(!encoded.contains("older plaintext") && !encoded.contains("recent plaintext"));
        let mut restored = peer.client(&ticks, &cancel);
        restored.user = c.user.clone();
        restored
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .unwrap();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_some()
        );
        ticks.store(301_001, Ordering::SeqCst);
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        assert_eq!(peer.auth.load(Ordering::SeqCst), 1);
        assert_eq!(peer.sync.load(Ordering::SeqCst), 1);
        assert_eq!(peer.metadata.load(Ordering::SeqCst), 1);
        assert_eq!(peer.pages.load(Ordering::SeqCst), 2);
        peer.finish().await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn live_failures_missing_terminal_cookie_rotation_and_loop_failure_never_seal() {
    tokio::time::timeout(Duration::from_secs(10), async {
        for mode in [1, 2, 3, 4, 5, 7, 8] {
            let peer = Peer::start().await;
            let cancel = CancellationToken::new();
            let ticks = Arc::new(AtomicU64::new(1000));
            let mut c = peer.client(&ticks, &cancel);
            let proof = peer.proof(&mut c, &cancel).await;
            c.history
                .insert(CHAT.into(), vec![message("cached", "offline retained")]);
            // History mutation above is intentionally invalid for the discovery
            // proof; take a fresh complete discovery rather than forging it.
            let proof = if mode == 1 {
                drop(proof);
                peer.proof(&mut c, &cancel).await
            } else {
                c.history.remove(CHAT);
                proof
            };
            peer.mode.store(mode, Ordering::SeqCst);
            let result = c
                .open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
                .await;
            if matches!(mode, 1 | 2 | 5 | 8) {
                assert!(result.is_ok());
            } else {
                assert!(result.is_err());
            }
            assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
            assert!(c.ciphertext_snapshot().get("chat_list_freshness").is_none());
            peer.finish().await;
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn foreign_prepared_socket_traffic_during_page_disqualifies_without_breaking_read() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let mut foreign = c.socket().await.unwrap();
        let proof = peer.proof(&mut c, &cancel).await;
        peer.mode.store(6, Ordering::SeqCst);
        let arrived = peer.arrived.clone();
        let release = peer.release.clone();
        let mode = peer.mode.clone();
        let traffic = tokio::spawn(async move {
            arrived.notified().await;
            crate::client::transport::send(&mut foreign, "read_probe", json!({}))
                .await
                .unwrap();
            let _ = crate::client::transport::receive(&mut foreign)
                .await
                .unwrap();
            mode.store(0, Ordering::SeqCst);
            release.notify_one();
            let _ = foreign.close(None).await;
        });
        let result = c
            .open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
            .await;
        traffic.await.unwrap();
        assert_eq!(result.unwrap().messages.len(), 2);
        assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
        peer.finish().await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn cancelled_last_page_never_publishes_receipt() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let proof = peer.proof(&mut c, &cancel).await;
        peer.mode.store(6, Ordering::SeqCst);
        let arrived = peer.arrived.clone();
        let cancelled = cancel.clone();
        let release = peer.release.clone();
        let cancellation = tokio::spawn(async move {
            arrived.notified().await;
            cancelled.cancel();
            release.notify_one();
        });
        assert!(matches!(
            c.open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
                .await,
            Err(Error::Cancelled)
        ));
        cancellation.await.unwrap();
        assert!(c.ciphertext_snapshot().get("chat_list_freshness").is_none());
        peer.finish().await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn actual_issued_inventory_rejects_foreign_mutated_restored_and_cancelled_contexts() {
    tokio::time::timeout(Duration::from_secs(15), async {
        for change in 0..18 {
            let peer = Peer::start().await;
            let cancel = CancellationToken::new();
            let ticks = Arc::new(AtomicU64::new(1000));
            let mut c = peer.client(&ticks, &cancel);
            let proof = peer.proof(&mut c, &cancel).await;
            match change {
                0 => c.session.as_mut().unwrap().master_key[0] ^= 1,
                1 => c.session.as_mut().unwrap().session_id = "other-session".into(),
                2 => {
                    c.cookies.insert("another-cookie".into(), "another".into());
                }
                3 => c.session.as_mut().unwrap().ws_token = Some("other-token".into()),
                4 => c.user = json!({"id":"other-owner"}),
                5 => c.credential_revision += 1,
                6 => c.generation += 1,
                7 => c.invalidate_chat_inventory_proofs(),
                8 => {
                    c.wrappers.push(json!({"synthetic":"different-wrapper"}));
                }
                9 => {
                    c.set_identity(ClientIdentity::Cli);
                    c.set_identity(ClientIdentity::Rust);
                }
                10 => {
                    c.set_team(Some("11111111-1111-4111-8111-111111111111"))
                        .unwrap();
                    c.set_team(None).unwrap();
                }
                11 => {
                    let snapshot = c.ciphertext_snapshot();
                    c.restore_ciphertext_snapshot(&snapshot).unwrap();
                }
                12 => {
                    cancel.cancel();
                }
                13 => {
                    c.operation_cancel.cancel();
                }
                14 => {
                    let mut foreign = peer.client(&ticks, &cancel);
                    foreign.user = c.user.clone();
                    foreign.chats = c.chats.clone();
                    c = foreign;
                }
                15 => {
                    c.chats.get_mut(CHAT).unwrap()["chat_visibility"] = json!("direct");
                }
                16 => c.session.as_mut().unwrap().paired_session_expires_at = Some(1),
                _ => c.session.as_mut().unwrap().created_at += 1,
            }
            let result = ReadFreshnessTransaction::begin(&c, CHAT, proof, &cancel);
            assert!(
                matches!(result, Ok(None) | Err(Error::Cancelled | Error::Expired)),
                "mutated context {change}"
            );
            assert!(c.ciphertext_snapshot().get("chat_list_freshness").is_none());
            peer.finish().await;
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn unselected_ciphertext_mutation_or_missing_clock_prevents_warm_reuse() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let proof = peer.proof(&mut c, &cancel).await;
        let mut transaction = ReadFreshnessTransaction::begin(&c, CHAT, proof, &cancel)
            .unwrap()
            .unwrap();
        c.chats.get_mut(OTHER).unwrap()["messages_v"] = json!(2);
        transaction.terminal = true;
        transaction.commit(&mut c, CHAT).unwrap();
        assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
        c.set_chat_cache_clock_provider(None);
        let proof = peer.proof(&mut c, &cancel).await;
        c.open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
            .await
            .unwrap();
        assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
        peer.finish().await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn dropping_last_page_read_future_cannot_publish_partial_history_receipt() {
    tokio::time::timeout(Duration::from_secs(8),async {
        let peer=Peer::start().await;let cancel=CancellationToken::new();let ticks=Arc::new(AtomicU64::new(1000));let mut c=peer.client(&ticks,&cancel);
        let proof=peer.proof(&mut c,&cancel).await;peer.mode.store(6,Ordering::SeqCst);
        {
            let read=c.open_chat_with_fresh_chat_inventory(CHAT,proof,&cancel);tokio::pin!(read);
            tokio::select!{biased;_=peer.arrived.notified()=>{},result=&mut read=>panic!("read finished before bounded final-page barrier: {}",result.is_ok())};
        }
        peer.release.notify_one();assert!(c.ciphertext_snapshot().get("chat_list_freshness").is_none());peer.finish().await;
    }).await.unwrap();
}

#[tokio::test]
async fn terminal_viewing_page_cannot_consume_or_mint_global_inventory_freshness() {
    tokio::time::timeout(Duration::from_secs(8), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let proof = peer.proof(&mut c, &cancel).await;
        peer.mode.store(9, Ordering::SeqCst);
        let page = c
            .chat_message_window(
                CHAT,
                crate::client::message_window::MessageWindowOptions::default(),
            )
            .await
            .unwrap();
        assert!(!page.history_complete);
        assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
        assert!(
            ReadFreshnessTransaction::begin(&c, CHAT, proof, &cancel)
                .unwrap()
                .is_none()
        );
        assert_eq!(peer.pages.load(Ordering::SeqCst), 1);
        peer.finish().await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn nonterminal_hundred_page_bound_never_seals_or_loops_forever() {
    tokio::time::timeout(Duration::from_secs(15), async {
        let peer = Peer::start().await;
        let cancel = CancellationToken::new();
        let ticks = Arc::new(AtomicU64::new(1000));
        let mut c = peer.client(&ticks, &cancel);
        let proof = peer.proof(&mut c, &cancel).await;
        peer.mode.store(10, Ordering::SeqCst);
        assert!(matches!(
            c.open_chat_with_fresh_chat_inventory(CHAT, proof, &cancel)
                .await,
            Err(Error::Invalid(_))
        ));
        assert_eq!(peer.pages.load(Ordering::SeqCst), 100);
        assert!(c.try_cached_default_chat_list(false).unwrap().is_none());
        peer.finish().await;
    })
    .await
    .unwrap();
}
