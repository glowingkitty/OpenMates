//! Authored UNRUN actual original HTTP/header/body/credential tests. Native
//! bootstrap/profile/Root and normal UI integration remain isolated browser CI.
use super::*;
use tokio::io::{AsyncReadExt,AsyncWriteExt};
// Drive the same original future while the fixture observes its held IO.
// A single poll cannot make later socket/HTTP progress while awaiting a notice.
async fn drive_until_held_notice<F: std::future::Future + ?Sized>(
    original: std::pin::Pin<&mut F>,
    notice: &tokio::sync::Notify,
) {
    tokio::time::timeout(Duration::from_secs(5), async {
        tokio::select! {
            _ = notice.notified() => {},
            _ = original => panic!("original held operation completed before fixture release"),
        }
    })
    .await
    .expect("fixture notice requires progress of the original bounded operation");
}
use std::sync::atomic::AtomicU64;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const FOREIGN:&str="22222222-2222-4222-8222-222222222222";
const SESSION:&str="66666666-6666-4666-8666-666666666666";
fn profile()->BrowserProfileKey{BrowserProfileKey::from_existing_profile(OWNER,Zeroizing::new([7;32]),"fixture-hash","fixture-salt",BrowserPersistence::MemoryOnly).unwrap()}
fn success()->Value{json!({"success":true,"user":{"id":OWNER,"username":"synthetic"},"ws_token":"actual-token",
    "client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"],
    "require_invite_code":false,"session_device_info":{"device_name":"Synthetic"},"extra_existing_field":{"preserved":true}})}
