//! Connected-account decisions of the web app (served by the shared Rust core
//! Worker's pre-bind `settings` unit).
//!
//! spec: specifications/architecture/connected-accounts#connected-accounts.connection.private-reusable
//!
//! Mirrors the pure logic of `connectedAccountStorageService.ts` (plaintext-field
//! guards, send-context row selection, directory and token-ref plans, account
//! summaries), `connectedAccountTokenBrokerService.ts` (turn-token ref merge),
//! `connectedAccountOAuthService.ts` (OAuth row plan, [`oauth`]) and
//! `connectedAccountCliTransfer.ts` (CLI transfer plan, [`transfer`]) with
//! JavaScript value semantics, proven by `web_connected_accounts_ts_vectors.json`
//! and `web_connected_accounts_write_ts_vectors.json`. The page keeps fetch,
//! master-key crypto, the passcode and the refresh-token envelopes: credential
//! material never enters this module. Every function takes and returns JSON
//! text; a malformed envelope is the stable code `protocol`.
#[path = "web_connected_accounts_js.rs"]
mod js;
#[path = "web_connected_accounts_oauth.rs"]
pub mod oauth;
#[path = "web_connected_accounts_tokens.rs"]
pub mod tokens;
#[path = "web_connected_accounts_transfer.rs"]
pub mod transfer;

use serde::Serialize;
use serde_json::{json, Map, Value};

use js::{coalesce, index, is_str, prop, prop_opt, strict_eq, to_js_string, truthy, utf16_cmp, Lookup};

/// Field names a stored row may never carry in plaintext (`STORAGE_FORBIDDEN_FIELDS`).
const STORAGE_FORBIDDEN_FIELDS: [&str; 15] = [
    "provider",
    "provider_type",
    "provider_name",
    "provider_email",
    "email",
    "account_email",
    "account_label",
    "display_name",
    "oauth_scopes",
    "scopes",
    "refresh_token",
    "access_token",
    "provider_account_id",
    "client_id",
    "private_key",
];

/// Field names a directory, summary or token ref may never carry
/// (`CONNECTED_ACCOUNT_FORBIDDEN_FIELDS`).
const SECRET_FORBIDDEN_FIELDS: [&str; 11] = [
    "refresh_token",
    "access_token",
    "provider_email",
    "email",
    "account_email",
    "provider_account_id",
    "provider_account_email",
    "client_id",
    "private_key",
    "oauth_scopes",
    "scopes",
];

const KNOWN_CAPABILITIES: [&str; 4] = ["read", "write", "update", "delete"];

/// Why a decision stopped; mirrors what the TypeScript service throws.
pub(crate) enum Fail {
    /// TypeScript throws a `TypeError` on this malformed decrypted value.
    Malformed,
    /// A plaintext guard tripped; carries the TypeScript error message.
    Forbidden(String),
}

impl Fail {
    fn outcome(&self) -> Value {
        match self {
            Fail::Malformed => json!({"kind": "error", "code": "malformed"}),
            Fail::Forbidden(message) => json!({"kind": "error", "code": "forbidden", "message": message}),
        }
    }
}

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

fn parse(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(protocol)
}

fn encode(value: &impl Serialize) -> Result<String, String> {
    serde_json::to_string(value).map_err(protocol)
}

/// `JSON.stringify(value).includes('"<field>"')` over `fields` in order.
fn assert_no_fields(value: &impl Serialize, fields: &[&str], message: &str) -> Result<(), Fail> {
    let serialized = serde_json::to_string(value).map_err(|_| Fail::Malformed)?;
    match fields.iter().find(|field| serialized.contains(&format!("\"{field}\""))) {
        Some(field) => Err(Fail::Forbidden(format!("{message}: {field}"))),
        None => Ok(()),
    }
}

/// `assertNoPlaintextConnectedAccountFields`.
fn assert_no_plaintext(value: &Value) -> Result<(), Fail> {
    assert_no_fields(value, &STORAGE_FORBIDDEN_FIELDS, "Connected account storage payload contains forbidden field")
}

/// `assertNoConnectedAccountSecretLeak`.
pub(crate) fn assert_no_secret_leak(value: &impl Serialize) -> Result<(), Fail> {
    assert_no_fields(value, &SECRET_FORBIDDEN_FIELDS, "Connected account payload contains forbidden field")
}

