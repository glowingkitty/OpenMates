//! Pure local ownership/serialization tests; no provider or network calls.
use super::*;
use futures_util::Sink;
use std::{
    pin::Pin,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    task::{Context, Poll},
};

fn source() -> (PlaintextJson, Arc<AtomicBool>) {
    let probe = Arc::new(AtomicBool::new(false));
    let mut source = PlaintextJson::new(json!({
        "text":"private \n Unicode 🦀", "nested":[{"secret-key":"value"}], "count":3
    }));
    source.drop_probe = Some(probe.clone());
    (source, probe)
}

#[test]
fn guarded_http_request_matches_existing_json_bytes_and_content_type() {
    let client = reqwest::Client::new();
    let (source, probe) = source();
    let expected = client
        .post("https://api.example.com/v1/context/select")
        .json(&source.value)
        .build()
        .unwrap();
    let actual = plaintext_request(
        client
            .post("https://api.example.com/v1/context/select")
            .header("Origin", "https://app.example.com")
            .header("X-OpenMates-Expected-Principal", "owner")
            .header("Cookie", "auth_refresh_token=retained"),
        source,
    )
    .unwrap()
    .build()
    .unwrap();
    assert_eq!(
        actual.body().unwrap().as_bytes(),
        expected.body().unwrap().as_bytes()
    );
    assert_eq!(
        actual.headers()["Content-Type"],
        expected.headers()["Content-Type"]
    );
    assert_eq!(actual.headers()["Origin"], "https://app.example.com");
    assert_eq!(actual.headers()["X-OpenMates-Expected-Principal"], "owner");
    assert_eq!(actual.headers()["Cookie"], "auth_refresh_token=retained");
    assert_eq!(actual.url().path(), "/v1/context/select");
    assert!(!probe.load(Ordering::SeqCst));
    let cloned = actual.try_clone().unwrap();
    drop(actual);
    assert!(
        !probe.load(Ordering::SeqCst),
        "request clone still owns the buffer"
    );
    drop(cloned);
    assert!(
        probe.load(Ordering::SeqCst),
        "last request body drop wipes JSON"
    );
}

#[test]
fn unpolled_http_send_and_invalid_builder_drop_guarded_body() {
    let client = reqwest::Client::new();
    let (source, probe) = source();
    let request = plaintext_request(
        client.post("https://api.example.com/v1/context/select"),
        source,
    )
    .unwrap();
    drop(request.send());
    assert!(
        probe.load(Ordering::SeqCst),
        "unpolled send drops request body"
    );
    let (source, probe) = self::source();
    let request = plaintext_request(
        client
            .post("https://api.example.com/v1/context/select")
            .header("Cookie", "invalid\nheader"),
        source,
    )
    .unwrap();
    assert!(request.build().is_err());
    assert!(
        probe.load(Ordering::SeqCst),
        "failed builder drops request body"
    );
}

#[test]
fn guarded_bytes_and_nested_json_wipe_on_last_owner_drop() {
    let (source, source_probe) = source();
    let mut serialized = PlaintextBytes::serialize(&source.value).unwrap();
    let size = serialized.bytes.len();
    let bytes_probe = Arc::new(Mutex::new(Vec::new()));
    serialized.drop_probe = Some(bytes_probe.clone());
    let bytes = serialized.owned(source);
    let clone = bytes.clone();
    drop(bytes);
    assert!(!source_probe.load(Ordering::SeqCst));
    assert!(bytes_probe.lock().unwrap().is_empty());
    drop(clone);
    assert!(source_probe.load(Ordering::SeqCst));
    assert_eq!(*bytes_probe.lock().unwrap(), vec![0; size]);
}

