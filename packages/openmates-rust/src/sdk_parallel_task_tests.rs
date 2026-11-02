//! Genuine native HTTP regressions authored UNRUN for isolated CI. No real
//! account, environment discovery, paid service or model override is involved.
use super::*;
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::{mpsc, oneshot};

type Trace = Vec<(String, Value)>;
async fn read_request(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = Vec::new();
    let (end, length) = loop {
        let mut chunk = [0u8;4096]; let n = stream.read(&mut chunk).await.unwrap(); assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]); assert!(bytes.len() < 2 * 1024 * 1024);
        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&bytes[..end]);
            let length = headers.lines().find_map(|line| {
                let (name,value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length").then(|| value.trim().parse::<usize>().unwrap())
            }).unwrap_or(0);
            break (end+4, length);
        }
    };
    while bytes.len() < end+length {
        let mut chunk = [0u8;4096]; let n = stream.read(&mut chunk).await.unwrap(); assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]); assert!(bytes.len() < 2 * 1024 * 1024);
    }
    let header = String::from_utf8_lossy(&bytes[..end]).into_owned();
    let body = if length == 0 { Value::Null } else { serde_json::from_slice(&bytes[end..end+length]).unwrap() };
    (header, body)
}
async fn respond(stream: &mut tokio::net::TcpStream, body: Value) -> std::io::Result<()> {
    let body = body.to_string();
    stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await
}
fn sdk(base: &str, gate: Option<Arc<dyn Fn()->Result<()>+Send+Sync>>) -> OpenMates {
    OpenMates::new(SdkOptions { api_url:base.into(), credentials:SdkCredentials::ApiKey(ApiKey::new("sk-api-parallelFixture.localSetupSuffix").unwrap()),
        device_id:"parallel-fixture-device".into(), client_options:ClientOptions { app_url:Some(base.into()), private_operation_gate:gate, ..ClientOptions::default() } }).unwrap()
}
fn check_trace(trace: &Trace, count: usize) {
    assert_eq!(trace.len(), count+1);
    assert_eq!(trace.iter().filter(|(h,_)|h.starts_with("POST /v1/apps/web/skills/search ")).count(),1);
    for i in 0..count {
        assert_eq!(trace.iter().filter(|(h,_)|h.starts_with(&format!("GET /v1/tasks/task-{i} "))).count(),1);
    }
    for (header,_) in trace {
        let header = header.to_lowercase();
        assert!(header.contains("authorization: bearer sk-api-parallelfixture"));
        assert!(!header.contains("localsetupsuffix")); assert!(!header.contains("cookie:"));
        assert!(header.contains("x-openmates-device-identity: parallel-fixture-device"));
    }
    assert_eq!(trace[0].1, json!({"query":"parallel-fixture"}));
}

// Route-aware replacement for the inherited serial-accept fixture. The public
// result order stays asserted by its original test, while actual GET arrival
// order is free to match concurrent transport scheduling.
pub(super) async fn routed_original_task_server() -> (String, tokio::task::JoinHandle<Trace>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}",listener.local_addr().unwrap());
    let peer = tokio::spawn(async move {
        let mut trace = vec![];
        for _ in 0..3 {
            let (mut stream,_) = listener.accept().await.unwrap();
            let request = read_request(&mut stream).await;
            let body = if request.0.starts_with("POST /v1/apps/web/skills/search ") {
                json!({"success":true,"data":{"task_ids":["task-a","task-b"]}})
            } else if request.0.starts_with("GET /v1/tasks/task-a ") {
                json!({"status":"completed","result":{"results":[{"id":"a"}]}})
            } else { assert!(request.0.starts_with("GET /v1/tasks/task-b "));
                json!({"status":"completed","result":{"results":[{"id":"b"}]}}) };
            trace.push(request); respond(&mut stream, body).await.unwrap();
        }
        trace
    });
    (base,peer)
}

