use super::*;
use openmates_sdk::view_model::{ChatWindowSource, PiiRestoration, chat_window_from_chat};

const FIRST: RequestId = RequestId(1);
const SECOND: RequestId = RequestId(2);
const THIRD: RequestId = RequestId(3);

fn started(message_id: &str) -> StreamUpdate {
    StreamUpdate::Started {
        chat_id: "c".into(),
        message_id: message_id.into(),
        expects_reply: true,
    }
}

fn content(text: &str) -> StreamUpdate {
    StreamUpdate::Content {
        content: text.into(),
        thinking: String::new(),
        mate: String::new(),
    }
}

fn completed(message_id: &str, text: &str) -> StreamUpdate {
    StreamUpdate::Completed {
        chat_id: "c".into(),
        message_id: message_id.into(),
        content: text.into(),
    }
}

fn submit(ui: &mut Ui, request: RequestId, text: &str) {
    ui.paste(text);
    let commands = ui.key(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));
    let [
        UiCommand::Send {
            chat_id: Some(chat_id),
            text: sent,
        },
    ] = commands.as_slice()
    else {
        panic!("Enter must immediately dispatch a saved-chat send");
    };
    assert_eq!((chat_id.as_str(), sent.as_str()), ("c", text));
    ui.register_send(
        request,
        Some(chat_id),
        sent,
        ui.is_streaming_chat(Some(chat_id)),
    );
    assert!(ui.draft.text.is_empty());
}

fn streaming_ui() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_chat(Chat {
        id: "c".into(),
        ..Default::default()
    });
    submit(&mut ui, FIRST, "first");
    ui.stream_for(FIRST, started("u1"), true);
    ui.stream_for(
        FIRST,
        StreamUpdate::Submitted {
            chat_id: "c".into(),
            message_id: "u1".into(),
        },
        true,
    );
    ui.stream_for(
        FIRST,
        StreamUpdate::Admitted {
            chat_id: "c".into(),
            message_id: "u1".into(),
        },
        true,
    );
    ui.stream_for(FIRST, content("Still working"), true);
    ui
}

