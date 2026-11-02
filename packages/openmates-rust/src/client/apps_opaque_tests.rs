//! Pure shared-library crypto checks: explicit synthetic credentials, no CLI or HTTP.
//! These real-AES ports are not evidence of a browser CryptoKey/server grant.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::sync::Arc;
use tokio::sync::Notify;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const RESULT: &str = "44444444-4444-4444-8444-444444444444";
type Gate = Arc<(Notify, Notify)>;
struct Port { gate: Option<Gate> }
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(g) = &self.gate { g.0.notify_one(); g.1.notified().await; }
            crypto::encrypt_aead(plain, &[7;32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            if let Some(g) = &self.gate { g.0.notify_one(); g.1.notified().await; }
            crypto::decrypt_aead(cipher, &[7;32], iv, &[])
        })
    }
}
fn client(mode: &str, gate: Option<Gate>) -> Client {
    let base = "http://127.0.0.1:1";
    let session = Session {
        api_url: base.into(), session_id: "synthetic-session".into(),
        cookies: BTreeMap::new(), ws_token: Some("synthetic-token".into()),
        master_key: zeroize::Zeroizing::new([7;32]), hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(), email_encryption_key: None, created_at: 1,
        paired_session_expires_at: None, active_team_id: None,
    };
    let mut c = Client::new(base, Some(session)).unwrap();
    c.user = json!({"id":OWNER});
    if mode != "native" {
        let mut creds = super::super::credentials::BrowserCredentials::from_native_session(c.session.take().unwrap());
        if mode == "opaque" { creds.master = MasterCapability::opaque_for_test(Arc::new(Port {gate})); }
        c.browser_credentials = Some(creds);
        c.browser_authority = Some(super::super::browser::BrowserAuthority {
            principal: OWNER.into(), persistence: super::super::browser::BrowserPersistence::MemoryOnly, owner_guards: true,
        });
        c.browser_transport = true;
    }
    c
}
fn response(legacy_content: bool) -> Value {
    let key = [8;32];
    let content = r#"{"private":"synthetic retained result"}"#;
    json!({"key":{"key_type":"master","encrypted_embed_key":crypto::server_fields::encrypt_bytes(&key,&[7;32],&[]).unwrap()},
        "root":{"embed_id":RESULT,"app_id":"web","skill_id":"search","status":"finished",
        "encrypted_content":if legacy_content {crypto::server_fields::encrypt_text(content,&key,&[]).unwrap()} else {crypto::encrypt_combined(content,&key).unwrap()}}})
}
#[tokio::test]
async fn wrapper_and_result_decode_support_native_restored_raw_and_opaque_without_export() {
    use base64::Engine;
    for mode in ["native", "raw_browser", "opaque"] {
        let c = client(mode, None);
        let encrypted = c.wrap_app_key(&zeroize::Zeroizing::new([8;32])).await.unwrap();
        let combined = base64::engine::general_purpose::STANDARD.decode(&encrypted).unwrap();
        assert_eq!(combined.len(), 60);
        assert_eq!(&*crypto::decrypt_aead(&combined[12..], &[7;32], &combined[..12], &[]).unwrap(), &[8;32]);
        for legacy in [true, false] {
            let item = c.decode_app_saved_result(RESULT, &response(legacy)).await.unwrap();
            assert_eq!(item.fields["content"]["private"], "synthetic retained result");
        }
        if mode == "opaque" { assert!(matches!(c.native_master_key(), Err(Error::Unavailable { code:"master_key_extraction_unavailable", .. }))); }
    }
}
#[tokio::test]
async fn wrong_root_wrapper_key_ciphertext_and_partial_content_are_rejected() {
    let c = client("opaque", None);
    for kind in ["root", "type", "wrapper", "content", "late_field"] {
        let mut row = response(true);
        match kind {
            "root" => row["root"]["embed_id"] = json!(OWNER),
            "type" => row["key"]["key_type"] = json!("team"),
            "wrapper" => row["key"]["encrypted_embed_key"] = json!(crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap()),
            "content" => row["root"]["encrypted_content"] = json!("invalid ciphertext"),
            "late_field" => { row["root"].as_object_mut().unwrap().remove("skill_id"); },
            _ => unreachable!(),
        }
        assert!(c.decode_app_saved_result(RESULT, &row).await.is_err());
    }
}
#[tokio::test]
async fn pending_wrapper_and_unwrap_recheck_cancel_owner_negative_knowledge_and_master() {
    for unwrap in [false, true] {
        for event in ["operation", "owner", "denial", "master"] {
            let gate = Arc::new((Notify::new(),Notify::new()));
            let c = client("opaque", Some(gate.clone()));
            let cancel = c.operation_cancel.clone();
            let owner = c.task_watch_authority.clone();
            let master = c.master_capability().unwrap();
            let call = tokio::spawn(async move {
                if unwrap { c.decode_app_saved_result(RESULT,&response(true)).await.map(|_| ()) }
                else { c.wrap_app_key(&zeroize::Zeroizing::new([8;32])).await.map(|_| ()) }
            });
            gate.0.notified().await;
            match event {
                "operation" => cancel.cancel(), "owner" => owner.cancel.cancel(),
                "denial" => owner.deny_cached_chat(Some("synthetic-denied")).unwrap(),
                "master" => master.invalidate(), _ => unreachable!(),
            }
            gate.1.notify_one();
            assert!(matches!(call.await.unwrap(),Err(Error::Cancelled)));
        }
    }
}
#[tokio::test]
async fn preexisting_cancel_and_expiry_never_enter_crypto_and_pending_future_can_drop() {
    for expired in [false,true] {
        let mut c = client("opaque", None);
        if expired { c.browser_credentials.as_mut().unwrap().paired_session_expires_at=Some(0); }
        else { c.operation_cancel.cancel(); }
        assert!(c.wrap_app_key(&zeroize::Zeroizing::new([8;32])).await.is_err());
        assert!(c.decode_app_saved_result(RESULT,&response(true)).await.is_err());
    }
    let gate=Arc::new((Notify::new(),Notify::new()));
    let c=client("opaque",Some(gate.clone()));
    let call=tokio::spawn(async move {c.decode_app_saved_result(RESULT,&response(true)).await});
    gate.0.notified().await;
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
}

