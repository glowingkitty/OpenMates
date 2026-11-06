// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::super::super::parity_test_support::{mock, parsed};
use super::*;
use openmates_sdk::crypto;
use serde_json::json;

const ID: &str = "11111111-1111-4111-8111-111111111111";
const CHAT_KEY: [u8; 32] = [9; 32];

fn row() -> Value {
    json!({"id":ID,"encrypted_chat_key":crypto::encrypt_bytes(&CHAT_KEY,&[7;32]).unwrap(),
           "encrypted_title":crypto::encrypt_combined("Synthetic",&CHAT_KEY).unwrap(),"messages_v":3})
}
fn window(roles: &[&str]) -> Value {
    let messages: Vec<Value> = roles
        .iter()
        .enumerate()
        .map(|(n, role)| {
            let id = format!("m{}", n + 1);
            json!({"client_message_id":id,"message_id":id,"chat_id":ID,"role":role,"created_at":n + 1,
                   "encrypted_content":crypto::encrypt_combined(&format!("text {}", n + 1),&CHAT_KEY).unwrap()})
        })
        .collect();
    json!({"messages":messages,"has_more_before":false})
}
fn body(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}
fn invalid(result: Result<CliOutput, CliError>) -> String {
    match result {
        Err(CliError::Invalid(message) | CliError::Contract { message, .. }) => message,
        Err(CliError::Unsupported { reason, .. }) => format!("unsupported: {reason}"),
        _ => panic!("expected an explicit refusal"),
    }
}

#[test]
fn supports_exactly_the_three_rewrite_commands() {
    for (args, expected) in [
        (vec!["openmates", "chats", "fork", ID, "--from-message", "m1"], true),
        (vec!["openmates", "chats", "rewind", ID, "--to-message", "m1"], true),
        (vec!["openmates", "chats", "retry", ID], true),
        (vec!["openmates", "chats", "show", ID], false),
    ] {
        assert_eq!(supported(&parsed(&args)), expected, "{args:?}");
    }
}

#[tokio::test]
async fn usage_api_key_and_selector_refusals_happen_before_any_request() {
    let (mut client, server) = mock(vec![]).await;
    let cases = [
        (vec!["openmates", "chats", "fork", ID], FORK_USAGE.to_owned()),
        (vec!["openmates", "chats", "rewind", ID], REWIND_USAGE.to_owned()),
        (
            vec!["openmates", "chats", "fork", "last", "--from-message", "m1"],
            "A canonical full chat ID is required.".to_owned(),
        ),
        (
            vec!["openmates", "chats", "retry", ID, "--api-key", "sk-placeholder"],
            "unsupported: API-key chat fork, rewind and retry run only through the explicit-key route; Cookie credentials were not used as a fallback.".to_owned(),
        ),
    ];
    for (args, expected) in cases {
        let result = execute(&parsed(&args), &mut client, CancellationToken::new()).await;
        assert_eq!(invalid(result), expected, "{args:?}");
    }
    drop(client);
    assert!(server.await.unwrap().is_empty());
}

#[tokio::test]
async fn fork_posts_a_fresh_master_wrapped_key_and_reencrypted_slice() {
    let response = json!({"success":true,"source_chat_id":ID,"chat_id":"new-chat","copied_message_count":2,"messages_v":2});
    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user", "assistant", "user"]), response.clone()]).await;
    let invocation = parsed(&["openmates", "chats", "fork", ID, "--from-message", "m2"]);
    let output = execute(&invocation, &mut client, CancellationToken::new()).await.ok().unwrap();
    assert_eq!(output.stdout, "Forked chat new-chat (2 messages copied)\n");
    let requests = server.await.unwrap();
    assert!(requests[2].starts_with(&format!("POST /v1/chats/{ID}/fork")));
    let sent = body(&requests[2]);
    assert_eq!(sent["from_message_id"], "m2");
    assert_eq!(sent["expected_source_messages_v"], 3);
    let messages = sent["encrypted_messages"].as_array().unwrap();
    assert_eq!(messages.len(), 2);
    let metadata = &sent["encrypted_chat_metadata"];
    assert_eq!(metadata["id"], sent["new_chat_id"]);
    let key = crypto::decrypt_bytes(metadata["encrypted_chat_key"].as_str().unwrap(), &[7; 32]).unwrap();
    let key: [u8; 32] = key.as_slice().try_into().unwrap();
    assert_ne!(key, CHAT_KEY);
    assert_eq!(crypto::decrypt_combined(metadata["encrypted_title"].as_str().unwrap(), &key).unwrap(), "Fork of Synthetic");
    assert_eq!(crypto::decrypt_combined(messages[1]["encrypted_content"].as_str().unwrap(), &key).unwrap(), "text 2");
    assert_eq!(messages[1]["chat_id"], sent["new_chat_id"]);
    assert!(!requests[2].contains("text 1"));

    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user"]), response.clone()]).await;
    let json_out = execute(
        &parsed(&["openmates", "chats", "fork", ID, "--from-message", "m1", "--json"]),
        &mut client,
        CancellationToken::new(),
    )
    .await
    .ok()
    .unwrap();
    assert_eq!(serde_json::from_str::<Value>(&json_out.stdout).unwrap(), response);
    server.await.unwrap();
}

