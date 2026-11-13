//! Array-header parsing of the TOON decoder (port of 4.4.0 `parseArrayHeaderLine`,
//! `parseBracketSegment` and the field-list helpers). Non-strict: the declared
//! length is validated as a literal but never enforced, and duplicate field
//! names are accepted (the TS `strictError` is ignored outside strict mode).
use super::ToonDecodeError;
use super::scan::{find_closing_quote, find_unquoted, parse_string_literal, text, trim_spaces};

/// One field of a `{...}` field list; `children` for a nested group `f{a,b}`.
pub(super) struct Field {
    pub name: String,
    pub children: Option<Vec<Field>>,
}

/// A parsed `key[N<delim><:>]{fields}:` header.
pub(super) struct Header {
    /// Absent for a keyless `[N]:` header.
    pub key: Option<String>,
    /// `,` (default), tab or `|` from the bracket suffix.
    pub delimiter: char,
    pub fields: Option<Vec<Field>>,
    /// `[N:]` keyed tabular object.
    pub keyed: bool,
}

/// Result of header detection on one line's content.
pub(super) enum HeaderLine {
    NotHeader,
    /// The header plus non-empty inline values after its colon.
    Header(Header, Option<Vec<char>>),
}

fn invalid(reason: &'static str) -> ToonDecodeError {
    ToonDecodeError::new(reason)
}

fn ends_with_whitespace(value: &[char]) -> bool {
    matches!(value.last(), Some(' ' | '\t'))
}

/// `parseArrayHeaderLine` followed by the non-strict `resolveArrayHeader`:
/// `NotHeader`, a header, or the TS "invalid" outcomes as errors.
pub(super) fn parse_header_line(content: &[char]) -> Result<HeaderLine, ToonDecodeError> {
    let bracket_start = if content.first() == Some(&'"') {
        let Some(close) = find_closing_quote(content, 0) else {
            return Ok(HeaderLine::NotHeader);
        };
        if content.get(close + 1) != Some(&'[') {
            return Ok(HeaderLine::NotHeader);
        }
        close + 1
    } else {
        let Some(start) = find_unquoted(content, '[', 0) else {
            return Ok(HeaderLine::NotHeader);
        };
        start
    };
    match find_unquoted(content, ':', 0) {
        Some(first_colon) if first_colon >= bracket_start => {}
        _ => return Ok(HeaderLine::NotHeader),
    }
    let bracket_end = find_unquoted(content, ']', bracket_start)
        .ok_or(invalid("unterminated bracket segment"))?;
    let mut brace_end = bracket_end + 1;
    let brace_start = find_unquoted(content, '{', bracket_end);
    if let Some(brace) = brace_start {
        if find_unquoted(content, ':', bracket_end).is_some_and(|colon| brace < colon) {
            if brace != bracket_end + 1 {
                return Err(invalid(
                    "unexpected content between bracket segment and field list",
                ));
            }
            if let Some(end) = find_matching_brace(content, brace) {
                brace_end = end + 1;
            }
        }
    }
    let colon = find_unquoted(content, ':', bracket_end.max(brace_end))
        .ok_or(invalid("missing colon after array header"))?;
    // brace_end >= bracket_end + 1, so the gap starts at brace_end.
    if colon != brace_end {
        return Err(invalid(
            "unexpected content between bracket segment and colon",
        ));
    }
    let key = if bracket_start > 0 {
        let raw = &content[..bracket_start];
        if ends_with_whitespace(raw) {
            return Err(invalid("whitespace between key and bracket segment"));
        }
        Some(if raw[0] == '"' {
            parse_string_literal(raw)?
        } else {
            text(raw)
        })
    } else {
        None
    };
    let after_colon = trim_spaces(&content[colon + 1..]);
    let (delimiter, keyed) = parse_bracket_segment(&content[bracket_start + 1..bracket_end])?;
    let mut fields = None;
    if let Some(brace) = brace_start.filter(|brace| *brace < colon) {
        if let Some(end) = find_matching_brace(content, brace).filter(|end| *end < colon) {
            let fields_content = &content[brace + 1..end];
            if [',', '\t', '|'].into_iter().any(|candidate| {
                candidate != delimiter && find_unquoted(fields_content, candidate, 0).is_some()
            }) {
                return Err(invalid("header delimiter mismatch"));
            }
            fields = Some(parse_field_entries(fields_content, delimiter)?);
        }
    }
    if keyed && fields.is_none() {
        return Err(invalid("keyed header requires a field list"));
    }
    if fields.is_some() && !after_colon.is_empty() {
        return Err(invalid("content after fields-bearing header colon"));
    }
    let inline = (!after_colon.is_empty()).then(|| after_colon.to_vec());
    Ok(HeaderLine::Header(
        Header {
            key,
            delimiter,
            fields,
            keyed,
        },
        inline,
    ))
}

