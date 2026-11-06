//! Web [`AeadProvider`] (WebCrypto in the shared Worker) and the crypto unit's
//! bulk exports.
//!
//! Formats and policy are the shared SDK's (`crypto::aead` over
//! `chat_key_policy`): base64 decode, OM header and fingerprint check, the
//! ordered authenticated attempts and the OM / Formats C-D framing. Only the
//! AES-256-GCM primitive runs on the Worker's WebCrypto, because the browser's
//! native AES-GCM is several times faster than software AES in WASM. A list of
//! primitive calls is issued at once over one joined input buffer and awaited
//! as one `Promise.allSettled`, so a list costs one Rust future, not one
//! future (and its JS callbacks) per call. Chat keys
//! are imported non-extractable and cached by SHA-256 digest (never by raw
//! bytes); no key material is returned.
use crate::browser_crypto::BrowserMasterCrypto;
use crate::browser_web_crypto::{import_aes, subtle};
use js_sys::{Array, Object, Reflect, Uint8Array};
use openmates_sdk::{
    Error, Result as SdkResult,
    crypto::{
        aead::{
            self, AeadBatch, AeadBatchFuture, AeadBatchKey, AeadKeyFuture, AeadOp, AeadProvider,
            SharedAeadKey, share_aead_key,
        },
        chat_key_policy::{self as policy, ChatContentOutcome},
        master::{MasterCrypto, MasterCryptoFuture},
    },
};
use std::{cell::RefCell, collections::HashMap};
use wasm_bindgen::{JsCast, JsValue, prelude::wasm_bindgen};
use wasm_bindgen_futures::JsFuture;
use web_sys::{CryptoKey, SubtleCrypto};
use zeroize::Zeroizing;

fn batch_unavailable() -> Error {
    Error::Unavailable {
        code: "web_crypto_unavailable",
        reason: "WEBCRYPTO_AES_BATCH_FAILED",
    }
}

/// Chat-key handle: single ops use the reviewed `BrowserMasterCrypto`
/// primitive; lists are issued at once and settled together.
struct WebAeadKey {
    single: BrowserMasterCrypto,
    key: CryptoKey,
    subtle: SubtleCrypto,
}

impl WebAeadKey {
    async fn run(&self, ops: &[AeadOp<'_>], encrypt: bool) -> AeadBatch {
        // A list-wide failure is not an authentication result: every op
        // reports it, so the policy aborts instead of trying the next attempt.
        self.run_list(ops, encrypt)
            .await
            .unwrap_or_else(|_| ops.iter().map(|_| Err(batch_unavailable())).collect())
    }

    async fn run_list(&self, ops: &[AeadOp<'_>], encrypt: bool) -> SdkResult<AeadBatch> {
        if ops.is_empty() {
            return Ok(Vec::new());
        }
        let fail = |_| batch_unavailable();
        let mut ivs = Zeroizing::new(Vec::with_capacity(ops.len() * 12));
        let mut data = Zeroizing::new(Vec::new());
        let mut ends = Vec::with_capacity(ops.len());
        for op in ops {
            ivs.extend_from_slice(op.iv);
            data.extend_from_slice(op.input);
            ends.push(u32::try_from(data.len()).map_err(|_| batch_unavailable())?);
        }
        let ivs = Uint8Array::from(ivs.as_slice());
        let joined = Uint8Array::from(data.as_slice());
        // WebCrypto normalizes the algorithm (copying the IV) and snapshots the
        // input during invocation, so one params object serves the whole list
        // and the joined input is wiped right after the last call is issued.
        let params = Object::new();
        let iv_key = JsValue::from_str("iv");
        Reflect::set(
            &params,
            &JsValue::from_str("name"),
            &JsValue::from_str("AES-GCM"),
        )
        .map_err(fail)?;
        Reflect::set(
            &params,
            &JsValue::from_str("tagLength"),
            &JsValue::from_f64(128.0),
        )
        .map_err(fail)?;
        let operations = Array::new_with_length(ops.len() as u32);
        let mut start = 0u32;
        let issued = (0..ops.len()).try_for_each(|index| {
            let at = index as u32 * 12;
            Reflect::set(&params, &iv_key, &ivs.subarray(at, at + 12))?;
            let input = joined.subarray(start, ends[index]);
            start = ends[index];
            let operation = if encrypt {
                self.subtle
                    .encrypt_with_object_and_js_u8_array(&params, &self.key, &input)?
            } else {
                self.subtle
                    .decrypt_with_object_and_js_u8_array(&params, &self.key, &input)?
            };
            operations.set(index as u32, operation.into());
            Ok::<(), JsValue>(())
        });
        joined.fill(0, 0, joined.length());
        issued.map_err(fail)?;
        let settled: Array = JsFuture::from(js_sys::Promise::all_settled(&operations))
            .await
            .map_err(fail)?
            .dyn_into()
            .map_err(fail)?;
        if settled.length() as usize != ops.len() {
            return Err(batch_unavailable());
        }
        let status_key = JsValue::from_str("status");
        let value_key = JsValue::from_str("value");
        let mut results = Vec::with_capacity(ops.len());
        for entry in settled.iter() {
            let status = Reflect::get(&entry, &status_key).map_err(fail)?;
            if status.as_string().as_deref() != Some("fulfilled") {
                results.push(Err(Error::Crypto));
                continue;
            }
            let buffer: js_sys::ArrayBuffer = Reflect::get(&entry, &value_key)
                .map_err(fail)?
                .dyn_into()
                .map_err(fail)?;
            let view = Uint8Array::new(&buffer);
            results.push(Ok(Zeroizing::new(view.to_vec())));
            view.fill(0, 0, view.length());
        }
        Ok(results)
    }
}

impl MasterCrypto for WebAeadKey {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plaintext: &'a [u8]) -> MasterCryptoFuture<'a> {
        self.single.encrypt(iv, plaintext)
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], sealed: &'a [u8]) -> MasterCryptoFuture<'a> {
        self.single.decrypt(iv, sealed)
    }
}

impl AeadBatchKey for WebAeadKey {
    fn decrypt_many<'a>(&'a self, ops: &'a [AeadOp<'a>]) -> AeadBatchFuture<'a> {
        Box::pin(self.run(ops, false))
    }
    fn encrypt_many<'a>(&'a self, ops: &'a [AeadOp<'a>]) -> AeadBatchFuture<'a> {
        Box::pin(self.run(ops, true))
    }
}

