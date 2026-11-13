//! Apps skill input validation with the web form's JSON-schema semantics.
//!
//! Shared core: the one client-side pre-dispatch validator for Apps skill input,
//! used by the web shared Worker `apps` unit (request flow) and the native CLI
//! direct skill path (`client/apps.rs`). It mirrors `validateSkillInput` and
//! `resolveSkillSchema` of `appsSkillFormUtils.ts` exactly, including their JS
//! coercions; `schema_ts_vectors.json` proves parity. The backend stays
//! the authoritative validator. Spec: feature.apps-workspace (apps.requests).
//! The live form (AppsSkillForm.svelte) keeps `validateSkillInput` in TS: it runs
//! synchronously inside a Svelte `$derived` on every keystroke, a Worker call is
//! async and main-thread WASM is forbidden; the vectors keep the two in lockstep.
use serde_json::{Map, Value};
use std::borrow::Cow;

use super::{js_string, truthy};

/// One validation issue: the dotted/indexed input path and a stable code
/// (`required`, `type`, `minimum`, `maximum`, `minLength`, `maxLength`,
/// `minItems`, `maxItems`, `enum`, `pattern`), in the TS walk order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SkillValidationIssue {
    /// `requests[0].query` style path; the root is the empty string.
    pub path: String,
    /// Stable issue code shared with the web form.
    pub code: &'static str,
}

/// `value && typeof value === 'object' && !Array.isArray(value) ? value : {}`.
fn object(value: Option<&Value>) -> Option<&Map<String, Value>> {
    value.and_then(Value::as_object)
}

/// Object spread of a resolved `$ref` target: arrays spread their indices.
fn spread(value: &Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map.clone(),
        Value::Array(items) => items
            .iter()
            .enumerate()
            .map(|(i, v)| (i.to_string(), v.clone()))
            .collect(),
        _ => Map::new(),
    }
}

/// A schema node as the TS code sees it: any non-object behaves like `{}`.
fn node(value: &Value) -> Cow<'_, Map<String, Value>> {
    match value {
        Value::Object(map) => Cow::Borrowed(map),
        _ => Cow::Owned(Map::new()),
    }
}

/// `schema.anyOf ?? schema.oneOf` (null and absent are nullish).
fn variants(schema: &Map<String, Value>) -> Option<&Value> {
    schema
        .get("anyOf")
        .filter(|v| !v.is_null())
        .or_else(|| schema.get("oneOf").filter(|v| !v.is_null()))
}

fn type_is(schema: &Map<String, Value>, kind: &str) -> bool {
    schema.get("type").and_then(Value::as_str) == Some(kind)
}

/// `resolveSkillSchema(schema, root, seen)`: local `$ref` merge (target first,
/// node keys win) and single non-null `anyOf`/`oneOf` collapse.
fn resolve<'a>(
    schema: Cow<'a, Map<String, Value>>,
    root: &Value,
    seen: &[String],
) -> Cow<'a, Map<String, Value>> {
    if let Some(reference) = schema.get("$ref").filter(|r| truthy(Some(r))) {
        let reference = js_string(reference);
        if !reference.starts_with("#/") || seen.contains(&reference) {
            return schema;
        }
        let mut target: Option<&Value> = Some(root);
        for part in reference[2..].split('/') {
            let key = part.replace("~1", "/").replace("~0", "~");
            target = object(target).and_then(|map| map.get(&key));
        }
        let Some(target) = target.filter(|t| t.is_object() || t.is_array()) else {
            return schema;
        };
        let mut merged = spread(target);
        for (key, value) in schema.iter() {
            merged.insert(key.clone(), value.clone());
        }
        merged.remove("$ref");
        let mut next = seen.to_vec();
        next.push(reference);
        return Cow::Owned(resolve(Cow::Owned(merged), root, &next).into_owned());
    }
    if let Some(Value::Array(parts)) = variants(&schema)
        && !parts.is_empty()
    {
        let non_null: Vec<&Value> = parts
            .iter()
            .filter(|part| !type_is(&node(part), "null"))
            .collect();
        if non_null.len() == 1 {
            let mut merged = resolve(node(non_null[0]), root, seen).into_owned();
            for (key, value) in schema.iter() {
                merged.insert(key.clone(), value.clone());
            }
            merged.remove("anyOf");
            merged.remove("oneOf");
            return Cow::Owned(merged);
        }
    }
    schema
}

