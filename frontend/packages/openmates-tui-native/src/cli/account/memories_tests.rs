// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,sdk.encryption.local-only
use super::super::settings_more::tests::{mock, parsed};
use super::*;

#[tokio::test]
async fn typed_commands_point_to_memories_without_network() {
    let (mut client, server) = mock(vec![]).await;
    // The catalog no longer declares the typed types and create subcommands, so
    // the parser refuses them before any handler or network access.
    for args in [
        ["openmates", "settings", "memories", "types"].as_slice(),
        [
            "openmates",
            "settings",
            "memories",
            "create",
            "--app-id",
            "books",
        ]
        .as_slice(),
    ] {
        let refusal = crate::cli::parse_from(args.iter().copied())
            .err()
            .unwrap_or_else(|| panic!("{args:?} must not parse"));
        assert!(
            refusal
                .to_string()
                .contains("Unknown subcommand for 'settings memories'"),
            "{args:?}: {refusal}"
        );
    }
    for args in [vec![
        "openmates",
        "settings",
        "memories",
        "update",
        "--id",
        "typed-1",
    ]] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(message)) => assert!(
                message.starts_with("Typed app memories were replaced by Memories"),
                "{args:?}: {message}"
            ),
            _ => panic!("expected invalid input for {args:?}"),
        }
    }
    match execute(
        &parsed(&["openmates", "settings", "memories", "delete"]),
        &mut client,
    )
    .await
    {
        Err(CliError::Invalid(message)) => assert!(message.starts_with("Missing entry ID.")),
        _ => panic!("expected invalid input"),
    }
    assert!(matches!(
        execute(
            &parsed(&[
                "openmates",
                "settings",
                "memories",
                "delete",
                "account-memory-guide"
            ]),
            &mut client
        )
        .await,
        Err(CliError::Unsupported { .. })
    ));
    drop(client);
    assert!(server.await.unwrap().is_empty());
}

#[tokio::test]
async fn list_filters_and_renders_decrypted_memories() {
    let item = openmates_sdk::crypto::encrypt_combined(
        r#"{"title":"Dune","_internal":"hidden","rating":5}"#,
        &[7; 32],
    )
    .unwrap();
    let other = openmates_sdk::crypto::encrypt_combined(r#"{"name":"Rust"}"#, &[7; 32]).unwrap();
    let (mut client, server) = mock(vec![
        json!({"memories":[
            {"id":"aaaaaaaa-1111-4111-8111-aabbccddeeff","app_id":"books","item_type":"favorite_books","item_key":"h","item_version":2,"created_at":0,"updated_at":0,"encrypted_item_json":item},
            {"id":"bbbbbbbb-1111-4111-8111-aabbccddeeff","app_id":"code","item_type":"preferred_tech","item_key":"h","item_version":1,"created_at":0,"updated_at":0,"encrypted_item_json":other}]}),
        json!({"success":true,"ws_token":"synthetic","user":{"id":"owner"}}),
    ])
    .await;
    let output = execute(
        &parsed(&[
            "openmates",
            "settings",
            "memories",
            "list",
            "--app-id",
            "books",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(
        output.stdout,
        "\x1b[1mMemories  (1)\n\x1b[0m\n\x1b[1mbooks/favorite_books\x1b[0m  \x1b[2mv2  —  id:aaaaaaaa\x1b[0m\n  \x1b[2mrating              \x1b[0m 5\n  \x1b[2mtitle               \x1b[0m Dune\n\n"
    );
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("GET /v1/sdk/memories "));
}

#[tokio::test]
async fn undo_requires_a_chat_and_accepts_listed_memory_ids() {
    let (mut client, _server) = mock(vec![]).await;
    let invocation = parsed(&["openmates", "settings", "memories", "undo"]);
    assert!(supported(&invocation));
    let error = execute(&invocation, &mut client).await.err().unwrap();
    assert!(matches!(error, CliError::Invalid(message) if message.starts_with("Missing chat ID.")));
    assert!(matches_memory("personal:abc", "account-memory-abc"));
    assert!(matches_memory("personal:abc", "personal:abc"));
    assert!(matches_memory("personal:abc", "abc"));
    assert!(!matches_memory("personal:abc", "abcd"));
}