/// Upper bound for one list; the page client sends at most a few hundred.
const MAX_ITEMS: usize = 1 << 16;
const KEY_CACHE_LIMIT: usize = 512;

thread_local! {
    // Keyed by SHA-256 of the chat key; the raw key is never a map key.
    static KEYS: RefCell<HashMap<[u8; 32], SharedAeadKey>> = RefCell::new(HashMap::new());
}

/// WebCrypto AES-256-GCM of the Worker realm.
pub(crate) struct WebAead;

impl AeadProvider for WebAead {
    fn import_key<'a>(&'a self, raw: &'a [u8; 32]) -> AeadKeyFuture<'a> {
        Box::pin(async move {
            let digest = policy::key_cache_digest(raw);
            if let Some(key) = KEYS.with(|keys| keys.borrow().get(&digest).cloned()) {
                return Ok(key);
            }
            let unavailable = |_| Error::Unavailable {
                code: "web_crypto_unavailable",
                reason: "WEBCRYPTO_AES_KEY_IMPORT_FAILED",
            };
            let crypto_key = import_aes(raw).await.map_err(unavailable)?;
            let key = share_aead_key(WebAeadKey {
                single: BrowserMasterCrypto::new(crypto_key.clone())
                    .map_err(|_| unavailable(JsValue::NULL))?,
                key: crypto_key,
                subtle: subtle().map_err(unavailable)?,
            });
            KEYS.with(|keys| {
                let mut keys = keys.borrow_mut();
                if keys.len() >= KEY_CACHE_LIMIT {
                    keys.clear();
                }
                keys.insert(digest, key.clone());
            });
            Ok(key)
        })
    }
}

/// Drops every cached chat-key AES handle (logout, key rotation).
pub(crate) fn clear_keys() {
    KEYS.with(|keys| keys.borrow_mut().clear());
}

/// Cached chat-key AES handles (logout proof; no key material).
pub(crate) fn cached_keys() -> u32 {
    KEYS.with(|keys| keys.borrow().len() as u32)
}

pub(crate) fn refused() -> JsValue {
    JsValue::from_str("crypto")
}

pub(crate) fn chat_key(raw: Vec<u8>) -> Option<Zeroizing<[u8; 32]>> {
    let raw = Zeroizing::new(raw);
    let mut key = Zeroizing::new([0u8; 32]);
    (raw.len() == 32).then(|| {
        key.copy_from_slice(&raw);
        key
    })
}

/// Page result of one chat-content read: the text, `null`, or
/// `{ fingerprintMismatch: "<8 hex>" }` so the page can run candidate recovery.
pub(crate) fn outcome_to_js(outcome: ChatContentOutcome) -> Result<JsValue, JsValue> {
    match outcome {
        ChatContentOutcome::Plaintext(plain) => Ok(match std::str::from_utf8(&plain) {
            Ok(text) => JsValue::from_str(text),
            Err(_) => JsValue::from_str(&Zeroizing::new(
                String::from_utf8_lossy(&plain).into_owned(),
            )),
        }),
        ChatContentOutcome::FingerprintMismatch(stored) => {
            let result = Object::new();
            let hex: String = stored.iter().map(|b| format!("{b:02x}")).collect();
            Reflect::set(
                &result,
                &JsValue::from_str("fingerprintMismatch"),
                &JsValue::from_str(&hex),
            )?;
            Ok(result.into())
        }
        ChatContentOutcome::Failed => Ok(JsValue::NULL),
    }
}

fn bounded(items: &[String]) -> Result<(), JsValue> {
    if items.len() > MAX_ITEMS {
        Err(refused())
    } else {
        Ok(())
    }
}

