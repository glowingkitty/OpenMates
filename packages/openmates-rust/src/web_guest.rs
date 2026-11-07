//! Guest (anonymous free-usage chat) promotion policy for the shared Rust core
//! Worker `crypto` unit (share-guest-crypto lane).
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/surfaces/sdk#sdk.encryption.local-only
//!
//! Mirrors the pure decisions of `anonymousChatPromotionService.ts`: which
//! anonymous messages are promotable after signup, which are dropped (system
//! rows), which local rows need a "synced" re-save, and the version/timestamp
//! numbers of the promoted chat row. Wrapping the per-chat key with the tab
//! session key is the existing master-key format (base64(IV || ciphertext || tag))
//! and runs on the existing `masterEncrypt`/`masterDecrypt` crypto ops, so no
//! second wrap format exists. Key bytes never enter this module. Parity with
//! the TS functions is proven by `web_guest_ts_vectors.json`
//! (`guestPromotionVectors.test.ts`).

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// One locally stored anonymous message row, reduced to the fields the policy reads.
#[derive(Deserialize)]
struct GuestMessage {
    role: Option<String>,
    status: Option<String>,
    content: Option<Value>,
    created_at: Option<i64>,
}

/// Chat-row timestamps the plan falls back to when no message is promotable.
#[derive(Deserialize)]
struct GuestChat {
    created_at: Option<i64>,
    updated_at: Option<i64>,
}

#[derive(Deserialize)]
struct PlanInput {
    chat: GuestChat,
    messages: Vec<GuestMessage>,
}

/// Promotion decisions for one anonymous chat; indexes refer to the input message order.
#[derive(Serialize, Debug, PartialEq, Eq)]
pub struct PromotionPlan {
    /// Messages that are uploaded (`isPromotableMessage`).
    pub promotable: Vec<usize>,
    /// System rows deleted after promotion.
    pub delete: Vec<usize>,
    /// Promotable rows whose local status is not yet `synced`.
    pub resave: Vec<usize>,
    /// `messages_v` of the promoted chat.
    pub messages_v: usize,
    /// `created_at` of the promoted chat row (chat value, else first promotable message).
    pub created_at: Option<i64>,
    /// `updated_at` and `last_edited_overall_timestamp` (last promotable message, else chat).
    pub last_edited: Option<i64>,
}

/// JS `String.prototype.trim` whitespace set, which differs from Rust's `char::is_whitespace`.
pub(crate) fn is_js_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{b}' | '\u{c}' | '\r' | ' ' | '\u{a0}' | '\u{1680}'
            | '\u{2000}'..='\u{200a}' | '\u{2028}' | '\u{2029}' | '\u{202f}' | '\u{205f}'
            | '\u{3000}' | '\u{feff}'
    )
}

fn is_promotable(message: &GuestMessage) -> bool {
    message.status.as_deref() != Some("failed")
        && message.role.as_deref() != Some("system")
        && matches!(&message.content, Some(Value::String(text)) if !text.trim_matches(is_js_space).is_empty())
}

/// Plans the promotion of one anonymous chat from its chat row and message rows.
///
/// # Errors
/// Returns the JSON parse error text for a malformed input document.
pub fn promotion_plan_json(input: &str) -> Result<String, String> {
    let input: PlanInput = serde_json::from_str(input).map_err(|e| e.to_string())?;
    let promotable: Vec<usize> = (0..input.messages.len())
        .filter(|&i| is_promotable(&input.messages[i]))
        .collect();
    let delete = (0..input.messages.len())
        .filter(|&i| input.messages[i].role.as_deref() == Some("system"))
        .collect();
    // TS `else if`: a system row is deleted, never re-saved.
    let resave = promotable
        .iter()
        .copied()
        .filter(|&i| {
            input.messages[i].role.as_deref() != Some("system")
                && input.messages[i].status.as_deref() != Some("synced")
        })
        .collect();
    let first = promotable.first().and_then(|&i| input.messages[i].created_at);
    let last = promotable.last().and_then(|&i| input.messages[i].created_at);
    let plan = PromotionPlan {
        messages_v: promotable.len(),
        created_at: input.chat.created_at.or(first),
        last_edited: last.or(input.chat.updated_at),
        promotable,
        delete,
        resave,
    };
    serde_json::to_string(&plan).map_err(|e| e.to_string())
}
