//! Attribution of generic `error` frames on the live monitor socket: an error
//! answering a forwarded shell frame reaches the shell and keeps the socket
//! (also during a draft read); core errors stay fatal (loopback WebSocket peer).
use super::super::MonitorReadData;
use super::*;
use crate::client::monitor_test_peer::{live_monitor, request, send, signed_in_client};
use crate::client::owned_operation::OwnedOperationScope;
use crate::error::Error;
use crate::view_model::UnownedSocketItem;
use serde_json::json;
use tokio_util::sync::CancellationToken;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";

fn item(event_type: &str, payload: Value) -> UnownedSocketItem {
    UnownedSocketItem::Frame {
        event_type: event_type.into(),
        payload_json: payload.to_string(),
    }
}

#[test]
fn only_errors_after_a_shell_write_and_outside_a_phased_sync_shape_go_to_the_shell() {
    let changes = Arc::new(Changes::default());
    let plain = json!({"message":"Missing chatId for delete_draft"});
    let coded = json!({"code":"synthetic_code","chat_id":CHAT});
    // Nothing written by the shell: every error is the core's.
    assert!(!forward_shell_error(Some(&changes), None, &coded));
    changes.passthrough.note_shell_write();
    assert!(forward_shell_error(Some(&changes), None, &plain));
    let sync = MonitorReadRequest::RecentSync;
    assert!(!forward_shell_error(Some(&changes), Some(&sync), &plain));
    assert!(forward_shell_error(Some(&changes), Some(&sync), &coded));
    let drafts = MonitorReadRequest::DraftVersions(Vec::new());
    assert!(forward_shell_error(Some(&changes), Some(&drafts), &plain));
    assert!(!forward_shell_error(None, None, &plain));
}

#[tokio::test]
async fn error_answering_a_shell_frame_reaches_the_shell_and_keeps_the_socket() {
    let client = signed_in_client();
    let mut live = live_monitor(&client).await;
    let passthrough = live.monitor.socket_passthrough();
    let error = json!({"message":"Missing chatId for delete_draft"});
    let server = {
        let error = error.clone();
        let mut peer = live.peer;
        tokio::spawn(async move {
            assert_eq!(
                request(&mut peer).await.unwrap()["type"],
                "synthetic_shell_ping"
            );
            send(&mut peer, "error", error).await;
            // Still read after the error: the socket stayed up.
            send(&mut peer, "synthetic_shell_pong", json!({"n":1})).await;
            send(&mut peer, "force_logout", json!({})).await;
            while request(&mut peer).await.is_some() {}
        })
    };
    assert_eq!(passthrough.send("synthetic_shell_ping", "{}").await, Ok(()));
    assert_eq!(live.errors.recv().await, Some(Error::Expired));
    live.task.await.unwrap();
    server.await.unwrap();
    let frames = passthrough.attach().unwrap();
    assert_eq!(frames.recv().await, Some(item("error", error)));
    assert_eq!(
        frames.recv().await,
        Some(item("synthetic_shell_pong", json!({"n":1})))
    );
    assert_eq!(frames.recv().await, None);
}

#[tokio::test]
async fn error_without_a_shell_frame_still_retires_the_socket() {
    let client = signed_in_client();
    let mut live = live_monitor(&client).await;
    send(
        &mut live.peer,
        "error",
        json!({"message":"Synthetic failure"}),
    )
    .await;
    assert_eq!(live.errors.recv().await, Some(Error::Offline));
    live.task.await.unwrap();
    assert!(!live.monitor.is_valid());
    let frames = live.monitor.socket_passthrough().attach().unwrap();
    assert_eq!(frames.recv().await, None);
}

#[tokio::test]
async fn shell_error_during_a_draft_read_keeps_the_read_and_the_socket() {
    let client = signed_in_client();
    let mut live = live_monitor(&client).await;
    let passthrough = live.monitor.socket_passthrough();
    let original = OwnedOperationScope::capture(&client, CancellationToken::new()).unwrap();
    let ticket = client
        .prepare_monitor_read(
            &live.monitor,
            &original,
            MonitorReadRequest::DraftVersions(vec![(CHAT.into(), 1)]),
        )
        .unwrap();
    assert_eq!(
        request(&mut live.peer).await.unwrap()["type"],
        "get_draft_versions"
    );
    let shell = tokio::spawn({
        let passthrough = passthrough.clone();
        async move { passthrough.send("synthetic_shell_ping", "{}").await }
    });
    assert_eq!(
        request(&mut live.peer).await.unwrap()["type"],
        "synthetic_shell_ping"
    );
    send(
        &mut live.peer,
        "error",
        json!({"message":"Synthetic shell failure"}),
    )
    .await;
    send(
        &mut live.peer,
        "draft_versions_response",
        json!({"versions":{(CHAT):2},"tombstone_versions":{}}),
    )
    .await;
    let receipt = ticket.wait().await.unwrap();
    let MonitorReadData::DraftVersions(data) =
        receipt.take(&client, &live.monitor, &original).unwrap()
    else {
        panic!("wrong read data");
    };
    assert_eq!(data.versions[CHAT], 2);
    assert_eq!(shell.await.unwrap(), Ok(()));
    assert!(live.monitor.is_valid());
    live.monitor.close();
    live.task.await.unwrap();
    let frames = passthrough.attach().unwrap();
    assert_eq!(
        frames.recv().await,
        Some(item("error", json!({"message":"Synthetic shell failure"})))
    );
}

#[tokio::test]
async fn phased_sync_shaped_error_during_a_sync_read_stays_fatal_after_a_shell_frame() {
    let client = signed_in_client();
    let mut live = live_monitor(&client).await;
    let passthrough = live.monitor.socket_passthrough();
    send(
        &mut live.peer,
        "recovery_outputs_discovery_complete",
        json!({"status":"disabled"}),
    )
    .await;
    let original = OwnedOperationScope::capture(&client, CancellationToken::new()).unwrap();
    let ticket = client
        .prepare_monitor_read(&live.monitor, &original, MonitorReadRequest::RecentSync)
        .unwrap();
    assert_eq!(
        request(&mut live.peer).await.unwrap()["type"],
        "phased_sync_request"
    );
    let shell = tokio::spawn({
        let passthrough = passthrough.clone();
        async move { passthrough.send("synthetic_shell_ping", "{}").await }
    });
    assert_eq!(
        request(&mut live.peer).await.unwrap()["type"],
        "synthetic_shell_ping"
    );
    send(
        &mut live.peer,
        "error",
        json!({"message":"Failed to process phased sync request"}),
    )
    .await;
    assert_eq!(ticket.wait().await.err(), Some(Error::Protocol));
    assert_eq!(live.errors.recv().await, Some(Error::Protocol));
    live.task.await.unwrap();
    assert_eq!(shell.await.unwrap(), Ok(()));
    assert!(!live.monitor.is_valid());
}
