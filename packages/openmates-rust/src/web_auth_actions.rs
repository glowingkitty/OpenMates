//! Decision parts of the web login, session-restore and debug-session actions,
//! owned by the shared core so web and Apple classify a login reply, resume a
//! debug session and reconcile the account language identically.
//! Mirrors `stores/authLoginLogoutActions.ts` (`login` branches, debug-session
//! resume) and `stores/authSessionActions.ts` (language reconciliation).
//! The page keeps all IO and store updates; these calls are pure and synchronous.
//! No master-key or password handling lives here.
//! spec: specifications/features/auth#auth.session.lifecycle
use crate::error::{Error, Result};
use serde_json::{Map, Value, json};

const ARGS: Error = Error::Invalid("flow_args");

/// Fixed user-facing messages of the deployed `login()`.
const RATE_LIMITED: &str = "Too many login attempts. Please try again later.";
const LOGIN_ERROR: &str = "An error occurred during login";
const LOGIN_FAILED: &str = "Login failed";
const TFA_INVALID: &str = "Invalid 2FA code";

/// JavaScript truthiness for a parsed JSON value (`undefined` is `None`).
fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Some(Value::String(text)) => !text.is_empty(),
        Some(_) => true,
    }
}

fn arg<'a>(args: &'a Value, key: &str) -> Result<&'a Value> { args.get(key).ok_or(ARGS) }
fn flag(args: &Value, key: &str) -> Result<bool> { arg(args, key)?.as_bool().ok_or(ARGS) }
fn optional_text(args: &Value, key: &str) -> Result<Option<String>> {
    match args.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.clone())),
        Some(_) => Err(ARGS),
    }
}

/// Message of a failed reply: the server text when truthy, else the fixed fallback.
fn message_or(data: &Map<String, Value>, fallback: &str) -> Value {
    match data.get("message") {
        Some(message) if truthy(Some(message)) => message.clone(),
        _ => json!(fallback),
    }
}

/// Classifies the `POST /v1/auth/login` reply exactly as the deployed `login()`:
/// a 429 first (without reading the body), then the parsed JSON. The page sends
/// the raw body text (`null` when none) and builds its store updates from the
/// `kind`; an unparsable or `null` body is the generic login error.
///
/// Kinds: `rate_limited`, `error`, `tfa_required` (password accepted, code
/// needed), `success`, `tfa_invalid`, `failed`. Success also carries the fields
/// the page returns to its caller, and `lastOpened` for the signup-resume check.
fn login_verdict(args: &Value) -> Result<Value> {
    let status = arg(args, "status")?.as_u64().ok_or(ARGS)?;
    let tfa_code_given = flag(args, "tfaCodeGiven")?;
    if status == 429 {
        return Ok(json!({"kind": "rate_limited", "tfaRequired": tfa_code_given, "message": RATE_LIMITED}));
    }
    let parsed: Option<Value> = optional_text(args, "body")?.and_then(|text| serde_json::from_str(&text).ok());
    // `null` and unparsable bodies both end in the catch branch of the deployed code.
    let Some(parsed) = parsed.filter(|value| !value.is_null()) else {
        return Ok(json!({"kind": "error", "tfaRequired": false, "message": LOGIN_ERROR}));
    };
    let empty = Map::new();
    let data = parsed.as_object().unwrap_or(&empty);
    let user = data.get("user").and_then(Value::as_object);
    let tfa_required = truthy(data.get("tfa_required"));
    if truthy(data.get("success")) {
        if tfa_required {
            return Ok(json!({"kind": "tfa_required", "tfaAppName": user.and_then(|u| u.get("tfa_app_name")).cloned()}));
        }
        let backup_used = match data.get("backup_code_used") {
            Some(used) if truthy(Some(used)) => used.clone(),
            _ => json!(false),
        };
        return Ok(json!({
            "kind": "success",
            "lastOpened": user.and_then(|u| u.get("last_opened")).cloned(),
            "backupCodeUsed": backup_used,
            "remainingBackupCodes": data.get("remaining_backup_codes").cloned(),
        }));
    }
    if tfa_required {
        return Ok(json!({"kind": "tfa_invalid", "tfaRequired": true, "message": message_or(data, TFA_INVALID)}));
    }
    Ok(json!({"kind": "failed", "tfaRequired": false, "message": message_or(data, LOGIN_FAILED)}))
}

/// Resume decision for a stored `debug_session` record of a non-admin user.
/// The page parses the stored JSON and the expiry date (`expiresAtMs` is `null`
/// for an unparsable date, which never counts as unexpired); this decides
/// whether to resume the session or drop the record. A record without an expiry
/// never expires; without a debugging id it is dropped.
fn debug_session_resume(args: &Value) -> Result<Value> {
    let now = arg(args, "nowMs")?.as_f64().filter(|n| n.is_finite()).ok_or(ARGS)?;
    let has_expiry = flag(args, "hasExpiry")?;
    let expires_at = match arg(args, "expiresAtMs")? {
        Value::Null => f64::NAN,
        value => value.as_f64().ok_or(ARGS)?,
    };
    let unexpired = !has_expiry || expires_at > now;
    let id = args.get("debuggingId").filter(|value| truthy(Some(value)));
    Ok(match id {
        Some(id) if unexpired => json!({"action": "start", "debuggingId": id}),
        _ => json!({"action": "remove"}),
    })
}

/// Language reconciliation of a restored session. A validated local manual
/// choice that differs from the stored account language is pushed to the
/// server and becomes the effective profile language (only when the server has
/// a stored language); otherwise the account language is applied.
fn language_reconcile(args: &Value) -> Result<Value> {
    let server = optional_text(args, "serverLanguage")?.filter(|language| !language.is_empty());
    let default = optional_text(args, "defaultLanguage")?.filter(|language| !language.is_empty());
    let local = optional_text(args, "localPreferred")?.filter(|language| !language.is_empty());
    let account = server.clone().or(default);
    let push_local = match (&local, &account, &server) {
        (Some(local), Some(account), Some(_)) => local != account,
        _ => false,
    };
    Ok(json!({
        "pushLocal": push_local,
        "applyAccount": if push_local { None } else { account },
        "effectiveIsLocal": push_local,
    }))
}

/// Dispatches the action-decision calls; `None` when `name` is not one of them.
pub(crate) fn call(name: &str, args: &Value) -> Option<Result<Value>> {
    match name {
        "login_verdict" => Some(login_verdict(args)),
        "debug_session_resume" => Some(debug_session_resume(args)),
        "language_reconcile" => Some(language_reconcile(args)),
        _ => None,
    }
}
