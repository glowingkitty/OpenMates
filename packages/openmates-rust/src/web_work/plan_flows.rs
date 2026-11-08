//! Plan user-flow and evidence-reference validation (shared Rust core `work` op).
//!
//! spec: specifications/features/plans#plans.content.client-encrypted
//!
//! Mirrors `validateUserFlows` / `validateEvidenceReference` of the web
//! `userPlanService.ts`, including the JS truthiness checks and the TypeErrors
//! the TS code throws on `null` steps or references. The page encrypts its own
//! flow JSON text after this passes, so the ciphertext keeps the TS key order.

use serde_json::Value;
use url::Url;

use super::{refusal, truthy};

const NOT_ARRAY: &str = "Plan user flows must be an array";
const NOT_OBJECT: &str = "Each Plan user flow must be an object";
const INCOMPLETE: &str = "Each Plan user flow requires flow_id, title, ordered steps, and expected_outcome";
const BAD_IDENTIFIER: &str = "Plan evidence references require a valid embed ID or repository-relative path";

/// JS property read: only objects carry named members (arrays and primitives read `undefined`).
fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(key))
}

/// The TypeError V8 raises for `null.<key>`.
fn null_read(key: &str) -> Value {
    refusal(&format!("Cannot read properties of null (reading '{key}')"))
}

/// `Number.isInteger(value)` of a JSON value.
fn integer(value: &Value) -> Option<f64> {
    value.as_f64().filter(|number| number.fract() == 0.0 && number.is_finite())
}

/// `validateUserFlows(flows)`: `Ok` when the TS function returns its input.
///
/// # Errors
/// The refusal document carrying the TS error message.
pub(crate) fn validate_user_flows(flows: &Value) -> Result<(), Value> {
    let flows = flows.as_array().ok_or_else(|| refusal(NOT_ARRAY))?;
    for flow in flows {
        // `typeof [] === 'object'`, so an array passes this check and fails the next one.
        if !truthy(Some(flow)) || !(flow.is_object() || flow.is_array()) {
            return Err(refusal(NOT_OBJECT));
        }
        let steps = get(flow, "steps").and_then(Value::as_array);
        let complete = truthy(get(flow, "flow_id"))
            && truthy(get(flow, "title"))
            && truthy(get(flow, "expected_outcome"))
            && steps.is_some();
        let Some(steps) = steps.filter(|_| complete) else {
            return Err(refusal(INCOMPLETE));
        };
        for step in steps {
            if step.is_null() {
                return Err(null_read("step_id"));
            }
            if !truthy(get(step, "step_id")) || !truthy(get(step, "text")) {
                return Err(refusal(INCOMPLETE));
            }
        }
        for step in steps {
            match get(step, "references") {
                None | Some(Value::Null) => {}
                Some(Value::Array(references)) => {
                    for reference in references {
                        validate_evidence_reference(reference)?;
                    }
                }
                // A string iterates its characters; each reads `kind`/`path` as undefined.
                Some(Value::String(s)) if s.is_empty() => {}
                Some(Value::String(_)) => return Err(refusal(BAD_IDENTIFIER)),
                Some(_) => return Err(refusal("step.references is not iterable")),
            }
        }
    }
    Ok(())
}

/// `validateEvidenceReference(reference)`.
fn validate_evidence_reference(reference: &Value) -> Result<(), Value> {
    if reference.is_null() {
        return Err(null_read("kind"));
    }
    let kind = get(reference, "kind").and_then(Value::as_str);
    if kind == Some("url") {
        // `new URL(String(reference.url))`: the WHATWG parser of the `url` crate.
        let href = super::template(get(reference, "url"));
        let parsed = Url::parse(&href).map_err(|_| refusal("Invalid URL"))?;
        if parsed.scheme() != "https" {
            return Err(refusal("Plan evidence URLs must use HTTPS"));
        }
        return Ok(());
    }
    let identifier = if kind == Some("embed") { get(reference, "embed_id") } else { get(reference, "path") };
    if !truthy(identifier) {
        return Err(refusal(BAD_IDENTIFIER));
    }
    if kind == Some("file") {
        let path = identifier
            .and_then(Value::as_str)
            .ok_or_else(|| refusal("identifier.startsWith is not a function"))?;
        if path.starts_with('/') || path.split('/').any(|part| part == "..") {
            return Err(refusal(BAD_IDENTIFIER));
        }
    }
    let start = get(reference, "start_line");
    if let Some(start) = start
        && integer(start).is_none_or(|line| line < 1.0)
    {
        return Err(refusal("Plan evidence start_line must be positive"));
    }
    if let Some(end) = get(reference, "end_line") {
        let floor = start.and_then(integer).unwrap_or(1.0);
        if integer(end).is_none_or(|line| line < floor) {
            return Err(refusal("Plan evidence end_line must follow start_line"));
        }
    }
    Ok(())
}

/// `decryptUserFlows` over an already decrypted text.
///
/// # Errors
/// Malformed JSON, a non-array document or an invalid flow (TS messages).
pub(crate) fn parse_user_flows(text: &str) -> Result<Value, Value> {
    if text.is_empty() {
        return Ok(Value::Array(Vec::new()));
    }
    let parsed: Value = serde_json::from_str(text).map_err(|_| refusal("Plan user flows are not valid JSON"))?;
    if !parsed.is_array() {
        return Err(refusal(NOT_ARRAY));
    }
    validate_user_flows(&parsed)?;
    Ok(parsed)
}
