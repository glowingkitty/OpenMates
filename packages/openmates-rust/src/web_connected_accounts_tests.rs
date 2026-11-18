//! Replays `web_connected_accounts_ts_vectors.json` (checked against the TypeScript
//! services by connectedAccountsVectors.test.ts) through the Rust decisions,
//! with the page adapter's decrypt/attach steps emulated as rustConnectedAccounts.ts does them.
use super::tokens::merge_turn_token_refs_json;
use super::*;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_connected_accounts_ts_vectors.json")).unwrap()
}

fn parsed(text: &str) -> Value {
    serde_json::from_str(text).unwrap()
}

/// Test decrypt convention: `enc:<plaintext>` (JSON when it parses), else failure.
fn decrypt(value: &Value) -> Option<Value> {
    let plain = value.as_str()?.strip_prefix("enc:")?;
    Some(serde_json::from_str(plain).unwrap_or_else(|_| Value::String(plain.to_string())))
}

/// The page's per-row decrypt (`decryptRowFacts`): `None` when any field fails.
fn facts(row: &Value) -> Option<Value> {
    let mut out = json!({
        "provider": decrypt(&row["encrypted_provider_type"])?,
        "label": decrypt(&row["encrypted_account_label"])?,
        "capabilities": decrypt(&row["encrypted_capabilities"])?,
        "permissions": decrypt(&row["encrypted_app_permissions"])?,
    });
    if row["encrypted_account_directory_hint"].as_str().is_some_and(|hint| !hint.is_empty()) {
        out["hint"] = decrypt(&row["encrypted_account_directory_hint"])?;
    }
    Some(out)
}

fn error_outcome(outcome: &Value) -> Value {
    let mut error = json!({"kind": "error", "code": outcome["code"]});
    if outcome["code"] == "forbidden" {
        error["message"] = outcome["message"].clone();
    }
    error
}

