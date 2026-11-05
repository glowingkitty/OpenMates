//! Actual terminal witness and actual captured caller gate; no storage proof
//! double. Native port/IDB positive path requires actual browser CI separately.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_terminal_with_gate_for_test;
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn final_callback_free_witness_check_refuses_real_original_control_cancelled_by_actual_gate_while_ok(){
    let token=Arc::new(Mutex::new(None::<CancellationToken>));let target=token.clone();let gate=Arc::new(move||{if let Some(token)=target.lock().unwrap().as_ref(){token.cancel();}Ok(())});
    let(client,handoff,result,_server)=genuine_terminal_with_gate_for_test(gate).await;result.check_original(&client).unwrap();let(_receipt,witness,_artifacts)=result.into_witnessed_parts().unwrap();
    witness.check_original_negative().unwrap();*token.lock().unwrap()=Some(witness.context.cancel.clone());client.verify_private_operation().unwrap();
    assert!(witness.check_original_negative().is_err());handoff.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());
}
