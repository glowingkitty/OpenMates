//! Pure selected ciphertext rollback. No server, auth grant or user account.
use super::*;
use zeroize::Zeroizing;
const ID: &str = "22222222-2222-4222-8222-222222222222";
// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
#[test]
fn rejected_live_transaction_restores_selected_ciphertext_without_restoring_denial_authority() {
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
    client.credentials_changed();
    let row = json!({"id":ID,"messages_v":2,"encrypted_chat_key":crate::crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_title":crate::crypto::encrypt_combined("Synthetic",&[9;32]).unwrap()});
    client.chats.insert(ID.into(), row.clone());
    let page = json!({"messages":[{"id":"10000000-0000-4000-8000-000000000001","chat_id":ID,"created_at":1,"role":"user","encrypted_content":crate::crypto::encrypt_combined("Synthetic",&[9;32]).unwrap()}],"server_message_count":2,"has_more_before":true,"start_cursor":{"created_at":1,"message_id":"10000000-0000-4000-8000-000000000001"}});
    let selected = client.prepare_selected_first_page(&row, &page).unwrap();
    client.selected_first_pages.insert(ID.into(), selected);
    let monitor = ChatMonitor {
        fence: Arc::new(MonitorFence {
            owner: client.task_watch_authority.clone(),
            generation: client.generation,
            team: None,
            expires_at: None,
            cancel: CancellationToken::new(),
            alive: std::sync::atomic::AtomicBool::new(true),
            denial: Mutex::new(None),
        }),
        changes: Arc::new(Changes::default()),
    };
    let before = client.ciphertext_snapshot();
    {
        let mut transaction = LiveReadTransaction::new(&mut client, monitor.fence.clone()).unwrap();
        transaction.selected_first_pages.clear();
    }
    assert_eq!(
        client.ciphertext_snapshot(),
        before,
        "new DATA must participate in read transaction rollback"
    );
    {
        let mut transaction = LiveReadTransaction::new(&mut client, monitor.fence.clone()).unwrap();
        transaction.selected_first_pages.clear();
        monitor
            .deny(ChatMonitorAccessDenial::ChatUnavailable { chat_id: ID.into() })
            .unwrap();
    }
    assert!(!client.task_watch_authority.cached_chat_allowed(ID));
    assert!(
        client.selected_first_pages.is_empty(),
        "known denial never resurrects earlier selected ciphertext"
    );
}
