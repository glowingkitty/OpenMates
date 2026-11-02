//! Genuine native HTTP fixtures; all execution is isolated-CI-only.
use super::*;
use crate::client::owned_operation::OwnedOperationScope;
use std::sync::Arc;
use tokio::io::{AsyncReadExt,AsyncWriteExt};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
fn fixture(base:&str)->Client {
    let mut cookies=BTreeMap::new();cookies.insert("auth_refresh_token".into(),"old-cookie".into());
    let mut client=Client::new(base,Some(Session{api_url:base.into(),session_id:"original-session".into(),cookies,
        ws_token:Some("old-token".into()),master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"owner".into(),
        user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
    client.user=json!({"id":OWNER});client
}
fn success(token:&str)->String {json!({"success":true,"ws_token":token,"user":{"id":OWNER}}).to_string()}
async fn request(stream:&mut tokio::net::TcpStream)->String {
    let mut bytes=Vec::new();let mut buffer=[0u8;1024];
    loop {
        let n=stream.read(&mut buffer).await.unwrap();assert!(n>0);bytes.extend_from_slice(&buffer[..n]);assert!(bytes.len()<16384);
        if let Some(end)=bytes.windows(4).position(|w|w==b"\r\n\r\n") {
            let head=std::str::from_utf8(&bytes[..end]).unwrap();
            let length=head.lines().find_map(|l|l.to_ascii_lowercase().strip_prefix("content-length:").and_then(|v|v.trim().parse::<usize>().ok())).unwrap_or(0);
            if bytes.len()>=end+4+length{return String::from_utf8(bytes).unwrap();}
        }
    }
}
async fn response(stream:&mut tokio::net::TcpStream,status:u16,cookie:&str,body:&str,headers_only:bool) {
    stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token={cookie}; Path=/\r\nConnection: close\r\n\r\n",body.len()).as_bytes()).await.unwrap();
    if !headers_only{stream.write_all(body.as_bytes()).await.unwrap();}
}
async fn held(mode:Option<&'static str>,status:u16,body:String)->(Client,Arc<OwnedOperationScope>,Arc<OwnedOperationScope>,OwnedSessionValidationBody,tokio::sync::oneshot::Sender<()>,tokio::task::JoinHandle<()>) {
    held_expiry(mode,status,body,None).await
}
async fn held_expiry(mode:Option<&'static str>,status:u16,body:String,expires:Option<u64>)->(Client,Arc<OwnedOperationScope>,Arc<OwnedOperationScope>,OwnedSessionValidationBody,tokio::sync::oneshot::Sender<()>,tokio::task::JoinHandle<()>) {
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut client=fixture(&base);client.session.as_mut().unwrap().paired_session_expires_at=expires;
    let a=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let(release,wait)=tokio::sync::oneshot::channel();
    let server=tokio::spawn(async move {
        let(mut first,_)=listener.accept().await.unwrap();let req=request(&mut first).await;
        assert!(req.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));
        assert!(req.to_ascii_lowercase().contains("cookie: auth_refresh_token=old-cookie"));
        assert!(req.contains("\"session_id\":\"original-session\""));
        assert!(!req.contains("encrypted_key"));assert!(!req.contains("password"));
        response(&mut first,status,"cookie-a",&body,true).await;
        if let Some(mode)=mode {
            let(mut second,_)=listener.accept().await.unwrap();let req=request(&mut second).await;
            assert!(req.to_ascii_lowercase().contains("cookie: auth_refresh_token=cookie-a"));
            let body=if mode=="auth" {assert!(req.starts_with("POST /v1/auth/session "));success("token-b")}
                else {assert!(req.starts_with("GET /v1/tasks/fixture-task "));"{}".into()};
            response(&mut second,200,"cookie-b",&body,false).await;
        }
        wait.await.unwrap();first.write_all(body.as_bytes()).await.unwrap();
    });
    let prepared=client.prepare_owned_session_validation(a.clone()).unwrap();
    let headers=send_owned_session_validation_headers(prepared).await;
    let body=client.apply_owned_session_validation_headers(headers).unwrap();
    (client,a,b,body,release,server)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn detached_auth_advances_same_original_across_actual_sibling_cookie_and_auth_edges() {
    for mode in ["cookie","auth"] {
        let(mut client,a,b,body,release,server)=held(Some(mode),200,success("token-a")).await;
        assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
        if mode=="auth"{client.validate_session().await.unwrap();}
        else {client.request(Method::GET,"/v1/tasks/fixture-task",None).await.unwrap();}
        assert_eq!(client.cookies["auth_refresh_token"],"cookie-b");
        b.check(&client).unwrap();release.send(()).unwrap();
        let completed=drive_owned_session_validation_body(body).await;
        let receipt=client.finish_owned_session_validation(completed).unwrap();
        assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("token-a"));
        assert_eq!(client.cookies["auth_refresh_token"],"cookie-b");
        receipt.check_original(&client,&a).unwrap();
        assert!(receipt.check_original(&client,&b).is_err());
        b.check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());server.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn malformed_success_keeps_actual_headers_and_irreversibly_revokes_live_originals() {
    let(mut client,a,b,body,release,server)=held(None,200,"{\"success\":true,\"ws_token\":\"new\",\"user\":{}}".into()).await;
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");release.send(()).unwrap();
    let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Protocol)));
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
    client.user=json!({"id":OWNER});assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("old-token"));server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn actual_header_resource_refuses_foreign_client_without_installing_rotation() {
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut original=fixture(&base);let a=Arc::new(OwnedOperationScope::capture(&original,CancellationToken::new()).unwrap());
    let server=tokio::spawn(async move {let(mut stream,_)=listener.accept().await.unwrap();let _=request(&mut stream).await;response(&mut stream,200,"rotated",&success("real"),false).await;});
    let prepared=original.prepare_owned_session_validation(a).unwrap();let headers=send_owned_session_validation_headers(prepared).await;
    let mut foreign=fixture(&base);
    assert!(matches!(foreign.apply_owned_session_validation_headers(headers),Err(Error::Cancelled)));
    assert_eq!(foreign.cookies["auth_refresh_token"],"old-cookie");assert_eq!(original.cookies["auth_refresh_token"],"old-cookie");server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn unexplained_mid_body_auth_drift_cannot_rearm_after_value_restoration() {
    let(mut client,a,b,body,release,server)=held(None,200,success("token-a")).await;
    client.session.as_mut().unwrap().ws_token=Some("unwitnessed".into());client.credentials_changed();
    release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
    client.session.as_mut().unwrap().ws_token=Some("old-token".into());
    assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn actual_http_denial_and_outage_keep_existing_auth_error_and_cookie_order() {
    for status in [401,403,500] {
        let(mut client,_a,_b,body,release,server)=held(None,status,"{}".into()).await;
        if status!=401{assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");}
        release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
        let result=client.finish_owned_session_validation(completed);
        if status==500{assert!(matches!(result,Err(Error::Offline)));assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");assert!(client.session.is_some());}
        else {assert!(matches!(result,Err(Error::Expired)));assert!(client.session.is_none());assert!(client.cookies.is_empty());}
        server.await.unwrap();
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn canceled_original_drains_real_auth_cookies_and_body_but_never_mints_socket_receipt() {
    let(mut client,a,b,body,release,server)=held(None,200,success("actual-after-cancel")).await;
    a.request().cancel();assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
    release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("actual-after-cancel"));
    assert!(a.observer().check_release().is_err());b.check(&client).unwrap();
    assert!(!client.operation_parent.is_cancelled());server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn unobserved_native_initial_validation_keeps_existing_no_enrollment_behavior() {
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut client=fixture(&base);client.user=json!({});
    let server=tokio::spawn(async move {let(mut stream,_)=listener.accept().await.unwrap();let req=request(&mut stream).await;
        assert!(req.starts_with("POST /v1/auth/session "));assert!(!req.contains("encrypted_key"));assert!(!req.contains("password"));
        response(&mut stream,200,"initial-rotation",&success("initial-token"),false).await;});
    client.validate_session().await.unwrap();assert_eq!(client.user["id"],OWNER);
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("initial-token"));
    assert_eq!(client.cookies["auth_refresh_token"],"initial-rotation");
    assert_eq!(client.session().unwrap().master_key.as_ref(),&[7u8;32]);server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn canceled_auth_with_actual_sibling_cookie_edge_keeps_body_durable_and_peer_healthy() {
    let(mut client,a,b,body,release,server)=held(Some("cookie"),200,success("actual-after-cancel")).await;
    client.request(Method::GET,"/v1/tasks/fixture-task",None).await.unwrap();
    a.request().cancel();release.send(()).unwrap();
    let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-b");
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("actual-after-cancel"));
    b.check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn cancellation_before_dispatch_never_opens_an_auth_connection() {
    use std::sync::atomic::{AtomicBool,Ordering};
    for change in 0..3 {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
        let mut client=fixture(&base);let mode=CancellationToken::new();let armed=Arc::new(AtomicBool::new(false));
        if change==1 {
            let mode=mode.clone();let armed=armed.clone();
            client.options.private_operation_gate=Some(Arc::new(move||{if armed.load(Ordering::SeqCst){mode.cancel();}Ok(())}));
        }
        let a=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
        let prepared=client.prepare_owned_session_validation(a.clone()).unwrap();
        if change==0{a.request().cancel();}armed.store(true,Ordering::SeqCst);
        let(done,finished)=tokio::sync::oneshot::channel();
        let peer=tokio::spawn(async move {tokio::select! {biased;
            accepted=listener.accept()=>{let(mut stream,_)=accepted.unwrap();let _=request(&mut stream).await;response(&mut stream,200,"unexpected",&success("unexpected"),false).await;true},
            _=finished=>false,
        }});
        let headers=send_owned_session_validation_headers_with_negative(prepared,|| {
            if change==2{a.request().cancel();return Ok(())}
            if mode.is_cancelled(){Err(Error::Cancelled)}else{Ok(())}
        }).await;
        let body=client.apply_owned_session_validation_headers(headers).unwrap();let completed=drive_owned_session_validation_body(body).await;
        assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
        done.send(()).unwrap();assert!(!tokio::time::timeout(Duration::from_secs(10),peer).await.unwrap().unwrap());
        assert_eq!(client.cookies["auth_refresh_token"],"old-cookie");
        assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("old-token"));
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn actual_body_cannot_adopt_reset_root_or_key_and_original_denial_never_mints_receipt() {
    for change in 0..4 {
        let(mut client,a,b,body,release,server)=held(None,200,success("actual-new")).await;
        match change {
            0=>client.user=json!({"id":"22222222-2222-4222-8222-222222222222"}),
            1=>client.session.as_mut().unwrap().master_key[0]^=1,
            2=>{client.task_watch_authority.deny_cached_chat(None).unwrap();},
            _=>client.generation=client.generation.wrapping_add(1),
        }
        release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
        assert!(client.finish_owned_session_validation(completed).is_err(),"{change}");
        assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
        if change!=2{assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("old-token"));}
        assert!(a.observer().check_release().is_err(),"{change}");assert!(b.observer().check_release().is_err(),"{change}");server.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn actual_original_deadline_can_expire_during_body_drain_without_new_continuation() {
    let deadline=now_ms()+5000;
    let(mut client,a,_b,body,release,server)=held_expiry(None,200,success("actual-expired-drain"),Some(deadline)).await;
    tokio::time::sleep(Duration::from_millis(deadline.saturating_sub(now_ms())+1)).await;
    release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
    assert!(client.finish_owned_session_validation(completed).is_err());
    assert_eq!(client.cookies["auth_refresh_token"],"cookie-a");
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("actual-expired-drain"));
    assert!(a.observer().check_release().is_err());server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn held_old_403_cannot_forget_supported_new_team_operation_or_revoke_later_b() {
    let(mut client,_a,_old_b,body,release,server)=held(None,403,"{}".into()).await;
    let registry=client.owned_operations.clone();
    client.set_team(Some("33333333-3333-4333-8333-333333333333")).unwrap();
    let b_parent=CancellationToken::new();client.set_operation_cancel(b_parent.clone());
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let before=serde_json::to_value(client.session().unwrap()).unwrap();let revision=client.credential_revision;
    release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(serde_json::to_value(client.session().unwrap()).unwrap(),before);
    assert_eq!(client.credential_revision,revision);assert_eq!(client.user["id"],OWNER);
    assert!(Arc::ptr_eq(&registry,&client.owned_operations));b.check(&client).unwrap();
    assert!(!b_parent.is_cancelled());assert!(b.observer().check_release().is_ok());server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn held_old_403_cannot_forget_actual_successful_password_login_b_or_revoke_b() {
    const OTHER:&str="22222222-2222-4222-8222-222222222222";
    let vector:Value=serde_json::from_str(include_str!("../../tests/crypto_fixtures/account.json")).unwrap();
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut client=fixture(&base);let a=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let(release,wait)=tokio::sync::oneshot::channel();let peer_vector=vector.clone();
    let server=tokio::spawn(async move {
        let(mut old,_)=listener.accept().await.unwrap();assert!(request(&mut old).await.starts_with("POST /v1/auth/session "));
        response(&mut old,403,"cookie-a","{}",true).await;
        for step in 0..3 {
            let(mut stream,_)=listener.accept().await.unwrap();let raw=request(&mut stream).await;
            let (head,body)=raw.split_once("\r\n\r\n").unwrap();
            assert!(!head.to_ascii_lowercase().contains("cookie:"));
            let sent:Value=serde_json::from_str(body).unwrap();
            let received=match step {
                0=>{assert!(head.starts_with("POST /v1/auth/lookup "));json!({"user_email_salt":peer_vector["password_v2_salt"]})},
                1=>{assert!(head.starts_with("POST /v1/auth/password-v2/challenge "));assert_eq!(sent["purpose"],"login");json!({"challenge_id":"actual-b-challenge","nonce":peer_vector["nonce_v2"]})},
                _=>{assert!(head.starts_with("POST /v1/auth/login "));assert_eq!(sent["credential_version"],2);assert_eq!(sent["password_proof"],peer_vector["login_proof_v2"]);
                    json!({"success":true,"ws_token":"token-b","user":{"id":OTHER,"credential_version":2,"user_email_salt":peer_vector["password_v2_salt"],"salt":peer_vector["password_v2_salt"],"encrypted_key":peer_vector["password_v2_wrapped_master"],"key_iv":peer_vector["iv"]}})},
            }.to_string();
            if step==2{response(&mut stream,200,"cookie-b",&received,false).await;}
            else {stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{received}",received.len()).as_bytes()).await.unwrap();}
        }
        wait.await.unwrap();old.write_all(b"{}").await.unwrap();
    });
    let prepared=client.prepare_owned_session_validation(a).unwrap();let headers=send_owned_session_validation_headers(prepared).await;
    let body=client.apply_owned_session_validation_headers(headers).unwrap();let registry=client.owned_operations.clone();
    // Supported account teardown precedes the genuine new password transaction.
    client.forget_session();let b_parent=CancellationToken::new();client.set_operation_cancel(b_parent.clone());
    client.login_password(vector["email"].as_str().unwrap(),vector["password_v2"].as_str().unwrap(),None).await.unwrap();
    assert_eq!(client.user["id"],OTHER);assert_eq!(client.cookies["auth_refresh_token"],"cookie-b");
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let before=serde_json::to_value(client.session().unwrap()).unwrap();let revision=client.credential_revision;
    release.send(()).unwrap();let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(serde_json::to_value(client.session().unwrap()).unwrap(),before);
    assert_eq!(client.credential_revision,revision);assert_eq!(client.user["id"],OTHER);
    assert!(Arc::ptr_eq(&registry,&client.owned_operations));b.check(&client).unwrap();
    assert!(!b_parent.is_cancelled());assert!(b.observer().check_release().is_ok());server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn previously_admitted_owned_b_auth_survives_unrelated_ordinary_a_child_cancel_without_reset() {
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut client=fixture(&base);let ordinary_a=client.operation_cancel.clone();let parent=client.operation_parent.clone();
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let peer=tokio::spawn(async move {let(mut stream,_)=listener.accept().await.unwrap();let raw=request(&mut stream).await;
        assert!(raw.starts_with("POST /v1/auth/session "));response(&mut stream,200,"actual-b-cookie",&success("actual-b-token"),false).await;});
    ordinary_a.cancel();b.check(&client).unwrap();
    let prepared=client.prepare_owned_session_validation(b.clone()).unwrap();
    let headers=send_owned_session_validation_headers(prepared).await;let body=client.apply_owned_session_validation_headers(headers).unwrap();
    let completed=drive_owned_session_validation_body(body).await;let receipt=client.finish_owned_session_validation(completed).unwrap();
    receipt.check_original(&client,&b).unwrap();assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("actual-b-token"));
    assert_eq!(client.cookies["auth_refresh_token"],"actual-b-cookie");
    assert_eq!(client.operation_cancel,ordinary_a);assert!(client.operation_cancel.is_cancelled());
    assert_eq!(client.operation_parent,parent);assert!(!parent.is_cancelled());b.check(&client).unwrap();
    b.request().cancel();assert!(matches!(client.prepare_owned_session_validation(b),Err(Error::Cancelled)));peer.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn genuine_restored_browser_owned_b_uses_original_child_in_auth_body_and_wrapper() {
    let(mut client,_pending,_server)=crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test().await;
    assert!(client.session.is_none());assert!(client.browser_credentials.is_some());assert!(client.browser_authority.is_some());
    let ordinary_a=client.operation_cancel.clone();let parent=client.operation_parent.clone();
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    ordinary_a.cancel();b.check(&client).unwrap();
    let prepared=client.prepare_owned_session_validation(b.clone()).unwrap();
    let headers=send_owned_session_validation_headers(prepared).await;let body=client.apply_owned_session_validation_headers(headers).unwrap();
    let completed=drive_owned_session_validation_body(body).await;let receipt=client.finish_owned_session_validation(completed).unwrap();
    receipt.check_original(&client,&b).unwrap();assert!(client.browser_authority.as_ref().unwrap().owner_guards);
    assert_eq!(client.operation_cancel,ordinary_a);assert!(client.operation_cancel.is_cancelled());
    assert_eq!(client.operation_parent,parent);assert!(!parent.is_cancelled());b.check(&client).unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn ordinary_validation_retains_its_original_child_negative_and_never_dispatches() {
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let mut client=fixture(&base);let ordinary=client.operation_cancel.clone();ordinary.cancel();
    let(done,finished)=tokio::sync::oneshot::channel();
    let peer=tokio::spawn(async move {tokio::select!{biased;
        accepted=listener.accept()=>{let(mut stream,_)=accepted.unwrap();let _=request(&mut stream).await;response(&mut stream,200,"unexpected",&success("unexpected"),false).await;true},
        _=finished=>false,
    }});
    assert!(matches!(client.validate_session().await,Err(Error::Cancelled)));
    done.send(()).unwrap();assert!(!tokio::time::timeout(Duration::from_secs(10),peer).await.unwrap().unwrap());
    assert_eq!(client.operation_cancel,ordinary);assert_eq!(client.cookies["auth_refresh_token"],"old-cookie");
    assert_eq!(client.session().unwrap().ws_token.as_deref(),Some("old-token"));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn genuine_browser_own_cancel_drains_actual_cookie_token_edge_and_keeps_sibling_c_healthy() {
    let(mut client,_pending,server)=crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test().await;
    assert!(client.session.is_none());assert!(client.browser_credentials.is_some());assert!(client.browser_authority.is_some());
    let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let c=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let parent=client.operation_parent.clone();let authority=client.task_watch_authority.clone();
    let revision=client.credential_revision;server.hold_next_auth_for_test();
    let prepared=client.prepare_owned_session_validation(b.clone()).unwrap();
    let headers=send_owned_session_validation_headers(prepared).await;
    let body=client.apply_owned_session_validation_headers(headers).unwrap();
    assert_eq!(client.cookies["auth_refresh_token"],"synthetic-owned-recovery-rotation");
    assert_eq!(client.browser_credentials.as_ref().unwrap().cookies["auth_refresh_token"],"synthetic-owned-recovery-rotation");
    assert_eq!(client.credential_revision,revision+1);c.check(&client).unwrap();
    b.request().cancel();server.release_auth_for_test();
    let completed=drive_owned_session_validation_body(body).await;
    assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
    assert_eq!(client.browser_credentials.as_ref().unwrap().ws_token.as_deref(),Some("synthetic-owned-recovery-rotated"));
    assert_eq!(client.cookies["auth_refresh_token"],"synthetic-owned-recovery-rotation");
    assert_eq!(client.credential_revision,revision+2);
    assert!(client.browser_authority.as_ref().unwrap().owner_guards);
    assert!(Arc::ptr_eq(&authority,&client.task_watch_authority));assert!(!authority.cancel.is_cancelled());
    assert_eq!(client.operation_parent,parent);assert!(!parent.is_cancelled());
    assert!(b.observer().check_release().is_err());c.check(&client).unwrap();assert!(c.observer().check_release().is_ok());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn genuine_browser_unsent_owned_stop_has_zero_requests_and_cannot_clear_sibling_c() {
    for narrower in [false,true] {
        let(mut client,pending,server)=crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test().await;
        assert!(client.session.is_none());assert!(client.browser_credentials.is_some());
        let b=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
        let c=Arc::new(OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
        let before_token=client.browser_credentials.as_ref().unwrap().ws_token.clone();let before_cookies=client.cookies.clone();
        let before_revision=client.credential_revision;let authority=client.task_watch_authority.clone();let parent=client.operation_parent.clone();
        let mode=client.completion_recovery_mode.clone();let monitor=client.monitor_cancel.clone();let checkpoint=pending.checkpoint().unwrap().digest().unwrap();
        let requests=server.request_count_for_test();let prepared=client.prepare_owned_session_validation(b.clone()).unwrap();
        let derived=b.request().child_token();if narrower{derived.cancel();}else{b.request().cancel();}
        let headers=send_owned_session_validation_headers_with_negative(prepared,||{
            if derived.is_cancelled(){Err(Error::Cancelled)}else{Ok(())}
        }).await;
        let body=client.apply_owned_session_validation_headers(headers).unwrap();let completed=drive_owned_session_validation_body(body).await;
        assert!(matches!(client.finish_owned_session_validation(completed),Err(Error::Cancelled)));
        // Actual send awaits a real response if invoked; this exact peer counter
        // therefore observes a forbidden request before the completed chain.
        assert_eq!(server.request_count_for_test(),requests);
        assert_eq!(client.browser_credentials.as_ref().unwrap().ws_token,before_token);
        assert_eq!(client.cookies,before_cookies);assert_eq!(client.credential_revision,before_revision);
        assert!(Arc::ptr_eq(&authority,&client.task_watch_authority));assert!(!authority.cancel.is_cancelled());
        assert_eq!(client.operation_parent,parent);assert!(!parent.is_cancelled());
        assert_eq!(client.completion_recovery_mode,mode);assert_eq!(client.monitor_cancel,monitor);
        assert_eq!(pending.checkpoint().unwrap().digest().unwrap(),checkpoint);
        c.check(&client).unwrap();assert!(c.observer().check_release().is_ok());
        // No actual fresh response: never rearm retired guards/URLs from data.
        assert!(!client.browser_authority.as_ref().unwrap().owner_guards);
    }
}
