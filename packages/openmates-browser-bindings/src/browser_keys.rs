//! WASM exports of the chat-key admission policy (`openmates_sdk::web_keys`), keys lane K1.
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/surfaces/sdk#sdk.encryption.local-only
//!
//! Served by the shared Worker `crypto` unit (`rustCore/crypto/keyOps.ts`). The
//! K1 exports compare or hash key bytes per call and store nothing. The K2
//! `keysState*` exports front the Worker-resident `KeyStore` (one per WASM
//! instance): the page offers keys once and afterwards only holds handles
//! (fingerprint, source, state); encrypt/decrypt by chat id run here with the
//! stored key. Refusals carry fixed codes (`rust_keys_bad_request`,
//! `rust_keys_no_key`, `rust_keys_queue_full`), never key material.
use js_sys::{Array, Object, Reflect};
use openmates_sdk::web_key_state::{Enqueue, KeyState, KeyStore};
use openmates_sdk::web_key_bulk;
use openmates_sdk::web_keys::{self, KeySource};
use std::cell::RefCell;
use wasm_bindgen::prelude::*;
use zeroize::Zeroizing;

thread_local! {
    static STORE: RefCell<KeyStore> = RefCell::new(KeyStore::new());
}

fn with_store<R>(f: impl FnOnce(&mut KeyStore) -> R) -> R {
    STORE.with(|store| f(&mut store.borrow_mut()))
}

fn tickets(list: &[u32]) -> Array {
    list.iter()
        .map(|t| JsValue::from_f64(f64::from(*t)))
        .collect()
}

fn field(object: &Object, name: &str, value: &JsValue) {
    // Reflect::set on a fresh plain object cannot fail.
    let _ = Reflect::set(object, &JsValue::from_str(name), value);
}

fn bad_request() -> JsValue {
    JsValue::from_str("rust_keys_bad_request")
}

/// `computeKeyFingerprint`: 16 hex characters, for comparison and logs only.
#[wasm_bindgen(js_name = keysFingerprint)]
pub fn keys_fingerprint(key: Vec<u8>) -> String {
    web_keys::key_fingerprint(&Zeroizing::new(key))
}

/// `keysAreEqual`: byte equality without an early exit.
#[wasm_bindgen(js_name = keysEqual)]
pub fn keys_equal(a: Vec<u8>, b: Vec<u8>) -> bool {
    web_keys::keys_equal(&Zeroizing::new(a), &Zeroizing::new(b))
}

/// `injectKey` admission: one of `set`, `replace`, `upgrade_source`, `keep`, `reject`.
///
/// `existing` and `current_source` describe the loaded key (absent for an empty slot).
/// Errors with `rust_keys_bad_request` for an unknown source string.
#[wasm_bindgen(js_name = keysInjectDecision)]
pub fn keys_inject_decision(
    existing: Option<Vec<u8>>,
    current_source: Option<String>,
    key: Vec<u8>,
    source: String,
    force: bool,
) -> Result<String, JsValue> {
    let (existing, key) = (existing.map(Zeroizing::new), Zeroizing::new(key));
    let source = KeySource::parse(&source).ok_or_else(bad_request)?;
    let current = match current_source {
        Some(text) => Some(KeySource::parse(&text).ok_or_else(bad_request)?),
        None => None,
    };
    let decision = web_keys::inject_decision(
        existing.as_deref().map(Vec::as_slice),
        current,
        &key,
        source,
        force,
    );
    Ok(decision.as_str().to_owned())
}

