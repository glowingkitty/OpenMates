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
