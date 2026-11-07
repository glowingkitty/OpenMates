//! Insertion-ordered JSON value and the web chat export YAML emitter.
//!
//! Part of the shared Rust core `transfer` unit (`web_transfer*`). It ports
//! `convertToYamlString`, `needsQuoting` and `escapeYamlString` of
//! `frontend/packages/ui/src/services/chatExportService.ts` byte for byte, so the
//! downloaded chat YAML is identical whichever engine builds it. The emitter is
//! deliberately not a YAML library: it reproduces the TypeScript service's
//! quoting quirks (numbers stay unquoted, block scalars escape `\` and `$`).
//! Parity: `web_transfer_export_ts_vectors.json` (generated from the TS service).
use crate::account::imports_parse::js_is_space;
use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use std::fmt;

/// Marker key the page uses for scalars JSON cannot carry (`NaN`, `Infinity`,
/// `undefined` inside arrays): `{"$om_raw": "NaN"}` prints the text verbatim.
const RAW_KEY: &str = "$om_raw";

/// A JSON value that remembers object key order (JavaScript `Object.entries`
/// order is already baked into the text the page sends).
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum Node {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    /// Verbatim scalar text (see [`RAW_KEY`]).
    Raw(String),
    Array(Vec<Node>),
    Object(Vec<(String, Node)>),
}

impl Node {
    /// Member of an object node; `None` for missing keys and non-objects.
    pub(crate) fn get(&self, key: &str) -> Option<&Node> {
        match self {
            Node::Object(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// JavaScript truthiness of a JSON-derived value.
    pub(crate) fn truthy(&self) -> bool {
        match self {
            Node::Null => false,
            Node::Bool(b) => *b,
            Node::Num(n) => *n != 0.0 && !n.is_nan(),
            Node::Str(s) => !s.is_empty(),
            Node::Raw(raw) => raw != "NaN" && raw != "undefined",
            Node::Array(_) | Node::Object(_) => true,
        }
    }

    /// The text of a string node.
    pub(crate) fn as_str(&self) -> Option<&str> {
        match self {
            Node::Str(s) => Some(s),
            _ => None,
        }
    }
}

struct NodeVisitor;

impl<'de> Visitor<'de> for NodeVisitor {
    type Value = Node;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value")
    }
    fn visit_unit<E>(self) -> Result<Node, E> {
        Ok(Node::Null)
    }
    fn visit_none<E>(self) -> Result<Node, E> {
        Ok(Node::Null)
    }
    fn visit_bool<E>(self, v: bool) -> Result<Node, E> {
        Ok(Node::Bool(v))
    }
    fn visit_i64<E>(self, v: i64) -> Result<Node, E> {
        Ok(Node::Num(v as f64))
    }
    fn visit_u64<E>(self, v: u64) -> Result<Node, E> {
        Ok(Node::Num(v as f64))
    }
    fn visit_f64<E>(self, v: f64) -> Result<Node, E> {
        Ok(Node::Num(v))
    }
    fn visit_str<E>(self, v: &str) -> Result<Node, E> {
        Ok(Node::Str(v.to_string()))
    }
    fn visit_string<E>(self, v: String) -> Result<Node, E> {
        Ok(Node::Str(v))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Node, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = seq.next_element()? {
            items.push(item);
        }
        Ok(Node::Array(items))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Node, A::Error> {
        let mut entries: Vec<(String, Node)> = Vec::new();
        while let Some((key, value)) = map.next_entry::<String, Node>()? {
            entries.push((key, value));
        }
        if let [(key, Node::Str(raw))] = entries.as_slice()
            && key == RAW_KEY
        {
            return Ok(Node::Raw(raw.clone()));
        }
        Ok(Node::Object(entries))
    }
}

impl<'de> Deserialize<'de> for Node {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Node, D::Error> {
        deserializer.deserialize_any(NodeVisitor)
    }
}

/// ECMAScript `Number.prototype.toString()` (radix 10) of a finite number.
///
/// Rust prints the shortest round-trip digits like V8; only the layout
/// (exponent thresholds 1e21 / 1e-7) is re-derived from the spec.
pub(crate) fn js_number_string(value: f64) -> String {
    if value.is_nan() {
        return "NaN".into();
    }
    if value == 0.0 {
        return "0".into();
    }
    if value.is_infinite() {
        return if value < 0.0 { "-Infinity" } else { "Infinity" }.into();
    }
    if value < 0.0 {
        return format!("-{}", js_number_string(-value));
    }
    let scientific = format!("{value:e}");
    let (mantissa, exponent) = scientific
        .split_once('e')
        .expect("LowerExp has an exponent");
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let n = exponent
        .parse::<i32>()
        .expect("LowerExp exponent is an integer")
        + 1;
    let k = digits.len() as i32;
    if k <= n && n <= 21 {
        format!("{digits}{}", "0".repeat((n - k) as usize))
    } else if 0 < n && n <= 21 {
        format!("{}.{}", &digits[..n as usize], &digits[n as usize..])
    } else if -6 < n && n <= 0 {
        format!("0.{}{digits}", "0".repeat((-n) as usize))
    } else {
        let e = n - 1;
        let sign = if e < 0 { '-' } else { '+' };
        if k == 1 {
            format!("{digits}e{sign}{}", e.abs())
        } else {
            format!("{}.{}e{sign}{}", &digits[..1], &digits[1..], e.abs())
        }
    }
}

/// `str.trim() === String(Number(str))` for strings that start with a digit and
/// are plain decimal literals (hex/binary/octal literals never round-trip to
/// their own text, so they cannot take the unquoted-number exemption).
fn is_canonical_number(text: &str) -> bool {
    let trimmed = text.trim_matches(js_is_space);
    let bytes = trimmed.as_bytes();
    let mut i = 0;
    let digits = |from: usize| {
        bytes[from..]
            .iter()
            .take_while(|b| b.is_ascii_digit())
            .count()
    };
    let int = digits(i);
    if int == 0 {
        return false;
    }
    i += int;
    if bytes.get(i) == Some(&b'.') {
        i += 1 + digits(i + 1);
    }
    if matches!(bytes.get(i), Some(b'e' | b'E')) {
        i += 1;
        if matches!(bytes.get(i), Some(b'+' | b'-')) {
            i += 1;
        }
        let exp = digits(i);
        if exp == 0 {
            return false;
        }
        i += exp;
    }
    if i != bytes.len() {
        return false;
    }
    match trimmed.parse::<f64>() {
        Ok(number) if number.is_finite() => js_number_string(number) == trimmed,
        _ => false,
    }
}

/// `needsQuoting`: whether a single-line string needs double quotes.
///
/// The HTML-entity and URL branches of the TypeScript original are subsumed by
/// the special-character branch (`&` and `:` both quote), so they are omitted.
pub(crate) fn needs_quoting(text: &str) -> bool {
    if text.is_empty()
        || matches!(
            text,
            "null" | "true" | "false" | "yes" | "no" | "on" | "off"
        )
    {
        return true;
    }
    if text.chars().any(|c| ":#@`|>&*!?%{}[]\\,\"'".contains(c)) {
        return true;
    }
    match text.chars().next() {
        Some('-' | '+' | '.') => return true,
        Some(first) if first.is_ascii_digit() && is_canonical_number(text) => return false,
        _ => {}
    }
    text.chars()
        .any(|c| matches!(c, '\u{0}'..='\u{8}' | '\u{b}' | '\u{c}' | '\u{e}'..='\u{1f}' | '\u{7f}'))
}

/// `escapeYamlString`: backslash, quote, newline, carriage return and tab.
fn escape_yaml_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            other => out.push(other),
        }
    }
    out
}