/// Offers a key to the Worker store (`injectKey`/rotation with `force`).
///
/// Resolves `{ decision, notifyReady, flushed: number[] }`; `flushed` are the waiter
/// tickets to run now, in arrival order. Errors `rust_keys_bad_request` for an unknown source.
#[wasm_bindgen(js_name = keysStateOffer)]
pub fn keys_state_offer(
    chat_id: String,
    key: Vec<u8>,
    source: String,
    force: bool,
) -> Result<JsValue, JsValue> {
    let key = Zeroizing::new(key);
    let source = KeySource::parse(&source).ok_or_else(bad_request)?;
    let outcome =
        with_store(|store| store.offer(&chat_id, &key, source, force, js_sys::Date::now()));
    let out = Object::new();
    field(
        &out,
        "decision",
        &JsValue::from_str(outcome.decision.as_str()),
    );
    field(
        &out,
        "notifyReady",
        &JsValue::from_bool(outcome.notify_ready),
    );
    field(&out, "flushed", &tickets(&outcome.flushed));
    Ok(out.into())
}

/// The page-safe handle `{ fingerprint, source, timestamp, persisted, state }` or `null`.
#[wasm_bindgen(js_name = keysStateHandle)]
pub fn keys_state_handle(chat_id: String) -> JsValue {
    with_store(|store| {
        let Some(handle) = store.handle(&chat_id) else {
            return JsValue::NULL;
        };
        let out = Object::new();
        field(&out, "fingerprint", &JsValue::from_str(&handle.fingerprint));
        field(
            &out,
            "source",
            &JsValue::from_str(source_name(handle.source)),
        );
        field(&out, "timestamp", &JsValue::from_f64(handle.timestamp_ms));
        field(&out, "persisted", &JsValue::from_bool(handle.persisted));
        field(
            &out,
            "state",
            &JsValue::from_str(store.state(&chat_id).as_str()),
        );
        out.into()
    })
}

fn source_name(source: KeySource) -> &'static str {
    match source {
        KeySource::Created => "created",
        KeySource::MasterKey => "master_key",
        KeySource::ServerSync => "server_sync",
        KeySource::ShareLink => "share_link",
        KeySource::SharedStorage => "shared_storage",
        KeySource::BulkInit => "bulk_init",
        KeySource::HiddenChat => "hidden_chat",
        KeySource::AnonymousSession => "anonymous_session",
        KeySource::DirectChat => "direct_chat",
        KeySource::Injected => "injected",
    }
}

/// Load state of a chat: `unloaded`, `loading`, `ready` or `failed`.
#[wasm_bindgen(js_name = keysStateState)]
pub fn keys_state_state(chat_id: String) -> String {
    with_store(|store| store.state(&chat_id).as_str().to_owned())
}

/// Records `unloaded`, `loading` or `failed` for a chat without a key; errors `rust_keys_bad_request` otherwise.
#[wasm_bindgen(js_name = keysStateSetState)]
pub fn keys_state_set_state(chat_id: String, state: String) -> Result<(), JsValue> {
    let state = KeyState::parse_settable(&state).ok_or_else(bad_request)?;
    with_store(|store| store.set_state(&chat_id, state));
    Ok(())
}

/// Parks a waiter: `{ kind: "ready" }`, `{ kind: "queued", ticket }`; errors `rust_keys_queue_full` at the bound.
#[wasm_bindgen(js_name = keysStateEnqueue)]
pub fn keys_state_enqueue(chat_id: String) -> Result<JsValue, JsValue> {
    let out = Object::new();
    match with_store(|store| store.enqueue(&chat_id)) {
        Enqueue::Ready => field(&out, "kind", &JsValue::from_str("ready")),
        Enqueue::Queued(ticket) => {
            field(&out, "kind", &JsValue::from_str("queued"));
            field(&out, "ticket", &JsValue::from_f64(f64::from(ticket)));
        }
        Enqueue::Full => return Err(JsValue::from_str("rust_keys_queue_full")),
    }
    Ok(out.into())
}

/// Drops a timed-out waiter; true when it was still parked.
#[wasm_bindgen(js_name = keysStateCancel)]
pub fn keys_state_cancel(chat_id: String, ticket: u32) -> bool {
    with_store(|store| store.cancel(&chat_id, ticket))
}

