//! Genuine native loopback WebSocket resource tests, authored UNRUN.
// contract-test-file: tooling
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.isolation
use super::*;
use tungstenite::Message;
use std::{future::{Future, poll_fn},sync::{Arc,atomic::{AtomicUsize,Ordering}},task::Poll};
use tokio::{net::TcpListener,sync::oneshot};

fn ok<T>(result: Result<T>) -> T {
    match result { Ok(value) => value, Err(_) => panic!("transport operation failed") }
}
async fn poll_actual_receive_pending<F:Future>(future:std::pin::Pin<&mut F>) {
    let mut future=future;
    let observed=poll_fn(|cx|Poll::Ready(future.as_mut().poll(cx))).await;
    assert!(observed.is_pending(),"the peer must still hold actual socket frames");
}
async fn original_connection() -> (Socket,tokio::task::JoinHandle<()>,Arc<AtomicUsize>) {
    let listener=TcpListener::bind("127.0.0.1:0").await.expect("loopback bind");
    let address=listener.local_addr().expect("loopback address");
    let count=Arc::new(AtomicUsize::new(0));let observed=count.clone();
    let peer=tokio::spawn(async move {
        let (tcp,_)=listener.accept().await.expect("one actual TCP connection");
        observed.fetch_add(1,Ordering::SeqCst);
        let mut ws=tokio_tungstenite::accept_async(tcp).await.expect("real WS handshake");
        // No initial frames: the client must poll a real receive to Pending.
        let message=ws.next().await.expect("phase frame").expect("valid phase frame");
        let Message::Text(text)=message else {panic!("text phase frame")};
        let wire:Value=serde_json::from_str(&text).expect("phase JSON");
        assert_eq!(wire,json!({"type":"phase_commit","payload":{"id":"original-A"}}));
        ws.send(Message::Text(json!({"type":"metadata_notice","payload":{"chat_id":"original-A","ordered":[3,1,2],"marker":"same-original-pending-frame"}}).to_string().into())).await.expect("real unrelated frame");
        ws.send(Message::Text(json!({"type":"phase_committed","payload":{"id":"original-A"}}).to_string().into())).await.expect("real exact ACK");
        assert!(matches!(ws.next().await,Some(Ok(Message::Close(_)))) ,"same resource close reaches original peer");
        assert!(std::future::poll_fn(|cx| std::task::Poll::Ready(listener.poll_accept(cx))).await.is_pending(),"phase handle must not establish another connection");
    });
    let (stream,_)=tokio_tungstenite::connect_async(format!("ws://{address}")).await.expect("actual original connect");
    (test_socket(stream),peer,count)
}
async fn exercise_same_resource(cancel_read_task:bool) {
    let (mut original,peer,count)=original_connection().await;
    let mut phase=original.original_phase_handle();
    let mut continuation=original.original_phase_handle();
    assert!(phase.same_original_socket(&original));
    assert!(continuation.same_original_socket(&phase));
    if cancel_read_task {
        let (entered,ready)=oneshot::channel();
        let reader=tokio::spawn(async move {
            let mut pending=Box::pin(receive(&mut original));
            poll_actual_receive_pending(pending.as_mut()).await;
            entered.send(()).expect("actual receive pending signal");
            pending.await
        });
        ready.await.expect("actual pending receive entered");
        assert!(matches!(receive(&mut phase).await,Err(Error::Conflict)),"a second receiver must not wait for or steal A frames");
        reader.abort();
        match reader.await {Err(error)=>assert!(error.is_cancelled()),Ok(_)=>panic!("receive task must abort")};
    } else {
        let mut pending=Box::pin(receive(&mut original));
        poll_actual_receive_pending(pending.as_mut()).await;
        assert!(matches!(receive(&mut phase).await,Err(Error::Conflict)),"single actual receive owner");
        drop(pending);
    }
    assert!(!phase.resource.receiving.load(Ordering::Acquire),"read-future drop releases exact receive owner");
    assert!(phase.resource.inner.try_lock().is_ok(),"no stream mutex survives the cancelled read");
    ok(send(&mut phase,"phase_commit",json!({"id":"original-A"})).await);
    assert_eq!(ok(wait(&mut phase,"phase_committed","id","original-A").await),json!({"id":"original-A"}));
    assert_eq!(phase.resource.pending.lock().expect("pending queue").len(),1,"unrelated actual frame retained on same queue");
    let (kind,payload)=ok(receive(&mut continuation).await);
    assert_eq!(kind,"metadata_notice");
    assert_eq!(payload,json!({"chat_id":"original-A","ordered":[3,1,2],"marker":"same-original-pending-frame"}));
    assert!(phase.resource.pending.lock().expect("pending queue").is_empty());
    phase.close(None).await.expect("close exact physical resource");
    peer.await.expect("peer assertions");
    assert_eq!(count.load(Ordering::SeqCst),1,"one real TCP/WS connection across all phases");
}
#[tokio::test]
async fn dropping_actual_receive_allows_original_phase_ack_and_shared_pending() {
    tokio::time::timeout(Duration::from_secs(5),exercise_same_resource(false)).await.expect("resource deadlock watchdog");
}
#[tokio::test]
async fn aborting_actual_receive_task_releases_only_original_read_owner() {
    tokio::time::timeout(Duration::from_secs(5),exercise_same_resource(true)).await.expect("resource deadlock watchdog");
}
#[tokio::test]
async fn exact_close_of_a_keeps_independent_real_socket_b_usable() {
    tokio::time::timeout(Duration::from_secs(5),async {
        let listener=TcpListener::bind("127.0.0.1:0").await.expect("loopback bind");
        let address=listener.local_addr().expect("loopback address");
        let (a_closed,observed_close)=oneshot::channel();
        let peer=tokio::spawn(async move {
            let (tcp_a,_)=listener.accept().await.expect("actual A connection");
            let mut a=tokio_tungstenite::accept_async(tcp_a).await.expect("A WS");
            let (tcp_b,_)=listener.accept().await.expect("actual independent B connection");
            let mut b=tokio_tungstenite::accept_async(tcp_b).await.expect("B WS");
            assert!(matches!(a.next().await,Some(Ok(Message::Close(_)))));
            a_closed.send(()).expect("actual A close observed");
            let frame=b.next().await.expect("B request").expect("valid B request");
            let Message::Text(text)=frame else {panic!("B text")};
            assert_eq!(serde_json::from_str::<Value>(&text).expect("B JSON"),json!({"type":"phase_commit","payload":{"id":"independent-B"}}));
            b.send(Message::Text(json!({"type":"phase_committed","payload":{"id":"independent-B"}}).to_string().into())).await.expect("real B ACK");
            assert!(matches!(b.next().await,Some(Ok(Message::Close(_)))));
            assert!(std::future::poll_fn(|cx| std::task::Poll::Ready(listener.poll_accept(cx))).await.is_pending());
        });
        let (stream_a,_)=tokio_tungstenite::connect_async(format!("ws://{address}")).await.expect("A actual connect");
        let mut a=test_socket(stream_a);
        let (stream_b,_)=tokio_tungstenite::connect_async(format!("ws://{address}")).await.expect("B actual connect");
        let mut b=test_socket(stream_b);
        assert!(!a.same_original_socket(&b));
        a.close(None).await.expect("close A only");observed_close.await.expect("A peer close reached");
        ok(send(&mut b,"phase_commit",json!({"id":"independent-B"})).await);
        assert_eq!(ok(wait(&mut b,"phase_committed","id","independent-B").await),json!({"id":"independent-B"}));
        b.close(None).await.expect("close B");peer.await.expect("actual peer assertions");
    }).await.expect("independent B socket watchdog");
}
