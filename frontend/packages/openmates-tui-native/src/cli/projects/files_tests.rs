// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
use super::*;
fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
#[tokio::test]
async fn file_commands_parse_and_keep_npm_contract_errors_before_any_request() {
    for (args, path, positionals) in [
        (
            vec![
                "openmates",
                "projects",
                "files",
                "list",
                "eng",
                "--path",
                "src",
                "--depth",
                "2",
                "--personal",
            ],
            "projects files list",
            vec!["eng"],
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "search",
                "eng",
                "main",
                "--personal",
            ],
            "projects files search",
            vec!["eng", "main"],
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "read",
                "eng",
                "src/main.rs",
                "--personal",
            ],
            "projects files read",
            vec!["eng", "src/main.rs"],
        ),
    ] {
        let i = invocation(&args);
        assert_eq!(i.command_path(), path);
        assert_eq!(i.positionals, positionals);
        assert!(supported(&i));
    }
    let mut client = crate::client::Client::new("http://127.0.0.1:1", None).unwrap();
    for (args, code, message) in [
        (
            vec!["openmates", "projects", "files", "list", "eng"],
            "context_confirmation_required",
            "Live file requests require --personal or --team <team>.",
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "list",
                "eng",
                "--personal",
                "--include-ignored",
            ],
            "include_ignored_read_only",
            "--include-ignored is allowed only for one exact file read.",
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "read",
                "eng",
                "x",
                "--personal",
                "--include-content",
            ],
            "include_content_search_only",
            "--include-content is allowed only for filename search.",
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "list",
                "eng",
                "--personal",
                "--depth",
                "9",
            ],
            "invalid_limit",
            "--depth must be between 1 and 8.",
        ),
        (
            vec![
                "openmates",
                "projects",
                "files",
                "read",
                "eng",
                "../secret",
                "--personal",
            ],
            "invalid_path",
            "Project file paths cannot traverse outside the source.",
        ),
    ] {
        match execute(&invocation(&args), &mut client.projects()).await {
            Err(CliError::Contract {
                code: actual,
                message: text,
            }) => assert_eq!((actual, text.as_str()), (code, message), "{args:?}"),
            _ => panic!("expected a contract error for {args:?}"),
        }
    }
}
