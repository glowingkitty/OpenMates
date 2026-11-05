//! Inert synthetic cleanup regressions, authored without execution.
//! Probe Drop observes typed fields only after the real shared wiper runs.
//! No allocator inspection, credentials, product account or runtime hooks exist.
//! The held-page case exercises the actual HTTP open path on owned loopback.
//! Original authority, read shape and output assertions remain unchanged.
// contract-test-file: tooling
use super::*;
use std::future::Future;
use std::sync::{Arc, Mutex};
fn message() -> Message {
    Message {
        id: "synthetic-row".into(),
        role: "user".into(),
        content: "PRIVATE_CONTENT".into(),
        sender: "PRIVATE_SENDER".into(),
        thinking: "PRIVATE_THINKING".into(),
        embeds: vec![Item {
            id: "embed".into(),
            title: "PRIVATE_EMBED".into(),
            fields: json!({"nested":[{"text":"PRIVATE_VALUE"}]}),
            ..Item::default()
        }],
    }
}
struct Probe {
    chat: Chat,
    observed: Arc<Mutex<bool>>,
}
impl Wipe for Probe {
    fn wipe(&mut self) {
        self.chat.wipe();
    }
}
impl Drop for Probe {
    fn drop(&mut self) {
        *self.observed.lock().unwrap() = self.chat.id.is_empty()
            && self.chat.title.is_empty()
            && self.chat.messages.iter().all(|m| {
                m.id.is_empty()
                    && m.role.is_empty()
                    && m.content.is_empty()
                    && m.sender.is_empty()
                    && m.thinking.is_empty()
                    && m.embeds.is_empty()
            });
    }
}
#[test]
fn owned_guard_wipes_nested_chat_on_rejection_but_accepted_move_is_exact() {
    let observed = Arc::new(Mutex::new(false));
    {
        let _guard = Plain::new(Probe {
            chat: Chat {
                id: "chat".into(),
                title: "PRIVATE_TITLE".into(),
                messages: vec![message()],
                ..Chat::default()
            },
            observed: observed.clone(),
        });
    }
    assert!(*observed.lock().unwrap());
    let original = message();
    let expected = serde_json::to_value(&original).unwrap();
    let accepted = Plain::new(original).into_inner();
    assert_eq!(serde_json::to_value(&accepted).unwrap(), expected);
}
#[test]
fn pii_and_item_scratch_wipers_cover_duplicate_nested_values() {
    let mut item = Item {
        title: "PRIVATE_TITLE".into(),
        description: "PRIVATE_SUMMARY".into(),
        category: "PRIVATE_CATEGORY".into(),
        fields: json!({"chat_list_title":"PRIVATE_TITLE"}),
        ..Item::default()
    };
    item.wipe();
    assert!(item.title.is_empty() && item.description.is_empty() && item.category.is_empty());
    assert!(!item.fields.to_string().contains("PRIVATE_"));
    let mut maps = vec![
        json!({"placeholder":"[PERSON_1]","original":"PRIVATE_PERSON","nested":["PRIVATE_OTHER"]}),
    ];
    maps.wipe();
    assert!(!serde_json::to_string(&maps).unwrap().contains("PRIVATE_"));
    let mut text = "PRIVATE_OLD".to_owned();
    replace_text(&mut text, "accepted".into());
    assert_eq!(text, "accepted");
}
#[tokio::test]
async fn dropping_pending_future_runs_real_owned_guard_cleanup() {
    use std::task::Poll;
    let observed = Arc::new(Mutex::new(false));
    let mut pending = Box::pin(async {
        let guard = Plain::new(Probe {
            chat: Chat {
                title: "PRIVATE_TITLE".into(),
                messages: vec![message()],
                ..Chat::default()
            },
            observed: observed.clone(),
        });
        std::future::pending::<()>().await;
        guard.into_inner()
    });
    std::future::poll_fn(|cx| {
        assert!(pending.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    assert!(!*observed.lock().unwrap());
    drop(pending);
    assert!(*observed.lock().unwrap());
}
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const MSG: &str = "33333333-3333-4333-8333-333333333333";
fn client(endpoint: &str) -> Client {
    Client::new(
        endpoint,
        Some(Session {
            api_url: endpoint.into(),
            session_id: "synthetic".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn metadata() -> Value {
    json!({"id":CHAT,"encrypted_chat_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("PRIVATE_TITLE",&[9;32]).unwrap()})
}
fn row() -> Value {
    json!({"id":MSG,"chat_id":CHAT,"created_at":1,"role":"user","encrypted_content":crypto::encrypt_combined("PRIVATE_CONTENT",&[9;32]).unwrap()})
}
#[test]
fn later_field_failure_refuses_partly_decrypted_message_and_item() {
    let mut seen = Default::default();
    let mut raw = row();
    raw["encrypted_sender_name"] = json!("invalid");
    assert!(matches!(
        super::super::sync::decode_chat_message(&raw, CHAT, &[9; 32], &mut seen),
        Err(Error::Crypto)
    ));
    let client = client("http://127.0.0.1:9");
    let mut raw = metadata();
    raw["encrypted_chat_summary"] = json!("invalid");
    assert!(matches!(
        client.chat_item(&raw, &[9; 32]),
        Err(Error::Crypto)
    ));
}
#[tokio::test]
async fn cached_decode_later_row_failure_keeps_ciphertext_and_no_plaintext_result() {
    let mut client = client("http://127.0.0.1:9");
    client.chats.insert(CHAT.into(), metadata());
    let mut bad = row();
    bad["id"] = json!("44444444-4444-4444-8444-444444444444");
    bad["encrypted_sender_name"] = json!("invalid");
    client.history.insert(CHAT.into(), vec![row(), bad]);
    let before = client.ciphertext_snapshot();
    assert!(matches!(
        client.cached_chat_with_capability(CHAT).await,
        Err(Error::Crypto)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.credential_ack, 0);
}
async fn request(stream: &mut tokio::net::TcpStream) -> String {
    use tokio::io::AsyncReadExt;
    let mut bytes = vec![];
    loop {
        let mut chunk = [0u8; 1024];
        let size = stream.read(&mut chunk).await.unwrap();
        assert!(size > 0);
        bytes.extend_from_slice(&chunk[..size]);
        assert!(bytes.len() <= 16384);
        if let Some(i) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            let header = String::from_utf8_lossy(&bytes[..i]);
            let length = header
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .and_then(|v| v.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if bytes.len() >= i + 4 + length {
                return String::from_utf8(bytes).unwrap();
            }
        }
    }
}
async fn reply(stream: &mut tokio::net::TcpStream, value: Value) {
    use tokio::io::AsyncWriteExt;
    let body = value.to_string();
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    );
    let _ = stream.write_all(response.as_bytes()).await;
}
#[tokio::test]
async fn actual_open_retains_owned_plaintext_while_next_page_pending_and_refuses_cancel_deny() {
    use std::task::Poll;
    for mode in 0..3 {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let (entered, waiting) = tokio::sync::oneshot::channel();
        let (release, held) = tokio::sync::oneshot::channel();
        let server = tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            let req = request(&mut socket).await;
            assert!(req.starts_with("POST /v1/chats/metadata/batch "));
            assert!(req.contains(CHAT));
            reply(&mut socket, json!({"chats":[metadata()]})).await;
            drop(socket);
            let (mut socket, _) = listener.accept().await.unwrap();
            let req = request(&mut socket).await;
            assert!(req.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?")));
            reply(&mut socket,json!({"messages":[row()],"has_more_before":true,"start_cursor":{"created_at":1,"message_id":MSG}})).await;
            drop(socket);
            let (mut socket, _) = listener.accept().await.unwrap();
            let req = request(&mut socket).await;
            assert!(req.contains("before_timestamp=1") && req.contains(MSG));
            entered.send(()).unwrap();
            let _ = held.await;
            reply(&mut socket, json!({"messages":[],"has_more_before":false})).await;
        });
        let mut client = client(&endpoint);
        let cancel = client.operation_cancel.clone();
        let owner = client.task_watch_authority.clone();
        let mut read = Box::pin(client.open_chat(CHAT));
        tokio::time::timeout(Duration::from_secs(4),async{tokio::select!{biased;result=&mut read=>panic!("open completed before held page: {}",result.is_ok()),result=waiting=>result.unwrap()}}).await.unwrap();
        std::future::poll_fn(|cx| {
            assert!(read.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        if mode == 0 {
            drop(read);
            release.send(()).unwrap();
        } else {
            if mode == 1 {
                cancel.cancel();
            } else {
                owner.deny_cached_chat(Some(CHAT)).unwrap();
            }
            release.send(()).unwrap();
            assert!(matches!(read.await, Err(Error::Cancelled)));
        }
        server.await.unwrap();
        assert!(!client.history.contains_key(CHAT));
        assert_eq!(client.credential_ack, 0);
    }
}

#[test]
fn complete_saved_output_wipes_chat_metadata_mappings_and_exact_message() {
    let key = [9; 32];
    let raw = row();
    let model = message();
    let chat_metadata =
        super::super::saved_chat_read::metadata::chat(&metadata(), CHAT, &key).unwrap();
    let message_metadata =
        super::super::saved_chat_read::metadata::message(&raw, &model, CHAT, &key).unwrap();
    let mut exact = SavedChatExactMessage {
        message: model.clone(),
        chat_metadata: chat_metadata.clone(),
        message_metadata: message_metadata.clone(),
        pii_mappings: Some(vec![json!({"original":"PRIVATE_PERSON"})]),
        content_mode: super::super::saved_chat_read::SavedChatContentMode::Stored,
        pii_restoration: "stored".into(),
        payload_bytes: 1,
        history_complete: false,
    };
    exact.wipe();
    assert!(!serde_json::to_string(&exact).unwrap().contains("PRIVATE_"));
    let mut all = SavedChatRead {
        window: SavedChatReadPage {
            chat: Chat {
                title: "PRIVATE_TITLE".into(),
                messages: vec![model],
                ..Chat::default()
            },
            has_more_before: true,
            has_more_after: false,
            anchor_found: false,
            start_cursor: None,
            end_cursor: None,
            server_message_count: None,
            messages_version: None,
            oversized_message: false,
            oversized_message_cursor: None,
            payload_bytes: 1,
            pii_restoration: "stored".into(),
            history_complete: false,
        },
        chat_metadata,
        message_metadata: vec![message_metadata],
        pii_mappings_by_message_id: std::iter::once((
            MSG.to_owned(),
            vec![json!({"original":"PRIVATE_PERSON"})],
        ))
        .collect(),
        content_mode: super::super::saved_chat_read::SavedChatContentMode::Stored,
        pages_read: 1,
    };
    all.wipe();
    assert!(!serde_json::to_string(&all).unwrap().contains("PRIVATE_"));
}
#[test]
fn typed_metadata_rejects_later_field_failure_after_title_or_sender_decode() {
    let mut raw = metadata();
    raw["encrypted_chat_summary"] = json!("invalid");
    assert!(matches!(
        super::super::saved_chat_read::metadata::chat(&raw, CHAT, &[9; 32]),
        Err(Error::Crypto)
    ));
    let mut raw = row();
    raw["encrypted_sender_name"] =
        json!(crypto::encrypt_combined("PRIVATE_SENDER", &[9; 32]).unwrap());
    raw["encrypted_category"] = json!("invalid");
    assert!(matches!(
        super::super::saved_chat_read::metadata::message(&raw, &message(), CHAT, &[9; 32]),
        Err(Error::Crypto)
    ));
}

#[test]
fn cached_window_wiper_preserves_public_model_move_semantics() {
    let mut window = super::super::monitor::cached_view::CachedChatWindow {
        chat: Chat {
            title: "PRIVATE_TITLE".into(),
            messages: vec![message()],
            ..Chat::default()
        },
        has_more_before: None,
        history_complete: false,
        cached: true,
        refreshing: true,
        pii_restoration: "page_local",
    };
    window.wipe();
    assert!(
        window.chat.title.is_empty() && window.chat.messages.iter().all(|m| m.content.is_empty())
    );
    let super::super::monitor::cached_view::CachedChatWindow { chat, .. } = window;
    assert!(chat.title.is_empty());
}

struct ChatModelsProbe {
    models: super::super::monitor::ChatModels,
    observed: Arc<Mutex<bool>>,
}
impl Wipe for ChatModelsProbe { fn wipe(&mut self) { self.models.wipe(); } }
impl Drop for ChatModelsProbe {
    fn drop(&mut self) {
        let items=self.models.items.iter().all(|item|item.id.is_empty() && item.title.is_empty() && item.description.is_empty() && item.status.is_empty() && item.category.is_empty() && item.fields.is_null());
        let selected=match &self.models.selection {
            super::super::monitor::ChatSelectionUpdate::Updated(chat) | super::super::monitor::ChatSelectionUpdate::CacheSettled(chat)=>chat.id.is_empty() && chat.title.is_empty() && chat.messages.iter().all(|row|row.content.is_empty() && row.sender.is_empty() && row.thinking.is_empty() && row.embeds.is_empty()),
            _=>false,
        };
        *self.observed.lock().unwrap()=items&&selected;
    }
}
#[test]
fn guarded_models_wipe_nested_selected_chat_on_failed_stage_abandoned_owner_and_accepted_move_is_exact() {
    for cached in [false,true] {
        let observed=Arc::new(Mutex::new(false));
        let chat=Chat{id:"private-chat".into(),title:"private-title".into(),messages:vec![message()],..Chat::default()};
        let models=super::super::monitor::ChatModels{
            items:vec![Item{id:"private-item".into(),title:"private-item-title".into(),description:"private-description".into(),fields:json!({"nested":{"body":"PRIVATE_BODY"}}),..Item::default()}],
            selection:if cached{super::super::monitor::ChatSelectionUpdate::CacheSettled(chat)}else{super::super::monitor::ChatSelectionUpdate::Updated(chat)},
        };
        // ChatRefresh and ChatPublication own this SAME typed Plain<ChatModels>
        // guard. Their failed commit/abandoned-queue paths cannot disarm it.
        drop(Plain::new(ChatModelsProbe{models,observed:observed.clone()}));
        assert!(*observed.lock().unwrap());
    }
    let models=super::super::monitor::ChatModels{items:vec![],selection:super::super::monitor::ChatSelectionUpdate::CacheSettled(Chat{id:"accepted".into(),messages:vec![message()],..Chat::default()})};
    let accepted=Plain::new(models).into_inner();
    assert!(matches!(&accepted.selection,super::super::monitor::ChatSelectionUpdate::CacheSettled(chat) if chat.id=="accepted" && chat.messages[0].content=="PRIVATE_CONTENT"));
}
