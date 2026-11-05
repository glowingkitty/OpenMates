use super::*;
use crate::client::persistence::receipt_test_peer as peer;

#[tokio::test]
async fn sealed_embed_and_diff_stores_require_their_canonical_echoed_artifact_id() {
    for (kind, response) in [
        ("store_embed", "store_embed_confirmed"),
        ("store_embed_diff", "store_embed_diff_confirmed"),
    ] {
        for valid in [true, false] {
            let (mut ws, peer) = peer::once(move |request| {
                assert_eq!(request["type"], kind);
                assert_eq!(request["payload"]["recovery_record_id"], "record");
                assert_eq!(request["payload"]["embed_id"], "embed");
                let mut payload = json!({"request_id":request["payload"]["request_id"],"canonical_digest":"digest"});
                if valid { payload["embed_id"] = json!("embed"); }
                vec![json!({"type":response,"payload":payload})]
            })
            .await;
            let receipt = store_output(
                &mut ws,
                kind,
                response,
                &json!({"record_id":"record"}),
                json!({"embed_id":"embed"}),
            )
            .await;
            if valid {
                assert_eq!(receipt.unwrap()["canonical_digest"], "digest");
            } else {
                assert!(matches!(receipt, Err(Error::Protocol)));
            }
            peer.await.unwrap();
        }
    }
}

#[tokio::test]
async fn sealed_key_wrapper_receipt_does_not_require_an_unpromised_embed_id() {
    let (mut ws, peer) = peer::once(|request| {
        assert_eq!(request["type"], "store_embed_keys");
        vec![json!({"type":"store_embed_keys_confirmed","payload":{
            "request_id":request["payload"]["request_id"],"created_count":2,"failed_count":0,"requested_count":2
        }})]
    })
    .await;
    let receipt = store_output(
        &mut ws,
        "store_embed_keys",
        "store_embed_keys_confirmed",
        &json!({"record_id":"record"}),
        json!({"keys":[]}),
    )
    .await
    .unwrap();
    assert_eq!(receipt["created_count"], 2);
    assert!(receipt.get("embed_id").is_none());
    peer.await.unwrap();
}
