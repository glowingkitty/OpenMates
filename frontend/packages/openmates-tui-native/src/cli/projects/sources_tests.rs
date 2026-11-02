// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,sdk.encryption.local-only
use super::*;
fn invocation(args: &[&str]) -> Invocation {
    super::super::super::parse_from(args.iter().copied())
        .unwrap_or_else(|error| panic!("{error}"))
        .invocation
        .unwrap()
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
#[test]
fn list_uses_existing_parser_and_scope_flags_without_enabling_source_mutation() {
    for scope in [
        vec!["--personal"],
        vec!["--team", "ccbbccdd-1111-4111-8111-aabbccddeeff"],
    ] {
        let mut args = vec![
            "openmates",
            "projects",
            "sources",
            "list",
            "engineering",
            "--json",
        ];
        args.extend(scope);
        let i = invocation(&args);
        assert!(supported(&i));
        assert_eq!(selector(&i).ok().unwrap(), "engineering");
        assert_eq!(i.command_path(), "projects sources list");
        assert_eq!(i.positionals, ["engineering"]);
    }
    let remove = invocation(&[
        "openmates",
        "projects",
        "sources",
        "remove",
        "engineering",
        "--source",
        "source-one",
    ]);
    assert!(supported(&remove));
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
#[test]
fn missing_selector_preserves_original_command_error_and_extra_arguments_are_not_reinterpreted() {
    for args in [
        vec!["openmates", "projects", "sources", "list"],
        vec!["openmates", "projects", "sources", "list", "   "],
    ] {
        let i = invocation(&args);
        let error = selector(&i).unwrap_err();
        assert_eq!(error.code(), "command_failed");
        assert_eq!(error.exit_code(), 1);
        assert_eq!(error.to_string(), "Missing project.");
    }
    let extra = invocation(&[
        "openmates",
        "projects",
        "sources",
        "list",
        " engineering ",
        "unused-legacy-extra",
    ]);
    assert_eq!(selector(&extra).ok().unwrap(), "engineering");
    let mut bad = invocation(&["openmates", "projects", "sources", "list", "engineering"]);
    bad.flags
        .insert("source".into(), json!("must-not-be-silently-used"));
    assert!(selector(&bad).is_err());
    bad.flags.remove("source");
    bad.flags.insert("team".into(), json!(["one", "two"]));
    assert!(selector(&bad).is_err());
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
#[test]
fn sources_list_selector_delegation_keeps_other_arity_and_unknown_option_refusals() {
    for args in [
        vec!["openmates", "projects", "show"],
        vec!["openmates", "projects", "show", "engineering", "extra"],
        vec!["openmates", "projects", "sources", "list", "engineering", "--unknown-native-fixture-flag"],
    ] {
        assert!(super::super::super::parse_from(args).is_err());
    }
}

// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn exact_six_field_json_and_ordinary_text_follow_maintained_typescript_vectors() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/project-source-list.json"
    ))
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let value = presentation(
            case["project_id"].as_str().unwrap(),
            case["decoded_sources"].as_array().unwrap(),
        )
        .ok()
        .unwrap();
        assert_eq!(value, case["expected"], "{}", case["id"]);
        for row in value["sources"].as_array().unwrap() {
            let keys = row
                .as_object()
                .unwrap()
                .keys()
                .map(String::as_str)
                .collect::<std::collections::BTreeSet<_>>();
            assert_eq!(
                keys,
                std::collections::BTreeSet::from([
                    "source_id",
                    "source_type",
                    "display_name",
                    "capabilities",
                    "status",
                    "ownership_label"
                ])
            );
        }
        let mut i = invocation(&[
            "openmates",
            "projects",
            "sources",
            "list",
            "engineering",
            "--json",
        ]);
        let json = output(&i, value.clone(), list_text(&value)).ok().unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&json.stdout).unwrap(),
            case["expected"]
        );
        assert_eq!(json.exit_code, 0);
        assert!(json.stderr.is_empty());
        assert!(json.stdout.ends_with('\n'));
        for forbidden in [
            "encrypted_metadata",
            "encrypted_display_name",
            "binding_root",
            "host_device_id",
            "unknown_future",
        ] {
            assert!(!json.stdout.contains(forbidden));
        }
        i.flags.remove("json");
        let plain = output(&i, value.clone(), list_text(&value)).ok().unwrap();
        assert_eq!(
            plain.stdout,
            case["text"].as_str().unwrap(),
            "{}",
            case["id"]
        );
        assert_eq!(plain.exit_code, 0);
        assert!(plain.stderr.is_empty());
    }
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,sdk.encryption.local-only
#[test]
fn malformed_shared_rows_fail_without_raw_output_and_existing_terminal_safety_remains() {
    for row in [
        json!({"source_type":"remote_folder"}),
        json!({"source_id":"source","source_type":null}),
    ] {
        assert!(presentation("project", &[row]).is_err());
    }
    let value=presentation("project",&[json!({"source_id":"source","source_type":"remote_folder","display_name":"Folder\u{1b}[31mname","status":"connected"})]).ok().unwrap();
    let i = invocation(&["openmates", "projects", "sources", "list", "project"]);
    assert_eq!(
        output(&i, value.clone(), list_text(&value))
            .ok()
            .unwrap()
            .stdout,
        "source  Folder\\u001b[31mname  connected\n"
    );
}

// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity
#[tokio::test]
async fn source_removal_requires_the_exact_source_id_before_any_request() {
    let mut client = crate::client::Client::new("http://127.0.0.1:1", None).unwrap();
    for (args, code, message) in [
        (vec!["openmates", "projects", "sources", "remove", "engineering", "--source", "src-1", "--json"],
            "confirmation_required", "Project source removal requires --confirm <source-id>."),
        (vec!["openmates", "projects", "sources", "remove", "engineering", "--source", "src-1", "--confirm", "src-2"],
            "confirmation_mismatch", "Project source removal confirmation must exactly match 'src-1'."),
        (vec!["openmates", "projects", "sources", "remove", "engineering", "--confirm", "src-1"],
            "command_failed", "Missing --source <source-id>."),
    ] {
        let i = invocation(&args);
        let mut service = client.projects();
        match remove(&i, &mut service, &CancellationToken::new()).await {
            Err(CliError::Contract { code: actual, message: text }) => {
                assert_eq!((actual, text.as_str()), (code, message), "{args:?}");
            }
            _ => panic!("expected a contract error for {args:?}"),
        }
    }
}
