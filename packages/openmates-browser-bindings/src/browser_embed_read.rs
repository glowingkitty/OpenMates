//! Worker-only export of shared embed read logic (`openmates_sdk::embed_read`):
//! exact replay of legacy artifact version patches, the Rust replacement for the
//! web client's `applyVersionPatch` (embedVersionReconstruction.ts). Marshals only:
//! JS passes the opened text and receives the patched text.
use openmates_sdk::embed_read::patch;
use wasm_bindgen::{prelude::*, JsCast};

/// Applies one stored version `patch` to `content` (byte-identical to the TS replay).
///
/// # Errors
/// Rejects with the fixed TS refusal message (`Version patch ...`) for a patch the
/// TS replay refuses, or `unavailable` outside a dedicated Worker.
#[wasm_bindgen]
pub fn embed_apply_version_patch(content: &str, patch_text: &str) -> Result<String, JsValue> {
    js_sys::global()
        .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map_err(|_| JsValue::from_str("unavailable"))?;
    patch::apply_version_patch(content, patch_text).map_err(|e| JsValue::from_str(e.reason))
}
