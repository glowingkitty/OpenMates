//! Decoded TOON value tree with JavaScript object semantics: duplicate keys keep
//! their first position and take the last value, and `to_json_text` emits keys
//! in JS property order (array-index keys ascending, then insertion order) with
//! `JSON.stringify` string escaping and `Number#toString` number formatting, so
//! the text is byte-identical to `JSON.stringify(decode(...))` in the web client.
use serde_json::{Map, Number, Value};

/// A decoded TOON value (the JSON data model; numbers are JS doubles).
#[derive(Debug, Clone, PartialEq)]
pub enum ToonValue {
    /// `null`.
    Null,
    /// `true` / `false`.
    Bool(bool),
    /// Finite double; `-0` is already folded to `0` by the decoder.
    Number(f64),
    /// String (unescaped).
    String(String),
    /// Array in source order.
    Array(Vec<ToonValue>),
    /// Object with JS own-property semantics.
    Object(ToonObject),
}

/// Object entries in insertion order (see the module doc for key semantics).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ToonObject {
    entries: Vec<(String, ToonValue)>,
}

impl ToonObject {
    /// JS assignment: replaces the value of an existing key in place.
    pub fn set(&mut self, key: String, value: ToonValue) {
        match self
            .entries
            .iter_mut()
            .find(|(existing, _)| *existing == key)
        {
            Some(entry) => entry.1 = value,
            None => self.entries.push((key, value)),
        }
    }

    /// Entries in insertion order.
    pub fn entries(&self) -> &[(String, ToonValue)] {
        &self.entries
    }

    /// Entries in JS own-property order: canonical array-index keys
    /// (`0..=4294967294`, no leading zero) ascending, then the rest as inserted.
    fn js_ordered(&self) -> Vec<&(String, ToonValue)> {
        let mut indexed: Vec<(u32, &(String, ToonValue))> = self
            .entries
            .iter()
            .filter_map(|entry| array_index(&entry.0).map(|index| (index, entry)))
            .collect();
        indexed.sort_by_key(|(index, _)| *index);
        let mut ordered: Vec<&(String, ToonValue)> =
            indexed.into_iter().map(|(_, entry)| entry).collect();
        ordered.extend(
            self.entries
                .iter()
                .filter(|entry| array_index(&entry.0).is_none()),
        );
        ordered
    }
}

fn array_index(key: &str) -> Option<u32> {
    if key.is_empty()
        || (key.len() > 1 && key.starts_with('0'))
        || !key.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    key.parse::<u32>().ok().filter(|index| *index != u32::MAX)
}

impl ToonValue {
    /// The exact `JSON.stringify` text of the equivalent JS value.
    pub fn to_json_text(&self) -> String {
        let mut out = String::new();
        self.write_json(&mut out);
        out
    }

    fn write_json(&self, out: &mut String) {
        match self {
            Self::Null => out.push_str("null"),
            Self::Bool(value) => out.push_str(if *value { "true" } else { "false" }),
            Self::Number(value) => out.push_str(&js_number_text(*value)),
            Self::String(value) => write_json_string(value, out),
            Self::Array(items) => {
                out.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    item.write_json(out);
                }
                out.push(']');
            }
            Self::Object(object) => {
                out.push('{');
                for (index, (key, value)) in object.js_ordered().into_iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    write_json_string(key, out);
                    out.push(':');
                    value.write_json(out);
                }
                out.push('}');
            }
        }
    }

    /// Converts to `serde_json::Value`. Integral doubles that `serde_json`
    /// would parse as integers become integer numbers, so the result equals
    /// `serde_json::from_str(&self.to_json_text())` (object key order aside).
    pub fn to_json_value(&self) -> Value {
        match self {
            Self::Null => Value::Null,
            Self::Bool(value) => Value::Bool(*value),
            Self::Number(value) => json_number(*value),
            Self::String(value) => Value::String(value.clone()),
            Self::Array(items) => Value::Array(items.iter().map(Self::to_json_value).collect()),
            Self::Object(object) => Value::Object(
                object
                    .entries
                    .iter()
                    .map(|(key, value)| (key.clone(), value.to_json_value()))
                    .collect::<Map<_, _>>(),
            ),
        }
    }
}

fn json_number(value: f64) -> Value {
    // JSON.stringify prints integral doubles below 1e21 as digit runs, which
    // serde_json reads back as u64/i64 when they fit.
    if value.fract() == 0.0 && value.abs() < 1e21 {
        if (0.0..18_446_744_073_709_551_616.0).contains(&value) {
            return Value::Number(Number::from(value as u64));
        }
        if (-9_223_372_036_854_775_808.0..0.0).contains(&value) {
            return Value::Number(Number::from(value as i64));
        }
    }
    Number::from_f64(value).map_or(Value::Null, Value::Number)
}

/// `JSON.stringify` string quoting: `\" \\ \b \f \n \r \t`, other C0 controls
/// as lowercase `\u00xx`, everything else verbatim.
fn write_json_string(value: &str, out: &mut String) {
    out.push('"');
    for c in value.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// ECMAScript `Number::toString(10)` for a finite double, built from Rust's
/// shortest round-trip digits (`{:e}`), which are the digits JS selects.
pub(crate) fn js_number_text(value: f64) -> String {
    if value == 0.0 {
        return "0".to_owned();
    }
    // `{:e}` of a finite non-zero double is always `<d>[.<ddd>]e<int>`, so the
    // fallbacks below are unreachable.
    let formatted = format!("{:e}", value.abs());
    let (mantissa, exponent) = formatted
        .split_once('e')
        .unwrap_or((formatted.as_str(), "0"));
    let exponent: i64 = exponent.parse().unwrap_or(0);
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let k = digits.len() as i64;
    let n = exponent + 1;
    let sign = if value < 0.0 { "-" } else { "" };
    let body = if k <= n && n <= 21 {
        format!("{digits}{}", "0".repeat((n - k) as usize))
    } else if 0 < n && n <= 21 {
        let (int, frac) = digits.split_at(n as usize);
        format!("{int}.{frac}")
    } else if -6 < n && n <= 0 {
        format!("0.{}{digits}", "0".repeat((-n) as usize))
    } else {
        let e = n - 1;
        let e_sign = if e < 0 { '-' } else { '+' };
        let (first, rest) = digits.split_at(1);
        if rest.is_empty() {
            format!("{first}e{e_sign}{}", e.abs())
        } else {
            format!("{first}.{rest}e{e_sign}{}", e.abs())
        }
    };
    format!("{sign}{body}")
}
