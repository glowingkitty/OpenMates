//! Message actions over a loopback session route and socket: delete-message and cancel-task frames, their acknowledgements, error frames, refusals before any network and the edit truncation plan.
use super::*;
use crate::client::workspaces::delete_tests::client;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const ID: &str = "11111111-1111-4111-8111-111111111111";

/// A loopback API: one session admission, then one socket that records every
/// frame of type `operation` and answers each with the next `answers` entry
/// (its `{id}` replaced by the request's id field `id_field`).
async fn peer(
    operation: &'static str,
    id_field: &'static str,
    answers: Vec<Value>,
) -> (String, tokio::task::JoinHandle<Vec<Value>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = vec![];
        let mut chunk = [0; 4096];
        let end = loop {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                break end + 4;
            }
        };
        let header = String::from_utf8(bytes[..end].to_vec()).unwrap();
        assert!(header.starts_with("POST /v1/auth/session "));
        let length = header
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(|v| v.trim().parse::<usize>().unwrap())
            })
            .unwrap();
        while bytes.len() < end + length {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
        }
        let body =
            json!({"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nSet-Cookie: auth_refresh_token=rotated; HttpOnly\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        drop(stream);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut seen = vec![];
        let mut answers = answers.into_iter();
        while let Some(Ok(frame)) = ws.next().await {
            let Ok(text) = frame.to_text() else { break };
            let Ok(frame) = serde_json::from_str::<Value>(text) else {
                break;
            };
            if frame["type"] != operation {
                continue;
            }
            let id = frame["payload"][id_field]
                .as_str()
                .unwrap_or_default()
                .to_owned();
            seen.push(frame["payload"].clone());
            // Without an answer left the socket stays open and silent.
            if let Some(answer) = answers.next() {
                let answer = answer.to_string().replace("{id}", &id);
                ws.send(Frame::Text(answer.into())).await.unwrap();
            }
        }
        let _ = ws.close(None).await;
        seen
    });
    (api, server)
}

fn deleted() -> Value {
    json!({"type":"message_deleted","payload":{"chat_id":ID,"message_id":"{id}"}})
}

async fn bounded<T>(work: impl std::future::Future<Output = T>) -> T {
    tokio::time::timeout(Duration::from_secs(5), work)
        .await
        .unwrap()
}

#[tokio::test]
async fn delete_message_sends_the_web_frame_and_drops_loaded_history_on_acknowledgement() {
    let (api, server) = peer("delete_message", "messageId", vec![deleted()]).await;
    let mut client = client(&api, false, false);
    bounded(client.delete_message(ID, "opaque-message"))
        .await
        .unwrap();
    assert!(!client.history.contains_key(ID));
    assert!(client.chats.contains_key(ID), "the chat row stays");
    drop(client);
    let seen = server.await.unwrap();
    assert_eq!(seen, [json!({"chatId": ID, "messageId": "opaque-message"})]);
}

#[tokio::test]
async fn delete_messages_uses_one_socket_in_order() {
    let (api, server) = peer("delete_message", "messageId", vec![deleted(), deleted()]).await;
    let mut client = client(&api, false, false);
    let ids = ["first".to_owned(), "second".to_owned()];
    bounded(client.delete_messages(ID, &ids)).await.unwrap();
    drop(client);
    let seen = server.await.unwrap();
    let order: Vec<_> = seen.iter().map(|p| p["messageId"].clone()).collect();
    assert_eq!(order, [json!("first"), json!("second")]);
}

#[tokio::test]
async fn delete_message_error_frame_is_a_protocol_error_and_stops_later_deletes() {
    let error = json!({"type":"error","payload":{"message":"synthetic refusal"}});
    let (api, server) = peer("delete_message", "messageId", vec![error]).await;
    let mut client = client(&api, false, false);
    let ids = ["first".to_owned(), "second".to_owned()];
    let result = bounded(client.delete_messages(ID, &ids)).await;
    assert!(matches!(result, Err(Error::Protocol)), "{result:?}");
    // The server history may have changed: nothing stale is kept.
    assert!(!client.history.contains_key(ID));
    drop(client);
    assert_eq!(server.await.unwrap().len(), 1);
}

