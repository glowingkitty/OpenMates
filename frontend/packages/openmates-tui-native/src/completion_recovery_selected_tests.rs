//! Authored encrypted-store regression. No account/backend or inference.
use super::*;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OTHER: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
fn checkpoint(job: &str, chat: &str) -> CompletionRecoveryCheckpoint {
    serde_json::from_value(serde_json::json!({"protocol_version":1,"api_url":"https://synthetic.invalid","owner_id":"11111111-1111-4111-8111-111111111111","team_id":null,"job":{"kind":"main","job_id":job,"chat_id":chat,"turn_id":"33333333-3333-4333-8333-333333333333","assistant_message_id":"55555555-5555-4555-8555-555555555555","task_id":null,"stage":null,"chat_key_version":1},"encrypted_candidate":{"retained":"sealed test bytes"},"wrapped_chat_key":null,"canonical_ciphertext":false})).unwrap()
}
#[tokio::test]
async fn selected_pending_clear_preserves_unrelated_ciphertext_and_continuations() {
    tokio::time::timeout(std::time::Duration::from_secs(30),async {
        let directory=tempfile::tempdir().unwrap();
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; std::fs::set_permissions(directory.path(),std::fs::Permissions::from_mode(0o700)).unwrap(); }
        let session=crate::storage::Session {api_url:"https://synthetic.invalid".into(),session_id:"synthetic".into(),cookies:Default::default(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic-owner".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None};
        let store=RuntimeStore::new(Some(directory.path().to_owned()),true).await.unwrap();
        store.begin_session(session.clone()).await.unwrap();
        store.save(session.clone(),Some(zeroize::Zeroizing::new("synthetic fixture passphrase".into()))).await.unwrap();
        let client=Client::new(&session.api_url,Some(session.clone())).unwrap();
        let selected=checkpoint("44444444-4444-4444-8444-444444444444",CHAT);
        let unrelated=checkpoint("66666666-6666-4666-8666-666666666666",OTHER);
        for candidate in [&selected,&unrelated] {
            persist_checkpoint(&store,CompletionCheckpointWrite{owner:session.hashed_email.clone(),cache_key:cache_key(&client).unwrap(),master:session.master_key.clone(),value:serde_json::to_value(candidate).unwrap(),job_id:candidate.job().job_id.clone(),digest:candidate.digest().unwrap(),store_generation:store.generation()}).await.unwrap();
        }
        let cursor_key=format!("{}-continuation",cache_key(&client).unwrap());
        store.write_cache(session.hashed_email.clone(),cursor_key.clone(),session.master_key.clone(),Value::String(unrelated.job().job_id.clone())).await.unwrap();
        let all=load_pending(&client,&store).await.unwrap();
        let eligible=all.iter().filter(|p|eligible_for_selected_chat(Some(CHAT),p.job())).collect::<Vec<_>>();
        assert_eq!(eligible.len(),1);assert_eq!(eligible[0].job().job_id,selected.job().job_id);
        assert!(all.iter().all(|p|eligible_for_selected_chat(None,p.job())));
        clear_pending(&client,&store,&selected.job().job_id).await.unwrap();
        let remaining=load_pending(&client,&store).await.unwrap();
        assert_eq!(remaining.len(),1);assert_eq!(remaining[0].digest().unwrap(),unrelated.digest().unwrap());
        assert_eq!(store.read_cache(session.hashed_email.clone(),cursor_key,session.master_key.clone()).await.unwrap(),Some(Value::String(unrelated.job().job_id.clone())));
    }).await.unwrap();
}
