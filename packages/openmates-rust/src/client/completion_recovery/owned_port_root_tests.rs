//! Actual browser profile and genuine stage fixture; negative Root binding is
//! not native-port/IDB execution or a foreground/read/durability grant.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test;
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_browser_root_survives_real_auth_and_ordinary_child_cancel_without_granting_foreground(){
    let(mut c,_pending,_server)=genuine_pending_for_test().await;let root=c.capture_browser_recovery_port_root().unwrap();c.validate_session().await.unwrap();root.check_original(&c).unwrap();
    c.operation_cancel.cancel();root.check_original(&c).unwrap();c.set_foreground_completion_recovery(false).unwrap();root.check_original(&c).unwrap();assert!(c.completion_recovery_mode.is_none());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn same_owner_genuine_peer_cannot_adopt_original_browser_port_root(){
    let(a,_pa,_sa)=genuine_pending_for_test().await;let(b,_pb,_sb)=genuine_pending_for_test().await;let root=a.capture_browser_recovery_port_root().unwrap();root.check_original(&a).unwrap();assert!(root.check_original(&b).is_err());root.check_original(&a).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn original_gate_cancelling_actual_parent_while_ok_is_rechecked_before_port_release(){
    let(mut c,_pending,_server)=genuine_pending_for_test().await;let armed=Arc::new(AtomicBool::new(false));let trigger=armed.clone();let parent=c.operation_parent.clone();c.set_private_operation_gate(Some(Arc::new(move||{if trigger.load(Ordering::Acquire){parent.cancel();}Ok(())})));
    let root=c.capture_browser_recovery_port_root().unwrap();armed.store(true,Ordering::Release);assert!(root.check_release().is_err());assert!(root.check_negative().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn bootstrap_fields_only_restrict_actual_root_and_never_replace_its_original_identity(){
    let(c,_pending,_server)=genuine_pending_for_test().await;let root=c.capture_browser_recovery_port_root().unwrap();let credentials=c.require_credentials().unwrap();let principal=super::super::super::owner(&c).unwrap();
    root.check_bootstrap(c.base.as_str(),credentials.session_id,&principal).unwrap();assert!(root.check_bootstrap(c.base.as_str(),credentials.session_id,"33333333-3333-4333-8333-333333333333").is_err());assert!(root.check_bootstrap("https://example.invalid",credentials.session_id,&principal).is_err());root.check_original(&c).unwrap();
    c.operation_parent.cancel();assert!(root.check_bootstrap(c.base.as_str(),credentials.session_id,&principal).is_err());
}
