//! Presentation-only source regressions. Rust execution remains required in CI.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use ratatui::{Terminal, backend::TestBackend};
fn chat(id: &str, content: &str) -> Chat {
    Chat {
        id: id.into(),
        title: "Saved private chat".into(),
        messages: vec![Message {
            id: "canonical-user".into(),
            role: "user".into(),
            content: content.into(),
            ..Default::default()
        }],
        ..Default::default()
    }
}
fn ui() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui
}
fn render(ui: &mut Ui) -> String {
    let mut terminal = Terminal::new(TestBackend::new(120, 38)).unwrap();
    terminal.draw(|frame| ui.draw(frame)).unwrap();
    terminal
        .backend()
        .buffer()
        .content()
        .iter()
        .map(|cell| cell.symbol())
        .collect()
}
#[test]
fn cached_content_is_rendered_before_canonical_without_settling_uncertain_user_message() {
    let mut ui = ui();
    ui.uncertain_turns.insert(
        "a".into(),
        UncertainTurn {
            message_id: "canonical-user".into(),
            text: Zeroizing::new("keep uncertainty".into()),
            admitted: true,
        },
    );
    ui.last_uncertain = Some("a".into());
    ui.set_cached_chat(chat("a", "Canonical marker\nNative line B"));
    assert!(ui.is_cached_chat_refreshing());
    assert!(ui.uncertain_turns.contains_key("a"));
    let cached = render(&mut ui);
    assert!(cached.contains("Canonical marker"));
    assert!(cached.contains("Native line B"));
    assert!(cached.contains("Cached chat · refreshing"));
    ui.set_busy(false);
    ui.set_status("Ready");
    assert!(render(&mut ui).contains("Cached chat · refreshing"));
    ui.set_chat(chat("a", "Canonical marker\nNative line B"));
    assert!(!ui.is_cached_chat_refreshing());
    assert!(!ui.uncertain_turns.contains_key("a"));
    assert!(ui.last_uncertain.is_none());
    assert!(render(&mut ui).contains("Canonical marker"));
    assert!(!render(&mut ui).contains("Cached chat · refreshing"));
}
#[test]
fn pending_and_admitted_effects_stay_owned_by_original_chat_during_cached_other_view() {
    let mut ui = ui();
    ui.set_chat(chat("a", "own optimistic turn"));
    ui.pending_send = Some(("a".into(), Zeroizing::new("do not resend".into())));
    ui.active_turn = Some(ActiveTurn {
        chat_id: "a".into(),
        user_id: "own-message".into(),
        assistant: None,
        expects_reply: true,
    });
    ui.delivery = Delivery::Admitted {
        chat_id: "a".into(),
        message_id: "own-message".into(),
    };
    ui.streaming = true;
    ui.set_cached_chat(chat("a", "older same chat"));
    assert!(!ui.is_cached_chat_refreshing());
    assert_eq!(
        ui.chat.as_ref().unwrap().messages[0].content,
        "own optimistic turn"
    );
    ui.set_cached_chat(chat("b", "cached other chat"));
    assert!(ui.is_cached_chat_refreshing());
    assert!(ui.streaming);
    assert_eq!(ui.pending_send.as_ref().unwrap().0, "a");
    assert_eq!(ui.active_turn.as_ref().unwrap().chat_id, "a");
    assert!(matches!(&ui.delivery,Delivery::Admitted {chat_id,..} if chat_id=="a"));
    ui.set_chat(chat("b", "canonical other chat"));
    assert!(ui.streaming);
    assert!(ui.pending_send.is_some());
    assert!(ui.active_turn.is_some());
}
#[test]
fn cached_to_canonical_preserves_draft_cursor_scroll_sidebar_focus_and_selection() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "cached tail"));
    ui.draft = Editor::from("unsent local text");
    ui.draft
        .key(KeyEvent::new(KeyCode::Left, KeyModifiers::NONE));
    let before = ui.draft.display(80, false);
    ui.scroll = 8;
    ui.follow_tail = false;
    ui.focus = Focus::Content;
    ui.sidebar = true;
    ui.selecting = true;
    ui.content_action = 3;
    ui.embed_offsets.insert("cache-embed".into(), 7);
    ui.set_cached_chat(chat("a", "updated cached tail"));
    assert_eq!(ui.scroll, 8);
    assert_eq!(ui.draft.display(80, false), before);
    ui.set_chat(chat("a", "canonical tail"));
    assert_eq!(ui.draft.display(80, false), before);
    assert_eq!(ui.scroll, 8);
    assert!(!ui.follow_tail);
    assert!(matches!(ui.focus, Focus::Content));
    assert!(ui.sidebar && ui.selecting);
    assert_eq!(ui.content_action, 3);
    assert_eq!(ui.embed_offsets["cache-embed"], 7);
}
#[test]
fn cached_snapshot_actions_are_blocked_but_uncertain_copy_and_navigation_keep_existing_policy() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "bounded cache"));
    ui.draft = Editor::from("my unsent text");
    assert!(ui.send().is_empty());
    assert_eq!(ui.draft.text.as_str(), "my unsent text");
    assert!(ui.pending_send.is_none());
    assert!(ui.activate(HitAction::Copy).is_empty());
    ui.share_form();
    assert!(ui.form.is_none());
    ui.download_form();
    assert!(ui.form.is_none());
    assert!(ui.activate(HitAction::Delete).is_empty());
    ui.uncertain_turns.insert(
        "a".into(),
        UncertainTurn {
            message_id: "u".into(),
            text: Zeroizing::new("caller-owned retry text".into()),
            admitted: false,
        },
    );
    assert!(
        matches!(&ui.command("/copy-pending")[..],[UiCommand::Copy(text)] if text=="caller-owned retry text")
    );
    assert!(
        matches!(&ui.command("/pending")[..],[UiCommand::Open(Workspace::Chats,id)] if id=="a")
    );
    ui.set_chat(chat("a", "canonical"));
    assert!(!ui.activate(HitAction::Copy).is_empty());
}
#[test]
fn already_open_share_or_export_form_cannot_submit_after_cached_publication() {
    for export in [false, true] {
        let mut ui = ui();
        ui.set_chat(chat("a", "canonical"));
        if export {
            ui.download_form();
        } else {
            ui.share_form();
        }
        ui.set_cached_chat(chat("b", "cache"));
        assert!(ui.submit_form().is_empty());
        assert!(ui.form.is_some());
    }
}
#[test]
fn cached_embed_return_keeps_gate_and_canonical_origin_update_clears_it() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "cached"));
    ui.draft = Editor::from("keep draft");
    ui.set_item(
        Workspace::Apps,
        Item {
            id: "embed:x".into(),
            ..Default::default()
        },
    );
    assert!(!ui.is_cached_chat_refreshing());
    ui.back();
    assert!(ui.is_cached_chat_refreshing());
    assert_eq!(ui.draft.text.as_str(), "keep draft");
    ui.set_item(
        Workspace::Apps,
        Item {
            id: "embed:x".into(),
            ..Default::default()
        },
    );
    ui.apply_live_chat_models(crate::client::ChatModels {
        items: vec![],
        selection: crate::client::ChatSelectionUpdate::Updated(chat("a", "canonical origin")),
    });
    ui.back();
    assert!(!ui.is_cached_chat_refreshing());
    assert_eq!(
        ui.chat.as_ref().unwrap().messages[0].content,
        "canonical origin"
    );
}
#[test]
fn cancellation_denial_error_and_logout_hide_preview_without_rebinding_its_draft() {
    for reason in ["cancel", "deny", "error", "logout"] {
        let mut ui = ui();
        ui.set_cached_chat(chat("a", "private cached content"));
        ui.draft = Editor::from("bound to a");
        ui.uncertain_turns.insert(
            "a".into(),
            UncertainTurn {
                message_id: "u".into(),
                text: Zeroizing::new("guard".into()),
                admitted: false,
            },
        );
        match reason {
            "cancel" => ui.set_status("Cancelled"),
            "deny" => ui.hide_live_chat("a"),
            "error" => ui.set_error("Read unavailable"),
            _ => ui.set_authenticated(false),
        };
        assert!(ui.chat.is_none());
        assert!(!ui.is_cached_chat_refreshing());
        assert!(ui.draft.text.is_empty());
        if reason != "logout" {
            assert!(ui.uncertain_turns.contains_key("a"));
            assert_eq!(ui.drafts["a"].as_str(), "bound to a");
        } else {
            assert!(ui.uncertain_turns.is_empty());
            assert!(ui.drafts.is_empty());
        }
    }
}
#[test]
fn stale_hidden_cached_origin_cannot_return_after_cancellation() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "cached"));
    ui.set_item(
        Workspace::Apps,
        Item {
            id: "embed:x".into(),
            ..Default::default()
        },
    );
    ui.set_status("Cancelled");
    ui.back();
    assert!(ui.chat.is_none());
}
#[test]
fn cached_and_canonical_frames_use_existing_terminal_cleaning_and_markdown_pipeline() {
    let mut ui = ui();
    ui.set_cached_chat(chat(
        "a",
        "Safe **bold**\nSecond line\u{1b}]52;c;do-not-copy\u{7}\u{202e}BAD",
    ));
    let frame = render(&mut ui);
    assert!(frame.contains("Safe bold"));
    assert!(frame.contains("Second line"));
    assert!(!frame.contains('\u{1b}'));
    assert!(!frame.contains('\u{202e}'));
}

