use super::receipt_test_peer as peer;
use super::*;

#[tokio::test]
async fn canonical_embed_receipt_keeps_digest_and_source_for_caller_validation() {
    let (mut ws, peer) = peer::once(|request| {
        assert_eq!(request["type"], "store_embed");
        vec![json!({"type":"store_embed_confirmed","payload":{
            "request_id":"request","embed_id":"embed","canonical_source":"head","canonical_digest":"ciphertext-digest"
        }})]
    })
    .await;
    send(
        &mut ws,
        "store_embed",
        json!({"request_id":"request","embed_id":"embed"}),
    )
    .await
    .unwrap();
    let receipt = wait_embed_receipt(&mut ws, "store_embed_confirmed", "request", "embed")
        .await
        .unwrap();
    assert_eq!(receipt["canonical_source"], "head");
    assert_eq!(receipt["canonical_digest"], "ciphertext-digest");
    peer.await.unwrap();
}

#[tokio::test]
async fn matching_request_with_missing_null_or_foreign_embed_is_rejected() {
    for payload in [
        json!({"request_id":"request"}),
        json!({"request_id":"request","embed_id":null}),
        json!({"request_id":"request","embed_id":"foreign"}),
    ] {
        let (mut ws, peer) =
            peer::once(move |_| vec![json!({"type":"store_embed_confirmed","payload":payload})])
                .await;
        send(
            &mut ws,
            "store_embed",
            json!({"request_id":"request","embed_id":"embed"}),
        )
        .await
        .unwrap();
        assert!(matches!(
            wait_embed_receipt(&mut ws, "store_embed_confirmed", "request", "embed").await,
            Err(Error::Protocol)
        ));
        peer.await.unwrap();
    }
}

#[tokio::test]
async fn wrong_request_is_ignored_until_the_matching_artifact_receipt() {
    let (mut ws, peer) = peer::once(|_| {
        vec![
            json!({"type":"store_embed_confirmed","payload":{"request_id":"other","embed_id":"foreign"}}),
            json!({"type":"store_embed_confirmed","payload":{"request_id":"request","embed_id":"embed"}}),
        ]
    })
    .await;
    send(
        &mut ws,
        "store_embed",
        json!({"request_id":"request","embed_id":"embed"}),
    )
    .await
    .unwrap();
    assert!(
        wait_embed_receipt(&mut ws, "store_embed_confirmed", "request", "embed")
            .await
            .is_ok()
    );
    peer.await.unwrap();
}

#[tokio::test]
async fn streamed_diff_receipt_fences_embed_and_preserves_version_row_receipt() {
    for valid in [true, false] {
        let (mut ws, peer) = peer::once(move |request| {
            assert_eq!(request["type"], "store_embed_diff");
            vec![json!({"type":"store_embed_diff_confirmed","payload":{
                "request_id":"request","embed_id":if valid {"embed"} else {"foreign"},
                "version_number":1,"canonical_source":"version_row","canonical_digest":"snapshot-digest"
            }})]
        })
        .await;
        send(
            &mut ws,
            "store_embed_diff",
            json!({"request_id":"request","embed_id":"embed","version_number":1}),
        )
        .await
        .unwrap();
        let receipt =
            wait_embed_receipt(&mut ws, "store_embed_diff_confirmed", "request", "embed").await;
        if valid {
            let receipt = receipt.unwrap();
            assert_eq!(receipt["canonical_source"], "version_row");
            assert_eq!(receipt["canonical_digest"], "snapshot-digest");
            assert_eq!(receipt["version_number"], 1);
        } else {
            assert!(matches!(receipt, Err(Error::Protocol)));
        }
        peer.await.unwrap();
    }
}
