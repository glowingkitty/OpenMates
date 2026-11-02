// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use crate::work::tasks::tests::{client, mock};

#[tokio::test]
async fn direct_chat_identity_is_enrolled_once_with_a_master_key_backup() {
    let (api, server) = mock(vec![json!({"key":{"version":1}})]).await;
    let mut c = client(&api);
    c.teams().ensure_direct_chat_identity().await.unwrap();
    assert_eq!(
        server.await.unwrap().len(),
        1,
        "an existing identity is never replaced"
    );

    let (api, server) = mock(vec![json!({"key":null}), json!({"key":{}})]).await;
    let mut c = client(&api);
    c.teams().ensure_direct_chat_identity().await.unwrap();
    let requests = server.await.unwrap();
    assert!(requests[1].starts_with("PUT /v1/account/chat-encryption-key "));
    let record: Value =
        serde_json::from_str(requests[1].split("\r\n\r\n").nth(1).unwrap()).unwrap();
    assert_eq!(record["algorithm"], "x25519-xsalsa20poly1305");
    let public = URL_SAFE_NO_PAD
        .decode(record["public_key"].as_str().unwrap())
        .unwrap();
    {
        use sha2::{Digest, Sha256};
        assert_eq!(record["key_id"], crypto::hex(&Sha256::digest(&public)));
    }
    let wrapped = STANDARD.encode(
        URL_SAFE_NO_PAD
            .decode(record["encrypted_private_key"].as_str().unwrap())
            .unwrap(),
    );
    let private = crypto::decrypt_combined(&wrapped, &[7; 32]).unwrap();
    let secret: [u8; 32] = URL_SAFE_NO_PAD.decode(private).unwrap().try_into().unwrap();
    let derived =
        x25519_dalek::PublicKey::from(&x25519_dalek::StaticSecret::from(secret)).to_bytes();
    assert_eq!(derived.as_slice(), public.as_slice());
}