#[tokio::test]
async fn message_actions_refuse_before_any_network() {
    // Port 1 never answers: every case below must fail before connecting.
    let mut personal = client("http://127.0.0.1:1", false, false);
    assert!(matches!(
        personal.delete_message("not-a-uuid", "m").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        personal.delete_message(ID, "").await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        personal.cancel_ai_task(ID, "").await,
        Err(Error::Invalid(_))
    ));
    let mut team = client("http://127.0.0.1:1", true, false);
    assert!(matches!(
        team.delete_message(ID, "m").await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        team.truncate_for_edit(ID, "m").await,
        Err(Error::Forbidden)
    ));
}

#[tokio::test]
async fn cancel_ai_task_sends_task_and_chat_and_waits_for_the_revocation_ack() {
    let ack = json!({"type":"ai_task_cancel_requested","payload":{"task_id":"{id}","status":"revocation_sent"}});
    let (api, server) = peer("cancel_ai_task", "task_id", vec![ack]).await;
    let mut client = client(&api, false, false);
    bounded(client.cancel_ai_task(ID, "synthetic-task"))
        .await
        .unwrap();
    drop(client);
    let seen = server.await.unwrap();
    assert_eq!(seen, [json!({"task_id": "synthetic-task", "chat_id": ID})]);
}

#[tokio::test]
async fn cancelled_operation_token_ends_a_waiting_cancel_with_cancelled() {
    // The peer records the frame but never answers.
    let (api, server) = peer("cancel_ai_task", "task_id", vec![]).await;
    let mut client = client(&api, false, false);
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    let canceller = tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(300)).await;
        cancel.cancel();
    });
    let result = bounded(client.cancel_ai_task(ID, "synthetic-task")).await;
    assert!(matches!(result, Err(Error::Cancelled)), "{result:?}");
    canceller.await.unwrap();
    drop(client);
    server.await.unwrap();
}

fn rewrite_state(roles: &[&str]) -> ChatRewriteState {
    let key = [3; 32];
    let row = json!({"id": ID, "messages_v": roles.len(),
        "encrypted_chat_key": "opaque-wrapper",
        "encrypted_title": crypto::encrypt_combined("Synthetic", &key).unwrap()});
    let rows: Vec<Value> = roles
        .iter()
        .enumerate()
        .map(|(i, role)| {
            json!({"id": format!("row-{i}"), "message_id": format!("server-{i}"),
                "client_message_id": format!("client-{i}"), "chat_id": ID, "role": role,
                "created_at": i + 1,
                "encrypted_content": crypto::encrypt_combined("synthetic", &key).unwrap()})
        })
        .collect();
    ChatRewriteState::from_encrypted_rows(ID, &row, &rows, &key).unwrap()
}

#[test]
fn editing_a_later_user_message_rewinds_to_the_message_before_it() {
    let state = rewrite_state(&["user", "assistant", "user", "assistant"]);
    assert_eq!(
        edit_truncation(&state, "server-2").unwrap(),
        EditTruncation::Rewind(1)
    );
}

#[test]
fn editing_the_first_message_deletes_every_message() {
    let state = rewrite_state(&["user", "assistant"]);
    assert_eq!(
        edit_truncation(&state, "server-0").unwrap(),
        EditTruncation::DeleteAll(vec!["server-0".into(), "server-1".into()])
    );
}

#[test]
fn editing_refuses_assistant_and_unknown_messages() {
    let state = rewrite_state(&["user", "assistant"]);
    assert!(matches!(
        edit_truncation(&state, "server-1"),
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        edit_truncation(&state, "missing"),
        Err(Error::Invalid(_))
    ));
}
