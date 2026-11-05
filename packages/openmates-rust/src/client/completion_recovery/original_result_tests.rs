//! Authored UNRUN actual foreground HTTP/WS + existing browser-profile restore.
//! No fake Session/status/receipt or Rust substitute. Server data is synthetic;
//! this is not production backend/IDB/monitor connection reuse acceptance proof.
use super::*;
use crate::client::completion_recovery::{OriginalForegroundRecoveryAdmission,OriginalForegroundRecoveryResult};
use futures_util::{SinkExt,StreamExt};
use std::{pin::Pin,task::{Context,Poll},sync::{Arc,atomic::{AtomicUsize,Ordering}}};
use tokio::io::{AsyncRead,AsyncReadExt,AsyncWrite,AsyncWriteExt,ReadBuf};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const JOB:&str="33333333-3333-4333-8333-333333333333";
const TASK:&str="44444444-4444-4444-8444-444444444444";
struct Replay {header:Vec<u8>,offset:usize,stream:tokio::net::TcpStream}
impl AsyncRead for Replay {
    fn poll_read(mut self:Pin<&mut Self>,cx:&mut Context<'_>,out:&mut ReadBuf<'_>)->Poll<std::io::Result<()>>{
        if self.offset<self.header.len(){let n=out.remaining().min(self.header.len()-self.offset);out.put_slice(&self.header[self.offset..self.offset+n]);self.offset+=n;Poll::Ready(Ok(()))}
        else{Pin::new(&mut self.stream).poll_read(cx,out)}
    }
}
impl AsyncWrite for Replay {
    fn poll_write(mut self:Pin<&mut Self>,cx:&mut Context<'_>,bytes:&[u8])->Poll<std::io::Result<usize>>{Pin::new(&mut self.stream).poll_write(cx,bytes)}
    fn poll_flush(mut self:Pin<&mut Self>,cx:&mut Context<'_>)->Poll<std::io::Result<()>>{Pin::new(&mut self.stream).poll_flush(cx)}
    fn poll_shutdown(mut self:Pin<&mut Self>,cx:&mut Context<'_>)->Poll<std::io::Result<()>>{Pin::new(&mut self.stream).poll_shutdown(cx)}
}
struct Server {base:String,requests:Arc<AtomicUsize>,sockets:Arc<AtomicUsize>,stop:CancellationToken,task:tokio::task::JoinHandle<()>}
fn job()->CompletionRecoveryJob{CompletionRecoveryJob{kind:CompletionRecoveryKind::Metadata,job_id:JOB.into(),chat_id:CHAT.into(),turn_id:None,assistant_message_id:None,task_id:Some(TASK.into()),stage:Some("initial".into()),chat_key_version:1,created_at:None}}
impl Server {
    async fn open()->Self{
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
        let requests=Arc::new(AtomicUsize::new(0));let sockets=Arc::new(AtomicUsize::new(0));let stop=CancellationToken::new();
        let(stop_task,count,ws_count)=(stop.clone(),requests.clone(),sockets.clone());
        let task=tokio::spawn(async move{loop{
            let(stream,_)=tokio::select!{_=stop_task.cancelled()=>break,accepted=listener.accept()=>accepted.unwrap()};
            let(count,ws_count)=(count.clone(),ws_count.clone());
            tokio::spawn(async move{
                let mut stream=stream;let mut header=Vec::new();
                while !header.ends_with(b"\r\n\r\n"){let mut byte=[0];stream.read_exact(&mut byte).await.unwrap();header.push(byte[0]);assert!(header.len()<=65536);}
                let text=String::from_utf8(header.clone()).unwrap();let line=text.lines().next().unwrap();
                if text.to_ascii_lowercase().contains("upgrade: websocket"){
                    assert!(line.starts_with("GET /v1/ws?"));assert!(line.contains("chat_metadata_recovery"));ws_count.fetch_add(1,Ordering::SeqCst);
                    let mut ws=tokio_tungstenite::accept_async(Replay{header,offset:0,stream}).await.unwrap();
                    let frame=ws.next().await.unwrap().unwrap();let value:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();assert_eq!(value["type"],"native_client_lifecycle");assert_eq!(value["payload"]["is_foreground"],true);
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"native_client_lifecycle_ack","payload":{"is_foreground":true}}).to_string().into())).await.unwrap();
                    let frame=ws.next().await.unwrap().unwrap();let value:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();assert_eq!(value["type"],"metadata_job_claim");let request=&value["payload"];assert_eq!(request["job_id"],JOB);assert_eq!(request["protocol_version"],1);
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"metadata_job_claimed","payload":{"request_id":request["request_id"],"job_id":JOB,"chat_id":CHAT,"task_id":TASK,"stage":"initial","chat_key_version":1,"state":"TERMINAL"}}).to_string().into())).await.unwrap();
                    // Actual foreground socket may close after canonical result;
                    // never synthesize an original monitor/hint completion here.
                    while let Some(frame)=ws.next().await{match frame{Ok(tokio_tungstenite::tungstenite::Message::Close(_))|Err(_)=>break,_=>{}}}
                    return;
                }
                count.fetch_add(1,Ordering::SeqCst);
                let length=text.lines().filter_map(|line|line.split_once(':')).find(|(key,_)|key.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap()).unwrap_or(0);assert!(length<65536);let mut body=vec![0;length];stream.read_exact(&mut body).await.unwrap();
                let response=if line.contains(" /v1/auth/session "){json!({"success":true,"ws_token":"synthetic-foreground-token","user":{"id":OWNER},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]})}
                else{assert!(line.contains(" /v1/chats/metadata/batch "));let body:Value=serde_json::from_slice(&body).unwrap();assert_eq!(body["chat_ids"],json!([CHAT]));
                    let key=crypto::server_fields::encrypt_bytes(&[9;32],&[7;32],&[]).unwrap();json!({"chats":[{"id":CHAT,"user_id":OWNER,"encrypted_chat_key":key,"metadata_v":1,"title_v":1,"messages_v":0}]})};
                let body=serde_json::to_vec(&response).unwrap();let response=format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",body.len());stream.write_all(response.as_bytes()).await.unwrap();stream.write_all(&body).await.unwrap();
            });
        }});Self{base,requests,sockets,stop,task}
    }
    async fn client(&self)->Client{
        let profile=crate::client::BrowserProfileKey::from_existing_profile(OWNER,zeroize::Zeroizing::new([7;32]),"synthetic-hash","synthetic-salt",crate::client::BrowserPersistence::MemoryOnly).unwrap();
        let c=Client::restore_browser_credentials_inner(&self.base,"http://localhost:5173",OWNER,profile).await.unwrap();assert!(c.session.is_none());assert!(c.browser_credentials.is_some());c
    }
}
impl Drop for Server{fn drop(&mut self){self.stop.cancel();self.task.abort();}}
async fn sealed(server:&Server,c:&mut Client,cancel:&CancellationToken)->OriginalForegroundRecoveryResult{
    c.set_foreground_completion_recovery(true).unwrap();let admission=c.stage_hint_completion_recovery(&job(),cancel).await.unwrap();
    let OriginalForegroundRecoveryAdmission::Canonical(result)=admission else{panic!("actual canonical metadata claim required")};
    assert_eq!(server.sockets.load(Ordering::SeqCst),1);result
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_foreground_terminal_result_remains_original_owner_mode_root_and_caller_fenced(){
    for revocation in ["mode","root","caller","denial"]{
        let server=Server::open().await;let mut c=server.client().await;let foreign=server.client().await;let cancel=CancellationToken::new();let result=sealed(&server,&mut c,&cancel).await;
        result.check_original(&c).unwrap();assert!(result.check_original(&foreign).is_err());assert_eq!(result.job().chat_id,CHAT);assert_eq!(result.job().job_id,JOB);
        match revocation{"mode"=>c.set_foreground_completion_recovery(false).unwrap(),"root"=>c.operation_parent.cancel(),"caller"=>cancel.cancel(),_=>c.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap()}
        assert!(result.check_original(&c).is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn genuine_foreground_result_preserves_existing_public_dto_without_accepting_dto_as_proof(){
    let server=Server::open().await;let mut c=server.client().await;c.set_foreground_completion_recovery(true).unwrap();let cancel=CancellationToken::new();
    let CompletionRecoveryAdmission::Canonical(dto)=c.stage_completion_recovery(&job(),&cancel).await.unwrap()else{panic!("old actual public API canonical result")};
    assert_eq!(serde_json::to_value(&dto).unwrap(),json!({"job_id":JOB,"chat_id":CHAT,"assistant_message_id":null,"messages_version":null,"metadata_version":1,"title_version":1,"state":"TERMINAL"}));
    // Serialization remains DATA. There is deliberately no from_receipt or
    // deserialization entry point on OriginalForegroundRecoveryResult.
    let copied:CompletionRecoveryReceipt=serde_json::from_value(serde_json::to_value(dto).unwrap()).unwrap();assert_eq!(copied.job_id,JOB);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn explicit_foreground_mode_is_required_before_any_actual_recovery_network_or_socket(){
    let server=Server::open().await;let mut c=server.client().await;let before=server.requests.load(Ordering::SeqCst);
    let result=c.stage_hint_completion_recovery(&job(),&CancellationToken::new()).await;
    assert!(matches!(result,Err(Error::Unavailable{code:"completion_recovery_unavailable",..})));assert_eq!(server.requests.load(Ordering::SeqCst),before);assert_eq!(server.sockets.load(Ordering::SeqCst),0);
}
