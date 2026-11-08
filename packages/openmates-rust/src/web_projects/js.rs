//! JavaScript value semantics the Project decisions need to answer exactly what the
//! TypeScript rules answer: truthiness, `===`, `String(x)`, `Number(x)`, relational
//! `>`, `String.prototype.trim`, UTF-16 `slice`, `decodeURIComponent` and the JSON
//! round-trip number shape. Part of the shared core `web_projects` module.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! An absent JSON field is JS `undefined` and is modelled as `None` throughout.

use super::Fault;
use crate::web_share_state::utf16_cmp;
use serde_json::{Map, Number, Value};
use std::cmp::Ordering;

/// Characters JS `String.prototype.trim` and the regex `\s` class treat as white space
/// (WhiteSpace + LineTerminator). Rust's `char::is_whitespace` differs (it includes
/// U+0085 and excludes U+FEFF), so the rules never use it.
pub(crate) fn is_js_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n'
            | '\u{000B}'
            | '\u{000C}'
            | '\r'
            | ' '
            | '\u{00A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
            | '\u{FEFF}'
    )
}

/// The JS `\s` class as a `regex` crate character-class body (without brackets).
pub(crate) const JS_SPACE_CLASS: &str =
    r"\t\n\x0B\x0C\r \x{A0}\x{1680}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}\x{FEFF}";

/// JS `String.prototype.trim`.
pub(crate) fn trim(text: &str) -> &str {
    text.trim_matches(is_js_space)
}

/// JS truthiness (`undefined`, `null`, `false`, `0`, `""` are falsy).
pub(crate) fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(flag)) => *flag,
        Some(Value::Number(number)) => number.as_f64().is_some_and(|n| n != 0.0),
        Some(Value::String(text)) => !text.is_empty(),
        Some(Value::Array(_) | Value::Object(_)) => true,
    }
}

/// JS `a === b` on JSON values. Distinct parsed objects/arrays are never identical.
pub(crate) fn strict_eq(a: Option<&Value>, b: Option<&Value>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(Value::Null), Some(Value::Null)) => true,
        (Some(Value::Bool(x)), Some(Value::Bool(y))) => x == y,
        (Some(Value::Number(x)), Some(Value::Number(y))) => x.as_f64() == y.as_f64(),
        (Some(Value::String(x)), Some(Value::String(y))) => x == y,
        _ => false,
    }
}

/// `value === "<text>"`.
pub(crate) fn is_str(value: Option<&Value>, text: &str) -> bool {
    matches!(value, Some(Value::String(s)) if s == text)
}

/// The string when the value is a JS string.
pub(crate) fn as_str(value: Option<&Value>) -> Option<&str> {
    value.and_then(Value::as_str)
}

/// JS `Number.prototype.toString()` (shortest round-trip digits, JS exponent rules).
pub(crate) fn number_to_string(n: f64) -> String {
    if n.is_nan() {
        return "NaN".to_owned();
    }
    if n == 0.0 {
        return "0".to_owned();
    }
    if n.is_infinite() {
        return if n > 0.0 { "Infinity" } else { "-Infinity" }.to_owned();
    }
    if n < 0.0 {
        return format!("-{}", number_to_string(-n));
    }
    // `{:e}` prints the shortest round-trip digits as `d[.ddd]e<exp>`.
    let formatted = format!("{n:e}");
    let (mantissa, exponent) = formatted.split_once('e').unwrap_or((formatted.as_str(), "0"));
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let exponent: i64 = exponent.parse().unwrap_or(0);
    let k = digits.len() as i64;
    let point = exponent + 1;
    if k <= point && point <= 21 {
        format!("{digits}{}", "0".repeat((point - k) as usize))
    } else if 0 < point && point <= 21 {
        let (head, tail) = digits.split_at(point as usize);
        format!("{head}.{tail}")
    } else if -6 < point && point <= 0 {
        format!("0.{}{digits}", "0".repeat((-point) as usize))
    } else {
        let sign = if exponent < 0 { '-' } else { '+' };
        let (first, rest) = digits.split_at(1);
        let rest = if rest.is_empty() { String::new() } else { format!(".{rest}") };
        format!("{first}{rest}e{sign}{}", exponent.abs())
    }
}

