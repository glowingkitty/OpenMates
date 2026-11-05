//! Focused real core lifecycle tests; no product network or synthetic terminal.
//! Product post-admission/recovery coverage belongs to shared three-adapter vectors.
use super::*;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
fn client() -> Client {
    let base="https://example.invalid";
    let mut client=Client::new(base,Some(Session { api_url:base.into(),session_id:"fixture".into(),cookies:BTreeMap::new(),ws_token:None,
        master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture-owner".into(),user_email_salt:String::new(),email_encryption_key:None,
        created_at:1,paired_session_expires_at:None,active_team_id:None })).expect("explicit fixture");
    client.user=json!({"id":OWNER});client
}
async fn cancelled(client:&mut Client)->SavedSendTerminal {
    let request=CancellationToken::new();
    let prepared=client.prepare_scoped_saved_send(None,request.clone()).expect("original admission");
    request.cancel();let (updates,_receiver)=mpsc::channel(1);
    // Existing actual send checks this child before any IO and returns itself.
    client.run_prepared_saved_send(prepared,"fixture",updates).await.expect("actual terminated future")
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn exact_pre_effect_child_rearms_without_resetting_original_parent() {
    let mut client=client();let parent=client.operation_parent.clone();
    let terminal=cancelled(&mut client).await;
    assert_eq!(terminal.outcome(),SavedSendOutcome::Cancelled);
    let mut disposition=client.take_scoped_saved_send_terminal(terminal).expect("actual terminal");
    assert!(disposition.reusable());assert_eq!(parent,client.operation_parent);assert!(!parent.is_cancelled());
    assert!(matches!(disposition.take_result(&client),Err(Error::Cancelled)));
    disposition.publication_guard().check_release().expect("separate final proof");
    let terminal=cancelled(&mut client).await;
    assert!(disposition.publication_guard().check_release().is_err());
    client.take_scoped_saved_send_terminal(terminal).expect("successor own terminal");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn queued_live_guard_never_borrows_terminal_rearm_child() {
    let mut client=client();let request=CancellationToken::new();
    let prepared=client.prepare_scoped_saved_send(None,request.clone()).expect("original");
    let live=prepared.publication_guard();assert!(live.check_release().is_err());
    request.cancel();let(updates,_receiver)=mpsc::channel(1);
    let terminal=client.run_prepared_saved_send(prepared,"fixture",updates).await.expect("actual future");
    let disposition=client.take_scoped_saved_send_terminal(terminal).expect("exact rearm");
    assert!(live.check_release().is_err());assert!(disposition.publication_guard().check_release().is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn root_policy_reset_and_denial_refuse_exact_terminal_rearm() {
    let mut root=client();let terminal=cancelled(&mut root).await;root.operation_parent.cancel();
    assert!(root.take_scoped_saved_send_terminal(terminal).is_err());
    let mut policy=client();let terminal=cancelled(&mut policy).await;policy.set_private_operation_gate(None);
    assert!(policy.take_scoped_saved_send_terminal(terminal).is_err());
    let mut reset=client();let terminal=cancelled(&mut reset).await;reset.forget_session();
    assert!(reset.take_scoped_saved_send_terminal(terminal).is_err());
    let mut denied=client();let terminal=cancelled(&mut denied).await;denied.task_watch_authority.deny_cached_chat(None).expect("denial");
    assert!(denied.take_scoped_saved_send_terminal(terminal).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn final_release_is_nonblocking_and_observes_original_denial_and_configuration() {
    let mut client=client();let terminal=cancelled(&mut client).await;
    let disposition=client.take_scoped_saved_send_terminal(terminal).expect("terminal");let guard=disposition.publication_guard();
    let held=client.scoped_send_gate.state.write().expect("fixture hold");assert!(guard.check_release().is_err());drop(held);
    assert!(guard.check_release().is_ok());client.task_watch_authority.deny_cached_chat(None).expect("negative observation");assert!(guard.check_release().is_err());
    let mut client=super::scoped_saved_send_tests::client();let terminal=cancelled(&mut client).await;
    let disposition=client.take_scoped_saved_send_terminal(terminal).expect("terminal");let guard=disposition.publication_guard();
    client.set_privacy_options(crate::privacy::PrivacyOptions::default());assert!(guard.check_release().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn stale_original_finish_cannot_release_or_refuse_successor_lane() {
    let lane=ScopedSendGate::default();let a=CancellationToken::new();let b=CancellationToken::new();
    lane.start("A",&a).expect("A");lane.finish("A",true);lane.start("B",&b).expect("B");
    lane.finish("A",false);assert_eq!(lane.state.read().expect("state").active.as_deref(),Some("B"));
    assert!(lane.check_publication("B",&b).is_ok());assert!(a.is_cancelled());lane.finish("B",true);lane.idle().await.expect("B actual drain");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn count_and_aggregate_backpressure_never_evict_original_attempts_or_close_parent() {
    let mut client=client();let parent=client.operation_parent.clone();
    for index in 0..MAX_SCOPED_SAVED_SEND_QUARANTINES { client.scoped_send_quarantine.insert(index.to_string(),std::sync::Arc::new(std::sync::Mutex::new(ScopedSendObservation::default()))); }
    let prepared=client.prepare_scoped_saved_send(None,CancellationToken::new()).expect("original preparation");let(updates,_receiver)=mpsc::channel(1);
    let terminal=client.run_prepared_saved_send(prepared,"fixture",updates).await.expect("actual preeffect terminal");
    assert_eq!(terminal.outcome(),SavedSendOutcome::Backpressure);
    let disposition=client.take_scoped_saved_send_terminal(terminal).expect("original parent");
    assert!(disposition.can_continue_parent());assert!(disposition.original_turn_settled());assert_eq!(parent,client.operation_parent);
    assert_eq!(client.scoped_send_quarantine.len(),MAX_SCOPED_SAVED_SEND_QUARANTINES);
    client.scoped_send_quarantine_bytes=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES;
    let prepared=client.prepare_scoped_saved_send(None,CancellationToken::new()).expect("byte preparation");let(updates,_receiver)=mpsc::channel(1);
    let terminal=client.run_prepared_saved_send(prepared,"fixture",updates).await.expect("actual byte backpressure");
    assert_eq!(terminal.outcome(),SavedSendOutcome::Backpressure);client.take_scoped_saved_send_terminal(terminal).expect("parent still live");
    assert_eq!(client.scoped_send_quarantine.len(),MAX_SCOPED_SAVED_SEND_QUARANTINES);client.forget_session();
    assert!(client.scoped_send_quarantine.is_empty());assert_eq!(client.scoped_send_quarantine_bytes,0);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn byte_counter_matches_actual_json_escaping_without_retaining_a_serialized_plaintext_copy() {
    for value in [json!({"x":"quote\" and \\ slash"}),json!(["猫","\n","\u{0001}"]),json!({"nested":[true,1,null]})] {
        let size=serde_json::to_vec(&value).expect("independent encoder").len();
        assert_eq!(scoped_admission_size(&value,size).expect("exact boundary"),size);
        assert!(matches!(scoped_admission_size(&value,size-1),Err(Error::Conflict)));
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn original_final_guard_rechecks_after_gate_cancels_or_denies_while_returning_ok(){
    use std::sync::{Arc,Mutex,atomic::{AtomicBool,Ordering}};
    for kind in 0..3 {
        let mut client=client();let armed=Arc::new(AtomicBool::new(false));let gate_armed=armed.clone();
        let target=Arc::new(Mutex::new(None::<CancellationToken>));let gate_target=target.clone();
        let authority=client.task_watch_authority.clone();
        client.set_private_operation_gate(Some(Arc::new(move||{
            if gate_armed.load(Ordering::Acquire){
                if kind==2{authority.deny_cached_chat(None)?;}else{gate_target.lock().map_err(|_|Error::Cancelled)?.as_ref().ok_or(Error::Cancelled)?.cancel();}
            }
            Ok(())
        })));
        // Obtain the actual original core terminal/rearm; no fixture-created
        // execution, child transition, completed DTO or admission status.
        let terminal=cancelled(&mut client).await;
        let disposition=client.take_scoped_saved_send_terminal(terminal).expect("actual terminal");
        let guard=disposition.publication_guard();assert!(guard.request.is_none(),"retired old request stays intentionally ignored");
        guard.check_release().expect("actual original guard before revocation");
        *target.lock().expect("fixture target")=Some(if kind==0{guard.parent.clone()}else{guard.child.clone()});
        armed.store(true,Ordering::Release);
        assert!(guard.check_release().is_err(),"same synchronous callback cannot hide original negative revocation");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn original_final_guard_shares_observation_reads_but_excludes_transition_writes() {
    let mut client = client();
    let terminal = cancelled(&mut client).await;
    let disposition = client.take_scoped_saved_send_terminal(terminal).expect("actual terminal");
    let original = disposition.publication_guard();
    let read = client.scoped_send_gate.state.read().expect("read-only observation");
    std::thread::scope(|threads| {
        let checked = threads.spawn(|| original.check_release());
        assert!(checked.join().expect("observer joined").is_ok());
    });
    drop(read);
    let refused = std::thread::scope(|threads| {
        let write = client.scoped_send_gate.state.write().expect("exclusive transition");
        let (send, receive) = std::sync::mpsc::channel();
        let guard = &original;
        threads.spawn(move || { let _ = send.send(guard.check_release()); });
        let observed = receive.recv_timeout(Duration::from_secs(1));
        // Release even if a future regression incorrectly blocks its observer.
        drop(write);
        observed
    });
    assert!(matches!(refused, Ok(Err(Error::Cancelled))));
    assert!(original.check_release().is_ok());
    client.operation_parent.cancel();
    assert!(original.check_release().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn poisoned_publication_transition_never_admits_original_output() {
    let mut client = client();
    let terminal = cancelled(&mut client).await;
    let disposition = client.take_scoped_saved_send_terminal(terminal).expect("actual terminal");
    let original = disposition.publication_guard();
    std::thread::scope(|threads| {
        let state = &client.scoped_send_gate.state;
        assert!(threads.spawn(move || {
            let _write = state.write().expect("exclusive transition");
            panic!("intentional transition poison");
        }).join().is_err());
    });
    assert!(matches!(original.check_release(), Err(Error::Cancelled)));
}
