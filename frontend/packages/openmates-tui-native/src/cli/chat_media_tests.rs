// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::super::parity_test_support::{mock, parsed};
use super::*;
use openmates_sdk::client::{
    assistant_speech::AssistantSpeechSummary,
    chat_files::{ChatFileError, ChatFiles, embed_file_references},
};

const CHAT: &str = "11111111-2222-4333-8444-555555555555";

#[test]
fn supports_exactly_the_three_media_commands() {
    for args in [
        vec!["openmates", "chats", "files", CHAT],
        vec!["openmates", "chats", "open"],
        vec!["openmates", "chats", "speak", CHAT, "--all"],
    ] {
        assert!(supported(&parsed(&args)), "{args:?}");
    }
    assert!(!supported(&parsed(&["openmates", "chats", "list"])));
}

fn files() -> ChatFiles {
    ChatFiles {
        chat_id: CHAT.into(),
        title: "Quarterly \u{1b}[31mreport".into(),
        files: embed_file_references(
            "embed-1",
            "pdf",
            &json!({"filename":"q3.pdf","page_count":2,"app_id":"docs","url":"https://cdn.test/q3.pdf"}),
        ),
        errors: vec![ChatFileError {
            embed_id: "embed-2".into(),
            message: "This operation is not available for the current account or Team.".into(),
        }],
    }
}

#[test]
fn files_output_keeps_the_npm_text_json_and_warning_contract() {
    let text = files_output(&parsed(&["openmates", "chats", "files", CHAT]), &files())
        .ok()
        .unwrap();
    assert!(text.stdout.starts_with("Files for Quarterly "));
    assert!(
        !text.stdout.contains('\u{1b}'),
        "control characters are escaped"
    );
    assert!(
        text.stdout.contains(
            "  q3.pdf  PDF | 2 pages  docs\n    embed:embed-1  https://cdn.test/q3.pdf\n"
        )
    );
    assert_eq!(
        text.stderr,
        "Warning: could not inspect embed embed-2: This operation is not available for the current account or Team.\n"
    );
    assert_eq!(text.exit_code, 0);
    let out = files_output(
        &parsed(&["openmates", "chats", "files", CHAT, "--json"]),
        &files(),
    )
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&out.stdout).unwrap();
    assert_eq!(value["chat_id"], CHAT);
    assert_eq!(value["source"], "chat");
    assert_eq!(value["count"], 1);
    assert_eq!(value["files"][0]["content_ref"], "embed:embed-1");
    assert_eq!(value["files"][0]["skill_id"], Value::Null);
    assert_eq!(
        value["errors"],
        json!([{"embed_id":"embed-2","message":"This operation is not available for the current account or Team."}])
    );
    let empty = ChatFiles {
        chat_id: CHAT.into(),
        ..ChatFiles::default()
    };
    let out = files_output(&parsed(&["openmates", "chats", "files", CHAT]), &empty)
        .ok()
        .unwrap();
    assert_eq!(
        out.stdout,
        format!("Files for {CHAT}\nNo files found for this chat.\n")
    );
    let out = files_output(
        &parsed(&["openmates", "chats", "files", CHAT, "--json"]),
        &empty,
    )
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap()["title"],
        Value::Null
    );
}

#[test]
fn speak_output_fails_the_process_when_any_segment_failed() {
    let mut summary = AssistantSpeechSummary {
        chat_id: CHAT.into(),
        messages: 2,
        generated_segments: 3,
        reused_segments: 1,
        failed_segments: 0,
        charged_segments: 3,
    };
    let out = speak_output(
        &parsed(&["openmates", "chats", "speak", CHAT, "--all"]),
        &summary,
    )
    .ok()
    .unwrap();
    assert_eq!(
        out.stdout,
        "Assistant speech saved for 2 message(s).\nGenerated 3, reused 1, failed 0.\n"
    );
    assert_eq!(out.exit_code, 0);
    summary.failed_segments = 1;
    let out = speak_output(
        &parsed(&["openmates", "chats", "speak", CHAT, "--all", "--json"]),
        &summary,
    )
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap(),
        json!({"chat_id":CHAT,"messages":2,"generated_segments":3,"reused_segments":1,"failed_segments":1,"charged_segments":3})
    );
    assert_eq!(out.exit_code, 1);
}

