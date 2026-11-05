//! Actual bounded loopback HTTP/WebSocket peers; authored, runtime UNRUN.
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex, atomic::{AtomicUsize, Ordering}};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const EMBED: &str = "33333333-3333-4333-8333-333333333333";
const RECORD: &str = "44444444-4444-4444-8444-444444444444";
fn page(plain: &str, version: u64) -> Value {
    json!({"embed_id":EMBED,"version_number":version,"rows":[{
        "version_number":version,
        "encrypted_snapshot":crypto::server_fields::encrypt_text(plain,&[8;32],&[]).unwrap(),
        "encrypted_patch":null,
    }]})
}
fn write(version: u64, sealed: bool) -> HistoryWrite<'static> {
    HistoryWrite { embed: EMBED, chat: CHAT, version, key: &[8;32],
        snapshot: (version == 1).then_some("canonical snapshot"), patch: (version > 1).then_some("canonical patch"), owner_hash: "synthetic-owner",
        created_at: 1, recovery_record: sealed.then_some(RECORD), allow_missing_revision: sealed }
}
fn client(api: &str) -> Client {
    Client::new(api, Some(Session {
        api_url:api.into(), session_id:"synthetic-history".into(), cookies:Default::default(),
        ws_token:None, master_key:zeroize::Zeroizing::new([7;32]), hashed_email:"synthetic-owner".into(),
        user_email_salt:String::new(), email_encryption_key:None, created_at:1,
        paired_session_expires_at:None, active_team_id:None,
    })).unwrap()
}
struct Peer {
    api: String, ws: Socket, reads: Arc<AtomicUsize>, frames: Arc<Mutex<Vec<Value>>>,
    http: tokio::task::JoinHandle<()>, socket: tokio::task::JoinHandle<()>,
}
impl Drop for Peer { fn drop(&mut self) { self.http.abort(); self.socket.abort(); } }
impl Peer {
    async fn start(responses: Vec<(u16, Value)>, reply: &'static str, version: u64) -> Self {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api=format!("http://{}",listener.local_addr().unwrap());
        let reads=Arc::new(AtomicUsize::new(0));let observed=reads.clone();
        let http=tokio::spawn(async move {
            for (status, body) in responses {
                let (mut stream,_)=listener.accept().await.unwrap();let mut bytes=Vec::new();
                loop {
                    let mut chunk=[0u8;2048];let n=stream.read(&mut chunk).await.unwrap();assert!(n>0);
                    bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<8192);
                    if bytes.windows(4).any(|part|part==b"\r\n\r\n"){break;}
                }
                let request=std::str::from_utf8(&bytes).unwrap();
                assert!(request.starts_with(&format!("GET /v1/embeds/{EMBED}/versions/{version}?capability=bounded-v1&chat_id={CHAT} HTTP/1.1\r\n")));
                assert!(!request.to_ascii_lowercase().contains("content-length:"));
                observed.fetch_add(1,Ordering::SeqCst);
                let body=body.to_string();
                stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            }
        });
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let address=listener.local_addr().unwrap();
        let frames=Arc::new(Mutex::new(Vec::new()));let observed=frames.clone();
        let socket=tokio::spawn(async move {
            let(stream,_)=listener.accept().await.unwrap();let mut ws=tokio_tungstenite::accept_async(stream).await.unwrap();
            while let Some(Ok(frame))=ws.next().await {
                if !frame.is_text(){continue;}
                let request:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();
                assert_eq!(request["type"],"store_embed_diff");observed.lock().unwrap().push(request.clone());
                let p=&request["payload"];
                if reply=="disconnect"{return;}
                let mut payload=json!({"request_id":p["request_id"],"embed_id":p["embed_id"],"version_number":p["version_number"]});
                let kind=if reply.starts_with("conflict")||reply=="unknown"{
                    payload["code"]=json!(if reply=="unknown"{"some_other_conflict"}else{"embed_diff_conflict"});"error"
                }else{
                    payload["canonical_source"]=json!("version_row");
                    payload["canonical_digest"]=json!(sha256(&json!([p["encrypted_snapshot"],p["encrypted_patch"]]).to_string()));"store_embed_diff_confirmed"
                };
                if reply.ends_with("wrong-version"){payload["version_number"]=json!(version+1);}
                if reply=="conflict-wrong-embed"{payload["embed_id"]=json!(CHAT);}
                if reply=="wrong-digest"{payload["canonical_digest"]=json!("wrong");}
                if reply=="wrong-source"{payload["canonical_source"]=json!("head");}
                if reply=="unrelated-first"{
                    ws.send(Frame::text(json!({"type":"error","payload":{"request_id":"other-request","code":"embed_diff_conflict","embed_id":EMBED,"version_number":version}}).to_string())).await.unwrap();
                }
                ws.send(Frame::text(json!({"type":kind,"payload":payload}).to_string())).await.unwrap();
            }
        });
        let(ws,_)=tokio_tungstenite::connect_async(format!("ws://{address}")).await.unwrap();
        Self {api,ws:super::super::transport::test_socket(ws),reads,frames,http,socket}
    }
    fn counts(&self)->(usize,usize){(self.reads.load(Ordering::SeqCst),self.frames.lock().unwrap().len())}
    async fn persist(&mut self,sealed:bool,version:u64)->Result<String>{
        let mut client=client(&self.api);let scope=AsyncCryptoScope::begin(&client)?;
        tokio::time::timeout(Duration::from_secs(2),client.persist_canonical_embed_diff(&mut self.ws,write(version,sealed),&|client|scope.check_chat(client,CHAT))).await.expect("bounded actual peer operation")
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[test]
fn canonical_page_requires_exact_envelope_and_unique_matching_version() {
    let valid=page("canonical snapshot",1);
    assert!(canonical_history_row(&valid,EMBED,1).is_ok());
    for field in ["embed_id","version_number","rows"]{
        let mut bad=valid.clone();bad.as_object_mut().unwrap().remove(field);
        assert!(canonical_history_row(&bad,EMBED,1).is_err());
    }
    let mut duplicate=valid.clone();duplicate["rows"].as_array_mut().unwrap().push(valid["rows"][0].clone());
    assert!(canonical_history_row(&duplicate,EMBED,1).is_err());
    assert!(canonical_history_row(&valid,CHAT,1).is_err());
    assert!(canonical_history_row(&valid,EMBED,2).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn existing_equivalent_history_adopts_exact_canonical_ciphertext_without_mutation() {
    for sealed in [false,true]{
        let canonical=page("canonical snapshot",1);
        let expected=sha256(&json!([canonical["rows"][0]["encrypted_snapshot"],null]).to_string());
        let mut peer=Peer::start(vec![(200,canonical)],"unused",1).await;
        assert_eq!(peer.persist(sealed,1).await.unwrap(),expected);
        assert_eq!(peer.counts(),(1,0));
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn different_duplicate_wrong_version_and_untyped_canonical_rows_never_write() {
    let valid=page("canonical snapshot",1);
    let mut duplicate=valid.clone();duplicate["rows"].as_array_mut().unwrap().push(valid["rows"][0].clone());
    let mut wrong_embed=valid.clone();wrong_embed["embed_id"]=json!(CHAT);
    let mut wrong_row=valid.clone();wrong_row["rows"][0]["version_number"]=json!(2);
    let mut untyped=valid.clone();untyped["rows"][0]["encrypted_patch"]=json!(false);
    for canonical in [page("different snapshot",1),duplicate,wrong_embed,page("canonical snapshot",2),wrong_row,untyped]{
        for sealed in [false,true]{
            let mut peer=Peer::start(vec![(200,canonical.clone())],"unused",1).await;
            assert!(peer.persist(sealed,1).await.is_err());assert_eq!(peer.counts(),(1,0));
        }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn only_correlated_conflict_rereads_once_and_adopts_equivalent_canonical_ciphertext() {
    for sealed in [false,true]{
        let canonical=page("canonical snapshot",1);let expected=sha256(&json!([canonical["rows"][0]["encrypted_snapshot"],null]).to_string());
        let mut peer=Peer::start(vec![(404,json!({})),(200,canonical.clone())],"conflict",1).await;
        assert_eq!(peer.persist(sealed,1).await.unwrap(),expected);assert_eq!(peer.counts(),(2,1));
        let frames=peer.frames.lock().unwrap();let sent=&frames[0]["payload"];
        assert_ne!(sent["encrypted_snapshot"],canonical["rows"][0]["encrypted_snapshot"]);
        assert_eq!(sent["recovery_record_id"],if sealed{json!(RECORD)}else{Value::Null});
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn conflict_rechecks_canonical_equivalence_identity_and_uniqueness_without_rewrite() {
    let valid=page("canonical snapshot",1);let mut duplicate=valid.clone();duplicate["rows"].as_array_mut().unwrap().push(valid["rows"][0].clone());
    for response in [(200,page("different snapshot",1)),(200,duplicate),(200,page("canonical snapshot",2)),(404,json!({}))]{
        for sealed in [false,true]{
            let mut peer=Peer::start(vec![(404,json!({})),response.clone()],"conflict",1).await;
            assert!(peer.persist(sealed,1).await.is_err());assert_eq!(peer.counts(),(2,1));
        }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn unknown_wrong_identity_receipts_and_unknown_write_outcomes_never_reread_or_retry() {
    for reply in ["unknown","conflict-wrong-version","conflict-wrong-embed","wrong-version","wrong-digest","wrong-source","disconnect"]{
        for sealed in [false,true]{
            let mut peer=Peer::start(vec![(404,json!({}))],reply,1).await;
            assert!(peer.persist(sealed,1).await.is_err(),"{reply}");assert_eq!(peer.counts(),(1,1));
        }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn absence_is_exact_status_and_version_one_snapshot_required_only() {
    for (version,status,body,missing) in [
        (1,404,json!({}),true),(1,409,json!({"detail":"snapshot_required"}),true),
        (1,400,json!({}),false),(1,410,json!({}),false),(1,403,json!({}),false),
        (1,409,json!({"detail":"other"}),false),(2,409,json!({"detail":"snapshot_required"}),false),
    ]{
        let mut peer=Peer::start(vec![(status,body)],"unrelated-first",version).await;
        let result=peer.persist(true,version).await;
        assert_eq!(result.is_ok(),missing);assert_eq!(peer.counts(),(1,usize::from(missing)));
    }
    // Ordinary streamed missing later versions remain pending, never mutated.
    let mut peer=Peer::start(vec![(404,json!({}))],"unused",2).await;
    assert!(matches!(peer.persist(false,2).await,Err(Error::Invalid(_))));assert_eq!(peer.counts(),(1,0));
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn scope_revocation_after_read_blocks_mutation_and_after_conflict_blocks_adoption() {
    for fail_check in [2,6,8]{
        let mut peer=Peer::start(vec![(404,json!({})),(200,page("canonical snapshot",1))],"conflict",1).await;
        let mut client=client(&peer.api);let checks=AtomicUsize::new(0);let scope=AsyncCryptoScope::begin(&client).unwrap();
        let result=tokio::time::timeout(Duration::from_secs(2),client.persist_canonical_embed_diff(&mut peer.ws,write(1,true),&|client|{
            if checks.fetch_add(1,Ordering::SeqCst)+1==fail_check {client.operation_cancel.cancel();}
            scope.check_chat(client,CHAT)
        })).await.unwrap();
        assert!(matches!(result,Err(Error::Cancelled)));
        assert_eq!(peer.counts(),match fail_check{2=>(1,0),6=>(1,1),8=>(2,1),_=>unreachable!()});
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only,auth.session.authoritative-enforcement
#[tokio::test]
async fn sealed_later_revision_conflict_adopts_exact_canonical_patch_digest() {
    let canonical=json!({"embed_id":EMBED,"version_number":2,"rows":[{
        "version_number":2,"encrypted_snapshot":null,
        "encrypted_patch":crypto::server_fields::encrypt_text("canonical patch",&[8;32],&[]).unwrap(),
    }]});
    let expected=sha256(&json!([null,canonical["rows"][0]["encrypted_patch"]]).to_string());
    let mut peer=Peer::start(vec![(404,json!({})),(200,canonical)],"conflict",2).await;
    assert_eq!(peer.persist(true,2).await.unwrap(),expected);assert_eq!(peer.counts(),(2,1));
    let frames=peer.frames.lock().unwrap();assert_eq!(frames[0]["payload"]["version_number"],2);
    assert_eq!(frames[0]["payload"]["recovery_record_id"],RECORD);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.authoritative-enforcement
#[tokio::test]
async fn generic_get_retains_original_status_errors_without_history_absence_policy() {
    for status in [400,404,409,410] {
        let mut peer=Peer::start(vec![(status,json!({"detail":"snapshot_required"}))],"unused",1).await;
        let mut client=client(&peer.api);
        let path=format!("/v1/embeds/{EMBED}/versions/1?capability=bounded-v1&chat_id={CHAT}");
        let result=tokio::time::timeout(Duration::from_secs(2),client.request(Method::GET,&path,None)).await.unwrap();
        if status==409 { assert!(matches!(result,Err(Error::Conflict))); }
        else { assert!(matches!(result,Err(Error::Invalid(_)))); }
        assert_eq!(peer.counts(),(1,0));
    }
}
