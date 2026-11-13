//! Worker export for the shared `deckDocument` unit: one `DeckDocumentTable` per unit port,
//! wrapping the core's `DeckDocuments` handle table (`live-collab.core.one-shared-model`).
//! Marshalling only: JSON text and byte arrays in, the core's JSON / bytes out; a refusal
//! rejects with the core's stable error code string (e.g. `slides_slide_not_found`).
use openmates_sdk::client::shared_items::deck_handles::{DeckDocuments, DeckHandleError};
use wasm_bindgen::prelude::*;

fn js<T>(result: Result<T, DeckHandleError>) -> Result<T, JsValue> {
    result.map_err(|error| JsValue::from_str(error.code()))
}

/// Open deck replicas of one `deckDocument` unit port; freed when the port closes.
#[wasm_bindgen]
pub struct DeckDocumentTable {
    table: DeckDocuments,
}

#[wasm_bindgen]
impl DeckDocumentTable {
    /// An empty table.
    #[wasm_bindgen(constructor)]
    pub fn new() -> Self {
        Self {
            table: DeckDocuments::new(),
        }
    }

    /// `{"handle","view"}` JSON.
    pub fn open(&mut self, markup: &str) -> Result<String, JsValue> {
        js(self.table.open(markup))
    }

    /// `{"outcome","view"}` JSON for one `DeckOperation` JSON.
    pub fn apply(&mut self, handle: u32, operation_json: &str) -> Result<String, JsValue> {
        js(self.table.apply(handle, operation_json))
    }

    /// `{"changed","view"}` JSON.
    pub fn undo(&mut self, handle: u32) -> Result<String, JsValue> {
        js(self.table.undo(handle))
    }

    /// `{"changed","view"}` JSON.
    pub fn redo(&mut self, handle: u32) -> Result<String, JsValue> {
        js(self.table.redo(handle))
    }

    /// `{"view"}` JSON.
    pub fn view(&self, handle: u32) -> Result<String, JsValue> {
        js(self.table.view(handle))
    }

    /// Normalised slides markup.
    #[wasm_bindgen(js_name = toMarkup)]
    pub fn to_markup(&self, handle: u32) -> Result<String, JsValue> {
        js(self.table.to_markup(handle))
    }

    /// Yjs v1 state vector bytes.
    #[wasm_bindgen(js_name = stateVector)]
    pub fn state_vector(&self, handle: u32) -> Result<Vec<u8>, JsValue> {
        js(self.table.state_vector(handle))
    }

    /// Yjs v1 update bytes the holder of `state_vector` lacks.
    #[wasm_bindgen(js_name = encodeUpdateSince)]
    pub fn encode_update_since(
        &self,
        handle: u32,
        state_vector: &[u8],
    ) -> Result<Vec<u8>, JsValue> {
        js(self.table.encode_update_since(handle, state_vector))
    }

    /// Applies Yjs v1 update bytes; `{"view"}` JSON.
    #[wasm_bindgen(js_name = applyUpdate)]
    pub fn apply_update(&mut self, handle: u32, update: &[u8]) -> Result<String, JsValue> {
        js(self.table.apply_update(handle, update))
    }

    /// Drops the replica; `false` when the handle was not open.
    pub fn close(&mut self, handle: u32) -> bool {
        self.table.close(handle)
    }

    /// Number of open replicas (diagnostics).
    #[wasm_bindgen(getter)]
    pub fn size(&self) -> usize {
        self.table.len()
    }
}

impl Default for DeckDocumentTable {
    fn default() -> Self {
        Self::new()
    }
}