#[tokio::test]
async fn each_apps_server_field_uses_strict_metadata_format_without_changing_generic_codec() {
    use base64::Engine;
    for mode in ["native", "raw_browser", "opaque"] {
        let c = client(mode,None);
        let key = zeroize::Zeroizing::new([8;32]);
        let wrapped = c.wrap_app_key(&key).await.unwrap();
        let run = AppRun { app:"web".into(),skill:"search".into(),input:json!({"query":"synthetic private input"}),owner:OWNER.into(),result_id:RESULT.into(),key:Some(key),wrapped };
        let payload=app_run_payload(&run,&json!({"results":[{"private":"synthetic result"}]}),"finished").unwrap();
        for (field,cipher,key) in [
            ("encrypted_embed_key",&payload["encrypted_embed_key"],&[7;32]),
            ("encrypted_type",&payload["embeds"][0]["encrypted_type"],&[8;32]),
            ("encrypted_content",&payload["embeds"][0]["encrypted_content"],&[8;32]),
        ] {
            let bytes=base64::engine::general_purpose::STANDARD.decode(cipher.as_str().unwrap()).unwrap();
            let plain=crypto::decrypt_aead(&bytes[12..],key,&bytes[..12],&[]).unwrap();
            assert!(!plain.is_empty(),"{field}");
            if field=="encrypted_embed_key" {assert_eq!(&*plain,&[8;32]);}
            if field=="encrypted_type" {assert_eq!(&*plain,b"app_skill_use");}
            if field=="encrypted_content" {assert!(String::from_utf8_lossy(&plain).contains("synthetic private input"));}
        }
        let generic=crypto::encrypt_combined("generic",&[8;32]).unwrap();
        let bytes=base64::engine::general_purpose::STANDARD.decode(generic).unwrap();
        assert!(bytes.starts_with(b"OM"));
    }
}