struct Peer{url:String,head:Arc<tokio::sync::Notify>,release:Arc<tokio::sync::Notify>,requests:Arc<AtomicU64>,task:tokio::task::JoinHandle<String>}
async fn open_peer(body:String,status:u16,hold:bool)->Peer{
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let url=format!("http://{}",listener.local_addr().unwrap());
    let head=Arc::new(tokio::sync::Notify::new());let release=Arc::new(tokio::sync::Notify::new());let requests=Arc::new(AtomicU64::new(0));
    let(h,r,count)=(head.clone(),release.clone(),requests.clone());
    let task=tokio::spawn(async move{
        let(mut socket,_)=listener.accept().await.unwrap();count.fetch_add(1,Ordering::AcqRel);let mut bytes=Vec::new();
        loop{let mut part=[0;1024];let n=socket.read(&mut part).await.unwrap();assert!(n>0);bytes.extend_from_slice(&part[..n]);assert!(bytes.len()<65536);
            if let Some(end)=bytes.windows(4).position(|b|b==b"\r\n\r\n"){
                let text=std::str::from_utf8(&bytes[..end]).unwrap();let len=text.lines().find_map(|line|line.split_once(':').filter(|(key,_)|key.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap())).unwrap_or(0);
                if bytes.len()>=end+4+len{break}
            }
        }
        assert!(std::str::from_utf8(&bytes).unwrap().starts_with("POST /v1/auth/session HTTP/1.1"));
        let headers=format!("HTTP/1.1 {status} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=actual-observed-rotation; Path=/\r\nConnection: close\r\n\r\n",if status==200{"OK"}else{"Error"},body.len());
        socket.write_all(headers.as_bytes()).await.unwrap();socket.flush().await.unwrap();h.notify_one();if hold{r.notified().await;}
        socket.write_all(body.as_bytes()).await.unwrap();socket.shutdown().await.unwrap();String::from_utf8(bytes).unwrap()
    });Peer{url,head,release,requests,task}
}
fn prepare(url:&str,profile:BrowserProfileKey)->PreparedBrowserFirstSession{
    Client::prepare_browser_first_session_inner(url,"https://app.example.invalid",SESSION,profile,json!({"screen":"synthetic","nullable":null}),CancellationToken::new()).unwrap()
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_normal_session_response_is_consumed_for_same_restore_with_exactly_one_http(){
    let actual=success();let peer=open_peer(actual.to_string(),200,false).await;let pending=prepare(&peer.url,profile());
    assert!(pending.client.as_ref().unwrap().browser_credentials.is_none());assert!(pending.client.as_ref().unwrap().session.is_none());
    let receipt=pending.wait().await.unwrap();assert!(receipt.client.as_ref().unwrap().browser_credentials.is_none());
    let mut ui:Value=serde_json::from_str(&receipt.response_json().unwrap()).unwrap();assert_eq!(ui,actual);
    // Mutating this ordinary output cannot replace the opaque actual response.
    ui["user"]["id"]=json!(FOREIGN);ui["ws_token"]=json!("forged-token");
    let client=receipt.restore().unwrap();assert_eq!(client.user,actual["user"]);assert_eq!(client.require_credentials().unwrap().ws_token.as_deref(),Some("actual-token"));
    assert!(client.require_browser_owner_guards().is_ok());assert!(client.credential_snapshot().is_none());assert_eq!(client.credential_ack,0);
    assert_eq!(client.cookies["auth_refresh_token"],"actual-observed-rotation");assert!(client.browser_session_status().is_some());
    let raw=peer.task.await.unwrap();let body:Value=serde_json::from_str(raw.split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(body,json!({"session_id":SESSION,"deviceSignals":{"screen":"synthetic","nullable":null}}));
    assert!(!raw.to_lowercase().contains("x-openmates-expected-principal:"));assert_eq!(peer.requests.load(Ordering::Acquire),1);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn cancelled_started_read_retains_actual_cookie_and_drains_body_but_cannot_restore_or_publish(){
    let peer=open_peer(success().to_string(),200,true).await;let pending=prepare(&peer.url,profile());let control=pending.control();
    let mut wait=Box::pin(pending.wait());assert!(futures_util::poll!(wait.as_mut()).is_pending());drive_until_held_notice(wait.as_mut(), &peer.head).await;
    assert!(futures_util::poll!(wait.as_mut()).is_pending());control.cancel();assert!(futures_util::poll!(wait.as_mut()).is_pending());
    peer.release.notify_one();let receipt=wait.await.unwrap();assert_eq!(receipt.client.as_ref().unwrap().cookies["auth_refresh_token"],"actual-observed-rotation");
    assert!(receipt.response_json().is_err());assert!(matches!(receipt.restore(),Err(Error::Cancelled)));assert_eq!(peer.requests.load(Ordering::Acquire),1);peer.task.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn actual_profile_key_invalidation_during_body_and_wrong_response_owner_refuse_original_restore(){
    let peer=open_peer(success().to_string(),200,true).await;let p=profile();let original=p.master.clone();let pending=prepare(&peer.url,p);
    let mut wait=Box::pin(pending.wait());assert!(futures_util::poll!(wait.as_mut()).is_pending());drive_until_held_notice(wait.as_mut(), &peer.head).await;original.invalidate();peer.release.notify_one();
    let receipt=wait.await.unwrap();assert!(receipt.response_json().is_err());assert!(receipt.restore().is_err());peer.task.await.unwrap();
    let mut wrong=success();wrong["user"]["id"]=json!(FOREIGN);let peer=open_peer(wrong.to_string(),200,false).await;let p=profile();let original=p.master.clone();
    let receipt=prepare(&peer.url,p).wait().await.unwrap();assert_eq!(receipt.observed_http_status(),Some(200));assert_eq!(serde_json::from_str::<Value>(&receipt.response_json().unwrap()).unwrap()["user"]["id"],FOREIGN);
    assert!(matches!(receipt.restore(),Err(Error::Authentication)));assert!(original.ensure_current().is_err());
    assert!(!peer.task.await.unwrap().to_lowercase().contains("x-openmates-expected-principal:"));
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn device_challenge_and_observed_http_status_preserve_ui_data_without_admitting_normal_client(){
    let challenge=json!({"success":false,"re_auth_required":"passkey","re_auth_reason":"new_device","password_fallback_available":true,"password_credential_version":2});
    let peer=open_peer(challenge.to_string(),200,false).await;let receipt=prepare(&peer.url,profile()).wait().await.unwrap();
    assert_eq!(serde_json::from_str::<Value>(&receipt.response_json().unwrap()).unwrap(),challenge);assert!(receipt.restore().is_err());peer.task.await.unwrap();
    for status in [401,403]{let peer=open_peer(json!({"detail":"denied"}).to_string(),status,false).await;let receipt=prepare(&peer.url,profile()).wait().await.unwrap();
        assert_eq!(receipt.observed_http_status(),Some(status));
        if status==401{assert_eq!(serde_json::from_str::<Value>(&receipt.response_json().unwrap()).unwrap(),json!({"success":false,"message":"Session expired or revoked"}));}
        else{assert!(receipt.response_json().is_err());}
        assert!(receipt.restore().is_err());peer.task.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn missing_token_or_capabilities_does_not_gain_more_than_existing_restore_policy(){
    let mut body=success();body.as_object_mut().unwrap().remove("ws_token");let peer=open_peer(body.to_string(),200,false).await;
    let receipt=prepare(&peer.url,profile()).wait().await.unwrap();assert!(receipt.response_json().is_ok());assert!(matches!(receipt.restore(),Err(Error::Protocol)));peer.task.await.unwrap();
    let mut body=success();body.as_object_mut().unwrap().remove("client_security_capabilities");let peer=open_peer(body.to_string(),200,false).await;
    let client=prepare(&peer.url,profile()).wait().await.unwrap().restore().unwrap();assert!(client.require_browser_owner_guards().is_err());assert!(!client.is_local_browser_profile());peer.task.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn stale_receipt_and_pre_dispatch_cancel_cannot_be_replayed_or_send(){
    let peer=open_peer(success().to_string(),200,false).await;let mut receipt=prepare(&peer.url,profile()).wait().await.unwrap();
    receipt.received=Instant::now()-Duration::from_secs(6);assert!(receipt.response_json().is_err());assert!(matches!(receipt.restore(),Err(Error::Expired)));peer.task.await.unwrap();
    let pending=prepare("http://127.0.0.1:1",profile());let control=pending.control();control.cancel();assert!(matches!(pending.wait().await,Err(Error::Cancelled)));
    let pending=prepare("http://127.0.0.1:1",profile());let control=pending.control();drop(pending);assert!(control.ensure_current().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_503_retains_existing_explicit_local_only_restore_and_old_default_wire_body_is_held(){
    let peer=open_peer(json!({"detail":"unavailable"}).to_string(),503,false).await;
    let receipt=prepare(&peer.url,profile()).wait().await.unwrap();assert!(matches!(receipt.response_json(),Err(Error::Offline)));
    let client=receipt.restore().unwrap();assert!(client.is_local_browser_profile());assert!(client.require_canonical_read_profile().is_err());assert!(client.require_browser_owner_guards().is_err());assert!(client.require_credentials().unwrap().ws_token.is_none());peer.task.await.unwrap();
    let peer=open_peer(success().to_string(),200,false).await;Client::restore_browser_credentials_inner(&peer.url,"https://app.example.invalid",SESSION,profile()).await.unwrap();
    let raw=peer.task.await.unwrap();assert_eq!(serde_json::from_str::<Value>(raw.split("\r\n\r\n").nth(1).unwrap()).unwrap(),json!({"session_id":SESSION}));
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[test]
fn closed_normal_request_sets_actual_ten_second_request_override_and_old_generic_budget_is_unchanged(){
    use crate::client::transport::{session_request_budget_at,SessionRequestBudget,NORMAL_BROWSER_SESSION_TIMEOUT};
    let client=Client::new("http://127.0.0.1:1",None).unwrap();
    let now=Instant::now();let deadline=now+NORMAL_BROWSER_SESSION_TIMEOUT;
    let normal=session_request_budget_at(client.http.post(client.base.join("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline}),now).unwrap().build().unwrap();
    assert_eq!(normal.timeout(),Some(&Duration::from_secs(10)));assert_eq!(*normal.timeout().unwrap(),NORMAL_BROWSER_SESSION_TIMEOUT);
    let old=session_request_budget_at(client.http.post(client.base.join("/v1/auth/session").unwrap()),None,now).unwrap().build().unwrap();
    // None leaves the existing client-level60second setting in effect.
    assert_eq!(old.timeout(),None);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[test]
fn same_actual_request_budget_refuses_late_headers_body_chunk_and_eof_with_native_abort_signal(){
    use std::{cell::Cell,future::{Future,poll_fn},pin::pin,task::{Context,Poll,Waker}};
    use crate::client::transport::{session_request_budget_at,SessionRequestBudget};
    let client=Client::new("http://127.0.0.1:1",None).unwrap();
    let at=Instant::now();let original_deadline=at+Duration::from_secs(10);
    let request=session_request_budget_at(client.http.post(client.base.join("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline:original_deadline}),at).unwrap().build().unwrap();
    let deadline=request.timeout().unwrap().as_millis()as u64;assert_eq!(deadline,10000);
    for stage in ["headers","body_chunk","body_eof"]{
        let now=Cell::new(0u64);let released=Cell::new(false);let settled=Cell::new(false);let aborts=Cell::new(0);
        let mut operation=pin!(crate::platform::within_http_budget(deadline,||now.get(),||aborts.set(aborts.get()+1),async{
            let value=poll_fn(|_|if released.get(){Poll::Ready(stage)}else{Poll::Pending}).await;
            settled.set(true);Ok(value)
        }));
        let mut context=Context::from_waker(Waker::noop());assert!(operation.as_mut().poll(&mut context).is_pending());assert!(!settled.get());
        now.set(deadline);released.set(true);
        assert!(matches!(operation.as_mut().poll(&mut context),Poll::Ready(Err(Error::Offline))),"{stage}");
        assert!(settled.get());assert_eq!(aborts.get(),1);
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn normal_budget_entry_cannot_be_reused_on_an_admitted_client(){
    let peer=open_peer(success().to_string(),200,false).await;
    let mut client=prepare(&peer.url,profile()).wait().await.unwrap().restore().unwrap();peer.task.await.unwrap();
    let mut status=None;assert!(matches!(client.normal_browser_session_request_observed(json!({"session_id":SESSION}),&mut status,Instant::now()+Duration::from_secs(10)).await,Err(Error::Forbidden)));
    assert_eq!(status,None);assert!(client.require_browser_owner_guards().is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn original_ten_second_budget_after_nine_second_queue_only_leaves_one_and_cannot_be_extended(){
    use crate::client::transport::{session_request_budget_at,SessionRequestBudget};
    let client=Client::new("http://127.0.0.1:1",None).unwrap();let start=Instant::now();let deadline=start+Duration::from_secs(10);
    let request=session_request_budget_at(client.http.post(client.base.join("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline}),start+Duration::from_secs(9)).unwrap().build().unwrap();
    assert_eq!(request.timeout(),Some(&Duration::from_secs(1)));
    assert!(matches!(session_request_budget_at(client.http.post(client.base.join("/v1/auth/session").unwrap()),Some(SessionRequestBudget::NormalBrowserCheck{deadline}),deadline),Err(Error::Offline)));
    let mut prepared=prepare("http://127.0.0.1:1",profile());prepared.restrict_remaining_budget(Duration::from_secs(1)).unwrap();let restricted=prepared.deadline;
    prepared.restrict_remaining_budget(Duration::from_secs(10)).unwrap();assert_eq!(prepared.deadline,restricted);
    assert!(prepared.restrict_remaining_budget(Duration::ZERO).is_err());assert!(prepared.control().ensure_current().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn queue_limited_actual_body_read_stays_owned_through_late_caller_cancel_without_fresh_budget(){
    let peer=open_peer(success().to_string(),200,true).await;let mut pending=prepare(&peer.url,profile());
    pending.restrict_remaining_budget(Duration::from_secs(1)).unwrap();let deadline=pending.deadline;let control=pending.control();
    let mut waiting=Box::pin(pending.wait());assert!(futures_util::poll!(waiting.as_mut()).is_pending());drive_until_held_notice(waiting.as_mut(), &peer.head).await;
    control.cancel();assert!(futures_util::poll!(waiting.as_mut()).is_pending());peer.release.notify_one();
    let receipt=waiting.await.unwrap();assert!(receipt.response_json().is_err());assert!(receipt.restore().is_err());
    assert!(deadline<=Instant::now()+Duration::from_secs(1));assert_eq!(peer.requests.load(Ordering::Acquire),1);peer.task.await.unwrap();
}

fn unadmitted_normal_io(url:&str,request:CancellationToken)->NormalSessionIo{
    let mut client=Client::with_options(url,None,ClientOptions{app_url:Some("https://app.example.invalid".into()),..Default::default()}).unwrap();
    client.browser_transport=true;client.set_operation_cancel(request);
    NormalSessionIo{client,session:Zeroizing::new(SESSION.into()),signals:Plain::new(json!({"screen":"synthetic","nullable":null})),deadline:Instant::now()+Duration::from_secs(10)}
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn same_normal_owner_retains_actual_full_cookie_b_and_challenge_data_without_any_master_or_admission(){
    let mut foreign=success();foreign["user"]["id"]=json!(FOREIGN);foreign["unknown_normal_field"]=json!({"kept":[1,2]});
    for value in [foreign,json!({"success":false,"re_auth_required":"passkey","password_fallback_available":true,"unknown_normal_field":{"kept":true}})]{
        let peer=open_peer(value.to_string(),200,false).await;
        let(client,response)=unadmitted_normal_io(&peer.url,CancellationToken::new()).read().await;
        assert_eq!(response.status,Some(200));assert_eq!(serde_json::from_str::<Value>(&response.json().unwrap()).unwrap(),value);
        assert_eq!(client.cookies["auth_refresh_token"],"actual-observed-rotation");
        assert!(client.browser_credentials.is_none()&&client.session.is_none()&&client.browser_authority.is_none()&&client.user.is_null());
        assert!(client.master_capability().is_err());assert!(client.require_canonical_read_profile().is_err());
        let raw=peer.task.await.unwrap();assert!(!raw.to_lowercase().contains("x-openmates-expected-principal:"));
        assert_eq!(serde_json::from_str::<Value>(raw.split("\r\n\r\n").nth(1).unwrap()).unwrap(),json!({"session_id":SESSION,"deviceSignals":{"screen":"synthetic","nullable":null}}));
        assert_eq!(peer.requests.load(Ordering::Acquire),1);
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn normal_data_owner_preserves_actual_401_403_offline_policy_and_never_finishes_a_client(){
    for status in [401,403,503]{
        let peer=open_peer(json!({"detail":"synthetic denial"}).to_string(),status,false).await;
        let(client,response)=unadmitted_normal_io(&peer.url,CancellationToken::new()).read().await;
        assert_eq!(response.status,Some(status));
        match status{
            401=>assert_eq!(serde_json::from_str::<Value>(&response.json().unwrap()).unwrap(),json!({"success":false,"message":"Session expired or revoked"})),
            403=>assert!(matches!(response.json(),Err(Error::Forbidden))),
            503=>assert!(matches!(response.json(),Err(Error::Offline))),_=>unreachable!(),
        }
        assert!(client.browser_credentials.is_none()&&client.session.is_none()&&client.browser_authority.is_none());
        assert!(client.master_capability().is_err());assert_eq!(peer.requests.load(Ordering::Acquire),1);peer.task.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn master_free_normal_io_keeps_started_body_owned_after_late_negative_without_a_second_request(){
    let peer=open_peer(success().to_string(),200,true).await;let cancel=CancellationToken::new();
    let mut io=unadmitted_normal_io(&peer.url,cancel.clone());io.deadline=Instant::now()+Duration::from_secs(1);
    let mut pending=Box::pin(io.read());assert!(futures_util::poll!(pending.as_mut()).is_pending());drive_until_held_notice(pending.as_mut(), &peer.head).await;
    cancel.cancel();assert!(futures_util::poll!(pending.as_mut()).is_pending());
    peer.release.notify_one();let(client,response)=pending.await;
    assert!(client.operation_cancel.is_cancelled());assert!(client.browser_credentials.is_none()&&client.session.is_none());
    assert_eq!(response.status,Some(200));assert_eq!(peer.requests.load(Ordering::Acquire),1);peer.task.await.unwrap();
}
