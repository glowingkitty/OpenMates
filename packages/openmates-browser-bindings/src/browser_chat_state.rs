//! Worker-only exports for shared chat read-state and chat management
//! (`openmates_sdk::chat_state`). The hidden-chat combined secret lives only
//! inside the vault resource (zeroized on lock/drop); PBKDF2 runs through
//! WebCrypto so derivation is no slower than the TypeScript path. Results are
//! JSON strings; errors are stable code strings (see `error_code`).
use crate::browser_crypto::BrowserMasterCrypto;
use js_sys::{ArrayBuffer, Object, Reflect, Uint8Array};
use openmates_sdk::Error;
use openmates_sdk::chat_state::{bookmarks, hidden, receipts};
use openmates_sdk::crypto::{Key, master::MasterCapability};
use serde_json::json;
use std::rc::Rc;
use wasm_bindgen::{JsCast, prelude::*};
use wasm_bindgen_futures::JsFuture;
use web_sys::{CryptoKey, DedicatedWorkerGlobalScope, SubtleCrypto};
use zeroize::Zeroizing;

#[path = "browser_chat_state_payloads.rs"]
mod payloads;

/// Stable error codes the TS adapter maps back to the web messages.
pub(crate) fn error_code(error: Error) -> JsValue {
    JsValue::from_str(match error {
        Error::Invalid(message) => message,
        Error::Locked => "locked",
        Error::Crypto => "crypto",
        Error::Protocol => "protocol",
        Error::Cancelled => "cancelled",
        _ => "unavailable",
    })
}

pub(crate) fn worker_only() -> Result<(), JsValue> {
    js_sys::global()
        .dyn_into::<DedicatedWorkerGlobalScope>()
        .map(|_| ())
        .map_err(|_| JsValue::from_str("unavailable"))
}

fn subtle() -> Result<SubtleCrypto, Error> {
    let global = js_sys::global()
        .dyn_into::<DedicatedWorkerGlobalScope>()
        .map_err(|_| Error::Crypto)?;
    let crypto = Reflect::get(&global, &JsValue::from_str("crypto"))
        .map_err(|_| Error::Crypto)?
        .dyn_into::<web_sys::Crypto>()
        .map_err(|_| Error::Crypto)?;
    Ok(crypto.subtle())
}

fn master_capability(master_key: CryptoKey) -> Result<MasterCapability, JsValue> {
    let port = BrowserMasterCrypto::new(master_key).map_err(error_code)?;
    Ok(MasterCapability::from_browser_port(Rc::new(port)))
}

pub(crate) fn chat_key(bytes: &[u8]) -> Result<Zeroizing<[u8; 32]>, JsValue> {
    let raw: [u8; 32] = bytes.try_into().map_err(|_| JsValue::from_str("crypto"))?;
    Ok(Zeroizing::new(raw))
}

/// Copy an ArrayBuffer result out and wipe the JS copy.
fn take_buffer(value: JsValue) -> Result<Zeroizing<Vec<u8>>, Error> {
    let buffer = value.dyn_into::<ArrayBuffer>().map_err(|_| Error::Crypto)?;
    let view = Uint8Array::new(&buffer);
    let bytes = Zeroizing::new(view.to_vec());
    view.fill(0, 0, view.length());
    Ok(bytes)
}

/// `deriveCombinedSecret` through WebCrypto PBKDF2-SHA256 (100k, 256 bits).
async fn derive_secret_webcrypto(
    master_key: &CryptoKey,
    code: &str,
    salt: &[u8],
) -> Result<Key, Error> {
    let subtle = subtle()?;
    let exported = JsFuture::from(
        subtle
            .export_key("raw", master_key)
            .map_err(|_| Error::Crypto)?,
    )
    .await
    .map_err(|_| Error::Crypto)?;
    let raw = take_buffer(exported)?;
    let master: [u8; 32] = raw.as_slice().try_into().map_err(|_| Error::Crypto)?;
    let master = Zeroizing::new(master);
    let input = hidden::combined_secret_input(&master, code)?;
    let password = Uint8Array::from(input.as_bytes());
    let usages = js_sys::Array::of1(&JsValue::from_str("deriveBits"));
    let imported = subtle.import_key_with_str("raw", &password, "PBKDF2", false, &usages);
    password.fill(0, 0, password.length());
    let base = JsFuture::from(imported.map_err(|_| Error::Crypto)?)
        .await
        .map_err(|_| Error::Crypto)?
        .dyn_into::<CryptoKey>()
        .map_err(|_| Error::Crypto)?;
    let params = Object::new();
    let salt = Uint8Array::from(hidden::hidden_salt(salt)?);
    for (name, value) in [
        ("name", JsValue::from_str("PBKDF2")),
        ("salt", salt.into()),
        (
            "iterations",
            JsValue::from_f64(f64::from(hidden::HIDDEN_CHAT_PBKDF2_ITERATIONS)),
        ),
        ("hash", JsValue::from_str("SHA-256")),
    ] {
        Reflect::set(&params, &JsValue::from_str(name), &value).map_err(|_| Error::Crypto)?;
    }
    let bits = JsFuture::from(
        subtle
            .derive_bits_with_object(&params, &base, 256)
            .map_err(|_| Error::Crypto)?,
    )
    .await
    .map_err(|_| Error::Crypto)?;
    let bits = take_buffer(bits)?;
    let secret: [u8; 32] = bits.as_slice().try_into().map_err(|_| Error::Crypto)?;
    Ok(Zeroizing::new(secret))
}