/// `normalizeConnectedAccountAppId` / `normalizeAppId`.
fn normalize_app_id(value: Option<Value>) -> Option<Value> {
    if is_str(value.as_ref(), "google_calendar") {
        Some(Value::String("calendar".into()))
    } else {
        value
    }
}

/// `appIdForProvider` of the storage service.
fn app_id_for_provider(provider: &Value) -> Value {
    match provider.as_str() {
        Some("google_calendar") => Value::String("calendar".into()),
        Some("revolut_business") => Value::String("finance".into()),
        _ => provider.clone(),
    }
}

/// `normalizeConnectedAccountProviderId`.
fn normalize_provider(provider: &Value) -> Value {
    if provider.as_str() == Some("google_calendar") {
        Value::String("google".into())
    } else {
        provider.clone()
    }
}

/// `normalizeCapabilityList`: string arrays, `{capabilities}` objects, or a
/// capability phrase such as "read-write".
fn normalize_capability_list(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items.iter().filter_map(|item| item.as_str().map(str::to_string)).collect(),
        Some(Value::Object(map)) if map.get("capabilities").is_some_and(Value::is_array) => {
            normalize_capability_list(map.get("capabilities"))
        }
        Some(Value::String(text)) => {
            let lowered = text.to_lowercase();
            let tokens: Vec<&str> = lowered
                .split(|c: char| !(c.is_ascii_lowercase() || c.is_ascii_digit()))
                .filter(|token| !token.is_empty())
                .collect();
            if tokens.is_empty() || tokens.iter().any(|token| !KNOWN_CAPABILITIES.contains(token)) {
                return vec![];
            }
            let mut unique: Vec<String> = vec![];
            for token in tokens {
                if !unique.iter().any(|seen| seen == token) {
                    unique.push(token.to_string());
                }
            }
            unique
        }
        _ => vec![],
    }
}

/// `isLegacyMissingCapabilityList`.
fn is_legacy_missing_capability_list(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => true,
        Some(Value::Array(items)) => items.is_empty(),
        Some(Value::Object(map)) => match map.get("capabilities") {
            Some(Value::Array(items)) => items.is_empty(),
            _ => false,
        },
        Some(_) => false,
    }
}

/// `capabilitiesForActions` (`for...of`: strings iterate code points, which
/// never equal an action; other non-iterables are a `TypeError`).
fn capabilities_for_actions(actions: &Value) -> Result<Vec<String>, Fail> {
    let items = match actions {
        Value::Array(items) => items,
        Value::String(_) => return Ok(vec![]),
        _ => return Err(Fail::Malformed),
    };
    let mut capabilities: Vec<String> = vec![];
    for action in items {
        if let Some(name) = action.as_str().filter(|name| KNOWN_CAPABILITIES.contains(name)) {
            if !capabilities.iter().any(|seen| seen == name) {
                capabilities.push(name.to_string());
            }
        }
    }
    Ok(capabilities)
}

/// `preauthorizedActions`: actions whose runtime mode runs without a prompt.
fn preauthorized_actions(actions: &Value, runtime_modes: Option<&Value>) -> Result<Vec<Value>, Fail> {
    let Some(modes) = runtime_modes.filter(|modes| truthy(Some(modes))) else {
        return Ok(vec![]);
    };
    let Value::Array(items) = actions else {
        return Err(Fail::Malformed);
    };
    Ok(items
        .iter()
        .filter(|action| match index(modes, &to_js_string(action)) {
            Lookup::Value(Value::String(mode)) => mode == "allow_automatically" || mode == "auto_decide",
            _ => false,
        })
        .cloned()
        .collect())
}

/// One app's permission envelope after `permissionForApp`.
struct AppPermission {
    app_id: Option<Value>,
    allowed_actions: Option<Value>,
    action_scope: Option<Value>,
    runtime_modes: Option<Value>,
}