fn quoted_or_plain(text: &str) -> String {
    if needs_quoting(text) {
        format!("\"{}\"", escape_yaml_string(text))
    } else {
        text.to_string()
    }
}

/// `${item}` of a non-string scalar.
fn scalar_text(node: &Node) -> String {
    match node {
        Node::Null => "null".into(),
        Node::Bool(b) => b.to_string(),
        Node::Num(n) => js_number_string(*n),
        Node::Raw(raw) => raw.clone(),
        Node::Str(s) => s.clone(),
        Node::Array(_) | Node::Object(_) => String::new(),
    }
}

/// `Object.entries(value)`: arrays enumerate their indices as keys.
fn entries(node: &Node) -> Vec<(String, &Node)> {
    match node {
        Node::Object(pairs) => pairs.iter().map(|(k, v)| (k.clone(), v)).collect(),
        Node::Array(items) => items
            .iter()
            .enumerate()
            .map(|(i, v)| (i.to_string(), v))
            .collect(),
        _ => Vec::new(),
    }
}

fn convert_value(lines: &mut Vec<String>, key: &str, value: &Node, indent: usize) {
    let spaces = "  ".repeat(indent);
    match value {
        Node::Null => lines.push(format!("{spaces}{key}: null")),
        Node::Str(text) if text.contains('\n') => {
            lines.push(format!("{spaces}{key}: |"));
            for line in text.split('\n') {
                // Block scalars keep `\` and `$` literal by doubling/escaping them.
                let escaped = line.replace('\\', "\\\\").replace('$', "\\$");
                lines.push(format!("{spaces}  {escaped}"));
            }
        }
        Node::Str(text) => lines.push(format!("{spaces}{key}: {}", quoted_or_plain(text))),
        Node::Num(_) | Node::Bool(_) | Node::Raw(_) => {
            lines.push(format!("{spaces}{key}: {}", scalar_text(value)));
        }
        Node::Array(items) => {
            lines.push(format!("{spaces}{key}:"));
            for item in items {
                match item {
                    Node::Array(_) | Node::Object(_) => {
                        lines.push(format!("{spaces}  -"));
                        for (item_key, item_value) in entries(item) {
                            convert_value(lines, &item_key, item_value, indent + 2);
                        }
                    }
                    Node::Str(text) => lines.push(format!("{spaces}  - {}", quoted_or_plain(text))),
                    scalar => lines.push(format!("{spaces}  - {}", scalar_text(scalar))),
                }
            }
        }
        Node::Object(pairs) => {
            lines.push(format!("{spaces}{key}:"));
            for (child_key, child) in pairs {
                convert_value(lines, child_key, child, indent + 1);
            }
        }
    }
}

/// `convertToYamlString` over the top-level entries of `data`.
pub(crate) fn to_yaml_string(data: &[(String, Node)]) -> String {
    let mut lines = Vec::new();
    for (key, value) in data {
        convert_value(&mut lines, key, value, 0);
    }
    lines.join("\n")
}