#[test]
fn cache_cannot_demote_an_already_canonical_same_chat() {
    let mut ui = ui();
    ui.set_chat(chat("a", "canonical"));
    ui.set_cached_chat(chat("a", "older cache"));
    assert!(!ui.is_cached_chat_refreshing());
    assert_eq!(ui.chat.as_ref().unwrap().messages[0].content, "canonical");
}
#[test]
fn cached_question_answer_cannot_bypass_send_gate_through_form_submission() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "cached question"));
    ui.form = Some(Form::new(
        "Question",
        FormPurpose::Question(json!({})),
        vec![],
    ));
    assert!(ui.submit_form().is_empty());
    assert!(ui.form.is_some());
    assert!(ui.pending_send.is_none());
}

#[test]
fn source_tagged_offline_result_is_read_only_and_cannot_reconcile_uncertainty() {
    let mut ui = ui();
    ui.set_cached_chat(chat("a", "cached body"));
    ui.uncertain_turns.insert(
        "a".into(),
        UncertainTurn {
            message_id: "canonical-user".into(),
            text: Zeroizing::new("keep uncertain".into()),
            admitted: true,
        },
    );
    ui.set_cached_chat_offline(chat("a", "older offline row"));
    assert!(ui.is_cached_chat_read_only());
    assert!(!ui.is_cached_chat_refreshing());
    assert!(render(&mut ui).contains("Cached chat · offline"));
    assert!(ui.uncertain_turns.contains_key("a"));
    assert_eq!(ui.chat.as_ref().unwrap().messages[0].content, "cached body");
    ui.draft = Editor::from("unsent");
    assert!(ui.send().is_empty());
    assert!(ui.activate(HitAction::Copy).is_empty());
    ui.share_form();
    assert!(ui.form.is_none());
    ui.set_chat(chat(
        "a",
        "canonical-user observed only after real canonical result",
    ));
    assert!(!ui.is_cached_chat_read_only());
    assert!(!ui.uncertain_turns.contains_key("a"));
    assert!(!ui.status.contains("read-only") && !ui.status.contains("offline"));
}
#[test]
fn offline_result_keeps_already_painted_canonical_and_active_turn_without_fake_ack() {
    let mut ui = ui();
    ui.set_chat(chat("a", "own latest optimistic row"));
    ui.pending_send = Some(("a".into(), Zeroizing::new("own send".into())));
    ui.active_turn = Some(ActiveTurn {
        chat_id: "a".into(),
        user_id: "u".into(),
        assistant: None,
        expects_reply: true,
    });
    ui.delivery = Delivery::Submitted {
        chat_id: "a".into(),
        message_id: "u".into(),
    };
    ui.streaming = true;
    ui.set_cached_chat_offline(chat("a", "older offline"));
    assert_eq!(
        ui.chat.as_ref().unwrap().messages[0].content,
        "own latest optimistic row"
    );
    assert!(ui.pending_send.is_some() && ui.active_turn.is_some() && ui.streaming);
    assert!(matches!(&ui.delivery,Delivery::Submitted {message_id,..} if message_id=="u"));
    assert!(ui.is_cached_chat_read_only());
}
#[test]
fn offline_embed_return_and_cancel_keep_the_read_only_lifetime() {
    let mut ui = ui();
    ui.set_cached_chat_offline(chat("a", "offline"));
    ui.set_item(
        Workspace::Apps,
        Item {
            id: "embed:x".into(),
            ..Default::default()
        },
    );
    ui.back();
    assert!(ui.is_cached_chat_read_only());
    assert!(!ui.is_cached_chat_refreshing());
    ui.set_status("Cancelled");
    assert!(ui.chat.is_none());
    assert!(!ui.is_cached_chat_read_only());
}