/// JS `String(value)` (`undefined` for an absent field, arrays join with `,`).
pub(crate) fn js_string(value: Option<&Value>) -> String {
    match value {
        None => "undefined".to_owned(),
        Some(Value::Null) => "null".to_owned(),
        Some(Value::Bool(flag)) => flag.to_string(),
        Some(Value::Number(number)) => number_to_string(number.as_f64().unwrap_or(f64::NAN)),
        Some(Value::String(text)) => text.clone(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| match item {
                Value::Null => String::new(),
                other => js_string(Some(other)),
            })
            .collect::<Vec<_>>()
            .join(","),
        Some(Value::Object(_)) => "[object Object]".to_owned(),
    }
}

/// JS `StringToNumber` (whitespace-trimmed decimal, `0x`/`0o`/`0b`, `Infinity`).
fn string_to_number(text: &str) -> f64 {
    let text = trim(text);
    if text.is_empty() {
        return 0.0;
    }
    match text {
        "Infinity" | "+Infinity" => return f64::INFINITY,
        "-Infinity" => return f64::NEG_INFINITY,
        _ => {}
    }
    let radix = match text.get(..2) {
        Some("0x" | "0X") => Some(16),
        Some("0o" | "0O") => Some(8),
        Some("0b" | "0B") => Some(2),
        _ => None,
    };
    if let Some(radix) = radix {
        let digits = &text[2..];
        if digits.is_empty() {
            return f64::NAN;
        }
        let mut total = 0.0_f64;
        for c in digits.chars() {
            match c.to_digit(radix) {
                Some(digit) => total = total * f64::from(radix) + f64::from(digit),
                None => return f64::NAN,
            }
        }
        return total;
    }
    let bytes = text.as_bytes();
    let mut i = usize::from(matches!(bytes.first(), Some(b'+' | b'-')));
    let int_start = i;
    while i < bytes.len() && bytes[i].is_ascii_digit() {
        i += 1;
    }
    let mut mantissa_digits = i - int_start;
    if i < bytes.len() && bytes[i] == b'.' {
        i += 1;
        let frac_start = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        mantissa_digits += i - frac_start;
    }
    if mantissa_digits == 0 {
        return f64::NAN;
    }
    if i < bytes.len() && (bytes[i] == b'e' || bytes[i] == b'E') {
        i += 1;
        if i < bytes.len() && (bytes[i] == b'+' || bytes[i] == b'-') {
            i += 1;
        }
        let exp_start = i;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            i += 1;
        }
        if i == exp_start {
            return f64::NAN;
        }
    }
    if i != bytes.len() {
        return f64::NAN;
    }
    text.parse::<f64>().unwrap_or(f64::NAN)
}

/// JS `Number(value)` / unary `+` (objects go through `String(value)`).
pub(crate) fn to_number(value: Option<&Value>) -> f64 {
    match value {
        None => f64::NAN,
        Some(Value::Null) => 0.0,
        Some(Value::Bool(flag)) => f64::from(u8::from(*flag)),
        Some(Value::Number(number)) => number.as_f64().unwrap_or(f64::NAN),
        Some(Value::String(text)) => string_to_number(text),
        Some(other @ (Value::Array(_) | Value::Object(_))) => string_to_number(&js_string(Some(other))),
    }
}

/// JS `a > b`: two strings (after `ToPrimitive`) compare by UTF-16 units, else numerically.
pub(crate) fn gt(a: Option<&Value>, b: Option<&Value>) -> bool {
    let primitive = |value: Option<&Value>| -> Option<String> {
        match value {
            Some(Value::String(text)) => Some(text.clone()),
            Some(other @ (Value::Array(_) | Value::Object(_))) => Some(js_string(Some(other))),
            _ => None,
        }
    };
    match (primitive(a), primitive(b)) {
        (Some(x), Some(y)) => utf16_cmp(&x, &y) == Ordering::Greater,
        (x, y) => {
            let left = x.map_or_else(|| to_number(a), |text| string_to_number(&text));
            let right = y.map_or_else(|| to_number(b), |text| string_to_number(&text));
            left > right
        }
    }
}

