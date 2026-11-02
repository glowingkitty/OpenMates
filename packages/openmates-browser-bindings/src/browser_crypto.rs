//! Worker-only AES primitive. The SDK owns envelopes, identity/admission,
//! cancellation, capability generation and storage policy. This resource is
//! never serialized, inspected for raw bytes, or represented by a dummy key.
use js_sys::{ArrayBuffer, Object, Reflect, Uint8Array};
use openmates_sdk::{
    Error, Result,
    crypto::master::{MasterCrypto, MasterCryptoFuture},
};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};
use wasm_bindgen::{JsCast, JsValue, closure::Closure};
use wasm_bindgen_futures::JsFuture;
use web_sys::{Crypto, CryptoKey, DedicatedWorkerGlobalScope, SubtleCrypto};
use zeroize::Zeroizing;

// Exactly one fulfillment/rejection callback consumes its Rust environment.
// The settled promise resolves undefined; it never retains a plaintext result.
#[wasm_bindgen::prelude::wasm_bindgen(inline_js = "
export function settlePrimitive(operation, settle) {
  return operation.then(value => { settle(value, true); }, () => { settle(undefined, false); });
}
")]
extern "C" {
    #[wasm_bindgen::prelude::wasm_bindgen(js_name = settlePrimitive)]
    fn settle_primitive(operation: &js_sys::Promise, settle: &JsValue) -> js_sys::Promise;
}
struct PrimitiveOutput {
    live: Cell<bool>,
    result: RefCell<Option<Result<Zeroizing<Vec<u8>>>>>,
}
struct OutputGuard(Rc<PrimitiveOutput>);
impl Drop for OutputGuard {
    fn drop(&mut self) {
        self.0.live.set(false);
        // A copied result is wiped even if its consumer stops after settlement.
        self.0.result.borrow_mut().take();
    }
}

pub(crate) struct BrowserMasterCrypto {
    key: CryptoKey,
    subtle: SubtleCrypto,
}

fn worker_subtle() -> Result<SubtleCrypto> {
    let global = js_sys::global();
    if !global.is_instance_of::<DedicatedWorkerGlobalScope>() {
        return Err(Error::Crypto);
    }
    let crypto = Reflect::get(&global, &JsValue::from_str("crypto"))
        .map_err(|_| Error::Crypto)?
        .dyn_into::<Crypto>()
        .map_err(|_| Error::Crypto)?;
    Ok(crypto.subtle())
}

impl BrowserMasterCrypto {
    /// Accept the structured-cloned key itself, preserving extractability and
    /// usages. Extractable and nonextractable keys follow the same operation.
    pub(crate) fn new(key: CryptoKey) -> Result<Self> {
        let subtle = worker_subtle()?;
        if !key.is_instance_of::<CryptoKey>() {
            return Err(Error::Crypto);
        }
        let algorithm = key.algorithm().map_err(|_| Error::Crypto)?;
        let name =
            Reflect::get(&algorithm, &JsValue::from_str("name")).map_err(|_| Error::Crypto)?;
        let length =
            Reflect::get(&algorithm, &JsValue::from_str("length")).map_err(|_| Error::Crypto)?;
        let usages = key.usages();
        if key.type_() != "secret"
            || name.as_string().as_deref() != Some("AES-GCM")
            || length.as_f64() != Some(256.0)
            || !usages
                .iter()
                .any(|value| value.as_string().as_deref() == Some("encrypt"))
            || !usages
                .iter()
                .any(|value| value.as_string().as_deref() == Some("decrypt"))
        {
            return Err(Error::Crypto);
        }
        Ok(Self { key, subtle })
    }

    async fn crypt(
        &self,
        iv: &[u8; 12],
        input: &[u8],
        encrypt: bool,
    ) -> Result<Zeroizing<Vec<u8>>> {
        worker_subtle()?;
        // Empty AAD is intentional. Rust supplies the nonce and owns all
        // framing/fallback/length policy; WebCrypto returns ciphertext || tag.
        let params = Object::new();
        let nonce = Uint8Array::from(iv.as_slice());
        for (name, value) in [
            ("name", JsValue::from_str("AES-GCM")),
            ("iv", nonce.clone().into()),
            ("tagLength", JsValue::from_f64(128.0)),
        ] {
            Reflect::set(&params, &JsValue::from_str(name), &value).map_err(|_| Error::Crypto)?;
        }
        let scratch = Uint8Array::from(input);
        let operation = if encrypt {
            self.subtle
                .encrypt_with_object_and_js_u8_array(&params, &self.key, &scratch)
        } else {
            self.subtle
                .decrypt_with_object_and_js_u8_array(&params, &self.key, &scratch)
        };
        // WebCrypto takes its input snapshot during invocation. Wipe the
        // adapter-owned JS copy on success and synchronous refusal alike.
        scratch.fill(0, 0, scratch.length());
        let operation = operation.map_err(|_| Error::Crypto)?;
        let output = Rc::new(PrimitiveOutput {
            live: Cell::new(true),
            result: RefCell::new(None),
        });
        let _guard = OutputGuard(output.clone());
        let receiving = output.clone();
        let settle = Closure::once_into_js(move |value: JsValue, success: bool| {
            let result = if success {
                value
                    .dyn_into::<ArrayBuffer>()
                    .map_err(|_| Error::Crypto)
                    .map(|buffer| {
                        let view = Uint8Array::new(&buffer);
                        let owned = receiving.live.get().then(|| Zeroizing::new(view.to_vec()));
                        // Runs on browser settlement even after the Rust consumer
                        // future was dropped; the JS Promise contains no copy.
                        view.fill(0, 0, view.length());
                        owned
                    })
            } else {
                Err(Error::Crypto)
            };
            if receiving.live.get() {
                *receiving.result.borrow_mut() =
                    Some(result.and_then(|value| value.ok_or(Error::Crypto)));
            }
        });
        JsFuture::from(settle_primitive(&operation, &settle))
            .await
            .map_err(|_| Error::Crypto)?;
        worker_subtle()?;
        let result = output.result.borrow_mut().take().ok_or(Error::Crypto)?;
        result
    }
}

impl MasterCrypto for BrowserMasterCrypto {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plaintext: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(self.crypt(iv, plaintext, true))
    }
    fn decrypt<'a>(
        &'a self,
        iv: &'a [u8; 12],
        ciphertext_and_tag: &'a [u8],
    ) -> MasterCryptoFuture<'a> {
        Box::pin(self.crypt(iv, ciphertext_and_tag, false))
    }
}

#[cfg(test)]
#[path = "browser_crypto_tests.rs"]
mod tests;
