//! WASM exports of the web chat import/export `transfer` unit. Marshalling only:
//! each export forwards JSON text to `openmates_sdk::web_transfer` and returns
//! its JSON text; a thrown string is the boundary's fixed `protocol` code.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_transfer;

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// `parseImportFile` routing by file name.
#[wasm_bindgen]
pub fn transfer_import_route(input: &str) -> Result<String, JsValue> {
    js(web_transfer::import_route_json(input))
}

/// Parses a `.json` export or a ZIP's `conversations.json` text.
#[wasm_bindgen]
pub fn transfer_parse_json_import(input: &str, text: &str) -> Result<String, JsValue> {
    js(web_transfer::parse_json_import_json(input, text))
}

/// Decides which ZIP entries the page must read.
#[wasm_bindgen]
pub fn transfer_zip_plan(input: &str) -> Result<String, JsValue> {
    js(web_transfer::zip_plan_json(input))
}

/// Validates a parsed OpenMates Export V1 `manifest.yml`.
#[wasm_bindgen]
pub fn transfer_openmates_manifest(input: &str) -> Result<String, JsValue> {
    js(web_transfer::openmates_manifest_json(input))
}

/// Builds Account Import V1 chats (ParsedImportChat) out of a parsed OpenMates Export V1 archive.
#[wasm_bindgen]
pub fn transfer_parse_openmates_archive(input: &str) -> Result<String, JsValue> {
    js(web_transfer::parse_openmates_archive_json(input))
}

/// Scan batch descriptors for the selected chats.
#[wasm_bindgen]
pub fn transfer_batch_plan(input: &str) -> Result<String, JsValue> {
    js(web_transfer::batch_plan_json(input))
}

/// `generateChatFilename`: dated, sanitized chat export filename.
#[wasm_bindgen]
pub fn transfer_export_filename(input: &str) -> Result<String, JsValue> {
    js(web_transfer::export_filename_json(input))
}

/// Whether a stored chat draft is cleartext or needs the page to decrypt it.
#[wasm_bindgen]
pub fn transfer_export_draft_kind(input: &str) -> Result<String, JsValue> {
    js(web_transfer::export_draft_kind_json(input))
}

/// `convertChatToYaml` over the page-resolved chat, messages and embeds.
#[wasm_bindgen]
pub fn transfer_export_yaml(input: &str) -> Result<String, JsValue> {
    js(web_transfer::export_yaml_json(input))
}

/// Entry layout, Markdown and names of a single or bulk chat ZIP download.
#[wasm_bindgen]
pub fn transfer_zip_chat_plan(input: &str) -> Result<String, JsValue> {
    js(web_transfer::zip_chat_plan_json(input))
}

/// Download names of a code-file download or code-files ZIP.
#[wasm_bindgen]
pub fn transfer_zip_code_files(input: &str) -> Result<String, JsValue> {
    js(web_transfer::zip_code_files_json(input))
}

/// Sanitized paths and zip name of an application project ZIP.
#[wasm_bindgen]
pub fn transfer_zip_application(input: &str) -> Result<String, JsValue> {
    js(web_transfer::zip_application_json(input))
}

/// Dated name of a bulk chat ZIP download.
#[wasm_bindgen]
pub fn transfer_zip_bulk_name(input: &str) -> Result<String, JsValue> {
    js(web_transfer::zip_bulk_name_json(input))
}

/// Ordered Account Export V1 archive entries with the secret guards applied.
#[wasm_bindgen]
pub fn transfer_account_export_archive(input: &str) -> Result<String, JsValue> {
    js(web_transfer::account_export_archive_json(input))
}