// All original GETs are accepted before ANY poll response. A serial loop or
// max-three wave cannot reach this barrier. The overall timeout is only a
// deadlock watchdog; no timing-only silence assertion establishes success.
async fn parallel_case(mode: u8) {
    let count = 7usize;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}",listener.local_addr().unwrap());
    let (all_tx,all_rx) = oneshot::channel(); let (release_tx,release_rx) = oneshot::channel();
    let sent = Arc::new(AtomicBool::new(false)); let released = Arc::new(AtomicBool::new(false));
    let deny = Arc::new(AtomicBool::new(false));
    let (parsed_tx,mut parsed_rx) = mpsc::unbounded_channel();
    let gate_sent=sent.clone();let gate_released=released.clone();let gate_deny=deny.clone();
    let gate: Arc<dyn Fn()->Result<()>+Send+Sync> = Arc::new(move || {
        if gate_deny.load(Ordering::Acquire) { return Err(Error::Forbidden); }
        if gate_sent.load(Ordering::Acquire) && !gate_released.load(Ordering::Acquire) { let _ = parsed_tx.send(()); }
        Ok(())
    });
    let peer_sent = sent.clone(); let peer_released = released.clone();
    let peer = tokio::spawn(async move {
        let (mut post,_) = listener.accept().await.unwrap();
        let mut trace = vec![read_request(&mut post).await];
        assert!(trace[0].0.starts_with("POST /v1/apps/web/skills/search "));
        let ids = (0..count).map(|i|format!("task-{i}")).collect::<Vec<_>>();
        respond(&mut post,json!({"success":true,"credits_charged":count,"data":{"task_ids":ids}})).await.unwrap();
        drop(post);
        let mut held = None; let mut others = vec![];
        for _ in 0..count {
            let (mut stream,_) = listener.accept().await.unwrap();
            let request = read_request(&mut stream).await;
            let path = request.0.lines().next().unwrap().split_whitespace().nth(1).unwrap();
            let index = path.strip_prefix("/v1/tasks/task-").unwrap().parse::<usize>().unwrap();
            assert!(index<count); trace.push(request);
            if index==0 { assert!(held.replace(stream).is_none()); } else { others.push((index,stream)); }
        }
        all_tx.send(()).unwrap();
        // All request-side policy gates already ran before the real peer could
        // accept these GETs. The next callback with sent=true and A still held
        // therefore observes a real later peer's parsed response in core.
        peer_sent.store(true,Ordering::Release);
        for (index,mut stream) in others {
            let response = if mode==1 && index==1 { json!({"status":"failed","error":"synthetic-private-task-diagnostic"}) }
                else { json!({"status":"completed","result":{"origin":index,"results":[{"index":index}]}}) };
            // Early failure/cancellation may legitimately close remaining GETs.
            let _ = respond(&mut stream,response).await;
        }
        release_rx.await.unwrap(); peer_released.store(true,Ordering::Release);
        let response = json!({"status":"completed","result":{"origin":0,"results":[{"index":0}]}});
        let write = respond(&mut held.unwrap(),response).await;
        if mode==0 { write.unwrap(); }
        trace
    });
    let sdk=sdk(&base,Some(gate)); let caller=CancellationToken::new(); let original=sdk.operation_cancel.clone();
    if mode==1 {
        let result=sdk.run_app_skill("web","search",json!({"query":"parallel-fixture"}),caller.clone()).await;
        assert_eq!(result,Err(Error::Invalid("App skill task failed.")));
        all_rx.await.unwrap(); parsed_rx.recv().await.unwrap();
        assert!(!released.load(Ordering::Acquire),"B failure returned while original A response is held");
        release_tx.send(()).unwrap();
    } else {
        let call=sdk.run_app_skill("web","search",json!({"query":"parallel-fixture"}),caller.clone());
        let control=async {
            all_rx.await.unwrap(); parsed_rx.recv().await.unwrap();
            assert!(!released.load(Ordering::Acquire),"later peer reached real core gate before A release");
            match mode { 0=>{},2=>caller.cancel(),3=>original.cancel(),4=>deny.store(true,Ordering::Release),_=>unreachable!() }
            release_tx.send(()).unwrap();
        };
        let (result,())=tokio::join!(call,control);
        match mode {
            0=>{ let value=result.unwrap(); assert_eq!(value["credits_charged"],count); assert_eq!(value["data"]["origin"],0);
                assert_eq!(value["data"]["results"],Value::Array((0..count).map(|i|json!({"index":i})).collect())); },
            2|3=>assert_eq!(result,Err(Error::Cancelled)),4=>assert_eq!(result,Err(Error::Forbidden)),_=>unreachable!(),
        }
    }
    check_trace(&peer.await.unwrap(),count);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn all_original_task_polls_start_and_later_completion_reaches_core_while_first_response_held() {
    tokio::time::timeout(Duration::from_secs(15),parallel_case(0)).await.expect("deadlock watchdog");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn later_task_failure_returns_while_first_response_held_without_replaying_paid_post() {
    tokio::time::timeout(Duration::from_secs(15),parallel_case(1)).await.expect("deadlock watchdog");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn concurrent_completed_and_pending_values_cannot_publish_after_original_cancel_or_policy_denial() {
    for mode in [2,3,4] { tokio::time::timeout(Duration::from_secs(15),parallel_case(mode)).await.expect("deadlock watchdog"); }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn wire_task_id_and_one_element_task_ids_preserve_distinct_scalar_and_object_shapes() {
    for array in [false,true] {
        for (result, array_expected) in [
            (json!(7),json!({"results":[7]})),
            (json!({"label":"one"}),json!({"results":[{"label":"one"}]})),
            (json!({"origin":"first","results":[{"index":0}]}),json!({"origin":"first","results":[{"index":0}]})),
        ] {
            let data=if array { json!({"task_ids":["task-one"]}) } else { json!({"task_id":"task-one"}) };
            let (base,peer)=super::tests::server(vec![(200,json!({"success":true,"credits_charged":1,"data":data})),
                (200,json!({"status":"completed","result":result.clone()}))]).await;
            let value=sdk(&base,None).run_app_skill("web","search",json!({"query":"parallel-fixture"}),CancellationToken::new()).await.unwrap();
            let expected=if array { array_expected } else { result };
            assert_eq!(value,json!({"success":true,"credits_charged":1,"data":expected}));
            let trace=peer.await.unwrap(); assert_eq!(trace.len(),2);
            assert!(trace[0].0.starts_with("POST /v1/apps/web/skills/search "));assert!(trace[1].0.starts_with("GET /v1/tasks/task-one "));
        }
    }
}
