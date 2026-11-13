//! Sectioned layout: golden records captured from the pre-move TUI code still
//! read and rewrite byte-compatibly, the commit order (sections, barrier,
//! index last), change-only publication, partial retention and revocation.
use super::*;
use crate::error::Error;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::{Arc, Mutex},
};

const OWNER_RAW: &str = "synthetic-owner";
const OWNER: &str = "90f9d7c2dc3a74b071652feddec532207e1aad02a37030875aa70b9266e8a4e8";
const CONTEXT: &str = "a482d440e75f0ab8f67ef8aa8fb26498f758cd2eb1a0a51af0defeff0e4237c8";
const KEY: [u8; 32] = [7; 32];
const FENCE: &str = r#"{"version":1,"epoch":"c4f86cef-590c-4a5e-8120-eb6a27ded8a2","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}"#;
const REVOKED_FENCE: &str = r#"{"version":1,"epoch":"0d1b5c1e-2f0a-4a4b-9e0e-5a3f2d5f9b11","revoked":true,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}"#;

/// Everything a test observes about the store: every mutation in order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum Op {
    Put(String, Durability),
    Delete(String),
    Barrier,
}

/// In-memory `ByteStore` with a mutation log. Locks are non-reentrant and a
/// second take of a held scope panics, which would be a deadlock in production.
#[derive(Default)]
pub(super) struct MemStore {
    files: Mutex<BTreeMap<String, (Vec<u8>, u64)>>,
    held: Arc<Mutex<BTreeSet<String>>>,
    log: Mutex<Vec<Op>>,
    clock: Mutex<u64>,
}

struct Release(Arc<Mutex<BTreeSet<String>>>, String);
impl Drop for Release {
    fn drop(&mut self) {
        self.0.lock().unwrap().remove(&self.1);
    }
}

impl MemStore {
    pub(super) fn with_fence(fence: &str) -> Self {
        let store = Self::default();
        store
            .files
            .lock()
            .unwrap()
            .insert(REVOCATION_FILE.into(), (fence.as_bytes().to_vec(), 0));
        store
    }
    pub(super) fn insert(&self, name: &str, bytes: &[u8]) {
        self.files
            .lock()
            .unwrap()
            .insert(name.into(), (bytes.to_vec(), 0));
    }
    pub(super) fn bytes(&self, name: &str) -> Option<Vec<u8>> {
        self.files
            .lock()
            .unwrap()
            .get(name)
            .map(|(bytes, _)| bytes.clone())
    }
    pub(super) fn cache_names(&self) -> Vec<String> {
        self.files
            .lock()
            .unwrap()
            .keys()
            .filter(|name| name.starts_with("cache-"))
            .cloned()
            .collect()
    }
    pub(super) fn take_log(&self) -> Vec<Op> {
        std::mem::take(&mut *self.log.lock().unwrap())
    }
}

impl ByteStore for MemStore {
    type Version = u64;
    fn get(&self, name: &str) -> std::result::Result<Option<Vec<u8>>, ByteStoreError> {
        Ok(self.bytes(name))
    }
    fn version(&self, name: &str) -> std::result::Result<Option<u64>, ByteStoreError> {
        Ok(self
            .files
            .lock()
            .unwrap()
            .get(name)
            .map(|(_, version)| *version))
    }
    fn put(
        &self,
        name: &str,
        bytes: &[u8],
        durability: Durability,
    ) -> std::result::Result<(), ByteStoreError> {
        let mut clock = self.clock.lock().unwrap();
        *clock += 1;
        self.files
            .lock()
            .unwrap()
            .insert(name.into(), (bytes.to_vec(), *clock));
        self.log
            .lock()
            .unwrap()
            .push(Op::Put(name.into(), durability));
        Ok(())
    }
    fn delete(&self, name: &str) -> std::result::Result<(), ByteStoreError> {
        self.files.lock().unwrap().remove(name);
        self.log.lock().unwrap().push(Op::Delete(name.into()));
        Ok(())
    }
    fn list(&self, prefix: &str) -> std::result::Result<Vec<String>, ByteStoreError> {
        Ok(self
            .files
            .lock()
            .unwrap()
            .keys()
            .filter(|name| name.starts_with(prefix))
            .cloned()
            .collect())
    }
    fn barrier(&self) -> std::result::Result<(), ByteStoreError> {
        self.log.lock().unwrap().push(Op::Barrier);
        Ok(())
    }
    fn sync(&self, _: &str) -> std::result::Result<(), ByteStoreError> {
        Ok(())
    }
    fn lock(&self, scope: &str) -> std::result::Result<LockGuard, ByteStoreError> {
        assert!(
            self.held.lock().unwrap().insert(scope.into()),
            "lock {scope} taken twice"
        );
        Ok(LockGuard::new(Release(self.held.clone(), scope.into())))
    }
}

