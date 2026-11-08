//! Plans (and later Tasks/Teams) client decisions for the shared Rust core
//! Worker `work` op (parked wave-5 `work` lane, slice 1: user Plans).
//!
//! spec: specifications/features/plans#plans.content.client-encrypted
//!
//! Mirrors the pure logic of the web `userPlanService.ts`: view projections of
//! decrypted records, user-flow and evidence validation, list/item request
//! paths and every request body. The page keeps `fetch`, WebCrypto, the plan
//! key, the workspace caches and every scope fence. Views: the page decrypts
//! each non-empty `encrypted_*` member itself (same `decryptOptional` rule) and
//! sends the plaintexts in `fields`. Bodies come back as ordered `steps` the
//! page applies in order (plain values, plaintexts to encrypt, page slots), so
//! body key order and encryption call order equal the TS originals and no key
//! bytes ever cross. Refusals the TS code raised as `Error` come back as
//! `{"error": "<same message>"}`. Parity: `plans_ts_vectors.json`
//! (`workPlanVectors.test.ts` regenerates it from the real flag-off service).

mod plan_bodies;
mod plan_flows;
mod plans;
mod task_bodies;
mod tasks;

#[cfg(test)]
mod plans_tests;
#[cfg(test)]
mod tasks_tests;

use serde_json::{Map, Value, json};

/// Result of one decision: the JSON document to return, or a malformed-input error.
pub(crate) type Decision = Result<Value, String>;

/// Runs one named work decision on a JSON document.
///
/// # Errors
/// Returns `unknown_op:<name>` for an unregistered op and `missing_field:<name>`
/// or `bad_field:<name>` for a malformed input document (never a silent default).
pub fn run_json(op: &str, input: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input).map_err(|e| e.to_string())?;
    let output = match op {
        o if o.starts_with("plan") && o.ends_with("View") => plans::run(o, &input),
        o if o.starts_with("plan") => plan_bodies::run(o, &input),
        o if o.starts_with("task") => tasks::run(o, &input),
        _ => Err(format!("unknown_op:{op}")),
    }?;
    serde_json::to_string(&output).map_err(|e| e.to_string())
}

/// Refusal document the TS adapter rethrows as `new Error(message)`.
pub(crate) fn refusal(message: &str) -> Value {
    json!({ "error": message })
}

/// Required input object member.
pub(crate) fn object<'a>(input: &'a Value, name: &str) -> Result<&'a Map<String, Value>, String> {
    input
        .get(name)
        .ok_or_else(|| format!("missing_field:{name}"))?
        .as_object()
        .ok_or_else(|| format!("bad_field:{name}"))
}

/// Required input member of any type.
pub(crate) fn member<'a>(input: &'a Value, name: &str) -> Result<&'a Value, String> {
    input.get(name).ok_or_else(|| format!("missing_field:{name}"))
}

/// JS `record[key] ?? fallback`: a missing or `null` member takes the fallback.
pub(crate) fn or(record: &Map<String, Value>, key: &str, fallback: Value) -> Value {
    match record.get(key) {
        None | Some(Value::Null) => fallback,
        Some(value) => value.clone(),
    }
}

/// JS `record[key] !== undefined` after a JSON hop (`undefined` members are dropped, `null` is kept).
pub(crate) fn defined(record: &Map<String, Value>, key: &str) -> bool {
    record.contains_key(key)
}

/// JS truthiness of an optional member (`undefined` is falsy).
pub(crate) fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0 && !f.is_nan()),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(_) | Value::Object(_)) => true,
    }
}

/// `${value}` of a member inside a TS template literal.
pub(crate) fn template(value: Option<&Value>) -> String {
    value.map_or_else(|| "undefined".to_owned(), crate::web_apps::js_string)
}

/// Copies `record[key]` to `out[name]` when present: a TS `undefined` member
/// stays absent (JSON.stringify and `toEqual` drop it), `null` is kept.
pub(crate) fn copy(out: &mut Map<String, Value>, name: &str, record: &Map<String, Value>, key: &str) {
    if let Some(value) = record.get(key) {
        out.insert(name.to_owned(), value.clone());
    }
}