/// One per page session (`hiddenChatService` singleton). Never serialized.
#[wasm_bindgen]
pub struct BrowserHiddenChatVault {
    vault: hidden::HiddenChatVault,
    master: MasterCapability,
    master_key: CryptoKey,
}

fn class_json(class: hidden::ChatKeyClass) -> (String, Option<Uint8Array>) {
    match class {
        hidden::ChatKeyClass::Normal(key) => {
            ("normal".into(), Some(Uint8Array::from(key.as_slice())))
        }
        hidden::ChatKeyClass::Hidden(key) => {
            ("hidden".into(), Some(Uint8Array::from(key.as_slice())))
        }
        hidden::ChatKeyClass::LockedCandidate => ("locked_candidate".into(), None),
    }
}

fn object(pairs: &[(&str, JsValue)]) -> Result<JsValue, JsValue> {
    let output = Object::new();
    for (name, value) in pairs {
        Reflect::set(&output, &JsValue::from_str(name), value)?;
    }
    Ok(output.into())
}

fn optional_bytes(value: Option<Uint8Array>) -> JsValue {
    value.map_or(JsValue::NULL, JsValue::from)
}

#[wasm_bindgen]
impl BrowserHiddenChatVault {
    /// `master_key` is the session master CryptoKey (extractable, as the web
    /// client's `getKeyFromStorage` key is: PBKDF2 input needs raw bytes).
    #[wasm_bindgen(constructor)]
    pub fn new(master_key: CryptoKey) -> Result<BrowserHiddenChatVault, JsValue> {
        worker_only()?;
        let master = master_capability(master_key.clone())?;
        Ok(Self {
            vault: hidden::HiddenChatVault::new(),
            master,
            master_key,
        })
    }

    pub fn is_unlocked(&self) -> bool {
        self.vault.is_unlocked()
    }

    pub fn remaining_lockout_seconds(&mut self, now_ms: f64) -> f64 {
        self.vault.remaining_lockout_seconds(now_ms as u64) as f64
    }

    /// `unlockHiddenChats`: resolves the decrypted count; rejects `locked`
    /// (lockout), the invalid-code message, or `crypto` (derivation failed).
    /// `salt` is the hidden-chat salt (`getOrCreateSalt`), `None` if missing.
    pub async fn unlock(
        &mut self,
        code: String,
        salt: Option<Vec<u8>>,
        encrypted_chat_keys: Vec<String>,
        verified_encrypted_chat_key: Option<String>,
        now_ms: f64,
    ) -> Result<u32, JsValue> {
        worker_only()?;
        let now = now_ms as u64;
        self.vault.admit_unlock(&code, now).map_err(error_code)?;
        let derived = match salt.filter(|s| !s.is_empty()) {
            Some(salt) => derive_secret_webcrypto(&self.master_key, &code, &salt).await,
            None => Err(Error::Crypto),
        };
        let secret = match derived {
            Ok(secret) => secret,
            Err(error) => {
                self.vault.unlock_derivation_failed(now);
                return Err(error_code(error));
            }
        };
        let count = self
            .vault
            .complete_unlock(
                &self.master,
                secret,
                &encrypted_chat_keys,
                verified_encrypted_chat_key.as_deref(),
                now,
            )
            .await
            .map_err(error_code)?;
        Ok(count as u32)
    }