/// `permissionForApp`: the per-app entry of `apps`, else the legacy single-app
/// envelope when it names the requested app; `None` skips the account.
fn permission_for_app(permissions: &Value, requested: &str, provider: &Value) -> Result<Option<AppPermission>, Fail> {
    let apps = prop(Some(permissions), "apps")?;
    // `apps?.[id] ?? apps?.[normalize(id)]`: `requested` is already normalized
    // and normalization is idempotent, so both reads are the same key.
    let lookup = match apps.as_ref() {
        None | Some(Value::Null) => Lookup::Undefined,
        Some(container) => index(container, requested),
    };
    match lookup {
        Lookup::Function => {
            return Ok(Some(AppPermission {
                app_id: Some(Value::String(requested.to_string())),
                allowed_actions: None,
                action_scope: None,
                runtime_modes: None,
            }))
        }
        Lookup::Value(entry) if truthy(Some(&entry)) => {
            // `{ appId: requestedAppId, ...appPermissions }`: only own object
            // fields survive the spread, and an own `appId` overrides.
            let field = |key: &str| prop_opt(Some(&entry), key);
            return Ok(Some(AppPermission {
                app_id: field("appId").or_else(|| Some(Value::String(requested.to_string()))),
                allowed_actions: field("allowed_actions"),
                action_scope: field("action_scope"),
                runtime_modes: field("runtime_modes"),
            }));
        }
        _ => {}
    }
    let legacy = normalize_app_id(coalesce(prop(Some(permissions), "app_id")?, || Some(app_id_for_provider(provider))));
    if !strict_eq(legacy.as_ref(), Some(&Value::String(requested.to_string()))) {
        return Ok(None);
    }
    Ok(Some(AppPermission {
        app_id: legacy,
        allowed_actions: prop(Some(permissions), "allowed_actions")?,
        action_scope: prop(Some(permissions), "action_scope")?,
        runtime_modes: prop(Some(permissions), "runtime_modes")?,
    }))
}

/// `primaryAppIdForPermissions`: the first (UTF-16 sorted) per-app key, else the
/// legacy app id.
fn primary_app_id(permissions: &Value, provider: &Value) -> Result<Option<Value>, Fail> {
    let apps = prop(Some(permissions), "apps")?;
    let keys: Option<Vec<String>> = match apps.as_ref() {
        Some(Value::Object(map)) => Some(map.keys().cloned().collect()),
        Some(Value::Array(items)) => Some((0..items.len()).map(|i| i.to_string()).collect()),
        _ => None,
    };
    if let Some(keys) = keys {
        let mut normalized: Vec<String> =
            keys.into_iter().map(|key| if key == "google_calendar" { "calendar".to_string() } else { key }).collect();
        normalized.sort_by(|a, b| utf16_cmp(a, b));
        if let Some(first) = normalized.into_iter().next().filter(|first| !first.is_empty()) {
            return Ok(Some(Value::String(first)));
        }
    }
    Ok(normalize_app_id(coalesce(prop(Some(permissions), "app_id")?, || Some(app_id_for_provider(provider)))))
}

/// Decrypted fields of one row, as the page read them (`hint` absent when the
/// row has no directory hint ciphertext).
struct Facts<'a> {
    provider: &'a Value,
    label: &'a Value,
    capabilities: &'a Value,
    permissions: &'a Value,
    hint: Option<&'a Value>,
}

impl<'a> Facts<'a> {
    fn read(value: &'a Value) -> Result<Self, String> {
        let field = |key: &str| value.get(key).ok_or_else(|| "protocol".to_string());
        Ok(Facts {
            provider: field("provider")?,
            label: field("label")?,
            capabilities: field("capabilities")?,
            permissions: field("permissions")?,
            hint: value.get("hint"),
        })
    }
}

