//! Offline draft writes of a local-read-only browser client: local encrypted row and
//! durable intent are allowed (also team and create-chat), publication and other
//! server operations stay refused, and the same principal publishes after online admission.
use super::super::browser_draft::tests::{
    client, io, options, store, write_with, CHAT, TEAM,
};
use super::*;

#[tokio::test]
async fn offline_write_is_encrypted_queued_and_has_no_publication_payload() {
    let mut c = client();
    assert!(c.is_local_browser_profile());
    let s = store();
    let w = write_with(&mut c, &s, &options(None, false)).await.unwrap();
    assert!(w.remote_payload_if_admitted(&c).unwrap().is_none());
    let row = s.borrow().row.clone();
    let change = s.borrow().change.clone();
    assert!(!row["encrypted_draft_md"].as_str().unwrap().contains("Synthetic"));
    assert_eq!(change["type"], "draft");
    assert_eq!(change["value"], row["encrypted_draft_md"]);
    assert!(change.get("markdown").is_none());
}

#[tokio::test]
async fn offline_team_and_create_chat_options_behave_like_online() {
    let mut c = client();
    let s = store();
    s.borrow_mut().row = Value::Null;
    let w = write_with(&mut c, &s, &options(Some(TEAM), true)).await.unwrap();
    assert!(w.remote_payload_if_admitted(&c).unwrap().is_none());
    assert_eq!(s.borrow().row["team_id"], TEAM);
    assert_eq!(s.borrow().change["team_id"], TEAM);
    s.borrow_mut().row = Value::Null;
    assert!(matches!(
        write_with(&mut c, &s, &options(None, false)).await.err(),
        Some(Error::Unavailable { code: "existing_chat_required", .. })
    ));
}

#[tokio::test]
async fn offline_profile_still_refuses_server_operations() {
    let mut c = client();
    let s = store();
    let w = write_with(&mut c, &s, &options(None, false)).await.unwrap();
    assert!(matches!(w.remote_payload(&c), Err(Error::Forbidden)));
    assert!(c.require_canonical_read_profile().is_err());
    assert!(matches!(
        w.acknowledge_transport(&mut c, io(s.clone())).await,
        Err(Error::Forbidden)
    ));
    assert!(!s.borrow().change.is_null());
}

#[tokio::test]
async fn online_admission_publishes_after_the_offline_write_with_the_next_version() {
    let mut c = client();
    let s = store();
    let offline = write_with(&mut c, &s, &options(None, false)).await.unwrap();
    let offline_version: Value = serde_json::from_str(&offline.local_result(&c).unwrap()).unwrap();
    drop(offline);
    // Same principal, now admitted with server validation (a new admission replaces the client).
    c.browser_local_read_only = false;
    let w = write_with(&mut c, &s, &options(None, false)).await.unwrap();
    let payload: Value =
        serde_json::from_str(&w.remote_payload_if_admitted(&c).unwrap().unwrap()).unwrap();
    assert_eq!(payload["chat_id"], CHAT);
    assert_eq!(payload["draft_v"], offline_version["version"].as_u64().unwrap() + 1);
}
