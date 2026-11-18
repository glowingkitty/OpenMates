use super::*;

fn streaming_ui() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_chat(Chat {
        id: "c".into(),
        ..Default::default()
    });
    ui.paste("first");
    let commands = ui.send();
    assert!(matches!(&commands[..], [UiCommand::Send { .. }]));
    ui.stream(StreamUpdate::Started {
        chat_id: "c".into(),
        message_id: "u1".into(),
        expects_reply: true,
    });
    ui
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn follow_up_while_streaming_is_sent_at_once() {
    let mut ui = streaming_ui();
    assert!(ui.streaming && ui.can_queue_followup());
    ui.paste("second");
    let commands = ui.send();
    assert!(
        matches!(&commands[..], [UiCommand::Send { chat_id: Some(id), text }] if id == "c" && text == "second")
    );
    assert!(ui.draft.text.is_empty());
    assert!(ui.streaming, "the first reply keeps streaming");
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn follow_up_row_is_labelled_queued_and_first_turn_is_untouched() {
    let mut ui = streaming_ui();
    ui.paste("second");
    ui.send();
    ui.stream(StreamUpdate::Started {
        chat_id: "c".into(),
        message_id: "u2".into(),
        expects_reply: true,
    });
    ui.followup_queued("c", Some("u2"));
    assert!(ui.queued_ids.contains("u2") && !ui.queued_ids.contains("u1"));
    let turn = ui.active_turn.as_ref().unwrap();
    assert_eq!(turn.user_id, "u1");
    assert!(ui.streaming && ui.pending_send.is_some());
    let chat = ui.chat.as_ref().unwrap();
    assert!(
        chat.messages
            .iter()
            .any(|m| m.id == "u2" && m.content == "second")
    );
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn queued_label_clears_once_an_assistant_reply_follows() {
    let mut ui = streaming_ui();
    ui.paste("second");
    ui.send();
    ui.stream(StreamUpdate::Started {
        chat_id: "c".into(),
        message_id: "u2".into(),
        expects_reply: true,
    });
    let msg = |id: &str, role: &str| Message {
        id: id.into(),
        role: role.into(),
        ..Default::default()
    };
    ui.set_chat(Chat {
        id: "c".into(),
        messages: vec![msg("u1", "user"), msg("a1", "assistant"), msg("u2", "user")],
        ..Default::default()
    });
    assert!(ui.queued_ids.contains("u2"));
    ui.set_chat(Chat {
        id: "c".into(),
        messages: vec![
            msg("u1", "user"),
            msg("a1", "assistant"),
            msg("u2", "user"),
            msg("a2", "assistant"),
        ],
        ..Default::default()
    });
    assert!(ui.queued_ids.is_empty());
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn runtime_keeps_view_epoch_only_for_a_follow_up_in_the_streaming_chat() {
    let ui = streaming_ui();
    assert!(ui.is_streaming_chat(Some("c")));
    assert!(!ui.is_streaming_chat(Some("other")));
    assert!(!ui.is_streaming_chat(None));
}
