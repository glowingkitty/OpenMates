//! Joining an exact oversized-cursor row into an empty saved viewing page.
use super::*;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const SCOPE: &str = "0000000000000000000000000000000000000000000000000000000000000000";

fn oversized_page() -> SavedChatRead {
    serde_json::from_value(json!({
        "chat": {"id": CHAT, "title": "Kitchen renovation", "category": "", "messages": []},
        "hasMoreBefore": true, "hasMoreAfter": false, "anchorFound": true,
        "startCursor": null, "endCursor": null,
        "serverMessageCount": 3, "messagesVersion": null,
        "oversizedMessage": true,
        "oversizedMessageCursor": {"chatId": CHAT, "scope": SCOPE, "createdAt": 1700, "messageId": "selected"},
        "payloadBytes": 0, "piiRestoration": "page_local", "historyComplete": false,
        "chatMetadata": {"id": CHAT},
        "messageMetadata": [], "piiMappingsByMessageId": {},
        "contentMode": "page_local", "pagesRead": 1
    }))
    .expect("synthetic oversized page")
}

fn exact(id: &str, created_at: i64) -> SavedChatExactMessage {
    serde_json::from_value(json!({
        "message": {"id": id, "role": "assistant", "content": "Large synthetic answer"},
        "chatMetadata": {"id": CHAT},
        "messageMetadata": {"id": id, "chatId": CHAT, "createdAt": created_at},
        "piiMappings": [],
        "contentMode": "page_local", "piiRestoration": "page_local",
        "payloadBytes": 300000, "historyComplete": false
    }))
    .expect("synthetic exact row")
}

// contract-test: supporting surface=sdks.rust assertions=storage.cold.independent-message-pages
#[test]
fn exact_row_joins_empty_oversized_page_and_becomes_its_cursor() {
    let mut read = oversized_page();
    join_exact_row(&mut read, exact("selected", 1700)).expect("join");
    assert_eq!(read.window.chat.messages.len(), 1);
    assert_eq!(read.window.chat.messages[0].id, "selected");
    assert_eq!(read.message_metadata.len(), 1);
    assert_eq!(read.message_metadata[0].id, "selected");
    assert!(!read.window.oversized_message);
    assert!(read.window.oversized_message_cursor.is_none());
    let start = read.window.start_cursor.as_ref().expect("start cursor");
    assert_eq!(
        (start.message_id.as_str(), start.created_at),
        ("selected", 1700)
    );
    assert_eq!(read.window.end_cursor, read.window.start_cursor);
    assert!(read.window.has_more_before);
    assert_eq!(read.window.payload_bytes, 300000);
    assert!(read.pii_mappings_by_message_id.contains_key("selected"));
    assert!(!read.window.history_complete);
}

// contract-test: supporting surface=sdks.rust assertions=storage.cold.independent-message-pages
#[test]
fn mismatched_or_complete_exact_rows_refuse_and_leave_page_unresolved() {
    let mut wrong_id = exact("other", 1700);
    wrong_id.message_metadata.id = "selected".into();
    let mut complete = exact("selected", 1700);
    complete.history_complete = true;
    let mut stored = exact("selected", 1700);
    stored.content_mode = SavedChatContentMode::Stored;
    for candidate in [wrong_id, exact("selected", 1699), complete, stored] {
        let mut read = oversized_page();
        assert!(matches!(
            join_exact_row(&mut read, candidate),
            Err(Error::Protocol)
        ));
        assert!(read.window.oversized_message);
        assert!(read.window.oversized_message_cursor.is_some());
        assert!(read.window.chat.messages.is_empty());
        assert!(read.message_metadata.is_empty());
    }
}

// contract-test: supporting surface=sdks.rust assertions=storage.cold.independent-message-pages
#[test]
fn pages_without_an_omitted_row_refuse_a_join() {
    let mut read = oversized_page();
    read.window.oversized_message = false;
    read.window.oversized_message_cursor = None;
    assert!(matches!(
        join_exact_row(&mut read, exact("selected", 1700)),
        Err(Error::Protocol)
    ));
    assert!(read.window.chat.messages.is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=storage.cold.independent-message-pages
#[tokio::test]
async fn resolving_a_page_without_an_omitted_row_makes_no_request() {
    let endpoint = "http://127.0.0.1:9";
    let session: Session = serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).expect("synthetic session");
    let mut client = Client::new(endpoint, Some(session)).expect("client");
    let mut read = oversized_page();
    read.window.oversized_message = false;
    read.window.oversized_message_cursor = None;
    // Port 9 is closed: any exact read attempt would surface as an error here.
    client
        .resolve_oversized_saved_row(CHAT, &mut read)
        .await
        .expect("no exact read");
    assert!(read.window.chat.messages.is_empty());
}
