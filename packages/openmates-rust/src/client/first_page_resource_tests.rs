//! Pure original-resource queued-output rejection. No HTTP or account grant.
use super::*;
use crate::session::Session;
use serde_json::json;
use zeroize::{Zeroize, Zeroizing};
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[tokio::test]
async fn queued_saved_admission_checks_original_master_resource_not_replacement() {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&session.api_url, Some(session.clone())).unwrap();
    client.user = json!({"id":"synthetic"});
    client.browser_credentials = Some(
        crate::client::credentials::BrowserCredentials::from_native_session(
            client.session.take().unwrap(),
        ),
    );
    let original = client.browser_credentials.as_ref().unwrap().master.clone();
    let admission = client.saved_chat_read_admission().unwrap();
    let mut output = Zeroizing::new("SYNTHETIC_PRIVATE_OUTPUT".to_owned());
    let (send, receive) = tokio::sync::oneshot::channel();
    send.send(admission).ok().unwrap();
    // A new live resource must never rescue the original queued proof.
    client.browser_credentials.as_mut().unwrap().master =
        crate::crypto::master::MasterCapability::from_native(Zeroizing::new([7; 32]));
    original.invalidate();
    let queued = receive.await.unwrap();
    assert!(matches!(
        queued.ensure_resource_current(),
        Err(Error::Cancelled)
    ));
    if queued.ensure_resource_current().is_err() {
        output.zeroize();
    }
    assert!(output.is_empty());
}
