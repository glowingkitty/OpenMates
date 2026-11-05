// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
use super::*;
fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
#[tokio::test]
async fn focus_commands_parse_and_validate_the_chat_before_any_request() {
    for action in ["activate", "deactivate"] {
        let i = invocation(&[
            "openmates",
            "projects",
            "settings",
            "engineering",
            "focus",
            action,
            "--chat",
            "aaaaaaaa-1111-4111-8111-aabbccddeeff",
            "--personal",
        ]);
        assert_eq!(
            i.command_path(),
            format!("projects settings focus {action}")
        );
        assert!(supported(&i));
        assert_eq!(i.positionals, ["engineering"]);
    }
    let mut client = crate::client::Client::new("http://127.0.0.1:1", None).unwrap();
    let missing = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "focus",
        "activate",
    ]);
    assert!(
        matches!(execute(&missing, &mut client.projects()).await, Err(CliError::Invalid(m)) if m == "Missing --chat <chat-id>.")
    );
    let short = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "focus",
        "activate",
        "--chat",
        "aaaaaaaa",
    ]);
    assert!(matches!(
        execute(&short, &mut client.projects()).await,
        Err(CliError::Unsupported { .. })
    ));
}
