//! Worker-only export of the shared TOON decoder (`openmates_sdk::toon_decode`),
//! the Rust replacement for the web client's `decode(text, { strict: false })`
//! (embedStore.ts / chatSyncServiceHandlersAI.ts). Marshals only: JS passes the
//! TOON text and receives the `JSON.stringify`-identical result text.
use openmates_sdk::toon_decode::{self, ToonDecodeError};
use wasm_bindgen::{JsCast, prelude::*};

/// Decodes TOON text to its JSON text (byte-identical to `JSON.stringify` of
/// the TS non-strict decode). Runs only in the shared Rust core Worker.
///
/// # Errors
/// Rejects with the stable code `toon_decode_failed` for input the TS decoder
/// rejects, or `unavailable` outside a dedicated Worker.
#[wasm_bindgen]
pub fn toon_decode(text: &str) -> Result<String, JsValue> {
    js_sys::global()
        .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map_err(|_| JsValue::from_str("unavailable"))?;
    toon_decode::decode_to_json_text(text).map_err(|_| JsValue::from_str(ToonDecodeError::CODE))
}
