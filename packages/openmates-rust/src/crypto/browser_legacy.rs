//! DedicatedWorker legacy-password primitive, not a login or wire protocol.
//! Rust retains version/base64/layout/length policy and every lifetime guard.
//! WebCrypto receives UTF-8 bytes, performs the unchanged PBKDF2 work factor,
//! and decrypts AES256-GCM with twelve-byte IV, appended128-bit tag, empty AAD.
//! Derived wrapping keys are nonextractable and never leave this primitive.
//! Scratch input copies and settled plaintext are erased on refusal/drop alike.
use super::*;
use js_sys::{Array, ArrayBuffer, Function, Object, Promise, Reflect, Uint8Array};
use std::{cell::{Cell, RefCell}, rc::Rc};
use wasm_bindgen::{JsCast, JsValue, closure::Closure};
use wasm_bindgen_futures::JsFuture;

// Bind the same once-owned callback to true/false without evaluating JS source
// or adding a generated inline snippet. Exactly one Promise branch consumes its
// Rust environment; its downstream promise holds undefined, never plaintext.
fn settle_legacy_primitive(operation: &Promise, settle: &JsValue) -> Result<Promise> {
    let bind = Reflect::get(settle, &JsValue::from_str("bind")).map_err(|_| Error::Crypto)?
        .dyn_into::<Function>().map_err(|_| Error::Crypto)?;
    let success = bind.call2(settle, &JsValue::UNDEFINED, &JsValue::TRUE).map_err(|_| Error::Crypto)?;
    let failure = bind.call2(settle, &JsValue::UNDEFINED, &JsValue::FALSE).map_err(|_| Error::Crypto)?;
    let then = Reflect::get(operation, &JsValue::from_str("then")).map_err(|_| Error::Crypto)?
        .dyn_into::<Function>().map_err(|_| Error::Crypto)?;
    then.call2(operation, &success, &failure).map_err(|_| Error::Crypto)?
        .dyn_into::<Promise>().map_err(|_| Error::Crypto)
}
struct Scratch(Uint8Array);
impl Scratch {
    fn new(bytes: &[u8]) -> Self { Self(Uint8Array::from(bytes)) }
}
impl Drop for Scratch { fn drop(&mut self) { self.0.fill(0, 0, self.0.length()); } }
struct Output { live: Cell<bool>, result: RefCell<Option<Result<Zeroizing<Vec<u8>>>>> }
struct OutputGuard(Rc<Output>);
impl Drop for OutputGuard {
    fn drop(&mut self) { self.0.live.set(false); self.0.result.borrow_mut().take(); }
}
fn object(values: &[(&str, JsValue)]) -> Result<Object> {
    let output = Object::new();
    for (key, value) in values { Reflect::set(&output, &JsValue::from_str(key), value).map_err(|_| Error::Crypto)?; }
    Ok(output)
}
fn call(subtle: &JsValue, method: &str, args: &[JsValue]) -> Result<Promise> {
    let function = Reflect::get(subtle, &JsValue::from_str(method)).map_err(|_| Error::Crypto)?
        .dyn_into::<Function>().map_err(|_| Error::Crypto)?;
    let array = Array::new(); for value in args { array.push(value); }
    function.apply(subtle, &array).map_err(|_| Error::Crypto)?.dyn_into::<Promise>().map_err(|_| Error::Crypto)
}
fn worker_subtle() -> Result<JsValue> {
    js_sys::global().dyn_into::<web_sys::DedicatedWorkerGlobalScope>().map_err(|_| Error::Forbidden)?;
    let crypto = Reflect::get(&js_sys::global(), &JsValue::from_str("crypto")).map_err(|_| Error::Crypto)?;
    Reflect::get(&crypto, &JsValue::from_str("subtle")).map_err(|_| Error::Crypto)
}
/// The sole asynchronous port. No caller-supplied algorithm/KDF/output policy.
/// `current` is the ORIGINAL fresh-login scope, not a newly captured key label.
pub(crate) async fn unwrap(password: &str, version: u8, ciphertext: &str, salt: &str, iv: &str,
    current: impl Fn() -> Result<()>) -> Result<Key> {
    current()?;
    if !matches!(version, 0 | 1) { return Err(Error::Crypto); }
    let salt = STANDARD.decode(salt).map_err(|_| Error::Crypto)?;
    let envelope = password_master_envelope(ciphertext, iv)?;
    let subtle = worker_subtle()?;
    let password_bytes = Scratch::new(password.as_bytes());
    let usages = Array::new(); usages.push(&JsValue::from_str("deriveKey"));
    current()?;
    let imported = call(&subtle, "importKey", &[JsValue::from_str("raw"), password_bytes.0.clone().into(),
        JsValue::from_str("PBKDF2"), JsValue::FALSE, usages.into()]);
    drop(password_bytes); // invocation snapshots input, including synchronous errors
    let imported = JsFuture::from(imported?).await;
    current()?; worker_subtle()?;
    let imported = imported.map_err(|_| Error::Crypto)?;
    let salt_bytes = Scratch::new(&salt);
    let params = object(&[("name", JsValue::from_str("PBKDF2")), ("salt", salt_bytes.0.clone().into()),
        ("iterations", JsValue::from_f64(LEGACY_PASSWORD_ITERATIONS.into())), ("hash", JsValue::from_str("SHA-256"))])?;
    let algorithm = object(&[("name", JsValue::from_str("AES-GCM")), ("length", JsValue::from_f64(256.0))])?;
    let usages = Array::new(); usages.push(&JsValue::from_str("decrypt"));
    current()?;
    let derived = call(&subtle, "deriveKey", &[params.into(), imported, algorithm.into(), JsValue::FALSE, usages.into()]);
    drop(salt_bytes);
    let derived = JsFuture::from(derived?).await;
    current()?; worker_subtle()?;
    let derived = derived.map_err(|_| Error::Crypto)?;
    let nonce = Scratch::new(&envelope.iv);
    let input = Scratch::new(&envelope.ciphertext);
    let params = object(&[("name", JsValue::from_str("AES-GCM")), ("iv", nonce.0.clone().into()),
        ("tagLength", JsValue::from_f64(128.0))])?;
    current()?;
    let operation = call(&subtle, "decrypt", &[params.into(), derived, input.0.clone().into()]);
    drop(input); drop(nonce);
    let operation = operation?;
    let output = Rc::new(Output { live: Cell::new(true), result: RefCell::new(None) });
    let _guard = OutputGuard(output.clone());
    let receiving = output.clone();
    let settle = Closure::once_into_js(move |success: bool, value: JsValue| {
        let result = if success {
            value.dyn_into::<ArrayBuffer>().map_err(|_| Error::Crypto).map(|buffer| {
                let view = Uint8Array::new(&buffer);
                let owned = receiving.live.get().then(|| Zeroizing::new(view.to_vec()));
                view.fill(0, 0, view.length()); owned
            })
        } else { Err(Error::Crypto) };
        if receiving.live.get() {
            *receiving.result.borrow_mut() = Some(result.and_then(|value| value.ok_or(Error::Crypto)));
        }
    });
    let settled = JsFuture::from(settle_legacy_primitive(&operation, &settle)?).await;
    current()?; worker_subtle()?;
    settled.map_err(|_| Error::Crypto)?;
    let raw = output.result.borrow_mut().take().ok_or(Error::Crypto)??;
    let master = password_master_from_plaintext(&raw)?;
    current()?;
    Ok(master)
}
