//! The seeded-cache fixture and the metadata mirrors: a `ViewModelCore` started from `test_support_seed_cached_account` shows the cached list offline and, once admitted, the cached window, both with row and message metadata; refusals of bad counts.
use crate::view_core_tests::{Events, Keychain, NAME, private_dir};
use crate::view_window_tests::{core, read_request, respond, windows};
use crate::*;
use serde_json::json;
use std::path::Path;
use std::sync::{Arc, Mutex};
use tokio::io::AsyncWriteExt;

/// Nothing listens on the discard port: every request fails offline.
const OFFLINE_API: &str = "http://127.0.0.1:9";

/// The most recently edited seeded chat (it holds the requested messages).
const FIRST_CHAT: &str = "00000000-0000-4000-8000-000000000001";

async fn seed(dir: &Path, api: &str, chats: u32, messages: u32) -> Vec<u8> {
    let (container, api) = (dir.to_str().unwrap().to_owned(), api.to_owned());
    tokio::task::spawn_blocking(move || {
        test_support_seed_cached_account(api, container, NAME.into(), chats, messages)
    })
    .await
    .unwrap()
    .unwrap()
}

fn keychain(payload: Vec<u8>) -> Arc<Keychain> {
    Arc::new(Keychain {
        payload: Mutex::new(Some(payload)),
        acknowledge: true,
        ..Keychain::default()
    })
}

#[tokio::test(flavor = "multi_thread")]
async fn a_seeded_cache_starts_offline_with_the_cached_list_and_row_metadata() {
    let dir = private_dir();
    let payload = seed(dir.path(), OFFLINE_API, 3, 4).await;
    let events = Arc::new(Events::default());
    let core = core(dir.path(), OFFLINE_API, &keychain(payload), &events);
    let started = core.start(None).await;
    assert_eq!(started, Err(CoreError::Offline), "{:?}", events.all());
    let all = events.all();
    assert!(matches!(
        all[0],
        ViewEventRecord::Session {
            event: SessionEventRecord::Restored { .. }
        }
    ));
    let ViewEventRecord::ChatList { rows, completeness } = &all[1] else {
        panic!("cached list expected: {all:?}");
    };
    assert_eq!(*completeness, ListCompletenessRecord::Cached);
    let titles: Vec<&str> = rows.iter().map(|row| row.title.as_str()).collect();
    assert_eq!(
        titles,
        ["Synthetic chat 1", "Synthetic chat 2", "Synthetic chat 3"]
    );
    let first = &rows[0].metadata;
    assert_eq!(first.icon.as_deref(), Some("message-circle"));
    assert_eq!(first.last_edited_at, Some(1_700_000_180));
    assert_eq!(first.last_message_at, Some(1_700_000_180));
    // Facts the seeded rows do not carry stay `None`.
    assert_eq!(first.parent_id, None);
    assert_eq!(first.budget_limit, None);
    assert_eq!(first.draft_preview, None);
    assert_eq!(first.team_id, None);
}

#[tokio::test(flavor = "multi_thread")]
async fn an_unadmitted_seeded_core_refuses_to_open_a_chat() {
    let dir = private_dir();
    let payload = seed(dir.path(), OFFLINE_API, 2, 4).await;
    let events = Arc::new(Events::default());
    let core = core(dir.path(), OFFLINE_API, &keychain(payload), &events);
    let _offline = core.start(None).await;
    let before = events.all().len();
    // Window commands need an admitted session (`ViewModelCore.openChat`).
    assert_eq!(
        core.open_chat(5, FIRST_CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(events.all().len(), before);
}

/// Loopback API that admits the session (`POST /v1/auth/session`) and
/// leaves every chat request unanswered (offline for chat data).
async fn admitting_api() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            tokio::spawn(async move {
                let request = read_request(&mut stream).await;
                if request.starts_with("POST /v1/auth/session ") {
                    let body = json!({"success": true, "ws_token": "synthetic",
                        "user": {"id": "synthetic-user"}});
                    let _ = stream.write_all(respond(&body).as_bytes()).await;
                }
            });
        }
    });
    url
}

#[tokio::test(flavor = "multi_thread")]
async fn an_admitted_seeded_chat_opens_from_the_cache_with_message_metadata() {
    let dir = private_dir();
    let api = admitting_api().await;
    let payload = seed(dir.path(), &api, 2, 4).await;
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &api, &keychain(payload), &events);
    core.start(None).await.unwrap();
    let before = events.all().len();
    let _strict = core.open_chat(5, FIRST_CHAT.into(), None).await;
    let shown = windows(&events.all()[before..]);
    let (request, window) = shown.first().expect("the cached window is shown first");
    assert_eq!(*request, 5);
    assert_eq!(window.source, ChatWindowSourceRecord::Cached);
    assert_eq!(window.messages.len(), 4);
    assert_eq!(window.messages[0].content, "Synthetic question 1");
    assert_eq!(window.messages[1].content, "Synthetic answer 1");
    let reply = &window.messages[1].metadata;
    assert_eq!(reply.created_at, Some(1_700_000_001));
    assert_eq!(reply.model_name.as_deref(), Some("synthetic-model"));
    assert_eq!(reply.category.as_deref(), Some("general_knowledge"));
    assert_eq!(
        reply.user_message_id.as_deref(),
        Some(window.messages[0].id.as_str())
    );
    assert_eq!(reply.stored_status.as_deref(), Some("synced"));
    assert!(reply.pii_mappings.is_empty());
    assert_eq!(window.messages[0].metadata.model_name, None);
    assert_eq!(window.has_more_after, None);
}

