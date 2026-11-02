// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,sdk.encryption.local-only
use super::super::settings_more::tests::{mock, parsed};
use super::*;

#[tokio::test]
async fn types_and_validation_match_the_legacy_registry_without_network() {
    let (mut client, server) = mock(vec![]).await;
    let types = execute(
        &parsed(&[
            "openmates",
            "settings",
            "memories",
            "types",
            "--app-id",
            "books",
            "--json",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    let value: Value = serde_json::from_str(&types.stdout).unwrap();
    assert!(
        value
            .as_array()
            .unwrap()
            .iter()
            .all(|t| t["app_id"] == "books")
    );
    assert_eq!(value[0]["key"], "books/favorite_books");
    let human = execute(
        &parsed(&[
            "openmates",
            "settings",
            "memories",
            "types",
            "--app-id",
            "books",
        ]),
        &mut client,
    )
    .await
    .ok()
    .unwrap();
    assert!(human.stdout.starts_with("\x1b[1mMemory types  ("));
    assert!(
        human
            .stdout
            .contains("\x1b[1mbooks\x1b[0m\n  \x1b[36mfavorite_books\x1b[0m  \x1b[2mlist\x1b[0m\n")
    );
    for (args, prefix) in [
        (
            vec![
                "openmates",
                "settings",
                "memories",
                "create",
                "--app-id",
                "books",
            ],
            "Missing required flags.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "memories",
                "create",
                "--app-id",
                "books",
                "--item-type",
                "favorite_books",
            ],
            "Missing --data '<json>'.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "memories",
                "create",
                "--app-id",
                "nope",
                "--item-type",
                "x",
                "--data",
                "{}",
            ],
            "Unknown memory type 'nope/x'.",
        ),
        (
            vec![
                "openmates",
                "settings",
                "memories",
                "create",
                "--app-id",
                "books",
                "--item-type",
                "favorite_books",
                "--data",
                "{}",
            ],
            "Missing required fields for 'books/favorite_books': title",
        ),
        (
            vec![
                "openmates",
                "settings",
                "memories",
                "update",
                "--app-id",
                "books",
                "--item-type",
                "favorite_books",
                "--data",
                "{}",
            ],
            "Missing required flags.",
        ),
        (
            vec!["openmates", "settings", "memories", "delete"],
            "Missing entry ID.",
        ),
    ] {
        match execute(&parsed(&args), &mut client).await {
            Err(CliError::Invalid(message)) => {
                assert!(message.starts_with(prefix), "{args:?}: {message}")
            }
            _ => panic!("expected invalid input for {args:?}"),
        }
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
