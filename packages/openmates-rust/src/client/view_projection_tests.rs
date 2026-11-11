//! Chat row and message metadata projection over synthetic encrypted rows: present fields, absent fields staying `None`, locked rows, mistyped fields.
use super::*;
use crate::{crypto, session::Session};
use serde_json::json;
use std::collections::BTreeMap as Map;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const MASTER: [u8; 32] = [1; 32];
const KEY: [u8; 32] = [8; 32];

fn session(team: Option<&str>) -> Session {
    Session {
        api_url: "https://api.example.org".into(),
        session_id: "fixture".into(),
        cookies: Map::new(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new(MASTER),
        hashed_email: "hash".into(),
        user_email_salt: "salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: team.map(str::to_owned),
    }
}

fn enc(text: &str) -> String {
    crypto::encrypt_combined(text, &KEY).unwrap()
}

fn client_with(row: Value) -> Client {
    let mut client = Client::new("https://api.example.org", Some(session(None))).unwrap();
    client.insert_chat_row(CHAT.into(), row);
    client
}

fn full_row() -> Value {
    json!({
        "id": CHAT,
        "encrypted_chat_key": crypto::encrypt_bytes(&KEY, &MASTER).unwrap(),
        "encrypted_title": enc("Kitchen renovation"),
        "encrypted_icon": enc("hammer"),
        "encrypted_active_focus_id": enc("web-research"),
        "parent_id": "11111111-1111-4111-8111-111111111111",
        "is_sub_chat": true,
        "is_shared": false,
        "is_private": true,
        "is_hidden": false,
        "last_message_timestamp": 1_700_000_100,
        "last_edited_overall_timestamp": "1700000200",
        "budget_limit": 500,
        "budget_spent": 120,
        "draft_v": 3,
        "encrypted_draft_md": crypto::encrypt_combined("Ask about tiles", &MASTER).unwrap(),
        "encrypted_draft_preview": crypto::encrypt_combined("Ask about", &MASTER).unwrap(),
    })
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn a_full_chat_row_projects_every_held_fact() {
    let metadata = client_with(full_row()).chat_row_metadata(CHAT).unwrap();
    assert_eq!(
        metadata,
        ChatRowMetadata {
            icon: Some("hammer".into()),
            active_focus_id: Some("web-research".into()),
            parent_id: Some("11111111-1111-4111-8111-111111111111".into()),
            is_sub_chat: Some(true),
            team_id: None,
            is_shared: Some(false),
            is_private: Some(true),
            is_hidden: Some(false),
            last_message_at: Some(1_700_000_100),
            last_edited_at: Some(1_700_000_200),
            budget_limit: Some(500),
            budget_spent: Some(120),
            draft_v: Some(3),
            draft_preview: Some("Ask about".into()),
        }
    );
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn absent_fields_stay_none_and_an_unknown_chat_has_no_facts() {
    let row =
        json!({"id": CHAT, "encrypted_chat_key": crypto::encrypt_bytes(&KEY, &MASTER).unwrap()});
    let client = client_with(row);
    assert_eq!(
        client.chat_row_metadata(CHAT).unwrap(),
        ChatRowMetadata::default()
    );
    assert_eq!(
        client.chat_row_metadata("embed:33333333").unwrap(),
        ChatRowMetadata::default()
    );
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn a_locked_row_keeps_plain_facts_but_no_decrypted_ones() {
    let mut row = full_row();
    // A team chat seen from personal scope: key selection refuses it.
    row["team_id"] = json!("synthetic-team");
    let metadata = client_with(row).chat_row_metadata(CHAT).unwrap();
    assert_eq!(metadata.icon, None);
    assert_eq!(metadata.active_focus_id, None);
    assert_eq!(metadata.budget_limit, Some(500));
    assert_eq!(metadata.is_sub_chat, Some(true));
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn a_mistyped_plain_field_is_a_protocol_error() {
    let mut row = full_row();
    row["budget_limit"] = json!("lots");
    assert!(matches!(
        client_with(row).chat_row_metadata(CHAT),
        Err(Error::Protocol)
    ));
}

fn reply_row() -> Value {
    let mappings = json!([
        {"placeholder": "[EMAIL_1]", "original": "user@example.org", "type": "EMAIL"},
        {"placeholder": "[NAME_1]", "original": "Alex"},
        {"broken": true}
    ]);
    json!({
        "id": "row-2",
        "message_id": "server-2",
        "client_message_id": "m2",
        "user_message_id": "m1",
        "chat_id": CHAT,
        "role": "assistant",
        "status": "synced",
        "created_at": 1_700_000_050,
        "encrypted_content": enc("Hello [NAME_1]"),
        "encrypted_model_name": enc("synthetic-model"),
        "encrypted_category": enc("software_development"),
        "has_thinking": true,
        "thinking_token_count": 42,
        "queue_revision": 0,
        "queue_mode": "after_current",
        "encrypted_pii_mappings": enc(&mappings.to_string()),
    })
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn held_message_rows_project_metadata_by_message_id() {
    let mut client = client_with(full_row());
    let user = json!({"id": "row-1", "client_message_id": "m1", "chat_id": CHAT, "role": "user", "encrypted_content": enc("hi")});
    // History rows may be JSON strings; both shapes are read.
    client
        .history
        .insert(CHAT.into(), vec![json!(user.to_string()), reply_row()]);
    let found = client.message_metadata_by_id(CHAT).unwrap();
    assert_eq!(found.len(), 2);
    assert_eq!(
        found["m1"],
        MessageMetadata {
            client_message_id: Some("m1".into()),
            ..MessageMetadata::default()
        }
    );
    let reply = &found["m2"];
    assert_eq!(reply.created_at, Some(1_700_000_050));
    assert_eq!(reply.server_message_id.as_deref(), Some("server-2"));
    assert_eq!(reply.user_message_id.as_deref(), Some("m1"));
    assert_eq!(reply.stored_status.as_deref(), Some("synced"));
    assert_eq!(reply.model_name.as_deref(), Some("synthetic-model"));
    assert_eq!(reply.category.as_deref(), Some("software_development"));
    assert_eq!(reply.has_thinking, Some(true));
    assert_eq!(reply.thinking_token_count, Some(42));
    assert_eq!(reply.queue_revision, Some(0));
    assert_eq!(reply.queue_mode.as_deref(), Some("after_current"));
    assert_eq!(reply.queue_dispatch_status, None);
    assert_eq!(
        reply.pii_mappings,
        [
            PiiMapping {
                placeholder: "[EMAIL_1]".into(),
                original: "user@example.org".into(),
                kind: "EMAIL".into()
            },
            PiiMapping {
                placeholder: "[NAME_1]".into(),
                original: "Alex".into(),
                kind: String::new()
            },
        ]
    );
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn a_chat_without_a_held_row_has_no_message_metadata() {
    let mut client = Client::new("https://api.example.org", Some(session(None))).unwrap();
    client.history.insert(CHAT.into(), vec![reply_row()]);
    assert!(client.message_metadata_by_id(CHAT).unwrap().is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted
#[test]
fn a_mistyped_message_field_is_a_protocol_error() {
    let mut row = reply_row();
    row["thinking_token_count"] = json!(-3);
    assert!(matches!(message_metadata(&row, &KEY), Err(Error::Protocol)));
}
