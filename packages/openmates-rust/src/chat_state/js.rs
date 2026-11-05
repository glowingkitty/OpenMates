//! Small JavaScript-semantics helpers so Rust decisions match the web client
//! exactly: UTF-16 `length`, `String.prototype.trim` whitespace and the
//! property order `JSON.stringify` emits for plain objects.

/// `value.length` in JavaScript (UTF-16 code units).
pub(crate) fn utf16_len(value: &str) -> usize {
    value.encode_utf16().count()
}

/// Characters removed by `String.prototype.trim` (WhiteSpace + LineTerminator).
fn js_whitespace(c: char) -> bool {
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

/// `value.trim()` is non-empty in JavaScript.
pub(crate) fn js_trim_nonempty(value: &str) -> bool {
    value.chars().any(|c| !js_whitespace(c))
}

/// `value.trim()` in JavaScript.
pub(crate) fn js_trim(value: &str) -> &str {
    value.trim_matches(js_whitespace)
}

/// `value.slice(0, max)` in UTF-16 units, never splitting a surrogate pair
/// (a pair cut by the limit is dropped whole).
pub(crate) fn utf16_prefix(value: &str, max: usize) -> &str {
    let mut units = 0;
    for (index, c) in value.char_indices() {
        units += c.len_utf16();
        if units > max {
            return &value[..index];
        }
    }
    value
}

/// `value.replace(/\s+/g, " ").trim()` with JavaScript `\s` semantics.
pub(crate) fn js_collapse_whitespace(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut in_space = false;
    for c in value.chars() {
        if js_whitespace(c) {
            in_space = true;
        } else {
            if in_space && !out.is_empty() {
                out.push(' ');
            }
            in_space = false;
            out.push(c);
        }
    }
    out
}

/// Canonical array-index property name (`"0"`, `"17"`, < 2^32 - 1).
fn array_index(key: &str) -> Option<u32> {
    if key.is_empty()
        || (key.len() > 1 && key.starts_with('0'))
        || !key.bytes().all(|b| b.is_ascii_digit())
    {
        return None;
    }
    key.parse::<u64>()
        .ok()
        .filter(|n| *n < u64::from(u32::MAX))
        .map(|n| n as u32)
}

/// Reorder (key, value) pairs the way a JavaScript plain object enumerates
/// them: array-index keys ascending first, then remaining keys in insertion
/// order. Duplicate keys keep the first position and the last value, exactly
/// like `JSON.parse` followed by `JSON.stringify`.
pub(crate) fn js_property_order<V>(pairs: Vec<(String, V)>) -> Vec<(String, V)> {
    let mut seen: Vec<(String, V)> = Vec::with_capacity(pairs.len());
    for (key, value) in pairs {
        if let Some(slot) = seen.iter_mut().find(|(existing, _)| *existing == key) {
            slot.1 = value;
        } else {
            seen.push((key, value));
        }
    }
    let (mut indexed, named): (Vec<_>, Vec<_>) = seen
        .into_iter()
        .partition(|(key, _)| array_index(key).is_some());
    indexed.sort_by_key(|(key, _)| array_index(key));
    indexed.extend(named);
    indexed
}

/// Serialize a JSON string literal with `JSON.stringify` escaping.
pub(crate) fn json_string(value: &str) -> String {
    serde_json::to_string(value).expect("string serialization is infallible")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn javascript_semantics_match_the_web_client() {
        assert_eq!(utf16_len("🔒🔒"), 4);
        assert!(!js_trim_nonempty("\u{FEFF} \u{3000}\n"));
        assert!(js_trim_nonempty("\u{0085}"));
        assert_eq!(js_collapse_whitespace("  a \n\t b  "), "a b");
        let ordered = js_property_order(vec![
            ("b".to_owned(), 1),
            ("10".to_owned(), 2),
            ("a".to_owned(), 3),
            ("2".to_owned(), 4),
            ("b".to_owned(), 5),
            ("01".to_owned(), 6),
        ]);
        let keys: Vec<_> = ordered.iter().map(|(k, v)| (k.as_str(), *v)).collect();
        assert_eq!(
            keys,
            vec![("2", 4), ("10", 2), ("b", 5), ("a", 3), ("01", 6)]
        );
        assert_eq!(json_string("a\"\u{1f}é"), "\"a\\\"\\u001fé\"");
    }
}