/// Product HTTP fixture is executed only by the isolated GitHub product lane.
/// The real shared-library full-run future pauses at accepted billable dispatch.
#[tokio::test]
async fn full_run_owner_or_negative_revocation_keeps_receipt_but_never_publishes_item() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    for event in ["owner", "denial"] {
        for unsaved in [false,true] {
            let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let base=format!("http://{}",listener.local_addr().unwrap());
            let gate=Arc::new((Notify::new(),Notify::new()));
            let peer_gate=gate.clone();
            let writes=Arc::new(std::sync::atomic::AtomicUsize::new(0));
            let peer_writes=writes.clone();
            let peer=tokio::spawn(async move {
                loop {
                    let (mut socket,_)=listener.accept().await.unwrap();
                    let mut bytes=Vec::new(); let mut part=[0;4096];
                    let (end,length)=loop {
                        let n=socket.read(&mut part).await.unwrap(); assert!(n>0);
                        bytes.extend_from_slice(&part[..n]);
                        if let Some(end)=bytes.windows(4).position(|v|v==b"\r\n\r\n") {
                            let headers=std::str::from_utf8(&bytes[..end]).unwrap();
                            let length=headers.lines().filter_map(|v|v.split_once(':')).find(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap()).unwrap_or(0);
                            break (end+4,length);
                        }
                    };
                    while bytes.len()<end+length {let n=socket.read(&mut part).await.unwrap();assert!(n>0);bytes.extend_from_slice(&part[..n]);}
                    let path=std::str::from_utf8(&bytes[..end]).unwrap().lines().next().unwrap().split_whitespace().nth(1).unwrap().to_owned();
                    let body:Value=if length>0 {serde_json::from_slice(&bytes[end..end+length]).unwrap()}else{Value::Null};
                    let (status,response)=match path.as_str() {
                        "/v1/apps/web/skills/search/details"=>(200,json!({"app_id":"web","skill_id":"search","execution_available":true,"input_schema":{"type":"object"}})),
                        "/v1/auth/session"=>(200,json!({"success":true,"ws_token":"synthetic-token","user":{"id":OWNER}})),
                        "/v1/apps/workspace/results"=>{
                            let number=peer_writes.fetch_add(1,std::sync::atomic::Ordering::SeqCst);
                            if unsaved && number>0 {(500,json!({"error":"synthetic unavailable"}))}
                            else {(200,json!({"success":true,"root_embed_id":body["root_embed_id"]}))}
                        },
                        "/v1/apps/web/skills/search"=>{peer_gate.0.notify_one();peer_gate.1.notified().await;(200,json!({"success":true,"data":{"results":[{"private":"synthetic sensitive completion"}]}}))},
                        _=>panic!("unexpected fixture endpoint"),
                    };
                    let response=response.to_string();
                    let header=format!("HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",response.len());
                    socket.write_all(header.as_bytes()).await.unwrap();socket.write_all(response.as_bytes()).await.unwrap();
                }
            });
            let mut c=client("native",None);
            c.session.as_mut().unwrap().api_url=base.clone();
            c.base=url::Url::parse(&base).unwrap();
            let authority=c.task_watch_authority.clone();
            let call=tokio::spawn(async move {c.run_app_skill_with_gate(json!({"app":"web","skill":"search","input":{"query":"synthetic private query"}}),||Ok(())).await});
            gate.0.notified().await;
            if event=="owner" {authority.cancel.cancel();}else{authority.deny_cached_chat(Some("synthetic-denied")).unwrap();}
            gate.1.notify_one();
            assert!(matches!(call.await.unwrap(),Err(Error::Cancelled)));
            assert_eq!(writes.load(std::sync::atomic::Ordering::SeqCst),2,"completed receipt must still be attempted");
            peer.abort();
        }
    }
}