/// One output member of a record projection.
pub(crate) enum Src {
    /// `record.key` as is (absent stays absent).
    Raw(&'static str),
    /// `record.key ?? fallback`.
    Or(&'static str, Fallback),
    /// The page-decrypted plaintext of `record.key` (`decryptOptional`).
    Text(&'static str),
}

/// Literal fallbacks of `??` defaults in the TS view models.
pub(crate) enum Fallback {
    Null,
    True,
    Zero,
    One,
    EmptyList,
    Str(&'static str),
}

impl Fallback {
    fn value(&self) -> Value {
        match self {
            Fallback::Null => Value::Null,
            Fallback::True => Value::Bool(true),
            Fallback::Zero => json!(0),
            Fallback::One => json!(1),
            Fallback::EmptyList => json!([]),
            Fallback::Str(s) => json!(s),
        }
    }
}

/// `decryptOptional(record[key])` over the page's plaintexts.
///
/// A falsy ciphertext member is `""` (the TS early return). A truthy one must
/// have its plaintext in `fields`: the page decrypts every non-empty string
/// `encrypted_*` member and maps a failed decrypt to `""` itself.
///
/// # Errors
/// `missing_field:fields.<key>` when the page did not send a needed plaintext.
pub(crate) fn text<'a>(
    record: &Map<String, Value>,
    fields: &'a Map<String, Value>,
    key: &str,
) -> Result<&'a str, String> {
    if !truthy(record.get(key)) {
        return Ok("");
    }
    fields
        .get(key)
        .ok_or_else(|| format!("missing_field:fields.{key}"))?
        .as_str()
        .ok_or_else(|| format!("bad_field:fields.{key}"))
}

/// Applies a projection table to one record and its decrypted fields.
pub(crate) fn project(
    record: &Map<String, Value>,
    fields: &Map<String, Value>,
    table: &[(&'static str, Src)],
) -> Result<Map<String, Value>, String> {
    let mut out = Map::new();
    for (name, source) in table {
        match source {
            Src::Raw(key) => copy(&mut out, name, record, key),
            Src::Or(key, fallback) => {
                out.insert((*name).to_owned(), or(record, key, fallback.value()));
            }
            Src::Text(key) => {
                out.insert((*name).to_owned(), json!(text(record, fields, key)?));
            }
        }
    }
    Ok(out)
}

/// The services' `decryptStringArray` over an already decrypted text: empty
/// text is `[]`, a JSON array keeps only its strings, anything else is `[]`.
///
/// # Errors
/// Malformed JSON is refused (the TS `JSON.parse` throws there too).
pub(crate) fn string_array(text: &str, label: &str) -> Result<Value, Value> {
    if text.is_empty() {
        return Ok(json!([]));
    }
    let parsed: Value = serde_json::from_str(text).map_err(|_| refusal(&format!("{label} is not valid JSON")))?;
    Ok(match parsed {
        Value::Array(items) => Value::Array(items.into_iter().filter(Value::is_string).collect()),
        _ => json!([]),
    })
}

/// `new URLSearchParams(pairs).toString()` (application/x-www-form-urlencoded).
pub(crate) fn search_params(pairs: &[(&str, String)]) -> String {
    pairs
        .iter()
        .map(|(name, value)| format!("{}={}", form_encode(name), form_encode(value)))
        .collect::<Vec<_>>()
        .join("&")
}

fn form_encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b' ' => out.push('+'),
            b if b.is_ascii_alphanumeric() || b"*-._".contains(&b) => out.push(b as char),
            b => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Ordered request body the page applies step by step.
///
/// Wire form: `[[name, {"value": v}] | [name, {"encrypt": text, "key": role}]
/// | [name, {"encrypt_input": member, "key": role}] | [name, {"slot": name}]]`.
/// `encrypt_input` means `JSON.stringify(<page input>[member] ?? [])`, so the
/// encrypted JSON text keeps the page's own key order; `slot` is a value only
/// the page can make (key wrappers, the wrapped task key). The page performs
/// the steps sequentially, which keeps the TS encryption call order.
#[derive(Default)]
pub(crate) struct Body(Vec<Value>);

impl Body {
    /// A plain body member.
    pub(crate) fn value(&mut self, name: &str, value: Value) {
        self.0.push(json!([name, { "value": value }]));
    }

    /// A plain member copied only when present (TS `undefined` is dropped by JSON.stringify).
    pub(crate) fn raw(&mut self, name: &str, record: &Map<String, Value>, key: &str) {
        if let Some(value) = record.get(key) {
            self.value(name, value.clone());
        }
    }

    /// A member the page encrypts from this plaintext with the named key.
    pub(crate) fn encrypt(&mut self, name: &str, text: &str, key: &str) {
        self.0.push(json!([name, { "encrypt": text, "key": key }]));
    }

    /// A member the page encrypts from `JSON.stringify(input[member] ?? [])`.
    pub(crate) fn encrypt_input(&mut self, name: &str, member: &str, key: &str) {
        self.0.push(json!([name, { "encrypt_input": member, "key": key }]));
    }

    /// A member only the page can produce.
    pub(crate) fn slot(&mut self, name: &str) {
        self.0.push(json!([name, { "slot": name }]));
    }

    /// The request document: path, method and ordered steps (plus extra facts).
    pub(crate) fn request(self, path: String, method: &str, extra: Map<String, Value>) -> Value {
        let mut out = extra;
        out.insert("path".into(), json!(path));
        out.insert("method".into(), json!(method));
        out.insert("steps".into(), Value::Array(self.0));
        Value::Object(out)
    }
}

/// Required string plaintext of an input member (`input[key]`).
pub(crate) fn input_text<'a>(input: &'a Map<String, Value>, key: &str) -> Result<&'a str, String> {
    input
        .get(key)
        .ok_or_else(|| format!("missing_field:input.{key}"))?
        .as_str()
        .ok_or_else(|| format!("bad_field:input.{key}"))
}

/// `input[key] ?? ""` as a plaintext.
pub(crate) fn input_text_or_empty<'a>(input: &'a Map<String, Value>, key: &str) -> Result<&'a str, String> {
    match input.get(key) {
        None | Some(Value::Null) => Ok(""),
        Some(Value::String(s)) => Ok(s),
        Some(_) => Err(format!("bad_field:input.{key}")),
    }
}

/// `input[key]` when defined: a string plaintext (`null` is not a valid patch text).
pub(crate) fn defined_text<'a>(input: &'a Map<String, Value>, key: &str) -> Result<Option<&'a str>, String> {
    match input.get(key) {
        None => Ok(None),
        Some(Value::String(s)) => Ok(Some(s)),
        Some(_) => Err(format!("bad_field:input.{key}")),
    }
}
