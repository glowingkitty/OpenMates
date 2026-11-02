//! Authored UNRUN actual loopback saved-send socket failure. The peer closes
//! TCP during the original preparation read; no lifecycle/completion flag is
//! written by the test, and no saved-turn admission/inference is sent.
use super::*;
use futures_util::StreamExt;
use tokio::io::{AsyncRead,AsyncReadExt,AsyncWrite,AsyncWriteExt};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
struct Server {base:String,stop:CancellationToken,task:tokio::task::JoinHandle<()>}
impl Drop for Server {fn drop(&mut self){self.stop.cancel();self.task.abort();}}
impl Server {
    async fn open()->Self {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());let stop=CancellationToken::new();let stopped=stop.clone();
        let task=tokio::spawn(async move{loop{
            let(stream,_)=tokio::select!{_=stopped.cancelled()=>break,value=listener.accept()=>value.unwrap()};
            tokio::spawn(async move{
                let mut stream=stream;let mut header=Vec::new();while !header.ends_with(b"\r\n\r\n"){let mut byte=[0];stream.read_exact(&mut byte).await.unwrap();header.push(byte[0]);assert!(header.len()<65536);}
                let raw=String::from_utf8(header).unwrap();
                if raw.to_ascii_lowercase().contains("upgrade: websocket") {
                    // Replay the actual handshake bytes already read by this
                    // HTTP/WS fixture, without a hidden endpoint or socket swap.
                    let buffered=Replay{header:raw.into_bytes(),offset:0,stream};let mut ws=tokio_tungstenite::accept_async(buffered).await.unwrap();
                    loop {let frame=ws.next().await.unwrap().unwrap();let value:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();let kind=value["type"].as_str().unwrap();
                        match kind {"native_client_lifecycle"|"set_active_chat"=>{},"personal_send_context_snapshot"=>break,_=>panic!("unexpected saved-send fixture frame {kind}")}
                    }
                    // Abrupt actual transport EOF: original receive returns an
                    // error, and closing its already-failed stream must fail.
                    drop(ws);return;
                }
                assert!(raw.starts_with("POST /v1/auth/session "));let len=raw.lines().filter_map(|line|line.split_once(':')).find(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap()).unwrap_or(0);assert!(len<65536);let mut body=vec![0;len];stream.read_exact(&mut body).await.unwrap();
                let body=serde_json::to_vec(&json!({"success":true,"ws_token":"synthetic-saved-send-token","user":{"id":OWNER},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]})).unwrap();
                stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).as_bytes()).await.unwrap();stream.write_all(&body).await.unwrap();
            });
        }});Self{base,stop,task}
    }
    async fn client(&self)->Client {
        let mut client=Client::new(&self.base,Some(Session{api_url:self.base.clone(),session_id:"synthetic-saved-send".into(),cookies:Default::default(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic-hash".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
        client.validate_session().await.unwrap();client
    }
}
struct Replay {header:Vec<u8>,offset:usize,stream:tokio::net::TcpStream}
impl tokio::io::AsyncRead for Replay {
    fn poll_read(mut self:std::pin::Pin<&mut Self>,cx:&mut std::task::Context<'_>,out:&mut tokio::io::ReadBuf<'_>)->std::task::Poll<std::io::Result<()>>{
        if self.offset<self.header.len(){let n=out.remaining().min(self.header.len()-self.offset);out.put_slice(&self.header[self.offset..self.offset+n]);self.offset+=n;std::task::Poll::Ready(Ok(()))}else{std::pin::Pin::new(&mut self.stream).poll_read(cx,out)}
    }
}
impl tokio::io::AsyncWrite for Replay {
    fn poll_write(mut self:std::pin::Pin<&mut Self>,cx:&mut std::task::Context<'_>,value:&[u8])->std::task::Poll<std::io::Result<usize>>{std::pin::Pin::new(&mut self.stream).poll_write(cx,value)}
    fn poll_flush(mut self:std::pin::Pin<&mut Self>,cx:&mut std::task::Context<'_>)->std::task::Poll<std::io::Result<()>>{std::pin::Pin::new(&mut self.stream).poll_flush(cx)}
    fn poll_shutdown(mut self:std::pin::Pin<&mut Self>,cx:&mut std::task::Context<'_>)->std::task::Poll<std::io::Result<()>>{std::pin::Pin::new(&mut self.stream).poll_shutdown(cx)}
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn peer_closed_original_socket_counts_as_returned_and_mints_a_terminal_unless_observation_is_corrupt(){
    for corrupt in [false,true] {
        let server=Server::open().await;let mut client=server.client().await;let peer=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let prepared=client.prepare_owned_saved_send(None,CancellationToken::new()).unwrap();let(updates,_)=mpsc::channel(8);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();
        let OwnedSavedSendStep::Apply(phase)=driver.drive_next().await.unwrap()else{panic!("actual original Prepare")};let resume=tokio::time::timeout(std::time::Duration::from_secs(5),client.apply_owned_saved_send_step(phase)).await.unwrap().unwrap();driver.resume(resume).unwrap();
        assert!(driver.context.socket.get().is_some(),"actual original transport must have registered");
        if corrupt {let observation=client.scoped_send_observation.as_ref().unwrap().clone();let _=std::panic::catch_unwind(std::panic::AssertUnwindSafe(||{let _held=observation.lock().unwrap();panic!("synthetic observation lock failure");}));}
        let step=tokio::time::timeout(std::time::Duration::from_secs(5),driver.drive_next()).await.unwrap();
        assert!(driver.context.transport_resources_tracked.load(std::sync::atomic::Ordering::Acquire));
        // The peer already closed the stream, which releases it (SDK lane fix):
        // closing reports ConnectionClosed/AlreadyClosed, never a lost resource.
        assert!(driver.context.socket_returned.load(std::sync::atomic::Ordering::Acquire),"a peer-closed socket is returned");
        if corrupt {
            assert!(matches!(step,Err(Error::Cancelled)));assert!(driver.take_returned_refusal().is_some(),"corrupt observation refuses explicitly");
        } else {
            let Ok(OwnedSavedSendStep::Terminal(ended))=step else{panic!("returned resources mint the actual terminal")};
            assert_eq!(ended.outcome(),SavedSendOutcome::Unavailable,"never attempted, not cancelled");
            client.finish_owned_saved_send(ended).expect("original client consumes its terminal");
        }
        peer.check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());assert!(!client.operation_cancel.is_cancelled());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_before_attempt_is_a_cancellation_and_never_blocks_the_next_send(){
    let server=Server::open().await;let mut client=server.client().await;let request=CancellationToken::new();
    let prepared=client.prepare_owned_saved_send(None,request.clone()).unwrap();let(updates,_)=mpsc::channel(8);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();
    let OwnedSavedSendStep::Apply(phase)=driver.drive_next().await.unwrap()else{panic!("actual original Prepare")};let resume=tokio::time::timeout(std::time::Duration::from_secs(5),client.apply_owned_saved_send_step(phase)).await.unwrap().unwrap();driver.resume(resume).unwrap();
    // Cancelled while the context snapshot is outstanding; the transport then fails.
    request.cancel();
    let Ok(OwnedSavedSendStep::Terminal(ended))=tokio::time::timeout(std::time::Duration::from_secs(5),driver.drive_next()).await.unwrap()else{panic!("actual terminal")};
    assert_eq!(ended.outcome(),SavedSendOutcome::Cancelled);
    let disposition=client.finish_owned_saved_send(ended).expect("original terminal");assert!(disposition.original_cancelled_result());drop(disposition);drop(driver);
    assert!(client.prepare_owned_saved_send(None,CancellationToken::new()).is_ok(),"a cancelled send must not refuse the next one");
}