/// List form of `decryptWithChatKey`: one entry per item (see `outcome_to_js`).
/// An invalid key reads every item as `null`, like the TS reader.
#[wasm_bindgen(js_name = webCryptoBulkDecryptChat)]
pub async fn bulk_decrypt_chat(key: Vec<u8>, items: Vec<String>) -> Result<Array, JsValue> {
    bounded(&items)?;
    let Some(raw) = chat_key(key) else {
        return Ok(items.iter().map(|_| JsValue::NULL).collect());
    };
    let handle = WebAead.import_key(&raw).await.map_err(|_| refused())?;
    let outcomes = aead::open_chat_batch(handle.as_ref(), &raw, &items)
        .await
        .map_err(|_| refused())?;
    let out = Array::new();
    for outcome in outcomes {
        out.push(&outcome_to_js(outcome)?);
    }
    Ok(out)
}

/// List form of `encryptWithChatKey`: OM frames with a fresh IV per item.
#[wasm_bindgen(js_name = webCryptoBulkEncryptChat)]
pub async fn bulk_encrypt_chat(key: Vec<u8>, items: Vec<String>) -> Result<Array, JsValue> {
    bounded(&items)?;
    let items: Vec<Zeroizing<String>> = items.into_iter().map(Zeroizing::new).collect();
    let raw = chat_key(key).ok_or_else(refused)?;
    let handle = WebAead.import_key(&raw).await.map_err(|_| refused())?;
    let plain: Vec<&[u8]> = items.iter().map(|item| item.as_bytes()).collect();
    let sealed = aead::seal_chat_batch(handle.as_ref(), &raw, &plain)
        .await
        .map_err(|_| refused())?;
    Ok(sealed
        .iter()
        .map(|frame| JsValue::from_str(frame))
        .collect())
}

/// List form of the Formats C/D read (`decryptChatKeyWithMasterKey`) under the
/// page's structured-cloned master CryptoKey: `{ values, errors }`, where a
/// failed item is `null` in `values` and `[index, "crypto"]` in `errors`.
#[wasm_bindgen(js_name = webCryptoBulkMasterDecrypt)]
pub async fn bulk_master_decrypt(
    master_key: CryptoKey,
    items: Vec<String>,
) -> Result<Object, JsValue> {
    bounded(&items)?;
    let master = BrowserMasterCrypto::new(master_key).map_err(|_| refused())?;
    let values = Array::new();
    let errors = Array::new();
    for (index, result) in aead::open_master_batch(&master, &items)
        .await
        .into_iter()
        .enumerate()
    {
        match result {
            Ok(plain) => {
                values.push(&Uint8Array::from(plain.as_slice()));
            }
            Err(_) => {
                values.push(&JsValue::NULL);
                let entry = Array::new();
                entry.push(&JsValue::from_f64(index as f64));
                entry.push(&refused());
                errors.push(&entry);
            }
        }
    }
    let out = Object::new();
    Reflect::set(&out, &JsValue::from_str("values"), &values)?;
    Reflect::set(&out, &JsValue::from_str("errors"), &errors)?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    //! Real DedicatedWorker WebCrypto against the TS-generated corpus; runs in
    //! isolated WASM CI (browser_crypto_tests configures the Worker runner).
    use super::*;
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    use wasm_bindgen_test::wasm_bindgen_test;

    fn label(outcome: &ChatContentOutcome) -> String {
        match outcome {
            ChatContentOutcome::Plaintext(plain) => format!("plain:{plain:?}"),
            ChatContentOutcome::FingerprintMismatch(fp) => format!("mismatch:{fp:?}"),
            ChatContentOutcome::Failed => "failed".to_owned(),
        }
    }

    // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
    #[wasm_bindgen_test(async)]
    async fn web_aead_matches_the_native_policy_on_ts_vectors() {
        let corpus: serde_json::Value = serde_json::from_str(include_str!(
            "../../openmates-rust/tests/crypto_fixtures/ts_web_policy.json"
        ))
        .unwrap();
        let raw: [u8; 32] = STANDARD
            .decode(corpus["keys"]["k1_b64"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let items: Vec<String> = corpus["chat_content"]
            .as_array()
            .unwrap()
            .iter()
            .map(|case| case["ciphertext"].as_str().unwrap().to_owned())
            .collect();
        let key = WebAead.import_key(&raw).await.unwrap();
        let outcomes = aead::open_chat_batch(key.as_ref(), &raw, &items)
            .await
            .unwrap();
        for (item, outcome) in items.iter().zip(&outcomes) {
            assert_eq!(
                label(outcome),
                label(&policy::decrypt_chat_content(item, &raw)),
                "{item}"
            );
        }
        let sealed = aead::seal_chat_batch(key.as_ref(), &raw, &[b"web writer".as_slice()])
            .await
            .unwrap();
        assert!(
            matches!(policy::decrypt_chat_content(&sealed[0], &raw), ChatContentOutcome::Plaintext(p) if p.as_slice() == b"web writer")
        );
        assert!(cached_keys() >= 1);
        clear_keys();
        assert_eq!(cached_keys(), 0);
    }
}