#[test]
fn open_position_target_and_output_follow_npm() {
    let position = |args: &[&str]| {
        open_position(&parsed(
            &[&["openmates", "chats", "open"][..], args].concat(),
        ))
    };
    assert_eq!(position(&[]).ok(), Some(1));
    assert_eq!(position(&["3"]).ok(), Some(3));
    assert_eq!(position(&["2abc"]).ok(), Some(2));
    for bad in ["0", "abc", "+x"] {
        match position(&[bad]) {
            Err(CliError::Invalid(message)) => assert_eq!(
                message,
                format!(
                    "Invalid position '{bad}'. Must be a positive integer (1 = most recent, 2 = second most recent, ...)."
                )
            ),
            _ => panic!("expected invalid position for {bad}"),
        }
    }
    let item = |id: &str, title: Value| crate::model::Item {
        id: id.into(),
        fields: json!({"chat_list_title": title}),
        ..Default::default()
    };
    let items = vec![
        item(CHAT, json!("Trip plan")),
        item("22222222-0000-4000-8000-000000000000", Value::Null),
    ];
    assert!(
        matches!(open_target(&[], 1), Err(CliError::Invalid(m)) if m == "No chats found. Run 'openmates chats list' to sync.")
    );
    assert!(
        matches!(open_target(&items, 3), Err(CliError::Invalid(m)) if m == "Only 2 chat(s) available — cannot open chat #3.")
    );
    let url = format!("https://app.test/#chat-id={CHAT}");
    let target = open_target(&items, 1).ok().unwrap();
    let text = parsed(&["openmates", "chats", "open"]);
    let out = open_output(&text, 1, &target, &url, true).ok().unwrap();
    assert_eq!(
        (out.stdout.as_str(), out.stderr.as_str()),
        ("", "Opening chat #1: \"Trip plan\"\n")
    );
    let out = open_output(&text, 1, &target, &url, false).ok().unwrap();
    assert_eq!(out.stdout, format!("{url}\n"));
    let untitled = open_target(&items, 2).ok().unwrap();
    let out = open_output(&text, 2, &untitled, &url, true).ok().unwrap();
    assert_eq!(out.stderr, "Opening chat #2: 22222222\n");
    let json_mode = parsed(&["openmates", "chats", "open", "--json"]);
    let out = open_output(&json_mode, 1, &target, &url, true)
        .ok()
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap(),
        json!({"url": url, "chat_id": CHAT, "position": 1, "title": "Trip plan"})
    );
    assert!(out.stderr.is_empty());
}

#[tokio::test]
async fn invalid_input_fails_before_any_network_read() {
    let (mut client, server) = mock(vec![]).await;
    // The catalog parser rejects a missing chat ID first; the adapter keeps
    // the preserved messages for directly constructed invocations.
    let bare = |command: &str| Invocation {
        path: vec!["chats".into(), command.into()],
        positionals: vec![],
        flags: Default::default(),
    };
    for (command, expected) in [
        (
            "files",
            "Missing chat ID. Usage: openmates chats files <chat-id> [--json]",
        ),
        ("speak", "Missing <chat-id>."),
    ] {
        match execute(&bare(command), &mut client, CancellationToken::new()).await {
            Err(CliError::Invalid(message)) => assert_eq!(message, expected),
            _ => panic!("expected invalid input for {command}"),
        }
    }
    let cases: Vec<(Vec<&str>, &str)> = vec![
        (
            vec![
                "openmates",
                "chats",
                "files",
                CHAT,
                "--api-key",
                "sk-placeholder",
            ],
            "Chat file listing through --api-key is not supported; use an authenticated CLI session so encrypted chat embeds can be decrypted locally.",
        ),
        (
            vec![
                "openmates",
                "chats",
                "speak",
                CHAT,
                "--all",
                "--api-key",
                "sk-placeholder",
            ],
            "Chat speech through --api-key is not supported; use an authenticated CLI session.",
        ),
        (
            vec!["openmates", "chats", "open", "zero"],
            "Invalid position 'zero'. Must be a positive integer (1 = most recent, 2 = second most recent, ...).",
        ),
    ];
    for (args, expected) in cases {
        match execute(&parsed(&args), &mut client, CancellationToken::new()).await {
            Err(CliError::Invalid(message)) => assert_eq!(message, expected, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    for args in [
        vec!["openmates", "chats", "files", "last"],
        vec!["openmates", "chats", "speak", "1111", "--all"],
        vec!["openmates", "chats", "open", "--api-key", "sk-placeholder"],
    ] {
        assert!(
            matches!(
                execute(&parsed(&args), &mut client, CancellationToken::new()).await,
                Err(CliError::Unsupported { .. })
            ),
            "{args:?}"
        );
    }
    assert!(server.await.unwrap().is_empty());
}
