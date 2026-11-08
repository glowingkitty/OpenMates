//! Reminder email preview context for saved items (shared Rust core `work` op,
//! saved-embed reminder slice).
//!
//! spec: specifications/features/notifications (reminder email durable limited context)
//!
//! Mirrors `buildReminderNotificationContext` of the web
//! `utils/reminderNotificationContext.ts`: the allowlisted, bounded fields, the
//! date members, the travel/stay/health facts and the 7800-byte JSON budget.
//! The page keeps what only a browser can do: it parses each candidate date
//! string with `Date` (the `dates` table, `null` for `NaN`) and validates the
//! time zone with `Intl` (`reminderTimeZone`). The context comes back as
//! ordered `[key, value]` entries so `Object.fromEntries` keeps the TS key order
//! on the wire. Parity: `reminders_ts_vectors.json`.

use serde_json::{Map, Value, json};

use crate::account::imports_parse::iso_from_ms;
use crate::web_apps::js_number;

/// The server accepts 8192 bytes; the TS leaves room for Python's separators.
const BYTE_BUDGET: usize = 7800;

/// `[label, keys]` of the TS `factFields`, in output order.
const FACTS: [(&str, &[&str]); 8] = [
    ("Provider", &["provider", "booking_provider"]),
    ("From", &["origin"]),
    ("To", &["destination"]),
    ("Transport", &["transport_method"]),
    ("Price", &["price", "price_label"]),
    ("Duration", &["duration"]),
    ("Property type", &["property_type"]),
    ("Speciality", &["speciality"]),
];

/// Members of `iso(first(fields, ...))` for `starts_at`.
pub(crate) const START_KEYS: [&str; 7] =
    ["date_start", "departure", "slot_datetime", "appointment_time", "check_in", "check_in_date", "available_from"];
/// Members of `iso(first(fields, ...))` for `ends_at`.
pub(crate) const END_KEYS: [&str; 4] = ["date_end", "arrival", "check_out", "check_out_date"];

/// Page-made facts of one context build.
pub(crate) struct PageFacts<'a> {
    /// `new Date(text).getTime()` per candidate date string (`null` for `NaN`).
    pub(crate) dates: &'a Map<String, Value>,
    /// `reminderTimeZone(fields)`: the bounded zone `Intl` accepts, if any.
    pub(crate) timezone: Option<&'a str>,
}

