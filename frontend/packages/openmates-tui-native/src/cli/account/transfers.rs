//! Non-JSON transfer commands: invoice/credit-note and Team profile-image
//! downloads, profile-image and Images AI-detection uploads, and the
//! notification SSE stream. Shared Rust owns the authenticated binary, SSE and
//! multipart transport plus metadata removal; this adapter keeps npm's local
//! file handling, messages, output shapes and exit codes.
use super::super::global_history::{js_number, js_number_string, js_string};
use super::super::terminal_text;
use super::{CliError, CliOutput, Invocation, handlers};
use crate::client::Client;
use crate::client::upload::UploadError;
use serde::{Serialize, Serializer, ser::SerializeMap, ser::SerializeSeq};
use serde_json::Value;

mod downloads;
mod stream;
mod uploads;

pub(super) const COMMANDS: &[&str] = &[
    "teams profile-image get",
    "teams profile-image upload",
    "account profile-picture set",
    "settings account profile-picture set",
    "settings billing invoices download",
    "settings billing invoices credit-note",
    "settings notifications stream",
    "apps images detect-ai",
    "apps images detect_ai",
];

const METADATA_WARNING: &str =
    "Warning: Could not remove embedded file metadata; uploading the original file.\n";

pub(super) fn supported(i: &Invocation) -> bool {
    COMMANDS.contains(&i.command_path().as_str())
}

pub(super) async fn execute(i: &Invocation, client: &mut Client) -> Result<CliOutput, CliError> {
    match i.command_path().as_str() {
        "teams profile-image get" => downloads::team_profile_image(i, client).await,
        "teams profile-image upload" => uploads::team_profile_image(i, client).await,
        "account profile-picture set" | "settings account profile-picture set" => {
            uploads::profile_picture(i, client).await
        }
        "settings billing invoices download" => downloads::invoice(i, client, false).await,
        "settings billing invoices credit-note" => downloads::invoice(i, client, true).await,
        "settings notifications stream" => stream::notifications(i, client).await,
        _ => uploads::detect_ai(i, client).await,
    }
}

/// A thrown npm `Error`: the message on stderr and exit 1.
fn failed(message: impl Into<String>) -> CliError {
    CliError::Contract {
        code: "command_failed",
        message: message.into(),
    }
}
fn upload_error(error: UploadError) -> CliError {
    match error {
        UploadError::Rejected(message) => failed(message),
        UploadError::Client(error) => CliError::Client(error),
    }
}
fn output(stdout: String, stderr: String) -> CliOutput {
    CliOutput {
        stdout,
        stderr,
        exit_code: 0,
    }
}

/// npm `requiredStringFlag`: a non-empty string, trimmed.
fn required(value: Option<&str>, label: &str) -> Result<String, CliError> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or_else(|| failed(format!("Missing {label}.")))
}
/// `flags.a ?? flags.b ?? positional`: a present flag wins even when it is
/// not a string (then `requiredStringFlag` reports it missing).
fn first_of<'a>(i: &'a Invocation, names: &[&str], positional: Option<usize>) -> Option<&'a str> {
    for name in names {
        if i.has(name) {
            return i.text(name);
        }
    }
    positional.and_then(|index| i.positionals.get(index).map(String::as_str))
}

/// JavaScript `encodeURIComponent`.
fn encode_uri_component(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}
/// A path segment that cannot address a different API route after URL
/// normalization (`.`/`..` would be resolved away by the URL parser).
fn path_segment(value: &str, label: &str) -> Result<String, CliError> {
    if matches!(value, "." | "..") {
        return Err(CliError::Invalid(format!("Invalid {label}.")));
    }
    Ok(encode_uri_component(value))
}

