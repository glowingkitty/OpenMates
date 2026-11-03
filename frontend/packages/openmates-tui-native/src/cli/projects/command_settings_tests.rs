// contract-test: supporting surface=cli assertions=cli.runtime.native-rust
use super::*;
fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
const CHAT: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

#[test]
fn every_command_setting_path_parses_and_is_supported() {
    let stop = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "command",
        "stop",
        "exec-1",
        "--chat",
        CHAT,
    ]);
    assert_eq!(stop.command_path(), "projects settings command stop");
    assert_eq!(stop.positionals, ["engineering", "exec-1"]);
    assert_eq!(stop.text("chat"), Some(CHAT));
    assert!(supported(&stop));
    for action in ["list", "enable", "disable"] {
        let i = invocation(&[
            "openmates",
            "projects",
            "settings",
            "engineering",
            "command-presets",
            action,
            "tests",
            "--source",
            "src-1",
        ]);
        assert_eq!(
            i.command_path(),
            format!("projects settings command-presets {action}")
        );
        assert_eq!(i.positionals, ["engineering", "tests"]);
        // Enable stays unsupported until host command protection is ported.
        assert_eq!(supported(&i), action != "enable");
    }
    let list = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "command-resources",
        "list",
        "--path",
        "/work/repo",
    ]);
    assert_eq!(
        list.command_path(),
        "projects settings command-resources list"
    );
    assert!(supported(&list));
    for action in ["enable", "disable"] {
        for kind in ["writable", "network", "credential"] {
            let i = invocation(&[
                "openmates",
                "projects",
                "settings",
                "engineering",
                "command-resources",
                action,
                kind,
                "target-cache",
            ]);
            assert_eq!(
                i.command_path(),
                format!("projects settings command-resources {action} {kind}")
            );
            assert_eq!(i.positionals, ["engineering", "target-cache"]);
            assert!(supported(&i));
        }
    }
}

#[test]
fn environment_mappings_follow_npm_parsing() {
    assert_eq!(
        parse_environment_mappings(" CARGO_TOKEN = MY_TOKEN ,_EXTRA=LOCAL")
            .ok()
            .unwrap(),
        [
            ("CARGO_TOKEN".to_owned(), "MY_TOKEN".to_owned()),
            ("_EXTRA".to_owned(), "LOCAL".to_owned())
        ]
    );
    for invalid in [
        "A",
        "A=",
        "=B",
        "A=B=C",
        "A=B,A=C",
        "A=B,",
        "constructor=X",
        "__proto__=X",
        "toString=X",
    ] {
        assert!(
            matches!(
                parse_environment_mappings(invalid),
                Err(CliError::Contract { code: "invalid_environment_mapping", message })
                    if message == "--environment must be a comma-separated TARGET=LOCAL_ENV mapping."
            ),
            "{invalid}"
        );
    }
}

#[test]
fn npm_state_directory_resolution() {
    let home = Path::new("/home/user");
    assert_eq!(
        resolve_npm_state_dir(None, None, Some(home)).ok().unwrap(),
        Path::new("/home/user/.openmates")
    );
    assert_eq!(
        resolve_npm_state_dir(Some("  "), Some(" work-2 "), Some(home))
            .ok()
            .unwrap(),
        Path::new("/home/user/.openmates/profiles/work-2")
    );
    assert_eq!(
        resolve_npm_state_dir(Some(" /state "), Some("work"), None)
            .ok()
            .unwrap(),
        Path::new("/state")
    );
    assert!(matches!(
        resolve_npm_state_dir(Some("relative"), None, Some(home)),
        Err(CliError::Invalid(message)) if message == "OPENMATES_STATE_DIR must be an absolute path."
    ));
    for profile in ["Work", "-work", "a_b", &"a".repeat(65)] {
        assert!(
            matches!(
                resolve_npm_state_dir(None, Some(profile), Some(home)),
                Err(CliError::Invalid(message)) if message == PROFILE_PATTERN_MESSAGE
            ),
            "{profile}"
        );
    }
}

#[tokio::test]
async fn native_state_dir_and_unported_options_fail_before_any_request() {
    let mut client = crate::client::Client::new("http://127.0.0.1:1", None).unwrap();
    let state_dir = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "command-presets",
        "list",
        "--state-dir",
        "/tmp/native-state",
    ]);
    assert!(matches!(
        execute(&state_dir, &mut client.projects()).await,
        Err(CliError::Unsupported { reason, .. }) if reason.starts_with("--state-dir selects native CLI state")
    ));
    let mut extra = invocation(&[
        "openmates",
        "projects",
        "settings",
        "engineering",
        "command",
        "stop",
        "exec-1",
        "--chat",
        CHAT,
    ]);
    extra.flags.insert("source".into(), json!("src-1"));
    assert!(matches!(
        execute(&extra, &mut client.projects()).await,
        Err(CliError::Unsupported { reason, .. }) if reason == "Option --source is not ported for this native Project operation."
    ));
}

#[test]
fn empty_text_lists_print_nothing() {
    let i = Invocation {
        path: ["projects", "settings", "command-presets", "list"]
            .map(String::from)
            .to_vec(),
        positionals: vec!["engineering".into()],
        flags: Default::default(),
    };
    let empty = lines_output(&i, json!({"presets":[]}), vec![])
        .ok()
        .unwrap();
    assert_eq!((empty.stdout.as_str(), empty.exit_code), ("", 0));
    let lines = lines_output(
        &i,
        json!({}),
        vec![
            "enabled  tests  Run tests".into(),
            "disabled  lint  Lint".into(),
        ],
    )
    .ok()
    .unwrap();
    assert_eq!(
        lines.stdout,
        "enabled  tests  Run tests\ndisabled  lint  Lint\n"
    );
}
