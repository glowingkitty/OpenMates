//! `Client::monitor_draft_versions` over the live monitor's loopback socket:
//! the server's versions and tombstones come back unchanged, chunked at 200
//! chats, on the one socket; an empty request writes no frame.
use super::*;
use crate::client::monitor_test_peer::{live_monitor, request, send, signed_in_client};

const FIRST: &str = "22222222-2222-4222-8222-222222222222";
const SECOND: &str = "33333333-3333-4333-8333-333333333333";

#[tokio::test]
async fn returns_server_versions_and_tombstones_on_the_monitor_socket() {
    let mut client = signed_in_client();
    let live = live_monitor(&client).await;
    let server = {
        let mut peer = live.peer;
        tokio::spawn(async move {
            let asked = request(&mut peer).await.unwrap();
            assert_eq!(
                asked,
                json!({"type":"get_draft_versions","payload":{"chats":[
                    {"chat_id":FIRST,"client_draft_v":1},{"chat_id":SECOND,"client_draft_v":3}]}})
            );
            send(
                &mut peer,
                "draft_versions_response",
                json!({"versions":{(FIRST):4,(SECOND):0},"tombstone_versions":{(SECOND):5}}),
            )
            .await;
            peer
        })
    };
    let requested = vec![(FIRST.to_owned(), 1), (SECOND.to_owned(), 3)];
    let read = client
        .monitor_draft_versions(&live.monitor, requested, CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(
        read.versions,
        BTreeMap::from([(FIRST.to_owned(), 4), (SECOND.to_owned(), 0)])
    );
    assert_eq!(read.tombstones, BTreeMap::from([(SECOND.to_owned(), 5)]));
    assert!(live.monitor.is_valid());
    let _peer = server.await.unwrap();
    live.monitor.close();
    live.task.await.unwrap();
}

#[tokio::test]
async fn more_than_200_chats_are_asked_in_chunks() {
    let mut client = signed_in_client();
    let live = live_monitor(&client).await;
    let ids: Vec<String> = (0..201)
        .map(|n| format!("44444444-4444-4444-8444-{n:012}"))
        .collect();
    let server = {
        let mut peer = live.peer;
        let ids = ids.clone();
        tokio::spawn(async move {
            for chunk in ids.chunks(200) {
                let asked = request(&mut peer).await.unwrap();
                assert_eq!(
                    asked["payload"]["chats"].as_array().unwrap().len(),
                    chunk.len()
                );
                let versions: serde_json::Map<String, Value> =
                    chunk.iter().map(|id| (id.clone(), json!(1))).collect();
                send(
                    &mut peer,
                    "draft_versions_response",
                    json!({"versions":versions}),
                )
                .await;
            }
            peer
        })
    };
    let requested = ids.iter().map(|id| (id.clone(), 1)).collect();
    let read = client
        .monitor_draft_versions(&live.monitor, requested, CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(read.versions.len(), 201);
    assert!(read.tombstones.is_empty());
    let _peer = server.await.unwrap();
    live.monitor.close();
    live.task.await.unwrap();
}

#[tokio::test]
async fn an_empty_request_answers_without_a_frame() {
    let mut client = signed_in_client();
    let mut live = live_monitor(&client).await;
    let read = client
        .monitor_draft_versions(&live.monitor, Vec::new(), CancellationToken::new())
        .await
        .unwrap();
    assert!(read.versions.is_empty() && read.tombstones.is_empty());
    live.monitor.close();
    live.task.await.unwrap();
    assert_eq!(request(&mut live.peer).await, None);
}
