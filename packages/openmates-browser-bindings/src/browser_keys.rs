//! WASM exports of the chat-key admission policy (`openmates_sdk::web_keys`), keys lane K1.
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/surfaces/sdk#sdk.encryption.local-only
//!
//! Served by the shared Worker `crypto` unit (`rustCore/crypto/keyOps.ts`). Key
//! bytes arrive per call, are compared or hashed and are zeroized on return;
//! nothing here stores a key. Refusals carry the fixed code `rust_keys_bad_request`.
use openmates_sdk::web_keys::{self, KeySource};
use wasm_bindgen::prelude::*;
use zeroize::Zeroizing;

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
    let decision = web_keys::inject_decision(existing.as_deref().map(Vec::as_slice), current, &key, source, force);
    Ok(decision.as_str().to_owned())
}
