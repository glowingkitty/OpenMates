//! Portable WebAssembly entry for the npm SDK (Node, Deno, Bun, edge, browsers).
//! Same JSON contracts and fixed error envelope as the Node-API entry: a thrown
//! JS `Error` carries `BindingError::json()` as its message. Stateless shared
//! operations only in this slice; no credentials, storage or network.
use crate::BindingError;
use wasm_bindgen::prelude::*;

fn error(error: BindingError) -> JsError {
    JsError::new(&error.json())
}

#[wasm_bindgen(js_name = "reconstructEmbedVersion")]
pub fn reconstruct_embed_version(input_json: String) -> Result<String, JsError> {
    crate::reconstruct_embed_version_json(input_json).map_err(error)
}

#[wasm_bindgen(js_name = "privacy")]
pub fn privacy(input_json: String) -> Result<String, JsError> {
    crate::privacy_json(input_json).map_err(error)
}

#[wasm_bindgen(js_name = "taskOrder")]
pub fn task_order(input_json: String) -> Result<String, JsError> {
    crate::sort_tasks_json(input_json).map_err(error)
}