#[tokio::test]
async fn unknown_boundary_uses_npm_wording_without_mutation() {
    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user"])]).await;
    let invocation = parsed(&["openmates", "chats", "rewind", ID, "--to-message", "zz"]);
    let result = execute(&invocation, &mut client, CancellationToken::new()).await;
    assert_eq!(invalid(result), "Message 'zz' was not found in the chat.");
    assert_eq!(server.await.unwrap().len(), 2);
}

#[tokio::test]
async fn rewind_and_retry_default_to_dry_run() {
    let dry = json!({"success":true,"dry_run":true,"chat_id":ID,"to_message_id":"m1",
                     "planned_deleted_message_ids":["m2","m3"],"planned_deleted_message_count":2,"messages_v":3});
    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user", "assistant", "user"]), dry.clone()]).await;
    let invocation = parsed(&["openmates", "chats", "rewind", ID, "--to-message", "m1", "--send", "again"]);
    let output = execute(&invocation, &mut client, CancellationToken::new()).await.ok().unwrap();
    assert_eq!(
        output.stdout,
        format!("Dry run chat {ID}\nWould delete 2 messages.\nm2, m3\n\nRun again with --yes to apply this rewind.\n")
    );
    let requests = server.await.unwrap();
    assert!(requests[2].starts_with(&format!("POST /v1/chats/{ID}/rewind")));
    let sent = body(&requests[2]);
    assert_eq!(sent["to_message_id"], "m1");
    assert_eq!(sent["expected_messages_v"], 3);
    assert_eq!(sent["dry_run"], true);
    assert_eq!(sent["confirm_destructive"], false);

    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user", "assistant", "user"]), dry]).await;
    execute(&parsed(&["openmates", "chats", "retry", ID]), &mut client, CancellationToken::new())
        .await
        .ok()
        .unwrap();
    let sent = body(&server.await.unwrap()[2]);
    assert_eq!(sent["to_message_id"], "m2");
    assert_eq!(sent["dry_run"], true);
}

#[tokio::test]
async fn retry_refuses_answered_chats_before_rewind() {
    let (mut client, server) = mock(vec![json!({"chats":[row()]}), window(&["user", "assistant"])]).await;
    let result = execute(&parsed(&["openmates", "chats", "retry", ID]), &mut client, CancellationToken::new()).await;
    match result {
        Err(CliError::Client(error)) => assert_eq!(error.to_string(), "No retryable user message found for this chat."),
        _ => panic!("expected retry refusal"),
    }
    assert_eq!(server.await.unwrap().len(), 2);
}

#[test]
fn applied_rewind_text_matches_print_chat_rewind_result() {
    let result = json!({"dry_run":false,"chat_id":ID,"deleted_message_ids":["m3"],"deleted_message_count":1,
                        "response":{"assistant":"fresh reply"}});
    assert_eq!(rewind_text(&result), format!("Rewound chat {ID}\nDeleted 1 message.\nm3\n\nfresh reply\n"));
    assert_eq!(rewind_text(&json!({"dry_run":false})), "Rewound chat \nDeleted 0 messages.\n");
    assert_eq!(fork_text(&json!({})), "Forked chat undefined (undefined messages copied)");
}

fn unreachable_sdk() -> openmates_sdk::sdk::OpenMates {
    openmates_sdk::sdk::OpenMates::new(openmates_sdk::SdkOptions {
        api_url: "http://127.0.0.1:9".into(),
        credentials: openmates_sdk::SdkCredentials::ApiKey(
            openmates_sdk::ApiKey::new("sk-api-synthetic.synthetic").unwrap(),
        ),
        device_id: "synthetic".into(),
        client_options: Default::default(),
    })
    .unwrap()
}

#[tokio::test]
async fn api_key_resend_steps_and_bad_selectors_are_refused_before_any_request() {
    // Port 9 is never served: any network attempt would surface as a transport
    // error instead of these explicit refusals.
    let mut sdk = unreachable_sdk();
    let resend = "needs saved-chat send, which the Rust API-key SDK does not implement yet; nothing was rewound and Cookie credentials were not used.";
    let cases = [
        (vec!["openmates", "chats", "retry", ID, "--yes", "--api-key", "sk-placeholder"], format!("unsupported: API-key retry --yes {resend}")),
        (
            vec!["openmates", "chats", "rewind", ID, "--to-message", "m1", "--send", "again", "--yes", "--api-key", "sk-placeholder"],
            format!("unsupported: API-key rewind --send {resend}"),
        ),
        (vec!["openmates", "chats", "fork", "last", "--from-message", "m1", "--api-key", "sk-placeholder"], "A canonical full chat ID is required.".to_owned()),
        (vec!["openmates", "chats", "fork", ID, "--api-key", "sk-placeholder"], FORK_USAGE.to_owned()),
    ];
    for (args, expected) in cases {
        let result = execute_key(&parsed(&args), &mut sdk).await;
        assert_eq!(invalid(result), expected, "{args:?}");
    }
}