#[derive(Default)]
struct RecordingSink {
    message: Option<tungstenite::Message>,
    pending_ready: bool,
    pending_flush: bool,
    fail_ready: bool,
}
impl Sink<tungstenite::Message> for RecordingSink {
    type Error = tungstenite::Error;
    fn poll_ready(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<std::result::Result<(), Self::Error>> {
        if self.fail_ready {
            Poll::Ready(Err(tungstenite::Error::ConnectionClosed))
        } else if self.pending_ready {
            Poll::Pending
        } else {
            Poll::Ready(Ok(()))
        }
    }
    fn start_send(
        mut self: Pin<&mut Self>,
        message: tungstenite::Message,
    ) -> std::result::Result<(), Self::Error> {
        self.message = Some(message);
        Ok(())
    }
    fn poll_flush(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<std::result::Result<(), Self::Error>> {
        if self.pending_flush {
            Poll::Pending
        } else {
            Poll::Ready(Ok(()))
        }
    }
    fn poll_close(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<std::result::Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }
}

#[tokio::test]
async fn guarded_websocket_matches_existing_text_envelope_exactly() {
    let mut sink = RecordingSink::default();
    let (source, probe) = source();
    let expected = json!({"type":"chat_turn_admit","payload":source.value}).to_string();
    send_plaintext_message(&mut sink, "chat_turn_admit", source)
        .await
        .unwrap();
    assert_eq!(sink.message.as_ref().unwrap().to_text().unwrap(), expected);
    assert!(!probe.load(Ordering::SeqCst));
    drop(sink);
    assert!(probe.load(Ordering::SeqCst));
}

#[test]
fn unpolled_and_aborted_websocket_futures_wipe_before_transport_handoff() {
    use std::future::Future;
    let mut sink = RecordingSink {
        pending_ready: true,
        ..Default::default()
    };
    let (source, probe) = source();
    drop(send_plaintext_message(&mut sink, "chat_turn_admit", source));
    assert!(probe.load(Ordering::SeqCst));
    let (source, probe) = self::source();
    let mut future = Box::pin(send_plaintext_message(&mut sink, "chat_turn_admit", source));
    let waker = futures_util::task::noop_waker();
    let mut cx = Context::from_waker(&waker);
    assert!(future.as_mut().poll(&mut cx).is_pending());
    drop(future);
    assert!(probe.load(Ordering::SeqCst));
    assert!(sink.message.is_none());
}

#[test]
fn aborted_websocket_future_preserves_guard_on_transport_owned_frame_until_drop() {
    use std::future::Future;
    let mut sink = RecordingSink {
        pending_flush: true,
        ..Default::default()
    };
    let (source, probe) = source();
    let mut future = Box::pin(send_plaintext_message(&mut sink, "chat_turn_admit", source));
    let waker = futures_util::task::noop_waker();
    let mut cx = Context::from_waker(&waker);
    assert!(future.as_mut().poll(&mut cx).is_pending());
    drop(future);
    assert!(!probe.load(Ordering::SeqCst), "sink owns an unsent frame");
    drop(sink);
    assert!(probe.load(Ordering::SeqCst));
}

#[tokio::test]
async fn websocket_error_wipes_guarded_source_and_serialized_owner() {
    let mut sink = RecordingSink {
        fail_ready: true,
        ..Default::default()
    };
    let (source, probe) = source();
    assert!(matches!(
        send_plaintext_message(&mut sink, "chat_turn_admit", source).await,
        Err(Error::Offline)
    ));
    assert!(probe.load(Ordering::SeqCst));
}

#[test]
fn unpolled_and_preflight_rejected_http_futures_wipe_guarded_value() {
    use std::future::Future;
    let mut client = Client::new("https://api.example.com", None).unwrap();
    let (source, probe) = source();
    drop(client.request_task_headers_inner(
        Method::POST,
        "/v1/context/select",
        Some(RequestBody::Plaintext(source)),
        None,
        None,
        None,
        None,
        false,
        None,
        None,
    ));
    assert!(probe.load(Ordering::SeqCst));
    let (source, probe) = self::source();
    client.operation_cancel.cancel();
    let mut future = Box::pin(client.request_task_headers_inner(
        Method::POST,
        "/v1/context/select",
        Some(RequestBody::Plaintext(source)),
        None,
        None,
        None,
        None,
        false,
        None,
        None,
    ));
    let waker = futures_util::task::noop_waker();
    let mut cx = Context::from_waker(&waker);
    assert!(matches!(
        future.as_mut().poll(&mut cx),
        Poll::Ready(Err(Error::Cancelled))
    ));
    drop(future);
    assert!(probe.load(Ordering::SeqCst));
}

#[test]
fn serialization_partial_failure_uses_guarded_fixed_allocation() {
    use serde::ser::{Error as _, SerializeSeq};
    use std::cell::Cell;
    struct FailsOnSecondPass(Cell<usize>);
    impl serde::Serialize for FailsOnSecondPass {
        fn serialize<S: serde::Serializer>(
            &self,
            serializer: S,
        ) -> std::result::Result<S::Ok, S::Error> {
            self.0.set(self.0.get() + 1);
            let mut seq = serializer.serialize_seq(Some(1))?;
            seq.serialize_element("private")?;
            if self.0.get() == 2 {
                return Err(S::Error::custom("test failure"));
            }
            seq.end()
        }
    }
    assert!(matches!(
        PlaintextBytes::serialize(&FailsOnSecondPass(Cell::new(0))),
        Err(Error::Protocol)
    ));
    let probe = Arc::new(Mutex::new(Vec::new()));
    let serialized = PlaintextBytes {
        bytes: zeroize::Zeroizing::new(vec![0; 64]),
        drop_probe: Some(probe.clone()),
    };
    assert!(matches!(
        serialized.write(&FailsOnSecondPass(Cell::new(1))),
        Err(Error::Protocol)
    ));
    assert_eq!(*probe.lock().unwrap(), vec![0; 64]);
}
