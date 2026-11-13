//! 401 handling of the shell HTTP passthrough: a rejected session is forgotten, except on password-migration routes.
use super::*;
use crate::session::Session;
use std::collections::BTreeMap as Map;

fn client() -> Client {
    let session = Session {
        api_url: "https://api.example.org".into(),
        session_id: "fixture".into(),
        cookies: Map::new(),
        ws_token: None,
        master_key: Zeroizing::new([1; 32]),
        hashed_email: "hash".into(),
        user_email_salt: "salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    Client::new("https://api.example.org", Some(session)).unwrap()
}

fn answered_401(client: &Client, path: &str) -> SentShellHttp {
    SentShellHttp {
        binding: Binding::current(client).unwrap(),
        received: Ok(Received {
            status: 401,
            headers: HeaderMap::new(),
            body: Ok(Zeroizing::new(b"{}".to_vec())),
        }),
        keeps_session_on_401: keeps_session_on_401(path),
    }
}

#[test]
fn a_401_on_a_password_migration_route_is_returned_and_keeps_the_session() {
    let mut client = client();
    let sent = answered_401(&client, "/v1/auth/password-v2/migrate");
    let response = client.finish_shell_http(sent).unwrap();
    assert_eq!(response.status, 401);
    assert!(client.session().is_some());
}

#[test]
fn a_401_on_any_other_route_forgets_the_session() {
    let mut client = client();
    let sent = answered_401(&client, "/v1/settings/user/darkmode");
    assert!(matches!(
        client.finish_shell_http(sent),
        Err(Error::Expired)
    ));
    assert!(client.session().is_none());
}
