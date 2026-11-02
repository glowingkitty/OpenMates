//! AUTHORED UNRUN: real native binary against an isolated controlled HTTP/WS peer.
//! Genuine native Store credentials and encrypted cache; no CLI response shim.
//! Fresh remote owner/key/content checks execute real Rust AES/share operations.
//! Peer identity collisions and old aliases deliberately differ from map order.
//! No real account, user data, keyring, AI service or foreign runtime is used.
//! This is test source, never claimed successful compiler/runtime evidence.
use aes_gcm::{Aes256Gcm,Nonce,aead::{Aead,KeyInit}};
use base64::{Engine as _,engine::general_purpose::STANDARD};
use futures_util::{SinkExt,StreamExt};
use openmates::storage::{CredentialBackend,KeyringFailure,Session,Store};
use serde_json::{Value,json};
use sha2::{Digest,Sha256};
use std::{collections::BTreeMap,path::Path,sync::{Arc,atomic::{AtomicBool,AtomicUsize,Ordering}},time::Duration};
use tokio::io::{AsyncReadExt,AsyncWriteExt};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const FIRST:&str="33333333-ffff-4333-8333-333333333333";
const SECOND:&str="33333333-0000-4333-8333-333333333333";
const ALIAS:&str="55555555-5555-4555-8555-555555555555";
fn encrypted(bytes:&[u8],key:&[u8;32])->String{
    use rand::RngCore;
    let mut iv=[0;12];rand::rngs::OsRng.fill_bytes(&mut iv);
    let mut wire=iv.to_vec();wire.extend(Aes256Gcm::new_from_slice(key).unwrap().encrypt(Nonce::from_slice(&iv),bytes).unwrap());STANDARD.encode(wire)
}
fn response(id:&str)->Value{
    json!({"embed_id":id,"user_id":OWNER,"already_encrypted":true,"encryption_mode":"client",
        "chat_id":"22222222-2222-4222-8222-222222222222","status":"finished","parent_embed_id":null,
        "type":encrypted(b"code",&[8;32]),"content":encrypted(b"{\"text\":\"Synthetic saved embed\"}",&[8;32]),
        "embed_keys":[{"hashed_embed_id":format!("{:x}",Sha256::digest(id.as_bytes())),"hashed_user_id":format!("{:x}",Sha256::digest(OWNER.as_bytes())),"key_type":"master","encrypted_embed_key":encrypted(&[8;32],&[9;32])}],
        "embed_keys_has_more_after":false,"oversized_embed_key_id":null,"createdAt":12,"is_private":true})
}
fn assert_fragment(url:&str){
    let blob=url.split_once("#key=").unwrap().1;
    let wire=base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(blob).unwrap();assert!(wire.len()>=28);
    let mut key=Zeroizing::new([0;32]);pbkdf2::pbkdf2_hmac::<Sha256>(FIRST.as_bytes(),b"openmates-share-v1",100_000,key.as_mut());
    let plaintext=Zeroizing::new(Aes256Gcm::new_from_slice(key.as_ref()).unwrap().decrypt(Nonce::from_slice(&wire[..12]),&wire[12..]).unwrap());
    let fields:url::form_urlencoded::Parse<'_>=url::form_urlencoded::parse(&plaintext);
    let fields:BTreeMap<_,_>=fields.into_owned().collect();assert_eq!(fields["embed_encryption_key"],STANDARD.encode([8;32]));assert_eq!(fields["duration_seconds"],"0");assert_eq!(fields["pwd"],"0");assert!(fields["generated_at"].parse::<u64>().unwrap()>0);
}
struct NoKeyring;
impl CredentialBackend for NoKeyring {
    fn get(&self,_:&str)->Result<Zeroizing<Vec<u8>>,KeyringFailure>{Err(KeyringFailure::Unavailable)}
    fn set(&self,_:&str,_:&[u8])->Result<(),KeyringFailure>{Err(KeyringFailure::Unavailable)}
    fn delete(&self,_:&str)->Result<(),KeyringFailure>{Err(KeyringFailure::Unavailable)}
}
struct Peer{api:String,sync:Arc<AtomicUsize>,reads:Arc<AtomicUsize>,deny:Arc<AtomicBool>,stop:CancellationToken,task:tokio::task::JoinHandle<()>}
impl Peer{
    async fn start()->Self{
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let api=format!("http://{}",listener.local_addr().unwrap());
        let sync=Arc::new(AtomicUsize::new(0));let reads=Arc::new(AtomicUsize::new(0));let deny=Arc::new(AtomicBool::new(false));let stop=CancellationToken::new();
        let(s,r,d,stopping)=(sync.clone(),reads.clone(),deny.clone(),stop.clone());
        let task=tokio::spawn(async move{let mut children=tokio::task::JoinSet::new();loop{
            let(mut stream,_)=tokio::select!{_=stopping.cancelled()=>break,v=listener.accept()=>v.unwrap()};
            let(s,r,d)=(s.clone(),r.clone(),d.clone());children.spawn(async move{
                let mut head=[0;8192];let n=loop{let n=stream.peek(&mut head).await.unwrap();if n==0{return}if head[..n].contains(&b'\n'){break n}tokio::task::yield_now().await;};
                if String::from_utf8_lossy(&head[..n]).starts_with("GET /v1/ws?"){
                    let mut ws=tokio_tungstenite::accept_async(stream).await.unwrap();
                    let first=ws.next().await.unwrap().unwrap();let lifecycle:Value=serde_json::from_str(first.to_text().unwrap()).unwrap();assert_eq!(lifecycle["type"],"native_client_lifecycle");
                    while let Some(event)=ws.next().await{let event=event.unwrap();if event.is_close(){break}if !event.is_text(){continue}let frame:Value=serde_json::from_str(event.to_text().unwrap()).unwrap();
                        let replies=match frame["type"].as_str().unwrap(){
                            "phased_sync_request"=>{s.fetch_add(1,Ordering::SeqCst);vec![
                                json!({"type":"phase_1b_chat_content_ready","payload":{"chats":[],"embeds":[{"embed_id":FIRST,"id":ALIAS},{"embed_id":SECOND},{"embed_id":FIRST,"id":FIRST}]}}),
                                json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[],"total_chat_count":0}}),
                                json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
                                json!({"type":"phased_sync_complete","payload":{"phase":"all"}})]},
                            "request_embed"=>{r.fetch_add(1,Ordering::SeqCst);assert_eq!(frame["payload"]["embed_id"],FIRST);if d.load(Ordering::SeqCst){vec![json!({"type":"error","payload":{"status":403}})]}else{vec![json!({"type":"send_embed_data","payload":response(FIRST)})]}},
                            other=>panic!("unexpected fixed peer event {other}"),
                        };
                        for reply in replies{ws.send(tokio_tungstenite::tungstenite::Message::Text(reply.to_string().into())).await.unwrap();}
                    }let _=ws.close(None).await;return;
                }
                let mut bytes=vec![];loop{let mut part=[0;4096];let n=stream.read(&mut part).await.unwrap();assert!(n>0&&bytes.len()+n<16384);bytes.extend_from_slice(&part[..n]);if let Some(end)=bytes.windows(4).position(|w|w==b"\r\n\r\n"){
                    let header=String::from_utf8_lossy(&bytes[..end]);let length=header.lines().find_map(|l|l.to_ascii_lowercase().strip_prefix("content-length:").map(|s|s.trim().parse::<usize>().unwrap())).unwrap_or(0);if bytes.len()>=end+4+length{break}
                }}
                let req=String::from_utf8(bytes).unwrap();assert!(req.starts_with("POST /v1/auth/session "));assert!(req.to_ascii_lowercase().contains("cookie:"));
                let body=json!({"success":true,"ws_token":"synthetic-ws","user":{"id":OWNER,"username":"Synthetic"}}).to_string();
                stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            });
        }children.abort_all();while let Some(result)=children.join_next().await{if let Err(error)=result{assert!(error.is_cancelled());}}});
        Self{api,sync,reads,deny,stop,task}
    }
    fn seed(&self,path:&Path){
        let store=Store::with_backend(path.into(),Arc::new(NoKeyring)).unwrap();
        store.save_session(&Session{api_url:self.api.clone(),session_id:OWNER.into(),cookies:BTreeMap::from([("auth_refresh_token".into(),"synthetic-cookie".into())]),ws_token:Some("synthetic-ws".into()),master_key:Zeroizing::new([9;32]),hashed_email:"synthetic-owner".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None},None).unwrap();
        // Deliberately no cache: cold absence is genuine, not a caller flag.
    }
    async fn run(&self,path:&Path,selector:&str)->std::process::Output{
        self.run_args(path,&["embeds","share",selector,"--json"]).await
    }
    async fn run_args(&self,path:&Path,args:&[&str])->std::process::Output{
        let mut command=tokio::process::Command::new(env!("CARGO_BIN_EXE_openmates"));command.env_clear().env("PATH","").env("HOME",path).env("XDG_CONFIG_HOME",path).env("XDG_DATA_HOME",path).env("XDG_CACHE_HOME",path).env("LANG","C.UTF-8")
            .args(["--api-url",&self.api,"--state-dir",path.to_str().unwrap()]).args(args).stdin(std::process::Stdio::null()).kill_on_drop(true);
        tokio::time::timeout(Duration::from_secs(30),command.output()).await.unwrap().unwrap()
    }
    async fn finish(self){self.stop.cancel();self.task.await.unwrap();}
}
// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.surface.semantic-parity,auth.session.isolation,sdk.encryption.local-only
#[tokio::test]
async fn real_binary_after_whoami_persist_cold_sync_then_cache_reuses_first_collision_and_old_alias(){
    let peer=Peer::start().await;
    let mut state_builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        state_builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    let state = state_builder.tempdir().unwrap();
    peer.seed(state.path());
    // Genuine normal native whoami admission and FINAL persist happens in a
    // separate real executable process before the first share. Credentials-only
    // seed alone cannot substitute for this user-reachable persistence seam.
    let whoami=peer.run_args(state.path(),&["whoami","--json"]).await;assert!(whoami.status.success(),"initial whoami failed");assert!(whoami.stderr.is_empty());assert_eq!(peer.sync.load(Ordering::SeqCst),0);
    let runtime=openmates::runtime_store::RuntimeStore::new(Some(state.path().into()),false).await.unwrap();
    let saved=runtime.load(None).await.unwrap().unwrap();let snapshot=runtime.read_cache(saved.hashed_email.clone(),openmates::session_runtime::cache_key(&saved),saved.master_key.clone()).await.unwrap().unwrap();
    assert_eq!(snapshot["saved_embed_order_v1"],json!({"version":1,"state":"unsynced"}));drop(snapshot);drop(runtime);
    let first=peer.run(state.path(),"33333333").await;assert!(first.status.success(),"cold share failed");assert!(first.stderr.is_empty());
    let value:Value=serde_json::from_slice(&first.stdout).unwrap();assert_eq!(value["embed_id"],"33333333");assert_eq!(value["expires"],0);assert_eq!(value["password_protected"],false);assert!(value["url"].as_str().unwrap().contains(&format!("/embed/{FIRST}#key=")));assert_eq!(peer.sync.load(Ordering::SeqCst),1);assert_fragment(value["url"].as_str().unwrap());
    let alias=peer.run(state.path(),"55555555").await;assert!(alias.status.success(),"warm alias share failed");let value:Value=serde_json::from_slice(&alias.stdout).unwrap();assert_eq!(value["embed_id"],"55555555");assert!(value["url"].as_str().unwrap().contains(FIRST));assert_eq!(peer.sync.load(Ordering::SeqCst),1);assert_eq!(peer.reads.load(Ordering::SeqCst),2);
    peer.deny.store(true,Ordering::SeqCst);let denied=peer.run(state.path(),"33333333").await;assert_eq!(denied.status.code(),Some(1));assert!(denied.stdout.is_empty());assert!(!String::from_utf8_lossy(&denied.stderr).contains("#key="));assert_eq!(peer.sync.load(Ordering::SeqCst),1);assert_eq!(peer.reads.load(Ordering::SeqCst),3);peer.finish().await;
}
