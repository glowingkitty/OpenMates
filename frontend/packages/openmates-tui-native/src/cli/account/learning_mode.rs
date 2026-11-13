//! `learning-mode status|enable|disable` with the legacy CLI's flags, messages,
//! JSON and text. The passcode is forwarded to the SDK request only.
use super::settings_more::text_output;
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use openmates_sdk::client::learning_mode::{LearningModeError, learning_mode_age_group};
use openmates_sdk::sdk::OpenMates;
use serde_json::Value;
use tokio_util::sync::CancellationToken;

pub(super) fn supported(invocation: &Invocation) -> bool {
    matches!(
        invocation.command_path().as_str(),
        "learning-mode status"
            | "learning-mode enable"
            | "learning-mode collaborative"
            | "learning-mode disable"
    )
}
fn failed(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
/// Legacy `parseRequiredStringFlag`: a non-empty string value is required.
fn passcode(i: &Invocation) -> Result<&str, CliError> {
    i.flags
        .get("passcode")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| failed("Provide --passcode."))
}
/// `--collaborative-build` / `--no-collaborative-build`; neither => `None`
/// so the backend default (on, except forced off for `under_10`) applies.
fn collaborative_build_flag(i: &Invocation) -> Result<Option<bool>, CliError> {
    match (
        i.boolean("collaborative-build"),
        i.boolean("no-collaborative-build"),
    ) {
        (true, true) => Err(failed(
            "Use only one of --collaborative-build and --no-collaborative-build.",
        )),
        (true, false) => Ok(Some(true)),
        (false, true) => Ok(Some(false)),
        (false, false) => Ok(None),
    }
}
/// `learning-mode collaborative <on|off>`: returns the target state and the
/// passcode, which is mandatory only when turning it on (the server refuses
/// an unauthenticated enable, disabling needs no proof).
fn collaborative_args(i: &Invocation) -> Result<(bool, Option<&str>), CliError> {
    let enabled = match i.positionals.first().map(String::as_str) {
        Some("on") => true,
        Some("off") => false,
        _ => {
            return Err(failed(
                "Provide on or off: openmates learning-mode collaborative on|off [--passcode <passcode>].",
            ));
        }
    };
    let passcode = i
        .flags
        .get("passcode")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty());
    if enabled && passcode.is_none() {
        return Err(failed("Provide --passcode."));
    }
    Ok((enabled, passcode))
}
fn request_error(action: &str, error: LearningModeError) -> CliError {
    match error.http_status {
        Some(status) => failed(format!("Learning Mode {action} failed with HTTP {status}")),
        None => error.source.into(),
    }
}
/// Legacy `new Date(seconds * 1000).toISOString()`.
fn iso(seconds: f64) -> Option<String> {
    let nanos = (seconds * 1000.0).round() as i128 * 1_000_000;
    let at = time::OffsetDateTime::from_unix_timestamp_nanos(nanos).ok()?;
    Some(format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        at.year(),
        u8::from(at.month()),
        at.day(),
        at.hour(),
        at.minute(),
        at.second(),
        at.millisecond()
    ))
}
fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(number) => number.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Value::String(text) => !text.is_empty(),
        _ => true,
    }
}
fn status_text(status: &Value) -> String {
    let mut out = format!(
        "Learning Mode: {}\n",
        if truthy(&status["enabled"]) {
            "enabled"
        } else {
            "disabled"
        }
    );
    if truthy(&status["age_group"]) {
        let group = match &status["age_group"] {
            Value::String(text) => text.clone(),
            other => other.to_string(),
        };
        out.push_str(&format!(
            "Age group: {}\n",
            super::super::terminal_text(&group)
        ));
    }
    if truthy(&status["enabled"]) {
        if let Some(on) = status["collaborative_build"].as_bool() {
            out.push_str(&format!(
                "Collaborative build: {}\n",
                if on { "on" } else { "off" }
            ));
        }
    }
    if let Some(attempts) = status["failed_attempts"].as_f64().filter(|n| *n > 0.0) {
        out.push_str(&format!(
            "Failed disable attempts: {}\n",
            status["failed_attempts"]
                .as_number()
                .map(ToString::to_string)
                .unwrap_or_else(|| attempts.to_string())
        ));
    }
    if let Some(until) = status["deactivation_blocked_until"]
        .as_f64()
        .filter(|n| *n != 0.0)
        .and_then(iso)
    {
        out.push_str(&format!("Disable blocked until: {until}\n"));
    }
    out
}
pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    let status = match i.command_path().as_str() {
        "learning-mode status" => {
            handlers::flags(i, &[])?;
            client
                .learning_mode_status()
                .await
                .map_err(|error| request_error("status", error))?
        }
        "learning-mode enable" => {
            handlers::flags(
                i,
                &[
                    "age-group",
                    "passcode",
                    "collaborative-build",
                    "no-collaborative-build",
                ],
            )?;
            let group = learning_mode_age_group(i.flags.get("age-group").and_then(Value::as_str))
                .map_err(failed)?;
            let passcode = passcode(i)?;
            let collaborative_build = collaborative_build_flag(i)?;
            client
                .activate_learning_mode(group, passcode, collaborative_build)
                .await
                .map_err(|error| request_error("activation", error))?
        }
        "learning-mode collaborative" => {
            handlers::flags(i, &["passcode"])?;
            let (enabled, passcode) = collaborative_args(i)?;
            client
                .set_learning_mode_collaborative(enabled, passcode)
                .await
                .map_err(|error| request_error("collaborative build update", error))?
        }
        _ => {
            handlers::flags(i, &["passcode"])?;
            let passcode = passcode(i)?;
            client
                .deactivate_learning_mode(passcode)
                .await
                .map_err(|error| request_error("deactivation", error))?
        }
    };
    render(i, &status)
}
fn render(i: &Invocation, status: &Value) -> Result<CliOutput, CliError> {
    if i.boolean("json") {
        CliOutput::json(status)
    } else {
        Ok(text_output(status_text(status)))
    }
}

