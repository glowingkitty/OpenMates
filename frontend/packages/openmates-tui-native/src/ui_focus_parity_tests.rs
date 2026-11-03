//! Keyboard focus parity with the TS TUI (tuiWorkspaceController.ts).
// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
use super::*;
fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
}
fn chat_item(id: &str) -> Item {
    Item { id: id.into(), title: format!("Chat {id}"), ..Default::default() }
}
fn chats_home() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_items(Workspace::Chats, vec![chat_item("a"), chat_item("b")]);
    ui
}
fn typed(ui: &mut Ui, text: &str) -> Vec<UiCommand> {
    text.chars().flat_map(|c| ui.key(key(KeyCode::Char(c)))).collect()
}

#[test]
fn typing_after_chats_navigation_starts_a_draft_instead_of_card_shortcuts() {
    let mut ui = chats_home();
    typed(&mut ui, "/chats");
    ui.key(key(KeyCode::Enter));
    assert!(ui.focus == Focus::Content);
    // `n`, `e` and `d` were card shortcuts (new/edit/delete forms) here.
    let commands = typed(&mut ui, "need details");
    assert!(commands.is_empty());
    assert!(ui.form.is_none());
    assert!(ui.focus == Focus::Composer);
    assert_eq!(ui.draft.text.to_string(), "need details");
}

#[test]
fn chat_home_arrows_and_enter_still_select_and_open_cards() {
    let mut ui = chats_home();
    typed(&mut ui, "/chats");
    ui.key(key(KeyCode::Enter));
    ui.key(key(KeyCode::Right));
    assert!(ui.focus == Focus::Content);
    assert_eq!(ui.selected[index(Workspace::Chats)], 1);
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Chats, id)] if id == "b"));
}

#[test]
fn slash_on_an_empty_draft_starts_a_command_from_any_workspace() {
    for workspace in [Workspace::Projects, Workspace::Tasks, Workspace::Workflows, Workspace::Apps] {
        let mut ui = chats_home();
        ui.nav(workspace);
        assert!(ui.focus == Focus::Content);
        typed(&mut ui, "/chats");
        assert!(ui.focus == Focus::Composer);
        assert_eq!(ui.draft.text.to_string(), "/chats");
        ui.key(key(KeyCode::Enter));
        assert_eq!(ui.workspace, Workspace::Chats);
    }
}

#[test]
fn other_workspaces_keep_their_content_shortcuts() {
    let mut ui = chats_home();
    ui.nav(Workspace::Projects);
    ui.set_items(Workspace::Projects, vec![chat_item("p")]);
    ui.key(key(KeyCode::Char('n')));
    // Projects keep their create shortcut (TS keeps per-screen content keys).
    assert!(ui.form.is_some());
    assert!(ui.draft.text.is_empty());
}

#[test]
fn home_starts_on_the_cards_so_enter_opens_the_selected_chat() {
    let mut ui = chats_home();
    assert!(ui.focus == Focus::Content);
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Chats, id)] if id == "a"));
    // Typing from the start screen still drafts a message.
    let mut ui = chats_home();
    typed(&mut ui, "hi");
    assert!(ui.focus == Focus::Composer);
    assert_eq!(ui.draft.text.to_string(), "hi");
}

#[test]
fn enter_on_cached_cards_before_authentication_still_opens_the_chat() {
    // Boot paints cached cards before the session is re-validated; no hidden
    // login form may swallow an early Enter (run_terminal no longer opens one).
    let mut ui = Ui::new();
    ui.set_items(Workspace::Chats, vec![chat_item("a")]);
    assert!(ui.form.is_none());
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Chats, id)] if id == "a"));
}

fn screen(ui: &mut Ui) -> String {
    let mut terminal = ratatui::Terminal::new(ratatui::backend::TestBackend::new(120, 38)).unwrap();
    terminal.draw(|frame| ui.draw(frame)).unwrap();
    let buffer = terminal.backend().buffer().clone();
    (0..38)
        .map(|y| (0..120).map(|x| buffer[(x, y)].symbol().to_owned()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn home_shows_ts_navigation_hint_and_places_the_pager_hint_under_the_pager() {
    let mut ui = chats_home();
    let text = screen(&mut ui);
    assert!(text.lines().next().unwrap().contains("Ctrl+G navigation"));
    let lines: Vec<&str> = text.lines().collect();
    let pager = lines.iter().position(|l| l.contains("Chat 1 of")).expect("pager");
    assert!(lines[pager + 1].contains("←/→ choose  ·  Enter open  ·  Tab write"));
    assert!(lines.iter().any(|l| l.trim() == "Continue where you left off"));
}

#[test]
fn opened_chat_header_has_the_chats_breadcrumb() {
    let mut ui = chats_home();
    ui.set_chat(Chat { id: "a".into(), title: "Trip plan".into(), ..Chat::default() });
    let text = screen(&mut ui);
    assert!(text.contains("› Chats › Trip plan"));
}

#[test]
fn composer_has_model_send_row_and_context_hint() {
    let mut ui = chats_home();
    let text = screen(&mut ui);
    assert!(text.contains("Model: Auto"));
    assert!(text.contains("Send ↵"));
    assert!(text.contains("←/→ chat   Enter open   Tab write   Ctrl+B sidebar"));
    ui.set_chat(Chat { id: "a".into(), title: "Trip".into(), ..Chat::default() });
    assert!(screen(&mut ui).contains("Enter send   Alt+Enter newline   Esc chats   Ctrl+B sidebar"));
}

#[test]
fn opened_chat_has_a_more_action_that_opens_the_palette() {
    let mut ui = chats_home();
    ui.set_chat(Chat { id: "a".into(), title: "Trip".into(), ..Chat::default() });
    assert!(screen(&mut ui).contains("More"));
    ui.activate(HitAction::Actions);
    assert!(ui.form.is_some());
}

#[test]
fn home_shows_two_wide_cards() {
    let mut ui = chats_home();
    let text = screen(&mut ui);
    assert!(text.contains("Chat 1 of 2"));
    assert_eq!(home_card_columns(120), 2);
    assert_eq!(home_card_columns(50), 1);
}