    /// `encryptChatKeyWithCode`: wrap for a code without unlocking.
    pub async fn wrap_with_code(
        &mut self,
        chat_key_bytes: Vec<u8>,
        code: String,
        salt: Option<Vec<u8>>,
        now_ms: f64,
    ) -> Result<String, JsValue> {
        worker_only()?;
        let now = now_ms as u64;
        let key = chat_key(&chat_key_bytes)?;
        self.vault.admit_code_wrap(&code, now).map_err(error_code)?;
        let derived = match salt.filter(|s| !s.is_empty()) {
            Some(salt) => derive_secret_webcrypto(&self.master_key, &code, &salt).await,
            None => Err(Error::Crypto),
        };
        let secret = derived
            .inspect_err(|_| self.vault.code_wrap_derivation_failed(now))
            .map_err(error_code)?;
        hidden::wrap_chat_key(&key, &secret).map_err(error_code)
    }

    /// `encryptChatKeyWithCombinedSecret`; rejects `locked`.
    pub fn wrap(&self, chat_key_bytes: Vec<u8>) -> Result<String, JsValue> {
        self.vault
            .wrap(&*chat_key(&chat_key_bytes)?)
            .map_err(error_code)
    }

    /// `decryptChatKeyWithCombinedSecret`: chat key bytes or `undefined`.
    pub fn unwrap(&self, encrypted_chat_key: String) -> Option<Uint8Array> {
        self.vault
            .unwrap(&encrypted_chat_key)
            .map(|key| Uint8Array::from(key.as_slice()))
    }

    /// `tryDecryptChatKey`: `{class, chatKey}` with class
    /// `normal | hidden | locked_candidate`.
    pub async fn classify(&self, encrypted_chat_key: String) -> Result<JsValue, JsValue> {
        worker_only()?;
        let class = self
            .vault
            .classify(&self.master, &encrypted_chat_key)
            .await
            .map_err(error_code)?;
        let (label, key) = class_json(class);
        object(&[
            ("class", JsValue::from_str(&label)),
            ("chatKey", optional_bytes(key)),
        ])
    }

    /// Hide decision: `{plan: needs_unlock|already_hidden|missing_key|hide,
    /// encryptedChatKey?, decryptedChatKey?}`.
    pub async fn plan_hide(
        &self,
        cached_chat_key: Option<Vec<u8>>,
        encrypted_chat_key: Option<String>,
    ) -> Result<JsValue, JsValue> {
        worker_only()?;
        let cached = cached_chat_key.map(|bytes| chat_key(&bytes)).transpose()?;
        let plan = self
            .vault
            .plan_hide(
                &self.master,
                cached.as_deref(),
                encrypted_chat_key.as_deref(),
            )
            .await
            .map_err(error_code)?;
        match plan {
            hidden::HidePlan::NeedsUnlock => object(&[("plan", "needs_unlock".into())]),
            hidden::HidePlan::AlreadyHidden => object(&[("plan", "already_hidden".into())]),
            hidden::HidePlan::MissingKey => object(&[("plan", "missing_key".into())]),
            hidden::HidePlan::Hide {
                encrypted_chat_key,
                decrypted_chat_key,
            } => object(&[
                ("plan", "hide".into()),
                ("encryptedChatKey", JsValue::from_str(&encrypted_chat_key)),
                (
                    "decryptedChatKey",
                    optional_bytes(decrypted_chat_key.map(|k| Uint8Array::from(k.as_slice()))),
                ),
            ]),
        }
    }

    /// `unhideChat` re-wrap: `{encryptedChatKey}` (master Format C).
    pub async fn unhide(&self, encrypted_chat_key: String) -> Result<JsValue, JsValue> {
        worker_only()?;
        let unhidden = self
            .vault
            .unhide(&self.master, &encrypted_chat_key)
            .await
            .map_err(error_code)?;
        object(&[(
            "encryptedChatKey",
            JsValue::from_str(&unhidden.encrypted_chat_key),
        )])
    }

    /// `lockHiddenChats` (the adapter also clears the chat-key cache).
    pub fn lock(&mut self) {
        self.vault.lock();
    }
}

/// `encrypted_chat_metadata` payload JSON for hide/unhide.
#[wasm_bindgen]
pub fn chat_state_hidden_key_update_payload(
    chat_id: &str,
    encrypted_chat_key: &str,
    messages_v: Option<f64>,
    title_v: Option<f64>,
    last_edited_overall_timestamp: Option<f64>,
    now_seconds: f64,
) -> String {
    let versions = hidden::ChatKeyVersions {
        messages_v: messages_v.map(|v| v as u64),
        title_v: title_v.map(|v| v as u64),
        last_edited_overall_timestamp: last_edited_overall_timestamp.map(|v| v as u64),
    };
    hidden::chat_key_update_payload(chat_id, encrypted_chat_key, versions, now_seconds as u64)
        .to_string()
}

