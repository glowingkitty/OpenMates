//! Pure fixed-route/resource-negative tests. No auth, socket or account is executed.
use super::*;
fn client()->Client {
    let mut client=Client::new("https://example.invalid",Some(Session{api_url:"https://example.invalid".into(),session_id:"fixture".into(),
        cookies:BTreeMap::new(),ws_token:Some("fixture".into()),master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),
        email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("fixture");
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
}
fn scope(client:&Client)->Arc<owned_operation::OwnedOperationScope>{Arc::new(owned_operation::OwnedOperationScope::capture(client,CancellationToken::new()).expect("original"))}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn owned_recovery_socket_cannot_invent_foreground_or_validate_auth_by_label(){
    let mut client=client();let original=scope(&client);
    assert!(client.begin_owned_completion_recovery_socket(original.clone()).is_err());
    assert!(client.completion_recovery_mode.is_none());
    client.set_foreground_completion_recovery(true).expect("explicit");
    let prepared=client.begin_owned_completion_recovery_socket(original).expect("original");
    assert!(prepared.needs_validation());
    assert!(prepared.prepare(&mut client,None).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn retired_original_mode_never_adopts_reenabled_foreground(){
    let mut client=client();client.set_foreground_completion_recovery(true).expect("explicit");
    let original=scope(&client);let prepared=client.begin_owned_completion_recovery_socket(original).expect("original");
    client.set_foreground_completion_recovery(false).expect("retire");
    client.set_foreground_completion_recovery(true).expect("new mode");
    assert!(prepared.check(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn exact_recovery_request_cancel_keeps_original_sibling_current(){
    let mut client=client();client.set_foreground_completion_recovery(true).expect("explicit");
    let original=scope(&client);let sibling=scope(&client);
    let prepared=client.begin_owned_completion_recovery_socket(original.clone()).expect("original");
    original.request().cancel();assert!(prepared.check(&client).is_err());
    sibling.check(&client).expect("ordinary sibling remains current");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn caller_gate_mode_cancel_returning_ok_is_refused_after_callback(){
    let mut client=client();client.set_foreground_completion_recovery(true).expect("explicit");
    let mode=client.completion_recovery_mode.clone().expect("mode");
    let armed=Arc::new(std::sync::atomic::AtomicBool::new(false));let state=armed.clone();let captured=mode.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{if state.load(std::sync::atomic::Ordering::SeqCst){captured.cancel();}Ok(())})));
    let original=scope(&client);let fence=SocketConnectFence{scope:original,mode,prepared_cancel:client.browser_prepared_transport_cancel.clone()};
    armed.store(true,std::sync::atomic::Ordering::SeqCst);
    assert!(fence.check().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn same_fixed_builder_preserves_foreground_capability_and_active_chat_data(){
    let mut client=client();client.active_chat=Some("22222222-2222-4222-8222-222222222222".into());
    let prepared=client.prepare_socket_connection(false,false,true,SocketSelectionPolicy::AnnounceActiveChat,None).expect("fixed transport data only");
    let url=url::Url::parse(&prepared.request.uri().to_string()).expect("url");
    let capabilities=url.query_pairs().find(|(key,_)|key=="client_capabilities").expect("capabilities").1.into_owned();
    assert_eq!(capabilities,"canonical_embed_receipts_v1,typed_recovery_outputs_v2,agentic-storage-v2,chat_metadata_recovery");
    assert_eq!(prepared.active_chat,client.active_chat);
    assert!(client.completion_recovery_mode.is_none(),"transport request DATA never grants foreground mode");
}

async fn actual_peer()->(Client,tokio::sync::oneshot::Sender<()>,tokio::task::JoinHandle<usize>){actual_peer_with_auth_count(1).await}
async fn actual_peer_with_auth_count(auth_count:usize)->(Client,tokio::sync::oneshot::Sender<()>,tokio::task::JoinHandle<usize>){
    use tokio::io::{AsyncReadExt,AsyncWriteExt};
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("listener");
    let base=format!("http://{}",listener.local_addr().expect("address"));
    let (done,finished)=tokio::sync::oneshot::channel();
    let peer=tokio::spawn(async move{
        for _ in 0..auth_count{
        let(mut http,_)=listener.accept().await.expect("actual auth connection");
        let mut request=Vec::new();
        while !request.windows(4).any(|v|v==b"\r\n\r\n"){
            let mut part=[0;1024];let n=http.read(&mut part).await.expect("request");assert!(n>0);request.extend_from_slice(&part[..n]);assert!(request.len()<8192);
        }
        assert!(String::from_utf8_lossy(&request).starts_with("POST /v1/auth/session "));
        let header_end=request.windows(4).position(|v|v==b"\r\n\r\n").expect("headers")+4;
        let header=String::from_utf8_lossy(&request[..header_end]);
        let length=header.lines().filter_map(|line|line.split_once(':')).find(|(name,_)|name.eq_ignore_ascii_case("content-length"))
            .expect("fixed request length").1.trim().parse::<usize>().expect("length");
        while request.len()<header_end+length{
            let mut part=[0;1024];let n=http.read(&mut part).await.expect("actual complete auth body");assert!(n>0);request.extend_from_slice(&part[..n]);assert!(request.len()<8192);
        }
        let actual:Value=serde_json::from_slice(&request[header_end..header_end+length]).expect("actual request body");
        assert_eq!(actual,json!({"session_id":"fixture"}));
        let body=json!({"success":true,"ws_token":"fresh-token","user":{"id":"11111111-1111-4111-8111-111111111111"}}).to_string();
        http.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.expect("actual auth response");
        drop(http);
        }
        let mut finished=finished;let mut accepted=0;
        loop{
            tokio::select!{biased;
                result=listener.accept()=>{
                    let(stream,_)=result.expect("socket connection");accepted+=1;
                    let mut ws=tokio_tungstenite::accept_hdr_async(stream,|request:&tungstenite::handshake::server::Request,response:tungstenite::handshake::server::Response|{
                        let url=url::Url::parse(&format!("http://fixture{}",request.uri())).expect("actual URL");
                        let pairs=url.query_pairs().collect::<BTreeMap<_,_>>();
                        assert_eq!(pairs.get("token").map(|s|s.as_ref()),Some("fresh-token"));
                        assert!(pairs.get("client_capabilities").expect("caps").split(',').any(|v|v=="chat_metadata_recovery"));
                        assert_eq!(request.headers().get("Cookie").expect("rotated original cookies").to_str().expect("cookie"),"auth_refresh_token=rotated");
                        Ok(response)
                    }).await.expect("actual upgrade");
                    let frame=ws.next().await.expect("actual lifecycle").expect("frame");
                    let value:Value=serde_json::from_str(frame.to_text().expect("text")).expect("JSON");
                    assert_eq!(value["type"],"native_client_lifecycle");assert_eq!(value["payload"]["is_foreground"],true);
                    ws.send(tungstenite::Message::Text(json!({"type":"native_client_lifecycle_ack","payload":{"is_foreground":true}}).to_string().into())).await.expect("actual ACK");
                    let _=ws.close(None).await;
                },
                _=&mut finished=>return accepted,
            }
        }
    });
    let mut client=client();client.base=url::Url::parse(&base).expect("base");
    // A loopback test credential scope; only the actual HTTP response below
    // can mint auth receipt. No DTO/fixture method constructs that receipt.
    client.session.as_mut().expect("test session").api_url=base;
    (client,done,peer)
}
async fn actual_validation(client:&mut Client,original:Arc<owned_operation::OwnedOperationScope>)->auth::OwnedSessionValidationReceipt{
    let prepared=client.prepare_owned_session_validation(original).expect("actual original auth prepare");
    let headers=auth::send_owned_session_validation_headers(prepared).await;
    let body=client.apply_owned_session_validation_headers(headers).expect("real header merge");
    let completed=auth::drive_owned_session_validation_body(body).await;
    client.finish_owned_session_validation(completed).expect("actual sealed body receipt")
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn real_auth_receipt_drives_exact_foreground_socket_and_actual_lifecycle_ack(){
    let(mut client,done,peer)=actual_peer().await;client.set_foreground_completion_recovery(true).expect("explicit");
    let original=scope(&client);let parent=client.operation_parent.clone();
    let preparation=client.begin_owned_completion_recovery_socket(original.clone()).expect("original");assert!(preparation.needs_validation());
    let receipt=actual_validation(&mut client,original).await;
    let prepared=preparation.prepare(&mut client,Some(receipt)).expect("same actual auth completion");
    let unannounced=connect_owned_completion_recovery_socket(prepared).await.expect("real connection");
    let lifecycle=unannounced.prepare_lifecycle(&client).expect("same original actual resource bind");
    let mut connected=drive_owned_completion_recovery_lifecycle(lifecycle).await.expect("actual lifecycle sends");
    connected.check_original(&client).expect("actual original before ACK");
    let(kind,payload)=receive_ephemeral(connected.socket()).await.expect("actual peer ACK still unconsumed by socket builder");
    connected.check_original(&client).expect("same original after actual ACK");
    assert_eq!(kind,"native_client_lifecycle_ack");assert_eq!(payload["is_foreground"],true);
    let _socket=connected.into_socket(&client).expect("actual original after ACK transferred");
    assert_eq!(client.operation_parent,parent);assert!(!parent.is_cancelled());
    done.send(()).expect("done");assert_eq!(peer.await.expect("peer"),1);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn cancel_after_real_auth_refuses_socket_without_retiring_original_sibling(){
    let(mut client,done,peer)=actual_peer().await;client.set_foreground_completion_recovery(true).expect("explicit");
    let original=scope(&client);let sibling=scope(&client);
    let preparation=client.begin_owned_completion_recovery_socket(original.clone()).expect("original");
    let receipt=actual_validation(&mut client,original.clone()).await;
    let prepared=preparation.prepare(&mut client,Some(receipt)).expect("actual auth");
    original.request().cancel();assert!(connect_owned_completion_recovery_socket(prepared).await.is_err());
    sibling.check(&client).expect("healthy original sibling after genuine auth rotation");
    assert_eq!(client.require_credentials().expect("actual credentials").ws_token.as_deref(),Some("fresh-token"));
    done.send(()).expect("done");assert_eq!(peer.await.expect("peer"),0,"actual accept-vs-done branch; no timeout/silence proof");
}


// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn narrower_callback_cannot_hide_mode_revocation_or_original_request_cancel(){
    for original_request in [false,true]{
        let mut client=client();client.set_foreground_completion_recovery(true).expect("explicit");
        let scope=scope(&client);let mode=client.completion_recovery_mode.clone().expect("mode");
        let captured_scope=scope.clone();let captured_mode=mode.clone();
        let fence=SocketConnectFence{scope,mode,prepared_cancel:client.browser_prepared_transport_cancel.clone()};
        assert!(fence.check_with_negative(&||{if original_request{captured_scope.request().cancel();}else{captured_mode.cancel();}Ok(())}).is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn original_gate_canceling_narrower_recovery_request_refuses_before_real_ws_dispatch(){
    let(mut client,done,peer)=actual_peer().await;client.set_foreground_completion_recovery(true).expect("explicit");
    let derived=CancellationToken::new();let captured=derived.clone();
    let armed=Arc::new(std::sync::atomic::AtomicBool::new(false));let active=armed.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{if active.load(std::sync::atomic::Ordering::SeqCst){captured.cancel();}Ok(())})));
    let original=scope(&client);let sibling=scope(&client);
    let preparation=client.begin_owned_completion_recovery_socket(original.clone()).expect("original");
    let receipt=actual_validation(&mut client,original).await;
    let prepared=preparation.prepare(&mut client,Some(receipt)).expect("actual auth");
    armed.store(true,std::sync::atomic::Ordering::SeqCst);
    assert!(connect_owned_completion_recovery_socket_with_negative(prepared,||if derived.is_cancelled(){Err(Error::Cancelled)}else{Ok(())}).await.is_err());
    assert!(derived.is_cancelled());sibling.check(&client).expect("original healthy sibling not narrower request");
    done.send(()).expect("done");assert_eq!(peer.await.expect("peer"),0);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn armed_native_handoff_and_canceled_ordinary_a_cannot_refuse_preadmitted_owned_b_normal_auth(){
    let(mut client,done,peer)=actual_peer_with_auth_count(2).await;
    client.set_foreground_completion_recovery(true).expect("explicit foreground");
    let parent=client.operation_parent.clone();let ordinary_a=client.operation_cancel.clone();
    let handoff=client.validate_session_for_recovery(&parent).await.expect("FIRST actual native validation").expect("real same-parent native handoff");
    client.use_fresh_session_for_recovery(handoff,&parent).expect("arm actual optimization");
    let b=scope(&client);ordinary_a.cancel();b.check(&client).expect("B already admitted independent original child");
    let preparation=client.begin_owned_completion_recovery_socket(b.clone()).expect("discard never matches unrelated ordinary A");
    assert!(preparation.needs_validation());assert!(ordinary_a.is_cancelled());assert!(!parent.is_cancelled());
    let receipt=actual_validation(&mut client,b.clone()).await;
    let prepared=preparation.prepare(&mut client,Some(receipt)).expect("SECOND actual normal auth required");
    let unannounced=connect_owned_completion_recovery_socket(prepared).await.expect("actual same B socket");
    let lifecycle=unannounced.prepare_lifecycle(&client).expect("same original B");
    let mut connected=drive_owned_completion_recovery_lifecycle(lifecycle).await.expect("real lifecycle");
    let(kind,payload)=receive_ephemeral(connected.socket()).await.expect("actual ACK");
    assert_eq!(kind,"native_client_lifecycle_ack");assert_eq!(payload["is_foreground"],true);
    connected.check_original(&client).expect("same B after actual ACK");b.check(&client).expect("same B still live");
    assert_eq!(client.operation_parent,parent);assert_eq!(client.operation_cancel,ordinary_a);assert!(ordinary_a.is_cancelled());assert!(!parent.is_cancelled());
    done.send(()).expect("done");assert_eq!(peer.await.expect("peer requires TWO real POSTs before WS"),1);
}
