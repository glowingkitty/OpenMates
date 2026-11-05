//! PRIVATE DRAFT presentation regressions — not executed.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use crate::client::{ChatModels, ChatSelectionUpdate};
fn chat(id: &str, title: &str) -> Chat {
    Chat {
        id: id.into(),
        title: title.into(),
        ..Chat::default()
    }
}
fn items() -> Vec<Item> {
    vec![
        Item {
            id: "a".into(),
            title: "A".into(),
            ..Item::default()
        },
        Item {
            id: "b".into(),
            title: "B".into(),
            ..Item::default()
        },
    ]
}
#[test]
fn live_update_preserves_selected_identity_composer_scroll_focus_and_navigation() {
    let mut ui = Ui::new();
    ui.set_items(Workspace::Chats, items());
    ui.selected[index(Workspace::Chats)] = 1;
    ui.set_chat(chat("b", "Before"));
    ui.draft = Editor::from("unsubmitted local text");
    ui.scroll = 17;
    ui.follow_tail = false;
    ui.focus = Focus::Composer;
    let reversed = items().into_iter().rev().collect();
    ui.apply_live_chat_models(ChatModels {
        items: reversed,
        selection: ChatSelectionUpdate::Updated(chat("b", "Canonical")),
    });
    assert_eq!(ui.selected_chat_id(), Some("b"));
    assert_eq!(ui.chat.as_ref().unwrap().title, "Canonical");
    assert_eq!(ui.draft.text.as_str(), "unsubmitted local text");
    assert_eq!(ui.scroll, 17);
    assert!(!ui.follow_tail);
    assert!(matches!(ui.focus, Focus::Composer));
    assert_eq!(
        ui.items[index(Workspace::Chats)][ui.selected[index(Workspace::Chats)]].id,
        "b"
    );
}
#[test]
fn recent_list_absence_never_deletes_or_navigates_selected_chat() {
    let mut ui = Ui::new();
    ui.set_chat(chat("old-but-authorized", "History"));
    ui.apply_live_chat_models(ChatModels {
        items: vec![],
        selection: ChatSelectionUpdate::Unchanged,
    });
    assert_eq!(ui.selected_chat_id(), Some("old-but-authorized"));
}
#[test]
fn canonical_selected_unavailable_hides_only_matching_view_and_preserves_local_draft_binding() {
    let mut ui = Ui::new();
    ui.set_chat(chat("a", "A"));
    ui.draft = Editor::from("keep under original chat");
    ui.apply_live_chat_models(ChatModels {
        items: vec![],
        selection: ChatSelectionUpdate::Unavailable {
            chat_id: "a".into(),
        },
    });
    assert!(ui.chat.is_none());
    assert!(ui.draft.text.is_empty());
    assert_eq!(ui.drafts["a"].as_str(), "keep under original chat");
    assert!(!ui.drafts.contains_key("__new__"));
}
#[test]
fn stale_selected_reply_does_not_replace_new_navigation_or_clear_new_draft() {
    let mut ui = Ui::new();
    ui.set_chat(chat("b", "B"));
    ui.draft = Editor::from("B local");
    ui.apply_live_chat_models(ChatModels {
        items: items(),
        selection: ChatSelectionUpdate::Updated(chat("a", "A new")),
    });
    ui.apply_live_chat_models(ChatModels {
        items: items(),
        selection: ChatSelectionUpdate::Unavailable {
            chat_id: "a".into(),
        },
    });
    assert_eq!(ui.selected_chat_id(), Some("b"));
    assert_eq!(ui.draft.text.as_str(), "B local");
}
#[test]
fn background_refresh_does_not_navigate_away_from_project_detail() {
    let mut ui = Ui::new();
    ui.workspace = Workspace::Projects;
    ui.detail = Some(Item {
        id: "project".into(),
        title: "Project".into(),
        ..Item::default()
    });
    ui.apply_live_chat_models(ChatModels {
        items: items(),
        selection: ChatSelectionUpdate::Updated(chat("a", "A")),
    });
    assert!(matches!(ui.workspace, Workspace::Projects));
    assert_eq!(ui.detail.as_ref().unwrap().id, "project");
}
#[test]
fn unavailable_chat_cannot_be_reopened_through_saved_apps_return_view() {
    let mut ui = Ui::new();
    ui.workspace = Workspace::Apps;
    ui.chat_origin = Some((chat("a", "old"), 4, false, None));
    ui.apply_live_chat_models(ChatModels {
        items: vec![],
        selection: ChatSelectionUpdate::Unavailable {
            chat_id: "a".into(),
        },
    });
    assert!(ui.chat_origin.is_none());
    assert!(matches!(ui.workspace, Workspace::Apps));
}

#[test]
fn external_canonical_refresh_does_not_replace_own_stream_or_discard_pending_send() {
    let mut ui = Ui::new();
    ui.set_chat(chat("a", "Own turn"));
    ui.streaming = true;
    ui.pending_send = Some(("a".into(), Zeroizing::new("own staged text".into())));
    ui.apply_live_chat_models(ChatModels {
        items: items(),
        selection: ChatSelectionUpdate::Updated(chat("a", "older canonical")),
    });
    assert_eq!(ui.chat.as_ref().unwrap().title, "Own turn");
    ui.apply_live_chat_models(ChatModels {
        items: vec![],
        selection: ChatSelectionUpdate::Unavailable {
            chat_id: "a".into(),
        },
    });
    assert!(ui.chat.is_none());
    assert!(ui.pending_send.is_some());
    assert!(ui.streaming);
    assert_eq!(ui.pending_send.as_ref().unwrap().0, "a");
}

#[test]
fn personal_chat_access_denial_hides_only_that_chat_without_signing_out_owner() {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_chat(chat("a", "Denied"));
    ui.set_items(Workspace::Chats, items());
    ui.hide_live_chat("a");
    assert!(ui.authenticated);
    assert!(ui.chat.is_none());
    assert!(
        !ui.items[index(Workspace::Chats)]
            .iter()
            .any(|row| row.id == "a")
    );
    assert!(
        ui.items[index(Workspace::Chats)]
            .iter()
            .any(|row| row.id == "b")
    );
}

#[test]
fn running_turn_is_reachable_through_the_active_pointer() {
    let mut ui = Ui::new();
    assert!(ui.running_chat_id().is_none());
    ui.active_turn = Some(ActiveTurn { chat_id: "a".into(), user_id: "u".into(), assistant: None, expects_reply: true });
    assert!(ui.running_chat_id().is_none());
    ui.streaming = true;
    assert_eq!(ui.running_chat_id().as_deref(), Some("a"));
}
