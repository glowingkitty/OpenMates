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

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
#[test]
fn opened_chat_shows_the_embed_carousel_instead_of_raw_reference_json() {
    let mut ui = chat_with_embeds();
    let text = screen(&mut ui);
    assert!(text.contains("Embed 1/2 · ←/→ choose · Enter open · /embed emb-v-1"), "{text}");
    assert!(text.contains("Embed · Code"));
    assert!(!text.contains("embed_id"));
    assert!(!text.contains("╭─ json"));
    assert!(text.contains("Anything else?"));
}

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
#[test]
fn arrows_choose_and_enter_opens_the_selected_embed() {
    let mut ui = chat_with_embeds();
    screen(&mut ui);
    ui.focus = Focus::Content;
    assert!(ui.key(key(KeyCode::Right)).is_empty());
    let text = screen(&mut ui);
    assert!(text.contains("Embed 2/2 · ←/→ choose · Enter open · /embed web-s-1"), "{text}");
    assert!(text.contains("recipe APIs"));
    // Right at the end stays on the last reference, as in TS.
    ui.key(key(KeyCode::Right));
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{SEARCH}")));
    ui.key(key(KeyCode::Left));
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{CODE}")));
}

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
#[test]
fn slash_embed_accepts_the_displayed_short_reference() {
    let mut ui = chat_with_embeds();
    for c in "/embed emb-v-1".chars() {
        ui.key(key(KeyCode::Char(c)));
    }
    let commands = ui.key(key(KeyCode::Enter));
    assert!(matches!(&commands[..], [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{CODE}")), "{}", commands.len());
}

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
#[test]
fn streamed_code_card_alias_resolves_the_full_id_even_with_a_matching_uuid_prefix() {
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    let request_id = RequestId(41);
    ui.paste("Build a recipe app");
    let commands = ui.key(key(KeyCode::Enter));
    let [UiCommand::Send { chat_id: None, text }] = &commands[..] else {
        panic!("A fresh chat must submit through the ordinary composer");
    };
    ui.register_send(request_id, None, text, false);
    ui.stream_for(
        request_id,
        StreamUpdate::Started {
            chat_id: "recipe-chat".into(),
            message_id: "recipe-request".into(),
            expects_reply: true,
        },
        true,
    );
    let other = "237a754b-9f65-4ddd-b761-2d601131837e";
    let reference = |id| format!("```json\n{}\n", json!({"type": "code", "embed_id": id}));
    let stream = |ui: &mut Ui, content| {
        ui.stream_for(
            request_id,
            StreamUpdate::Content {
                content,
                thinking: String::new(),
                mate: String::new(),
            },
            true,
        );
    };
    stream(&mut ui, reference(CODE));
    // An unfinished fence has no embed card.
    assert!(!screen(&mut ui).contains("/embed emb-v-1"));
    stream(&mut ui, format!("{}```\n\n", reference(CODE)));
    let first_screen = screen(&mut ui);
    assert!(first_screen.contains("│ Embed · Code "));
    assert!(first_screen.contains("│ /embed emb-v-1 "));
    assert!(!first_screen.contains("/embed 237a754b"));
    stream(
        &mut ui,
        format!(
            "{}```\n\nAnother result.\n\n{}```\n\n",
            reference(CODE),
            reference(other)
        ),
    );
    screen(&mut ui);
    for (alias, expected) in [
        ("emb-v-1", CODE),
        ("emb-v-2", other),
        ("237a754b", "237a754b"),
        (CODE, CODE),
    ] {
        for c in format!("/embed {alias}").chars() {
            ui.key(key(KeyCode::Char(c)));
        }
        let commands = ui.key(key(KeyCode::Enter));
        assert!(matches!(
            &commands[..],
            [UiCommand::Open(Workspace::Apps, id)] if id == &format!("embed:{expected}")
        ));
    }
    ui.set_item(
        Workspace::Apps,
        Item {
            id: CODE.into(),
            fields: json!({
                "type": "code",
                "content": {
                    "app_id": "code",
                    "skill_id": "code",
                    "filename": "recipe.html",
                    "code": "<h1>Recipes</h1>",
                },
            }),
            ..Default::default()
        },
    );
    let details = screen(&mut ui);
    assert!(details.contains("Code · Code  ·  emb-v-1"), "{details}");
    assert!(!details.contains("Code · Code  ·  emb-v-2"));
}

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
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
