// contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
use super::*;
use serde_json::json;
fn invocation(path: &str) -> Invocation {
    Invocation {
        path: path.split(' ').map(str::to_owned).collect(),
        positionals: vec!["embed-synthetic".into()],
        flags: Default::default(),
    }
}
#[test]
fn decimal_prefix_versions_and_strict_timeout_match_baseline() {
    for (raw, want) in [("2suffix", 2), (" +2", 2), ("2.9", 2), ("002", 2)] {
        let mut i = invocation("embeds versions restore");
        i.flags.insert("version".into(), json!(raw));
        assert_eq!(
            version(&i).unwrap_or_else(|_| panic!("synthetic version")),
            want
        );
    }
    for raw in ["0", "-1", "", "NaN", "Infinity"] {
        let mut i = invocation("embeds versions restore");
        i.flags.insert("version".into(), json!(raw));
        assert!(version(&i).is_err());
    }
    for raw in ["01", "+2", " 2", "2.0", "0", "-2"] {
        let mut i = invocation("embeds preview start");
        i.flags.insert("wait".into(), json!(true));
        i.flags.insert("timeout-seconds".into(), json!(raw));
        assert!(options(&i).is_err());
        i.flags.remove("wait");
        assert!(
            options(&i).is_ok(),
            "Baseline ignores timeout without --wait"
        );
    }
}
#[test]
fn preview_json_and_human_output_preserve_fields_and_no_browser_launch() {
    let mut i = invocation("embeds preview open");
    let value = json!({"session_id":"session-synthetic","status":"running","preview_url":"https://preview.invalid","charged_credits":3,"error":"synthetic"});
    assert_eq!(
        preview_output(&i, value.clone())
            .unwrap_or_else(|_| panic!("synthetic preview"))
            .stdout,
        "Session: session-synthetic\nStatus: running\nPreview URL: https://preview.invalid\nCharged credits: 3\nError: synthetic\n"
    );
    i.flags.insert("json".into(), json!(true));
    assert_eq!(
        serde_json::from_str::<Value>(
            &preview_output(&i, value.clone())
                .unwrap_or_else(|_| panic!("synthetic preview"))
                .stdout
        )
        .unwrap(),
        value
    );
}
#[test]
fn versions_keep_order_readonly_current_marker_and_utc_milliseconds() {
    let i = invocation("embeds versions list");
    let value = json!({"embed_id":"embed-synthetic","current_version":2,"readonly":true,"versions":[{"version_number":2,"created_at":0.125},{"version_number":1,"created_at":0}]});
    let out = versions_output(&i, value).unwrap_or_else(|_| panic!("synthetic versions"));
    assert!(
        out.stdout
            .contains("v2 (current)  1970-01-01T00:00:00.125Z\n  v1  1970-01-01T00:00:00.000Z")
    );
    assert!(out.stdout.contains("Read-only shared history"));
    assert_eq!(out.exit_code, 0);
}
#[test]
fn actual_parser_admits_six_bounded_routes_and_no_project_grant() {
    for argv in [
        vec!["openmates", "embeds", "versions", "list", "id", "--json"],
        vec![
            "openmates",
            "embeds",
            "versions",
            "restore",
            "id",
            "--version",
            "2suffix",
            "--yes",
        ],
        vec![
            "openmates",
            "embeds",
            "preview",
            "start",
            "id",
            "--chat-id",
            "chat",
            "--wait",
            "--timeout-seconds",
            "2",
        ],
        vec!["openmates", "embeds", "preview", "status", "session"],
        vec!["openmates", "embeds", "preview", "open", "session"],
        vec!["openmates", "embeds", "preview", "stop", "session"],
    ] {
        let parsed = super::super::parse_from(argv).unwrap();
        let i = parsed.invocation.unwrap();
        assert!(supported(&i));
        assert!(super::super::requirements(&i).supported);
    }
    for path in [
        "embeds show",
        "embeds share",
        "embeds add-to-project",
        "embeds remove-from-project",
    ] {
        assert!(!supported(&invocation(path)));
    }
}
#[tokio::test]
async fn missing_confirmation_never_starts_sdk_io() {
    let mut sdk = OpenMates::new(openmates_sdk::SdkOptions {
        api_url: "http://127.0.0.1:9".into(),
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap();
    let mut i = invocation("embeds versions restore");
    i.flags.insert("version".into(), json!("2"));
    assert!(matches!(
        execute_sdk_embeds(&i, &mut sdk, CancellationToken::new()).await,
        Err(CliError::Contract {
            code: "command_failed",
            ..
        })
    ));
}

#[test]
fn version_show_formatting_matches_actual_maintained_handler_oracle() {
    let f: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/sdk-embed-version-content.json"
    ))
    .unwrap();
    for case in f["capabilities"]["sdk.embeds.version-content"]["cli_cases"]
        .as_array()
        .unwrap()
    {
        if case["flags"].get("output").is_some() {
            continue;
        }
        let mut i = invocation("embeds versions show");
        i.flags = serde_json::from_value(case["flags"].clone()).unwrap();
        let out = version_content_output(
            &i,
            case["result"].clone(),
            &CancellationToken::new(),
            &|| Ok(()),
        )
        .unwrap_or_else(|_| panic!("synthetic version output"));
        if i.boolean("json") {
            assert_eq!(
                serde_json::from_str::<Value>(&out.stdout).unwrap(),
                case["result"]
            );
        } else {
            assert_eq!(out.stdout, case["stdout"].as_str().unwrap());
        }
        assert_eq!(out.stderr, case["stderr"].as_str().unwrap());
    }
    assert!(supported(&invocation("embeds versions show")));
    assert!(!supported(&invocation("embeds show")));
}
#[test]
fn version_show_keeps_only_trusted_styling_and_preserves_json_payloads() {
    for (payload, escaped) in [
        ("\x1b[31mred\x1b[0m", "\\u001b[31mred\\u001b[0m"),
        ("\x1b]52;c;c2VjcmV0\x07", "\\u001b]52;c;c2VjcmV0\\u0007"),
        (
            "\u{202e}hidden\u{2066}text\u{2069}",
            "\\u202ehidden\\u2066text\\u2069",
        ),
    ] {
        for field in ["embed_id", "version_number", "content"] {
            let mut value = json!({"embed_id":"embed-synthetic","version_number":2,"content":"safe\ntext\tvalue"});
            value[field] = json!(payload);
            let i = invocation("embeds versions show");
            let out =
                version_content_output(&i, value.clone(), &CancellationToken::new(), &|| Ok(()))
                    .unwrap_or_else(|_| panic!("synthetic version output"));
            let (id, number, content) = match field {
                "embed_id" => (
                    escaped.to_owned(),
                    "2".to_owned(),
                    "safe\ntext\tvalue".to_owned(),
                ),
                // JSON's version display is already quoted/escaped before terminal sanitization.
                "version_number" => (
                    "embed-synthetic".to_owned(),
                    format!("\"{escaped}\""),
                    "safe\ntext\tvalue".to_owned(),
                ),
                _ => (
                    "embed-synthetic".to_owned(),
                    "2".to_owned(),
                    escaped.to_owned(),
                ),
            };
            assert_eq!(
                out.stdout,
                format!("\n\x1b[1m{id} v{number}\x1b[0m\n{content}\n"),
                "{field}"
            );
            assert_eq!(out.stdout.matches('\x1b').count(), 2, "{field}");
            assert!(
                !out.stdout
                    .contains(['\x07', '\u{202e}', '\u{2066}', '\u{2069}'])
            );
            assert!(out.stderr.is_empty());
            assert_eq!(out.exit_code, 0);

            let mut json_i = invocation("embeds versions show");
            json_i.flags.insert("json".into(), json!(true));
            let json_out =
                version_content_output(&json_i, value.clone(), &CancellationToken::new(), &|| {
                    Ok(())
                })
                .unwrap_or_else(|_| panic!("synthetic version output"));
            assert_eq!(
                serde_json::from_str::<Value>(&json_out.stdout).unwrap(),
                value
            );
        }
    }
}
#[cfg(unix)]
#[test]
fn output_is_private_atomic_durable_and_refuses_symlink_or_late_denial() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let root = tempfile::tempdir().unwrap();
    let dest = root.path().join("version.txt");
    std::fs::write(&dest, "old").unwrap();
    write_version_output(&dest, b"synthetic new", &CancellationToken::new(), &|| {
        Ok(())
    })
    .unwrap_or_else(|_| panic!("synthetic write"));
    assert_eq!(std::fs::read(&dest).unwrap(), b"synthetic new");
    assert_eq!(
        std::fs::metadata(&dest).unwrap().permissions().mode() & 0o777,
        0o600
    );
    let cancel = CancellationToken::new();
    cancel.cancel();
    assert!(write_version_output(&dest, b"withheld", &cancel, &|| Ok(())).is_err());
    assert!(
        write_version_output(&dest, b"withheld", &CancellationToken::new(), &|| Err(
            Error::Forbidden
        ))
        .is_err()
    );
    assert_eq!(std::fs::read(&dest).unwrap(), b"synthetic new");
    let link = root.path().join("link");
    symlink(&dest, &link).unwrap();
    assert!(write_version_output(&link, b"never", &CancellationToken::new(), &|| Ok(())).is_err());
    let dirlink = root.path().join("dirlink");
    symlink(root.path(), &dirlink).unwrap();
    assert!(
        write_version_output(
            &dirlink.join("file"),
            b"never",
            &CancellationToken::new(),
            &|| Ok(())
        )
        .is_err()
    );
    assert_eq!(std::fs::read(&dest).unwrap(), b"synthetic new");
    assert!(!std::fs::read_dir(root.path()).unwrap().any(|entry| {
        entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".openmates-version-")
    }));
}

#[tokio::test]
async fn cookie_version_flags_and_short_selector_refuse_before_account_io() {
    let mut client = openmates_sdk::Client::new("http://127.0.0.1:9", None).unwrap();
    let mut bad = invocation("embeds versions show");
    bad.positionals = vec!["short".into()];
    bad.flags.insert("version".into(), json!("1"));
    assert!(
        execute_cookie_version(&bad, &mut client, CancellationToken::new())
            .await
            .is_err()
    );
    bad.flags.insert(
        "unexpected-secret-field".into(),
        json!("synthetic-private-value"),
    );
    let error = execute_cookie_version(&bad, &mut client, CancellationToken::new())
        .await
        .err()
        .unwrap_or_else(|| panic!("unknown flag admitted"));
    assert!(!error.to_string().contains("synthetic-private-value"));
}
