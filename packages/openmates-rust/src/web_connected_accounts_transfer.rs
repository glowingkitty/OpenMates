//! CLI transfer payload plan of the web connected-account client, shared Rust
//! core (mirrors `connectedAccountCliTransfer.ts` `buildTransferPayload` and the
//! command assembly of `buildConnectedAccountCliImportCommand`).
//!
//! spec: specifications/architecture/connected-accounts#connected-accounts.connection.private-reusable
//!
//! Rust decides the payload fields from the decrypted non-credential facts. The
//! page keeps master-key decryption, the refresh-token bundle (only the fact
//! that it carries a non-empty `refresh_token` crosses), the passcode,
//! PBKDF2/AES-GCM and the clock. Field sources are returned as pointers so the
//! page assembles the payload from its own values in TypeScript key order.
use serde_json::{json, Map, Value};

use super::js::{coalesce, is_str, nullish, prop, prop_opt, to_js_string, truthy};
use super::{protocol, Fail};

const MISSING_TOKEN: &str = "Connected account refresh token bundle is missing a refresh token";
const TOKEN_NAMES: &str = "Connected account transfer command unexpectedly contains token field names";

/// `normalizeCapabilityList` of the transfer service (one level of `{capabilities}` unwrapping per call).
fn normalize_capability_list(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items.iter().filter_map(|item| item.as_str().map(str::to_string)).collect(),
        Some(Value::Object(map)) if matches!(map.get("capabilities"), Some(Value::Array(_))) => {
            normalize_capability_list(map.get("capabilities"))
        }
        _ => vec![],
    }
}

fn plan(facts: &Map<String, Value>) -> Result<Value, Fail> {
    let provider = facts.get("provider");
    let permissions = facts.get("permissions");
    let hint = facts.get("hint");
    let hinted = normalize_capability_list(prop_opt(hint, "capabilities").as_ref());
    let capabilities = if hinted.is_empty() {
        normalize_capability_list(facts.get("capabilities"))
    } else {
        hinted
    };
    // `normalizeAppId(permissions.app_id ?? appIdForProvider(providerId))`.
    let app = prop(permissions, "app_id")?;
    let app_id = if !nullish(app.as_ref()) {
        if is_str(app.as_ref(), "google_calendar") {
            json!({"value": "calendar"})
        } else {
            json!({"from": "permissions"})
        }
    } else if is_str(provider, "google_calendar") {
        json!({"value": "calendar"})
    } else {
        json!({"from": "provider"})
    };
    let label = if nullish(prop_opt(hint, "label").as_ref()) { "row" } else { "hint" };
    let runtime_modes = if nullish(prop_opt(hint, "runtime_modes").as_ref()) {
        // `runtimeModesForActions(permissions.allowed_actions ?? [])`: `.map` on a
        // non-array throws a TypeError. Keys are `Object.fromEntries` property keys.
        let actions = coalesce(prop(permissions, "allowed_actions")?, || Some(json!([])));
        let Some(Value::Array(actions)) = actions else {
            return Err(Fail::Malformed);
        };
        let pairs: Vec<Value> = actions
            .iter()
            .map(|action| {
                let mode = if is_str(Some(action), "read") { "allow_automatically" } else { "always_ask" };
                json!([to_js_string(action), mode])
            })
            .collect();
        Value::Array(pairs)
    } else {
        Value::String("hint".into())
    };
    Ok(json!({
        "kind": "ok",
        "app_id": app_id,
        "label": label,
        "account_ref": truthy(prop_opt(hint, "account_ref").as_ref()),
        "capabilities": capabilities,
        "runtime_modes": runtime_modes,
    }))
}

/// Field plan of a CLI transfer payload.
///
/// `input_json`: `{facts: {provider, label, capabilities, permissions, hint?},
/// refreshTokenPresent}` (decrypted values; `hint` absent when the row has none).
/// Output `{"kind":"ok","app_id":{"value"}|{"from":"permissions"|"provider"},
/// "label":"hint"|"row","account_ref":bool,"capabilities":[..],
/// "runtime_modes":"hint"|[[key, mode], ..]}`, the `missing_token` error with the
/// TypeScript message, or `malformed` where TypeScript throws a `TypeError`
/// (a nullish permissions envelope, non-array allowed actions).
///
/// # Errors
/// `protocol` for a malformed envelope.
pub fn transfer_plan_json(input_json: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input_json).map_err(protocol)?;
    let facts = input.get("facts").and_then(Value::as_object).ok_or_else(|| "protocol".to_string())?;
    let present = input.get("refreshTokenPresent").and_then(Value::as_bool).ok_or_else(|| "protocol".to_string())?;
    // TypeScript checks the token before reading any other field.
    let outcome = if !present {
        json!({"kind": "error", "code": "missing_token", "message": MISSING_TOKEN})
    } else {
        plan(facts).unwrap_or_else(|fail| fail.outcome())
    };
    serde_json::to_string(&outcome).map_err(protocol)
}

/// The `openmates connected-accounts import` command for an encrypted
/// `OMCA1.` transfer payload, refusing a payload that contains `refresh_token`.
/// Output `{"kind":"ok","command":..}` or the `forbidden` outcome.
///
/// # Errors
/// None today; the `Result` keeps the binding signature uniform.
pub fn transfer_command_json(encrypted_payload: &str) -> Result<String, String> {
    let outcome = if encrypted_payload.contains("refresh_token") {
        Fail::Forbidden(TOKEN_NAMES.to_string()).outcome()
    } else {
        json!({"kind": "ok", "command": format!("openmates connected-accounts import --payload \"{encrypted_payload}\"")})
    };
    serde_json::to_string(&outcome).map_err(protocol)
}
