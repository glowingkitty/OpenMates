//! The view-model draft versions call: a round trip on the installed
//! monitor's loopback socket with no second connection, and `Offline`
//! without a monitor.
use super::{
    DraftVersionQuery, ServerDraftVersion,
    actor_tests::{API, CHAT, OWNER, fixture, session},
    draft_versions,
};
use crate::client::monitor_test_peer::{live_monitor, request, send};
use crate::error::Error;
use serde_json::json;
use tokio_util::sync::CancellationToken;

const OTHER: &str = "33333333-3333-4333-8333-333333333333";

#[tokio::test]
async fn round_trip_on_the_monitor_socket_returns_what_the_server_sent() {
    let mut f = fixture();
    let core = &mut f.host.core;
    core.client_mut().reset(API, Some(session())).unwrap();
    core.client_mut().adopt_test_principal(OWNER).unwrap();
    let live = live_monitor(core.client()).await;
    core.set_chat_monitor(Some(live.monitor));
    let server = {
        let mut peer = live.peer;
        tokio::spawn(async move {
            let asked = request(&mut peer).await.unwrap();
            assert_eq!(asked["type"], "get_draft_versions");
            send(
                &mut peer,
                "draft_versions_response",
                json!({"versions":{(CHAT):0,(OTHER):6},"tombstone_versions":{(CHAT):3}}),
            )
            .await;
            // The same socket is still open afterwards: nothing else is
            // sent until the monitor retires it.
            assert_eq!(request(&mut peer).await, None);
        })
    };
    let chats = vec![
        DraftVersionQuery {
            chat_id: CHAT.into(),
            client_draft_v: 2,
        },
        DraftVersionQuery {
            chat_id: OTHER.into(),
            client_draft_v: 5,
        },
    ];
    let versions = draft_versions(&mut f.host, chats, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(
        versions,
        [
            ServerDraftVersion {
                chat_id: CHAT.into(),
                server_draft_v: 0,
                tombstone_v: Some(3)
            },
            ServerDraftVersion {
                chat_id: OTHER.into(),
                server_draft_v: 6,
                tombstone_v: None
            },
        ]
    );
    assert!(
        f.host
            .core
            .chat_monitor()
            .is_some_and(|monitor| monitor.is_valid())
    );
    f.host.core.set_chat_monitor(None);
    live.task.await.unwrap();
    server.await.unwrap();
}

#[tokio::test]
async fn without_a_monitor_the_call_is_offline() {
    let mut f = fixture();
    let chats = vec![DraftVersionQuery {
        chat_id: CHAT.into(),
        client_draft_v: 1,
    }];
    let result = draft_versions(&mut f.host, chats, &CancellationToken::new()).await;
    assert_eq!(result.err(), Some(Error::Offline));
}
