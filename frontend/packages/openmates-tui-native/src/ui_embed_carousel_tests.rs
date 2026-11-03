use super::*;
const CODE: &str = "237a754b-f65c-4e2c-aea2-edaf207b0998";
const SEARCH: &str = "9b4f1c2e-0000-4000-8000-000000000002";
fn key(code: KeyCode) -> KeyEvent {
    KeyEvent::new(code, KeyModifiers::NONE)
}
fn chat_with_embeds() -> Ui {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    let reference = |body: &str| format!("```json\n{body}\n```\n\n");
    ui.set_chat(Chat {
        id: "chat".into(),
        title: "Recipe app".into(),
        messages: vec![
            Message { id: "u".into(), role: "user".into(), content: "Build it".into(), ..Default::default() },
            Message {
                id: "a".into(),
                role: "assistant".into(),
                content: format!(
                    "Here is the app.\n\n{}{}Anything else?",
                    reference(&format!("{{\"type\": \"code\", \"embed_id\": \"{CODE}\"}}")),
                    reference(&format!(
                        "{{\"type\":\"app_skill_use\",\"embed_id\":\"{SEARCH}\",\"app_id\":\"web\",\"skill_id\":\"search\",\"query\":\"recipe APIs\"}}"
                    )),
                ),
                ..Default::default()
            },
        ],
        ..Default::default()
    });
    ui
}
fn screen(ui: &mut Ui) -> String {
    let mut terminal = ratatui::Terminal::new(ratatui::backend::TestBackend::new(120, 40)).unwrap();
    terminal.draw(|frame| ui.draw(frame)).unwrap();
    let buffer = terminal.backend().buffer().clone();
    (0..40)
        .map(|y| (0..120).map(|x| buffer[(x, y)].symbol().to_owned()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn opened_chat_shows_the_embed_carousel_instead_of_raw_reference_json() {
    let mut ui = chat_with_embeds();
    let text = screen(&mut ui);
    assert!(text.contains("Embed 1/2 · ←/→ choose · Enter open · /embed 237a754b"), "{text}");
    assert!(text.contains("Embed · Code"));
    assert!(!text.contains("embed_id"));
    assert!(!text.contains("╭─ json"));
    assert!(text.contains("Anything else?"));
}

#[test]
fn arrows_choose_and_enter_opens_the_selected_embed() {
    let mut ui = chat_with_embeds();
    screen(&mut ui);
    ui.focus = Focus::Content;
    assert!(ui.key(key(KeyCode::Right)).is_empty());
    let text = screen(&mut ui);
    assert!(text.contains("Embed 2/2 · ←/→ choose · Enter open · /embed 9b4f1c2e"), "{text}");
    assert!(text.contains("recipe APIs"));
    // Right at the end stays on the last reference, as in TS.
    ui.key(key(KeyCode::Right));
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{SEARCH}")));
    ui.key(key(KeyCode::Left));
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{CODE}")));
}

#[test]
fn slash_embed_accepts_the_displayed_short_reference() {
    let mut ui = chat_with_embeds();
    for c in "/embed 237a754b".chars() {
        ui.key(key(KeyCode::Char(c)));
    }
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{CODE}")), "{}", commands.len());
}

#[test]
fn embed_detail_shows_a_per_type_summary() {
    let mut ui = chat_with_embeds();
    ui.set_item(
        Workspace::Apps,
        Item {
            id: CODE.into(),
            title: "App.tsx".into(),
            category: "code".into(),
            fields: json!({"type":"code","content":{"type":"code","language":"tsx","filename":"App.tsx","code":"export default function App() {}"}}),
            ..Default::default()
        },
    );
    let text = screen(&mut ui);
    assert!(text.contains("Code  ·  237a754b"), "{text}");
    assert!(text.contains("Language: tsx"));
    assert!(text.contains("export default function App"));
    assert!(!text.contains("\"language\""));
}