/// JS `StringToNumber`.
fn string_to_number(text: &str) -> f64 {
    let trimmed = super::request::js_trim(text);
    if trimmed.is_empty() {
        return 0.0;
    }
    let unsigned = trimmed.strip_prefix(['+', '-']).unwrap_or(trimmed);
    let negative = trimmed.starts_with('-');
    if unsigned == "Infinity" {
        return if negative {
            f64::NEG_INFINITY
        } else {
            f64::INFINITY
        };
    }
    for (prefix, radix) in [
        ("0x", 16),
        ("0X", 16),
        ("0o", 8),
        ("0O", 8),
        ("0b", 2),
        ("0B", 2),
    ] {
        if let Some(digits) = trimmed.strip_prefix(prefix) {
            return if !digits.is_empty() && digits.chars().all(|c| c.is_digit(radix)) {
                digits.chars().fold(0.0, |acc, c| {
                    acc * f64::from(radix) + f64::from(c.to_digit(radix).unwrap_or(0))
                })
            } else {
                f64::NAN
            };
        }
    }
    // Rust also accepts "inf"/"nan"; JS only digits, one dot and an exponent.
    if !unsigned
        .bytes()
        .all(|b| b.is_ascii_digit() || b"eE.+-".contains(&b))
        || !unsigned.bytes().any(|b| b.is_ascii_digit())
    {
        return f64::NAN;
    }
    trimmed.parse::<f64>().unwrap_or(f64::NAN)
}

/// JS `ToNumber` of a schema keyword value (objects through `ToPrimitive`).
/// ECMAScript `ToNumber` for JSON values (arrays/objects via their `String()` form).
pub(super) fn to_number(value: &Value) -> f64 {
    match value {
        Value::Null => 0.0,
        Value::Bool(b) => f64::from(u8::from(*b)),
        Value::Number(n) => n.as_f64().unwrap_or(f64::NAN),
        Value::String(s) => string_to_number(s),
        other => string_to_number(&js_string(other)),
    }
}

/// `keyword !== undefined && actual < keyword` (NaN compares false).
fn below(schema: &Map<String, Value>, keyword: &str, actual: f64) -> bool {
    schema
        .get(keyword)
        .is_some_and(|limit| actual < to_number(limit))
}
fn above(schema: &Map<String, Value>, keyword: &str, actual: f64) -> bool {
    schema
        .get(keyword)
        .is_some_and(|limit| actual > to_number(limit))
}

/// `item === value` for a JSON enum member (objects never compare equal).
fn strict_equal(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Number(x), Value::Number(y)) => x.as_f64() == y.as_f64(),
        (Value::String(x), Value::String(y)) => x == y,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::Null, Value::Null) => true,
        _ => false,
    }
}

/// `(field.required ?? []).includes(name)`; a string `required` is a substring test.
fn is_required(schema: &Map<String, Value>, name: &str) -> bool {
    match schema.get("required") {
        Some(Value::Array(names)) => names.iter().any(|n| n.as_str() == Some(name)),
        Some(Value::String(names)) => names.contains(name),
        _ => false,
    }
}

/// Hidden member [`parse_schema`] adds to every `properties` object: its keys in
/// JS own-property order. serde_json maps are sorted, but the TS walk (and so the
/// issue order) follows the schema's own key order.
const KEY_ORDER: &str = "\u{0}order";

/// `Object.entries(field.properties ?? {})`, in JS order when the schema came
/// through [`parse_schema`] (sorted otherwise, which only the order of issues sees).
fn properties(schema: &Map<String, Value>) -> Vec<(String, &Value)> {
    match schema.get("properties") {
        Some(Value::Object(map)) => match map.get(KEY_ORDER).and_then(Value::as_array) {
            Some(order) => order
                .iter()
                .filter_map(Value::as_str)
                .filter_map(|key| map.get(key).map(|value| (key.to_owned(), value)))
                .collect(),
            None => map.iter().map(|(k, v)| (k.clone(), v)).collect(),
        },
        Some(Value::Array(items)) => items
            .iter()
            .enumerate()
            .map(|(i, v)| (i.to_string(), v))
            .collect(),
        _ => Vec::new(),
    }
}

/// `new RegExp(pattern).test(text)`; `None` when the pattern does not compile
/// (the TS form ignores malformed metadata; the backend rejects it).
#[cfg(target_arch = "wasm32")]
fn pattern_matches(pattern: &str, text: &str) -> Option<bool> {
    use wasm_bindgen::{JsCast, JsValue};
    // The Worker realm's own RegExp: exact ECMAScript syntax and semantics.
    let constructor = js_sys::Reflect::get(&js_sys::global(), &JsValue::from_str("RegExp")).ok()?;
    let constructor: js_sys::Function = constructor.dyn_into().ok()?;
    let compiled = js_sys::Reflect::construct(
        &constructor,
        &js_sys::Array::of1(&JsValue::from_str(pattern)),
    )
    .ok()?;
    Some(compiled.dyn_into::<js_sys::RegExp>().ok()?.test(text))
}

