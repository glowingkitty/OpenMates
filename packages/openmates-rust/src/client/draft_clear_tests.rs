// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use crate::client::workspaces::delete_tests::{client, peer_control};

const ID: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";

fn receipt(payload: Value) -> Vec<Value> {
    vec![json!({"type":"draft_delete_receipt","payload":payload})]
}

#[tokio::test]
async fn clearing_saved_draft_preserves_chat_key_metadata_history_and_active_chat() {
    let (api, server) = peer_control(
        false,
        "delete_draft",
        receipt(json!({"chat_id":ID,"success":true,"draft_v":3})),
        None,
    )
    .await;
    let mut client = client(&api, false, false);
    client.chats.get_mut(ID).unwrap()["encrypted_draft_md"] = json!("original-draft-ciphertext");
    client.chats.get_mut(ID).unwrap()["encrypted_draft_preview"] =
        json!("original-preview-ciphertext");
    client.chats.get_mut(ID).unwrap()["draft_v"] = json!(2);
    client.chats.get_mut(ID).unwrap()["encrypted_title"] = json!("opaque-title");
    client
        .wrappers
        .push(json!({"hashed_chat_id":sha256(ID),"encrypted_chat_key":"opaque-wrapper"}));
    let mut expected = client.chats[ID].clone();
    expected
        .as_object_mut()
        .unwrap()
        .remove("encrypted_draft_md");
    expected
        .as_object_mut()
        .unwrap()
        .remove("encrypted_draft_preview");
    expected["draft_v"] = json!(3);
    let history = client.history.clone();
    let wrappers = client.wrappers.clone();
    client.clear_draft(ID).await.unwrap();
    assert_eq!(client.chats[ID], expected);
    assert_eq!(client.history, history);
    assert_eq!(client.wrappers, wrappers);
    assert_eq!(client.active_chat.as_deref(), Some(ID));
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    server.await.unwrap();
}

#[tokio::test]
async fn explicit_uncached_draft_clear_accepts_positive_tombstone_without_removing_unknown_state() {
    let (api, server) = peer_control(
        false,
        "delete_draft",
        receipt(json!({"chat_id":ID,"success":true,"draft_v":1})),
        None,
    )
    .await;
    let mut client = client(&api, false, false);
    client.chats.remove(ID);
    let history = client.history.clone();
    let active = client.active_chat.clone();
    client.clear_draft(ID).await.unwrap();
    assert!(!client.chats.contains_key(ID));
    assert_eq!(client.history, history);
    assert_eq!(client.active_chat, active);
    server.await.unwrap();
}

#[tokio::test]
async fn malformed_stale_foreign_or_failed_clear_receipt_preserves_all_ciphertext() {
    for payload in [
        json!({"chat_id":ID,"success":false}),
        json!({"chat_id":ID,"draft_v":3}),
        json!({"chat_id":ID,"success":true}),
        json!({"chat_id":ID,"success":true,"draft_v":null}),
        json!({"chat_id":ID,"success":true,"draft_v":"3"}),
        json!({"chat_id":ID,"success":true,"draft_v":0}),
        json!({"chat_id":ID,"success":true,"draft_v":1}),
        json!({"chat_id":ID,"success":true,"draft_v":2}),
        json!({"chat_id":ID,"success":true,"draft_v":3,"superseded":true}),
        json!({"chat_id":ID,"success":true,"draft_v":3,"team_id":OTHER}),
        json!({"chat_id":ID,"success":true,"draft_v":3,"hashed_team_id":sha256(OTHER)}),
        json!({"chat_id":OTHER,"success":true,"draft_v":3}),
    ] {
        let (api, server) = peer_control(false, "delete_draft", receipt(payload), None).await;
        let mut client = client(&api, false, true);
        let chats = client.chats.clone();
        let history = client.history.clone();
        assert!(
            tokio::time::timeout(Duration::from_secs(5), client.clear_draft(ID))
                .await
                .unwrap()
                .is_err()
        );
        assert_eq!(client.chats, chats);
        assert_eq!(client.history, history);
        assert_eq!(client.active_chat.as_deref(), Some(ID));
        assert_eq!(
            client.session().unwrap().cookies["auth_refresh_token"],
            "rotated"
        );
        server.await.unwrap();
    }
}

