use super::super::*;
use ratatui::{Terminal, backend::TestBackend};

const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const LAST_LINE: &str = "UNREAD_LONG_REPLY_LAST_LINE";

fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
}
fn render(ui: &mut Ui, width: u16, height: u16) -> String {
    let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
    terminal.draw(|frame| ui.draw(frame)).unwrap();
    terminal.backend().buffer().content().iter().map(|cell| cell.symbol()).collect()
}
fn chat_item(unread: u64) -> Item {
    Item {
        id: CHAT.into(),
        title: "Rainbows".into(),
        fields: json!({"unread_count":unread}),
        ..Default::default()
    }
}
fn long_reply_chat() -> Chat {
    let mut reply: Vec<String> = (1..=60).map(|n| format!("Step {n} of the explanation.")).collect();
    reply.push(LAST_LINE.into());
    Chat {
        id: CHAT.into(),
        title: "Rainbows".into(),
        category: String::new(),
        messages: vec![
            Message { id: "u1".into(), role: "user".into(), content: "Explain rainbows".into(), ..Message::default() },
            Message { id: "a1".into(), role: "assistant".into(), content: reply.join("\n\n"), ..Message::default() },
        ],
    }
}
fn signed_in(unread: u64) -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_items(Workspace::Chats, vec![chat_item(unread)]);
    ui
}
fn is_mark_read(command: &UiCommand) -> bool {
    matches!(command, UiCommand::MarkRead(id) if id == CHAT)
}

// contract-test: direct surface=cli assertions=chat-unread.reply.read-at-last-line
#[test]
fn unread_chat_opens_at_the_newest_reply_and_reads_only_once_its_last_line_is_shown() {
    let mut ui = signed_in(1);
    ui.set_chat(long_reply_chat());
    let screen = render(&mut ui, 120, 30);
    assert!(screen.contains("Step 1 of the explanation."), "opens at the reply start");
    assert!(!screen.contains(LAST_LINE));
    assert!(ui.take_deferred_commands().is_empty());
    assert_eq!(unread::unread_count(&ui.items[0][0]), 1);

    // Closing after a partial read keeps it unread.
    ui.key(key(KeyCode::Esc));
    render(&mut ui, 120, 30);
    assert!(ui.take_deferred_commands().is_empty());
    assert_eq!(unread::unread_count(&ui.items[0][0]), 1);

    // Showing the last line marks it read once.
    ui.set_chat(long_reply_chat());
    render(&mut ui, 120, 30);
    ui.follow_tail = true;
    let screen = render(&mut ui, 120, 30);
    assert!(screen.contains(LAST_LINE));
    let commands = ui.take_deferred_commands();
    assert_eq!(commands.len(), 1);
    assert!(is_mark_read(&commands[0]));
    assert_eq!(unread::unread_count(&ui.items[0][0]), 0);
    render(&mut ui, 120, 30);
    assert!(ui.take_deferred_commands().is_empty());
}

// contract-test: direct surface=cli assertions=chat-unread.reply.read-at-last-line
#[test]
fn an_unread_cached_chat_opens_at_the_newest_reply_and_the_refresh_keeps_it() {
    let mut ui = signed_in(1);
    ui.set_cached_chat(long_reply_chat());
    let screen = render(&mut ui, 120, 30);
    assert!(screen.contains("Step 1 of the explanation."), "cached view opens at the reply start");
    assert!(!screen.contains(LAST_LINE));
    ui.set_chat(long_reply_chat());
    let screen = render(&mut ui, 120, 30);
    assert!(screen.contains("Step 1 of the explanation."), "refresh keeps the reply start");
    assert!(!screen.contains(LAST_LINE));
    assert!(ui.take_deferred_commands().is_empty());
    assert_eq!(unread::unread_count(&ui.items[0][0]), 1);
}

// contract-test: direct surface=cli assertions=chat-unread.reply.read-at-last-line
#[test]
fn a_read_chat_opens_at_the_tail_and_sends_nothing() {
    let mut ui = signed_in(0);
    ui.set_chat(long_reply_chat());
    let screen = render(&mut ui, 120, 30);
    assert!(screen.contains(LAST_LINE));
    assert!(ui.take_deferred_commands().is_empty());
}

// contract-test: direct surface=cli assertions=chat-unread.followup.implies-read
#[test]
fn answering_an_unread_reply_marks_it_read_before_sending() {
    let mut ui = signed_in(1);
    ui.set_chat(long_reply_chat());
    render(&mut ui, 120, 30);
    ui.focus = Focus::Composer;
    for c in "and double rainbows?".chars() {
        ui.key(key(KeyCode::Char(c)));
    }
    let commands = ui.key(key(KeyCode::Enter));
    assert_eq!(commands.len(), 2);
    assert!(is_mark_read(&commands[0]));
    assert!(matches!(&commands[1], UiCommand::Send { chat_id: Some(id), .. } if id == CHAT));
    assert_eq!(unread::unread_count(&ui.items[0][0]), 0);
}

// contract-test: direct surface=cli assertions=chat-unread.surfaces.sidebar-and-continue
#[test]
fn counters_show_on_continue_cards_and_sidebar_rows_capped_at_nine_plus() {
    let mut ui = signed_in(2);
    ui.sidebar = true;
    let screen = render(&mut ui, 160, 40);
    assert!(screen.matches("●2 Rainbows").count() >= 2, "sidebar row and Continue card");
    ui.set_items(Workspace::Chats, vec![chat_item(12)]);
    let screen = render(&mut ui, 160, 40);
    assert!(screen.contains("●9+ Rainbows"));
    ui.set_items(Workspace::Chats, vec![chat_item(0)]);
    let screen = render(&mut ui, 160, 40);
    assert!(screen.contains("Rainbows"));
    assert!(!screen.contains("●0") && !screen.contains("● Rainbows"));
}
