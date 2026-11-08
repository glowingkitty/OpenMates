//! Turn-token ref merge of the web connected-account token broker client
//! (`connectedAccountTokenBrokerService.ts` `createConnectedAccountTurnTokenRefs`),
//! shared Rust core.
//!
//! The page posts the token-ref inputs (with refresh-token envelopes) to the
//! broker itself and passes this module only the inputs' non-secret fields plus
//! the broker response; the opaque turn-token refs are returned unchanged.
use serde::Serialize;
use serde_json::{json, Value};

use super::js::{coalesce, prop, strict_eq};
use super::Fail;

#[derive(Serialize)]
struct TurnTokenRef {
    #[serde(skip_serializing_if = "Option::is_none")]
    connected_account_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    app_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    provider_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    turn_token_ref: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    expires_at: Option<Value>,
    allowed_actions: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    action_scope: Option<Value>,
}

fn merge(inputs: &[Value], payload: &Value) -> Result<Option<Vec<TurnTokenRef>>, Fail> {
    let Some(Value::Array(refs)) = prop(Some(payload), "refs")? else {
        return Ok(None);
    };
    let mut merged = Vec::with_capacity(refs.len());
    for broker_ref in &refs {
        let account = prop(Some(broker_ref), "connected_account_id")?;
        let app = prop(Some(broker_ref), "app_id")?;
        // First input for the same account and app (`Array.prototype.find`).
        let input = inputs.iter().find(|item| {
            strict_eq(item.get("connected_account_id"), account.as_ref()) && strict_eq(item.get("app_id"), app.as_ref())
        });
        let input_field = |key: &str| input.and_then(|item| item.get(key).cloned());
        merged.push(TurnTokenRef {
            connected_account_id: account.clone(),
            app_id: app.clone(),
            provider_id: coalesce(prop(Some(broker_ref), "provider_id")?, || input_field("provider_id")),
            turn_token_ref: prop(Some(broker_ref), "turn_token_ref")?,
            expires_at: prop(Some(broker_ref), "expires_at")?,
            allowed_actions: coalesce(input_field("allowed_actions"), || Some(json!([]))).unwrap_or(Value::Null),
            action_scope: input_field("action_scope"),
        });
    }
    Ok(Some(merged))
}

/// Turn-token refs of a broker response, completed from the matching inputs'
/// provider, allowed actions and action scope.
///
/// `inputs_json` is the array of inputs without `refresh_token_envelope`;
/// `payload_json` the parsed broker response body. Output
/// `{"kind":"ok","refs":[..]}`, `{"kind":"error","code":"missing_refs"}` when
/// the response has no `refs` array, or a `malformed` outcome where TypeScript
/// throws a `TypeError` (a `null` body or ref).
///
/// # Errors
/// `protocol` when either text is not JSON or `inputs_json` is not an array.
pub fn merge_turn_token_refs_json(inputs_json: &str, payload_json: &str) -> Result<String, String> {
    let inputs: Value = serde_json::from_str(inputs_json).map_err(super::protocol)?;
    let inputs = inputs.as_array().ok_or_else(|| "protocol".to_string())?;
    let payload: Value = serde_json::from_str(payload_json).map_err(super::protocol)?;
    let outcome = match merge(inputs, &payload) {
        Ok(Some(refs)) => json!({"kind": "ok", "refs": refs}),
        Ok(None) => json!({"kind": "error", "code": "missing_refs"}),
        Err(fail) => fail.outcome(),
    };
    serde_json::to_string(&outcome).map_err(super::protocol)
}
