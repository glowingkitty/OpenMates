//! Authored final-lane security regressions. Synthetic queued scratch only;
//! these do not manufacture an actual successful HTTP/decrypt full read.
use super::*;
const ID: &str = "22222222-2222-4222-8222-222222222222";
const JSON: &str = r#"{"id":"22222222-2222-4222-8222-222222222222","slug":"original"}"#;
fn ok<T>(result: Result<T>) -> T {
    let Ok(value) = result else {panic!("full read test setup failed");}; value
}
async fn bridge() -> SessionBridge {
    let b=ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#));
    ok(b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","hashed_email":"synthetic-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await);
    b
}
async fn pending(b:&SessionBridge) -> FullChatOutput {
    let guard=Arc::new(ok(b.admit_work()));
    let admission={let mut client=b.state.client.lock().await;
        client.set_operation_cancel(guard.token());
        client.full_chat_read_admission(ID).unwrap_or_else(|_|panic!("core test admission"))};
    FullChatOutput {state:b.state.clone(),guard,admission,output:Zeroizing::new(JSON.into())}
}
#[tokio::test]
async fn ordinary_output_allocates_exact_bytes_once_then_wipes_rust_scratch() {
    let b=bridge().await;let mut output=pending(&b).await;
    let value=ok(output.encode_checked(|text|Ok(text.to_owned())));
    assert_eq!(value,JSON);assert!(output.output.is_empty());
    assert!(output.encode_checked::<()>(|_|panic!("one-shot scope must reject")).is_err());
}
#[tokio::test]
async fn queued_cancel_owner_rotation_revoke_and_privacy_tightening_refuse_before_allocation() {
    for change in ["cancel","owner","core","privacy"] {
        let b=bridge().await;let mut output=pending(&b).await;
        let (send,resume)=tokio::sync::oneshot::channel();
        let release=tokio::spawn(async move {let _=resume.await;
            let result:Result<()>=output.encode_checked(|_|panic!("stale output allocated"));
            assert!(output.output.is_empty());result});
        match change {
            "cancel"=>ok(b.cancel()),
            "owner"=>ok(b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"other-session","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"other-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await),
            "core"=>b.state.client.lock().await.forget_session(),
            _=>b.state.client.lock().await.set_privacy_options(PrivacyOptions {enhanced:true}),
        }
        assert!(send.send(()).is_ok());
        let Ok(result)=release.await else {panic!("queued release join");};assert!(result.is_err());
    }
}
#[tokio::test]
async fn original_gate_revocation_after_replacement_and_during_allocation_refuses_handoff() {
    for during in [false,true] {
        let b=bridge().await;let gate=Arc::new(AtomicBool::new(true));let captured=gate.clone();
        b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(move ||
            if captured.load(Ordering::Acquire){Ok(())}else{Err(Error::Forbidden)})));
        let mut output=pending(&b).await;
        b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
        if !during {gate.store(false,Ordering::Release);}
        let allocated=AtomicBool::new(false);
        let result=output.encode_checked(|text|{assert!(during);assert_eq!(text,JSON);
            allocated.store(true,Ordering::Release);gate.store(false,Ordering::Release);Ok(text.to_owned())});
        assert!(result.is_err());assert!(output.output.is_empty());
        assert_eq!(allocated.load(Ordering::Acquire),during);
    }
}
#[tokio::test]
async fn stale_a_drop_and_final_refusal_preserve_b_original_child_and_b_can_release() {
    let b=bridge().await;let mut a=pending(&b).await;let successor=pending(&b).await;
    assert!(a.encode_checked::<()>(|_|panic!("stale A allocated")).is_err());
    assert!(a.output.is_empty());drop(a);
    assert!(!successor.guard.token().is_cancelled());
    assert!(successor.admission.check(&*b.state.client.lock().await).is_ok());
    assert_eq!(ok(successor.release_json()),JSON);
}
#[tokio::test]
async fn final_lane_refuses_lock_contention_and_encoder_error_and_erases_scratch() {
    let b=bridge().await;let mut output=pending(&b).await;
    let lock=b.state.client.lock().await;
    let result:Result<()>=output.encode_checked(|_|panic!("contended final allocation"));
    assert_eq!(result.err().unwrap().code,"conflict");assert!(output.output.is_empty());drop(lock);drop(output);
    let mut output=pending(&b).await;
    let result:Result<()>=output.encode_checked(|_|Err(Error::Protocol.into()));
    assert_eq!(result.err().unwrap().code,"protocol");assert!(output.output.is_empty());
}
#[tokio::test]
async fn cancelling_during_final_allocation_rejects_after_value_creation() {
    let b=bridge().await;let mut output=pending(&b).await;let cancel=output.guard.token();
    let result=output.encode_checked(|text|{let value=text.to_owned();cancel.cancel();Ok(value)});
    assert_eq!(result.err().unwrap().code,"cancelled");assert!(output.output.is_empty());
}

#[tokio::test]
async fn still_permitted_original_gate_survives_current_gate_replacement() {
    let b=bridge().await;
    b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
    let output=pending(&b).await;
    b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
    assert_eq!(ok(output.release_json()),JSON);
}
