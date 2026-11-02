//! Actual loopback header observations against native browser-credential model.
//! No browser/WASM/opaque WebCrypto claim; no header/transition is fabricated.
use super::*;
use crate::client::owned_operation::OwnedOperationScope;
use tokio::io::{AsyncReadExt,AsyncWriteExt};
async fn fixture(browser:bool,changed:bool)->(Client,tokio::task::JoinHandle<()>){
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("listener");
    let base=format!("http://{}",listener.local_addr().expect("address"));
    let peer=tokio::spawn(async move{
        let(mut stream,_)=listener.accept().await.expect("actual HTTP");let mut request=Vec::new();
        while !request.windows(4).any(|v|v==b"\r\n\r\n"){
            let mut bytes=[0;1024];let n=stream.read(&mut bytes).await.expect("request");assert!(n>0);request.extend_from_slice(&bytes[..n]);assert!(request.len()<8192);
        }
        assert!(String::from_utf8_lossy(&request).starts_with("GET /cookie "));
        let header=if changed{"Set-Cookie: auth_refresh_token=rotated; Path=/\r\n"}else{""};
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{header}Content-Length: 2\r\nConnection: close\r\n\r\n{{}}").as_bytes()).await.expect("actual response");
    });
    let mut client=Client::new(&base,Some(Session{api_url:base.clone(),session_id:"cookie-fixture".into(),cookies:BTreeMap::new(),ws_token:Some("existing".into()),
        master_key:Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("test credential resource");
    client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
    if browser{let session=client.session.take().expect("native fixture conversion before capture");client.browser_credentials=Some(credentials::BrowserCredentials::from_native_session(session));}
    (client,peer)
}
async fn headers(client:&Client)->crate::platform::http::Response{
    client.http.request(reqwest::Method::GET,client.url("/cookie").expect("fixed test route")).send().await.expect("actual received headers")
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn browser_credentials_actual_header_rotation_keeps_canceled_a_denied_and_original_c_healthy(){
    let(mut client,peer)=fixture(true,true).await;let request=CancellationToken::new();
    let a=OwnedOperationScope::capture(&client,request.clone()).expect("original A");let c=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("original C");
    let generation=client.generation;let revision=client.credential_revision;let parent=client.operation_parent.clone();let ordinary=client.operation_cancel.clone();
    let response=headers(&client).await;request.cancel();
    let receipt=client.apply_owned_response_cookies(response.headers(),generation).expect("actual typed rotation").expect("observed transition");
    assert_eq!(client.credential_revision,revision.checked_add(1).expect("revision"));
    assert_eq!(client.browser_credentials.as_ref().expect("SAME browser authority").cookies,client.cookies);
    assert_eq!(client.cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
    receipt.check_applied_state(&client).expect("actual browser endpoint");
    assert!(a.observer().check_release().is_err());c.check(&client).expect("healthy C exact witnessed lineage");
    assert_eq!(client.operation_parent,parent);assert_eq!(client.operation_cancel,ordinary);assert!(!parent.is_cancelled());peer.await.expect("peer");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn unchanged_browser_response_has_no_revision_or_transition(){
    let(mut client,peer)=fixture(true,false).await;let scope=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("original");
    let generation=client.generation;let revision=client.credential_revision;let response=headers(&client).await;
    assert!(client.apply_owned_response_cookies(response.headers(),generation).expect("same").is_none());
    assert_eq!(client.credential_revision,revision);assert!(client.cookies.is_empty());assert!(client.browser_credentials.as_ref().expect("browser").cookies.is_empty());scope.check(&client).expect("same original");peer.await.expect("peer");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn native_session_actual_rotation_behavior_stays_same(){
    let(mut client,peer)=fixture(false,true).await;let scope=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("original");
    let generation=client.generation;let revision=client.credential_revision;let response=headers(&client).await;
    client.apply_owned_response_cookies(response.headers(),generation).expect("native").expect("typed native transition");
    assert_eq!(client.session.as_ref().expect("native").cookies,client.cookies);assert_eq!(client.credential_revision,revision.checked_add(1).expect("revision"));scope.check(&client).expect("original native");peer.await.expect("peer");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn received_cookie_for_wrong_original_generation_cannot_change_any_live_authority(){
    let(mut client,peer)=fixture(true,true).await;let scope=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("original");
    let generation=client.generation.checked_add(1).expect("foreign");let revision=client.credential_revision;let response=headers(&client).await;
    assert!(client.apply_owned_response_cookies(response.headers(),generation).is_err());assert!(client.cookies.is_empty());assert!(client.browser_credentials.as_ref().expect("browser").cookies.is_empty());assert_eq!(client.credential_revision,revision);scope.check(&client).expect("current original unaffected");peer.await.expect("peer");
}