/// Explicit API-key variant: the same flags, validation and rendering over the
/// shared SDK `/v1/sdk/learning-mode` routes. No session or profile is read.
/// HTTP failures surface as typed SDK errors.
pub(super) async fn execute_key(
    i: &Invocation,
    client: &mut OpenMates,
    cancel: CancellationToken,
) -> Result<CliOutput, CliError> {
    let status = match i.command_path().as_str() {
        "learning-mode status" => {
            handlers::flags(i, &[])?;
            client.set_operation_cancel(cancel);
            client.learning_mode().status().await?
        }
        "learning-mode enable" => {
            handlers::flags(
                i,
                &[
                    "age-group",
                    "passcode",
                    "collaborative-build",
                    "no-collaborative-build",
                ],
            )?;
            let group = learning_mode_age_group(i.flags.get("age-group").and_then(Value::as_str))
                .map_err(failed)?;
            let passcode = passcode(i)?;
            let collaborative_build = collaborative_build_flag(i)?;
            client.set_operation_cancel(cancel);
            client
                .learning_mode()
                .enable(group, passcode, collaborative_build)
                .await?
        }
        "learning-mode collaborative" => {
            handlers::flags(i, &["passcode"])?;
            let (enabled, passcode) = collaborative_args(i)?;
            client.set_operation_cancel(cancel);
            client
                .learning_mode()
                .collaborative(enabled, passcode)
                .await?
        }
        _ => {
            handlers::flags(i, &["passcode"])?;
            let passcode = passcode(i)?;
            client.set_operation_cancel(cancel);
            client.learning_mode().disable(passcode).await?
        }
    };
    render(i, &status)
}

#[cfg(test)]
#[path = "learning_mode_tests.rs"]
mod tests;
