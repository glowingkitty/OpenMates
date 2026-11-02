//! Genuine MAIN admission through actual outer driver and nested canonical HTTP.
//! No manufactured CanonicalRun/Apply/Boundary, receipt or cancellation flags.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_main_handoff_for_test;
use tokio::time::{timeout,Duration};
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_outer_main_cancel_after_nested_headers_keeps_cookie_and_denies_body_socket_and_result(){
    let(mut client,handoff,server)=genuine_main_handoff_for_test().await;client.set_foreground_completion_recovery(true).unwrap();let scope=handoff.scope_arc();
    let mut driver=client.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();let control=driver.control();let mut canonical_io=0;let mut cancelled=false;
    let result:Result<()>=timeout(Duration::from_secs(10),async{for _ in 0..300{match driver.next().await{
        Ok(OwnedRecoveryStep::Apply(phase))=>{driver.resume(phase.apply(&mut client)?)?;},
        Ok(OwnedRecoveryStep::Io(io))=>{
            if io.stage_name_for_test()=="canonical"{
                canonical_io+=1;
                if canonical_io==2{server.rotate_next_metadata_headers_for_test();}
            }
            let resume=io.drive().await?;
            if canonical_io==2&&!cancelled{control.cancel();cancelled=true;}
            driver.resume(resume)?;
        }
        Ok(_)=>return Err(Error::Protocol),Err(error)=>return Err(error),
    }}Err(Error::Protocol)}).await.unwrap();
    assert!(cancelled);assert_eq!(canonical_io,2);assert!(matches!(result,Err(Error::Cancelled)));
    assert_eq!(client.browser_credentials.as_ref().unwrap().cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-canonical-header-rotation"));
    assert_eq!(server.socket_count_for_test(),0);assert!(!client.operation_parent.is_cancelled());scope.check(&client).unwrap();
}
