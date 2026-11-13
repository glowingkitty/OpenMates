//! Single JSON entry point for the web signup, pair and recovery-print policy
//! (`web_auth_signup`, `web_auth_pair`, `web_auth_recovery_print`). One
//! dispatcher keeps the WASM export surface to one function; the shared Worker's
//! auth unit forwards `{name, args}` and returns the JSON result. Pure and
//! synchronous: no IO, no secrets besides the recovery key echoed into the
//! print page, which the caller already holds.
//! spec: specifications/features/auth#auth.pair-login.lifecycle
use super::pair::{self, ActivateInput, PairSessionData};
use super::print::{self, PrintTranslations};
use super::actions;
use super::signup;
use crate::error::{Error, Result};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};

const ARGS: Error = Error::Invalid("flow_args");

fn field<T: DeserializeOwned>(args: &Value, key: &str) -> Result<T> {
    serde_json::from_value(args.get(key).cloned().ok_or(ARGS)?).map_err(|_| ARGS)
}
fn now(args: &Value) -> Result<f64> {
    let now: f64 = field(args, "nowMs")?;
    if now.is_finite() { Ok(now) } else { Err(ARGS) }
}
fn out<T: serde::Serialize>(value: &T) -> Result<Value> { serde_json::to_value(value).map_err(|_| Error::Protocol) }

/// Runs one named policy call. Unknown names and malformed arguments are
/// refused with the stable codes `flow_op` and `flow_args`.
///
/// # Errors
/// `Invalid("flow_op")` for an unknown name, `Invalid("flow_args")` for missing
/// or mistyped arguments.
pub fn flow_call(name: &str, args: &Value) -> Result<Value> {
    if let Some(result) = actions::call(name, args) {
        return result;
    }
    match name {
        "signup_step_from_path" => Ok(json!(signup::step_from_path(&field::<String>(args, "path")?))),
        "signup_path_from_step" => Ok(json!(signup::path_from_step(&field::<String>(args, "step")?))),
        "signup_is_signup_path" => Ok(json!(field::<Option<String>>(args, "path")?.is_some_and(|path| signup::is_signup_path(&path)))),
        "signup_is_settings_step" => Ok(json!(signup::is_settings_step(&field::<String>(args, "step")?))),
        "signup_step_sequence" => Ok(json!(signup::STEP_SEQUENCE)),
        "tfa_apps" => Ok(Value::Array(signup::TFA_APPS.iter().map(|(name, icon)| json!({"name": name, "icon": icon})).collect())),
        "pair_activate" => out(&pair::activate(field::<ActivateInput>(args, "input")?, now(args)?)),
        "pair_view" => out(&pair::view(field::<Option<PairSessionData>>(args, "data")?.as_ref(), now(args)?)),
        "pair_auto_logout_due" => Ok(json!(pair::auto_logout_due(field::<Option<PairSessionData>>(args, "data")?.as_ref(), now(args)?))),
        "pair_is_terminal" => Ok(json!(pair::is_terminal(&field::<String>(args, "status")?))),
        "pair_expired" => Ok(json!(pair::expired(field::<Option<f64>>(args, "expiresAt")?, now(args)?))),
        "pair_error_message" => Ok(json!(pair::error_message(field::<u16>(args, "status")?, args.get("body").unwrap_or(&Value::Null)))),
        "recovery_print_html" => Ok(json!(print::print_page_html(&field::<String>(args, "recoveryKey")?, &field::<PrintTranslations>(args, "translations")?))),
        _ => Err(Error::Invalid("flow_op")),
    }
}
