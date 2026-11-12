//! The C chat-list seed of the Apple UI-test fixtures: rows seeded through `openmates_test_support_seed_chat_list` come back from `ViewModelCore.start` as the cached `ChatList` (titles, order, pin, unread, draft-only, metadata in unix seconds); refusals and the buffer contract.
use crate::view_core_tests::{Events, Keychain, NAME, private_dir};
use crate::view_fixture_ffi::{SEED_BUFFER_TOO_SMALL, SEED_INVALID, SEED_OK};
use crate::view_window_tests::core;
use crate::*;
use serde_json::{Value, json};
use std::path::Path;
use std::sync::{Arc, Mutex};

/// Nothing listens on the discard port: admission fails offline.
const OFFLINE_API: &str = "http://127.0.0.1:9";
const NOW: i64 = 1_800_000_000;

/// Calls the C entry like Swift does; returns the code and the written bytes.
fn call(request: &[u8], capacity: usize) -> (i32, Vec<u8>, usize) {
    let mut out = vec![0_u8; capacity];
    let mut length = 0_usize;
    // SAFETY: both buffers live for the call and have the stated sizes.
    let code = unsafe {
        openmates_test_support_seed_chat_list(
            request.as_ptr(),
            request.len(),
            out.as_mut_ptr(),
            out.len(),
            &mut length,
        )
    };
    // A too-small buffer reports the needed length and writes nothing.
    out.truncate(if length <= capacity { length } else { 0 });
    (code, out, length)
}

fn request(dir: &Path, chats: Value) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "api_url": OFFLINE_API,
        "cache_container": dir.to_str().unwrap(),
        "cache_directory_name": NAME,
        "chats": chats,
    }))
    .unwrap()
}

/// The chat-navigation fixture's rows plus a pinned, unread chat.
fn navigation_rows() -> Value {
    let message =
        |content: &str, at: i64| json!([{"role": "user", "content": content, "created_at": at}]);
    json!([
        {"id": "ui-test-draft-chat", "created_at": NOW - 30, "draft": "Header navigation draft"},
        {"id": "ui-test-newer-chat", "title": "Newer Chat", "summary": "Newer seeded chat",
         "category": "general_knowledge", "icon": "message-square", "app_id": "general_knowledge",
         "created_at": NOW - 60, "last_message_at": NOW - 60, "messages": message("Newer Chat", NOW - 60)},
        {"id": "ui-test-current-chat", "title": "Current Chat", "created_at": NOW - 120,
         "last_message_at": NOW - 120, "messages": message("Current Chat", NOW - 120)},
        {"id": "ui-test-older-chat", "title": "Older Chat", "created_at": NOW - 180,
         "last_message_at": NOW - 180, "unread_count": 2, "messages": message("Older Chat", NOW - 180)},
        {"id": "ui-test-pinned-chat", "title": "Kitchen renovation", "created_at": NOW - 900,
         "pinned": true, "messages": message("Kitchen renovation", NOW - 900)},
    ])
}

fn keychain(payload: Vec<u8>) -> Arc<Keychain> {
    Arc::new(Keychain {
        payload: Mutex::new(Some(payload)),
        acknowledge: true,
        ..Keychain::default()
    })
}

#[tokio::test(flavor = "multi_thread")]
async fn seeded_rows_start_as_the_cached_chat_list_in_core_order() {
    let dir = private_dir();
    let body = request(dir.path(), navigation_rows());
    let (code, payload, _) = tokio::task::spawn_blocking(move || call(&body, 64 * 1024))
        .await
        .unwrap();
    assert_eq!(code, SEED_OK, "{}", String::from_utf8_lossy(&payload));
    let events = Arc::new(Events::default());
    let core = core(dir.path(), OFFLINE_API, &keychain(payload), &events);
    assert_eq!(core.start(None).await, Err(CoreError::Offline));
    let all = events.all();
    assert!(matches!(
        all[0],
        ViewEventRecord::Session {
            event: SessionEventRecord::Restored { .. }
        }
    ));
    let ViewEventRecord::ChatList { rows, completeness, .. } = &all[1] else {
        panic!("cached list expected: {all:?}");
    };
    assert_eq!(*completeness, ListCompletenessRecord::Cached);
    let ids: Vec<&str> = rows.iter().map(|row| row.id.as_str()).collect();
    assert_eq!(
        ids,
        [
            "ui-test-pinned-chat",
            "ui-test-draft-chat",
            "ui-test-newer-chat",
            "ui-test-current-chat",
            "ui-test-older-chat",
        ]
    );
    let row = |id: &str| rows.iter().find(|row| row.id == id).unwrap();
    let draft = row("ui-test-draft-chat");
    assert_eq!(draft.status, ChatRowStatusRecord::Draft);
    // A draft-only row is marked by its status; `has_draft` flags drafts of established chats.
    assert_eq!(draft.title, "Header navigation draft");
    assert_eq!(
        draft.metadata.draft_preview.as_deref(),
        Some("Header navigation draft")
    );
    let newer = row("ui-test-newer-chat");
    assert_eq!(newer.status, ChatRowStatusRecord::Ready);
    assert_eq!(newer.title, "Newer Chat");
    assert_eq!(newer.summary, "Newer seeded chat");
    assert_eq!(newer.category, "general_knowledge");
    assert_eq!(newer.messages_v, Some(1));
    assert_eq!(newer.metadata.icon.as_deref(), Some("message-square"));
    assert_eq!(newer.metadata.app_id.as_deref(), Some("general_knowledge"));
    // Server units: every chat-row time is unix seconds, never milliseconds.
    assert_eq!(newer.created_at, Some(NOW - 60));
    assert_eq!(newer.updated_at, Some(NOW - 60));
    assert_eq!(newer.metadata.last_message_at, Some(NOW - 60));
    assert_eq!(newer.metadata.last_edited_at, Some(NOW - 60));
    assert!(!newer.has_draft);
    assert!(row("ui-test-pinned-chat").pinned);
    assert_eq!(row("ui-test-older-chat").unread_count, 2);
}

#[tokio::test(flavor = "multi_thread")]
async fn the_seed_refuses_bad_requests_and_reports_the_needed_buffer() {
    let dir = private_dir();
    let path = dir.path().to_owned();
    let results = tokio::task::spawn_blocking(move || {
        let duplicate = json!([{"id": "a", "created_at": 1}, {"id": "a", "created_at": 2}]);
        let unknown = json!([{"id": "a", "created_at": 1, "colour": "red"}]);
        let millis_typo = json!([{"id": "a", "created_at": "1"}]);
        let small = call(&request(&path, json!([{"id": "a", "created_at": 1}])), 4);
        [
            call(b"not json", 256).0,
            call(&request(&path, json!([])), 256).0,
            call(&request(&path, duplicate), 256).0,
            call(&request(&path, unknown), 256).0,
            call(&request(&path, millis_typo), 256).0,
            small.0,
            i32::from(small.1.is_empty() && small.2 > 4),
        ]
    })
    .await
    .unwrap();
    assert_eq!(
        results,
        [
            SEED_INVALID,
            SEED_INVALID,
            SEED_INVALID,
            SEED_INVALID,
            SEED_INVALID,
            SEED_BUFFER_TOO_SMALL,
            1
        ]
    );
    let mut length = 7_usize;
    // SAFETY: null pointers are refused before any access.
    let code = unsafe {
        openmates_test_support_seed_chat_list(
            std::ptr::null(),
            0,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    };
    assert_eq!((code, length), (SEED_INVALID, 7));
}
