//! Byte scanners for the privacy placeholder token grammar, used by restore.
//!
//! Restore runs on every rendered message (`restore_page`), including chats
//! without any mappings. A first `Regex::new` there pulls the whole regex
//! compiler into the first history read, which in the browser means thousands
//! of lazily compiled WebAssembly functions on the critical path. These
//! scanners match exactly what the former patterns matched:
//! - [`find`]: `\[[A-Za-z][A-Za-z0-9_]*\]`, leftmost-first, non-overlapping;
//! - [`is_token`]: `^\[[A-Za-z][A-Za-z0-9_]*\]$`;
//! - [`is_generated`]: `^\[OM_PII_[A-F0-9]{32}\]$`.
//!
//! All grammar bytes are ASCII, so every reported range lies on UTF-8 char
//! boundaries of the scanned `&str`.

/// Length of the token starting at `start` (which must hold `[`), if any.
fn token_len(bytes: &[u8], start: usize) -> Option<usize> {
    if bytes.get(start) != Some(&b'[') || !bytes.get(start + 1).is_some_and(u8::is_ascii_alphabetic)
    {
        return None;
    }
    let mut end = start + 2;
    while bytes
        .get(end)
        .is_some_and(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
    {
        end += 1;
    }
    (bytes.get(end) == Some(&b']')).then_some(end + 1 - start)
}

/// Placeholder tokens in `text` as `(start, end)` byte ranges, in order.
pub(super) fn find(text: &str) -> impl Iterator<Item = (usize, usize)> + '_ {
    let bytes = text.as_bytes();
    let mut cursor = 0;
    std::iter::from_fn(move || {
        while cursor < bytes.len() {
            let start = cursor + bytes[cursor..].iter().position(|byte| *byte == b'[')?;
            match token_len(bytes, start) {
                Some(length) => {
                    cursor = start + length;
                    return Some((start, cursor));
                }
                None => cursor = start + 1,
            }
        }
        None
    })
}

/// True when the whole of `token` is one placeholder token.
pub(super) fn is_token(token: &str) -> bool {
    token_len(token.as_bytes(), 0) == Some(token.len())
}

/// True when the whole of `token` is a generated `[OM_PII_<32 upper hex>]` token.
pub(super) fn is_generated(token: &str) -> bool {
    let Some(hex) = token
        .strip_prefix("[OM_PII_")
        .and_then(|rest| rest.strip_suffix(']'))
    else {
        return false;
    };
    hex.len() == 32
        && hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'A'..=b'F').contains(&byte))
}

#[cfg(test)]
#[path = "placeholder_tests.rs"]
mod placeholder_tests;
