//! Project source remote-access request decisions: preflight, copy/move path checks,
//! the ignored-read approval match, relay acknowledgement and Team routing checks and
//! the HTTP status mapping. Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/remoteAccessPolicy.ts`; fetch, polling and X25519/AES stay in
//! `projectService.ts`. Refusals are `{remoteError: {code, message}}` data.

use super::js::{as_str, is_str, opt_prop, prop, strict_eq, truthy};
use super::{Fault, Outcome, throw};
use serde_json::{Map, Value, json};
use std::collections::HashSet;

/// Largest text read the browser asks a connected source for (`PROJECT_BROWSER_REMOTE_READ_MAX_BYTES`).
const READ_MAX_BYTES: u32 = 180 * 1024;
/// Line cap of a browser text read (`PROJECT_BROWSER_REMOTE_READ_MAX_LINES`).
const READ_MAX_LINES: u32 = 4_000;

/// `{remoteError: {code, message}}`, rethrown by the page as `ProjectRemoteAccessError`.
pub(super) fn refuse(code: &str, message: &str) -> Value {
    json!({ "remoteError": { "code": code, "message": message } })
}

fn ok() -> Value {
    json!({ "ok": true })
}

/// `value.includes(needle)` for an array (SameValueZero) or a string (substring).
fn includes(value: Option<&Value>, needle: &str) -> Result<bool, Fault> {
    match value {
        Some(Value::Array(items)) => Ok(items.iter().any(|item| item.as_str() == Some(needle))),
        Some(Value::String(text)) => Ok(text.contains(needle)),
        _ => Err(Fault::Malformed("bad_field:capabilities".to_owned())),
    }
}

/// `projectRemotePreflight`: offline/capability/identity refusals before a relay request.
pub(super) fn preflight(input: &Value) -> Outcome {
    let operation = input.get("operation");
    let capabilities = input.get("capabilities");
    let args = input.get("args");
    if !is_str(input.get("status"), "connected") {
        return Ok(refuse("source_offline", "This Project source is offline"));
    }
    if is_str(operation, "search")
        && prop(args, "include_content")? == Some(&Value::Bool(true))
        && !includes(capabilities, "read")?
    {
        return Ok(refuse("source_capability_denied", "This Project source does not allow file reads"));
    }
    if !truthy(input.get("hasOwner")) {
        return Ok(refuse("requester_identity_unavailable", "Authenticated user identity is unavailable"));
    }
    let user_file_transfer = is_str(operation, "copy_entries") || is_str(operation, "move_entries");
    if user_file_transfer
        && (prop(args, "user_initiated")? != Some(&Value::Bool(true)) || !includes(capabilities, "write_request")?)
    {
        return Ok(refuse("source_capability_denied", "This source does not allow file changes"));
    }
    let read_limits = if is_str(operation, "read_text") {
        json!({ "max_bytes": READ_MAX_BYTES, "max_lines": READ_MAX_LINES })
    } else {
        Value::Null
    };
    Ok(json!({ "userFileTransfer": user_file_transfer, "readLimits": read_limits }))
}

/// The strict relative path rule of a copy/move entry (no hidden, empty or `..` parts).
fn strict_path(value: Option<&Value>) -> bool {
    let Some(text) = as_str(value) else { return false };
    let len = super::js::len16(text);
    len > 0
        && len <= 4096
        && !text.starts_with('/')
        && !text.contains('\\')
        && text.split('/').all(|part| !part.is_empty() && !part.starts_with('.'))
        && !text.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
}

/// `projectRemoteTransfer`: up to 20 distinct strict paths and a strict destination (or `.`).
pub(super) fn transfer(input: &Value) -> Outcome {
    let destination = input.get("destinationPath");
    let valid = match input.get("paths") {
        Some(Value::Array(paths)) => {
            // `new Set(paths).size`: only strings survive `strictPath`, so string identity suffices
            // whenever the verdict depends on it.
            let distinct: HashSet<String> = paths.iter().map(Value::to_string).collect();
            !paths.is_empty()
                && paths.len() <= 20
                && distinct.len() == paths.len()
                && paths.iter().all(|path| strict_path(Some(path)))
                && (is_str(destination, ".") || strict_path(destination))
        }
        _ => false,
    };
    Ok(if valid { ok() } else { refuse("invalid_path", "Select up to 20 files or folders within this Project") })
}

