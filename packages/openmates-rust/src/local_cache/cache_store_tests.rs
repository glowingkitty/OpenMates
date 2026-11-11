//! `CacheStore` over a real directory: ordered queue, generation refusal and
//! the fast paths that do not wait behind a held queue.
use super::{sections_tests::admission, *};
use crate::error::Error;
use serde_json::{Value, json};
use std::{sync::Arc, time::Duration};
use zeroize::Zeroizing;

const OWNER_RAW: &str = "synthetic-owner";

fn directory() -> tempfile::TempDir {
    use std::os::unix::fs::PermissionsExt;
    let mut builder = tempfile::Builder::new();
    builder.permissions(std::fs::Permissions::from_mode(0o700));
    builder.tempdir().unwrap()
}

fn key() -> CacheKey {
    Zeroizing::new([7; 32])
}

fn snapshot() -> Value {
    json!({"chats":{"chat-a":{"id":"chat-a","encrypted_title":"opaque-a"}},
        "wrappers":[],"history":{"chat-a":[{"id":"m1","encrypted_content":"c1"}]},
        "embeds":{},"embed_keys":[],"revision":1})
}

/// A store over a fresh directory with an unrevoked, epoch-1 fence.
fn store(directory: &tempfile::TempDir) -> (CacheStore<FileByteStore>, OrderedBlocking) {
    let bytes = FileByteStore::open(directory.path()).unwrap();
    let fence = r#"{"version":1,"epoch":"c4f86cef-590c-4a5e-8120-eb6a27ded8a2","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}"#;
    bytes
        .put(REVOCATION_FILE, fence.as_bytes(), Durability::Now)
        .unwrap();
    let ops = OrderedBlocking::new();
    let cache = CacheStore::new(
        Arc::new(CacheEngine::new(bytes)),
        Arc::new(admission()),
        Arc::new(NoScope),
        ops.clone(),
    );
    (cache, ops)
}

async fn seed(cache: &CacheStore<FileByteStore>) {
    let prepared = cache.prepare_sections(snapshot(), None).await.unwrap();
    assert!(
        cache
            .write_sections(OWNER_RAW.into(), "sync-personal".into(), key(), prepared)
            .await
            .unwrap()
    );
}

#[tokio::test]
async fn sections_written_through_the_queue_read_back_through_the_fast_paths() {
    let dir = directory();
    let (cache, _) = store(&dir);
    seed(&cache).await;
    let index = cache
        .read_index(OWNER_RAW.into(), "sync-personal".into(), key())
        .await
        .unwrap()
        .unwrap();
    assert!(index["chats"]["chat-a"].is_object());
    let chat = cache
        .cached_chat(
            OWNER_RAW.into(),
            "sync-personal".into(),
            key(),
            "chat-a".into(),
        )
        .await
        .unwrap()
        .unwrap();
    assert_eq!(chat["history"][0]["id"], "m1");
}

#[tokio::test]
async fn fast_paths_do_not_wait_behind_a_held_queue_but_queued_reads_do() {
    let dir = directory();
    let (cache, ops) = store(&dir);
    seed(&cache).await;
    let held = ops.hold().await;
    let fast = tokio::time::timeout(
        Duration::from_secs(5),
        cache.read_index(OWNER_RAW.into(), "sync-personal".into(), key()),
    )
    .await;
    assert!(
        fast.expect("the index fast path must not queue")
            .unwrap()
            .is_some()
    );
    let queued = tokio::time::timeout(
        Duration::from_millis(200),
        cache.read_cache(OWNER_RAW.into(), "sync-personal".into(), key()),
    )
    .await;
    assert!(queued.is_err(), "a queued read waits for the held queue");
    drop(held);
    assert!(
        cache
            .read_cache(OWNER_RAW.into(), "sync-personal".into(), key())
            .await
            .unwrap()
            .is_some()
    );
}

#[tokio::test]
async fn advancing_the_generation_refuses_later_operations_and_the_content_loader() {
    let dir = directory();
    let (cache, ops) = store(&dir);
    seed(&cache).await;
    cache
        .read_index(OWNER_RAW.into(), "sync-personal".into(), key())
        .await
        .unwrap();
    let loader = cache.content_loader(OWNER_RAW.into(), "sync-personal".into(), key());
    assert!(loader(&[]).is_ok());
    let held = ops.hold().await;
    let pending = {
        let cache = cache.clone();
        tokio::spawn(async move {
            cache
                .read_cache(OWNER_RAW.into(), "sync-personal".into(), key())
                .await
        })
    };
    tokio::time::sleep(Duration::from_millis(50)).await;
    ops.advance();
    drop(held);
    assert!(matches!(pending.await.unwrap(), Err(Error::Cancelled)));
    assert!(matches!(loader(&[]), Err(Error::Cancelled)));
    assert!(matches!(
        cache
            .read_index(OWNER_RAW.into(), "sync-personal".into(), key())
            .await
            .map(|_| ()),
        Ok(())
    ));
}

#[tokio::test]
async fn single_record_write_and_read_roundtrip_with_capacity_check() {
    let dir = directory();
    let (cache, _) = store(&dir);
    cache
        .write_cache(OWNER_RAW.into(), "pending".into(), key(), json!(["a"]))
        .await
        .unwrap();
    assert_eq!(
        cache
            .read_cache(OWNER_RAW.into(), "pending".into(), key())
            .await
            .unwrap(),
        Some(json!(["a"]))
    );
    assert!(cache.admits_checkpoint(1024).unwrap());
    assert!(!cache.admits_checkpoint(MAX_LOCAL_RECORD_BYTES).unwrap());
}
