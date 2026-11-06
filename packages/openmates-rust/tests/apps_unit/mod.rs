use super::*;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
type Requests = Arc<Mutex<Vec<(String, Value)>>>;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
fn metadata() -> Value {
    json!({"app_id":"web","skill_id":"search","name":"Search","description":"Search the web","execution_available":true,"defaults":{},"input_schema":{"type":"object","required":["requests"],"additionalProperties":false,"properties":{"requests":{"type":"array","minItems":1,"items":{"type":"object","required":["query"],"properties":{"query":{"type":"string","minLength":1},"model":{"type":"string"}}}}}}})
}
fn fields() -> Value {
    json!({"app":"web","skill":"search","input":{"requests":[{"query":"fictional-sensitive-query"}]}})
}
struct ConcurrentTaskControl {
    release:tokio::sync::watch::Sender<bool>,release_d:tokio::sync::watch::Sender<bool>,hold_headers:bool,
    started:std::sync::atomic::AtomicUsize,task_seen:tokio::sync::Notify,
    a_held:Arc<std::sync::atomic::AtomicBool>,c_held:Arc<std::sync::atomic::AtomicBool>,
    a_seen:Arc<tokio::sync::Notify>,c_seen:Arc<tokio::sync::Notify>,d_seen:Arc<tokio::sync::Notify>,
    drivers:Mutex<Vec<tokio::task::JoinHandle<()>>>,
}
impl ConcurrentTaskControl {
    fn new(hold_headers:bool)->Arc<Self>{
        let(release,_)=tokio::sync::watch::channel(false);let(release_d,_)=tokio::sync::watch::channel(false);
        Arc::new(Self{release,release_d,hold_headers,started:0.into(),task_seen:tokio::sync::Notify::new(),a_held:Arc::new(std::sync::atomic::AtomicBool::new(false)),c_held:Arc::new(std::sync::atomic::AtomicBool::new(false)),a_seen:Arc::new(tokio::sync::Notify::new()),c_seen:Arc::new(tokio::sync::Notify::new()),d_seen:Arc::new(tokio::sync::Notify::new()),drivers:Mutex::new(vec![])})
    }
    async fn drain(&self){self.release.send_replace(true);self.release_d.send_replace(true);let drivers=std::mem::take(&mut*self.drivers.lock().unwrap());for driver in drivers{let _=driver.await;}}
}
impl Drop for ConcurrentTaskControl{fn drop(&mut self){self.release.send_replace(true);self.release_d.send_replace(true);for driver in self.drivers.get_mut().unwrap().drain(..){driver.abort();}}}
async fn released(receiver:&mut tokio::sync::watch::Receiver<bool>)->bool{
    loop{let ready=*receiver.borrow();if ready{return true;}if receiver.changed().await.is_err(){return false;}}
}
async fn fixture(
    async_job: bool,
    cancel_on_dispatch: bool,
    fail: bool,
) -> (
    Client,
    Requests,
    tokio::task::JoinHandle<()>,
    CancellationToken,
) {
    fixture_with_tasks(async_job,cancel_on_dispatch,fail,None).await
}
async fn fixture_with_tasks(
    async_job: bool,
    cancel_on_dispatch: bool,
    fail: bool,
    task_plan: Option<u8>,
) -> (
    Client,
    Requests,
    tokio::task::JoinHandle<()>,
    CancellationToken,
) {
    fixture_with_task_controls(async_job,cancel_on_dispatch,fail,task_plan,None).await
}
async fn fixture_with_task_controls(
    async_job: bool,
    cancel_on_dispatch: bool,
    fail: bool,
    task_plan: Option<u8>,
    controls:Option<Arc<ConcurrentTaskControl>>,
) -> (
    Client,
    Requests,
    tokio::task::JoinHandle<()>,
    CancellationToken,
) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let requests: Requests = Arc::new(Mutex::new(vec![]));
    let recorded = requests.clone();
    let cancel = CancellationToken::new();
    let cancellation = cancel.clone();
    let server = tokio::spawn(async move {
        let mut a_reads=0usize;
        let mut b_reads=0usize;
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            let mut part = [0u8; 4096];
            let (headers_end, length) = loop {
                let read = socket.read(&mut part).await.unwrap();
                if read == 0 {
                    return;
                }
                bytes.extend_from_slice(&part[..read]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                    let length = headers
                        .lines()
                        .filter_map(|l| l.split_once(':'))
                        .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                        .map(|(_, v)| v.trim().parse::<usize>().unwrap())
                        .unwrap_or(0);
                    break (end + 4, length);
                }
            };
            while bytes.len() < headers_end + length {
                let read = socket.read(&mut part).await.unwrap();
                if read == 0 {
                    return;
                }
                bytes.extend_from_slice(&part[..read]);
            }
            let headers = std::str::from_utf8(&bytes[..headers_end]).unwrap();
            let path = headers
                .lines()
                .next()
                .unwrap()
                .split_whitespace()
                .nth(1)
                .unwrap()
                .to_owned();
            let body = if length == 0 {
                Value::Null
            } else {
                serde_json::from_slice(&bytes[headers_end..headers_end + length]).unwrap()
            };
            recorded.lock().unwrap().push((path.clone(), body.clone()));
            if path.starts_with("/v1/tasks/"){if let Some(c)=&controls{c.started.fetch_add(1,std::sync::atomic::Ordering::AcqRel);c.task_seen.notify_one();}}
            if (matches!(task_plan,Some(3|4|5)) && matches!(path.as_str(),"/v1/tasks/task-a"|"/v1/tasks/task-c")) || task_plan==Some(6)&&path.starts_with("/v1/tasks/") {
                use std::sync::atomic::Ordering;
                let controls=controls.as_ref().unwrap();let title=if path.ends_with("task-a"){"A"}else if path.ends_with("task-b"){"B"}else if path.ends_with("task-c"){"C"}else{"D"};
                if title=="A"{controls.a_held.store(true,Ordering::Release);controls.a_seen.notify_one();}else{controls.c_held.store(true,Ordering::Release);controls.c_seen.notify_one();}
                let task_id=path.rsplit('/').next().unwrap();
                let body=json!({"task_id":task_id,"status":"completed","result":{"results":[{"title":title}],"request_count":1}}).to_string();
                let header=format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=shared-rotated; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len());
                let mut release=controls.release.subscribe();let hold_headers=controls.hold_headers;
                let driver=tokio::spawn(async move{
                    if hold_headers&&!released(&mut release).await{return;}
                    if socket.write_all(header.as_bytes()).await.is_err(){return;}
                    if !hold_headers&&!released(&mut release).await{return;}
                    let _=socket.write_all(body.as_bytes()).await;
                });controls.drivers.lock().unwrap().push(driver);continue;
            }
            if matches!(task_plan,Some(3|4|5)) && path=="/v1/tasks/task-b" {
                b_reads+=1;let controls=controls.as_ref().unwrap();
                let a=controls.a_held.clone();let a_seen=controls.a_seen.clone();let c=controls.c_held.clone();let c_seen=controls.c_seen.clone();
                let plan=task_plan.unwrap();let body=if plan==3||plan==5&&b_reads>1{json!({"task_id":"task-b","status":"failed"})}else if plan==5{json!({"task_id":"task-b","status":"pending"})}else{json!({"task_id":"task-b","status":"completed","result":{"results":[{"title":"B"}],"request_count":1}})}.to_string();
                let driver=tokio::spawn(async move {
                    use std::sync::atomic::Ordering;
                    loop{let ready=a.load(Ordering::Acquire);if ready{break;}a_seen.notified().await;}
                    if plan==4{loop{let ready=c.load(Ordering::Acquire);if ready{break;}c_seen.notified().await;}}
                    let _=socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=shared-rotated; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await;
                });controls.drivers.lock().unwrap().push(driver);continue;
            }
            if task_plan==Some(4)&&path=="/v1/tasks/task-d" {
                let controls=controls.as_ref().unwrap();controls.d_seen.notify_one();
                let mut release=controls.release_d.subscribe();
                let body=json!({"task_id":"task-d","status":"completed","result":{"results":[{"title":"D"}],"request_count":1}}).to_string();
                let driver=tokio::spawn(async move{
                    let header=format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len());
                    if socket.write_all(header.as_bytes()).await.is_err(){return;}
                    if released(&mut release).await{let _=socket.write_all(body.as_bytes()).await;}
                });controls.drivers.lock().unwrap().push(driver);continue;
            }
            let response = match path.as_str() {
                "/v1/apps/web/skills/search/details" => metadata(),
                "/v1/auth/session" => {
                    json!({"success":true,"ws_token":"synthetic-token","user":{"id":OWNER}})
                }
                "/v1/apps/workspace/results" => {
                    json!({"success":true,"root_embed_id":body["root_embed_id"]})
                }
                "/v1/apps/web/skills/search" => {
                    if cancel_on_dispatch {
                        cancellation.cancel()
                    }
                    if fail {
                        json!({"success":false,"error":"SYNTHETIC PRIVATE FAILURE BODY"})
                    } else if let Some(plan)=task_plan {
                        json!({"success":true,"credits_charged":1,"data":{"task_ids":(if plan==2{vec!["task-a"]}else if plan==4||plan==6{vec!["task-a","task-b","task-c","task-d"]}else{vec!["task-a","task-b"]})}})
                    } else if async_job {
                        json!({"success":true,"data":{"task_id":"task-1","status":"processing"}})
                    } else {
                        json!({"success":true,"data":{"results":[{"title":"A real fixture result","url":"https://example.invalid"}]}})
                    }
                }
                "/v1/tasks/task-a" => {
                    a_reads+=1;
                    if task_plan==Some(0) || task_plan==Some(1) && a_reads==1 {
                        json!({"task_id":"task-a","status":"pending"})
                    }else{json!({"task_id":"task-a","status":"completed","result":{"results":[{"title":"A"}],"request_count":1}})}
                }
                "/v1/tasks/task-d" => {json!({"task_id":"task-d","status":"completed","result":{"results":[{"title":"D"}],"request_count":1}})}
                "/v1/tasks/task-b" => {
                    if task_plan==Some(0){json!({"task_id":"task-b","status":"failed"})}
                    else{json!({"task_id":"task-b","status":"completed","result":{"results":[{"title":"B"}],"request_count":1}})}
                }
                "/v1/tasks/task-1" => {
                    json!({"task_id":"task-1","status":"completed","result":{"results":[{"title":"Async fixture result","url":"https://example.invalid/async"}]}})
                }
                _ => panic!("unexpected synthetic endpoint"),
            };
            let body = response.to_string();
            let header = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            socket.write_all(header.as_bytes()).await.unwrap();
            socket.write_all(body.as_bytes()).await.unwrap();
        }
    });
    let base = format!("http://{address}");
    let session = Session {
        api_url: base.clone(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::new(),
        ws_token: Some("synthetic-token".into()),
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&base, Some(session)).unwrap();
    client.user = json!({"id":OWNER});
    client.set_operation_cancel(cancel.clone());
    (client, requests, server, cancel)
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn canonical_metadata_schema_and_automatic_routing_controls() {
    let item = skill_item("web", "search", metadata()).unwrap();
    assert_eq!(item.fields["app"], "web");
    assert_eq!(item.fields["skill_id"], "search");
    assert_eq!(item.fields["confirmation_required"], true);
    let mut sandbox = metadata();
    sandbox["execution_mode"] = json!("sandbox");
    assert_eq!(
        skill_item("web", "search", sandbox).unwrap().fields["execution_available"],
        false
    );
    let schema = &item.fields["input_schema"];
    assert!(validate_schema(schema, &fields()["input"]));
    assert!(!validate_schema(schema, &json!({"requests":[{"query":42}]})));
    assert!(!validate_schema(schema, &json!({"requests":[]})));
    assert!(!validate_schema(schema, &json!({"requests":[{}]})));
    assert_eq!(
        automatic_input(&json!({"requests":[{"query":"hello","model":"auto"}]}), 0).unwrap(),
        json!({"requests":[{"query":"hello"}]})
    );
    assert!(automatic_input(&json!({"model":"provider/model"}), 0).is_err());
    assert!(automatic_input(&json!({"requests":[{"provider":"forced"}]}), 0).is_err());
    assert_eq!(
        automatic_input(
            &json!({"query":"typed value","pii_mappings":{"original":"must remain local"}}),
            0
        )
        .unwrap(),
        json!({"query":"typed value"})
    );
    assert!(task_ids(&json!({"data":{"task_ids":["task-1","task-1"]}})).is_err());
    assert!(task_ids(&json!({"task_id":"//another-authority"})).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn synchronous_skill_keeps_private_retention_encrypted_and_returns_real_content() {
    let (mut client, requests, server, _) = fixture(false, false, false).await;
    let item = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        item.fields["content"]["results"][0]["title"],
        "A real fixture result"
    );
    let requests = requests.lock().unwrap();
    let dispatch = requests
        .iter()
        .position(|(p, _)| p == "/v1/apps/web/skills/search")
        .unwrap();
    let saved = requests
        .iter()
        .position(|(p, _)| p == "/v1/apps/workspace/results")
        .unwrap();
    assert!(saved < dispatch);
    assert_eq!(requests[dispatch].1, fields()["input"]);
    for (path, body) in requests
        .iter()
        .filter(|(path, _)| path == "/v1/apps/workspace/results")
    {
        assert!(
            !body.to_string().contains("fictional-sensitive-query"),
            "{path}"
        );
        let key = key_from_bytes(
            &crypto::decrypt_bytes(text(body, "encrypted_embed_key"), &[7; 32]).unwrap(),
        )
        .unwrap();
        let content =
            crypto::decrypt_combined(text(&body["embeds"][0], "encrypted_content"), &key).unwrap();
        assert!(content.contains("fictional-sensitive-query"));
    }
    drop(requests);
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn asynchronous_skill_polls_actual_task_and_preserves_admission() {
    let (mut client, requests, server, _) = fixture(true, false, false).await;
    let item = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        item.fields["content"]["results"][0]["title"],
        "Async fixture result"
    );
    assert!(
        requests
            .lock()
            .unwrap()
            .iter()
            .any(|(path, _)| path == "/v1/tasks/task-1")
    );
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn cancellation_after_post_retains_task_receipt_without_retry_or_poll() {
    let (mut client, requests, server, _) = fixture(true, true, false).await;
    assert!(matches!(
        client.run_app_skill_with_gate(fields(), || Ok(())).await,
        Err(Error::Cancelled)
    ));
    let requests = requests.lock().unwrap();
    assert_eq!(
        requests
            .iter()
            .filter(|(path, _)| path == "/v1/apps/web/skills/search")
            .count(),
        1
    );
    assert!(
        !requests
            .iter()
            .any(|(path, _)| path.starts_with("/v1/tasks/"))
    );
    let (_, saved) = requests
        .iter()
        .rev()
        .find(|(path, _)| path == "/v1/apps/workspace/results")
        .unwrap();
    let key = key_from_bytes(
        &crypto::decrypt_bytes(text(saved, "encrypted_embed_key"), &[7; 32]).unwrap(),
    )
    .unwrap();
    let content: Value = serde_json::from_str(
        &crypto::decrypt_combined(text(&saved["embeds"][0], "encrypted_content"), &key).unwrap(),
    )
    .unwrap();
    assert_eq!(content["task_ids"], json!(["task-1"]));
    drop(requests);
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn cancellation_after_synchronous_post_still_persists_the_completed_result() {
    let (mut client, requests, server, _) = fixture(false, true, false).await;
    assert!(matches!(
        client.run_app_skill_with_gate(fields(), || Ok(())).await,
        Err(Error::Cancelled)
    ));
    let requests = requests.lock().unwrap();
    let (_, saved) = requests
        .iter()
        .rev()
        .find(|(path, _)| path == "/v1/apps/workspace/results")
        .unwrap();
    assert_eq!(saved["embeds"][0]["status"], "finished");
    let key = key_from_bytes(
        &crypto::decrypt_bytes(text(saved, "encrypted_embed_key"), &[7; 32]).unwrap(),
    )
    .unwrap();
    let content: Value = serde_json::from_str(
        &crypto::decrypt_combined(text(&saved["embeds"][0], "encrypted_content"), &key).unwrap(),
    )
    .unwrap();
    assert_eq!(content["results"][0]["title"], "A real fixture result");
    drop(requests);
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn enhanced_mode_and_upstream_failures_are_fail_closed_and_redacted() {
    let (mut client, requests, server, _) = fixture(false, false, true).await;
    let error = client
        .run_app_skill_with_gate(fields(), || {
            Err(Error::Invalid("Enhanced mode unavailable."))
        })
        .await
        .err()
        .unwrap();
    assert_eq!(error.to_string(), "Enhanced mode unavailable.");
    assert!(requests.lock().unwrap().is_empty());
    let error = client
        .run_app_skill_with_gate(fields(), || Ok(()))
        .await
        .err()
        .unwrap();
    assert!(!error.to_string().contains("PRIVATE FAILURE"));
    server.abort();
}

// contract-test: supporting surface=cli assertions=cli.migration.complete-compatible
#[tokio::test]
async fn direct_personal_execution_preserves_resolved_envelope_without_retained_writes() {
    for asynchronous in [false, true] {
        let (mut client, requests, server, _) = fixture(asynchronous, false, false).await;
        let value = client
            .run_direct_app_skill("web", "search", fields()["input"].clone())
            .await
            .unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(
            value["data"]["results"][0]["title"],
            if asynchronous {
                "Async fixture result"
            } else {
                "A real fixture result"
            }
        );
        let recorded = requests.lock().unwrap();
        assert_eq!(
            recorded
                .iter()
                .filter(|(path, _)| path == "/v1/apps/web/skills/search")
                .count(),
            1
        );
        assert!(
            recorded
                .iter()
                .all(|(path, _)| !path.starts_with("/v1/apps/workspace/results")
                    && !path.starts_with("/v1/chats"))
        );
        assert!(recorded.iter().any(|(path, _)| path.ends_with("/details")));
        assert!(recorded.iter().any(|(path, _)| path == "/v1/auth/session"));
        server.abort();
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn direct_cancellation_after_dispatch_never_retries_or_publishes_success() {
    let (mut client, requests, server, _) = fixture(false, true, false).await;
    assert!(matches!(
        client
            .run_direct_app_skill("web", "search", fields()["input"].clone())
            .await,
        Err(Error::Cancelled)
    ));
    let recorded = requests.lock().unwrap();
    assert_eq!(
        recorded
            .iter()
            .filter(|(path, _)| path == "/v1/apps/web/skills/search")
            .count(),
        1
    );
    assert!(
        recorded
            .iter()
            .all(|(path, _)| path != "/v1/apps/workspace/results")
    );
    server.abort();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn direct_failure_does_not_create_error_result_graph() {
    let (mut client, requests, server, _) = fixture(false, false, true).await;
    assert!(
        client
            .run_direct_app_skill("web", "search", fields()["input"].clone())
            .await
            .is_err()
    );
    assert!(
        requests
            .lock()
            .unwrap()
            .iter()
            .all(|(path, _)| path != "/v1/apps/workspace/results")
    );
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn generated_file_credentials_are_sent_only_to_fixed_relative_embed_routes() {
    let (source,_,old_server,_)=fixture(false,false,false).await;
    old_server.abort();
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base=format!("http://{}",listener.local_addr().unwrap());
    let mut session=source.session.clone().unwrap();session.api_url=base.clone();
    session.cookies.insert("session".into(),"synthetic-owned-cookie".into());
    let mut client=Client::new(&base,Some(session)).unwrap();client.user=json!({"id":OWNER});
    let peer=tokio::spawn(async move {
        let mut requests=vec![];
        for _ in 0..2 {
            let (mut stream,_)=listener.accept().await.unwrap();let mut bytes=vec![];let mut part=[0u8;4096];
            while !bytes.windows(4).any(|w|w==b"\r\n\r\n") {
                let n=stream.read(&mut part).await.unwrap();assert!(n>0);bytes.extend_from_slice(&part[..n]);
            }
            requests.push(String::from_utf8(bytes).unwrap().to_lowercase());
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nabc").await.unwrap();
        }
        requests
    });
    let mut bytes=vec![];
    client.stream_generated_app_file("/v1/embeds/22222222-2222-4222-8222-222222222222/file?format=original",|chunk|{bytes.extend_from_slice(chunk);Ok(())}).await.unwrap();
    assert_eq!(bytes,b"abc");bytes.clear();
    client.stream_generated_app_file(&format!("{base}/provider"),|chunk|{bytes.extend_from_slice(chunk);Ok(())}).await.unwrap();
    let requests=peer.await.unwrap();
    assert!(requests[0].contains("cookie: session=synthetic-owned-cookie"));
    assert!(!requests[1].contains("cookie:"));assert!(!requests[1].contains("authorization:"));
    for invalid in ["/v1/auth/session","//example.invalid/file","file:///tmp/fixture","https://user:pass@example.invalid/file"] {
        assert!(client.stream_generated_app_file(invalid,|_|Ok(())).await.is_err());
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn direct_async_receipt_has_only_original_validated_ids_before_polling() {
    let (mut client,requests,server,_)=fixture(true,false,false).await;
    let mut ids=vec![];
    client.run_direct_app_skill_with_task_receipt("web","search",fields()["input"].clone(),|tasks|ids.extend_from_slice(tasks)).await.unwrap();
    assert_eq!(ids,vec!["task-1"]);
    let recorded=requests.lock().unwrap();
    assert_eq!(recorded.iter().filter(|(path,_)|path=="/v1/apps/web/skills/search").count(),1);
    assert!(recorded.iter().all(|(path,_)|path!="/v1/apps/workspace/results"));
    server.abort();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn direct_sweep_observes_failed_b_while_a_remains_pending_without_awaiting_a_completion() {
    let (mut client,requests,server,_)=fixture_with_tasks(true,false,false,Some(0)).await;
    assert_eq!(client.run_direct_app_skill("web","search",fields()["input"].clone()).await.unwrap_err(),Error::Invalid("App task execution failed."));
    let recorded=requests.lock().unwrap();
    let polls=recorded.iter().filter(|(p,_)|p.starts_with("/v1/tasks/")).map(|(p,_)|p.as_str()).collect::<Vec<_>>();
    assert_eq!(polls.len(),2);assert!(polls.contains(&"/v1/tasks/task-a")&&polls.contains(&"/v1/tasks/task-b"));
    assert_eq!(recorded.iter().filter(|(p,_)|p=="/v1/apps/web/skills/search").count(),1);
    server.abort();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn direct_array_merge_keeps_original_task_order_and_single_array_aggregation() {
    for plan in [1,2] {
        let (mut client,requests,server,_)=fixture_with_tasks(true,false,false,Some(plan)).await;
        let result=client.run_direct_app_skill("web","search",fields()["input"].clone()).await.unwrap();
        assert_eq!(result["success"],true);assert_eq!(result["credits_charged"],1);
        assert_eq!(result["data"]["results"][0]["title"],"A");
        assert_eq!(result["data"]["result_count"],if plan==1{2}else{1});
        assert_eq!(result["data"]["items"],json!([]));
        if plan==1 {
            assert_eq!(result["data"]["results"][1]["title"],"B");
            let recorded=requests.lock().unwrap();let polls=recorded.iter().filter(|(p,_)|p.starts_with("/v1/tasks/")).map(|(p,_)|p.as_str()).collect::<Vec<_>>();
            assert_eq!(polls.len(),3);assert_eq!(polls.iter().filter(|p|**p=="/v1/tasks/task-a").count(),2);assert_eq!(polls.iter().filter(|p|**p=="/v1/tasks/task-b").count(),1);assert!(polls.iter().position(|p|*p=="/v1/tasks/task-b").unwrap()<polls.iter().rposition(|p|*p=="/v1/tasks/task-a").unwrap());
        }
        server.abort();
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[test]
fn original_direct_policy_survives_current_gate_replacement_and_current_tightening() {
    let api="https://example.invalid";
    let mut client=Client::new(api,Some(Session{api_url:api.into(),session_id:"synthetic".into(),cookies:BTreeMap::new(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
    let denied=Arc::new(std::sync::atomic::AtomicBool::new(false));let observed=denied.clone();
    client.set_private_operation_gate(Some(Arc::new(move ||if observed.load(std::sync::atomic::Ordering::Acquire){Err(Error::Forbidden)}else{Ok(())})));
    let original=client.direct_app_skill_admission().unwrap();
    client.set_private_operation_gate(Some(Arc::new(||Ok(()))));
    denied.store(true,std::sync::atomic::Ordering::Release);
    assert_eq!(original.check(&client),Err(Error::Forbidden));
    denied.store(false,std::sync::atomic::Ordering::Release);
    assert!(original.check(&client).is_ok());
    client.set_privacy_options(crate::privacy::PrivacyOptions{enhanced:true});
    assert!(original.check(&client).is_err());
}

// The 10s timeout is a deadlock watchdog, NOT a latency threshold.
// Actual Rust B-result acceptance releases D; actual D acceptance releases A/C.
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor="current_thread")]
async fn concurrent_task_gets_consume_b_then_d_before_held_a_and_c_resolve() {
    use std::sync::atomic::Ordering;
    for hold_headers in [true,false] {
        let controls=ConcurrentTaskControl::new(hold_headers);
        let (mut client,requests,server,_)=fixture_with_task_controls(true,false,false,Some(4),Some(controls.clone())).await;
        let (observed,mut completions)=tokio::sync::mpsc::unbounded_channel();
        let _observer=super::direct_poll_observation::install(move|index|{let _=observed.send(index);});
        let call=tokio::spawn(async move{let result=client.run_direct_app_skill("web","search",fields()["input"].clone()).await;(client,result)});
        assert_eq!(tokio::time::timeout(Duration::from_secs(10),completions.recv()).await.unwrap(),Some(1),"B must be actually consumed while A/C are held");
        assert!(controls.a_held.load(Ordering::Acquire)&&controls.c_held.load(Ordering::Acquire));
        assert!(!*controls.release.borrow());assert!(!call.is_finished());
        controls.release_d.send_replace(true);
        assert_eq!(tokio::time::timeout(Duration::from_secs(10),completions.recv()).await.unwrap(),Some(3),"D must be consumed without releasing A/C");
        assert!(!*controls.release.borrow());assert!(!call.is_finished());controls.release.send_replace(true);
        let (client,result)=tokio::time::timeout(Duration::from_secs(10),call).await.unwrap().unwrap();let result=result.unwrap();
        assert!(client.session.as_ref().unwrap().cookies.get("auth_refresh_token").is_some_and(|v|v=="shared-rotated"));
        let titles=result["data"]["results"].as_array().unwrap().iter().map(|v|v["title"].as_str().unwrap()).collect::<Vec<_>>();
        assert_eq!(titles,vec!["A","B","C","D"]);assert_eq!(result["data"]["result_count"],4);
        assert_eq!(requests.lock().unwrap().iter().filter(|(p,_)|p=="/v1/apps/web/skills/search").count(),1);
        server.abort();controls.drain().await;
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn concurrent_task_gets_start_all_four_equal_slow_reads_before_any_release() {
    for hold_headers in [true,false] {
        let controls=ConcurrentTaskControl::new(hold_headers);
        let (mut client,_requests,server,_)=fixture_with_task_controls(true,false,false,Some(6),Some(controls.clone())).await;
        let call=tokio::spawn(async move{client.run_direct_app_skill("web","search",fields()["input"].clone()).await});
        // A notification records each real request before holding headers/body.
        tokio::time::timeout(Duration::from_secs(10),async{loop{
            if controls.started.load(std::sync::atomic::Ordering::Acquire)==4{break;}
            controls.task_seen.notified().await;
        }}).await.expect("ALL four original task GETs must start before any response is released");
        assert!(!*controls.release.borrow());assert!(!call.is_finished());controls.release.send_replace(true);
        let result=tokio::time::timeout(Duration::from_secs(10),call).await.unwrap().unwrap().unwrap();
        let titles=result["data"]["results"].as_array().unwrap().iter().map(|v|v["title"].as_str().unwrap()).collect::<Vec<_>>();
        assert_eq!(titles,vec!["A","B","C","D"]);server.abort();controls.drain().await;
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn concurrent_task_gets_observe_failed_or_later_failed_b_while_a_headers_or_body_remains_held() {
    use std::sync::atomic::Ordering;
    for plan in [3,5] {for hold_headers in [true,false] {
        let controls=ConcurrentTaskControl::new(hold_headers);
        let (mut client,requests,server,_)=fixture_with_task_controls(true,false,false,Some(plan),Some(controls.clone())).await;
        let call=tokio::spawn(async move{client.run_direct_app_skill("web","search",fields()["input"].clone()).await});
        let result=tokio::time::timeout(Duration::from_secs(10),call).await.expect("B failure is observed without releasing A").unwrap();
        assert_eq!(result.unwrap_err(),Error::Invalid("App task execution failed."));
        assert!(controls.a_held.load(Ordering::Acquire));assert!(!*controls.release.borrow());
        let recorded=requests.lock().unwrap();assert_eq!(recorded.iter().filter(|(p,_)|p=="/v1/apps/web/skills/search").count(),1);
        assert_eq!(recorded.iter().filter(|(p,_)|p=="/v1/tasks/task-b").count(),if plan==5{2}else{1});drop(recorded);
        server.abort();controls.drain().await;
    }}
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn concurrent_task_gets_cancel_all_held_reads_without_releasing_or_redispatching() {
    for hold_headers in [true,false] {
        let controls=ConcurrentTaskControl::new(hold_headers);
        let (mut client,requests,server,cancel)=fixture_with_task_controls(true,false,false,Some(6),Some(controls.clone())).await;
        let call=tokio::spawn(async move{client.run_direct_app_skill("web","search",fields()["input"].clone()).await});
        tokio::time::timeout(Duration::from_secs(10),async{loop{
            if controls.started.load(std::sync::atomic::Ordering::Acquire)==4{break;}
            controls.task_seen.notified().await;
        }}).await.unwrap();
        cancel.cancel();
        let result=tokio::time::timeout(Duration::from_secs(10),call).await.expect("original cancellation drops ALL pending IO").unwrap();
        assert_eq!(result.unwrap_err(),Error::Cancelled);assert!(!*controls.release.borrow());
        assert_eq!(requests.lock().unwrap().iter().filter(|(p,_)|p=="/v1/apps/web/skills/search").count(),1);
        assert_eq!(requests.lock().unwrap().iter().filter(|(p,_)|p.starts_with("/v1/tasks/")).count(),4);
        server.abort();controls.drain().await;
    }
}
