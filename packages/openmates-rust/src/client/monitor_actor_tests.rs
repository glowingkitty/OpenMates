//! Actual original monitor actor + native loopback WebSocket cases, UNRUN.
//! These tests use the real single Socket/receiver and genuine owned scopes.
//! Synthetic explicit Session data never touches accounts or paid inference.
//! Peer frames are loopback protocol stimuli, not host-granted auth receipts.
//! No body/status/marker grants recovery, cache IO, inventory or deletion proof.
//! All existing monitor tests remain separate and unchanged.
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{WebSocketStream, tungstenite::Message as Frame};
type Peer = WebSocketStream<tokio::net::TcpStream>;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
fn fixture() -> Client {
    let mut client = Client::new("https://example.invalid",Some(Session {
        api_url:"https://example.invalid".into(),session_id:"synthetic-session".into(),cookies:BTreeMap::new(),ws_token:None,
        master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic-owner".into(),user_email_salt:String::new(),
        email_encryption_key:None,created_at:now_ms(),paired_session_expires_at:None,active_team_id:None,
    })).unwrap();
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    client
}
fn monitor(client: &Client, socket: &Socket) -> (ChatMonitor, MonitorReadReceiver) {
    let fence = Arc::new(MonitorFence { owner:client.task_watch_authority.clone(),generation:client.generation,
        team:client.team().unwrap().map(str::to_owned),expires_at:None,cancel:CancellationToken::new(),
        alive:AtomicBool::new(true),denial:Mutex::new(None) });
    let (port, receiver) = channel(socket);
    let changes = Arc::new(Changes::default());
    *changes.read_port.lock().unwrap() = Some(port);
    (ChatMonitor { fence, changes }, receiver)
}
async fn sockets() -> (Socket, Peer) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let connect = tokio_tungstenite::connect_async(format!("ws://{address}"));
    let accept = async { let (stream, _) = listener.accept().await.unwrap(); tokio_tungstenite::accept_async(stream).await.unwrap() };
    let (client, peer) = tokio::join!(connect, accept);
    (transport::test_socket(client.unwrap().0), peer)
}
fn spawn(socket: Socket, monitor: &ChatMonitor, receiver: MonitorReadReceiver) -> tokio::task::JoinHandle<()> {
    let (errors, _unused) = mpsc::channel(8);
    // Keep the error consumer alive: actor lifecycle must not end from a fixture's
    // dropped errors receiver. It is owned only by this exact test task.
    let changes = monitor.changes.clone(); let fence = monitor.fence.clone();
    tokio::spawn(async move {
        let _errors_receiver = _unused;
        monitor_socket_mode(socket,fence.cancel.clone(),errors,fence.team.as_deref().map(sha256),json!({}),
            Duration::from_secs(25),Some(changes),Some(fence),Some(receiver)).await;
    })
}
async fn send(peer: &mut Peer, kind: &str, payload: Value) {
    peer.send(Frame::Text(json!({"type":kind,"payload":payload}).to_string().into())).await.unwrap();
}
async fn request(peer: &mut Peer) -> Value {
    loop {
        let frame = tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap().unwrap().unwrap();
        match frame {
            Frame::Text(text) => { let value:Value=serde_json::from_str(&text).unwrap(); if value["type"]!="native_client_lifecycle" { return value; } },
            Frame::Ping(data) => peer.send(Frame::Pong(data)).await.unwrap(),
            other => panic!("unexpected protocol frame: {other:?}"),
        }
    }
}
async fn complete(peer: &mut Peer, epoch: u64) {
    send(peer,"phase_2_last_20_chats_ready",json!({"context_epoch":epoch,"team_id":null,"chats":[]})).await;
    send(peer,"phased_sync_complete",json!({"context_epoch":epoch,"team_id":null,"phase":"all"})).await;
}
async fn closed(peer: &mut Peer) {
    loop {
        let frame=tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap();
        match frame { Some(Ok(Frame::Close(_)))|None=>return,Some(Ok(Frame::Text(_)))=>{},other=>panic!("expected original socket close: {other:?}") }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn one_original_socket_interleaves_hints_and_successive_epochs_ignore_stale_completions() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);
    let task=spawn(socket,&monitor,receiver);
    let server=tokio::spawn(async move {
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
        let first=request(&mut peer).await;assert_eq!(first["type"],"phased_sync_request");let a=first["payload"]["context_epoch"].as_u64().unwrap();assert!(a>0);
        send(&mut peer,"new_chat_message",json!({"chat_id":CHAT,"messages_v":2})).await;complete(&mut peer,a).await;
        let second=request(&mut peer).await;let b=second["payload"]["context_epoch"].as_u64().unwrap();assert!(b>a);
        // Same socket's old terminal cannot satisfy the next command.
        complete(&mut peer,a).await;send(&mut peer,"chat_title_updated",json!({"chat_id":CHAT,"metadata_v":3})).await;
        complete(&mut peer,b).await;closed(&mut peer).await;
    });
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let first=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();
    assert!(matches!(first.take(&client,&monitor,&original).unwrap(),MonitorReadData::RecentSync(_)));
    let second=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();
    assert!(matches!(second.take(&client,&monitor,&original).unwrap(),MonitorReadData::RecentSync(_)));
    let pending=monitor.take_pending().unwrap().unwrap();assert!(pending.pending.chats.contains(CHAT));assert_eq!(pending.pending.versions[CHAT].metadata_v,3);
    monitor.close();task.await.unwrap();server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn uncorrelated_dispatched_draft_cancellation_closes_original_socket_and_fresh_b_works() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let a=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1)])).unwrap();
    let got=request(&mut peer).await;assert_eq!(got["type"],"get_draft_versions");drop(ticket);
    closed(&mut peer).await;task.await.unwrap();assert!(!monitor.is_valid());
    // No account/root cancellation or new authority is invented: a genuine
    // independent explicit B uses a fresh original monitor/socket/scope.
    let (socket,mut peer)=sockets().await;let (bmonitor,receiver)=monitor_fixture_again(&client,&socket);let btask=spawn(socket,&bmonitor,receiver);
    let b=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&bmonitor,&b,MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1)])).unwrap();
    assert_eq!(request(&mut peer).await["type"],"get_draft_versions");
    send(&mut peer,"draft_versions_response",json!({"versions":{(CHAT):2},"tombstone_versions":{},"unavailable_chat_ids":[]})).await;
    let receipt=ticket.wait().await.unwrap();let MonitorReadData::DraftVersions(data)=receipt.take(&client,&bmonitor,&b).unwrap() else {panic!("wrong DATA kind")};assert_eq!(data.versions[CHAT],2);
    bmonitor.close();closed(&mut peer).await;btask.await.unwrap();
}
fn monitor_fixture_again(client:&Client,socket:&Socket)->(ChatMonitor,MonitorReadReceiver){monitor(client,socket)}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn security_notifications_are_processed_during_original_read_before_epoch_filtering() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::DraftMetadata(Some(CHAT.into()))).unwrap();
    assert_eq!(request(&mut peer).await["type"],"phased_sync_request");
    send(&mut peer,"phased_sync_complete",json!({"context_epoch":0,"team_id":null,"phase":"phase2"})).await;
    send(&mut peer,"force_logout",json!({})).await;
    assert!(matches!(ticket.wait().await,Err(Error::Expired)));closed(&mut peer).await;task.await.unwrap();
    assert!(matches!(monitor.access_denial().unwrap(),Some(ChatMonitorAccessDenial::Expired)));assert!(original.check(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn bounded_queue_queued_abandonment_cannot_cancel_independent_b() {
    let client=fixture();let (socket,_peer)=sockets().await;let (monitor,mut receiver)=monitor(&client,&socket);let a=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let b=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let mut tickets=Vec::new();
    for _ in 0..QUEUE_CAPACITY { tickets.push(client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::DraftVersions(vec![])).unwrap()); }
    assert!(matches!(client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::RecentSync),Err(Error::Conflict)));
    drop(tickets);let command=receiver.receiver.try_recv().unwrap();assert!(matches!(command.check(),Err(Error::Cancelled)));assert!(b.check(&client).is_ok());

}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn explicit_monitor_close_drains_only_original_socket_and_refuses_queued_read() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);
    let task=spawn(socket,&monitor,receiver);let a=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::RecentSync).unwrap();monitor.close();
    assert!(ticket.wait().await.is_err());closed(&mut peer).await;task.await.unwrap();assert!(a.check(&client).is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn fixed_read_requests_frame_budget_epoch_exhaustion_and_team_drafts_fail_closed() {
    let mut client=fixture();let (socket,_peer)=sockets().await;let (monitor,_receiver)=monitor(&client,&socket);let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    monitor.changes.read_port.lock().unwrap().as_ref().unwrap().next_epoch.store(MAX_CONTEXT_EPOCH,Ordering::Release);
    assert!(matches!(client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync),Err(Error::Conflict)));
    let mut budget=ReadBudget{frames:MAX_READ_FRAMES,bytes:0};assert_eq!(budget.observe(&json!({})),Err(Error::Protocol));
    let mut budget=ReadBudget{frames:0,bytes:MAX_READ_BYTES};assert_eq!(budget.observe(&json!({"data":"bounded"})),Err(Error::Protocol));
    assert!(MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1),(CHAT.into(),2)]).validate(None).is_err());
    assert!(MonitorReadRequest::DraftMetadata(Some("not-a-uuid".into())).validate(None).is_err());
    assert!(MonitorReadRequest::DraftVersions(vec![]).validate(Some(CHAT)).is_err());
    client.operation_parent.cancel();assert!(original.check(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn actual_socket_receipt_rejects_rebinding_to_b_scope_then_fresh_b_succeeds() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let server=tokio::spawn(async move {
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
        for _ in 0..2 { let request=request(&mut peer).await;complete(&mut peer,request["payload"]["context_epoch"].as_u64().unwrap()).await; }
        closed(&mut peer).await;
    });
    let a=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let b=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let receipt=client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();
    assert!(matches!(receipt.take(&client,&monitor,&b),Err(Error::Cancelled)));
    let receipt=client.prepare_monitor_read(&monitor,&b,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();
    assert!(matches!(receipt.take(&client,&monitor,&b).unwrap(),MonitorReadData::RecentSync(_)));
    monitor.close();task.await.unwrap();server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn exact_team_revocation_during_read_is_not_hidden_by_stale_or_unrelated_context() {
    let mut client=fixture();client.session.as_mut().unwrap().active_team_id=Some(CHAT.into());
    let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap();
    send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
    let actual=request(&mut peer).await;assert_eq!(actual["payload"]["team_id"],CHAT);
    send(&mut peer,"project_remote_access_revoked",json!({"context_type":"personal","context_id_hash":sha256(CHAT)})).await;
    send(&mut peer,"project_remote_access_revoked",json!({"context_type":"team","context_id_hash":sha256("other")})).await;
    send(&mut peer,"project_remote_access_revoked",json!({"context_type":"team","context_id_hash":sha256(CHAT)})).await;
    assert!(matches!(ticket.wait().await,Err(Error::Forbidden)));closed(&mut peer).await;task.await.unwrap();
    assert!(matches!(monitor.access_denial().unwrap(),Some(ChatMonitorAccessDenial::ScopeRevoked)));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn original_heartbeat_sends_after_pending_receive_is_dropped_during_read() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);
    let (errors,_errors_receiver)=mpsc::channel(8);let fence=monitor.fence.clone();let changes=monitor.changes.clone();
    let task=tokio::spawn(monitor_socket_mode(socket,fence.cancel.clone(),errors,None,json!({"client_type":"fixture"}),Duration::from_millis(5),Some(changes),Some(fence),Some(receiver)));
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1)])).unwrap();
    assert_eq!(request(&mut peer).await["type"],"get_draft_versions");
    let frame=tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap().unwrap().unwrap();
    let Frame::Text(raw)=frame else {panic!("heartbeat missing on original socket")};let value:Value=serde_json::from_str(&raw).unwrap();assert_eq!(value["type"],"native_client_lifecycle");
    drop(ticket);closed(&mut peer).await;task.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_queued_a_sends_nothing_and_b_uses_same_original_socket() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);
    let a=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&a,MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1)])).unwrap();
    a.observer().cancel();let task=spawn(socket,&monitor,receiver);
    assert!(matches!(ticket.wait().await,Err(Error::Cancelled)));assert!(monitor.is_valid());
    let b=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&b,MonitorReadRequest::DraftMetadata(Some(CHAT.into()))).unwrap();
    // No A draft request can precede this B phased request on the actual socket.
    let request=request(&mut peer).await;assert_eq!(request["type"],"phased_sync_request");let epoch=request["payload"]["context_epoch"].as_u64().unwrap();
    send(&mut peer,"phase_2_last_20_chats_ready",json!({"context_epoch":epoch,"team_id":null,"phase":"phase2","chats":[]})).await;
    send(&mut peer,"phased_sync_complete",json!({"context_epoch":epoch,"team_id":null,"phase":"phase2"})).await;
    assert!(matches!(ticket.wait().await.unwrap().take(&client,&monitor,&b).unwrap(),MonitorReadData::DraftMetadata(_)));
    monitor.close();closed(&mut peer).await;task.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[test]
