//! Queued follow-up revision over a loopback socket: the frame shape with the chat-key ciphertext, the typed receipt, stale-revision and other rejections, and refusals before any network.
use super::super::message_actions::tests::{bounded, peer};
use super::*;
use crate::client::workspaces::delete_tests::client;

const ID: &str = "11111111-1111-4111-8111-111111111111";
const KEY: [u8; 32] = [8; 32];

fn keyed(api: &str, team: bool) -> Client {
    let mut c = client(api, team, false);
    c.chats.insert(
        ID.into(),
        json!({"id":ID,"messages_v":1,"chat_visibility":"private",
            "encrypted_chat_key":crypto::encrypt_bytes(&KEY, &[7; 32]).unwrap()}),
    );
    c.history.insert(ID.into(), vec![]);
    c
}

fn updated(mode: &str, revision: u64) -> Value {
    json!({"type":"queued_message_updated","payload":{"chat_id":ID,"message_id":"queued-1",
        "client_request_id":"{id}","queue_mode":mode,"queue_revision":revision}})
}

fn rejected(reason: &str) -> Value {
    json!({"type":"queued_message_revision_rejected","payload":{"chat_id":ID,
        "message_id":"queued-1","client_request_id":"{id}","reason_code":reason,"current_revision":5}})
}

#[test]
fn payload_carries_ids_revision_mode_and_encrypted_text() {
    let text = revision_payload(
        ID,
        "m",
        2,
        "r",
        Some(QueuedRevisionMode::Steer),
        Some(("hi", "ct", None)),
    );
    assert_eq!(
        text,
        json!({"chat_id":ID,"message_id":"m","expected_revision":2,"client_request_id":"r",
            "queue_mode":"steer","content":"hi","encrypted_content":"ct","encrypted_pii_mappings":null})
    );
    let mode_only = revision_payload(ID, "m", 2, "r", Some(QueuedRevisionMode::FollowUp), None);
    assert!(mode_only.get("content").is_none() && mode_only.get("encrypted_content").is_none());
    assert_eq!(mode_only["queue_mode"], "follow_up");
}

#[tokio::test]
async fn text_revision_sends_chat_key_ciphertext_and_returns_the_receipt() {
    let (api, server) = peer(
        "revise_queued_message",
        "client_request_id",
        vec![updated("follow_up", 3)],
    )
    .await;
    let mut c = keyed(&api, false);
    let receipt = bounded(c.revise_queued_message(
        ID,
        "queued-1",
        2,
        None,
        Some("Better words"),
        SendOptions {
            pii_detection: false,
            ..Default::default()
        },
    ))
    .await
    .unwrap();
    assert_eq!(receipt.queue_revision, 3);
    assert_eq!(receipt.queue_mode, QueuedRevisionMode::FollowUp);
    drop(c);
    let seen = server.await.unwrap();
    assert_eq!(seen.len(), 1);
    let frame = &seen[0];
    assert_eq!(frame["message_id"], "queued-1");
    assert_eq!(frame["expected_revision"], 2);
    assert_eq!(frame["content"], "Better words");
    assert!(frame.get("queue_mode").is_none());
    assert!(frame["encrypted_pii_mappings"].is_null());
    let plain =
        crypto::decrypt_combined(frame["encrypted_content"].as_str().unwrap(), &KEY).unwrap();
    assert_eq!(plain, "Better words");
}

#[tokio::test]
async fn steering_without_text_sends_only_the_mode() {
    let (api, server) = peer(
        "revise_queued_message",
        "client_request_id",
        vec![updated("steer", 4)],
    )
    .await;
    let mut c = keyed(&api, false);
    let receipt = bounded(c.revise_queued_message(
        ID,
        "queued-1",
        3,
        Some(QueuedRevisionMode::Steer),
        None,
        SendOptions::default(),
    ))
    .await
    .unwrap();
    assert_eq!(
        (receipt.queue_mode, receipt.queue_revision),
        (QueuedRevisionMode::Steer, 4)
    );
    drop(c);
    let seen = server.await.unwrap();
    assert_eq!(seen[0]["queue_mode"], "steer");
    assert!(seen[0].get("content").is_none());
}

#[tokio::test]
async fn rejections_become_typed_errors() {
    for (reason, check) in [
        (
            "conflict",
            (|e: &Error| matches!(e, Error::Conflict)) as fn(&Error) -> bool,
        ),
        ("forbidden", |e| matches!(e, Error::Forbidden)),
        ("invalid_request", |e| matches!(e, Error::Invalid(_))),
        ("not_queued", |e| {
            matches!(
                e,
                Error::Unavailable {
                    code: "queued_revision",
                    reason: "not_queued"
                }
            )
        }),
    ] {
        let (api, server) = peer(
            "revise_queued_message",
            "client_request_id",
            vec![rejected(reason)],
        )
        .await;
        let mut c = keyed(&api, false);
        let error = bounded(c.revise_queued_message(
            ID,
            "queued-1",
            2,
            Some(QueuedRevisionMode::Steer),
            None,
            SendOptions::default(),
        ))
        .await
        .unwrap_err();
        assert!(check(&error), "{reason}: {error:?}");
        drop(c);
        server.await.unwrap();
    }
}

#[test]
fn a_foreign_or_wrong_revision_answer_is_a_protocol_error() {
    let ok = updated("steer", 3);
    assert!(parse_answer("queued_message_updated", &ok, ID, "queued-1", 2).is_ok());
    assert!(matches!(
        parse_answer("queued_message_updated", &ok, ID, "other", 2),
        Err(Error::Protocol)
    ));
    assert!(matches!(
        parse_answer("queued_message_updated", &ok, ID, "queued-1", 5),
        Err(Error::Protocol)
    ));
}

#[tokio::test]
async fn revisions_refuse_before_any_network() {
    let mut c = keyed("http://127.0.0.1:1", false);
    let none = SendOptions::default();
    let steer = Some(QueuedRevisionMode::Steer);
    for result in [
        c.revise_queued_message("bad", "m", 1, steer, None, none.clone())
            .await,
        c.revise_queued_message(ID, "", 1, steer, None, none.clone())
            .await,
        c.revise_queued_message(ID, "m", 0, steer, None, none.clone())
            .await,
        c.revise_queued_message(ID, "m", 1, None, None, none.clone())
            .await,
        c.revise_queued_message(ID, "m", 1, None, Some("   "), none.clone())
            .await,
    ] {
        assert!(matches!(result, Err(Error::Invalid(_))), "{result:?}");
    }
    let mut team = keyed("http://127.0.0.1:1", true);
    assert!(matches!(
        team.revise_queued_message(ID, "m", 1, steer, None, none)
            .await,
        Err(Error::Forbidden)
    ));
}
