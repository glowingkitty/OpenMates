// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::tasks::tests::{client, mock};

const TEAM: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

#[test]
fn invite_keys_match_the_npm_hkdf_context() {
    let secret = "CQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQk";
    let hex = |key: Key| key.iter().map(|b| format!("{b:02x}")).collect::<String>();
    assert_eq!(
        hex(invite_key(
            " Bob@Example.org ",
            secret,
            "invite-1",
            "team-1",
            "https://app.example.org/"
        )
        .unwrap()),
        "9ce38b7fb4bc37417ad578e3243c6050c5b2901cc35103d8016ff7dbf0179906"
    );
    assert_eq!(
        hex(invite_key("", secret, "invite-1", "team-1", "https://app.example.org").unwrap()),
        "3ba5049c8f466b5ce0404b7b1791ae1ab1b58ac004847a3e2a44a0fc547ef714"
    );
    assert!(invite_key("", "short", "i", "t", "o").is_err());
}

#[tokio::test]
async fn create_encrypts_name_and_wraps_a_fresh_team_key_with_the_master_key() {
    let (api, server) = mock(vec![
        json!({"approval_token":"approved"}),
        json!({"team":{"team_id":"server-team","slug":"eng"}}),
    ])
    .await;
    let mut c = client(&api);
    let team = c
        .teams()
        .create(TeamCreate {
            name: "Private Team",
            description: Some("Secret plans"),
            slug: Some("eng"),
        })
        .await
        .unwrap();
    assert_eq!(team["slug"], "eng");
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/teams/name-approval "));
    assert!(requests[0].ends_with(r#"{"name":"private team"}"#));
    assert!(requests[1].starts_with("POST /v1/teams "));
    assert!(!requests[1].contains("Private Team") && !requests[1].contains("Secret plans"));
    let body: Value = serde_json::from_str(requests[1].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let key = key_bytes(
        &crypto::decrypt_bytes(body["encrypted_team_key"].as_str().unwrap(), &[7; 32]).unwrap(),
    )
    .unwrap();
    assert_eq!(
        crypto::decrypt_combined(body["encrypted_name"].as_str().unwrap(), &key).unwrap(),
        "Private Team"
    );
    assert_eq!(
        crypto::decrypt_combined(body["encrypted_description"].as_str().unwrap(), &key).unwrap(),
        "Secret plans"
    );
    assert_eq!(
        crypto::decrypt_combined(body["encrypted_zero_balance"].as_str().unwrap(), &key).unwrap(),
        "0"
    );
    assert_eq!(body["name_approval_token"], "approved");
    assert_eq!(body["slug"], "eng");
}

#[tokio::test]
async fn invites_round_trip_the_team_key_and_members_decrypt_profiles() {
    let team_key = [5u8; 32];
    let row =
        json!({"team_id":TEAM,"encrypted_team_key":legacy_encrypt(&team_key, &[7; 32]).unwrap()});
    let (api, server) = mock(vec![
        json!({"team":row}),
        json!({"team":row}),
        json!({"invite":{"invite_id":"server-copy"}}),
    ])
    .await;
    let mut c = client(&api);
    let invite = c
        .teams()
        .invite(
            TEAM,
            TeamInvite {
                email: Some("Bob@Example.org"),
                role: "member",
                ..Default::default()
            },
        )
        .await
        .unwrap();
    let requests = server.await.unwrap();
    let body: Value = serde_json::from_str(requests[2].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    let secret = invite["invite_secret"].as_str().unwrap();
    assert!(
        !requests[2].contains(secret),
        "the fragment secret never reaches the server"
    );
    assert!(
        invite["invite_url"]
            .as_str()
            .unwrap()
            .ends_with(&format!("#key={secret}"))
    );
    let context = &body["invite_key_kdf_context"];
    let key = invite_key(
        "bob@example.org",
        secret,
        body["invite_id"].as_str().unwrap(),
        TEAM,
        context["origin"].as_str().unwrap(),
    )
    .unwrap();
    assert_eq!(
        crypto::decrypt_bytes(body["encrypted_invite_team_key"].as_str().unwrap(), &key)
            .unwrap()
            .as_slice(),
        team_key
    );

    // Accept re-wraps the invite's Team key with the accepting account's master key.
    let (api, server) = mock(vec![
        json!({"invite":{"kind":"email","hashed_recipient_email":"h","encrypted_invite_team_key":body["encrypted_invite_team_key"],"invite_key_kdf_context":context}}),
        json!({"membership":{"role":"member"},"status":"active"}),
    ])
    .await;
    let mut c = client(&api);
    let accepted = c
        .teams()
        .accept_invite(
            body["invite_id"].as_str().unwrap(),
            Some(secret),
            Some("bob@example.org"),
        )
        .await
        .unwrap();
    assert_eq!(accepted["membership"]["role"], "member");
    let requests = server.await.unwrap();
    let accept: Value =
        serde_json::from_str(requests[1].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(
        crypto::decrypt_bytes(accept["encrypted_team_key"].as_str().unwrap(), &[7; 32])
            .unwrap()
            .as_slice(),
        team_key
    );

    let profile = legacy_encrypt(br#"{"display_name":"Bob","avatar":null}"#, &team_key).unwrap();
    let (api, _server) = mock(vec![
        json!({"members":[{"user_id":"u1","role":"admin","encrypted_member_profile":profile},{"user_id":"u2","role":"viewer"}]}),
        json!({"team":row}),
    ])
    .await;
    let mut c = client(&api);
    let members = c.teams().members(TEAM).await.unwrap();
    assert_eq!(members[0]["profile"]["display_name"], "Bob");
    assert!(members[1]["profile"].is_null());
    assert!(matches!(
        c.teams().set_role(TEAM, "u1", "owner").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        c.teams().get("../x").await,
        Err(Error::Invalid(_))
    ));
}
