//! Settings menu and per-workspace composer parity with the TS TUI.
// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
use super::*;
fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
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
fn signed_in() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_username("Glowingkitty");
    ui
}

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
#[test]
fn settings_menu_lists_the_ts_pages_with_web_markers_and_key_hints() {
    let mut ui = signed_in();
    ui.set_settings_restricted(true);
    ui.settings_toggle();
    let text = screen(&mut ui);
    for label in ["AI", "Privacy", "Projects ↗", "Mates", "Notifications", "Interface", "Developers", "Support & Community ↗", "Log out", "Esc back/close"] {
        assert!(text.contains(label), "{label}\n{text}");
    }
    // The identity header wraps inside the fixed-width panel: "… · Paired" / "session".
    let lines: Vec<&str> = text.lines().collect();
    let header = lines
        .iter()
        .position(|line| line.contains("Glowingkitty · Personal · Paired"))
        .unwrap_or_else(|| panic!("identity header missing\n{text}"));
    assert!(lines[header + 1].contains("│session"), "{text}");
    assert!(!text.contains("Profile") && !text.contains("Billing"), "{text}");
}

// contract-test: supporting surface=cli assertions=terminal-settings.navigation.web-hierarchy-and-capabilities
#[test]
fn log_out_row_issues_the_logout_command() {
    let mut ui = signed_in();
    let commands = ui.activate(HitAction::SettingsRoute(settings_catalog::LOGOUT_ROUTE.into()));
    assert!(matches!(&commands[..], [UiCommand::Logout]));
}

// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
#[test]
fn project_composer_names_a_new_project_instead_of_sending_a_chat() {
    let mut ui = signed_in();
    ui.nav(Workspace::Projects);
    assert!(screen(&mut ui).contains("Name a new project  ·  /search to browse"));
    ui.focus = Focus::Composer;
    for c in "Kitchen remodel".chars() {
        ui.key(key(KeyCode::Char(c)));
    }
    let commands = ui.key(key(KeyCode::Enter));
    assert!(commands.is_empty());
    let form = ui.form.as_ref().expect("create form");
    assert!(matches!(form.purpose, FormPurpose::Create(Workspace::Projects)));
    assert_eq!(form.fields[0].editor.text.to_string(), "Kitchen remodel");
}

// contract-test: supporting surface=cli assertions=terminal-ui.workspaces.web-aligned
#[test]
fn workflow_and_task_composers_use_their_ts_placeholders() {
    let mut ui = signed_in();
    ui.nav(Workspace::Workflows);
    assert!(screen(&mut ui).contains("Describe new workflow  ·  /search to browse"));
    ui.nav(Workspace::Tasks);
    assert!(screen(&mut ui).contains("Add or update tasks  ·  /search to browse"));
}