/// JS `\s` (WhiteSpace + LineTerminator), also what `trim` removes.
fn js_ws(c: char) -> bool {
    matches!(
        c,
        '\u{0009}'..='\u{000D}'
            | '\u{0020}'
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

/// End of `<NAME\b[^>]*>[\s\S]*?</NAME\s*>` matched at `start` (ASCII
/// case-insensitive like the non-unicode `i` flag, back-reference included).
fn script_style_end(lower: &str, start: usize) -> Option<usize> {
    let bytes = lower.as_bytes();
    for name in ["script", "style"] {
        let after = start + 1 + name.len();
        if !lower[start + 1..].starts_with(name) {
            continue;
        }
        // `\b` is ASCII in JS: the next byte must not be a word character.
        if bytes.get(after).is_some_and(|b| b.is_ascii_alphanumeric() || *b == b'_') {
            continue;
        }
        let open_end = after + lower[after..].find('>')? + 1;
        let close = format!("</{name}");
        let mut from = open_end;
        while let Some(offset) = lower[from..].find(&close) {
            let at = from + offset;
            let rest = &lower[at + close.len()..];
            let spaces: usize = rest.chars().take_while(|c| js_ws(*c)).map(char::len_utf8).sum();
            if rest[spaces..].starts_with('>') {
                return Some(at + close.len() + spaces + 1);
            }
            from = at + 1;
        }
        return None;
    }
    None
}

/// `text.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, ' ')`.
fn strip_script_style(text: &str) -> String {
    // ASCII lowercasing keeps every byte offset, so matches index `text` too.
    let lower = text.to_ascii_lowercase();
    let (mut out, mut copied, mut pos) = (String::with_capacity(text.len()), 0, 0);
    while let Some(offset) = lower[pos..].find('<') {
        let start = pos + offset;
        match script_style_end(&lower, start) {
            Some(end) => {
                out.push_str(&text[copied..start]);
                out.push(' ');
                copied = end;
                pos = end;
            }
            None => pos = start + 1,
        }
    }
    out.push_str(&text[copied..]);
    out
}

/// `text.replace(/<[^>]*>/g, ' ')`.
fn strip_tags(text: &str) -> String {
    let (mut out, mut rest) = (String::with_capacity(text.len()), text);
    while let Some(start) = rest.find('<') {
        let Some(len) = rest[start..].find('>') else { break };
        out.push_str(&rest[..start]);
        out.push(' ');
        rest = &rest[start + len + 1..];
    }
    out.push_str(rest);
    out
}

/// `text.replace(/<pattern>/gi, replacement)` for an ASCII pattern.
fn replace_ascii_ci(text: &str, pattern: &str, replacement: &str) -> String {
    let lower = text.to_ascii_lowercase();
    let (mut out, mut copied) = (String::with_capacity(text.len()), 0);
    let mut from = 0;
    while let Some(offset) = lower[from..].find(pattern) {
        let at = from + offset;
        out.push_str(&text[copied..at]);
        out.push_str(replacement);
        copied = at + pattern.len();
        from = copied;
    }
    out.push_str(&text[copied..]);
    out
}

/// The TS `bounded(value, limit)`: strings and finite numbers only, markup
/// stripped, the six entities decoded in TS order, control characters
/// dropped, trimmed, then the first `limit` code points; empty is `None`.
pub(crate) fn bounded(value: Option<&Value>, limit: usize) -> Option<String> {
    let text = match value? {
        Value::String(s) => s.clone(),
        // JSON numbers are always finite (`NaN`/`Infinity` arrive as `null`).
        Value::Number(n) => js_number(n.as_f64()?),
        _ => return None,
    };
    let mut text = strip_tags(&strip_script_style(&text));
    for (pattern, replacement) in
        [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\""), ("&#39;", "'")]
    {
        text = replace_ascii_ci(&text, pattern, replacement);
    }
    // `charCodeAt(0)` of an astral character is its high surrogate (kept).
    let kept: String = text
        .chars()
        .filter(|c| matches!(*c as u32, 9 | 10 | 13) || (*c as u32 >= 32 && *c as u32 != 127))
        .collect();
    let trimmed = kept.trim_matches(js_ws);
    (!trimmed.is_empty()).then(|| trimmed.chars().take(limit).collect())
}

/// `first(fields, keys)`: the first member with a non-empty bounded text.
pub(crate) fn first<'a>(fields: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    keys.iter().filter_map(|key| fields.get(*key)).find(|value| bounded(Some(value), 1).is_some())
}

/// The page's `Date` parse of a candidate date string.
///
/// # Errors
/// `missing_field:dates.<text>` when the page did not parse a needed string.
pub(crate) fn date_ms(dates: &Map<String, Value>, text: &str) -> Result<Option<f64>, String> {
    match dates.get(text) {
        None => Err(format!("missing_field:dates.{text}")),
        Some(Value::Null) => Ok(None),
        Some(value) => value.as_f64().map(Some).ok_or_else(|| format!("bad_field:dates.{text}")),
    }
}