/// Selects the rows a send context reads (all rows unless `accountIds` is a
/// non-empty array) and runs the plaintext guard on each, in order.
///
/// Output: `{"kind":"ok","indices":[..]}` or a `forbidden` error outcome.
///
/// # Errors
/// `protocol` when the input is not JSON or `rows` is not an array.
pub fn select_send_rows_json(rows_json: &str, account_ids_json: &str) -> Result<String, String> {
    let rows = parse(rows_json)?;
    let rows = rows.as_array().ok_or_else(|| "protocol".to_string())?;
    let ids = parse(account_ids_json)?;
    let ids: &[Value] = match &ids {
        Value::Array(items) => items,
        Value::Null => &[],
        _ => return Err("protocol".into()),
    };
    let mut indices: Vec<usize> = vec![];
    for (position, row) in rows.iter().enumerate() {
        // `new Set(accountIds).has(row.id)` (SameValueZero over JSON values).
        if ids.is_empty() || ids.iter().any(|id| strict_eq(Some(id), row.get("id"))) {
            if let Err(fail) = assert_no_plaintext(row) {
                return encode(&fail.outcome());
            }
            indices.push(position);
        }
    }
    encode(&json!({"kind": "ok", "indices": indices}))
}

#[derive(Serialize)]
struct DirectoryEntry {
    #[serde(skip_serializing_if = "Option::is_none")]
    connected_account_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    app_id: Option<Value>,
    provider_id: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    account_ref: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    label: Option<Value>,
    capabilities: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    runtime_modes: Option<Value>,
}

#[derive(Serialize)]
struct TokenPlan {
    /// Position in the selected rows; the page attaches that row's decrypted
    /// refresh-token envelope.
    row: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    connected_account_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    app_id: Option<Value>,
    provider_id: Value,
    allowed_actions: Vec<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    action_scope: Option<Value>,
}

fn optional_array(input: &Value, key: &str) -> Result<Option<Vec<Value>>, String> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Array(items)) => Ok(Some(items.clone())),
        Some(_) => Err("protocol".into()),
    }
}

/// Directory entries and token-ref plans of `buildConnectedAccountSendContext`
/// over the selected rows' decrypted facts.
///
/// Input: `{appId, defaultAllowedActions?, allowedActionsOverride?,
/// actionScopesOverride?, includeActionScope?, rows:[{id?, execution_mode?,
/// provider, label, capabilities, permissions, hint?}]}`. Output:
/// `{"kind":"ok","directory":[..],"tokens":[..]}` or a `malformed` /
/// `forbidden` error outcome.
///
/// # Errors
/// `protocol` when the envelope does not have that shape.
pub fn send_context_plan_json(input_json: &str) -> Result<String, String> {
    let input = parse(input_json)?;
    let app_id = input.get("appId").and_then(Value::as_str).ok_or_else(|| "protocol".to_string())?;
    let rows = input.get("rows").and_then(Value::as_array).ok_or_else(|| "protocol".to_string())?;
    let default_allowed = optional_array(&input, "defaultAllowedActions")?.unwrap_or_default();
    let allowed_override = optional_array(&input, "allowedActionsOverride")?;
    let scopes_override = optional_array(&input, "actionScopesOverride")?.filter(|scopes| !scopes.is_empty());
    let include_scope = input.get("includeActionScope") != Some(&Value::Bool(false));
    let mut facts = Vec::with_capacity(rows.len());
    for row in rows {
        facts.push(Facts::read(row)?);
    }
    match plan_send_context(app_id, rows, &facts, &default_allowed, allowed_override, scopes_override, include_scope) {
        Ok((directory, tokens)) => encode(&json!({"kind": "ok", "directory": directory, "tokens": tokens})),
        Err(fail) => encode(&fail.outcome()),
    }
}