pub(super) fn admission() -> FixedContext {
    FixedContext(CacheContext {
        owner_hash: OWNER.into(),
        context: CONTEXT.into(),
        expires_at: None,
    })
}

fn name(logical: &str) -> String {
    cache_file_name(OWNER_RAW, logical)
}

const GOLDEN: [(&str, &str, &[u8]); 4] = [
    (
        "sync-personal#index",
        "index",
        include_bytes!("golden/index.json"),
    ),
    (
        "sync-personal#shared",
        "shared",
        include_bytes!("golden/shared.json"),
    ),
    (
        "sync-personal#chat:chat-a",
        "chat-a",
        include_bytes!("golden/chat-a.json"),
    ),
    (
        "sync-personal#chat:chat-b",
        "chat-b",
        include_bytes!("golden/chat-b.json"),
    ),
];

fn golden_snapshot() -> Value {
    json!({"chats":{"chat-a":{"id":"chat-a","encrypted_title":"opaque-a"},"chat-b":{"id":"chat-b","encrypted_title":"opaque-b"}},
        "wrappers":[],"history":{"chat-a":[{"id":"m1","encrypted_content":"c1"}],"chat-b":[{"id":"m2","encrypted_content":"c2"}]},
        "embeds":{"e1":{"id":"e1","hashed_chat_id":"unbound"}},"embed_keys":[],"revision":3})
}

fn golden_store() -> MemStore {
    let store = MemStore::with_fence(FENCE);
    for (logical, _, bytes) in GOLDEN {
        store.insert(&name(logical), bytes);
    }
    store
}

fn plaintext(store: &MemStore, logical: &str) -> Value {
    let aad = admission().0.aad(logical).unwrap();
    let bytes = store.bytes(&name(logical)).unwrap();
    decode_cache_record_value(&bytes, &KEY, &aad).unwrap()
}

#[test]
fn golden_records_from_the_previous_layout_read_back_completely() {
    let engine = CacheEngine::new(golden_store());
    let read = engine
        .read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Complete,
        )
        .unwrap()
        .unwrap();
    let SyncCacheRead::Complete(value) = read else {
        panic!("expected a complete read")
    };
    assert_eq!(value["chats"]["chat-a"]["encrypted_title"], "opaque-a");
    assert_eq!(value["history"]["chat-b"][0]["id"], "m2");
    assert_eq!(value["embeds"]["e1"]["id"], "e1");
    assert_eq!(value["revision"], 3);
}

#[test]
fn golden_index_mode_reads_one_record_and_one_chat_on_demand() {
    let store = golden_store();
    let engine = CacheEngine::new(store);
    let read = engine
        .read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Index,
        )
        .unwrap()
        .unwrap();
    let SyncCacheRead::Index(index) = read else {
        panic!("expected an index read")
    };
    assert!(index["chats"]["chat-a"].is_object());
    assert!(index.get("history").is_none(), "content stays on disk");
    let chat = engine
        .read_sync_chat(&admission(), OWNER_RAW, "sync-personal", &KEY, "chat-b")
        .unwrap()
        .unwrap();
    assert_eq!(chat["history"][0]["id"], "m2");
}

