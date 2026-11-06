//! Worker-only embed key resolution and stored-row opening on the
//! `BrowserEmbedWriter` session (`openmates_sdk::client::embed_write`
//! `KeyLookup`, the shared-Rust `embedStore.getEmbedKey` order). Marshals only:
//! JS passes `embed_keys` rows from IndexedDB and stored ciphertext fields; it
//! receives a lookup state and decrypted fields. Keys and wrappers never return.
use super::{BrowserEmbedWriter, code, parse};
use crate::browser_crypto_batch::WebAead;
use openmates_sdk::client::embed_write::{self, KeyLookup};
use openmates_sdk::crypto::aead::AeadProvider;
use serde_json::{Value, json};
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
impl BrowserEmbedWriter {
    /// Installs the chat key the page's write guard validated (team, direct and
    /// anonymous chats included). The page copy should be dropped by the caller;
    /// the Worker never returns it.
    pub fn install_chat_key(&self, chat_id: &str, key: Vec<u8>) -> Result<(), JsValue> {
        let key = zeroize::Zeroizing::new(key);
        self.session
            .borrow_mut()
            .install_chat_key(chat_id, &key)
            .map_err(code)
    }
    /// Loads `embed_id`'s key from its `embed_keys` rows (JSON array). Resolves
    /// to `{"state":"loaded"}`, `{"state":"no_wrappers"}` (legacy child: inherit
    /// the parent) or `{"state":"unavailable","pending_chat_hashes":[..]}`.
    pub fn resolve_embed_key(
        &self,
        embed_id: &str,
        hashed_chat_id: Option<String>,
        rows_json: &str,
    ) -> Result<js_sys::Promise, JsValue> {
        let Value::Array(rows) = parse(rows_json)? else {
            return Err(JsValue::from_str("invalid"));
        };
        let lookup =
            self.session
                .borrow()
                .plan_key_lookup(embed_id, hashed_chat_id.as_deref(), &rows);
        let session = self.session.clone();
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let state = match lookup {
                KeyLookup::Loaded => json!({ "state": "loaded" }),
                KeyLookup::NoWrappers => json!({ "state": "no_wrappers" }),
                KeyLookup::Wrappers {
                    candidates,
                    pending_chat_hashes,
                } => {
                    let mut loaded = false;
                    for candidate in candidates {
                        // A wrapper that does not unwrap is skipped, as the TS lookup's null.
                        if let Ok(adopted) = candidate.resolve().await {
                            session.borrow_mut().install(adopted);
                            loaded = true;
                            break;
                        }
                    }
                    if loaded {
                        json!({ "state": "loaded" })
                    } else {
                        json!({ "state": "unavailable", "pending_chat_hashes": pending_chat_hashes })
                    }
                }
            };
            Ok(JsValue::from_str(&state.to_string()))
        }))
    }
    /// Legacy child without wrappers shares its parent's loaded key.
    pub fn inherit_parent_embed_key(&self, child_id: &str, parent_id: &str) -> bool {
        self.session
            .borrow_mut()
            .inherit_parent_key(child_id, parent_id)
    }
    /// Early HKDF key of a processing parent (children may finalize first).
    pub fn derive_early_parent_key(&self, embed_id: &str, chat_id: &str) -> Result<bool, JsValue> {
        self.session
            .borrow_mut()
            .derive_early_parent_key(embed_id, chat_id)
            .map_err(code)
    }
    /// Opens a stored row's `encrypted_content` / `encrypted_type` /
    /// `encrypted_text_preview` with the loaded embed key in one batched
    /// WebCrypto call. Resolves to `{content, content_failed, type, text_preview}`;
    /// rejects `embed_key_unavailable` when the key is not loaded.
    pub fn open_embed_fields(
        &self,
        embed_id: &str,
        encrypted_content: Option<String>,
        encrypted_type: Option<String>,
        encrypted_text_preview: Option<String>,
    ) -> Result<js_sys::Promise, JsValue> {
        let material = self
            .session
            .borrow()
            .embed_key_material(embed_id)
            .map_err(code)?;
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let handle = WebAead.import_key(&material).await.map_err(code)?;
            drop(material);
            let fields = [
                encrypted_content.as_deref(),
                encrypted_type.as_deref(),
                encrypted_text_preview.as_deref(),
            ];
            let opened = embed_write::read::open_fields(handle.as_ref(), fields)
                .await
                .map_err(code)?;
            super::opened_fields_js(opened)
        }))
    }
}