fn message<'a>(ui: &'a Ui, id: &str) -> &'a Message {
    ui.chat
        .as_ref()
        .unwrap()
        .messages
        .iter()
        .find(|message| message.id == id)
        .unwrap()
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced,chat-queued-followups.steering.active-artifact
#[test]
fn enter_sends_an_active_correction_and_associates_its_receipt_with_its_own_row() {
    let mut ui = streaming_ui();
    assert!(ui.is_streaming_chat(Some("c")));
    submit(&mut ui, SECOND, "Change the header to red");
    ui.stream_for(SECOND, started("u2"), true);
    assert!(
        !ui.queued_ids.contains_key("u2"),
        "the server decides how this message is routed"
    );
    ui.send_queued(SECOND, "c", Some("u2"), Some(SendQueueMode::Steer));

    assert!(matches!(
        ui.queued_ids.get("u2"),
        Some(SendQueueMode::Steer)
    ));
    assert!(!ui.queued_ids.contains_key("u1"));
    assert_eq!(message(&ui, "u2").content, "Change the header to red");
    assert_eq!(ui.active_turn.as_ref().unwrap().user_id, "u1");
    assert!(matches!(&ui.delivery, Delivery::Admitted { message_id, .. } if message_id == "u1"));
    assert!(ui.visible_chat_streaming());
    ui.stream_for(FIRST, content("Working on the correction"), true);
    assert_eq!(
        message(&ui, "__pending_assistant__:u1").content,
        "Working on the correction"
    );
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.routing.active-work
#[test]
fn overlapping_replies_and_out_of_order_receipts_keep_their_own_messages() {
    let mut ui = streaming_ui();
    submit(&mut ui, SECOND, "independent question");
    ui.stream_for(SECOND, started("u2"), true);
    ui.stream_for(SECOND, content("Second reply"), true);
    ui.stream_for(FIRST, content("First reply"), true);
    assert_eq!(
        message(&ui, "__pending_assistant__:u1").content,
        "First reply"
    );
    assert_eq!(
        message(&ui, "__pending_assistant__:u2").content,
        "Second reply"
    );

    ui.stream_for(SECOND, completed("a2", "Final second reply"), true);
    let second_snapshot = Chat {
        id: "c".into(),
        messages: vec![message(&ui, "u2").clone(), message(&ui, "a2").clone()],
        ..Default::default()
    };
    ui.send_finished(
        SECOND,
        second_snapshot,
        true,
        &[Some("u2".into()), Some("a2".into())],
    );
    assert!(ui.visible_chat_streaming());

    ui.stream_for(FIRST, completed("a1", "Final first reply"), true);
    let first_snapshot = Chat {
        id: "c".into(),
        messages: vec![
            message(&ui, "u1").clone(),
            message(&ui, "a1").clone(),
            Message {
                content: "Stale second reply".into(),
                ..message(&ui, "a2").clone()
            },
        ],
        ..Default::default()
    };
    ui.send_finished(
        FIRST,
        first_snapshot,
        true,
        &[Some("u1".into()), Some("a1".into())],
    );
    assert!(!ui.visible_chat_streaming());
    assert_eq!(message(&ui, "a1").content, "Final first reply");
    assert_eq!(message(&ui, "a2").content, "Final second reply");
    assert_eq!(ui.chat.as_ref().unwrap().messages.len(), 4);
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn a_staged_followup_failure_restores_only_its_retry_and_never_touches_another_turn() {
    let mut ui = streaming_ui();
    submit(&mut ui, SECOND, "correction");
    ui.stream_for(SECOND, started("u2"), true);
    submit(&mut ui, THIRD, "next correction");
    ui.stream_for(THIRD, started("u3"), true);
    ui.send_failed(SECOND, "Connection interrupted");

    assert!(ui.visible_chat_streaming());
    assert_eq!(message(&ui, "u3").content, "next correction");
    assert!(
        ui.chat
            .as_ref()
            .unwrap()
            .messages
            .iter()
            .all(|message| message.id != "u2")
    );
    ui.command("/retry");
    assert_eq!(ui.draft.text.as_str(), "correction");
    assert!(matches!(&ui.delivery, Delivery::Admitted { message_id, .. } if message_id == "u1"));
}

#[test]
fn submitted_followup_failure_retains_text_without_reassigning_the_predecessor_fence() {
    let mut ui = streaming_ui();
    submit(&mut ui, SECOND, "correction");
    ui.stream_for(SECOND, started("u2"), true);
    ui.stream_for(
        SECOND,
        StreamUpdate::Submitted {
            chat_id: "c".into(),
            message_id: "u2".into(),
        },
        true,
    );
    ui.send_failed(SECOND, "Connection interrupted");
    ui.command("/retry");
    assert!(ui.draft.text.is_empty());
    assert!(
        matches!(&ui.command("/copy-pending")[..], [UiCommand::Copy(text)] if text == "correction")
    );
    assert!(matches!(&ui.delivery, Delivery::Admitted { message_id, .. } if message_id == "u1"));
    assert!(ui.visible_chat_streaming());
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn queued_label_uses_saved_state_instead_of_an_unrelated_assistant_reply() {
    let mut ui = streaming_ui();
    submit(&mut ui, SECOND, "correction");
    ui.stream_for(SECOND, started("u2"), true);
    ui.send_queued(SECOND, "c", Some("u2"), Some(SendQueueMode::Steer));
    let snapshot = Chat {
        id: "c".into(),
        messages: vec![
            message(&ui, "u2").clone(),
            Message {
                id: "other".into(),
                role: "assistant".into(),
                ..Default::default()
            },
        ],
        ..Default::default()
    };
    let mut window = chat_window_from_chat(
        &snapshot,
        ChatWindowSource::Canonical,
        None,
        false,
        false,
        PiiRestoration::PageLocal,
    )
    .unwrap();
    window.messages[0].metadata.queue_mode = Some("steer".into());
    window.messages[0].metadata.queue_dispatch_status = Some("queued".into());
    ui.update_saved_queue_labels(&window);
    assert!(matches!(
        ui.queued_ids.get("u2"),
        Some(SendQueueMode::Steer)
    ));
    window.messages[0].metadata.queue_dispatch_status = Some("processing".into());
    ui.update_saved_queue_labels(&window);
    assert!(!ui.queued_ids.contains_key("u2"));
}

// contract-test: supporting surface=cli assertions=chat-queued-followups.admission.synced
#[test]
fn runtime_keeps_view_epoch_only_for_a_follow_up_in_the_streaming_chat() {
    let ui = streaming_ui();
    assert!(ui.is_streaming_chat(Some("c")));
    assert!(!ui.is_streaming_chat(Some("other")));
    assert!(!ui.is_streaming_chat(None));
}

fn task_assigned(message_id: &str, task_id: &str) -> StreamUpdate {
    StreamUpdate::TaskAssigned {
        chat_id: "c".into(),
        message_id: message_id.into(),
        task_id: task_id.into(),
    }
}

#[test]
fn an_ambiguous_stop_requires_the_named_foreground_reply() {
    let mut ui = streaming_ui();
    ui.stream_for(FIRST, task_assigned("u1", "first-task"), true);
    submit(&mut ui, SECOND, "another question");
    ui.stream_for(SECOND, started("u2"), true);
    ui.stream_for(SECOND, task_assigned("u2", "second-task"), true);

    assert!(
        ui.key(KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL))
            .is_empty()
    );
    assert!(ui.command("/stop unknown-task").is_empty());
    assert!(matches!(
        &ui.command("/stop second-task")[..],
        [UiCommand::StopSend { request: SECOND, task: Some((chat, task)) }] if chat == "c" && task == "second-task"
    ));
    ui.stop_result(SECOND, Ok(()));
    assert_eq!(ui.status, "Stop requested for this response");
    ui.stream_for(FIRST, content("First response continues"), true);
    assert_eq!(
        message(&ui, "__pending_assistant__:u1").content,
        "First response continues"
    );
}

#[test]
fn control_c_keeps_single_reply_and_idle_exit_behavior() {
    let mut ui = streaming_ui();
    let ctrl_c = KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL);
    assert!(matches!(
        &ui.key(ctrl_c)[..],
        [UiCommand::StopSend {
            request: FIRST,
            task: None
        }]
    ));
    ui.stream_for(FIRST, task_assigned("u1", "first-task"), true);
    assert!(matches!(
        &ui.key(ctrl_c)[..],
        [UiCommand::StopSend { request: FIRST, task: Some((chat, task)) }] if chat == "c" && task == "first-task"
    ));
    ui.stream_for(FIRST, completed("a1", "Done"), true);
    assert!(matches!(&ui.key(ctrl_c)[..], [UiCommand::Quit]));
}