/// Native CLI: the `regex` crate. ECMAScript-only syntax (lookaround,
/// backreferences) does not compile here and is skipped, as an invalid pattern is.
#[cfg(not(target_arch = "wasm32"))]
fn pattern_matches(pattern: &str, text: &str) -> Option<bool> {
    if pattern.len() > 4096 {
        return None;
    }
    regex::Regex::new(pattern)
        .ok()
        .map(|compiled| compiled.is_match(text))
}

struct Walker<'r> {
    root: &'r Value,
    issues: Vec<SkillValidationIssue>,
}

impl Walker<'_> {
    fn push(&mut self, path: &str, code: &'static str) {
        self.issues.push(SkillValidationIssue {
            path: path.to_owned(),
            code,
        });
    }

    /// `walk(node, value, path, required)`; `None` is `undefined` (absent key).
    fn walk(&mut self, raw: &Value, value: Option<&Value>, path: &str, required: bool) {
        let unresolved = node(raw);
        let field = resolve(unresolved.clone(), self.root, &[]);
        let Some(value) = value else {
            if required {
                self.push(path, "required");
            }
            return;
        };
        if value.is_null() {
            let nullable = type_is(&unresolved, "null")
                || matches!(variants(&unresolved), Some(Value::Array(parts)) if parts.iter().any(|p| type_is(&node(p), "null")));
            if !nullable {
                self.push(path, if required { "required" } else { "type" });
            }
            return;
        }
        if value.as_str() == Some("") {
            if required {
                self.push(path, "required");
            }
            return;
        }
        if let Some(choices) = field.get("enum").filter(|e| truthy(Some(e)))
            && let Some(choices) = choices.as_array()
            && !choices.iter().any(|item| strict_equal(item, value))
        {
            self.push(path, "enum");
        }
        let kind = field.get("type");
        if type_is(&field, "object") || truthy(field.get("properties")) {
            let Some(object) = value.as_object() else {
                self.push(path, "type");
                return;
            };
            for (name, child) in properties(&field) {
                let child_path = if path.is_empty() {
                    name.clone()
                } else {
                    format!("{path}.{name}")
                };
                self.walk(
                    child,
                    object.get(&name),
                    &child_path,
                    is_required(&field, &name),
                );
            }
        } else if type_is(&field, "array") {
            let Some(items) = value.as_array() else {
                self.push(path, "type");
                return;
            };
            let length = items.len() as f64;
            if below(&field, "minItems", length) {
                self.push(path, "minItems");
            }
            if above(&field, "maxItems", length) {
                self.push(path, "maxItems");
            }
            let empty = Value::Object(Map::new());
            let item_schema = field
                .get("items")
                .filter(|i| !i.is_null())
                .unwrap_or(&empty)
                .clone();
            for (index, item) in items.iter().enumerate() {
                self.walk(&item_schema, Some(item), &format!("{path}[{index}]"), true);
            }
        } else if type_is(&field, "integer") || type_is(&field, "number") {
            let Some(number) = value.as_f64() else {
                self.push(path, "type");
                return;
            };
            if type_is(&field, "integer") && number.fract() != 0.0 {
                self.push(path, "type");
                return;
            }
            if below(&field, "minimum", number) {
                self.push(path, "minimum");
            }
            if above(&field, "maximum", number) {
                self.push(path, "maximum");
            }
        } else if type_is(&field, "boolean") {
            if !value.is_boolean() {
                self.push(path, "type");
            }
        } else if type_is(&field, "string") || !truthy(kind) {
            let Some(text) = value.as_str() else {
                self.push(path, "type");
                return;
            };
            // `String.prototype.length` counts UTF-16 code units.
            let length = text.encode_utf16().count() as f64;
            if below(&field, "minLength", length) {
                self.push(path, "minLength");
            }
            if above(&field, "maxLength", length) {
                self.push(path, "maxLength");
            }
            if let Some(pattern) = field.get("pattern").filter(|p| truthy(Some(p)))
                && pattern_matches(&js_string(pattern), text) == Some(false)
            {
                self.push(path, "pattern");
            }
        }
    }
}

