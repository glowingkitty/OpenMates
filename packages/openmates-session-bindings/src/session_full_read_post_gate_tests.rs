//! Actual final allocator method, with synthetic queued bytes, no HTTP read claim.
use super::*;
const ID:&str="22222222-2222-4222-8222-222222222222";
const JSON:&str=r#"{"id":"22222222-2222-4222-8222-222222222222","slug":"original"}"#;
fn ok<T>(value:Result<T>)->T {match value {Ok(value)=>value,Err(_)=>panic!("synthetic final allocator setup/result")}}
async fn bridge()->SessionBridge {
    let b=ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#));
    ok(b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","hashed_email":"synthetic-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await);b
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test]
async fn successful_post_allocation_gate_cannot_retire_independent_original_sdk_parent() {
    for retire in [false,true] {
        let b=bridge().await;let guard=Arc::new(ok(b.admit_work()));
        // Deliberately independent: WorkGuard checks cannot detect this SDK
        // parent's cancellation, so admission must reject it after the callback.
        let parent=CancellationToken::new();let captured=parent.clone();
        let calls=Arc::new(std::sync::atomic::AtomicUsize::new(0));let count=calls.clone();
        let target=Arc::new(std::sync::atomic::AtomicUsize::new(0));let trigger=target.clone();
        let admission={let mut client=b.state.client.lock().await;
            client.set_operation_cancel(parent.clone());
            client.set_private_operation_gate(Some(Arc::new(move || {
                if count.fetch_add(1,Ordering::SeqCst)+1==trigger.load(Ordering::SeqCst) {captured.cancel();}
                Ok(())
            })));
            client.full_chat_read_admission(ID).unwrap()};
        let mut output=FullChatOutput {state:b.state.clone(),guard:guard.clone(),admission,output:Zeroizing::new(JSON.into())};
        let result=output.encode_checked(|text| {
            assert_eq!(text,JSON);calls.store(0,Ordering::SeqCst);
            target.store(if retire {4}else{0},Ordering::SeqCst);Ok(text.to_owned())
        });
        assert_eq!(calls.load(Ordering::SeqCst),4);
        assert!(!guard.token().is_cancelled());assert!(work_authority(&guard).is_ok());
        assert!(output.output.is_empty());
        if retire {assert!(parent.is_cancelled());assert!(result.is_err());}else{assert_eq!(ok(result),JSON);}
    }
}
