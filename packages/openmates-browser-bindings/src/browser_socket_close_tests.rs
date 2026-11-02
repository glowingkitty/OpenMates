//! Authored UNRUN real browser WebSocket close lifecycle cases. These reuse
//! the exact production adapter source in the existing DedicatedWorker harness.
//! Each socket is closed while CONNECTING, before an open task can run.
//! No product account/backend/inference or listening fixture is used.
#[path="../../openmates-rust/src/platform/browser_socket.rs"]
mod actual;
use futures_util::{future::poll_fn,Sink};
use std::{future::Future,pin::Pin,task::Poll};
use wasm_bindgen_test::*;
// browser_crypto_tests already configures this crate's DedicatedWorker runner.
fn original()->(actual::Stream,web_sys::WebSocket){
    let physical=web_sys::WebSocket::new("ws://127.0.0.1:65534/openmates-close-lifecycle").unwrap();
    let(stream,_opened)=actual::own_socket(physical.clone(),1024);(stream,physical)
}
async fn assert_actual_pending(future:Pin<&mut impl Future<Output=Result<(),tungstenite::Error>>>){
    let mut future=future;assert!(poll_fn(|cx|Poll::Ready(future.as_mut().poll(cx))).await.is_pending(),"submitting close must not acknowledge actual socket completion");
}
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.client.shared-rust-policy
#[wasm_bindgen_test(async)]
async fn actual_browser_close_waits_for_original_native_event_or_known_closed_state(){
    let(mut stream,physical)=original();assert_eq!(physical.ready_state(),web_sys::WebSocket::CONNECTING);
    let mut close=Box::pin(stream.close(None));assert_actual_pending(close.as_mut()).await;
    assert_ne!(physical.ready_state(),web_sys::WebSocket::CLOSED);close.await.unwrap();
    assert_eq!(physical.ready_state(),web_sys::WebSocket::CLOSED);
    // Repeated local close reads the SAME actual CLOSED state, with no rearm.
    stream.close(None).await.unwrap();
}
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,sync.client.shared-rust-policy
#[wasm_bindgen_test(async)]
async fn dropping_actual_browser_close_wait_keeps_original_completion_receiver_for_the_next_wait(){
    let(mut stream,physical)=original();let mut close=Box::pin(stream.close(None));assert_actual_pending(close.as_mut()).await;
    drop(close);
    // Drop only releases this borrow; the exact stream still owns its receiver.
    let mut resumed=Box::pin(stream.close(None));assert_actual_pending(resumed.as_mut()).await;resumed.await.unwrap();
    assert_eq!(physical.ready_state(),web_sys::WebSocket::CLOSED);
}
// contract-test: supporting surface=gui.web assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[wasm_bindgen_test(async)]
async fn synthetic_close_and_error_events_cannot_acknowledge_an_original_browser_socket_that_is_not_closed(){
    let(mut stream,physical)=original();
    physical.dispatch_event(&web_sys::CloseEvent::new("close").unwrap()).unwrap();
    physical.dispatch_event(&web_sys::Event::new("error").unwrap()).unwrap();
    assert_eq!(physical.ready_state(),web_sys::WebSocket::CONNECTING);
    // Queue/error callbacks have run, but the original native socket has not
    // closed. Sink close must remain pending after its real close submission.
    assert!(poll_fn(|cx|Poll::Ready(Pin::new(&mut stream).poll_close(cx))).await.is_pending());
    stream.close(None).await.unwrap();assert_eq!(physical.ready_state(),web_sys::WebSocket::CLOSED);
}
