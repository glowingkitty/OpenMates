//! Replays `web_connected_accounts_write_ts_vectors.json` (checked against the
//! TypeScript OAuth and CLI transfer services by connectedAccountWritesVectors.test.ts)
//! through the Rust plans, emulating the page steps of rustConnectedAccountWrites.ts.
use super::oauth::{oauth_row_plan_json, storage_guard_json};
use super::transfer::{transfer_command_json, transfer_plan_json};
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_connected_accounts_write_ts_vectors.json")).unwrap()
}

fn parsed(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

fn quote(text: &str) -> String {
    serde_json::to_string(text).unwrap()
}

/// Mocked `encryptWithMasterKey`: `enc:<plaintext>`, `None` for `FAILENC`.
fn encrypt(plain: &str) -> Option<String> {
    (!plain.contains("FAILENC")).then(|| format!("enc:{plain}"))
}

/// The page's `JSON.stringify(x?.scopes)` (vector scopes are arrays of strings or null).
fn scopes_text(owner: &Value) -> Option<Value> {
    owner.get("scopes").map(|scopes| Value::String(scopes.to_string()))
}

/// rustBuildEncryptedConnectedAccountRow: plan, run the steps in order, guard.
/// Returns the outcome and the plaintexts handed to encryption.
fn oauth_row(params: &Value) -> (Value, Vec<String>) {
    let handoff = &params["handoff"];
    let hint = &handoff["account_hint"];
    let bundle = &handoff["refresh_token_bundle"];
    let mut input = json!({
        "connectedAccountId": params["connectedAccountId"],
        "providerId": handoff["provider_id"],
        "hint": hint,
        "bundleNullish": bundle.is_null(),
    });
    if let Some(capabilities) = params.get("capabilitiesOverride") {
        input["capabilitiesOverride"] = capabilities.clone();
    }
    if let Some(scopes) = scopes_text(hint) {
        input["hintScopes"] = scopes;
    }
    if let Some(scopes) = scopes_text(bundle) {
        input["bundleScopes"] = scopes;
    }
    let plan = parsed(&oauth_row_plan_json(&input.to_string()).unwrap());
    let mut encrypted = vec![];
    if plan["kind"] != "ok" {
        return (json!({"kind": "error", "code": plan["code"]}), encrypted);
    }
    let mut keys = vec!["id".to_string()];
    let mut row = vec![quote(params["connectedAccountId"].as_str().unwrap())];
    for step in plan["steps"].as_array().unwrap() {
        let field = step["field"].as_str().unwrap().to_string();
        let value = if let Some(input) = step["hash"].as_str() {
            format!("sha:{input}")
        } else {
            let plain = if step["bundle"] == true { bundle.to_string() } else { step["encrypt"].as_str().unwrap().to_string() };
            encrypted.push(plain.clone());
            match encrypt(&plain) {
                Some(value) => value,
                None => return (json!({"kind": "error", "code": "encrypt", "message": step["failure"]}), encrypted),
            }
        };
        keys.push(field);
        row.push(quote(&value));
    }
    if plan["malformed"] == true {
        return (json!({"kind": "error", "code": "malformed"}), encrypted);
    }
    // The page's exact `JSON.stringify(row)` in insertion order.
    let pairs: Vec<String> = keys.iter().zip(&row).map(|(key, value)| format!("{}:{value}", quote(key))).collect();
    let serialized = format!("{{{}}}", pairs.join(","));
    let guard = parsed(&storage_guard_json(&serialized).unwrap());
    if guard["kind"] != "ok" {
        return (guard, encrypted);
    }
    let row_value = parsed(&serialized);
    (json!({"kind": "ok", "keys": keys, "row": row_value}), encrypted)
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn oauth_rows_equal_typescript_with_bundle_left_on_the_page() {
    for case in vectors()["oauthRows"].as_array().unwrap() {
        let (outcome, encrypted) = oauth_row(&case["params"]);
        assert_eq!(outcome, case["out"], "{}", case["name"]);
        if let Some(expected) = case.get("encrypted") {
            assert_eq!(json!(encrypted), *expected, "{}", case["name"]);
        }
    }
}

/// Test decrypt convention: `enc:<plaintext>` (JSON when it parses), else failure.
fn decrypt(value: &Value) -> Option<Value> {
    let plain = value.as_str()?.strip_prefix("enc:")?;
    Some(serde_json::from_str(plain).unwrap_or_else(|_| Value::String(plain.to_string())))
}

/// rustBuildConnectedAccountCliImportCommand up to the payload object (the
/// passcode check stands in for `encryptTransferPayload`).
fn transfer(case: &Value) -> Value {
    let row = &case["row"];
    let field = |key: &str| decrypt(&row[key]);
    let (Some(provider), Some(label), Some(capabilities), Some(permissions), Some(bundle)) = (
        field("encrypted_provider_type"),
        field("encrypted_account_label"),
        field("encrypted_capabilities"),
        field("encrypted_app_permissions"),
        field("encrypted_refresh_token_bundle"),
    ) else {
        return json!({"kind": "error", "code": "decrypt"});
    };
    let hint = row.get("encrypted_account_directory_hint").map(|value| decrypt(value).unwrap());
    let present = bundle["refresh_token"].as_str().is_some_and(|token| !token.is_empty());
    let mut facts = json!({"provider": provider, "label": label, "capabilities": capabilities, "permissions": permissions});
    if let Some(hint) = &hint {
        facts["hint"] = hint.clone();
    }
    let plan = parsed(&transfer_plan_json(&json!({"facts": facts, "refreshTokenPresent": present}).to_string()).unwrap());
    if plan["kind"] != "ok" {
        let mut error = json!({"kind": "error", "code": plan["code"]});
        if let Some(message) = plan.get("message") {
            error["message"] = message.clone();
        }
        return error;
    }
    let hint = hint.unwrap_or(Value::Null);
    let app_id = match (&plan["app_id"]["value"], plan["app_id"]["from"].as_str()) {
        (Value::String(value), _) => Value::String(value.clone()),
        (_, Some("permissions")) => permissions["app_id"].clone(),
        _ => provider.clone(),
    };
    let payload_label = if plan["label"] == "hint" { hint["label"].clone() } else { label };
    let runtime_modes = match &plan["runtime_modes"] {
        Value::Array(pairs) => {
            Value::Object(pairs.iter().map(|pair| (pair[0].as_str().unwrap().to_string(), pair[1].clone())).collect())
        }
        _ => hint["runtime_modes"].clone(),
    };
    let mut payload = json!({
        "version": 1, "provider_id": provider, "app_id": app_id, "label": payload_label,
        "capabilities": plan["capabilities"], "runtime_modes": runtime_modes,
        "refresh_token_bundle": bundle, "created_at": "2026-01-02T03:04:05.000Z",
    });
    if plan["account_ref"] == true {
        payload["account_ref"] = hint["account_ref"].clone();
    }
    if case["passcode"].as_str().unwrap().trim().is_empty() {
        return json!({"kind": "error", "code": "passcode"});
    }
    json!({"kind": "ok", "payload": payload})
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn transfer_payloads_equal_typescript_without_the_bundle() {
    for case in vectors()["transfers"].as_array().unwrap() {
        assert_eq!(transfer(case), case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn transfer_command_refuses_token_field_names() {
    let ok = parsed(&transfer_command_json("OMCA1.abc").unwrap());
    assert_eq!(ok["command"], "openmates connected-accounts import --payload \"OMCA1.abc\"");
    let refused = parsed(&transfer_command_json("OMCA1.refresh_token").unwrap());
    assert_eq!(refused["code"], "forbidden");
    assert_eq!(refused["message"], "Connected account transfer command unexpectedly contains token field names");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn malformed_write_envelopes_are_protocol_errors() {
    assert_eq!(oauth_row_plan_json("[]").unwrap_err(), "protocol");
    assert_eq!(oauth_row_plan_json(r#"{"connectedAccountId":1,"providerId":"p","bundleNullish":false}"#).unwrap_err(), "protocol");
    assert_eq!(
        oauth_row_plan_json(r#"{"connectedAccountId":"a","providerId":"p","bundleNullish":false,"hint":{},"hintScopes":"[unclosed"}"#).unwrap_err(),
        "protocol"
    );
    assert_eq!(transfer_plan_json(r#"{"facts":{}}"#).unwrap_err(), "protocol");
    assert_eq!(transfer_plan_json("null").unwrap_err(), "protocol");
}