/// Node `fs.readFileSync` failure text for the common cases.
fn read_error_text(path: &str, error: &std::io::Error) -> String {
    match error.kind() {
        std::io::ErrorKind::NotFound => {
            format!("ENOENT: no such file or directory, open '{path}'")
        }
        std::io::ErrorKind::PermissionDenied => format!("EACCES: permission denied, open '{path}'"),
        std::io::ErrorKind::IsADirectory => {
            "EISDIR: illegal operation on a directory, read".to_owned()
        }
        _ => format!("Could not read file '{path}'."),
    }
}
fn read_file(path: &str) -> Result<Vec<u8>, CliError> {
    std::fs::read(path).map_err(|error| failed(read_error_text(path, &error)))
}
/// Node `path.basename` for POSIX paths.
fn basename(path: &str) -> &str {
    let trimmed = path.trim_end_matches('/');
    if trimmed.is_empty() {
        return "";
    }
    trimmed.rsplit('/').next().unwrap_or(trimmed)
}

/// `JSON.stringify(value, null, 2)` for objects whose key order is part of
/// the npm output. Nested server objects keep the decoded (sorted) order.
struct Js<'a>(&'a Value);
impl Serialize for Js<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self.0 {
            Value::Null => serializer.serialize_unit(),
            Value::Bool(value) => serializer.serialize_bool(*value),
            Value::String(value) => serializer.serialize_str(value),
            Value::Number(value) => match value.as_f64().filter(|n| n.is_finite()) {
                Some(number) => serde_json::value::RawValue::from_string(js_number_string(number))
                    .map_err(serde::ser::Error::custom)?
                    .serialize(serializer),
                None => serializer.serialize_unit(),
            },
            Value::Array(values) => {
                let mut sequence = serializer.serialize_seq(Some(values.len()))?;
                for value in values {
                    sequence.serialize_element(&Js(value))?;
                }
                sequence.end()
            }
            Value::Object(values) => {
                let mut object = serializer.serialize_map(Some(values.len()))?;
                for (key, value) in values {
                    object.serialize_entry(key, &Js(value))?;
                }
                object.end()
            }
        }
    }
}
struct Ordered<'a>(&'a [(&'a str, Value)]);
impl Serialize for Ordered<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut object = serializer.serialize_map(Some(self.0.len()))?;
        for (key, value) in self.0 {
            object.serialize_entry(key, &Js(value))?;
        }
        object.end()
    }
}
fn pretty<T: Serialize>(value: &T) -> Result<String, CliError> {
    let mut text = serde_json::to_string_pretty(value)
        .map_err(|_| CliError::Client(crate::error::Error::Protocol))?;
    text.push('\n');
    Ok(text)
}
/// `printJson({...})` with npm's insertion order.
fn ordered_json(entries: &[(&str, Value)]) -> Result<String, CliError> {
    pretty(&Ordered(entries))
}
/// `printJson(value)` for a decoded server value.
fn value_json(value: &Value) -> Result<String, CliError> {
    pretty(&Js(value))
}

/// npm `parseRequiredNumber`.
fn required_number(i: &Invocation, name: &str) -> Result<f64, CliError> {
    let label = format!("--{name}");
    let Some(text) = i.flags.get(name).and_then(Value::as_str) else {
        return Err(failed(format!("Missing {label}.")));
    };
    let number = js_number(text);
    if !number.is_finite() {
        return Err(failed(format!("Invalid {label}: {text}")));
    }
    Ok(number)
}

/// JavaScript `Number.prototype.toFixed(1)` (ties round away from zero).
fn to_fixed_1(value: f64) -> String {
    let magnitude = value.abs() * 10.0;
    let quarter = value.abs() * 4.0;
    // Only k/4 values with odd k sit exactly halfway between two tenths.
    let tie = quarter.fract() == 0.0 && (quarter as u64) % 2 == 1;
    let rounded = if tie {
        (magnitude.floor() + 1.0) / 10.0
    } else {
        value.abs()
    };
    let sign = if value < 0.0 { "-" } else { "" };
    format!("{sign}{rounded:.1}")
}

#[cfg(test)]
mod tests;
