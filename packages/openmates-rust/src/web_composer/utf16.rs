//! JavaScript string semantics needed by the composer ports: UTF-16 offsets,
//! the JS `\s` whitespace set, `trim`, `indexOf` and `split().join()`.
//! spec: specifications/features/pii-protection#pii.composer.detect-redact-exclude

/// JS `\s` / `String.prototype.trim` whitespace as a regex class body.
pub(crate) const WS_CLASS: &str = r"\x{9}-\x{d}\x{20}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}\x{feff}";

/// True for a code point in JavaScript's `\s` set (not Unicode White_Space: no U+0085, with U+FEFF).
pub(crate) fn is_js_ws(c: char) -> bool {
    matches!(c as u32, 9..=13 | 0x20 | 0xa0 | 0x1680 | 0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000 | 0xfeff)
}

/// `String.prototype.trim` on a `&str`.
pub(crate) fn js_trim(text: &str) -> &str {
    text.trim_matches(is_js_ws)
}

/// UTF-16 length of `text` (JS `.length`).
pub(crate) fn len16(text: &str) -> usize {
    text.chars().map(char::len_utf16).sum()
}

/// Maps byte offsets of a `&str` to UTF-16 offsets (identity for ASCII).
pub(crate) struct Utf16Index {
    ascii: bool,
    map: Vec<u32>,
}

impl Utf16Index {
    /// Builds the byte-to-UTF-16 map once for `text`.
    pub(crate) fn new(text: &str) -> Self {
        if text.is_ascii() {
            return Self { ascii: true, map: Vec::new() };
        }
        let mut map = vec![0u32; text.len() + 1];
        let mut units = 0u32;
        for (byte, c) in text.char_indices() {
            map[byte] = units;
            units += c.len_utf16() as u32;
        }
        map[text.len()] = units;
        Self { ascii: false, map }
    }

    /// UTF-16 offset of a char-boundary byte offset.
    pub(crate) fn at(&self, byte: usize) -> usize {
        if self.ascii { byte } else { self.map[byte] as usize }
    }
}

/// Encodes `text` as UTF-16 code units.
pub(crate) fn units(text: &str) -> Vec<u16> {
    text.encode_utf16().collect()
}

/// Decodes units; a lone surrogate is a protocol error (JSON cannot carry it into Rust).
pub(crate) fn string(units: &[u16]) -> Result<String, String> {
    String::from_utf16(units).map_err(super::protocol)
}

/// `haystack.indexOf(needle, from)` on code units; an empty needle matches at `from` (clamped).
pub(crate) fn index_of(hay: &[u16], needle: &[u16], from: usize) -> Option<usize> {
    let from = from.min(hay.len());
    if needle.is_empty() {
        return Some(from);
    }
    if needle.len() > hay.len() {
        return None;
    }
    (from..=hay.len() - needle.len()).find(|&i| hay[i..i + needle.len()] == *needle)
}

/// `hay.split(needle).join(rep)` on code units (empty needle splits between every unit).
pub(crate) fn split_join(hay: &[u16], needle: &[u16], rep: &[u16]) -> Vec<u16> {
    let mut out = Vec::with_capacity(hay.len());
    if needle.is_empty() {
        for (i, unit) in hay.iter().enumerate() {
            if i > 0 {
                out.extend_from_slice(rep);
            }
            out.push(*unit);
        }
        return out;
    }
    let mut cursor = 0;
    while let Some(at) = index_of(hay, needle, cursor) {
        out.extend_from_slice(&hay[cursor..at]);
        out.extend_from_slice(rep);
        cursor = at + needle.len();
    }
    out.extend_from_slice(&hay[cursor..]);
    out
}

/// `text.substring(a, b)` semantics: clamp to the length and swap when reversed.
pub(crate) fn substring(text: &[u16], a: i64, b: i64) -> &[u16] {
    let clamp = |v: i64| v.clamp(0, text.len() as i64) as usize;
    let (a, b) = (clamp(a), clamp(b));
    &text[a.min(b)..a.max(b)]
}

/// JS regex `\w` (ASCII word character) for boundary checks.
pub(crate) fn is_word(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}
