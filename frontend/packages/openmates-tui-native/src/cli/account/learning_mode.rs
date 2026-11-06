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
        "learning-mode status" | "learning-mode enable" | "learning-mode disable"
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
            handlers::flags(i, &["age-group", "passcode"])?;
            let group = learning_mode_age_group(i.flags.get("age-group").and_then(Value::as_str))
                .map_err(failed)?;
            let passcode = passcode(i)?;
            client
                .activate_learning_mode(group, passcode)
                .await
                .map_err(|error| request_error("activation", error))?
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
            handlers::flags(i, &["age-group", "passcode"])?;
            let group = learning_mode_age_group(i.flags.get("age-group").and_then(Value::as_str))
                .map_err(failed)?;
            let passcode = passcode(i)?;
            client.set_operation_cancel(cancel);
            client.learning_mode().enable(group, passcode).await?
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
mod tests {
    use super::*;
    use serde_json::json;

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn status_text_matches_the_legacy_lines() {
        assert_eq!(
            status_text(&json!({"enabled":false,"age_group":null,"failed_attempts":0})),
            "Learning Mode: disabled\n"
        );
        assert_eq!(
            status_text(
                &json!({"enabled":true,"age_group":"13_15","failed_attempts":2,
                "deactivation_blocked_until":1_700_000_000})
            ),
            "Learning Mode: enabled\nAge group: 13_15\nFailed disable attempts: 2\nDisable blocked until: 2023-11-14T22:13:20.000Z\n"
        );
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust
    #[test]
    fn errors_keep_the_legacy_codes_and_messages() {
        let err = request_error(
            "activation",
            LearningModeError {
                source: openmates_sdk::Error::Protocol,
                http_status: Some(403),
            },
        );
        assert!(
            matches!(err, CliError::Contract { code: "command_failed", ref message }
            if message == "Learning Mode activation failed with HTTP 403")
        );
        let i = Invocation {
            path: vec!["learning-mode".into(), "disable".into()],
            positionals: vec![],
            flags: [("passcode".to_owned(), json!(""))].into_iter().collect(),
        };
        assert!(
            matches!(passcode(&i), Err(CliError::Contract { ref message, .. })
            if message == "Provide --passcode.")
        );
    }
}
