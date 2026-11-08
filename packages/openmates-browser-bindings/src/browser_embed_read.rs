//! Worker-only export of shared embed read logic (`openmates_sdk::embed_read`):
//! exact replay of legacy artifact version patches, the Rust replacement for the
//! web client's `applyVersionPatch` (embedVersionReconstruction.ts). Marshals only:
//! JS passes the opened text and receives the patched text.
//! Also serves the canonical embed sender decisions (`embed_read::run_json`, op
//! `decideSender` of the embedData unit) as JSON text in, JSON text out.
use openmates_sdk::embed_read::{self, admission, patch};
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

/// Decides whether an inbound embed event may be applied to a stored embed
/// (`embed_read::admission`; same outcome as TS `isEmbedEventAdmitted`).
///
/// # Errors
/// Rejects with `unavailable` outside a dedicated Worker.
#[wasm_bindgen]
pub fn embed_event_admitted(
    current_status: &str,
    incoming_status: Option<String>,
    current_version: Option<f64>,
    incoming_version: Option<f64>,
    version_exempt: bool,
) -> Result<bool, JsValue> {
    js_sys::global()
        .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map_err(|_| JsValue::from_str("unavailable"))?;
    Ok(admission::is_embed_event_admitted(&admission::EmbedEventFacts {
        current_status,
        incoming_status: incoming_status.as_deref(),
        current_version,
        incoming_version,
        version_exempt,
    }))
}

/// Runs one canonical embed sender decision (`embed_read::run_json`): `input`
/// and the answer are JSON text (no key bytes or plaintext cross).
///
/// # Errors
/// Rejects with `embed_sender:<reason>` for an unknown op or malformed document,
/// or `unavailable` outside a dedicated Worker.
#[wasm_bindgen]
pub fn embed_sender_decide(op: &str, input: &str) -> Result<String, JsValue> {
    js_sys::global()
        .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map_err(|_| JsValue::from_str("unavailable"))?;
    embed_read::run_json(op, input).map_err(|reason| JsValue::from_str(&format!("embed_sender:{reason}")))
}