fn send_context(case: &Value) -> Value {
    let params = &case["params"];
    let rows = case["rows"].as_array().unwrap();
    let ids = params.get("accountIds").cloned().unwrap_or(Value::Null);
    let selection = parsed(&select_send_rows_json(&case["rows"].to_string(), &ids.to_string()).unwrap());
    if selection["kind"] != "ok" {
        return error_outcome(&selection);
    }
    let selected: Vec<&Value> = selection["indices"].as_array().unwrap().iter().map(|i| &rows[i.as_u64().unwrap() as usize]).collect();
    if selected.is_empty() {
        return json!({"kind": "ok", "value": null});
    }
    let mut plan_rows = vec![];
    for row in &selected {
        let Some(mut fact) = facts(row) else {
            return json!({"kind": "error", "code": "decrypt"});
        };
        fact["id"] = row["id"].clone();
        if let Some(mode) = row.get("execution_mode") {
            fact["execution_mode"] = mode.clone();
        }
        plan_rows.push(fact);
    }
    let mut input = params.clone();
    input.as_object_mut().unwrap().remove("accountIds");
    input["rows"] = Value::Array(plan_rows);
    let plan = parsed(&send_context_plan_json(&input.to_string()).unwrap());
    if plan["kind"] != "ok" {
        return error_outcome(&plan);
    }
    let mut inputs = vec![];
    for token in plan["tokens"].as_array().unwrap() {
        let row = selected[token["row"].as_u64().unwrap() as usize];
        let Some(envelope) = decrypt(&row["encrypted_refresh_token_bundle"]) else {
            return json!({"kind": "error", "code": "decrypt"});
        };
        let mut entry = json!({
            "connected_account_id": token["connected_account_id"], "app_id": token["app_id"],
            "provider_id": token["provider_id"], "allowed_actions": token["allowed_actions"],
            "refresh_token_envelope": envelope,
        });
        if let Some(scope) = token.get("action_scope") {
            entry["action_scope"] = scope.clone();
        }
        inputs.push(entry);
    }
    json!({"kind": "ok", "value": {"directory": plan["directory"], "tokenRefInputs": inputs}})
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn send_context_plans_equal_typescript() {
    for case in vectors()["sendContext"].as_array().unwrap() {
        // `flagOnOut` records a documented flag-on deviation from the TypeScript `out`.
        let expected = case.get("flagOnOut").unwrap_or(&case["out"]);
        assert_eq!(&send_context(case), expected, "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn summaries_equal_typescript() {
    for case in vectors()["summaries"].as_array().unwrap() {
        let rows = case["rows"].as_array().unwrap();
        let decrypted: Vec<Value> = rows.iter().map(|row| facts(row).unwrap_or(Value::Null)).collect();
        let input = json!({"rows": rows, "decrypted": decrypted});
        let outcome = parsed(&summary_plan_json(&input.to_string()).unwrap());
        let actual = if outcome["kind"] == "ok" {
            json!({"kind": "ok", "value": outcome["summaries"]})
        } else {
            error_outcome(&outcome)
        };
        assert_eq!(actual, case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn token_ref_merges_equal_typescript_without_envelopes() {
    for case in vectors()["tokenRefs"].as_array().unwrap() {
        let inputs: Vec<Value> = case["inputs"]
            .as_array()
            .unwrap()
            .iter()
            .map(|input| {
                let mut stripped = input.clone();
                stripped.as_object_mut().unwrap().remove("refresh_token_envelope");
                stripped
            })
            .collect();
        let outcome = parsed(&merge_turn_token_refs_json(&Value::Array(inputs).to_string(), &case["payload"].to_string()).unwrap());
        let actual = if outcome["kind"] == "ok" {
            json!({"kind": "ok", "value": outcome["refs"]})
        } else {
            error_outcome(&outcome)
        };
        assert_eq!(actual, case["out"], "{}", case["name"]);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn malformed_envelopes_are_protocol_errors() {
    assert_eq!(select_send_rows_json("{}", "null").unwrap_err(), "protocol");
    assert_eq!(select_send_rows_json("[]", "\"acct\"").unwrap_err(), "protocol");
    assert_eq!(send_context_plan_json(r#"{"rows":[]}"#).unwrap_err(), "protocol");
    assert_eq!(send_context_plan_json(r#"{"appId":"calendar","rows":[{"provider":"x"}]}"#).unwrap_err(), "protocol");
    assert_eq!(summary_plan_json(r#"{"rows":[{}],"decrypted":[]}"#).unwrap_err(), "protocol");
    assert_eq!(merge_turn_token_refs_json("{}", "{}").unwrap_err(), "protocol");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.client.thin-platform-boundary
#[test]
fn inherited_prototype_app_key_reads_as_permission_without_fields() {
    // `apps["constructor"]` is Object's constructor in JavaScript: truthy, no own fields.
    let input = json!({"appId": "constructor", "rows": [{"id": "a", "provider": "p", "label": "L",
        "capabilities": ["read"], "permissions": {"apps": {"mail": {}}}}]});
    let plan = parsed(&send_context_plan_json(&input.to_string()).unwrap());
    assert_eq!(plan["directory"][0]["app_id"], "constructor");
    assert_eq!(plan["tokens"], json!([]));
}

// contract-test: supporting surface=sdks.rust assertions=design-figma.connection.oauth
#[test]
fn figma_oauth_row_plan_stores_design_app_and_figma_label() {
    let input = json!({"connectedAccountId": "acct-f", "providerId": "figma", "bundleNullish": false,
        "hint": {"capabilities": ["read", "variables"]}, "hintScopes": "[\"file_content:read\"]"});
    let plan = parsed(&oauth::oauth_row_plan_json(&input.to_string()).unwrap());
    let steps = plan["steps"].as_array().unwrap();
    let encrypted = |field: &str| steps.iter().find(|s| s["field"] == field).unwrap()["encrypt"].as_str().unwrap().to_string();
    assert_eq!(encrypted("encrypted_account_label"), "Figma");
    assert_eq!(encrypted("encrypted_provider_type"), "figma");
    assert_eq!(steps.iter().find(|s| s["field"] == "provider_type_hash").unwrap()["hash"], "figma");
    let permissions = encrypted("encrypted_app_permissions");
    assert!(permissions.contains("\"app_id\":\"design\""), "{permissions}");
    assert!(permissions.contains("\"allowed_actions\":[\"read\"]"), "{permissions}");
}

// contract-test: supporting surface=sdks.rust assertions=design-figma.execution.token-lifecycle
#[test]
fn figma_send_context_maps_provider_and_app_without_action_scope() {
    let row = json!({"id": "acct-f", "provider": "figma", "label": "Figma", "capabilities": ["read", "variables"],
        "permissions": {"app_id": "figma", "allowed_actions": ["read"], "runtime_modes": {"read": "allow_automatically"}}});
    for app in ["design", "figma"] {
        let plan = parsed(&send_context_plan_json(&json!({"appId": app, "rows": [row]}).to_string()).unwrap());
        assert_eq!(plan["directory"][0]["app_id"], "design");
        assert_eq!(plan["directory"][0]["provider_id"], "figma");
        assert_eq!(plan["tokens"][0]["allowed_actions"], json!(["read"]));
        assert!(plan["tokens"][0].get("action_scope").is_none());
    }
}