#[test]
fn monitor_offline_only_relabels_already_admitted_cached_views() {
    let mut ui = ui();
    ui.set_chat(chat("a", "canonical"));
    ui.mark_cached_chat_offline();
    assert!(!ui.is_cached_chat_read_only());
    ui.set_cached_chat(chat("b", "cached"));
    ui.draft = Editor::from("draft");
    ui.mark_cached_chat_offline();
    assert!(ui.is_cached_chat_read_only());
    assert!(!ui.is_cached_chat_refreshing());
    assert_eq!(ui.draft.text.as_str(), "draft");
    assert!(render(&mut ui).contains("Cached chat · offline"));
}

#[test]
fn cached_other_chat_never_displays_original_turn_content_question_or_stream_controls() {
    let mut ui = ui();
    ui.set_chat(chat("a", "A private optimistic user"));
    ui.pending_send = Some(("a".into(), Zeroizing::new("A submitted secret".into())));
    ui.active_turn = Some(ActiveTurn {
        chat_id: "a".into(),
        user_id: "a-user".into(),
        assistant: Some("a-assistant".into()),
        expects_reply: true,
    });
    ui.streaming = true;
    ui.delivery = Delivery::Admitted {
        chat_id: "a".into(),
        message_id: "a-user".into(),
    };
    ui.uncertain_turns.insert(
        "a".into(),
        UncertainTurn {
            message_id: "a-user".into(),
            text: Zeroizing::new("A uncertainty secret".into()),
            admitted: true,
        },
    );
    ui.form = Some(Form::new(
        "A private question",
        FormPurpose::Question(json!({})),
        vec![],
    ));
    ui.status = "A private task status".into();
    let mut b = chat("b", "B cached public fixture");
    b.messages[0].thinking = "B historical thought".into();
    ui.set_cached_chat(b.clone());
    for offline in [false, true] {
        if offline {
            ui.set_cached_chat_offline(b.clone());
        }
        let frame = render(&mut ui);
        assert!(frame.contains("B cached public fixture"));
        for absent in [
            "A private optimistic",
            "A submitted secret",
            "A private question",
            "A private task status",
            "Responding",
            "Thinking…",
            "Ctrl+C stop",
        ] {
            assert!(!frame.contains(absent), "wrong-chat presentation: {absent}");
        }
        assert!(ui.form.is_none());
        assert!(ui.streaming && ui.pending_send.is_some() && ui.active_turn.is_some());
        assert!(ui.uncertain_turns.contains_key("a"));
        assert!(matches!(&ui.delivery, Delivery::Admitted{chat_id,..} if chat_id=="a"));
    }
    ui.set_chat(chat("b", "B canonical"));
    assert!(!render(&mut ui).contains("Responding"));
    assert!(ui.pending_send.is_some() && ui.uncertain_turns.contains_key("a"));
    // Returning to A still owns the live journal; a same-chat cache cannot erase it.
    ui.set_chat(chat("a", "A current optimistic"));
    ui.streaming = true;
    ui.set_cached_chat(chat("a", "A older cache"));
    assert_eq!(
        ui.chat.as_ref().unwrap().messages[0].content,
        "A current optimistic"
    );
    assert!(ui.pending_send.is_some() && ui.uncertain_turns.contains_key("a"));
    assert!(render(&mut ui).contains("Responding"));
}