#[tokio::test(flavor = "multi_thread")]
async fn the_fixture_refuses_empty_and_oversized_seeds() {
    let dir = private_dir();
    let container = dir.path().to_str().unwrap().to_owned();
    let refused = tokio::task::spawn_blocking(move || {
        [(0, 1), (501, 1), (1, 2_001)].map(|(chats, messages)| {
            test_support_seed_cached_account(
                OFFLINE_API.into(),
                container.clone(),
                NAME.into(),
                chats,
                messages,
            )
        })
    })
    .await
    .unwrap();
    assert!(
        refused
            .iter()
            .all(|result| matches!(result, Err(CoreError::Invalid { .. })))
    );
}

#[test]
fn metadata_mirrors_map_every_field_one_to_one() {
    use openmates_sdk::view_model::{ChatRowMetadata, MessageMetadata, PiiMapping};
    let row = ChatRowMetadata {
        icon: Some("hammer".into()),
        active_focus_id: Some("focus".into()),
        parent_id: Some("parent".into()),
        is_sub_chat: Some(true),
        team_id: Some("team".into()),
        is_shared: Some(false),
        is_private: Some(true),
        is_hidden: Some(false),
        last_message_at: Some(1),
        last_edited_at: Some(2),
        budget_limit: Some(3),
        budget_spent: Some(4),
        draft_v: Some(5),
        draft_preview: Some("draft".into()),
    };
    assert_eq!(
        ChatRowMetadataRecord::from(row),
        ChatRowMetadataRecord {
            icon: Some("hammer".into()),
            active_focus_id: Some("focus".into()),
            parent_id: Some("parent".into()),
            is_sub_chat: Some(true),
            team_id: Some("team".into()),
            is_shared: Some(false),
            is_private: Some(true),
            is_hidden: Some(false),
            last_message_at: Some(1),
            last_edited_at: Some(2),
            budget_limit: Some(3),
            budget_spent: Some(4),
            draft_v: Some(5),
            draft_preview: Some("draft".into()),
        }
    );
    let message = MessageMetadata {
        created_at: Some(1),
        server_message_id: Some("server".into()),
        client_message_id: Some("client".into()),
        user_message_id: Some("user".into()),
        stored_status: Some("synced".into()),
        model_name: Some("model".into()),
        category: Some("category".into()),
        has_thinking: Some(true),
        thinking_token_count: Some(7),
        queue_revision: Some(2),
        queue_mode: Some("mode".into()),
        queue_dispatch_status: Some("status".into()),
        queue_dispatch_mode: Some("dispatch".into()),
        queue_dispatch_task_id: Some("task".into()),
        pii_mappings: vec![PiiMapping {
            placeholder: "[EMAIL_1]".into(),
            original: "user@example.org".into(),
            kind: "EMAIL".into(),
        }],
    };
    assert_eq!(
        MessageMetadataRecord::from(message),
        MessageMetadataRecord {
            created_at: Some(1),
            server_message_id: Some("server".into()),
            client_message_id: Some("client".into()),
            user_message_id: Some("user".into()),
            stored_status: Some("synced".into()),
            model_name: Some("model".into()),
            category: Some("category".into()),
            has_thinking: Some(true),
            thinking_token_count: Some(7),
            queue_revision: Some(2),
            queue_mode: Some("mode".into()),
            queue_dispatch_status: Some("status".into()),
            queue_dispatch_mode: Some("dispatch".into()),
            queue_dispatch_task_id: Some("task".into()),
            pii_mappings: vec![PiiMappingRecord {
                placeholder: "[EMAIL_1]".into(),
                original: "user@example.org".into(),
                kind: "EMAIL".into(),
            }],
        }
    );
    assert_eq!(
        MessageMetadataRecord::from(MessageMetadata::default()),
        MessageMetadataRecord::default()
    );
}

#[test]
fn a_message_update_mirrors_request_chat_and_the_whole_message() {
    use openmates_sdk::view_model::{
        MessageMetadata, MessageRecord, MessageRole, MessageStatus, RequestId, ViewEvent,
    };
    let event = ViewEvent::MessageUpdated {
        request: RequestId(4),
        chat_id: FIRST_CHAT.into(),
        message: MessageRecord {
            id: "pending-reply:m1".into(),
            role: MessageRole::Assistant,
            status: MessageStatus::Streaming,
            content: "Hel".into(),
            sender: "Synthetic mate".into(),
            thinking: String::new(),
            embeds: Vec::new(),
            send_state: None,
            metadata: MessageMetadata::default(),
        },
    };
    let ViewEventRecord::MessageUpdated {
        request,
        chat_id,
        message,
    } = ViewEventRecord::from(event)
    else {
        panic!("a message update mirrors to MessageUpdated");
    };
    assert_eq!((request, chat_id.as_str()), (4, FIRST_CHAT));
    assert_eq!(message.id, "pending-reply:m1");
    assert_eq!(message.status, MessageStatusRecord::Streaming);
    assert_eq!(message.content, "Hel");
    assert_eq!(message.metadata, MessageMetadataRecord::default());
}