/// The TS `iso(value)`: an ISO-looking string of at most 80 UTF-16 units,
/// normalized through the page's `Date` parse and `toISOString`.
fn iso(value: Option<&Value>, dates: &Map<String, Value>) -> Result<Option<String>, String> {
    let Some(Value::String(text)) = value else { return Ok(None) };
    let b = text.as_bytes();
    let shaped = b.len() >= 10
        && b[..4].iter().all(u8::is_ascii_digit)
        && b[4] == b'-'
        && b[5..7].iter().all(u8::is_ascii_digit)
        && b[7] == b'-'
        && b[8..10].iter().all(u8::is_ascii_digit)
        && (b.len() == 10 || b[10] == b'T');
    if text.encode_utf16().count() > 80 || !shaped {
        return Ok(None);
    }
    match date_ms(dates, text)? {
        None => Ok(None),
        Some(ms) => iso_from_ms(ms).map(Some),
    }
}

/// UTF-8 length of `JSON.stringify(Object.fromEntries(entries))`.
fn json_bytes(entries: &[(String, Value)]) -> usize {
    // serde_json escapes strings like JSON.stringify; member order does not change the length.
    let members: usize = entries.iter().map(|(key, value)| json!(key).to_string().len() + 1 + value.to_string().len()).sum();
    2 + members + entries.len().saturating_sub(1)
}

fn position(entries: &[(String, Value)], key: &str) -> Option<usize> {
    entries.iter().position(|(name, _)| name == key)
}

/// `buildReminderNotificationContext(kind, title, fields, appId)` as ordered entries.
///
/// # Errors
/// A malformed `dates` table (see [`date_ms`]).
pub(crate) fn context_entries(
    kind: &str,
    title: &str,
    fields: &Map<String, Value>,
    app_id: Option<&Value>,
    page: &PageFacts<'_>,
) -> Result<Vec<(String, Value)>, String> {
    let kind = if kind == "health_appointment" { "appointment" } else { kind };
    let title = bounded(Some(&json!(title)), 200).unwrap_or_else(|| "Reminder".into());
    let mut entries: Vec<(String, Value)> =
        vec![("version".into(), json!(1)), ("kind".into(), json!(kind)), ("title".into(), json!(title))];
    let texts: [(&str, Option<&Value>, usize); 6] = [
        ("description", fields.get("description"), 2000),
        ("summary", fields.get("summary"), 500),
        ("icon", fields.get("icon"), 64),
        ("category", fields.get("category"), 64),
        ("app_id", app_id, 64),
        ("location", first(fields, &["location", "address", "where"]), 1000),
    ];
    for (key, value, limit) in texts {
        if let Some(text) = bounded(value, limit) {
            entries.push((key.into(), json!(text)));
        }
    }
    if let Some(starts) = iso(first(fields, &START_KEYS), page.dates)? {
        entries.push(("starts_at".into(), json!(starts)));
    }
    if let Some(ends) = iso(first(fields, &END_KEYS), page.dates)? {
        entries.push(("ends_at".into(), json!(ends)));
    }
    if let Some(zone) = page.timezone {
        entries.push(("timezone".into(), json!(zone)));
    }
    let facts: Vec<Value> = FACTS
        .iter()
        .filter_map(|(label, keys)| bounded(first(fields, keys), 512).map(|value| json!({ "label": label, "value": value })))
        .collect();
    if !facts.is_empty() {
        entries.push(("facts".into(), Value::Array(facts)));
    }
    // Facts go first, then location, summary and description lose 100 code points at a time.
    while json_bytes(&entries) > BYTE_BUDGET {
        let Some(at) = position(&entries, "facts") else { break };
        let Value::Array(items) = &mut entries[at].1 else { break };
        if items.pop().is_none() || items.is_empty() {
            entries.remove(at);
        }
    }
    for key in ["location", "summary", "description"] {
        while json_bytes(&entries) > BYTE_BUDGET {
            let Some(at) = position(&entries, key) else { break };
            // Only bounded texts are ever stored under these keys.
            let Some(text) = entries[at].1.as_str() else { break };
            let chars: Vec<char> = text.chars().collect();
            let kept: String = chars[..chars.len().saturating_sub(100)].iter().collect();
            if kept.is_empty() {
                entries.remove(at);
            } else {
                entries[at].1 = json!(kept);
            }
        }
    }
    Ok(entries)
}