#[test]
fn online_cache_settlement_preserves_uncertain_delivery_and_exposes_existing_strict_actions() {
    let mut ui=ui();
    ui.uncertain_turns.insert("a".into(),UncertainTurn{message_id:"canonical-user".into(),text:Zeroizing::new("keep uncertain".into()),admitted:true});
    ui.last_uncertain=Some("a".into());
    ui.set_cached_chat(chat("a","all loaded cached messages"));
    ui.set_settled_chat(chat("a","all loaded cached messages"));
    assert!(!ui.is_cached_chat_read_only());assert!(!ui.is_cached_chat_refreshing());
    assert!(ui.uncertain_turns.contains_key("a"),"cached rows cannot settle delivery uncertainty");
    assert!(render(&mut ui).contains("Showing all cached messages"));
    assert!(!ui.cached_action_blocked(),"copy/share/download return to ordinary command admission");
    ui.share_form();assert!(matches!(&ui.form.as_ref().unwrap().purpose,FormPurpose::Share(id) if id=="a"));
    ui.form=None;ui.download_form();assert!(matches!(&ui.form.as_ref().unwrap().purpose,FormPurpose::Download(..)));
    // The runtime handlers retain strict share_chat/download; cache state does
    // not become their full-history proof. Losing live admission closes controls.
    ui.form=None;ui.mark_cached_chat_offline();assert!(ui.is_cached_chat_read_only());
    assert!(ui.cached_action_blocked());
}
#[test]
fn bounded_preview_cannot_replace_settled_cached_history_and_denial_hides_it() {
    let mut ui=ui();ui.set_settled_chat(chat("a","all cached rows"));
    ui.set_cached_chat(chat("a","older bounded preview"));
    assert_eq!(ui.chat.as_ref().unwrap().messages[0].content,"all cached rows");
    assert!(!ui.is_cached_chat_read_only());
    ui.hide_cached_chat();assert!(ui.chat.is_none());
}

#[test]
fn authorized_same_id_settlement_replaces_canonical_rows_for_render_and_copy_without_settling_delivery() {
    let mut ui=ui();ui.set_chat(chat("a","STALE_CANONICAL_BODY"));
    ui.uncertain_turns.insert("a".into(),UncertainTurn{message_id:"canonical-user".into(),text:Zeroizing::new("uncertain remains".into()),admitted:true});
    ui.last_uncertain=Some("a".into());
    ui.set_settled_chat(chat("a","AUTHORIZED_CACHE_BODY"));
    assert!(ui.uncertain_turns.contains_key("a"));assert_eq!(ui.last_uncertain.as_deref(),Some("a"));
    assert!(!ui.is_cached_chat_read_only());
    let frame=render(&mut ui);assert!(frame.contains("AUTHORIZED_CACHE_BODY"));assert!(!frame.contains("STALE_CANONICAL_BODY"));
    let commands=ui.activate(HitAction::Copy);
    assert!(matches!(&commands[..],[UiCommand::Copy(value)] if value.contains("AUTHORIZED_CACHE_BODY") && !value.contains("STALE_CANONICAL_BODY")));
}
