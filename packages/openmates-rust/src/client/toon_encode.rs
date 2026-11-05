//! Canonical TOON encoder for client-authored embed content (npm
//! `toonEncodeContent` via `@toon-format/toon` 4.x defaults: two-space indent,
//! comma delimiter). Covers objects, primitive arrays and scalars; arrays that
//! would need tabular or list form fail closed instead of guessing a layout.
use crate::{Error, Result};
use serde_json::{Map, Value};

/// Encode an ordered top-level object (npm keeps insertion order).
pub(crate) fn encode_fields(fields: &[(&str, Value)]) -> Result<String> {
    let mut lines = vec![];
    for (key, value) in fields {
        field(&mut lines, 0, key, value)?;
    }
    Ok(lines.join("\n"))
}

fn object(lines: &mut Vec<String>, depth: usize, map: &Map<String, Value>) -> Result<()> {
    for (key, value) in map {
        field(lines, depth, key, value)?;
    }
    Ok(())
}

fn field(lines: &mut Vec<String>, depth: usize, key: &str, value: &Value) -> Result<()> {
    let indent = "  ".repeat(depth);
    let key = encode_key(key);
    match value {
        Value::Object(map) => {
            lines.push(format!("{indent}{key}:"));
            object(lines, depth + 1, map)
        }
        Value::Array(items) if items.is_empty() => {
            lines.push(format!("{indent}{key}: []"));
            Ok(())
        }
        Value::Array(items) => {
            let values = items.iter().map(primitive).collect::<Result<Vec<_>>>()?;
            lines.push(format!(
                "{indent}{key}[{}]: {}",
                items.len(),
                values.join(",")
            ));
            Ok(())
        }
        other => {
            lines.push(format!("{indent}{key}: {}", primitive(other)?));
            Ok(())
        }
    }
}

fn primitive(value: &Value) -> Result<String> {
    Ok(match value {
        Value::Null => "null".into(),
        Value::Bool(flag) => flag.to_string(),
        Value::Number(number) => js_number(number)?,
        Value::String(text) => string_literal(text),
        Value::Array(_) | Value::Object(_) => return Err(Error::Protocol),
    })
}

fn encode_key(key: &str) -> String {
    let mut chars = key.chars();
    let valid = chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.');
    if valid {
        key.to_owned()
    } else {
        format!("\"{}\"", escape(key))
    }
}

fn escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for c in value.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn numeric_like(value: &str) -> bool {
    // /^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i
    let bytes = value.as_bytes();
    let mut i = usize::from(matches!(bytes.first(), Some(b'+' | b'-')));
    let digits = |i: &mut usize| {
        let start = *i;
        while bytes.get(*i).is_some_and(u8::is_ascii_digit) {
            *i += 1;
        }
        *i > start
    };
    if !digits(&mut i) {
        return false;
    }
    if bytes.get(i) == Some(&b'.') {
        i += 1;
        if !digits(&mut i) {
            return false;
        }
    }
    if matches!(bytes.get(i), Some(b'e' | b'E')) {
        i += 1;
        if matches!(bytes.get(i), Some(b'+' | b'-')) {
            i += 1;
        }
        if !digits(&mut i) {
            return false;
        }
    }
    i == bytes.len()
}

fn safe_unquoted(value: &str) -> bool {
    !value.is_empty()
        && !value.starts_with([' ', '\t'])
        && !value.ends_with([' ', '\t'])
        && !matches!(value, "true" | "false" | "null")
        && !numeric_like(value)
        && !value.contains([':', '"', '\\', '[', ']', '{', '}', ','])
        && !value.chars().any(|c| (c as u32) < 0x20)
        && !value.starts_with(['-', '#'])
}

fn string_literal(value: &str) -> String {
    if safe_unquoted(value) {
        value.to_owned()
    } else {
        format!("\"{}\"", escape(value))
    }
}

/// JavaScript `String(number)` (ECMAScript Number::toString, radix 10).
fn js_number(number: &serde_json::Number) -> Result<String> {
    if let Some(value) = number.as_i64() {
        return Ok(value.to_string());
    }
    if let Some(value) = number.as_u64() {
        return Ok(value.to_string());
    }
    let value = number
        .as_f64()
        .filter(|v| v.is_finite())
        .ok_or(Error::Protocol)?;
    Ok(js_float(value))
}

pub(super) fn js_float(value: f64) -> String {
    if value == 0.0 {
        return "0".into();
    }
    let sign = if value < 0.0 { "-" } else { "" };
    // Rust's `{:e}` emits the shortest round-tripping digits, as JS does.
    let formatted = format!("{:e}", value.abs());
    let (mantissa, exponent) = formatted.split_once('e').unwrap_or((&formatted, "0"));
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let exponent: i32 = exponent.parse().unwrap_or(0);
    let k = digits.len() as i32;
    let n = exponent + 1;
    let body = if k <= n && n <= 21 {
        format!("{digits}{}", "0".repeat((n - k) as usize))
    } else if 0 < n && n <= 21 {
        format!("{}.{}", &digits[..n as usize], &digits[n as usize..])
    } else if -6 < n && n <= 0 {
        format!("0.{}{digits}", "0".repeat((-n) as usize))
    } else {
        let e = n - 1;
        let e_sign = if e < 0 { "-" } else { "+" };
        if k == 1 {
            format!("{digits}e{e_sign}{}", e.abs())
        } else {
            format!("{}.{}e{e_sign}{}", &digits[..1], &digits[1..], e.abs())
        }
    };
    format!("{sign}{body}")
}
