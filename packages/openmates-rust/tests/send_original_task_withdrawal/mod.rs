//! Actual socket regression: a known Content A is stopped through its original
//! operation child, while the separate receive-caller token remains live. The
//! peer then releases one actual frame so the old scope-error exit is reached.
//! No synthetic terminal, sleep, fake Rust, current-chat selector or account IO.
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
use super::*;
use futures_util::{SinkExt,StreamExt};
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
use tokio_tungstenite::tungstenite::Message as Frame;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const TURN:&str="33333333-3333-4333-8333-333333333333";
const MESSAGE:&str="44444444-4444-4444-8444-444444444444";
const TASK:&str="55555555-5555-4555-8555-555555555555";
const DEADLINE:Duration=Duration::from_secs(3);
async fn emit(ws:&mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,kind:&str,payload:Value){
    ws.send(Frame::Text(json!({"type":kind,"payload":payload}).to_string().into())).await.unwrap();
}
async fn exercise(revoke_parent_inside_gate:bool){
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address=listener.local_addr().unwrap();
    let(release_late,mut wait_late)=tokio::sync::oneshot::channel::<()>();
    let peer=tokio::spawn(async move{
        let(stream,_)=listener.accept().await.unwrap();let mut ws=tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut effects=vec![];
        while let Some(raw)=ws.next().await {
            let raw=raw.unwrap();if matches!(raw,Frame::Close(_)){return effects}
            let event:Value=serde_json::from_str(&raw.into_text().unwrap()).unwrap();
            let kind=event["type"].as_str().unwrap();effects.push(event.clone());
            match kind {
                "set_active_chat"=>assert_eq!(event["payload"]["chat_id"],CHAT),
                "personal_send_context_snapshot"=>{
                    assert_eq!(event["payload"]["turn_id"],TURN);
                    emit(&mut ws,"personal_send_context_snapshot_result",json!({"success":true,"unchanged":false,
                        "request_id":event["payload"]["request_id"],"turn_id":TURN,"receipt_id":"fixture-receipt",
                        "privacy_generation":1,"project_candidates":[],"personal_memories":{"memories":[]}})).await;
                },
                "chat_turn_admit"=>{
                    assert_eq!(event["payload"]["chat_id"],CHAT);assert_eq!(event["payload"]["turn_id"],TURN);
                    assert_eq!(event["payload"]["message_id"],MESSAGE);
                    emit(&mut ws,"chat_turn_preflight_ack",json!({"turn_id":TURN,"preflight_id":"fixture-preflight","committed_messages_v":1})).await;
                    emit(&mut ws,"chat_message_confirmed",json!({"chat_id":CHAT,"message_id":MESSAGE,"new_messages_v":1})).await;
                    emit(&mut ws,"ai_task_initiated",json!({"chat_id":CHAT,"user_message_id":MESSAGE,"task_id":TASK})).await;
                    emit(&mut ws,"ai_message_update",json!({"chat_id":CHAT,"user_message_id":MESSAGE,"task_id":TASK,"full_content_so_far":"first","is_final_chunk":false})).await;
                    (&mut wait_late).await.expect("actual Content observed before original child stop");
                    emit(&mut ws,"ai_message_update",json!({"chat_id":CHAT,"user_message_id":MESSAGE,"task_id":TASK,"full_content_so_far":"late","is_final_chunk":false})).await;
                },
                "cancel_ai_task"=>{
                    assert_eq!(event["payload"]["task_id"],TASK);assert_eq!(event["payload"]["chat_id"],CHAT);
                },
                _=>panic!("unexpected protocol effect"),
            }
        }
        panic!("socket must close explicitly after actual operation terminal")
    });
    let(inner,_)=tokio_tungstenite::connect_async(format!("ws://{address}")).await.unwrap();
    let mut socket=transport::test_socket(inner);let api="https://api.example.invalid";
    let mut client=Client::new(api,Some(Session{api_url:api.into(),session_id:MESSAGE.into(),cookies:Default::default(),
        ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture-owner".into(),
        user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
    client.user=json!({"id":OWNER});
    let original_parent=client.operation_parent.clone();let stopped_child=client.operation_cancel.clone();
    let armed=Arc::new(AtomicBool::new(false));let callback_armed=armed.clone();let gate_parent=original_parent.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{
        if revoke_parent_inside_gate&&callback_armed.load(Ordering::Acquire){gate_parent.cancel();}Ok(())
    })));
    let caller_cancel=CancellationToken::new();let key=[9;32];let wrapped=crypto::encrypt_bytes(&key,&[7;32]).unwrap();
    let mut chat=Chat{id:CHAT.into(),..Default::default()};let(updates,mut receive_updates)=mpsc::channel(16);
    let options=SendOptions{pii_detection:false,task_update_jobs:false,response_timeout_ms:Some(2_000),..Default::default()};
    let generation=client.generation;let mut trace=SendTrace::new();
    let mut operation=Box::pin(client.send_on_socket(&mut socket,CHAT,TURN,MESSAGE,"fixture input",&key,&wrapped,0,true,&[],
        &mut chat,&updates,&caller_cancel,generation,None,&options,&mut trace));
    let result=tokio::time::timeout(DEADLINE,async{
        loop {
            tokio::select!{biased;
                result=operation.as_mut()=>panic!("operation ended before actual Content: {:?}",result.err()),
                event=receive_updates.recv()=>if let Some(StreamUpdate::Content{content,..})=event {
                    assert_eq!(content,"first");break;
                },
            }
        }
        // Keep caller_cancel live, ensuring old select(cancel) cannot mask the
        // precise later frame-validation failure caused by the original child.
        armed.store(true,Ordering::Release);stopped_child.cancel();assert!(!caller_cancel.is_cancelled());
        release_late.send(()).unwrap();operation.as_mut().await
    }).await.expect("terminal watchdog only");
    assert!(matches!(result,Err(Error::Cancelled)));drop(operation);receive_updates.close();
    while let Ok(update)=receive_updates.try_recv(){assert!(!matches!(update,StreamUpdate::Completed{..}));}
    let _=socket.close(None).await;
    let effects=tokio::time::timeout(DEADLINE,peer).await.expect("peer terminal watchdog").unwrap();
    assert_eq!(effects.iter().filter(|event|event["type"]=="chat_turn_admit").count(),1);
    assert_eq!(effects.iter().filter(|event|event["type"]=="cancel_ai_task").count(),usize::from(!revoke_parent_inside_gate));
    assert!(!effects.iter().any(|event|event["type"]=="recovery_job_persist"));
    assert_eq!(original_parent.is_cancelled(),revoke_parent_inside_gate);
    assert!(chat.messages.is_empty(),"no local stop can claim the uncertain turn settled");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn known_original_task_is_withdrawn_once_after_content_scope_failure(){exercise(false).await;}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn gate_returning_ok_after_root_revocation_cannot_dispatch_withdrawal(){exercise(true).await;}
