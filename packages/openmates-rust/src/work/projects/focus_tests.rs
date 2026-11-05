// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::tasks::tests::{client, mock};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
const CHAT: &str = "aaaaaaaa-1111-4111-8111-aabbccddeeff";

fn raw() -> Value {
    encode_create(
        &ProjectCreate {
            project_id: Some(PROJECT.into()),
            name: "Private Project".into(),
            write_mode: Some(ProjectWriteMode::AlwaysAsk),
            ..Default::default()
        },
        &[8; 32],
        &[7; 32],
        None,
    )
    .unwrap()
}

#[tokio::test]
async fn activation_sends_the_decrypted_default_focus_for_the_chat() {
    let raw = raw();
    let focus_id = raw["default_focus_id"].as_str().unwrap().to_owned();
    let settings = json!({"settings":{"write_mode":"always_ask","encrypted_settings":raw["encrypted_settings"],"default_focus_id_hash":hash(&focus_id)}});
    let (api, server) = mock(vec![
        json!({"project":raw}),
        json!({"project":raw}),
        settings,
        json!({"focus":{"project_id":PROJECT,"chat_id":CHAT}}),
    ])
    .await;
    let mut c = client(&api);
    let focus = c.projects().activate_focus(PROJECT, CHAT).await.unwrap();
    assert_eq!(focus["chat_id"], CHAT);
    let requests = server.await.unwrap();
    assert!(requests[3].starts_with(&format!("POST /v1/projects/{PROJECT}/focus/activate ")));
    let body: Value = serde_json::from_str(requests[3].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body["focus_id"], focus_id);
    assert_eq!(body["chat_id"], CHAT);
    assert!(
        body["instruction"]
            .as_str()
            .unwrap()
            .starts_with("Help with work in Private Project.")
    );
}

#[tokio::test]
async fn current_and_deactivate_use_the_chat_routes_and_reject_short_ids() {
    let (api, server) = mock(vec![json!({"focus":null}), json!({"success":true})]).await;
    let mut c = client(&api);
    assert!(c.projects().active_focus(CHAT).await.unwrap().is_null());
    c.projects().deactivate_focus(CHAT).await.unwrap();
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with(&format!("GET /v1/projects/focus/current?chat_id={CHAT} ")));
    assert!(requests[1].starts_with("POST /v1/projects/focus/deactivate "));
    assert!(matches!(
        c.projects().deactivate_focus("abc").await,
        Err(Error::Invalid(_))
    ));
}