/// JS `Number.isInteger`.
pub(crate) fn is_integer(value: Option<&Value>) -> bool {
    value.and_then(Value::as_f64).is_some_and(|n| n.is_finite() && n.fract() == 0.0)
}

/// JS `Number.isSafeInteger`.
pub(crate) fn is_safe_integer(value: Option<&Value>) -> bool {
    value.is_some_and(|v| crate::web_share_state::safe_int(v).is_some())
}

/// The JSON number of an `f64` exactly as JS `JSON.stringify` + `JSON.parse` shapes it.
pub(crate) fn number_value(n: f64) -> Value {
    if !n.is_finite() {
        return Value::Null;
    }
    if n.fract() == 0.0 && n.abs() < 1e21 {
        if n.abs() <= 9_007_199_254_740_991.0 {
            return Value::from(n as i64);
        }
        if n >= 0.0 && n <= u64::MAX as f64 {
            return Value::from(n as u64);
        }
    }
    Number::from_f64(n).map_or(Value::Null, Value::Number)
}

/// Re-shapes every number of a document like a JS JSON round trip (`1.0` → `1`,
/// `-0` → `0`, integers beyond 2^53 rounded to binary64).
pub(crate) fn normalize(value: Value) -> Value {
    match value {
        Value::Number(number) => number_value(number.as_f64().unwrap_or(f64::NAN)),
        Value::Array(items) => Value::Array(items.into_iter().map(normalize).collect()),
        Value::Object(map) => Value::Object(map.into_iter().map(|(k, v)| (k, normalize(v))).collect()),
        other => other,
    }
}

/// JS `text.length`.
pub(crate) fn len16(text: &str) -> usize {
    text.encode_utf16().count()
}

/// JS `text.slice(start, end)` with negative offsets counted from the end. A cut through
/// a surrogate pair cannot be represented in a Rust string and becomes U+FFFD
/// (documented deviation; JS keeps the lone surrogate).
pub(crate) fn slice16(text: &str, start: i64, end: Option<i64>) -> String {
    let units: Vec<u16> = text.encode_utf16().collect();
    let len = units.len() as i64;
    let clamp = |index: i64| -> usize { (if index < 0 { (len + index).max(0) } else { index.min(len) }) as usize };
    let from = clamp(start);
    let to = clamp(end.unwrap_or(len));
    if from >= to {
        return String::new();
    }
    String::from_utf16_lossy(&units[from..to])
}

/// JS `decodeURIComponent`: `None` where JS throws `URIError` (bad escape or invalid UTF-8).
pub(crate) fn decode_uri_component(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex = text.get(i + 1..i + 3)?;
            if !hex.bytes().all(|b| b.is_ascii_hexdigit()) {
                return None;
            }
            out.push(u8::from_str_radix(hex, 16).ok()?);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    // Raw characters are whole UTF-8 sequences, so any malformed escape run stays
    // malformed in the byte stream exactly where JS raises URIError.
    String::from_utf8(out).ok()
}

/// A lookup in a JS object literal table: own keys, or the `Object.prototype` members a
/// lower-case key can reach (`constructor` is a function JSON drops, `__proto__` is `{}`).
pub(crate) enum TableHit<'a> {
    /// An own entry of the table.
    Own(&'a str),
    /// `Object.prototype.constructor`: truthy, omitted by `JSON.stringify`.
    Function,
    /// `Object.prototype` itself: truthy, serializes as `{}`.
    Prototype,
    /// `undefined`.
    Missing,
}