#[test]
fn rewriting_the_golden_snapshot_keeps_names_and_plaintext_layout() {
    let golden = golden_store();
    let fresh = MemStore::with_fence(FENCE);
    let engine = CacheEngine::new(fresh);
    let prepared = engine
        .prepare_sync_sections(golden_snapshot(), None)
        .unwrap();
    assert!(
        engine
            .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
            .unwrap()
    );
    assert_eq!(engine.bytes().cache_names().len(), 4);
    for (logical, _, _) in GOLDEN {
        let mut old = plaintext(&golden, logical);
        let mut new = plaintext(engine.bytes(), logical);
        // Set ids are fresh per write; everything else must be identical.
        for value in [&mut old, &mut new] {
            if let Some(object) = value.as_object_mut() {
                object.remove("set");
                object.remove("records");
                object.remove("shared");
            }
        }
        assert_eq!(old, new, "{logical}");
    }
}

#[test]
fn sections_are_written_first_then_a_barrier_then_the_index_last() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let prepared = engine
        .prepare_sync_sections(golden_snapshot(), None)
        .unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    let log = engine.bytes().take_log();
    let index = name("sync-personal#index");
    let index_at = log
        .iter()
        .position(|op| matches!(op, Op::Put(n, _) if *n == index))
        .unwrap();
    let barrier_at = log.iter().position(|op| *op == Op::Barrier).unwrap();
    assert_eq!(index_at, log.len() - 1, "nothing follows the index commit");
    assert!(barrier_at < index_at, "barrier before the index");
    for (position, op) in log.iter().enumerate().take(index_at) {
        if let Op::Put(put, durability) = op {
            assert_eq!(
                *durability,
                Durability::AfterBarrier,
                "section {put} at {position}"
            );
        }
    }
    assert!(matches!(&log[index_at], Op::Put(_, Durability::Now)));
}

#[test]
fn an_unchanged_snapshot_writes_nothing_and_a_changed_chat_rewrites_only_it() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let write = |snapshot: Value| {
        let prepared = engine.prepare_sync_sections(snapshot, None).unwrap();
        engine
            .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
            .unwrap()
    };
    assert!(write(golden_snapshot()));
    engine.bytes().take_log();
    assert!(!write(golden_snapshot()), "nothing changed");
    assert!(
        engine.bytes().take_log().is_empty(),
        "no put, delete or barrier"
    );
    let mut changed = golden_snapshot();
    changed["history"]["chat-a"] = json!([{"id":"m1","encrypted_content":"c1b"}]);
    assert!(write(changed));
    let puts: Vec<_> = engine
        .bytes()
        .take_log()
        .into_iter()
        .filter_map(|op| match op {
            Op::Put(name, _) => Some(name),
            _ => None,
        })
        .collect();
    assert_eq!(
        puts,
        vec![
            name("sync-personal#chat:chat-a"),
            name("sync-personal#index")
        ]
    );
}

#[test]
fn a_partial_client_keeps_the_content_of_chats_it_never_restored() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let prepared = engine
        .prepare_sync_sections(golden_snapshot(), None)
        .unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    let mut partial = golden_snapshot();
    partial["history"] = json!({});
    let prepared = engine.prepare_sync_sections(partial, Some(vec![])).unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    let chat = engine
        .read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Index,
        )
        .and_then(|_| {
            engine.read_sync_chat(&admission(), OWNER_RAW, "sync-personal", &KEY, "chat-a")
        })
        .unwrap()
        .unwrap();
    assert_eq!(chat["history"][0]["id"], "m1");
}

#[test]
fn a_removed_chat_loses_its_section_record() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let prepared = engine
        .prepare_sync_sections(golden_snapshot(), None)
        .unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    let mut smaller = golden_snapshot();
    smaller["chats"].as_object_mut().unwrap().remove("chat-b");
    smaller["history"].as_object_mut().unwrap().remove("chat-b");
    let prepared = engine.prepare_sync_sections(smaller, None).unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    assert!(
        engine
            .bytes()
            .bytes(&name("sync-personal#chat:chat-b"))
            .is_none()
    );
    assert!(
        engine
            .bytes()
            .bytes(&name("sync-personal#chat:chat-a"))
            .is_some()
    );
}

