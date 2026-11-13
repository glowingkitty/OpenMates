//! OAuth handoff row plan of the web connected-account client, shared Rust core
//! (mirrors `connectedAccountOAuthService.ts` `buildEncryptedConnectedAccountRow`).
//!
//! spec: specifications/architecture/connected-accounts#connected-accounts.connection.private-reusable
//!
//! Rust decides every plaintext the page encrypts, in the TypeScript await
//! order, plus the storage guard over the finished row. The page keeps
//! master-key encryption, SHA-256 and the claimed refresh-token bundle, which
//! never enters this module: its encrypt step is a marker the page fills with
//! `JSON.stringify(handoff.refresh_token_bundle)`. Plaintext JSON is written by
//! hand in `JSON.stringify` key order, so the encrypted bytes match TypeScript.
use serde_json::{json, Map, Value};

use super::js::{coalesce, prop};
use super::{protocol, Fail, STORAGE_FORBIDDEN_FIELDS};

/// `JSON.stringify` of a string (escaping matches for well-formed strings).
fn quote(text: &str) -> String {
    serde_json::to_string(text).expect("serializing a str to JSON cannot fail")
}

fn string_array(items: &[String]) -> String {
    format!("[{}]", items.iter().map(|item| quote(item)).collect::<Vec<_>>().join(","))
}

/// `normalizeCapabilities` of the OAuth service: strings of an array, else `["read"]`.
fn normalize_capabilities(value: Option<&Value>) -> Vec<String> {
    let capabilities: Vec<String> = match value {
        Some(Value::Array(items)) => items.iter().filter_map(|item| item.as_str().map(str::to_string)).collect(),
        _ => vec![],
    };
    if capabilities.is_empty() {
        vec!["read".to_string()]
    } else {
        capabilities
    }
}

/// `actionsForCapabilities`: `Set` insertion order.
fn actions_for_capabilities(capabilities: &[String]) -> Vec<String> {
    let mut actions: Vec<String> = vec![];
    for capability in capabilities {
        let added: &[&str] = match capability.as_str() {
            "read" => &["read"],
            "write" => &["write", "update"],
            "delete" => &["delete"],
            _ => &[],
        };
        for action in added {
            if !actions.iter().any(|known| known == action) {
                actions.push((*action).to_string());
            }
        }
    }
    actions
}

/// `runtimeModesForCapabilities` as JSON text (action names are never integer-like keys).
fn runtime_modes_json(actions: &[String]) -> String {
    let pairs: Vec<String> = actions
        .iter()
        .map(|action| {
            let mode = if action == "read" { "allow_automatically" } else { "always_ask" };
            format!("{}:{}", quote(action), quote(mode))
        })
        .collect();
    format!("{{{}}}", pairs.join(","))
}

/// The page's `JSON.stringify(x.scopes)` text: `None` when `undefined` or `null`.
fn scopes_text(input: &Map<String, Value>, key: &str) -> Result<Option<String>, String> {
    match input.get(key) {
        None => Ok(None),
        Some(Value::String(text)) => {
            // Spliced verbatim into the plaintext, so it must be one JSON value.
            let value: Value = serde_json::from_str(text).map_err(protocol)?;
            Ok(if value.is_null() { None } else { Some(text.clone()) })
        }
        Some(_) => Err("protocol".to_string()),
    }
}

fn encrypt_step(field: &str, plaintext: &str, name: &str) -> Value {
    json!({"field": field, "encrypt": plaintext, "failure": failure(name)})
}

fn failure(name: &str) -> String {
    format!("Failed to encrypt connected account OAuth field: {name}")
}

