// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;
use super::tests::{mock, parsed};

#[tokio::test]
async fn account_delete_refuses_code_flags_before_any_request() {
    let (mut client, server) = mock(vec![]).await;
    for args in [
        vec!["openmates", "settings", "account", "delete", "--yes", "--email-code", "123456"],
        vec!["openmates", "account", "delete", "--totp-code", "123456"],
    ] {
        let invocation = parsed(&args);
        assert!(supported(&invocation), "{args:?}");
        match execute(&invocation, &mut client).await {
            Err(CliError::Invalid(message)) => assert_eq!(
                message,
                "Deletion verification codes must be entered through interactive prompts, not command-line flags."
            ),
            _ => panic!("code flags must be refused for {args:?}"),
        }
    }
    drop(client);
    assert!(server.await.unwrap().is_empty());
}
