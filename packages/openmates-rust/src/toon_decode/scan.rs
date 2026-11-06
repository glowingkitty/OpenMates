//! Line scanner and token helpers of the TOON decoder (port of the 4.4.0
//! `scanner.ts`, `string-utils.ts` and `literal-utils.ts`, non-strict mode).
//! Content is held as `char` slices so index arithmetic mirrors the TS string
//! indexing for every character the grammar inspects (all ASCII).
use super::ToonDecodeError;
use super::value::ToonValue;

/// TOON indentation unit (the TS default `indent: 2`).
const INDENT_SIZE: usize = 2;

/// One non-blank, non-comment source line.
pub(super) struct Line {
    /// Line text after its leading indentation, trailing spaces trimmed.
    pub content: Vec<char>,
    /// Non-strict depth: `floor(spaces / 2) + tabs` of the leading whitespace.
    pub depth: usize,
    /// 1-based source line number.
    pub number: usize,
}

/// `parseLineIncremental` over `input.split("\n")`: strips a first-line BOM
/// and a trailing `\r`, skips blank lines and `#` comments (only when the
/// indentation has no tab, as in TS).
pub(super) fn scan_lines(input: &str) -> Vec<Line> {
    let mut lines = Vec::new();
    for (index, raw) in input.split('\n').enumerate() {
        let mut chars: Vec<char> = raw.chars().collect();
        if index == 0 && chars.first() == Some(&'\u{feff}') {
            chars.remove(0);
        }
        if chars.last() == Some(&'\r') {
            chars.pop();
        }
        let indent = chars
            .iter()
            .take_while(|c| **c == ' ' || **c == '\t')
            .count();
        let tabs = chars[..indent].iter().filter(|c| **c == '\t').count();
        let mut content = chars.split_off(indent);
        while content.last() == Some(&' ') {
            content.pop();
        }
        if tabs == 0 && content.first() == Some(&'#') {
            continue;
        }
        if content.is_empty() {
            continue;
        }
        let depth = (indent - tabs) / INDENT_SIZE + tabs;
        lines.push(Line {
            content,
            depth,
            number: index + 1,
        });
    }
    lines
}

/// `trimSpaces`: trims U+0020 only (never tabs or other whitespace).
pub(super) fn trim_spaces(value: &[char]) -> &[char] {
    let start = value.iter().take_while(|c| **c == ' ').count();
    let end = value.len()
        - value[start..]
            .iter()
            .rev()
            .take_while(|c| **c == ' ')
            .count();
    &value[start..end]
}

pub(super) fn text(value: &[char]) -> String {
    value.iter().collect()
}

pub(super) fn is(value: &[char], literal: &str) -> bool {
    value.iter().copied().eq(literal.chars())
}

/// `findClosingQuote`: index of the quote closing the one at `start`.
pub(super) fn find_closing_quote(content: &[char], start: usize) -> Option<usize> {
    let mut i = start + 1;
    while i < content.len() {
        if content[i] == '\\' && i + 1 < content.len() {
            i += 2;
            continue;
        }
        if content[i] == '"' {
            return Some(i);
        }
        i += 1;
    }
    None
}

/// `findUnquotedChar`: first `target` outside double quotes, scanning from
/// `start` with the quote state reset there (as TS does).
pub(super) fn find_unquoted(content: &[char], target: char, start: usize) -> Option<usize> {
    let mut in_quotes = false;
    let mut i = start;
    while i < content.len() {
        let c = content[i];
        if c == '\\' && i + 1 < content.len() && in_quotes {
            i += 2;
            continue;
        }
        if c == '"' {
            in_quotes = !in_quotes;
        } else if c == target && !in_quotes {
            return Some(i);
        }
        i += 1;
    }
    None
}

/// `unescapeString`: `\n \t \r \\ \"` and `\uXXXX` (lone surrogates refused).
pub(super) fn unescape(value: &[char]) -> Result<String, ToonDecodeError> {
    let mut out = String::with_capacity(value.len());
    let mut i = 0;
    while i < value.len() {
        if value[i] != '\\' {
            out.push(value[i]);
            i += 1;
            continue;
        }
        let next = value
            .get(i + 1)
            .ok_or(ToonDecodeError::new("backslash at end of string"))?;
        let simple = match next {
            'n' => Some('\n'),
            't' => Some('\t'),
            'r' => Some('\r'),
            '\\' => Some('\\'),
            '"' => Some('"'),
            _ => None,
        };
        if let Some(c) = simple {
            out.push(c);
            i += 2;
            continue;
        }
        if *next != 'u' {
            return Err(ToonDecodeError::new("invalid escape sequence"));
        }
        if i + 6 > value.len() {
            return Err(ToonDecodeError::new("truncated unicode escape"));
        }
        let hex = &value[i + 2..i + 6];
        if !hex.iter().all(char::is_ascii_hexdigit) {
            return Err(ToonDecodeError::new("unicode escape needs 4 hex digits"));
        }
        let code = u32::from_str_radix(&text(hex), 16)
            .map_err(|_| ToonDecodeError::new("unicode escape needs 4 hex digits"))?;
        let c = char::from_u32(code).ok_or(ToonDecodeError::new("lone surrogate escape"))?;
        out.push(c);
        i += 6;
    }
    Ok(out)
}