fn plan(input: &Map<String, Value>) -> Result<Value, String> {
    let text = |key: &str| input.get(key).and_then(Value::as_str).map(str::to_string).ok_or_else(|| "protocol".to_string());
    // Deviation (documented): TypeScript types both as strings (claim validation,
    // `crypto.randomUUID()`); any other value is refused at the boundary.
    let account_id = text("connectedAccountId")?;
    let provider = text("providerId")?;
    let bundle_nullish = input.get("bundleNullish").and_then(Value::as_bool).ok_or_else(|| "protocol".to_string())?;
    let hint = input.get("hint");
    // TypeScript reads `account_hint.capabilities` (override nullish) or
    // `account_hint.label` before the first await: a nullish hint throws a TypeError.
    let Ok(label_value) = prop(hint, "label") else {
        return Ok(Fail::Malformed.outcome());
    };
    let override_value = input.get("capabilitiesOverride").cloned();
    let capabilities = normalize_capabilities(
        coalesce(override_value, || prop(hint, "capabilities").ok().flatten()).as_ref(),
    );
    let label = match label_value {
        Some(Value::String(label)) => label,
        _ if provider == "google_calendar" => "Google Calendar".to_string(),
        _ => "Connected account".to_string(),
    };
    let account_ref = match prop(hint, "account_ref").ok().flatten() {
        Some(Value::String(account_ref)) => account_ref,
        _ => account_id,
    };
    let provider_account = match prop(hint, "provider_account_id").ok().flatten() {
        Some(Value::String(id)) if !id.is_empty() => Some(id),
        _ => None,
    };
    let actions = actions_for_capabilities(&capabilities);

    let mut steps = vec![
        encrypt_step("encrypted_provider_type", &provider, "provider_id"),
        json!({"field": "provider_type_hash", "hash": provider}),
        encrypt_step("encrypted_account_label", &label, "account_label"),
        json!({"field": "encrypted_refresh_token_bundle", "bundle": true, "failure": failure("refresh_token_bundle")}),
        encrypt_step("encrypted_capabilities", &string_array(&capabilities), "capabilities"),
    ];
    // `account_hint.scopes ?? refresh_token_bundle.scopes ?? []`: a nullish bundle
    // throws a TypeError after the steps above have run.
    let scopes = match scopes_text(input, "hintScopes")? {
        Some(scopes) => scopes,
        None if bundle_nullish => return Ok(json!({"kind": "ok", "steps": steps, "malformed": true})),
        None => scopes_text(input, "bundleScopes")?.unwrap_or_else(|| "[]".to_string()),
    };
    let app_id = if provider == "google_calendar" { "calendar" } else { provider.as_str() };
    let permissions = format!(
        "{{\"app_id\":{},\"allowed_actions\":{},\"scopes\":{}}}",
        quote(app_id),
        string_array(&actions),
        scopes
    );
    steps.push(encrypt_step("encrypted_app_permissions", &permissions, "app_permissions"));
    let directory_hint = format!(
        "{{\"account_ref\":{},\"label\":{},\"capabilities\":{},\"runtime_modes\":{}}}",
        quote(&account_ref),
        quote(&label),
        string_array(&capabilities),
        runtime_modes_json(&actions)
    );
    steps.push(encrypt_step("encrypted_account_directory_hint", &directory_hint, "account_directory_hint"));
    if let Some(id) = provider_account {
        steps.push(json!({"field": "provider_account_id_hash", "hash": id}));
        steps.push(encrypt_step("encrypted_provider_account_display", &id, "provider_account_display"));
    }
    Ok(json!({"kind": "ok", "steps": steps, "malformed": false}))
}

/// Ordered encrypt/hash steps of a new connected-account row from an OAuth handoff.
///
/// `input_json`: `{connectedAccountId, providerId, hint?, capabilitiesOverride?,
/// hintScopes?, bundleScopes?, bundleNullish}`, where the scope fields are the
/// page's `JSON.stringify` of `account_hint.scopes` / `refresh_token_bundle.scopes`
/// (absent when `undefined`) and no refresh-token material is included.
/// Output `{"kind":"ok","steps":[..],"malformed":bool}`: each step is
/// `{field, hash}`, `{field, encrypt, failure}` or the bundle marker
/// `{field, bundle: true, failure}`; `malformed: true` means TypeScript throws a
/// `TypeError` after those steps. A nullish account hint is a `malformed`
/// outcome before any step.
///
/// # Errors
/// `protocol` for a malformed envelope, non-string ids or non-JSON scope text.
pub fn oauth_row_plan_json(input_json: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input_json).map_err(protocol)?;
    let input = input.as_object().ok_or_else(|| "protocol".to_string())?;
    serde_json::to_string(&plan(input)?).map_err(protocol)
}

/// `assertNoPlaintextConnectedAccountFields` over the page's exact
/// `JSON.stringify(value ?? {})` text, so key order and escaping are TypeScript's.
/// Output `{"kind":"ok"}` or the `forbidden` outcome with the TypeScript message.
///
/// # Errors
/// None today; the `Result` keeps the binding signature uniform.
pub fn storage_guard_json(serialized: &str) -> Result<String, String> {
    let outcome = match STORAGE_FORBIDDEN_FIELDS.iter().find(|field| serialized.contains(&format!("\"{field}\""))) {
        Some(field) => Fail::Forbidden(format!("Connected account storage payload contains forbidden field: {field}")).outcome(),
        None => json!({"kind": "ok"}),
    };
    serde_json::to_string(&outcome).map_err(protocol)
}
