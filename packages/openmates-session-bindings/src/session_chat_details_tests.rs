// contract-test-file: tooling
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
//! Authored final-lane tests: synthetic queued rich JSON, not successful read IO.
//! The production path moves its admission from actual read.take_admission.
use super::*;
const ID: &str = "22222222-2222-4222-8222-222222222222";
fn ok<T>(result: Result<T>) -> T {let Ok(value)=result else {panic!("chat details fixture setup");};value}
fn expected() -> String {
    // Typed output can preserve escaped UTF-16 leaf units; Value cannot.
    #[derive(serde::Deserialize)]
    struct Fixture {vectors:Vec<Vector>}
    #[derive(serde::Deserialize)]
    struct Vector {expected:openmates_sdk::client::chat_details::ChatDetailsRead}
    let fixture:Fixture=serde_json::from_str(include_str!("../tests/fixtures/chat-details-read.json")).unwrap();
    fixture.vectors[0].expected.sdk_json().unwrap()
}
async fn bridge() -> SessionBridge {
    let b=ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#));
    ok(b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=","hashed_email":"synthetic-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await);b
}
async fn pending(b:&SessionBridge) -> ChatDetailsOutput {
    let guard=Arc::new(ok(b.admit_work()));
    let (admission,original_privacy,original_gate)={let mut c=b.state.client.lock().await;
        c.set_operation_cancel(guard.token());
        (c.full_chat_read_admission(ID).unwrap_or_else(|_|panic!("original rich admission")),c.options().privacy.clone(),c.options().private_operation_gate.clone())};
    ChatDetailsOutput {state:b.state.clone(),guard,admission,original_privacy,original_gate,output:Zeroizing::new(expected())}
}
#[tokio::test]
async fn positive_rich_bytes_followups_and_one_shot_release_preserve_wiping_scratch() {
    let b=bridge().await;let mut output=pending(&b).await;
    let value=ok(output.encode_checked(|text|Ok(text.to_owned())));
    assert_eq!(value,expected());
    assert!(output.output.is_empty());
    assert!(output.encode_checked::<()>(|_|panic!("reused admission encoded")).is_err());
}
#[tokio::test]
async fn queued_cancel_privacy_core_owner_and_key_reset_refuse_before_allocation() {
    for change in ["cancel","privacy","core","team","owner","same-owner-key-reset"] {
        let b=bridge().await;let mut output=pending(&b).await;
        let (send,resume)=tokio::sync::oneshot::channel();
        let release=tokio::spawn(async move {let _=resume.await;let result=output.encode_checked::<()>(|_|panic!("stale rich allocation"));assert!(output.output.is_empty());result});
        match change {
            "cancel"=>ok(b.cancel()),
            "privacy"=>b.state.client.lock().await.set_privacy_options(PrivacyOptions {enhanced:true}),
            "core"=>b.state.client.lock().await.forget_session(),
            "team"=>ok(b.set_team(Some("33333333-3333-4333-8333-333333333333".into())).await),
            _=>ok(b.import_session(json!({"api_url":"http://127.0.0.1:9","session_id":"replacement-session","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":if change=="owner"{"other-owner"}else{"synthetic-owner"},"user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await),
        }
        assert!(send.send(()).is_ok());let Ok(result)=release.await else{panic!("queued rich join");};
        assert_eq!(result.err().unwrap().code,match change{"privacy"=>"invalid_argument","core"=>"authentication",_=>"cancelled"});
    }
}
#[tokio::test]
async fn original_gate_replaced_then_revoked_before_or_during_allocation_refuses_handoff() {
    for during in [false,true] {
        let b=bridge().await;let gate=Arc::new(AtomicBool::new(true));let captured=gate.clone();
        b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(move||if captured.load(Ordering::Acquire){Ok(())}else{Err(Error::Forbidden)})));
        let mut output=pending(&b).await;
        b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
        if !during {gate.store(false,Ordering::Release);}
        let encoded=AtomicBool::new(false);
        let result=output.encode_checked(|text|{assert!(during);encoded.store(true,Ordering::Release);let value=Zeroizing::new(text.to_owned());gate.store(false,Ordering::Release);Ok(value)});
        assert_eq!(result.err().unwrap().code,"forbidden");assert!(output.output.is_empty());assert_eq!(encoded.load(Ordering::Acquire),during);
    }
}
#[tokio::test]
async fn stale_a_refusal_and_drop_preserve_exact_b_child_and_b_release() {
    let b=bridge().await;let mut a=pending(&b).await;let successor=pending(&b).await;
    assert_eq!(a.encode_checked::<()>(|_|panic!("stale A allocated")).err().unwrap().code,"cancelled");
    assert!(a.output.is_empty());drop(a);
    assert!(!successor.guard.token().is_cancelled());assert!(successor.admission.check(&*b.state.client.lock().await).is_ok());
    assert_eq!(ok(successor.release_json()),expected());
}
#[tokio::test]
async fn final_lock_is_nonblocking_and_encoder_error_wipes_owned_json() {
    let b=bridge().await;let mut output=pending(&b).await;let lock=b.state.client.lock().await;
    assert_eq!(output.encode_checked::<()>(|_|panic!("contended allocation")).err().unwrap().code,"conflict");
    assert!(output.output.is_empty());drop(lock);drop(output);
    let mut output=pending(&b).await;
    assert_eq!(output.encode_checked::<()>(|_|Err(Error::Protocol.into())).err().unwrap().code,"protocol");assert!(output.output.is_empty());
}
#[tokio::test]
async fn cancellation_inside_final_encoder_refuses_after_allocation() {
    let b=bridge().await;let mut output=pending(&b).await;let cancel=output.guard.token();
    let result=output.encode_checked(|text|{let value=Zeroizing::new(text.to_owned());cancel.cancel();Ok(value)});
    assert_eq!(result.err().unwrap().code,"cancelled");assert!(output.output.is_empty());
}
#[tokio::test]
async fn permitted_original_gate_survives_current_gate_replacement() {
    let b=bridge().await;b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
    let output=pending(&b).await;b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(||Ok(()))));
    assert_eq!(ok(output.release_json()),expected());
}
#[tokio::test]
async fn invalid_rich_options_fail_before_authentication_or_any_io() {
    let b=ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:9","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#));
    for options in ["true","[]","{\"history\":{\"kind\":\"invented\"}}","{\"unreviewed\":true}"] {
        assert_eq!(b.chat_details(ID.into(),options.into()).await.err().unwrap().code,"invalid_argument");
    }
    assert_eq!(b.chat_details(ID.into(),"x".repeat(4097)).await.err().unwrap().code,"invalid_argument");
}