#[tokio::test]
async fn cancelled_clear_receipt_keeps_cache_and_rotated_credentials_without_fallback() {
    let cancel = CancellationToken::new();
    let (api, server) = peer_control(
        false,
        "delete_draft",
        receipt(json!({"chat_id":ID,"success":true,"draft_v":3})),
        Some(cancel.clone()),
    )
    .await;
    let mut client = client(&api, false, true);
    client.set_operation_cancel(cancel);
    let chats = client.chats.clone();
    assert!(matches!(
        client.clear_draft(ID).await,
        Err(Error::Cancelled)
    ));
    assert_eq!(client.chats, chats);
    assert_eq!(client.active_chat.as_deref(), Some(ID));
    assert_eq!(
        client.session().unwrap().cookies["auth_refresh_token"],
        "rotated"
    );
    server.await.unwrap();
}

#[tokio::test]
async fn foreign_cached_scope_is_refused_before_any_transport() {
    for (field, value) in [
        ("id", json!(OTHER)),
        ("team_id", json!(OTHER)),
        ("hashed_team_id", json!(sha256(OTHER))),
        ("chat_visibility", json!("direct")),
        ("user_id", json!("foreign")),
        ("hashed_user_id", json!(sha256("foreign"))),
        ("owner_id", json!("foreign")),
        ("team_id", json!(false)),
    ] {
        let mut client = client("http://127.0.0.1:1", false, true);
        client.chats.get_mut(ID).unwrap()[field] = value;
        let chats = client.chats.clone();
        assert!(matches!(
            client.clear_draft(ID).await,
            Err(Error::Forbidden)
        ));
        assert_eq!(client.chats, chats);
    }
    let mut client = client("http://127.0.0.1:1", true, true);
    assert!(matches!(
        client.clear_draft(ID).await,
        Err(Error::Unavailable {
            code: "team_draft_clear_unavailable",
            ..
        })
    ));
}

#[tokio::test]
async fn authentication_and_precancel_are_required_even_without_cached_metadata() {
    let mut client = Client::new("http://127.0.0.1:1", None).unwrap();
    assert!(matches!(
        client.clear_draft(ID).await,
        Err(Error::Authentication)
    ));
    let mut client =
        super::super::workspaces::delete_tests::client("http://127.0.0.1:1", false, true);
    let chats = client.chats.clone();
    let cancel = CancellationToken::new();
    cancel.cancel();
    client.set_operation_cancel(cancel);
    assert!(matches!(
        client.clear_draft(ID).await,
        Err(Error::Cancelled)
    ));
    assert_eq!(client.chats, chats);
}

#[test]
fn shell_classification_never_removes_saved_messages_or_key_wrappers() {
    let mut client = client("http://127.0.0.1:1", false, true);
    assert!(client.cached_draft_shell(ID).unwrap());
    client.chats.get_mut(ID).unwrap()["messages_v"] = json!(1);
    assert!(!client.cached_draft_shell(ID).unwrap());
    client.chats.get_mut(ID).unwrap()["messages_v"] = json!(0);
    client
        .history
        .insert(ID.into(), vec![json!({"encrypted_content":"opaque"})]);
    assert!(!client.cached_draft_shell(ID).unwrap());
    client.history.get_mut(ID).unwrap().clear();
    client.wrappers.push(json!({"hashed_chat_id":sha256(ID)}));
    assert!(!client.cached_draft_shell(ID).unwrap());
    client.wrappers.clear();
    client.chats.get_mut(ID).unwrap()["encrypted_chat_key"] = json!("opaque-saved-key");
    assert!(!client.cached_draft_shell(ID).unwrap());
}

#[test]
fn clear_publication_fence_rejects_changed_owner_generation_session_and_context() {
    assert_eq!(
        clear_owner(&json!({"id":"","user_id":"owner"})),
        Some("owner")
    );
    let mut client = client("http://127.0.0.1:1", false, true);
    let generation = client.generation;
    let session = client.session().unwrap().session_id.clone();
    let cancel = CancellationToken::new();
    assert!(
        client
            .draft_clear_current(generation, &session, Some("owner"), &cancel)
            .is_ok()
    );
    client.generation += 1;
    assert!(matches!(
        client.draft_clear_current(generation, &session, Some("owner"), &cancel),
        Err(Error::Cancelled)
    ));
    client.generation = generation;
    client.user = json!({"id":"foreign"});
    assert!(matches!(
        client.draft_clear_current(generation, &session, Some("owner"), &cancel),
        Err(Error::Cancelled)
    ));
    client.user = json!({"id":"owner"});
    assert!(matches!(
        client.draft_clear_current(generation, "other-session", Some("owner"), &cancel),
        Err(Error::Cancelled)
    ));
    client.session.as_mut().unwrap().active_team_id = Some(OTHER.into());
    assert!(matches!(
        client.draft_clear_current(generation, &session, Some("owner"), &cancel),
        Err(Error::Cancelled)
    ));
}
