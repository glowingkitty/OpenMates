//! WASM exports of the web IndexedDB row-policy `persist` unit. Marshalling only:
//! each export forwards JSON text to `openmates_sdk::web_persist` and returns its
//! JSON text; a thrown string is the boundary's fixed `protocol` code.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use wasm_bindgen::prelude::*;

use openmates_sdk::web_persist::{cache_policy, chat_policy, message_policy};

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// `shouldUpdateMessage` over stored/incoming message pairs.
#[wasm_bindgen]
pub fn persist_message_should_update(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::should_update_json(input_json))
}

/// The update and fill-encrypted-fields checks of `saveMessage`.
#[wasm_bindgen]
pub fn persist_message_save_decision(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::save_decision_json(input_json))
}

/// `findContentDuplicate` over the chat's stored messages.
#[wasm_bindgen]
pub fn persist_message_content_duplicate(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::content_duplicate_json(input_json))
}

/// `isSafeToEvictMessage` over stored rows.
#[wasm_bindgen]
pub fn persist_message_safe_to_evict(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::safe_to_evict_json(input_json))
}

/// `planDuplicateCleanup`: message ids whose stored copy `cleanupDuplicateMessages` deletes.
#[wasm_bindgen]
pub fn persist_message_duplicate_cleanup(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::duplicate_cleanup_json(input_json))
}

macro_rules! persist_export {
    ($($(#[$doc:meta])* $export:ident => $function:path;)*) => {
        $(
            $(#[$doc])*
            #[wasm_bindgen]
            pub fn $export(input_json: &str) -> Result<String, JsValue> {
                js($function(input_json))
            }
        )*
    };
}

persist_export! {
    /// `planMessageWindow`: limit, direction, ranges and anchor handling of a window read.
    persist_window_plan => cache_policy::window_plan_json;
    /// `windowResultMeta`: has-more flags and cursors of a window result.
    persist_window_result_meta => cache_policy::window_result_meta_json;
    /// `buildWindowPageRecord`: the cache record of a viewed window.
    persist_window_page_record => cache_policy::window_page_record_json;
    /// `planPageEviction`: eviction candidates and how many pages must go.
    persist_evict_plan => cache_policy::evict_plan_json;
    /// `planPageDeletion`: messages to delete per evicted page.
    persist_evict_delete_plan => cache_policy::evict_delete_plan_json;
    /// Whether every stored message of a cached page is safe to evict.
    persist_page_confirmed => cache_policy::page_confirmed_json;
    /// The offline cache budget check throttle.
    persist_budget_throttle => cache_policy::budget_throttle_json;
    /// The offline cache target and whether usage calls for trimming.
    persist_budget_target => cache_policy::budget_target_json;
    /// Pages the budget trim visits.
    persist_budget_candidates => cache_policy::budget_candidates_json;
    /// Whether a chat has surplus pages to trim.
    persist_budget_chat_step => cache_policy::budget_chat_step_json;
    /// Stop/continue decision after a budget eviction.
    persist_budget_after => cache_policy::budget_after_json;
    /// Next step of the quota-recovery retry flow.
    persist_quota_step => cache_policy::quota_step_json;
    /// Page size of the chat catalog cursor.
    persist_chats_page_size => cache_policy::chats_page_size_json;
    /// Stored defaults of a chat row.
    persist_chat_defaults => chat_policy::chat_defaults_json;
    /// Whether a chat is the expected keyless draft-only sync shell.
    persist_keyless_draft_only => chat_policy::keyless_draft_only_json;
    /// Candidate-key list after remembering a rejected key.
    persist_candidate_keys => chat_policy::candidate_keys_json;
    /// Merge of draft fields into the latest chat row.
    persist_draft_merge => chat_policy::draft_merge_json;
    /// Whether a Team draft intent may be recorded, and its fields.
    persist_team_draft_intent => chat_policy::team_draft_intent_json;
}
