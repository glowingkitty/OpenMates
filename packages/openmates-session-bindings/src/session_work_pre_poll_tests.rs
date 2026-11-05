//! Genuine prepared Bridge operation before first poll; actual loopback IO, UNRUN.
use super::*;
use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::{TcpListener, TcpStream}, sync::oneshot};
use std::sync::atomic::AtomicUsize;
use tokio::time::{timeout, Duration};
fn ok<T>(result: Result<T>) -> T { match result { Ok(value) => value, Err(e) => panic!("synthetic bridge refused: {}", e.code) } }
struct Peer { endpoint: String, generation: Arc<AtomicUsize>, requests: Arc<AtomicUsize>, writes: Arc<AtomicUsize>, stop: oneshot::Sender<()>, task: tokio::task::JoinHandle<()> }
impl Peer {
    async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("synthetic loopback");
        let endpoint = format!("http://{}", listener.local_addr().expect("address"));
        let generation = Arc::new(AtomicUsize::new(0)); let current = generation.clone();
        let requests = Arc::new(AtomicUsize::new(0)); let count = requests.clone();
        let writes = Arc::new(AtomicUsize::new(0)); let posted = writes.clone();
        let (stop, mut stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                let mut socket = tokio::select! { _ = &mut stopped => break, accepted = listener.accept() => accepted.expect("actual connection").0 };
                let (head, input) = read(&mut socket).await;
                count.fetch_add(1, Ordering::AcqRel);
                let identity = current.load(Ordering::Acquire);
                assert!(head.lines().any(|line| line == format!("cookie: auth_refresh_token=synthetic-prepoll-{identity}")), "actual original cookie identity");
                assert!(!head.to_ascii_lowercase().contains("authorization:"));
                assert!(head.lines().any(|line| line.eq_ignore_ascii_case("x-openmates-sdk: rust")));
                let path = head.lines().next().expect("request line");
                let output = if path.starts_with("POST /v1/auth/session ") {
                    assert_eq!(input, json!({"session_id":format!("synthetic-prepoll-{identity}")}));
                    json!({"success":true,"user":{"id":format!("0000000{}-1111-4111-8111-111111111111",identity+1)},"ws_token":format!("synthetic-ws-{identity}")})
                } else {
                    assert!(path.starts_with("POST /v1/user-tasks "), "only genuine Task create is allowed");
                    assert!(input["encrypted_title"].as_str().is_some_and(|v| !v.is_empty()));
                    assert!(input.get("title").is_none());
                    assert_eq!(input["task_id"], "33333333-2222-4222-8222-222222222222");
                    posted.fetch_add(1, Ordering::AcqRel);
                    json!({"task":input})
                };
                let body = serde_json::to_vec(&output).expect("synthetic response");
                socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).as_bytes()).await.expect("actual headers");
                socket.write_all(&body).await.expect("actual body");
                socket.flush().await.expect("actual flush");
            }
        });
        Self { endpoint, generation, requests, writes, stop, task }
    }
    fn session(&self, generation: usize) -> String {
        let session = Session { api_url:self.endpoint.clone(), session_id:format!("synthetic-prepoll-{generation}"), cookies:BTreeMap::from([("auth_refresh_token".into(),format!("synthetic-prepoll-{generation}"))]), ws_token:None, master_key:Zeroizing::new([generation as u8;32]), hashed_email:"synthetic-email".into(), user_email_salt:"synthetic-salt".into(), email_encryption_key:None, created_at:1, paired_session_expires_at:None, active_team_id:None };
        serde_json::to_string(&session).expect("real typed session")
    }
    async fn close(self) { self.stop.send(()).expect("stop peer"); self.task.await.expect("actual wire assertions"); }
}
async fn read(socket:&mut TcpStream) -> (String,Value) {
    let mut bytes=Vec::new(); let end=loop { let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("request bytes");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<=2*1024*1024);if let Some(i)=bytes.windows(4).position(|p|p==b"\r\n\r\n"){break i+4;} };
    let head=std::str::from_utf8(&bytes[..end]).expect("headers").to_owned();
    let length=head.lines().find_map(|line|line.split_once(':').filter(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().expect("length"))).unwrap_or(0);assert!(length<=1024*1024);
    while bytes.len()<end+length {let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("body");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);}
    (head,serde_json::from_slice(&bytes[end..end+length]).expect("typed request JSON"))
}
fn create() -> Request { Request::TaskCreate(TaskCreate {title:"Synthetic queued private Task".into(),task_id:Some("33333333-2222-4222-8222-222222222222".into()),..Default::default()},TaskFilters {personal:true,..Default::default()}) }
async fn case(replace:bool,drop_old:bool) {
    let peer=Peer::start().await;
    let bridge=ok(SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":peer.endpoint,"enhanced_privacy":false,"allow_private_operations":false}).to_string()));
    ok(bridge.import_session(peer.session(0)).await);
    // This is the exact factory invoked synchronously by both foreign wrappers.
    let old=ok(bridge.prepare_work(create()));
    let original=old.guard.token();
    assert_eq!(bridge.state.work_operations.lock().expect("registry").len(),1);
    let queued=old.run(); // genuine original future remains completely UNPOLLED
    if replace { peer.generation.store(1,Ordering::Release);ok(bridge.import_session(peer.session(1)).await); }
    else { ok(bridge.cancel()); }
    assert!(original.is_cancelled());
    assert_eq!(peer.requests.load(Ordering::Acquire),0,"old A has performed zero auth or Task IO");
    let fresh=ok(bridge.prepare_work(create()));let fresh_token=fresh.guard.token();
    if drop_old { drop(queued); } else { assert_eq!(queued.await.err().map(|e|e.code),Some("cancelled")); }
    assert!(!fresh_token.is_cancelled(),"late A must not retire B");
    assert_eq!(peer.requests.load(Ordering::Acquire),0,"refusal happened before actual HTTP");
    ok(bridge.validate_session().await); // actual B authentication, only after old A zero-IO refusal
    let result=ok(fresh.run().await);let result:Value=serde_json::from_str(&result).expect("actual decrypted Task");
    assert_eq!(result["title"],"Synthetic queued private Task");
    assert_eq!(peer.writes.load(Ordering::Acquire),1,"only the fresh B Task POST is admitted");
    assert_eq!(peer.requests.load(Ordering::Acquire),2,"fresh B auth then exactly one encrypted Task create");
    assert!(bridge.state.work_operations.lock().expect("registry").is_empty());
    peer.close().await;
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn foreign_prepared_task_cancel_before_first_poll_has_zero_old_io_and_fresh_success() { timeout(Duration::from_secs(5),case(false,false)).await.expect("HTTP watchdog"); }
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn foreign_prepared_task_import_b_before_first_poll_cannot_write_as_b() { timeout(Duration::from_secs(5),case(true,false)).await.expect("HTTP watchdog"); }
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn dropping_retired_unpolled_a_cannot_retire_fresh_b() { timeout(Duration::from_secs(5),case(true,true)).await.expect("HTTP watchdog"); }
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[test]
fn native_work_preflight_rejects_before_registration() {
    let bridge=ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#));
    assert_eq!(bridge.prepare_work(Request::TaskDelete("synthetic".into(),false,TaskFilters{personal:true,..Default::default()})).err().map(|e|e.code),Some("invalid_argument"));
    assert!(bridge.state.work_operations.lock().expect("registry").is_empty());
}
