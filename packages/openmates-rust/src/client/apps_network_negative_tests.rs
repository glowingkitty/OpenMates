//! Actual concurrent header/body driver against a bounded real loopback server.
//! Tests are authored for isolated CI; no local product execution is claimed.
use super::*;
use std::sync::{Arc, atomic::{AtomicBool, AtomicUsize, Ordering}};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
fn client(endpoint:&str)->Client {
    let session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic-network-session","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut c=Client::new(endpoint,Some(session)).unwrap();c.user=json!({"id":"synthetic-owner"});c
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test]
async fn concurrent_header_gate_success_cannot_dispatch_after_original_parent_child_or_denial_retirement() {
    for mode in ["allow","parent","child","denial","strict-transport-cancel"] {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint=format!("http://{}",listener.local_addr().unwrap());
        let (stop,mut shutdown)=tokio::sync::oneshot::channel::<()>();
        let observed=Arc::new(AtomicUsize::new(0));let requests=observed.clone();
        let server=tokio::spawn(async move {
            loop {
                // Drain an already queued accept before shutdown. There is no
                // elapsed-time-based assertion that no request was dispatched.
                let accepted=tokio::select!{biased;accepted=listener.accept()=>Some(accepted.unwrap()),_= &mut shutdown=>None};
                let Some((mut socket,_))=accepted else {break};
                let mut header=Vec::new();let mut byte=[0u8;1];
                while !header.ends_with(b"\r\n\r\n") {
                    assert!(header.len()<8192);assert_eq!(socket.read(&mut byte).await.unwrap(),1);header.push(byte[0]);
                }
                assert!(header.starts_with(b"GET /v1/tasks/original-task HTTP/1.1\r\n"));
                requests.fetch_add(1,Ordering::SeqCst);
                let body=r#"{"task_id":"original-task","status":"completed","result":{"allowed":true}}"#;
                let response=format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body);
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        let mut c=client(&endpoint);let parent=CancellationToken::new();c.set_operation_cancel(parent.clone());
        let child=c.current_operation_child();let authority=c.task_watch_authority.clone();
        let armed=Arc::new(AtomicBool::new(false));let trigger=armed.clone();
        let calls=Arc::new(AtomicUsize::new(0));let count=calls.clone();
        c.set_private_operation_gate(Some(Arc::new(move || {
            count.fetch_add(1,Ordering::SeqCst);
            if trigger.swap(false,Ordering::SeqCst) {
                match mode {"parent"=>parent.cancel(),"child"=>child.cancel(),"denial"=>authority.deny_cached_chat(None)?,_=>{}}
            }
            Ok(()) // Real negative mutation while the caller callback succeeds.
        })));
        let original=c.direct_app_skill_admission().unwrap();
        let prepared=c.prepare_owned_read(transport::OwnedReadRoute::AppTask("original-task")).unwrap();
        // The explicit transport token is intentionally independent: the
        // original admission must retain its own parent/child even if IO has
        // a still-live cancellation token. Denial also fails with a shared token.
        let transport_cancel=if mode=="denial" {c.current_operation_child()}else{CancellationToken::new()};
        if mode=="strict-transport-cancel" {transport_cancel.cancel();}
        calls.store(0,Ordering::SeqCst);armed.store(true,Ordering::SeqCst);
        let budget=transport::OwnedReadByteBudget::new(transport::MAX_BODY);
        let event=tokio::time::timeout(Duration::from_secs(10),drive_app_poll_read(AppPollReadStep::Headers{index:0,prepared},&transport_cancel,&original,&budget)).await.expect("header driver deadlock watchdog");
        assert_eq!(calls.load(Ordering::SeqCst),1,"one original gate before dispatch");
        let AppPollReadEvent::Headers{index:0,result}=event else {panic!("wrong concurrent driver event")};
        if mode=="allow" {
            let head=result.unwrap();let body=c.apply_owned_read_headers(head).unwrap();
            let event=tokio::time::timeout(Duration::from_secs(10),drive_app_poll_read(AppPollReadStep::Body{index:0,body},&transport_cancel,&original,&budget)).await.expect("body driver deadlock watchdog");
            let AppPollReadEvent::Body{index:0,result}=event else {panic!("wrong body event")};
            let value=c.finish_owned_read(result.unwrap()).unwrap().unwrap();
            assert_eq!(value["result"]["allowed"],true);
        } else {assert!(matches!(result,Err(Error::Cancelled)|Err(Error::Forbidden)),"original negative must refuse before GET");}
        let _=stop.send(());tokio::time::timeout(Duration::from_secs(10),server).await.expect("server shutdown watchdog").unwrap();
        assert_eq!(observed.load(Ordering::SeqCst),usize::from(mode=="allow"));
    }
}