fn data_or_policy_error_categories_cannot_mint_authenticated_monitor_denials() {
    assert_eq!(ActorFailure::from(Error::Forbidden).monitor_error(),Error::Protocol);
    assert_eq!(ActorFailure::from(Error::Expired).monitor_error(),Error::Protocol);
    assert_eq!(ActorFailure::socket(Error::Expired).monitor_error(),Error::Expired);
    assert_eq!(ActorFailure::socket(Error::Forbidden).monitor_error(),Error::Protocol);
    assert_eq!(ActorFailure::observed(Error::Forbidden).monitor_error(),Error::Forbidden);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn caller_policy_forbidden_during_read_refuses_data_without_forging_socket_denial() {
    let mut client=fixture();let deny=Arc::new(AtomicBool::new(false));let policy=deny.clone();
    client.set_private_operation_gate(Some(Arc::new(move||if policy.load(Ordering::Acquire){Err(Error::Forbidden)}else{Ok(())})));
    let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::DraftMetadata(Some(CHAT.into()))).unwrap();
    let request=request(&mut peer).await;let epoch=request["payload"]["context_epoch"].as_u64().unwrap();deny.store(true,Ordering::Release);
    send(&mut peer,"phase_2_last_20_chats_ready",json!({"context_epoch":epoch,"team_id":null,"phase":"phase2","chats":[]})).await;
    assert!(matches!(ticket.wait().await,Err(Error::Forbidden)));closed(&mut peer).await;task.await.unwrap();
    assert!(monitor.access_denial().unwrap().is_none());assert!(!client.task_watch_authority.cancel.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn received_exact_team_negative_precedes_postreceive_request_callback_and_budget_refusal() {
    use std::sync::atomic::AtomicUsize;
    for exhausted_budget in [false,true] {
        let mut client=fixture();client.session.as_mut().unwrap().active_team_id=Some(CHAT.into());
        let armed=Arc::new(AtomicBool::new(false));let calls=Arc::new(AtomicUsize::new(0));
        let request_cancel=CancellationToken::new();let original_cancel=request_cancel.clone();
        let policy_armed=armed.clone();let policy_calls=calls.clone();
        client.set_private_operation_gate(Some(Arc::new(move||{
            // The first armed call is frame's pre-receive check. The next can
            // run only after receive_monitor returned the ACTUAL peer frame.
            if policy_armed.load(Ordering::Acquire)&&policy_calls.fetch_add(1,Ordering::AcqRel)==1&&!exhausted_budget { original_cancel.cancel(); }
            Ok(())
        })));
        let (mut socket,mut peer)=sockets().await;let (monitor,mut receiver)=monitor(&client,&socket);
        let original=OwnedOperationScope::capture(&client,request_cancel.clone()).unwrap();
        let _ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap();
        let command=receiver.receiver.try_recv().unwrap();
        assert!(receiver.original_socket.same_original_socket(&socket));
        let server=tokio::spawn(async move {
            send(&mut peer,"project_remote_access_revoked",json!({"context_type":"team","context_id_hash":sha256(CHAT)})).await;
        });
        let (events,_events_receiver)=mpsc::channel(1);
        let mut heartbeat=crate::platform::time::interval_at(crate::platform::time::Instant::now()+Duration::from_secs(25),Duration::from_secs(25));
        let mut budget=ReadBudget{frames:if exhausted_budget{MAX_READ_FRAMES}else{0},bytes:0};
        armed.store(true,Ordering::Release);
        let result=receiver.frame(&command,&mut socket,Some(&monitor.changes),Some(&sha256(CHAT)),&json!({}),&mut heartbeat,
            crate::platform::time::Instant::now()+Duration::from_secs(2),&mut budget,&events).await;
        let Err(failure)=result else {panic!("received authenticated Team negative was released as DATA")};
        assert!(failure.authenticated_negative);
        assert_eq!(failure.error,Error::Forbidden);
        // Selecting this actual socket negative did not invoke the later
        // request-only callback or accept even one byte as request DATA.
        assert_eq!(calls.load(Ordering::Acquire),1);assert!(!request_cancel.is_cancelled());
        assert_eq!(budget.frames,if exhausted_budget{MAX_READ_FRAMES}else{0});
        server.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn received_ordinary_frame_still_refuses_original_request_cancel_before_data_return() {
    use std::sync::atomic::AtomicUsize;
    let mut client=fixture();let armed=Arc::new(AtomicBool::new(false));let calls=Arc::new(AtomicUsize::new(0));
    let request_cancel=CancellationToken::new();let original_cancel=request_cancel.clone();let a=armed.clone();let n=calls.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{
        if a.load(Ordering::Acquire)&&n.fetch_add(1,Ordering::AcqRel)==1 {original_cancel.cancel();}Ok(())
    })));
    let (mut socket,mut peer)=sockets().await;let (monitor,mut receiver)=monitor(&client,&socket);
    let original=OwnedOperationScope::capture(&client,request_cancel.clone()).unwrap();
    let _ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::DraftMetadata(Some(CHAT.into()))).unwrap();
    let command=receiver.receiver.try_recv().unwrap();let epoch=command.epoch;
    let server=tokio::spawn(async move{send(&mut peer,"phase_2_last_20_chats_ready",json!({"context_epoch":epoch,"team_id":null,"phase":"phase2","chats":[]})).await;});
    let (events,_events_receiver)=mpsc::channel(1);let mut heartbeat=crate::platform::time::interval_at(crate::platform::time::Instant::now()+Duration::from_secs(25),Duration::from_secs(25));
    let mut budget=ReadBudget{frames:0,bytes:0};armed.store(true,Ordering::Release);
    let result=receiver.frame(&command,&mut socket,Some(&monitor.changes),None,&json!({}),&mut heartbeat,
        crate::platform::time::Instant::now()+Duration::from_secs(2),&mut budget,&events).await;
    let Err(failure)=result else {panic!("cancelled original request released private DATA")};
    assert!(!failure.authenticated_negative);assert_eq!(failure.error,Error::Cancelled);assert!(request_cancel.is_cancelled());
    assert_eq!(budget.frames,0);assert!(original.check(&client).is_err());server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn actual_completed_receipt_rechecks_original_request_after_final_policy_callback() {
    let mut client=fixture();let armed=Arc::new(AtomicBool::new(false));let request_cancel=CancellationToken::new();
    let original_cancel=request_cancel.clone();let policy=armed.clone();
    client.set_private_operation_gate(Some(Arc::new(move||{if policy.load(Ordering::Acquire){original_cancel.cancel();}Ok(())})));
    let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,request_cancel.clone()).unwrap();let b=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::DraftVersions(vec![(CHAT.into(),1)])).unwrap();
    assert_eq!(request(&mut peer).await["type"],"get_draft_versions");
    send(&mut peer,"draft_versions_response",json!({"versions":{(CHAT):2},"tombstone_versions":{},"unavailable_chat_ids":[]})).await;
    let receipt=ticket.wait().await.unwrap();armed.store(true,Ordering::Release);
    assert!(matches!(receipt.take(&client,&monitor,&original),Err(Error::Cancelled)));
    assert!(request_cancel.is_cancelled());assert!(b.check(&client).is_ok());
    monitor.close();closed(&mut peer).await;task.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative,auth.session.isolation