/// `visibleMessageReceipts` ledger (one per page).
#[wasm_bindgen]
pub struct BrowserReceiptLedger {
    ledger: receipts::VisibleReceiptLedger,
}

#[wasm_bindgen]
impl BrowserReceiptLedger {
    #[wasm_bindgen(constructor)]
    pub fn new() -> BrowserReceiptLedger {
        Self {
            ledger: receipts::VisibleReceiptLedger::default(),
        }
    }

    /// `{decision: refused|in_flight|recent|send, ticket?}`.
    pub fn report(
        &mut self,
        owner_id: String,
        chat_id: String,
        epoch: f64,
        connection: Option<f64>,
        message_id: String,
        now_ms: f64,
    ) -> String {
        let scope = receipts::ReceiptScope {
            owner_id,
            chat_id,
            epoch: epoch as u64,
            connection: connection.map(|c| c as u64),
        };
        match self.ledger.report(&scope, &message_id, now_ms as u64) {
            receipts::ReceiptDecision::Refused => json!({"decision": "refused"}),
            receipts::ReceiptDecision::InFlight(ticket) => {
                json!({"decision": "in_flight", "ticket": ticket})
            }
            receipts::ReceiptDecision::Recent => json!({"decision": "recent"}),
            receipts::ReceiptDecision::Send(ticket) => {
                json!({"decision": "send", "ticket": ticket})
            }
        }
        .to_string()
    }

    pub fn settle(&mut self, ticket: f64, sent: bool, now_ms: f64) -> bool {
        self.ledger.settle(ticket as u64, sent, now_ms as u64)
    }
}

impl Default for BrowserReceiptLedger {
    fn default() -> Self {
        Self::new()
    }
}

/// Account bookmarks: `{encryptedSettings, index}` (`index` is
/// `{chat_id: [message_id]}`). The adapter posts `encryptedSettings`.
#[wasm_bindgen]
pub async fn chat_state_bookmarks_toggle_account(
    master_key: CryptoKey,
    encrypted_settings: Option<String>,
    chat_id: String,
    message_id: String,
    legacy_ids: Vec<String>,
) -> Result<String, JsValue> {
    worker_only()?;
    let master = master_capability(master_key)?;
    let toggle = bookmarks::BookmarkToggle {
        chat_id: &chat_id,
        message_id: &message_id,
        legacy_ids: &legacy_ids,
    };
    let write = bookmarks::toggle_account_bookmark(&master, encrypted_settings.as_deref(), &toggle)
        .await
        .map_err(error_code)?;
    Ok(format!(
        "{{\"encryptedSettings\":{},\"index\":{}}}",
        serde_json::Value::from(write.encrypted_settings),
        write.index.to_json()
    ))
}

/// Account bookmarks index JSON from the current `encrypted_settings`.
#[wasm_bindgen]
pub async fn chat_state_bookmarks_read_account(
    master_key: CryptoKey,
    encrypted_settings: Option<String>,
) -> Result<String, JsValue> {
    worker_only()?;
    let master = master_capability(master_key)?;
    let index = bookmarks::read_account_bookmarks(&master, encrypted_settings.as_deref())
        .await
        .map_err(error_code)?;
    Ok(index.to_json())
}

/// Device/transient toggle over the stored localStorage value; returns the
/// new value to store (`[]` JSON array of ids).
#[wasm_bindgen]
pub fn chat_state_bookmarks_toggle_device(
    stored: Option<String>,
    chat_id: String,
    message_id: String,
    legacy_ids: Vec<String>,
) -> Result<String, JsValue> {
    let ids = bookmarks::decode_device_bookmarks(stored.as_deref()).map_err(error_code)?;
    let toggle = bookmarks::BookmarkToggle {
        chat_id: &chat_id,
        message_id: &message_id,
        legacy_ids: &legacy_ids,
    };
    let ids = bookmarks::toggle_local_bookmark(ids, &toggle).map_err(error_code)?;
    Ok(bookmarks::encode_device_bookmarks(&ids))
}

#[wasm_bindgen]
pub fn chat_state_bookmarks_decode_device(stored: Option<String>) -> Result<Vec<String>, JsValue> {
    bookmarks::decode_device_bookmarks(stored.as_deref()).map_err(error_code)
}