/// Number of parked waiters for a chat.
#[wasm_bindgen(js_name = keysStatePending)]
pub fn keys_state_pending(chat_id: String) -> u32 {
    with_store(|store| u32::try_from(store.pending(&chat_id)).unwrap_or(u32::MAX))
}

/// Marks a provisional (created) key as stored; false when the chat has no key.
#[wasm_bindgen(js_name = keysStateMarkPersisted)]
pub fn keys_state_mark_persisted(chat_id: String) -> bool {
    with_store(|store| store.mark_persisted(&chat_id))
}

/// Forgets a chat's key for a retry load (`reloadKey`); waiters stay parked.
#[wasm_bindgen(js_name = keysStateReset)]
pub fn keys_state_reset(chat_id: String) {
    with_store(|store| store.reset(&chat_id));
}

/// Removes one chat (`removeKey`); returns the waiter tickets the page must reject.
#[wasm_bindgen(js_name = keysStateRemove)]
pub fn keys_state_remove(chat_id: String) -> Array {
    tickets(&with_store(|store| store.remove(&chat_id)))
}

/// Terminates all key state (logout, account switch); returns the waiter tickets to reject.
#[wasm_bindgen(js_name = keysStateClear)]
pub fn keys_state_clear() -> Array {
    tickets(&with_store(KeyStore::clear))
}

/// `{ keys, unpersisted }` counts, no key material (logout proof).
#[wasm_bindgen(js_name = keysStateStats)]
pub fn keys_state_stats() -> JsValue {
    with_store(|store| {
        let out = Object::new();
        field(&out, "keys", &JsValue::from_f64(store.size() as f64));
        field(
            &out,
            "unpersisted",
            &JsValue::from_f64(store.unpersisted() as f64),
        );
        out.into()
    })
}

fn stored_key(chat_id: &str) -> Result<Vec<u8>, JsValue> {
    with_store(|store| store.key(chat_id))
        .map(|key| key.to_vec())
        .ok_or_else(|| JsValue::from_str("rust_keys_no_key"))
}

/// `decryptWithChatKey` with the stored key of `chat_id` (same result shape as `webCryptoDecryptChatContent`).
/// Errors `rust_keys_no_key` when the Worker holds no key for the chat.
#[wasm_bindgen(js_name = keysStateDecrypt)]
pub async fn keys_state_decrypt(chat_id: String, ciphertext: String) -> Result<JsValue, JsValue> {
    // The borrow ends before the await: the store is never locked across a suspension.
    crate::browser_web_crypto::decrypt_chat_content(stored_key(&chat_id)?, ciphertext).await
}

/// `encryptWithChatKey` with the stored key of `chat_id`; errors `rust_keys_no_key` without one.
#[wasm_bindgen(js_name = keysStateEncrypt)]
pub async fn keys_state_encrypt(chat_id: String, plaintext: String) -> Result<String, JsValue> {
    crate::browser_web_crypto::encrypt_chat_content(stored_key(&chat_id)?, plaintext).await
}

/// Bulk chat-key load batches for `count` collected keys as `[[start, end], ...]` (no key material).
#[wasm_bindgen(js_name = keysBulkBatches)]
pub fn keys_bulk_batches(count: u32) -> Array {
    web_key_bulk::batch_ranges(count as usize)
        .into_iter()
        .map(|(start, end)| {
            Array::of2(
                &JsValue::from_f64(start as f64),
                &JsValue::from_f64(end as f64),
            )
            .into()
        })
        .collect()
}

/// Master-key retry step of the bulk load: `decrypt`, `retry` or `give_up`.
#[wasm_bindgen(js_name = keysBulkRetryStep)]
pub fn keys_bulk_retry_step(retry_count: u32, master_key_available: bool) -> String {
    web_key_bulk::retry_step(retry_count, master_key_available)
        .as_str()
        .to_owned()
}