#[test]
fn a_single_record_write_retires_the_sections_and_reads_back() {
    let engine = CacheEngine::new(golden_store());
    engine
        .write_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            &json!({"single": true}),
        )
        .unwrap();
    assert!(
        engine.bytes().bytes(&name("sync-personal#index")).is_none(),
        "index retired"
    );
    let read = engine
        .read_cache(&admission(), OWNER_RAW, "sync-personal", &KEY)
        .unwrap();
    assert_eq!(read, Some(json!({"single": true})));
}

#[test]
fn a_revoked_fence_refuses_publication_and_reads() {
    let engine = CacheEngine::new(MemStore::with_fence(REVOKED_FENCE));
    let prepared = engine
        .prepare_sync_sections(golden_snapshot(), None)
        .unwrap();
    assert!(matches!(
        engine.write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared),
        Err(Error::Authentication)
    ));
    assert!(engine.bytes().cache_names().is_empty());
    assert!(matches!(
        engine.read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Index
        ),
        Err(Error::Authentication)
    ));
}

#[test]
fn another_owner_and_a_wrong_key_are_refused() {
    let engine = CacheEngine::new(golden_store());
    assert!(matches!(
        engine.read_sync_cache(
            &admission(),
            "another-owner",
            "sync-personal",
            &KEY,
            SyncReadMode::Index
        ),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        engine.read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &[8; 32],
            SyncReadMode::Index
        ),
        Err(Error::Crypto)
    ));
}

#[test]
fn a_chat_read_before_the_index_is_refused() {
    let engine = CacheEngine::new(golden_store());
    assert!(matches!(
        engine.read_sync_chat(&admission(), OWNER_RAW, "sync-personal", &KEY, "chat-a"),
        Err(Error::Cancelled)
    ));
}

#[test]
fn a_section_record_with_a_stale_set_id_is_treated_as_absent() {
    let store = golden_store();
    let engine = CacheEngine::new(store);
    // Replace chat-a with a record whose set id the index does not name.
    let aad = admission().0.aad("sync-personal#chat:chat-a").unwrap();
    let stale = json!({"version":1,"set":"00000000-0000-4000-8000-000000000000","chat":"chat-a","section":{"history":{}}});
    let bytes = encode_cache_record(&KEY, &serde_json::to_vec(&stale).unwrap(), &aad).unwrap();
    engine
        .bytes()
        .insert(&name("sync-personal#chat:chat-a"), &bytes);
    engine
        .read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Index,
        )
        .unwrap();
    let chat = engine
        .read_sync_chat(&admission(), OWNER_RAW, "sync-personal", &KEY, "chat-a")
        .unwrap();
    assert!(chat.is_none());
}

#[test]
fn freshness_revocation_is_durable_and_stripped_on_the_next_read() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let mut snapshot = golden_snapshot();
    snapshot[crate::client::snapshot_sections::CHAT_LIST_FRESHNESS_FIELD] = json!({"opaque": 1});
    let prepared = engine.prepare_sync_sections(snapshot, None).unwrap();
    engine
        .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
        .unwrap();
    engine
        .revoke_sync_freshness(&admission(), OWNER_RAW, "sync-personal")
        .unwrap();
    engine
        .revoke_sync_freshness(&admission(), OWNER_RAW, "sync-personal")
        .unwrap();
    let read = engine
        .read_sync_cache(
            &admission(),
            OWNER_RAW,
            "sync-personal",
            &KEY,
            SyncReadMode::Index,
        )
        .unwrap()
        .unwrap();
    let SyncCacheRead::Index(index) = read else {
        panic!("expected an index read")
    };
    assert!(
        index
            .get(crate::client::snapshot_sections::CHAT_LIST_FRESHNESS_FIELD)
            .is_none()
    );
}

#[test]
fn forgetting_evidence_makes_the_next_write_republish_everything() {
    let engine = CacheEngine::new(MemStore::with_fence(FENCE));
    let write = || {
        let prepared = engine
            .prepare_sync_sections(golden_snapshot(), None)
            .unwrap();
        engine
            .write_sync_sections(&admission(), OWNER_RAW, "sync-personal", &KEY, prepared)
            .unwrap()
    };
    write();
    engine.forget_evidence();
    assert!(write());
}