/// Validate Apps skill input against its `input_schema` with the web form's
/// semantics: `""` and absent count as missing, `null` only for nullable
/// fields, `$ref`/single-variant resolution, then type and bound checks. Returns
/// the issues in walk order; empty means the input may be dispatched.
pub fn validate_skill_input(schema: &Value, input: &Value) -> Vec<SkillValidationIssue> {
    let mut walker = Walker {
        root: schema,
        issues: Vec::new(),
    };
    walker.walk(schema, Some(input), "", true);
    walker.issues
}

/// JSON adapter for the Worker: `{schema, input}` text in, `[{path, code}]` out.
///
/// # Errors
/// `protocol` when either text is not JSON (the page sends `JSON.stringify` output).
pub fn validate_skill_input_json(schema_json: &str, input_json: &str) -> Result<String, String> {
    let schema = parse_schema(schema_json).map_err(|_| "protocol".to_string())?;
    let input: Value = serde_json::from_str(input_json).map_err(|_| "protocol".to_string())?;
    // `resolveSkillSchema(undefined)` throws in TS; a missing schema is a malformed details response.
    if schema.is_null() {
        return Err("protocol".into());
    }
    let issues: Vec<Value> = validate_skill_input(&schema, &input)
        .into_iter()
        .map(|issue| serde_json::json!({"path": issue.path, "code": issue.code}))
        .collect();
    Ok(Value::Array(issues).to_string())
}

/// JS own-property order: canonical array-index keys ascending, then insertion order.
fn js_key_order(keys: Vec<String>) -> Vec<String> {
    let index = |key: &str| {
        key.parse::<u32>()
            .ok()
            .filter(|n| *n != u32::MAX && n.to_string() == key)
    };
    let (mut indices, named): (Vec<String>, Vec<String>) =
        keys.into_iter().partition(|key| index(key).is_some());
    indices.sort_by_key(|key| index(key));
    indices.extend(named);
    indices
}

fn forget_order(value: &mut Value) {
    if let Some(object) = value.as_object_mut() {
        object.remove(KEY_ORDER);
    }
}

/// A JSON value whose `properties` objects remember their key order.
struct OrderedSchema(Value);

impl<'de> serde::Deserialize<'de> for OrderedSchema {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Visit;
        impl<'de> serde::de::Visitor<'de> for Visit {
            type Value = OrderedSchema;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("JSON")
            }
            fn visit_bool<E>(self, v: bool) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::Bool(v)))
            }
            fn visit_i64<E>(self, v: i64) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::from(v)))
            }
            fn visit_u64<E>(self, v: u64) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::from(v)))
            }
            fn visit_f64<E>(self, v: f64) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::from(v)))
            }
            fn visit_str<E>(self, v: &str) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::from(v)))
            }
            fn visit_string<E>(self, v: String) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::String(v)))
            }
            fn visit_unit<E>(self) -> Result<OrderedSchema, E> {
                Ok(OrderedSchema(Value::Null))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<OrderedSchema, A::Error> {
                let mut items = Vec::new();
                while let Some(OrderedSchema(mut item)) = seq.next_element()? {
                    forget_order(&mut item);
                    items.push(item);
                }
                Ok(OrderedSchema(Value::Array(items)))
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut access: A,
            ) -> Result<OrderedSchema, A::Error> {
                let mut map = Map::new();
                let mut order = Vec::new();
                while let Some((key, OrderedSchema(value))) =
                    access.next_entry::<String, OrderedSchema>()?
                {
                    // A repeated key keeps its first position and last value, like JSON.parse.
                    if !map.contains_key(&key) {
                        order.push(key.clone());
                    }
                    map.insert(key, value);
                }
                // Only a `properties` object keeps its order; every other child forgets it.
                for (key, value) in map.iter_mut() {
                    if key != "properties" {
                        forget_order(value);
                    }
                }
                map.insert(KEY_ORDER.into(), Value::from(js_key_order(order)));
                Ok(OrderedSchema(Value::Object(map)))
            }
        }
        deserializer.deserialize_any(Visit)
    }
}

/// Parses a skill schema keeping each `properties` object's JS key order, so
/// [`validate_skill_input`] reports issues in the TS walk order.
///
/// # Errors
/// The serde error for malformed JSON.
pub fn parse_schema(text: &str) -> Result<Value, serde_json::Error> {
    let mut schema = serde_json::from_str::<OrderedSchema>(text)?.0;
    forget_order(&mut schema);
    Ok(schema)
}

#[cfg(test)]
#[path = "schema_tests.rs"]
mod tests;
