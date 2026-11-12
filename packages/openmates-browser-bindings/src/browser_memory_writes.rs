//! Worker exports of assistant Memory writes (crypto unit, `memory*` ops).
//! Marshals `openmates_sdk::client::memory_write_job_bridge` (sans-IO job
//! driver), `memory_write_jobs::prepare_memory_undo` and the undone marker;
//! the page performs only the returned IO effects. Master-key work runs on the
//! page's structured-cloned, non-extractable master CryptoKey. Rejections are
//! the core's stable lowercase codes (`rule_changed`, ...); no Memory text,
//! key or ciphertext is logged.
use crate::browser_crypto::BrowserMasterCrypto;
use openmates_sdk::client::memory_write_job_bridge::{MemoryJobDesk, MemoryJobDriver, MemoryJobEffect};
use openmates_sdk::client::memory_write_jobs::{
    MemoryUndoOutcome, build_memory_write_undone_event, memory_write_undone_message_id,
    prepare_memory_undo,
};
use openmates_sdk::client::recommendations::ContextEntryHistoryEvent;
use openmates_sdk::crypto::master::{MasterCapability, MasterCrypto};
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::rc::Rc;
use wasm_bindgen::prelude::*;
use web_sys::CryptoKey;

thread_local! {
    // One shared Worker realm serves every tab; job state is per chat inside the desk.
    static DESK: RefCell<MemoryJobDesk> = RefCell::new(MemoryJobDesk::default());
    static DRIVERS: RefCell<HashMap<u32, MemoryJobDriver>> = RefCell::new(HashMap::new());
    static NEXT: Cell<u32> = const { Cell::new(1) };
}

fn code(value: &str) -> JsValue {
    JsValue::from_str(value)
}

fn master(key: CryptoKey) -> Result<MasterCapability, JsValue> {
    let port: Rc<dyn MasterCrypto> =
        Rc::new(BrowserMasterCrypto::new(key).map_err(|_| code("rule_settings_unavailable"))?);
    Ok(MasterCapability::from_browser_port(port))
}

fn event_of(event_json: &str) -> Result<ContextEntryHistoryEvent, JsValue> {
    serde_json::from_str(event_json).map_err(|_| code("rule_not_undoable"))
}

/// Await the driver's next effect: `{done:{frames}}`, or `{token, effect}` to answer
/// with [`memory_job_resume`].
async fn step(mut driver: MemoryJobDriver) -> Result<String, JsValue> {
    let effect = driver.next().await.map_err(|_| code("cancelled"))?;
    if let MemoryJobEffect::Done { frames } = effect {
        return Ok(json!({"done": {"frames": frames}}).to_string());
    }
    let token = NEXT.with(|next| {
        let token = next.get();
        next.set(token.wrapping_add(1).max(1));
        token
    });
    DRIVERS.with(|drivers| drivers.borrow_mut().insert(token, driver));
    Ok(json!({"token": token, "effect": effect}).to_string())
}

/// Handle one inbound `memory_write_job_*` frame. `settings` is the profile's
/// current `encrypted_settings`. Resolves with the first step (see [`step`]).
#[wasm_bindgen(js_name = memoryJobFrame)]
pub async fn memory_job_frame(
    master_key: CryptoKey,
    settings: Option<String>,
    kind: String,
    event_json: String,
    now_s: f64,
) -> Result<String, JsValue> {
    let event: Value = serde_json::from_str(&event_json).map_err(|_| code("protocol"))?;
    if !(now_s.is_finite() && now_s >= 0.0) {
        return Err(code("protocol"));
    }
    let master = master(master_key)?;
    // Whole seconds: the protocol's `expires_at` is integral.
    let (run, driver) = DESK.with(|desk| {
        desk.borrow_mut()
            .start(master, settings, &kind, event, now_s as u64)
    });
    wasm_bindgen_futures::spawn_local(run);
    step(driver).await
}

/// Answer the effect of `token` (`outcome` null = success, else an error code)
/// and resolve with the next step.
#[wasm_bindgen(js_name = memoryJobResume)]
pub async fn memory_job_resume(token: u32, outcome: Option<String>) -> Result<String, JsValue> {
    let mut driver = DRIVERS
        .with(|drivers| drivers.borrow_mut().remove(&token))
        .ok_or_else(|| code("protocol"))?;
    driver.resume(outcome).map_err(|_| code("protocol"))?;
    step(driver).await
}

/// Forget every job state and pending driver (logout, account switch).
#[wasm_bindgen(js_name = memoryJobsClear)]
pub fn memory_jobs_clear() {
    DRIVERS.with(|drivers| drivers.borrow_mut().clear());
    DESK.with(|desk| desk.borrow_mut().clear());
}

/// Undo of the assistant write `event_json` announces: resolves
/// `{outcome:"deleted"|"restored", encrypted_settings, marker_id, marker}` for
/// the page to post and to store as the undone marker; rejects with the core
/// code (`rule_changed`, `rule_not_found`, `rule_not_undoable`, ...).
#[wasm_bindgen(js_name = memoryUndoPrepare)]
pub async fn memory_undo_prepare(
    master_key: CryptoKey,
    settings: Option<String>,
    event_json: String,
    now_s: f64,
) -> Result<String, JsValue> {
    let event = event_of(&event_json)?;
    let master = master(master_key)?;
    let (outcome, prepared) = prepare_memory_undo(&master, settings.as_deref(), &event)
        .await
        .map_err(|error| code(error.code()))?;
    let marker = build_memory_write_undone_event(&event, now_s as i64)
        .map_err(|error| code(error.code()))?;
    let job = event
        .undo
        .as_ref()
        .map(|undo| undo.job_id.as_str())
        .ok_or_else(|| code("rule_not_undoable"))?;
    Ok(json!({
        "outcome": match outcome {
            MemoryUndoOutcome::Deleted => "deleted",
            MemoryUndoOutcome::Restored => "restored",
        },
        "encrypted_settings": prepared.encrypted_settings,
        "marker_id": memory_write_undone_message_id(job),
        "marker": marker,
    })
    .to_string())
}