fn plan_send_context(
    app_id: &str,
    rows: &[Value],
    facts: &[Facts<'_>],
    default_allowed: &[Value],
    allowed_override: Option<Vec<Value>>,
    scopes_override: Option<Vec<Value>>,
    include_scope: bool,
) -> Result<(Vec<DirectoryEntry>, Vec<TokenPlan>), Fail> {
    let requested = if app_id == "google_calendar" { "calendar" } else { app_id };
    let mut directory: Vec<DirectoryEntry> = vec![];
    let mut tokens: Vec<TokenPlan> = vec![];
    for (position, (row, fact)) in rows.iter().zip(facts).enumerate() {
        let capability_list = normalize_capability_list(Some(fact.capabilities));
        let Some(permission) = permission_for_app(fact.permissions, requested, fact.provider)? else {
            continue;
        };
        let provider_ref = normalize_provider(fact.provider);
        let default_actions = if is_str(permission.app_id.as_ref(), "calendar")
            && is_legacy_missing_capability_list(Some(fact.capabilities))
        {
            default_allowed.to_vec()
        } else {
            vec![]
        };
        let fallback = capabilities_for_actions(
            &coalesce(permission.allowed_actions.clone(), || Some(Value::Array(default_actions))).unwrap_or(Value::Null),
        )?;
        let directory_capabilities = normalize_capability_list(prop_opt(fact.hint, "capabilities").as_ref());
        let hint_modes = prop_opt(fact.hint, "runtime_modes");
        let runtime_modes = coalesce(hint_modes, || permission.runtime_modes.clone());
        let allowed_actions = match &allowed_override {
            Some(actions) => actions.clone(),
            None => preauthorized_actions(
                &coalesce(permission.allowed_actions.clone(), || Some(json!([]))).unwrap_or(Value::Null),
                runtime_modes.as_ref(),
            )?,
        };
        let action_scopes: Vec<Value> = match &scopes_override {
            Some(scopes) => scopes.clone(),
            None => permission.action_scope.iter().filter(|scope| truthy(Some(scope))).cloned().collect(),
        };
        let row_id = row.get("id").cloned();
        directory.push(DirectoryEntry {
            connected_account_id: row_id.clone(),
            app_id: permission.app_id.clone(),
            provider_id: provider_ref.clone(),
            account_ref: coalesce(prop_opt(fact.hint, "account_ref"), || row_id.clone()),
            label: coalesce(prop_opt(fact.hint, "label"), || Some(fact.label.clone())),
            capabilities: pick_capabilities(directory_capabilities, capability_list, fallback),
            runtime_modes,
        });
        if allowed_actions.is_empty() || is_str(row.get("execution_mode"), "local_connector") {
            continue;
        }
        let scopes: Vec<Option<Value>> = if !include_scope || action_scopes.is_empty() {
            vec![None]
        } else {
            action_scopes.into_iter().map(Some).collect()
        };
        for scope in scopes {
            tokens.push(TokenPlan {
                row: position,
                connected_account_id: row_id.clone(),
                app_id: permission.app_id.clone(),
                provider_id: provider_ref.clone(),
                allowed_actions: allowed_actions.clone(),
                action_scope: scope.filter(|scope| truthy(Some(scope))),
            });
        }
    }
    assert_no_secret_leak(&directory)?;
    Ok((directory, tokens))
}

/// Directory hint capabilities, else stored capabilities, else those implied
/// by the allowed actions.
fn pick_capabilities(directory: Vec<String>, stored: Vec<String>, fallback: Vec<String>) -> Vec<String> {
    if !directory.is_empty() {
        directory
    } else if !stored.is_empty() {
        stored
    } else {
        fallback
    }
}

#[derive(Serialize)]
struct Summary {
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    provider_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    app_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    account_ref: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    label: Option<Value>,
    capabilities: Vec<String>,
    runtime_modes: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    execution_mode: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    connector_provider_id: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    connector_status: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    updated_at: Option<Value>,
}

fn null_if_nullish(value: Option<&Value>) -> Option<Value> {
    coalesce(value.cloned(), || Some(Value::Null))
}

fn summarize_row(row: &Value, fact: &Facts<'_>) -> Result<Summary, Fail> {
    let capability_list = normalize_capability_list(Some(fact.capabilities));
    let app_id = primary_app_id(fact.permissions, fact.provider)?;
    let fallback = capabilities_for_actions(
        &coalesce(prop(Some(fact.permissions), "allowed_actions")?, || Some(json!([]))).unwrap_or(Value::Null),
    )?;
    let directory_capabilities = normalize_capability_list(prop_opt(fact.hint, "capabilities").as_ref());
    let row_id = row.get("id").cloned();
    Ok(Summary {
        id: row_id.clone(),
        provider_id: Some(fact.provider.clone()),
        app_id,
        account_ref: coalesce(prop_opt(fact.hint, "account_ref"), || row_id.clone()),
        label: coalesce(prop_opt(fact.hint, "label"), || Some(fact.label.clone())),
        capabilities: pick_capabilities(directory_capabilities, capability_list, fallback),
        runtime_modes: coalesce(prop_opt(fact.hint, "runtime_modes"), || Some(json!({}))).unwrap_or(Value::Null),
        execution_mode: coalesce(row.get("execution_mode").cloned(), || Some(Value::String("oauth".into()))),
        connector_provider_id: null_if_nullish(row.get("connector_provider_id")),
        connector_status: null_if_nullish(row.get("connector_status")),
        updated_at: row.get("updated_at").cloned(),
    })
}

/// `buildLocalConnectorSummary`: non-secret Proton Mail Bridge metadata used
/// when the encrypted summary fields cannot be read.
fn local_connector_summary(row: &Value) -> Option<Summary> {
    if !is_str(row.get("execution_mode"), "local_connector") || !is_str(row.get("connector_provider_id"), "protonmail_bridge") {
        return None;
    }
    let metadata = coalesce(row.get("connector_public_metadata").cloned(), || Some(json!({}))).unwrap_or(Value::Null);
    let label = match prop_opt(Some(&metadata), "label") {
        Some(Value::String(text)) => text,
        _ => "Proton Mail".to_string(),
    };
    Some(Summary {
        id: row.get("id").cloned(),
        provider_id: row.get("connector_provider_id").cloned(),
        app_id: Some(Value::String("mail".into())),
        account_ref: row.get("id").cloned(),
        label: Some(Value::String(label)),
        capabilities: normalize_capability_list(prop_opt(Some(&metadata), "capabilities").as_ref()),
        runtime_modes: Value::Object(Map::new()),
        execution_mode: row.get("execution_mode").cloned(),
        connector_provider_id: row.get("connector_provider_id").cloned(),
        connector_status: null_if_nullish(row.get("connector_status")),
        updated_at: row.get("updated_at").cloned(),
    })
}

/// `summarizeConnectedAccountRows` over rows and their decrypted facts
/// (`null` where the page could not decrypt the row).
///
/// Input: `{rows:[..], decrypted:[facts|null]}`. Output
/// `{"kind":"ok","summaries":[..],"fallbacks":[..]}`; a failing row without a
/// local-connector fallback answers `{"kind":"error","code":"decrypt"|"malformed","row":i,"fallbacks":[..]}`
/// (the page rethrows its own decrypt error), a plaintext guard a `forbidden`
/// outcome. `fallbacks` lists rows summarized from local-connector metadata.
///
/// # Errors
/// `protocol` when the envelope does not have that shape.
pub fn summary_plan_json(input_json: &str) -> Result<String, String> {
    let input = parse(input_json)?;
    let rows = input.get("rows").and_then(Value::as_array).ok_or_else(|| "protocol".to_string())?;
    let decrypted = input.get("decrypted").and_then(Value::as_array).ok_or_else(|| "protocol".to_string())?;
    if rows.len() != decrypted.len() {
        return Err("protocol".into());
    }
    let mut summaries: Vec<Summary> = vec![];
    let mut fallbacks: Vec<usize> = vec![];
    for (position, (row, facts)) in rows.iter().zip(decrypted).enumerate() {
        if let Err(fail) = assert_no_plaintext(row) {
            return encode(&fail.outcome());
        }
        let (code, attempt) = if facts.is_null() {
            ("decrypt", None)
        } else {
            match summarize_row(row, &Facts::read(facts)?) {
                Ok(summary) => ("", Some(summary)),
                Err(Fail::Forbidden(message)) => return encode(&Fail::Forbidden(message).outcome()),
                Err(Fail::Malformed) => ("malformed", None),
            }
        };
        if let Some(summary) = attempt {
            summaries.push(summary);
        } else if let Some(summary) = local_connector_summary(row) {
            fallbacks.push(position);
            summaries.push(summary);
        } else {
            return encode(&json!({"kind": "error", "code": code, "row": position, "fallbacks": fallbacks}));
        }
    }
    if let Err(fail) = assert_no_secret_leak(&summaries) {
        return encode(&fail.outcome());
    }
    encode(&json!({"kind": "ok", "summaries": summaries, "fallbacks": fallbacks}))
}

#[cfg(test)]
#[path = "web_connected_accounts_tests.rs"]
mod web_connected_accounts_tests;
#[cfg(test)]
#[path = "web_connected_accounts_write_tests.rs"]
mod web_connected_accounts_write_tests;
