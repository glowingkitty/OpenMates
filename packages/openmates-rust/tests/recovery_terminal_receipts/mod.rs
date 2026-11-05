use super::*;
use crate::client::persistence::receipt_test_peer as peer;

async fn receipt(payload: Value) -> Result<()> {
    let (mut ws, peer) = peer::once(move |request| {
        assert_eq!(request["type"], "recovery_job_persist");
        assert_eq!(request["payload"]["job_id"], "job");
        vec![json!({"type":"recovery_job_persisted","payload":payload})]
    })
    .await;
    send(&mut ws, "recovery_job_persist", json!({"job_id":"job"})).await?;
    let result = wait_terminal_persisted(&mut ws, "job").await;
    peer.await.unwrap();
    result
}

#[tokio::test]
async fn canonical_new_and_idempotent_terminal_receipts_accept_optional_version() {
    for payload in [
        json!({"job_id":"job","state":"TERMINAL","idempotent":false,"committed_messages_v":4}),
        json!({"job_id":"job","state":"TERMINAL","idempotent":true,"committed_messages_v":4}),
        json!({"job_id":"job","state":"TERMINAL","idempotent":true}),
    ] {
        assert!(receipt(payload).await.is_ok());
    }
}

#[tokio::test]
async fn missing_null_wrong_type_and_nonterminal_state_never_confirm_persistence() {
    for payload in [
        json!({"job_id":"job"}),
        json!({"job_id":"job","state":null}),
        json!({"job_id":"job","state":true}),
        json!({"job_id":"job","state":"LEASED"}),
        json!({"job_id":"job","state":"terminal"}),
    ] {
        assert!(matches!(receipt(payload).await, Err(Error::Protocol)));
    }
}

#[tokio::test]
async fn foreign_job_receipt_cannot_replace_matching_terminal_ack() {
    let (mut ws, peer) = peer::once(|_| {
        vec![
            json!({"type":"recovery_job_persisted","payload":{"job_id":"foreign","state":"LEASED"}}),
            json!({"type":"recovery_job_persisted","payload":{"job_id":"job","state":"TERMINAL"}}),
        ]
    })
    .await;
    send(&mut ws, "recovery_job_persist", json!({"job_id":"job"}))
        .await
        .unwrap();
    assert!(wait_terminal_persisted(&mut ws, "job").await.is_ok());
    peer.await.unwrap();
}