/// `parseBracketSegment`: `N`, then optional `:` (keyed), then optional tab or
/// `|` delimiter; `N` is `0` or a digit run without a leading zero.
fn parse_bracket_segment(segment: &[char]) -> Result<(char, bool), ToonDecodeError> {
    let mut content = segment;
    let mut delimiter = ',';
    if let Some(last @ ('\t' | '|')) = content.last().copied() {
        delimiter = last;
        content = &content[..content.len() - 1];
    }
    let keyed = content.last() == Some(&':');
    if keyed {
        content = &content[..content.len() - 1];
    }
    let valid = match content {
        ['0'] => true,
        [first, rest @ ..] => ('1'..='9').contains(first) && rest.iter().all(char::is_ascii_digit),
        [] => false,
    };
    if !valid {
        return Err(invalid("invalid array length"));
    }
    Ok((delimiter, keyed))
}

/// `parseFieldEntries`, recursing into nested groups.
fn parse_field_entries(content: &[char], delimiter: char) -> Result<Vec<Field>, ToonDecodeError> {
    split_field_entries(content, delimiter)
        .into_iter()
        .map(|entry| {
            let trimmed = trim_spaces(&entry);
            if trimmed.is_empty() {
                return Err(invalid("empty field name"));
            }
            let Some(group_start) = find_unquoted(trimmed, '{', 0) else {
                return Ok(Field {
                    name: parse_string_literal(trimmed)?,
                    children: None,
                });
            };
            let name = &trimmed[..group_start];
            if name.is_empty() {
                return Err(invalid("missing field name before nested group"));
            }
            if name.last() == Some(&' ') {
                return Err(invalid("whitespace before nested field group"));
            }
            let group_end = find_matching_brace(trimmed, group_start)
                .ok_or(invalid("unmatched brace in field list"))?;
            if group_end != trimmed.len() - 1 {
                return Err(invalid("content after nested field group"));
            }
            let children = parse_field_entries(&trimmed[group_start + 1..group_end], delimiter)?;
            Ok(Field {
                name: parse_string_literal(name)?,
                children: Some(children),
            })
        })
        .collect()
}

/// `splitFieldEntries`: split at brace depth zero outside quotes.
fn split_field_entries(content: &[char], delimiter: char) -> Vec<Vec<char>> {
    let mut entries = Vec::new();
    let mut buffer = Vec::new();
    let mut in_quotes = false;
    let mut depth: i64 = 0;
    let mut i = 0;
    while i < content.len() {
        let c = content[i];
        if c == '\\' && i + 1 < content.len() && in_quotes {
            buffer.extend_from_slice(&content[i..i + 2]);
            i += 2;
            continue;
        }
        if c == '"' {
            in_quotes = !in_quotes;
        } else if !in_quotes {
            if c == '{' {
                depth += 1;
            } else if c == '}' {
                depth -= 1;
            } else if c == delimiter && depth == 0 {
                entries.push(std::mem::take(&mut buffer));
                i += 1;
                continue;
            }
        }
        buffer.push(c);
        i += 1;
    }
    entries.push(buffer);
    entries
}

/// `findMatchingBrace`: the `}` closing the `{` at `start`, quotes ignored.
fn find_matching_brace(content: &[char], start: usize) -> Option<usize> {
    let mut in_quotes = false;
    let mut depth: i64 = 0;
    let mut i = start;
    while i < content.len() {
        let c = content[i];
        if c == '\\' && i + 1 < content.len() && in_quotes {
            i += 2;
            continue;
        }
        if c == '"' {
            in_quotes = !in_quotes;
        } else if !in_quotes {
            if c == '{' {
                depth += 1;
            } else if c == '}' {
                depth -= 1;
                if depth == 0 {
                    return Some(i);
                }
            }
        }
        i += 1;
    }
    None
}

/// `countLeafFields`: cells each row carries.
pub(super) fn count_leaf_fields(fields: &[Field]) -> usize {
    fields
        .iter()
        .map(|field| field.children.as_deref().map_or(1, count_leaf_fields))
        .sum()
}
