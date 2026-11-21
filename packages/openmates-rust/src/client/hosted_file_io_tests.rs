//! Hosted file commits accept the web Worker's browser credentials, not only a native session.
use super::*;

#[tokio::test]
async fn a_browser_credential_client_is_not_refused_as_needing_a_native_session() {
    let mut client = super::super::browser_draft::tests::client();
    assert!(client.session.is_none());
    let refused = client
        .commit_embed_revision(json!({"embed_id": "e"}))
        .await
        .expect_err("no server listens on the fixture URL");
    assert_ne!(
        refused,
        Error::Unavailable {
            code: "native_session_required",
            reason: "THIS_OPERATION_REQUIRES_NATIVE_SESSION_MATERIAL",
        }
    );
}