/// `projectIgnoredRead`: the approval must name this exact read; a mismatch throws.
pub(super) fn ignored_read(input: &Value) -> Outcome {
    let approved = input.get("approved");
    if !is_str(input.get("operation"), "read_text")
        || !strict_eq(input.get("path"), prop(approved, "path")?)
        || !truthy(prop(approved, "chatId")?)
        || !truthy(prop(approved, "operationId")?)
    {
        return Err(throw("The ignored-file approval does not match this exact read"));
    }
    Ok(ok())
}

/// `projectRemoteCreated`: the relay acknowledgement must not name another session/epoch.
pub(super) fn remote_created(input: &Value) -> Outcome {
    let created = input.get("created");
    let session = prop(created, "source_session_id")?;
    let epoch = prop(created, "key_epoch")?;
    if (truthy(session) && !strict_eq(session, input.get("sourceSessionId")))
        || (truthy(epoch) && !strict_eq(epoch, input.get("keyEpoch")))
    {
        return Ok(refuse("source_session_changed", "The Project source session changed. Retry the request"));
    }
    Ok(ok())
}

/// `projectRoutingCreated`: a Team routing acknowledgement needs session, epoch and a team identity.
pub(super) fn routing_created(input: &Value) -> Outcome {
    let created = input.get("created");
    let identity = prop(created, "routing_identity")?;
    if !truthy(prop(created, "source_session_id")?)
        || !truthy(prop(created, "key_epoch")?)
        || !is_str(opt_prop(identity, "context_type"), "team")
    {
        return Ok(refuse("routing_identity_unavailable", "The Team source routing identity is unavailable"));
    }
    Ok(ok())
}

/// `parseRemoteObject`: a JSON object (given as text or value), else `throw errorMessage`.
pub(super) fn parse_remote_object(value: Option<&Value>, message: &str) -> Result<Map<String, Value>, Fault> {
    let parsed = match value {
        Some(Value::String(text)) => serde_json::from_str::<Value>(text).ok(),
        other => other.cloned(),
    };
    match parsed {
        Some(Value::Object(map)) => Ok(map),
        _ => Err(throw(message)),
    }
}

/// `projectRoutingResult`: the decrypted discovery answer must echo the request nonce.
pub(super) fn routing_result(input: &Value) -> Outcome {
    let discovery = parse_remote_object(input.get("discovery"), "The Team source routing response is invalid")?;
    if !is_str(discovery.get("type"), "routing_discovery_result") || !strict_eq(discovery.get("nonce"), input.get("nonce")) {
        return Ok(refuse("routing_identity_invalid", "The Team source routing response is invalid"));
    }
    Ok(ok())
}

/// `projectRemoteHttpError`: relay HTTP status (and 409 detail) to a typed refusal.
pub(super) fn http_error(input: &Value) -> Outcome {
    let status = input.get("status").and_then(Value::as_f64);
    let is = |code: f64| status == Some(code);
    // A valid login can outlive its server-side per-session device binding; only this
    // exact backend code asks the user to establish a new login.
    Ok(if is(409.0) && is_str(input.get("detail"), "REQUESTER_DEVICE_IDENTITY_UNAVAILABLE") {
        refuse("requester_device_identity_unavailable", "Sign out and sign in again to reconnect this Project source")
    } else if is(401.0) || is(403.0) {
        refuse("access_revoked", "You no longer have access to this Project source")
    } else if is(404.0) {
        refuse("source_offline", "This Project source is unavailable")
    } else if is(409.0) {
        refuse("source_offline", "This Project source changed or disconnected. Refresh and try again")
    } else if is(429.0) {
        refuse("rate_limited", "Too many Project source requests. Try again shortly")
    } else {
        refuse("operation_failed", "The Project source request failed")
    })
}
