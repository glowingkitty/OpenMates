//! Worker-only glue for image revisions (`images-generate.revision.*`): child
//! revision writes and message-scoped versions of the shared core
//! (`openmates_sdk::client::embed_write::{revision, pinned}`). Marshalling only;
//! every decision is in Rust. Errors reject with the stable code strings of
//! `browser_embed_write.rs` (`embed_revision_*`, `embed_version_unavailable`, ...).
use super::{BrowserEmbedWriter, array, code, now_ms, now_seconds, parse, proto};
use openmates_sdk::client::embed_write::{
    MessageParents, StreamedEmbedData, history::EncryptedDiffRow, pinned,
};
use wasm_bindgen::prelude::*;

fn rows(text: &str) -> Result<Vec<EncryptedDiffRow>, JsValue> {
    serde_json::from_str(text).map_err(|_| JsValue::from_str("invalid"))
}

#[wasm_bindgen]
impl BrowserEmbedWriter {
    /// `send_embed_data` carrying `payload.revision`. `stored_head_json` is the
    /// child's local `embeds` row (`undefined` when absent), `existing_rows_json`
    /// its local `embed_diffs` rows (JSON array). Resolves to `PreparedEmbedWrite`
    /// JSON with `child_revision.steps` to run in order.
    pub fn prepare_child_revision(
        &self,
        payload_json: &str,
        stored_head_json: Option<String>,
        existing_rows_json: &str,
    ) -> Result<js_sys::Promise, JsValue> {
        let data = StreamedEmbedData::from_value(parse(payload_json)?).map_err(code)?;
        let head = stored_head_json.as_deref().map(parse).transpose()?;
        let existing = rows(existing_rows_json)?;
        let planned = self
            .session
            .borrow_mut()
            .plan_child_revision(data, head.as_ref(), existing)
            .map_err(code)?;
        Ok(wasm_bindgen_futures::future_to_promise(async move {
            let prepared = planned.finish(now_ms()).await.map_err(code)?;
            Ok(JsValue::from_str(
                &serde_json::to_string(&prepared).map_err(proto)?,
            ))
        }))
    }
    /// After `embed_diff_conflict` on a step: `local_row_json` is that step's
    /// `local_row`, `page_json` the bounded-v1 canonical page of its version.
    /// Returns the canonical `EncryptedDiffRow` JSON to store locally.
    pub fn adopt_child_revision_row(
        &self,
        local_row_json: &str,
        page_json: &str,
    ) -> Result<String, JsValue> {
        let local: EncryptedDiffRow =
            serde_json::from_str(local_row_json).map_err(|_| JsValue::from_str("invalid"))?;
        let page = parse(page_json)?;
        let adopted = self
            .session
            .borrow()
            .adopt_child_revision_row(&local, &page, now_seconds())
            .map_err(code)?;
        serde_json::to_string(&adopted).map_err(proto)
    }
    /// Plaintext content (TOON) of version `version` of `embed_id`, from its
    /// stored head row and local `embed_diffs` rows (JSON array).
    pub fn embed_version_content(
        &self,
        embed_id: &str,
        version: f64,
        head_json: &str,
        rows_json: &str,
    ) -> Result<String, JsValue> {
        if version.fract() != 0.0 || version < 1.0 {
            return Err(JsValue::from_str("invalid"));
        }
        let (head, rows) = (parse(head_json)?, array(rows_json)?);
        let content = self
            .session
            .borrow()
            .embed_version_content(embed_id, version as i64, &head, &rows)
            .map_err(code)?;
        Ok(content.as_str().to_owned())
    }
    /// A fetched bounded-v1 page of `embed_id` (`page_json`), validated with
    /// the head's key owner, as local `embed_diffs` rows (JSON array, each
    /// `server_confirmed: true`) to store.
    pub fn cache_version_page(
        &self,
        embed_id: &str,
        head_json: &str,
        page_json: &str,
    ) -> Result<String, JsValue> {
        let (head, page) = (parse(head_json)?, parse(page_json)?);
        let rows = self
            .session
            .borrow()
            .cache_version_page(embed_id, &head, &page, now_seconds())
            .map_err(code)?;
        serde_json::to_string(&rows).map_err(proto)
    }
}

/// Head version of a stored `embeds` row (`version_number`, missing means 1).
#[wasm_bindgen]
pub fn embed_head_version(stored_head_json: &str) -> Result<f64, JsValue> {
    Ok(pinned::head_version(&parse(stored_head_json)?).map_err(code)? as f64)
}
/// True when `incoming_json` (a synced or fetched server row) would lower the
/// version of the stored child head `stored_head_json`; the shell keeps the
/// stored row then.
#[wasm_bindgen]
pub fn embed_synced_head_regresses(
    stored_head_json: &str,
    incoming_json: &str,
) -> Result<bool, JsValue> {
    pinned::synced_head_regresses(&parse(stored_head_json)?, &parse(incoming_json)?).map_err(code)
}
/// `pinned_embeds` of one decrypted `app_skill_use` parent content:
/// JSON `[{embed_id, version, embed_ref?, previous_version?}]`.
#[wasm_bindgen]
pub fn embed_pinned_embeds(parent_content: &str) -> Result<String, JsValue> {
    serde_json::to_string(&pinned::pinned_embeds(parent_content).map_err(code)?).map_err(proto)
}
/// `messages_json`: `[{message_id, parent_contents: [toon]}]` in chat order.
/// Returns `[{message_id, version, pinned_here}]` for `embed_id`.
#[wasm_bindgen]
pub fn embed_versions_by_message(messages_json: &str, embed_id: &str) -> Result<String, JsValue> {
    let messages: Vec<MessageParents> =
        serde_json::from_str(messages_json).map_err(|_| JsValue::from_str("invalid"))?;
    serde_json::to_string(&pinned::versions_by_message(&messages, embed_id).map_err(code)?)
        .map_err(proto)
}
