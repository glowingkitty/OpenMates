//! Signed-out guest sessions (`EmbedWriteSession::local_only`): no master key,
//! so they refuse master-wrapped keys and server payloads and complete only
//! local-only embeds (`billing.anonymous.local-only-content`).
use super::payload::StreamedEmbedData;
use super::keys::hash_id;
use super::*;
use crate::error::Error;
use serde_json::{Value, json};

fn fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/ts_embed_writes.json"
    ))
    .unwrap()
}
fn parent_input(local_only: bool) -> Value {
    let mut input = fixture()["finalized"][0]["input"].clone();
    input["local_only"] = json!(local_only);
    input
}

#[test]
fn local_only_session_refuses_master_wrapped_chat_keys() {
    let session = EmbedWriteSession::local_only();
    let result = session.chat_key_adoption("anonymous-chat", "wrapped");
    assert!(matches!(
        result,
        Err(Error::Unavailable {
            code: "embed_master_unavailable",
            ..
        })
    ));
}

#[test]
fn local_only_session_refuses_master_wrapped_embed_keys() {
    let session = EmbedWriteSession::local_only();
    let embed_id = "embed-1";
    let row = json!({
        "hashed_embed_id": hash_id(embed_id),
        "encrypted_embed_key": "wrapped",
        "key_type": "master"
    });
    let result = session.embed_wrapper_adoption(embed_id, "anonymous-chat", &row);
    assert!(matches!(
        result,
        Err(Error::Unavailable {
            code: "embed_master_unavailable",
            ..
        })
    ));
}

#[test]
fn local_only_session_refuses_a_server_payload_completion() {
    let mut session = EmbedWriteSession::local_only();
    let data = StreamedEmbedData::from_value(parent_input(false)).unwrap();
    assert!(matches!(
        session.plan_stream_completion(data),
        Err(Error::Unavailable {
            code: "embed_local_only_required",
            ..
        })
    ));
}

#[tokio::test]
async fn local_only_session_completes_a_local_only_embed_without_server_material() {
    let mut session = EmbedWriteSession::local_only();
    let data = StreamedEmbedData::from_value(parent_input(true)).unwrap();
    let chat_id = data.chat_id().to_owned();
    session.install_chat_key(&chat_id, &[7u8; 32]).unwrap();
    let prepared = session
        .plan_stream_completion(data)
        .unwrap()
        .finish(1_790_000_000_000)
        .await
        .unwrap();
    assert!(prepared.store_payload.is_none());
    assert!(prepared.server_keys.is_none());
    assert!(
        prepared
            .local_key_wrappers
            .iter()
            .all(|row| row["key_type"] != "master")
    );
    assert!(!prepared.local_key_wrappers.is_empty());
}
