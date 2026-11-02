//! Browser JSON handoff admission tests, authored UNRUN for isolated Rust CI.
//! Explicit synthetic in-memory native key only; no credential-store discovery.
//! No test calls product HTTP, WebCrypto, account or browser admission.
//! These negative/context checks do not prove real browser authentication.
//! Actual successful paging/crypto belongs to the authored built-app case.
// contract-test-file: tooling
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
fn session()->Session {
    Session{api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:None,
        master_key:zeroize::Zeroizing::new([7;32]),hashed_email:String::new(),user_email_salt:String::new(),email_encryption_key:None,
        created_at:1,paired_session_expires_at:None,active_team_id:None}
}
fn context()->Client {
    let session=session();
    let mut client=Client::new("http://127.0.0.1:9",None).unwrap();
    client.browser_credentials=Some(credentials::BrowserCredentials::from_native_session(session));
    assert!(client.session.is_none());
    client.user=json!({"id":OWNER});
    client.browser_transport=true;client.browser_authority=Some(BrowserAuthority{principal:OWNER.into(),persistence:BrowserPersistence::MemoryOnly,owner_guards:false});client
}
#[test]
fn canonical_json_handoff_requires_current_browser_principal_and_never_upgrades_local_mode() {
    let mut client=context();assert!(client.browser_canonical_json_current(OWNER).is_ok());
    assert!(client.browser_canonical_json_current(CHAT).is_err());client.user=json!({"id":CHAT});assert!(client.browser_canonical_json_current(OWNER).is_err());
    client.user=json!({"id":OWNER});client.browser_transport=false;assert!(client.browser_canonical_json_current(OWNER).is_err());
    client.browser_transport=true;client.browser_local_read_only=true;
    assert!(matches!(client.browser_canonical_json_current(OWNER),Err(Error::Unavailable{code:"local_profile_read_only",..})));
}
#[tokio::test]
async fn browser_json_admission_rejects_unbounded_multi_page_or_stored_mode_before_any_http() {
    for change in 0..3 {
        let mut client=context();let mut options=saved_chat_read::SavedChatReadOptions{limit:20,max_pages:1,content_mode:saved_chat_read::SavedChatContentMode::PageLocal,..Default::default()};
        match change{0=>options.limit=21,1=>options.max_pages=2,_=>options.content_mode=saved_chat_read::SavedChatContentMode::Stored};
        assert!(matches!(client.browser_saved_chat_read_json(OWNER,CHAT,options).await,Err(Error::Invalid(_))));
        assert_eq!(client.credential_ack,0);assert!(client.history.is_empty());
    }
}
#[test]
fn canonical_json_original_scope_refuses_generation_operation_and_negative_revision_drift() {
    for change in 0..3 {
        let mut client=context();let scope=sync_capability::AsyncCryptoScope::begin(&client).unwrap();
        match change{0=>client.generation+=1,1=>client.operation_cancel.cancel(),_=>client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap()};
        assert!(scope.check_chat(&client,CHAT).is_err());assert_eq!(client.credential_ack,0);
    }
}

#[test]
fn native_session_with_local_flag_is_not_a_browser_json_admission() {
    let mut client=Client::new("http://127.0.0.1:9",Some(session())).unwrap();
    client.user=json!({"id":OWNER});client.browser_transport=true;client.browser_local_read_only=true;
    assert!(!client.is_local_browser_profile());
    assert!(matches!(client.browser_canonical_json_current(OWNER),Err(Error::Forbidden)));
    assert_eq!(client.credential_ack,0);
}
