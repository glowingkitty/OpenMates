//! Conversion of realistic core chat rows, messages, windows and stream
//! updates, and refusal of malformed ones.
use super::*;
use crate::client::CachedChatWindow;
use crate::model::{Chat, Item, Message, StreamUpdate};
use serde_json::json;

fn row_item() -> Item {
    Item {
        id: "chat-1".into(),
        title: "Kitchen renovation".into(),
        description: "Planning the new layout".into(),
        status: String::new(),
        category: "home".into(),
        fields: json!({"created_at":1700000000,"updated_at":1700000500,"pinned":true,"messages_v":4,"unread_count":2,"chat_list_title":"Kitchen renovation"}),
    }
}

#[test]
fn chat_row_reads_every_metadata_field() {
    let row = chat_list_row_from_item(&row_item()).unwrap();
    assert_eq!(row.id, "chat-1");
    assert_eq!(row.chat_list_title.as_deref(), Some("Kitchen renovation"));
    assert_eq!(
        (row.created_at, row.updated_at, row.messages_v),
        (Some(1700000000), Some(1700000500), Some(4))
    );
    assert_eq!(row.unread_count, 2);
    assert!(row.pinned && !row.archived && !row.has_draft);
    assert_eq!(row.status, ChatRowStatus::Ready);
    assert_eq!(row.footer, None);
}

#[test]
fn draft_row_has_no_title_but_keeps_the_draft_flag() {
    let item = Item {
        status: "draft".into(),
        title: "long draft body".into(),
        fields: json!({"chat_list_title":null,"has_draft":true}),
        ..row_item()
    };
    let row = chat_list_row_from_item(&item).unwrap();
    assert_eq!(row.status, ChatRowStatus::Draft);
    assert_eq!(row.chat_list_title, None);
    assert!(row.has_draft);
    assert_eq!(row.created_at, None);
    assert_eq!(row.unread_count, 0);
}

#[test]
fn home_footer_is_carried() {
    let item = Item {
        fields: json!({"footer":"Reminder in 5m"}),
        ..row_item()
    };
    assert_eq!(
        chat_list_row_from_item(&item).unwrap().footer.as_deref(),
        Some("Reminder in 5m")
    );
}

#[test]
fn chat_row_refuses_missing_id_unknown_status_and_mistyped_fields() {
    let no_id = Item {
        id: String::new(),
        ..row_item()
    };
    assert_eq!(
        chat_list_row_from_item(&no_id),
        Err(ViewModelError::MissingField {
            record: "chat_row",
            field: "id"
        })
    );
    let status = Item {
        status: "weird".into(),
        ..row_item()
    };
    assert_eq!(
        chat_list_row_from_item(&status),
        Err(ViewModelError::UnknownVariant {
            record: "chat_row",
            field: "status"
        })
    );
    for (field, bad) in [
        ("chat_list_title", json!(1)),
        ("pinned", json!("yes")),
        ("unread_count", json!(-1)),
        ("updated_at", json!("x")),
    ] {
        let item = Item {
            fields: json!({ field: bad }),
            ..row_item()
        };
        assert_eq!(
            chat_list_row_from_item(&item),
            Err(ViewModelError::InvalidField {
                record: "chat_row",
                field
            }),
            "{field}"
        );
    }
}

fn embed_item() -> Item {
    Item {
        id: "embed-1".into(),
        title: "fallback".into(),
        category: "web".into(),
        fields: json!({"app":"web","skill":"search","query":"rust","status":"finished"}),
        ..Item::default()
    }
}

#[test]
fn embed_ref_follows_the_tui_metadata_lookup() {
    let embed = embed_ref_from_item(&embed_item()).unwrap();
    assert_eq!(
        (
            embed.kind.as_str(),
            embed.app_id.as_str(),
            embed.skill_id.as_str()
        ),
        ("web", "web", "search")
    );
    assert_eq!(
        (embed.title.as_str(), embed.status.as_str()),
        ("fallback", "finished")
    );
    let data: serde_json::Value = serde_json::from_str(&embed.data_json).unwrap();
    assert_eq!(data["query"], "rust");
    let typed = Item {
        fields: json!({"type":"website","app_id":"a","skill_id":"s","title":"Page"}),
        ..embed_item()
    };
    let embed = embed_ref_from_item(&typed).unwrap();
    assert_eq!(
        (
            embed.kind.as_str(),
            embed.app_id.as_str(),
            embed.skill_id.as_str(),
            embed.title.as_str()
        ),
        ("website", "a", "s", "Page")
    );
}

#[test]
fn embed_ref_requires_an_id() {
    let item = Item {
        id: String::new(),
        ..embed_item()
    };
    assert_eq!(
        embed_ref_from_item(&item),
        Err(ViewModelError::MissingField {
            record: "embed",
            field: "id"
        })
    );
}

fn chat() -> Chat {
    Chat {
        id: "chat-1".into(),
        title: "Kitchen renovation".into(),
        category: "home".into(),
        messages: vec![
            Message {
                id: "m1".into(),
                role: "user".into(),
                content: "Find tiles".into(),
                ..Message::default()
            },
            Message {
                id: "m2".into(),
                role: "assistant".into(),
                content: "Here".into(),
                sender: "Sophia".into(),
                thinking: "hm".into(),
                embeds: vec![embed_item()],
            },
        ],
    }
}