/// Looks `key` up in a `Record<string, string>` literal (prototype chain included).
pub(crate) fn table_get<'a>(table: &[(&str, &'a str)], key: &str) -> TableHit<'a> {
    if let Some((_, value)) = table.iter().find(|(name, _)| *name == key) {
        return TableHit::Own(value);
    }
    match key {
        "constructor" | "hasOwnProperty" | "isPrototypeOf" | "propertyIsEnumerable" | "toLocaleString"
        | "toString" | "valueOf" | "__defineGetter__" | "__defineSetter__" | "__lookupGetter__"
        | "__lookupSetter__" => TableHit::Function,
        "__proto__" => TableHit::Prototype,
        _ => TableHit::Missing,
    }
}

impl TableHit<'_> {
    /// The value stored under an output key (`None` = the key is omitted by JSON).
    pub(crate) fn json(&self) -> Option<Value> {
        match self {
            TableHit::Own(text) => Some(Value::from(*text)),
            TableHit::Function | TableHit::Missing => None,
            TableHit::Prototype => Some(Value::Object(Map::new())),
        }
    }
}

/// Property read `value.name`: `undefined`/`null` receivers are a TypeError (malformed
/// input), primitives and arrays have none of the named fields.
pub(crate) fn prop<'a>(value: Option<&'a Value>, name: &str) -> Result<Option<&'a Value>, Fault> {
    match value {
        None | Some(Value::Null) => Err(Fault::Malformed(format!("nullish_read:{name}"))),
        Some(Value::Object(map)) => Ok(map.get(name)),
        Some(_) => Ok(None),
    }
}

/// Optional-chaining read `value?.name`.
pub(crate) fn opt_prop<'a>(value: Option<&'a Value>, name: &str) -> Option<&'a Value> {
    match value {
        Some(Value::Object(map)) => map.get(name),
        _ => None,
    }
}

/// `value ?? fallback` (absent or `null` take the fallback).
pub(crate) fn nullish_or<'a>(value: Option<&'a Value>, fallback: &'a Value) -> &'a Value {
    match value {
        None | Some(Value::Null) => fallback,
        Some(other) => other,
    }
}

/// Inserts `name: value` unless the value is `undefined` (JSON omits it).
pub(crate) fn put(map: &mut Map<String, Value>, name: &str, value: Option<&Value>) {
    if let Some(value) = value {
        map.insert(name.to_owned(), value.clone());
    }
}

/// A required JS string; anything else is malformed input (the TS rule would throw a TypeError).
pub(crate) fn req_str<'a>(value: Option<&'a Value>, name: &str) -> Result<&'a str, Fault> {
    as_str(value).ok_or_else(|| Fault::Malformed(format!("bad_field:{name}")))
}

/// A required JS array; anything else is malformed input.
pub(crate) fn req_array<'a>(value: Option<&'a Value>, name: &str) -> Result<&'a Vec<Value>, Fault> {
    value.and_then(Value::as_array).ok_or_else(|| Fault::Malformed(format!("bad_field:{name}")))
}

/// Object spread `{...value}`: own entries of an object, index keys of an array or string.
pub(crate) fn spread(value: Option<&Value>) -> Map<String, Value> {
    match value {
        Some(Value::Object(map)) => map.clone(),
        Some(Value::Array(items)) => items.iter().enumerate().map(|(i, v)| (i.to_string(), v.clone())).collect(),
        Some(Value::String(text)) => {
            let units: Vec<u16> = text.encode_utf16().collect();
            units
                .iter()
                .enumerate()
                .map(|(i, unit)| (i.to_string(), Value::from(String::from_utf16_lossy(&[*unit]))))
                .collect()
        }
        _ => Map::new(),
    }
}

/// `JSON.parse(String(value))` as the rules use it; `None` where JS throws a SyntaxError.
/// serde_json additionally refuses lone surrogate escapes, numbers beyond binary64 and
/// nesting deeper than 128 (documented deviations; JS parses those).
pub(crate) fn json_parse(value: Option<&Value>) -> Option<Value> {
    let text = match value {
        Some(Value::String(text)) => text.clone(),
        other => js_string(other),
    };
    serde_json::from_str::<Value>(&text).ok()
}
