//! Real prepared mutable-session transitions; bounded synthetic HTTP, UNRUN.
use super::*;
use tokio::{io::{AsyncReadExt,AsyncWriteExt},net::{TcpListener,TcpStream},sync::oneshot,time::{timeout,Duration}};
use std::sync::atomic::AtomicUsize;
fn ok<T>(result:Result<T>)->T { match result { Ok(v)=>v,Err(e)=>panic!("synthetic transition refused: {}",e.code) } }
struct Peer { endpoint:String, requests:Arc<AtomicUsize>, stop:oneshot::Sender<()>, task:tokio::task::JoinHandle<()> }
impl Peer {
    async fn start()->Self {
        let listener=TcpListener::bind("127.0.0.1:0").await.expect("local peer");
        let endpoint=format!("http://{}",listener.local_addr().expect("address"));let requests=Arc::new(AtomicUsize::new(0));let seen=requests.clone();let(stop,mut stopped)=oneshot::channel();
        let task=tokio::spawn(async move { loop {
            let mut socket=tokio::select!{_= &mut stopped=>break,accepted=listener.accept()=>accepted.expect("actual connection").0};
            let(head,body)=read(&mut socket).await;seen.fetch_add(1,Ordering::AcqRel);
            assert!(head.lines().any(|v|v.eq_ignore_ascii_case("cookie: auth_refresh_token=synthetic-auth-b")),"actual B credential only");
            assert!(!head.to_ascii_lowercase().contains("authorization:"));
            assert!(head.lines().next().expect("request line").starts_with("POST /v1/auth/session "));
            assert_eq!(body,json!({"session_id":"synthetic-auth-b"}));
            respond(&mut socket,&json!({"success":true,"user":{"id":"22222222-1111-4111-8111-111111111111"},"ws_token":"synthetic-b-ws"})).await;
        }});
        Self{endpoint,requests,stop,task}
    }
    async fn close(self){self.stop.send(()).expect("stop");self.task.await.expect("actual peer assertions");}
}
async fn read(socket:&mut TcpStream)->(String,Value) {
    let mut bytes=Vec::new();let end=loop{let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("headers");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<=2*1024*1024);if let Some(i)=bytes.windows(4).position(|p|p==b"\r\n\r\n"){break i+4;}};
    let head=std::str::from_utf8(&bytes[..end]).expect("header encoding").to_owned();let len=head.lines().find_map(|line|line.split_once(':').filter(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().expect("length"))).unwrap_or(0);assert!(len<=1024*1024);
    while bytes.len()<end+len{let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("body");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);}
    (head,serde_json::from_slice(&bytes[end..end+len]).expect("actual JSON"))
}
async fn respond(socket:&mut TcpStream,value:&Value) {let raw=serde_json::to_vec(value).expect("response");socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await.expect("headers");socket.write_all(&raw).await.expect("body");socket.flush().await.expect("flush");}
fn bridge(endpoint:&str)->SessionBridge {ok(SessionBridge::new(&json!({"api_url":endpoint,"app_url":endpoint,"enhanced_privacy":false,"allow_private_operations":false}).to_string()))}
fn session(endpoint:&str,name:&str)->String {serde_json::to_string(&Session{api_url:endpoint.into(),session_id:format!("synthetic-auth-{name}"),cookies:BTreeMap::from([("auth_refresh_token".into(),format!("synthetic-auth-{name}"))]),ws_token:None,master_key:Zeroizing::new([if name=="b"{2}else{1};32]),hashed_email:format!("synthetic-{name}"),user_email_salt:"synthetic-salt".into(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None}).expect("genuine typed Session")}
#[derive(Clone,Copy)] enum Kind {Import,Password,Team,Logout}
async fn stale_case(kind:Kind) {
    let peer=Peer::start().await;let b=bridge(&peer.endpoint);ok(b.import_session(session(&peer.endpoint,"a")).await);
    let old=ok(match kind {
        Kind::Import=>b.prepare_import_session(session(&peer.endpoint,"a")),
        Kind::Password=>b.prepare_login_password("synthetic-a@example.invalid".into(),"synthetic-password".into(),None,openmates_sdk::PasswordLoginOptions{stay_logged_in:true}),
        Kind::Team=>b.prepare_set_team(Some("33333333-1111-4111-8111-111111111111".into())),
        Kind::Logout=>b.prepare_logout(),
    });
    // Both adapters capture this real transition before scheduling its future.
    let queued=old.run_unit(); // remains UNPOLLED until genuine B import completes
    ok(b.import_session(session(&peer.endpoint,"b")).await);
    assert_eq!(queued.await.err().map(|e|e.code),Some("cancelled"));
    assert_eq!(peer.requests.load(Ordering::Acquire),0,"no obsolete A login/logout/auth IO");
    let before:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("current exact B snapshot");
    assert_eq!(before["session"]["session_id"],"synthetic-auth-b");assert!(before["session"]["active_team_id"].is_null());
    ok(b.validate_session().await); // actual B auth proves its original credentials survived
    let team="44444444-1111-4111-8111-111111111111";
    ok(ok(b.prepare_set_team(Some(team.into()))).run_unit().await);
    let after:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("real B current snapshot");assert_eq!(after["session"]["session_id"],"synthetic-auth-b");assert_eq!(after["session"]["active_team_id"],team);
    assert_eq!(peer.requests.load(Ordering::Acquire),1,"only fresh B actual authentication");peer.close().await;
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn original_queued_import_never_overwrites_completed_b(){timeout(Duration::from_secs(5),stale_case(Kind::Import)).await.expect("watchdog");}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn original_queued_password_never_logs_in_after_completed_b(){timeout(Duration::from_secs(5),stale_case(Kind::Password)).await.expect("watchdog");}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn original_queued_team_never_mutates_completed_b(){timeout(Duration::from_secs(5),stale_case(Kind::Team)).await.expect("watchdog");}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn original_queued_logout_never_forgets_or_logs_out_completed_b(){timeout(Duration::from_secs(5),stale_case(Kind::Logout)).await.expect("watchdog");}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn pending_transition_refuses_work_instead_of_using_previous_client() {
    let b=bridge("http://127.0.0.1:1");ok(b.import_session(session("http://127.0.0.1:1","a")).await);
    let old=ok(b.prepare_import_session(session("http://127.0.0.1:1","a")));
    let new=ok(b.prepare_import_session(session("http://127.0.0.1:1","b")));
    assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"));
    drop(old);assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"),"late A cannot clear B pending negative");
    ok(new.run_unit().await);let admitted=ok(b.admit_work());drop(admitted);
    let snapshot:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("snapshot");assert_eq!(snapshot["session"]["session_id"],"synthetic-auth-b");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn malformed_import_retires_old_guard_without_claiming_new_identity() {
    let b=bridge("http://127.0.0.1:1");ok(b.import_session(session("http://127.0.0.1:1","a")).await);let old=ok(b.admit_work());
    assert_eq!(b.prepare_import_session("malformed synthetic session".into()).err().map(|e|e.code),Some("invalid_argument"));
    assert!(old.token().is_cancelled());assert!(super::super::work::work_authority(&old).is_err());
    let snapshot:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("snapshot");assert_eq!(snapshot["session"]["session_id"],"synthetic-auth-a");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[test]
fn queued_password_scratch_wipes_on_unpolled_drop_and_cannot_clear_b_pending() {
    let b=bridge("http://127.0.0.1:1");let mut old=ok(b.prepare_login_password("synthetic-email".into(),"synthetic-private-password".into(),Some("synthetic-tfa".into()),openmates_sdk::PasswordLoginOptions::default()));
    let probe=Arc::new(Mutex::new(vec![]));if let Action::Password{email,password,tfa,..}=&mut old.action {email.probe=Some(probe.clone());password.probe=Some(probe.clone());tfa.as_mut().expect("TFA").probe=Some(probe.clone());}else{panic!("real password preparation");}
    let queued=old.run_string();let new=ok(b.prepare_set_team(None));drop(queued);assert_eq!(*probe.lock().expect("scratch"),vec![true,true,true]);assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"));drop(new);assert!(b.admit_work().is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn close_is_terminal_before_first_poll_and_awaits_actual_client_cleanup() {
    let b=bridge("http://127.0.0.1:1");ok(b.import_session(session("http://127.0.0.1:1","b")).await);let held=b.state.client.lock().await;let closing=ok(b.prepare_close());
    assert!(b.state.closed.load(Ordering::Acquire));assert_eq!(b.admit_work().err().map(|e|e.code),Some("cancelled"));assert_eq!(b.prepare_import_session(session("http://127.0.0.1:1","a")).err().map(|e|e.code),Some("cancelled"));
    let future=closing.run();drop(held);ok(future.await);assert!(b.state.client.lock().await.session().is_none());
    ok(b.close().await); // idempotent finally-close remains a successful real drain
    assert!(b.state.client.lock().await.session().is_none());
}
async fn drain_case() {
    let listener=TcpListener::bind("127.0.0.1:0").await.expect("actual peer");let endpoint=format!("http://{}",listener.local_addr().expect("address"));
    let(entered,headers_received)=oneshot::channel();let(release,continue_body)=oneshot::channel();
    let peer=tokio::spawn(async move {
        let(mut socket,_)=listener.accept().await.expect("actual logout");let(head,body)=read(&mut socket).await;
        assert!(head.lines().next().expect("request").starts_with("POST /v1/auth/logout "));assert!(head.lines().any(|v|v.eq_ignore_ascii_case("cookie: auth_refresh_token=synthetic-auth-a")));assert_eq!(body,json!({}));
        let raw=br#"{"success":true}"#;socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await.expect("actual headers");socket.flush().await.expect("flush");entered.send(()).expect("held actual body");continue_body.await.expect("body release");socket.write_all(raw).await.expect("actual body drain");socket.flush().await.expect("body flush");
    });
    let b=bridge(&endpoint);ok(b.import_session(session(&endpoint,"a")).await);
    let logout=ok(b.prepare_logout());let abandoned=tokio::spawn(logout.run_unit());headers_received.await.expect("actual logout entered");
    abandoned.abort();assert!(abandoned.await.err().expect("outer host future abandoned").is_cancelled());
    // The driver clone owns the pending lifetime after the host future is gone.
    assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"));
    assert!(b.state.client.try_lock().is_err(),"actual original Client still held through HTTP body settlement");
    let replacement=ok(b.prepare_import_session(session(&endpoint,"b")));let imported=tokio::spawn(replacement.run_unit());
    assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"));release.send(()).expect("release original response");ok(imported.await.expect("B original join"));peer.await.expect("actual logout wire oracle");
    let snapshot:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("exact B state");assert_eq!(snapshot["session"]["session_id"],"synthetic-auth-b");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn abandoned_started_logout_retains_pending_and_drains_actual_http_before_b() {timeout(Duration::from_secs(5),drain_case()).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn synchronous_identity_reservation_cannot_interleave_locked_original_admission() {
    let b=bridge("http://127.0.0.1:1");ok(b.import_session(session("http://127.0.0.1:1","a")).await);let original=ok(b.admit_work());let epoch=b.state.identity_epoch.load(Ordering::Acquire);
    let identity=ok(b.identity_admission());let other=b.clone();let(blocked,observed)=std::sync::mpsc::sync_channel(1);let(prepared,receive)=std::sync::mpsc::sync_channel(1);
    let thread=std::thread::spawn(move||{
        assert!(matches!(other.state.identity_transitions.try_lock(),Err(std::sync::TryLockError::WouldBlock)));
        blocked.send(()).expect("actual identity reservation contention");
        prepared.send(ok(other.prepare_import_session(session("http://127.0.0.1:1","b")))).expect("real prepared B");
    });
    observed.recv_timeout(Duration::from_secs(1)).expect("real lock contention");assert_eq!(b.state.identity_epoch.load(Ordering::Acquire),epoch);assert!(!original.token().is_cancelled());drop(identity);
    let replacement=receive.recv_timeout(Duration::from_secs(1)).expect("B after original critical section");thread.join().expect("concurrent entry");assert!(original.token().is_cancelled());assert_eq!(b.admit_work().err().map(|e|e.code),Some("conflict"));ok(replacement.run_unit().await);
    let snapshot:Value=serde_json::from_str(&ok(b.export_session(true).await)).expect("genuine B snapshot");assert_eq!(snapshot["session"]["session_id"],"synthetic-auth-b");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn superseded_password_refusal_wipes_queued_owned_scratch_before_core_entry() {
    let b=bridge("http://127.0.0.1:1");let mut old=ok(b.prepare_login_password("synthetic-email".into(),"synthetic-private-password".into(),None,openmates_sdk::PasswordLoginOptions::default()));let probe=Arc::new(Mutex::new(vec![]));
    if let Action::Password{password,..}=&mut old.action {password.probe=Some(probe.clone());}else{panic!("actual password preparation");}
    let replacement=ok(b.prepare_import_session(session("http://127.0.0.1:1","b")));ok(replacement.run_unit().await);assert_eq!(old.run_string().await.err().map(|e|e.code),Some("cancelled"));assert_eq!(*probe.lock().expect("scratch"),vec![true]);
}


// Hold actual original HTTP body settlement, not a synthetic auth-complete flag.
// Latest B preparation is then dropped/refused while old A still owns Client.
async fn latest_replacement_drop_during_actual_drain(malformed: bool) {
    let listener=TcpListener::bind("127.0.0.1:0").await.expect("actual bounded peer");
    let endpoint=format!("http://{}",listener.local_addr().expect("address"));
    let requests=Arc::new(AtomicUsize::new(0));let observed=requests.clone();
    let(entered,headers_received)=oneshot::channel();let(release,continue_body)=oneshot::channel();
    let peer=tokio::spawn(async move {
        let(mut a,_)=listener.accept().await.expect("actual original logout");let(head,body)=read(&mut a).await;
        observed.fetch_add(1,Ordering::AcqRel);
        assert!(head.lines().next().expect("request").starts_with("POST /v1/auth/logout "));
        assert!(head.lines().any(|v|v.eq_ignore_ascii_case("cookie: auth_refresh_token=synthetic-auth-a")));
        assert_eq!(body,json!({}));
        let raw=br#"{"success":true}"#;
        a.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await.expect("actual headers");
        a.flush().await.expect("flush");entered.send(()).expect("original body held");
        continue_body.await.expect("actual drain release");a.write_all(raw).await.expect("original body");a.flush().await.expect("flush");
        let(mut b,_)=listener.accept().await.expect("fresh explicit B authentication");let(head,body)=read(&mut b).await;
        observed.fetch_add(1,Ordering::AcqRel);
        assert!(head.lines().next().expect("request").starts_with("POST /v1/auth/session "));
        assert!(head.lines().any(|v|v.eq_ignore_ascii_case("cookie: auth_refresh_token=synthetic-auth-b")));
        assert!(!head.to_ascii_lowercase().contains("authorization:"));
        assert_eq!(body,json!({"session_id":"synthetic-auth-b"}));
        respond(&mut b,&json!({"success":true,"user":{"id":"22222222-1111-4111-8111-111111111111"},"ws_token":"synthetic-b-ws"})).await;
    });
    let bridge=bridge(&endpoint);ok(bridge.import_session(session(&endpoint,"a")).await);
    let logout=ok(bridge.prepare_logout());let host=tokio::spawn(logout.run_unit());
    headers_received.await.expect("original actual HTTP entered");
    host.abort();assert!(host.await.err().expect("abandoned original host").is_cancelled());
    if malformed {
        assert_eq!(bridge.prepare_import_session("malformed synthetic replacement".into()).err().map(|e|e.code),Some("invalid_argument"));
    } else {
        let queued=ok(bridge.prepare_import_session(session(&endpoint,"b"))).run_unit();
        drop(queued); // Genuine newer preparation is NEVER polled/spawned.
    }
    {
        let transitions=bridge.state.identity_transitions.lock().expect("identity negative");
        assert!(transitions.pending.is_none(),"latest B released only its own pending preparation");
    }
    assert!(bridge.state.client.try_lock().is_err(),"actual Core is still draining HTTP with original Client");
    assert_eq!(bridge.identity_admission().err().map(|e|e.code),Some("conflict"));
    let c=bridge.prepare_work(super::super::work::Request::TasksList(openmates_sdk::work::TaskFilters {personal:true,..Default::default()}));
    assert_eq!(c.err().map(|e|e.code),Some("conflict"),"fresh C cannot register at a newer negative epoch over draining A");
    assert!(bridge.state.work_operations.lock().expect("actual registry").is_empty());
    assert_eq!(requests.load(Ordering::Acquire),1,"only original A HTTP exists; no C send was admitted");
    release.send(()).expect("allow actual original settlement");
    // A new explicit B may serialize behind draining A. The actual import must
    // complete before availability and the real B cookie-auth proof return.
    ok(ok(bridge.prepare_import_session(session(&endpoint,"b"))).run_unit().await);
    assert!(bridge.identity_admission().is_ok(),"ordinary admission reopens only after actual drivers and latest B settle");
    assert!(bridge.admit_work().is_ok());
    let snapshot:Value=serde_json::from_str(&ok(bridge.export_session(true).await)).expect("genuine current B snapshot");
    assert_eq!(snapshot["session"]["session_id"],"synthetic-auth-b");
    ok(bridge.validate_session().await);
    assert_eq!(requests.load(Ordering::Acquire),2,"only old A logout and fresh B actual authentication");
    peer.await.expect("actual original/fresh wire assertions");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn latest_unpolled_drop_cannot_release_older_actual_auth_drain() {
    timeout(Duration::from_secs(5),latest_replacement_drop_during_actual_drain(false)).await.expect("original HTTP watchdog");
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.library.explicit-headless
#[tokio::test]
async fn latest_malformed_import_cannot_release_older_actual_auth_drain() {
    timeout(Duration::from_secs(5),latest_replacement_drop_during_actual_drain(true)).await.expect("original HTTP watchdog");
}
