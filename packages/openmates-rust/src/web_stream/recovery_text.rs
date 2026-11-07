//! JavaScript `String.prototype.trim` emptiness for the recovery path (the
//! ECMAScript WhiteSpace and LineTerminator sets differ from Rust `trim`).
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy

/// True when `value.trim()` is empty under the ECMAScript WhiteSpace and
/// LineTerminator sets.
pub fn js_trim_is_empty(value: &str) -> bool {
    value.chars().all(is_js_space)
}

fn is_js_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n'
            | '\u{B}'
            | '\u{C}'
            | '\r'
            | ' '
            | '\u{A0}'
            | '\u{1680}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
            | '\u{FEFF}'
    ) || ('\u{2000}'..='\u{200A}').contains(&c)
}