#[tokio::test]
async fn original_socket_metadata_responses_filter_old_epoch_and_keep_older_pages_memory_only() {
    let client=fixture();let (socket,mut peer)=sockets().await;let (monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let server=tokio::spawn(async move {
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
        let first=request(&mut peer).await;assert_eq!(first["type"],"phased_sync_request");let epoch=first["payload"]["context_epoch"].as_u64().unwrap();assert!(epoch>0);
        let mut expanded=json!({"context_epoch":epoch-1,"team_id":null,"total_count":1234,"chats":[{"chat_details":{"id":"70000000-0000-4000-8000-000000000001","encrypted_title":"opaque"}}]});
        send(&mut peer,"sync_metadata_chats_response",expanded.clone()).await;
        expanded["context_epoch"]=json!(epoch);expanded["chats"][0]["chat_details"]["id"]=json!("70000000-0000-4000-8000-000000000002");send(&mut peer,"sync_metadata_chats_response",expanded).await;
        send(&mut peer,"load_more_chats_response",json!({"context_epoch":epoch,"team_id":null,"total_count":1234,"offset":1000,"has_more":false,"chats":[{"chat_details":{"id":"80000000-0000-4000-8000-000000000001","parent_id":CHAT,"is_sub_chat":true}}]})).await;
        complete(&mut peer,epoch).await;closed(&mut peer).await;
    });
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let receipt=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();
    let MonitorReadData::RecentSync(data)=receipt.take(&client,&monitor,&original).unwrap() else {panic!("wrong DATA kind")};
    assert_eq!(data.chats.len(),1);assert_eq!(data.chat_arrival_order,vec!["70000000-0000-4000-8000-000000000002"]);
    assert_eq!(data.phase1_windows.older_metadata_pages().len(),1);assert_eq!(data.phase1_windows.older_metadata_pages()["1000"]["has_more"],false);
    assert!(client.chats.is_empty()); // Parsing an actual socket still grants no apply/IO capability.
    monitor.close();task.await.unwrap();server.await.unwrap();
}

async fn startup_boundary(peer:&mut Peer,epoch:u64,count:Option<u64>){
    let mut payload=json!({"context_epoch":epoch,"team_id":null,"chats":[]});if let Some(count)=count{payload["total_chat_count"]=json!(count);}
    send(peer,"phase_2_last_20_chats_ready",payload).await;
    send(peer,"phased_sync_complete",json!({"context_epoch":epoch,"team_id":null,"phase":"all"})).await;
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative,auth.session.isolation
#[tokio::test]
async fn explicit_metadata_operation_requests_only_after_startup_terminal_on_same_original_socket(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let server=tokio::spawn(async move{
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
        let initial=request(&mut peer).await;assert_eq!(initial["type"],"phased_sync_request");let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();
        startup_boundary(&mut peer,epoch,Some(1234)).await;
        let metadata=request(&mut peer).await;assert_eq!(metadata["type"],"sync_metadata_chats");assert_eq!(metadata["payload"],json!({"context_epoch":epoch,"existing_chat_ids":[CHAT]}));
        let mut page=json!({"context_epoch":epoch-1,"team_id":null,"total_count":1234,"chats":[{"chat_details":{"id":"70000000-0000-4000-8000-000000000001","encrypted_title":"opaque雪","pinned":true,"draft_v":7,"encrypted_draft_md":"cipher"}}]});
        send(&mut peer,"sync_metadata_chats_response",page.clone()).await;
        send(&mut peer,"new_chat_message",json!({"chat_id":CHAT,"messages_v":2})).await;
        page["context_epoch"]=json!(epoch);send(&mut peer,"sync_metadata_chats_response",page).await;closed(&mut peer).await;
    });
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let receipt=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSyncWithExpandedMetadata(vec![CHAT.into()])).unwrap().wait().await.unwrap();
    let MonitorReadData::RecentSync(data)=receipt.take(&client,&monitor,&original).unwrap()else{panic!("wrong DATA kind")};
    assert_eq!(data.chats.len(),1);assert_eq!(data.chats["70000000-0000-4000-8000-000000000001"]["encrypted_draft_md"],"cipher");
    assert!(client.chats.is_empty());assert!(monitor.take_pending().unwrap().unwrap().pending.chats.contains(CHAT));
    monitor.close();task.await.unwrap();server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn expanded_request_abandonment_after_startup_retires_actual_socket_without_canceling_independent_scope(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let independent=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
    let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSyncWithExpandedMetadata(vec![])).unwrap();
    send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let first=request(&mut peer).await;let epoch=first["payload"]["context_epoch"].as_u64().unwrap();
    startup_boundary(&mut peer,epoch,Some(101)).await;assert_eq!(request(&mut peer).await["type"],"sync_metadata_chats");drop(ticket);
    closed(&mut peer).await;task.await.unwrap();assert!(!monitor.is_valid());assert!(independent.check(&client).is_ok());assert!(client.chats.is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[tokio::test]
async fn ordinary_sync_never_expands_and_explicit_metadata_does_not_infer_total_from_cache_or_absence(){
    for (opt_in,count) in [(false,Some(1234)),(true,Some(100)),(true,None)]{
        let client=fixture();let(socket,mut peer)=sockets().await;let(monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
        let server=tokio::spawn(async move{
            send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
            let first=request(&mut peer).await;assert_eq!(first["type"],"phased_sync_request");let epoch=first["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,count).await;
            // Client closes after the returned original receipt. Any metadata
            // request here is an unexpected non-lifecycle frame and fails.
            loop{let frame=tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap();match frame{
                Some(Ok(Frame::Close(_)))|None=>break,
                Some(Ok(Frame::Text(text)))=>{let value:Value=serde_json::from_str(&text).unwrap();assert_eq!(value["type"],"native_client_lifecycle");},
                other=>panic!("unexpected frame: {other:?}"),
            }}
        });
        let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();
        let request=if opt_in{MonitorReadRequest::RecentSyncWithExpandedMetadata(vec![])}else{MonitorReadRequest::RecentSync};
        let receipt=client.prepare_monitor_read(&monitor,&original,request).unwrap().wait().await.unwrap();assert!(matches!(receipt.take(&client,&monitor,&original).unwrap(),MonitorReadData::RecentSync(_)));
        monitor.close();task.await.unwrap();server.await.unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn post_startup_metadata_server_error_is_not_empty_success_or_ready_ack(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(monitor,receiver)=monitor(&client,&socket);let task=spawn(socket,&monitor,receiver);
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let ticket=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSyncWithExpandedMetadata(vec![])).unwrap();
    send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let initial=request(&mut peer).await;let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;assert_eq!(request(&mut peer).await["type"],"sync_metadata_chats");
    send(&mut peer,"sync_metadata_chats_response",json!({"context_epoch":epoch,"team_id":null,"total_count":0,"chats":[],"error":"Failed to sync metadata chats"})).await;
    assert!(matches!(ticket.wait().await,Err(Error::Offline)));closed(&mut peer).await;task.await.unwrap();assert!(client.chats.is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases,auth.session.isolation
#[tokio::test]
async fn genuine_initial_operation_dispatches_once_then_consumes_actual_metadata_io_on_same_socket(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let monitor=Arc::new(handle);
    let server=tokio::spawn(async move{
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;
        let initial=request(&mut peer).await;assert_eq!(initial["type"],"phased_sync_request");let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;
        let metadata=request(&mut peer).await;assert_eq!(metadata["type"],"sync_metadata_chats");assert_eq!(metadata["payload"],json!({"context_epoch":epoch,"existing_chat_ids":[]}));
        send(&mut peer,"sync_metadata_chats_response",json!({"context_epoch":epoch,"team_id":null,"total_count":1234,"chats":[{"chat_details":{"id":"70000000-0000-4000-8000-000000000001","encrypted_title":"opaque"}}]})).await;
        // Any second initial request would be visible before the close and fail.
        loop{match tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap(){
            Some(Ok(Frame::Close(_)))|None=>break,Some(Ok(Frame::Text(text)))=>{let value:Value=serde_json::from_str(&text).unwrap();assert_eq!(value["type"],"native_client_lifecycle");},other=>panic!("unexpected repeated startup frame:{other:?}"),
        }}
    });
    let pending=client.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();let control=pending.control();control.ensure_current(&client).unwrap();
    let batch=pending.wait().await.unwrap().retain(&client).unwrap();assert_eq!(batch.received_metadata_count(&client).unwrap(),1);assert!(client.chats.is_empty());
    let repeated=client.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();assert!(matches!(repeated.wait().await,Err(Error::Conflict)));
    batch.ensure_current(&client).unwrap();monitor.close();task.await.unwrap();server.await.unwrap();assert!(control.ensure_current(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases,auth.session.isolation
#[tokio::test]
async fn selected_recent_read_cannot_be_relabelled_as_initial_startup_or_fetch_expanded_metadata(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let monitor=Arc::new(handle);
    let server=tokio::spawn(async move{
        send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let first=request(&mut peer).await;let epoch=first["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;
        loop{match tokio::time::timeout(Duration::from_secs(2),peer.next()).await.unwrap(){Some(Ok(Frame::Close(_)))|None=>break,Some(Ok(Frame::Text(text)))=>{let value:Value=serde_json::from_str(&text).unwrap();assert_eq!(value["type"],"native_client_lifecycle");},other=>panic!("selected open emitted extra frame:{other:?}")}}
    });
    let original=OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap();let receipt=client.prepare_monitor_read(&monitor,&original,MonitorReadRequest::RecentSync).unwrap().wait().await.unwrap();drop(receipt.take(&client,&monitor,&original).unwrap());
    let pending=client.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();assert!(matches!(pending.wait().await,Err(Error::Conflict)));
    monitor.close();task.await.unwrap();server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn actual_profile_forget_cancels_dispatched_initial_metadata_and_invalidates_its_control(){
    let mut client=fixture();let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let monitor=Arc::new(handle);
    let pending=client.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();let control=pending.control();
    send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let initial=request(&mut peer).await;let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;assert_eq!(request(&mut peer).await["type"],"sync_metadata_chats");
    let independent=fixture();client.forget_session();assert!(control.ensure_current(&client).is_err());assert!(pending.wait().await.is_err());closed(&mut peer).await;task.await.unwrap();assert!(independent.require_credentials().is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn actual_cookie_headers_preserve_initial_io_scope_but_unwitnessed_credentials_do_not(){
    use tokio::io::{AsyncReadExt,AsyncWriteExt};
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let address=listener.local_addr().unwrap();
    let http=tokio::spawn(async move{let(mut stream,_)=listener.accept().await.unwrap();let mut request=Vec::new();loop{let mut bytes=[0u8;1024];let count=stream.read(&mut bytes).await.unwrap();assert!(count>0);request.extend_from_slice(&bytes[..count]);if request.windows(4).any(|part|part==b"\r\n\r\n"){break;}assert!(request.len()<8192);}assert!(String::from_utf8_lossy(&request).starts_with("GET /v1/tasks/fixture-task "));stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}").await.unwrap();});
    let mut client=fixture();let base=format!("http://{address}");let mut session=client.session.take().unwrap();session.api_url=base.clone();client.reset(&base,Some(session)).unwrap();client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
    let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let monitor=Arc::new(handle);
    let pending=client.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();let control=pending.control();
    send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let initial=request(&mut peer).await;let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;assert_eq!(request(&mut peer).await["type"],"sync_metadata_chats");
    let prepared=client.prepare_owned_read(transport::OwnedReadRoute::AppTask("fixture-task")).unwrap();let cancel=CancellationToken::new();let headers=transport::send_owned_read_headers(prepared,&cancel,||control.check_original_negative()).await.unwrap();let body=client.apply_owned_read_headers(headers).unwrap();control.ensure_current(&client).unwrap();
    let completed=transport::drive_owned_read_body(body,&cancel,||control.check_original_negative()).await.unwrap();assert_eq!(client.finish_owned_read(completed).unwrap(),Some(json!({"ok":true})));assert_eq!(client.session.as_ref().unwrap().cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
    send(&mut peer,"sync_metadata_chats_response",json!({"context_epoch":epoch,"team_id":null,"total_count":1234,"chats":[]})).await;let batch=pending.wait().await.unwrap().retain(&client).unwrap();assert_eq!(batch.received_metadata_count(&client).unwrap(),0);
    client.credentials_changed();assert!(batch.ensure_current(&client).is_err());assert!(control.ensure_current(&client).is_err());monitor.close();closed(&mut peer).await;task.await.unwrap();http.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn replacing_actual_connection_retires_old_initial_intent_and_fresh_connection_can_start_once(){
    let client=fixture();let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let old=Arc::new(handle);
    let pending=client.prepare_initial_sync(old.clone(),CancellationToken::new()).unwrap();let control=pending.control();send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let initial=request(&mut peer).await;let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(1234)).await;assert_eq!(request(&mut peer).await["type"],"sync_metadata_chats");old.close();assert!(pending.wait().await.is_err());closed(&mut peer).await;task.await.unwrap();assert!(control.ensure_current(&client).is_err());
    let(socket,mut peer)=sockets().await;let(handle,receiver)=monitor(&client,&socket);let task=spawn(socket,&handle,receiver);let fresh=Arc::new(handle);let server=tokio::spawn(async move{send(&mut peer,"recovery_outputs_discovery_complete",json!({"status":"disabled"})).await;let initial=request(&mut peer).await;let epoch=initial["payload"]["context_epoch"].as_u64().unwrap();startup_boundary(&mut peer,epoch,Some(100)).await;closed(&mut peer).await;});
    let batch=client.prepare_initial_sync(fresh.clone(),CancellationToken::new()).unwrap().wait().await.unwrap().retain(&client).unwrap();assert_eq!(batch.received_metadata_count(&client).unwrap(),0);fresh.close();task.await.unwrap();server.await.unwrap();
}
