//! OAuth row plan labels, multi-app permissions envelope, mail capability limits and app merging.
use serde_json::{Value, json};

use super::{merge_account_update_json, merge_app_permissions_json, oauth_row_plan_json};

fn plan(input: Value) -> Value {
    serde_json::from_str(&oauth_row_plan_json(&input.to_string()).unwrap()).unwrap()
}

fn encrypted(plan: &Value, field: &str) -> Value {
    let step = plan["steps"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["field"] == field)
        .unwrap();
    serde_json::from_str(step["encrypt"].as_str().unwrap()).unwrap()
}

fn encrypted_text(plan: &Value, field: &str) -> String {
    let step = plan["steps"]
        .as_array()
        .unwrap()
        .iter()
        .find(|s| s["field"] == field)
        .unwrap();
    step["encrypt"].as_str().unwrap().to_string()
}

fn google(hint: Value) -> Value {
    plan(
        json!({"connectedAccountId":"a1","providerId":"google_calendar","bundleNullish":false,"hint":hint,"hintScopes":"[\"s\"]"}),
    )
}

#[test]
fn label_falls_back_to_account_email_then_provider_default() {
    let with_email = google(json!({"account_email":"me@example.org"}));
    assert_eq!(
        encrypted_text(&with_email, "encrypted_account_label"),
        "me@example.org"
    );
    let both = google(json!({"label":"Work","account_email":"me@example.org"}));
    assert_eq!(encrypted_text(&both, "encrypted_account_label"), "Work");
    let none = google(json!({}));
    assert_eq!(
        encrypted_text(&none, "encrypted_account_label"),
        "Google Calendar"
    );
}

#[test]
fn google_calendar_writes_the_multi_app_envelope() {
    let calendar = google(json!({"capabilities":["read","write"]}));
    assert_eq!(
        encrypted(&calendar, "encrypted_app_permissions"),
        json!({"apps":{"calendar":{"allowed_actions":["read","write","update"],"scopes":["s"]}}})
    );
}

#[test]
fn other_providers_keep_the_single_app_object() {
    let figma = plan(
        json!({"connectedAccountId":"a1","providerId":"figma","bundleNullish":false,"hint":{},"hintScopes":"[]"}),
    );
    assert_eq!(
        encrypted(&figma, "encrypted_app_permissions"),
        json!({"app_id":"design","allowed_actions":["read"],"scopes":[]})
    );
}

#[test]
fn mail_app_allows_only_read_and_draft() {
    let mail =
        google(json!({"app_id":"mail","capabilities":["read","draft","write","delete","send"]}));
    assert_eq!(
        encrypted(&mail, "encrypted_app_permissions"),
        json!({"apps":{"mail":{"allowed_actions":["read","draft"],"scopes":["s"]}}})
    );
    assert_eq!(
        encrypted(&mail, "encrypted_capabilities"),
        json!(["read", "draft"])
    );
    let hint = encrypted(&mail, "encrypted_account_directory_hint");
    assert_eq!(
        hint["runtime_modes"],
        json!({"read":"allow_automatically","draft":"always_ask"})
    );
}

#[test]
fn merge_adds_mail_to_a_single_app_calendar_row() {
    let old = r#"{"app_id":"calendar","allowed_actions":["read"],"scopes":["c"]}"#;
    let new = r#"{"apps":{"mail":{"allowed_actions":["read","draft"],"scopes":["m"]}}}"#;
    let merged: Value =
        serde_json::from_str(&merge_app_permissions_json(old, new).unwrap()).unwrap();
    assert_eq!(
        merged,
        json!({"apps":{"calendar":{"allowed_actions":["read"],"scopes":["c"]},"mail":{"allowed_actions":["read","draft"],"scopes":["m"]}}})
    );
}

#[test]
fn merge_replaces_the_same_apps_older_entry() {
    let old =
        r#"{"apps":{"calendar":{"allowed_actions":["read"]},"mail":{"allowed_actions":["read"]}}}"#;
    let new = r#"{"apps":{"mail":{"allowed_actions":["read","draft"]}}}"#;
    let merged: Value =
        serde_json::from_str(&merge_app_permissions_json(old, new).unwrap()).unwrap();
    assert_eq!(
        merged["apps"]["mail"]["allowed_actions"],
        json!(["read", "draft"])
    );
    assert_eq!(
        merged["apps"]["calendar"]["allowed_actions"],
        json!(["read"])
    );
}

#[test]
fn merge_refuses_non_permission_text() {
    assert_eq!(
        merge_app_permissions_json("[]", "{}").unwrap_err(),
        "protocol"
    );
}

#[test]
fn account_update_merge_unions_capabilities_and_keeps_existing_runtime_modes() {
    let input = json!({
        "existingPermissions": r#"{"app_id":"calendar","allowed_actions":["read"],"scopes":[]}"#,
        "newPermissions": r#"{"apps":{"mail":{"allowed_actions":["read","draft"],"scopes":[]}}}"#,
        "existingHint": r#"{"account_ref":"r","label":"me@example.org","capabilities":["read"],"runtime_modes":{"read":"always_ask"}}"#,
        "newHint": r#"{"account_ref":"x","label":"other","capabilities":["read","draft"],"runtime_modes":{"read":"allow_automatically","draft":"always_ask"}}"#,
        "existingCapabilities": r#"["read"]"#,
        "newCapabilities": r#"["read","draft"]"#,
    });
    let out: Value =
        serde_json::from_str(&merge_account_update_json(&input.to_string()).unwrap()).unwrap();
    let hint: Value = serde_json::from_str(out["hint"].as_str().unwrap()).unwrap();
    assert_eq!(hint["account_ref"], "r");
    assert_eq!(hint["label"], "me@example.org");
    assert_eq!(hint["capabilities"], json!(["read", "draft"]));
    assert_eq!(
        hint["runtime_modes"],
        json!({"read":"always_ask","draft":"always_ask"})
    );
    assert_eq!(out["capabilities"], r#"["read","draft"]"#);
    let permissions: Value = serde_json::from_str(out["permissions"].as_str().unwrap()).unwrap();
    assert!(permissions["apps"]["calendar"].is_object() && permissions["apps"]["mail"].is_object());
}
