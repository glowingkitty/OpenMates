// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::export_archive::{encrypt_zip, zip as write_zip};
use super::super::imports_zip::ZipArchive;
use super::super::settings_more::tests::{mock, parsed};
use super::*;
use serde_json::json;

fn write(dir: &tempfile::TempDir, name: &str, bytes: &[u8]) -> String {
    let path = dir.path().join(name);
    std::fs::write(&path, bytes).unwrap();
    path.to_str().unwrap().to_owned()
}

fn claude_zip() -> Vec<u8> {
    let conversations = json!([{"uuid": "c1", "name": "Trip", "chat_messages": [
        {"uuid": "m1", "sender": "human", "content": [{"type": "text", "text": "Hi"}]},
        {"uuid": "m2", "sender": "assistant", "content": [{"type": "text", "text": "Hello"}]}
    ]}]);
    write_zip(&[
        ("__MACOSX/export/._conversations.json".into(), "junk".into()),
        (
            "export/conversations.json".into(),
            conversations.to_string(),
        ),
    ])
    .unwrap()
}

#[test]
fn every_import_path_is_supported_under_account_and_settings() {
    for root in [&["openmates"][..], &["openmates", "settings"][..]] {
        for tail in [
            &["account", "import", "claude"][..],
            &["account", "import", "chatgpt"],
            &["account", "import", "generic"],
            &["account", "import", "opencode"],
            &["account", "import", "openmates"],
            &["account", "import-chat"],
        ] {
            let args: Vec<&str> = root.iter().chain(tail).copied().collect();
            let invocation = parsed(&args);
            assert!(supported(&invocation), "{args:?}");
            assert!(
                super::super::super::handlers::requirements(&invocation).supported,
                "{args:?}"
            );
        }
    }
}

#[test]
fn archives_are_read_like_the_legacy_zip_loader() {
    let archive = claude_zip();
    let zip = ZipArchive::open(&archive).unwrap();
    assert!(
        zip.find_text("conversations.json")
            .unwrap()
            .contains("Trip")
    );
    assert_eq!(
        zip.find_text("missing.json").unwrap_err(),
        "Import archive is missing missing.json"
    );
    let parsed = parse_file(ImportParser::Claude, archive, "claude.zip", None, None).unwrap();
    assert_eq!(parsed.chats[0].messages.len(), 2);
    let error = parse_file(
        ImportParser::Claude,
        b"PK\x03\x04broken".to_vec(),
        "x",
        None,
        None,
    )
    .unwrap_err();
    assert!(
        error.starts_with("Claude export could not be parsed: "),
        "{error}"
    );
    assert_eq!(
        parse_file(
            ImportParser::Claude,
            b"[]".to_vec(),
            "x",
            Some("bard"),
            None
        )
        .unwrap_err(),
        "Unsupported account import source: bard"
    );
    assert!(
        parse_file(
            ImportParser::Generic,
            b"{}".to_vec(),
            "x",
            Some("claude"),
            None
        )
        .unwrap_err()
        .contains("--source gemini")
    );

    let manifest = "format: openmates-account-export\nversion: 1\ndomains:\n  chats:\n  usage:\n";
    let export = write_zip(&[
        ("manifest.yml".into(), manifest.into()),
        ("chats/abc.yml".into(), "chat: {}\n".into()),
    ])
    .unwrap();
    let sealed = encrypt_zip(&export, "correct horse").unwrap();
    let opened = parse_file(
        ImportParser::OpenMates,
        sealed.clone(),
        "e.zip",
        None,
        Some("correct horse"),
    )
    .unwrap();
    assert_eq!(opened.chats[0].source_chat_id, "abc");
    assert_eq!(opened.skipped_domains, ["usage"]);
    assert_eq!(
        parse_file(ImportParser::OpenMates, sealed.clone(), "e.zip", None, None).unwrap_err(),
        "OpenMates encrypted export requires a password."
    );
    assert!(
        parse_file(
            ImportParser::OpenMates,
            sealed,
            "e.zip",
            None,
            Some("wrong")
        )
        .unwrap_err()
        .contains("could not be decrypted")
    );
}

#[tokio::test]
async fn dry_run_previews_without_confirming_or_importing() {
    let dir = tempfile::tempdir().unwrap();
    let file = write(&dir, "claude.zip", &claude_zip());
    let (mut client, server) = mock(vec![json!({
        "import_id": "imp", "default_selection_count": 1, "max_batch_count": 3,
        "duplicate_fingerprints": ["x"], "can_import": false, "reason": "limit"
    })])
    .await;
    let out = execute(
        &parsed(&[
            "openmates",
            "account",
            "import",
            "claude",
            &file,
            "--dry-run",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        out.stdout,
        "Account import preview (claude): 1 chat(s) parsed\nDefault selection: 1 / max 3\nDuplicate warnings: 1\nImport blocked: limit\n"
    );
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].starts_with("POST /v1/account-imports/preview "));
    assert!(
        !requests[0].contains("Hello"),
        "the preview never uploads message content"
    );
}

#[tokio::test]
async fn blocked_and_invalid_imports_fail_before_any_write() {
    let dir = tempfile::tempdir().unwrap();
    let generic = write(
        &dir,
        "t.json",
        br#"{"messages":[{"role":"user","content":"One"}]}"#,
    );
    let (mut client, server) = mock(vec![
        json!({"can_import": false, "reason": "limit", "default_selection_count": 1}),
    ])
    .await;
    for (args, message) in [
        (
            vec![
                "openmates",
                "account",
                "import",
                "generic",
                generic.as_str(),
            ],
            "Generic account import requires --source gemini or --source other.",
        ),
        (
            vec!["openmates", "account", "import", "claude"],
            "Missing import file. Example: openmates account import claude ./export.zip --dry-run",
        ),
        (
            vec!["openmates", "settings", "account", "import-chat"],
            "Missing import file. Example: openmates settings account import-chat ./chat.yml",
        ),
        (
            vec![
                "openmates",
                "account",
                "import",
                "generic",
                generic.as_str(),
                "--source",
                "gemini",
                "--yes",
            ],
            "Account import blocked: limit",
        ),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(actual)) => assert_eq!(actual, message, "{args:?}"),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    assert!(matches!(
        execute(
            &parsed(&[
                "openmates",
                "account",
                "import-chat",
                "x.yml",
                "--api-key",
                "sk-api-placeholder"
            ]),
            &mut client
        )
        .await,
        Err(CliError::Unsupported { .. })
    ));
    assert_eq!(server.await.unwrap().len(), 1);
}

#[tokio::test]
async fn import_chat_posts_the_parsed_payload() {
    let dir = tempfile::tempdir().unwrap();
    let file = write(
        &dir,
        "chat.yml",
        b"chat:\n  title: T\nmessages:\n  -\n    role: user\n    content: Hi\n",
    );
    let (mut client, server) =
        mock(vec![json!({"imported": [], "total_credits_charged": 0})]).await;
    let out = execute(
        &parsed(&[
            "openmates",
            "settings",
            "account",
            "import-chat",
            &file,
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap()["total_credits_charged"],
        0
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/settings/import-chat "));
    assert!(requests[0].contains(r#""title":"T""#));
}
