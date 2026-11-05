//! Actual portable ownership paths; no injected terminal, transport, or scope.
//! These authored native cases have not been executed in this source packet.
use super::*;
fn client()->Client {
    let api="http://127.0.0.1:9";
    let mut c=Client::new(api,Some(Session {api_url:api.into(),session_id:"owned-send-fixture".into(),
        cookies:Default::default(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),
        hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,
        created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("explicit native fixture");
    c.user=json!({"id":"11111111-1111-4111-8111-111111111111"});c
}
async fn terminal(driver:&mut OwnedSavedSendDriver)->OwnedSavedSendTerminal {
    match driver.drive_next().await.expect("actual owned future returns") {
        OwnedSavedSendStep::Terminal(value)=>value,
        OwnedSavedSendStep::Apply(_)=>panic!("no Client phase may run after pre-effect refusal"),
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn pre_effect_stop_returns_actual_terminal_without_changing_original_parent_or_ordinary_child(){
    let mut c=client();let parent=c.operation_parent.clone();let ordinary=c.operation_cancel.clone();
    let request=CancellationToken::new();let prepared=c.prepare_owned_saved_send(None,request.clone()).expect("actual original preparation");
    let old=prepared.publication_guard().expect("old live guard");request.cancel();
    let(updates,_)=mpsc::channel(4);let mut driver=c.start_owned_saved_send(prepared,"private",updates).expect("negative-only actual driver");
    let ended=terminal(&mut driver).await;assert_eq!(ended.outcome(),SavedSendOutcome::Cancelled);
    assert!(!c.scoped_send_observation.as_ref().expect("same observation").lock().expect("observation").attempted);
    let d=c.finish_owned_saved_send(ended).expect("actual original terminal continuation");
    assert!(d.can_continue_parent());assert!(d.original_turn_settled());assert!(d.original_cancelled_result());
    assert!(matches!(d.recovery_identity(&c).expect("guarded identity"),None));
    assert_eq!(c.operation_parent,parent);assert_eq!(c.operation_cancel,ordinary);assert!(!ordinary.is_cancelled());
    d.check_current(&c).expect("actual terminal proof current");d.publication_guard().check_release().expect("separate terminal guard");
    assert!(old.check_release().is_err(),"old live guard never borrows continuation child");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn abandoned_actual_phase_must_drain_original_future_before_parent_continuation(){
    let mut c=client();let(updates,_)=mpsc::channel(4);
    let prepared=c.prepare_owned_saved_send(None,CancellationToken::new()).expect("actual original preparation");
    let mut driver=c.start_owned_saved_send(prepared,"private",updates).expect("actual driver");
    let step=match driver.drive_next().await.expect("actual Prepare command") {OwnedSavedSendStep::Apply(step)=>step,_=>panic!("actual preparation phase required")};
    assert!(matches!(driver.drive_next().await,Err(Error::Conflict)),"outstanding phase is not a terminal");
    assert!(matches!(c.prepare_owned_saved_send(None,CancellationToken::new()),Err(Error::Conflict)),"no successor while driver owns phase");
    drop(step);
    let ended=terminal(&mut driver).await;assert_eq!(ended.outcome(),SavedSendOutcome::Cancelled);
    assert!(!c.scoped_send_observation.as_ref().expect("same observation").lock().expect("observation").attempted);
    let d=c.finish_owned_saved_send(ended).expect("actual returned future continuation");assert!(d.can_continue_parent());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn foreign_client_cannot_apply_original_phase_even_with_equal_credentials(){
    let mut a=client();let mut b=client();let(updates,_)=mpsc::channel(4);
    let prepared=a.prepare_owned_saved_send(None,CancellationToken::new()).expect("original A");
    let mut driver=a.start_owned_saved_send(prepared,"private",updates).expect("actual A driver");
    let step=match driver.drive_next().await.expect("actual A phase"){OwnedSavedSendStep::Apply(step)=>step,_=>panic!("A phase")};
    assert!(matches!(b.apply_owned_saved_send_step(step).await,Err(Error::Cancelled)),"same values cannot replace original Client/resource");
    assert!(b.scoped_send_observation.is_none());assert!(!b.operation_parent.is_cancelled());
    let ended=terminal(&mut driver).await;assert_eq!(ended.outcome(),SavedSendOutcome::Cancelled);
    a.finish_owned_saved_send(ended).expect("only original A can consume actual terminal");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn stale_original_control_and_disposition_drop_do_not_retire_successor(){
    let mut c=client();let ordinary=c.operation_cancel.clone();let parent=c.operation_parent.clone();
    let request=CancellationToken::new();let prepared=c.prepare_owned_saved_send(None,request.clone()).expect("actual A");
    request.cancel();let(updates,_)=mpsc::channel(4);let mut a=c.start_owned_saved_send(prepared,"A",updates).expect("A driver");
    let stale=a.control();let ended=terminal(&mut a).await;let d=c.finish_owned_saved_send(ended).expect("actual A drained");
    let prepared=c.prepare_owned_saved_send(None,CancellationToken::new()).expect("new explicit B");
    let bchild=prepared.current().expect("actual B admission").scope.child();let(updates,_)=mpsc::channel(4);
    let mut b=c.start_owned_saved_send(prepared,"B",updates).expect("actual B driver");
    stale.cancel();drop(d);drop(a);
    assert!(!bchild.is_cancelled());assert!(!parent.is_cancelled());assert!(!ordinary.is_cancelled());
    let phase=match b.drive_next().await.expect("B still owns its original phase"){OwnedSavedSendStep::Apply(p)=>p,_=>panic!("B Prepare phase")};
    drop(phase);let ended=terminal(&mut b).await;c.finish_owned_saved_send(ended).expect("B actual terminal remains consumable");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn true_parent_retirement_cannot_be_rearmed_by_actual_child_terminal(){
    let mut c=client();let request=CancellationToken::new();let prepared=c.prepare_owned_saved_send(None,request.clone()).expect("original");
    request.cancel();let(updates,_)=mpsc::channel(4);let mut driver=c.start_owned_saved_send(prepared,"private",updates).expect("negative driver");
    let ended=terminal(&mut driver).await;c.operation_parent.cancel();
    assert!(matches!(c.finish_owned_saved_send(ended),Err(Error::Cancelled)));
    assert!(c.operation_parent.is_cancelled());assert!(c.prepare_owned_saved_send(None,CancellationToken::new()).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn consumed_terminal_guard_survives_driver_drop_but_not_parent_retirement(){
    let mut c=client();let request=CancellationToken::new();let prepared=c.prepare_owned_saved_send(None,request.clone()).expect("actual A");
    request.cancel();let(updates,_)=mpsc::channel(4);let mut driver=c.start_owned_saved_send(prepared,"A",updates).expect("actual driver");
    let ended=terminal(&mut driver).await;let d=c.finish_owned_saved_send(ended).expect("actual consumed terminal");
    let final_guard=d.publication_guard();drop(d);drop(driver);
    final_guard.check_release().expect("actual terminal publication does not depend on disposed scheduling wrapper");
    c.operation_parent.cancel();assert!(final_guard.check_release().is_err());
}