#[test]
fn messages_convert_with_roles_and_embeds() {
    let window = chat_window_from_chat(
        &chat(),
        ChatWindowSource::Canonical,
        Some(true),
        false,
        false,
        PiiRestoration::PageLocal,
    )
    .unwrap();
    assert_eq!(window.messages.len(), 2);
    assert_eq!(window.messages[0].role, MessageRole::User);
    assert_eq!(window.messages[1].role, MessageRole::Assistant);
    assert_eq!(window.messages[1].status, MessageStatus::Complete);
    assert_eq!(window.messages[1].embeds[0].id, "embed-1");
    assert_eq!(
        (window.has_more_before, window.source),
        (Some(true), ChatWindowSource::Canonical)
    );
}

#[test]
fn message_refuses_unknown_role_and_empty_id() {
    let mut bad = chat();
    bad.messages[0].role = "tool".into();
    assert_eq!(
        chat_window_from_chat(
            &bad,
            ChatWindowSource::Cached,
            None,
            false,
            false,
            PiiRestoration::PageLocal
        ),
        Err(ViewModelError::UnknownVariant {
            record: "message",
            field: "role"
        })
    );
    let mut bad = chat();
    bad.messages[1].id.clear();
    assert!(
        chat_window_from_chat(
            &bad,
            ChatWindowSource::Cached,
            None,
            false,
            false,
            PiiRestoration::PageLocal
        )
        .is_err()
    );
    let mut bad = chat();
    bad.id.clear();
    assert_eq!(
        chat_window_from_chat(
            &bad,
            ChatWindowSource::Cached,
            None,
            false,
            false,
            PiiRestoration::PageLocal
        ),
        Err(ViewModelError::MissingField {
            record: "chat_window",
            field: "chat_id"
        })
    );
}

#[test]
fn cached_window_maps_facts_and_refuses_unknown_restoration() {
    let cached = CachedChatWindow {
        chat: chat(),
        has_more_before: None,
        history_complete: false,
        cached: true,
        refreshing: true,
        pii_restoration: "all_cached_user_rows",
    };
    let window = chat_window_from_cached(&cached, ChatWindowSource::CachedOffline).unwrap();
    assert_eq!(
        (
            window.has_more_before,
            window.refreshing,
            window.pii_restoration
        ),
        (None, true, PiiRestoration::AllCachedUserRows)
    );
    let cached = CachedChatWindow {
        pii_restoration: "other",
        ..cached
    };
    assert_eq!(
        chat_window_from_cached(&cached, ChatWindowSource::Cached),
        Err(ViewModelError::UnknownVariant {
            record: "chat_window",
            field: "pii_restoration"
        })
    );
}

#[test]
fn stream_updates_convert_one_to_one() {
    let content = StreamUpdate::Content {
        content: "Hi".into(),
        thinking: "t".into(),
        mate: "Sophia".into(),
    };
    assert_eq!(
        stream_event_from_update(&content).unwrap(),
        StreamEvent::Content {
            content: "Hi".into(),
            thinking: "t".into(),
            mate: "Sophia".into()
        }
    );
    let started = StreamUpdate::Started {
        chat_id: "c".into(),
        message_id: "m".into(),
        expects_reply: true,
    };
    assert_eq!(
        stream_event_from_update(&started).unwrap(),
        StreamEvent::Started {
            chat_id: "c".into(),
            message_id: "m".into(),
            expects_reply: true
        }
    );
    assert_eq!(
        stream_event_from_update(&StreamUpdate::TaskAssigned {
            chat_id: "c".into(),
            message_id: "m".into(),
            task_id: "t".into(),
        })
        .unwrap(),
        StreamEvent::TaskAssigned {
            chat_id: "c".into(),
            message_id: "m".into(),
            task_id: "t".into()
        }
    );
    assert_eq!(
        stream_event_from_update(&StreamUpdate::Status("Waiting".into())).unwrap(),
        StreamEvent::Status {
            message: "Waiting".into()
        }
    );
    let consent = StreamUpdate::Consent {
        request_id: "r".into(),
        items: vec![embed_item()],
    };
    match stream_event_from_update(&consent).unwrap() {
        StreamEvent::Consent { request_id, items } => {
            assert_eq!((request_id.as_str(), items.len()), ("r", 1))
        }
        other => panic!("unexpected {other:?}"),
    }
    let bad = StreamUpdate::Consent {
        request_id: "r".into(),
        items: vec![Item::default()],
    };
    assert!(stream_event_from_update(&bad).is_err());
}

#[test]
fn only_embed_prefixed_ids_are_saved_item_rows() {
    let mut item = row_item();
    assert!(!chat_list_row_from_item(&item).unwrap().is_saved_item);
    item.id = format!("{}e1", crate::view_model::SAVED_ITEM_ID_PREFIX);
    assert!(chat_list_row_from_item(&item).unwrap().is_saved_item);
}