/// `parseStringLiteral`: a quoted token must close exactly at its end.
pub(super) fn parse_string_literal(token: &[char]) -> Result<String, ToonDecodeError> {
    let trimmed = trim_spaces(token);
    if trimmed.first() != Some(&'"') {
        return Ok(text(trimmed));
    }
    let close =
        find_closing_quote(trimmed, 0).ok_or(ToonDecodeError::new("unterminated string"))?;
    if close != trimmed.len() - 1 {
        return Err(ToonDecodeError::new(
            "unexpected characters after closing quote",
        ));
    }
    unescape(&trimmed[1..close])
}

/// `NUMERIC_LITERAL_PATTERN` (`-?(0|[1-9]\d*)(\.\d+)?(e[+-]?\d+)?`, case-
/// insensitive, ASCII digits) plus the TS finiteness check.
fn numeric_literal(token: &[char]) -> Option<f64> {
    let digits = |from: usize| {
        token[from..]
            .iter()
            .take_while(|c| c.is_ascii_digit())
            .count()
    };
    let mut i = usize::from(token.first() == Some(&'-'));
    match token.get(i) {
        Some('0') => i += 1,
        Some('1'..='9') => i += digits(i),
        _ => return None,
    }
    if token.get(i) == Some(&'.') {
        let count = digits(i + 1);
        if count == 0 {
            return None;
        }
        i += 1 + count;
    }
    if matches!(token.get(i), Some('e' | 'E')) {
        i += 1;
        if matches!(token.get(i), Some('+' | '-')) {
            i += 1;
        }
        let count = digits(i);
        if count == 0 {
            return None;
        }
        i += count;
    }
    if i != token.len() {
        return None;
    }
    // Rust's float parsing is correctly rounded like JS `Number`/`parseFloat`.
    text(token)
        .parse::<f64>()
        .ok()
        .filter(|value| value.is_finite())
}

/// `parsePrimitiveToken`: quoted string, `true`/`false`/`null`, a numeric
/// literal (`-0` becomes `0`), otherwise the trimmed token as a string.
pub(super) fn parse_primitive(token: &[char]) -> Result<ToonValue, ToonDecodeError> {
    let trimmed = trim_spaces(token);
    if trimmed.is_empty() {
        return Ok(ToonValue::String(String::new()));
    }
    if trimmed[0] == '"' {
        return parse_string_literal(trimmed).map(ToonValue::String);
    }
    if is(trimmed, "true") {
        return Ok(ToonValue::Bool(true));
    }
    if is(trimmed, "false") {
        return Ok(ToonValue::Bool(false));
    }
    if is(trimmed, "null") {
        return Ok(ToonValue::Null);
    }
    if let Some(number) = numeric_literal(trimmed) {
        // `Object.is(n, -0) ? 0 : n`: comparing with 0.0 also folds -0.
        return Ok(ToonValue::Number(if number == 0.0 { 0.0 } else { number }));
    }
    Ok(ToonValue::String(text(trimmed)))
}

/// `parseDelimitedValues`: split on `delimiter` outside quotes, cells trimmed.
pub(super) fn parse_delimited(input: &[char], delimiter: char) -> Vec<Vec<char>> {
    let mut values = Vec::new();
    let mut buffer: Vec<char> = Vec::new();
    let mut in_quotes = false;
    let mut i = 0;
    while i < input.len() {
        let c = input[i];
        if c == '\\' && i + 1 < input.len() && in_quotes {
            buffer.extend_from_slice(&input[i..i + 2]);
            i += 2;
            continue;
        }
        if c == '"' {
            in_quotes = !in_quotes;
        } else if c == delimiter && !in_quotes {
            values.push(trim_spaces(&buffer).to_vec());
            buffer.clear();
            i += 1;
            continue;
        }
        buffer.push(c);
        i += 1;
    }
    if !buffer.is_empty() || !values.is_empty() {
        values.push(trim_spaces(&buffer).to_vec());
    }
    values
}

/// `parseKeyToken` from the line start: `(key, index after the colon)`.
pub(super) fn parse_key_token(content: &[char]) -> Result<(String, usize), ToonDecodeError> {
    if content.first() == Some(&'"') {
        let close = find_closing_quote(content, 0)
            .ok_or(ToonDecodeError::new("unterminated quoted key"))?;
        let key = unescape(&content[1..close])?;
        let mut position = close + 1;
        while content.get(position) == Some(&' ') {
            position += 1;
        }
        if content.get(position) != Some(&':') {
            return Err(ToonDecodeError::new("missing colon after key"));
        }
        return Ok((key, position + 1));
    }
    let colon =
        find_unquoted(content, ':', 0).ok_or(ToonDecodeError::new("missing colon after key"))?;
    Ok((text(trim_spaces(&content[..colon])), colon + 1))
}

/// `isArrayHeaderContent`.
pub(super) fn is_array_header_content(content: &[char]) -> bool {
    trim_spaces(content).first() == Some(&'[') && find_unquoted(content, ':', 0).is_some()
}

/// `isKeyValueContent`.
pub(super) fn is_key_value(content: &[char]) -> bool {
    find_unquoted(content, ':', 0).is_some()
}

/// `isDataRow`: no colon, or the delimiter comes before the first colon.
pub(super) fn is_data_row(content: &[char], delimiter: char) -> bool {
    match (
        find_unquoted(content, ':', 0),
        find_unquoted(content, delimiter, 0),
    ) {
        (None, _) => true,
        (Some(colon), Some(delimiter)) => delimiter < colon,
        (Some(_), None) => false,
    }
}
