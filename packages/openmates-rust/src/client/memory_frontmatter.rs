//! The YAML subset of Memory document frontmatter, read and written without a
//! YAML library (the Apple framework builds without `workflow-yaml`): top-level
//! `key: value` lines, plain, single- and double-quoted (with line folding and
//! escapes) and block (`|`, `>`) scalars. Used by `memory_document_fields`,
//! which mirrors `parseRuleDocument` of `frontend/packages/ui/src/utils/ruleDocuments.ts`.
//! Spec: `features.app-memories`.
use super::memory_documents::{MemoryDocumentError, MemoryResult};
use zeroize::{Zeroize, Zeroizing};

fn invalid<T>() -> MemoryResult<T> {
    Err(MemoryDocumentError::InvalidDocument)
}

/// One top-level `key: value` of the frontmatter with its continuation lines.
pub(super) struct Entry<'a> {
    pub(super) key: &'a str,
    pub(super) first: &'a str,
    pub(super) rest: Vec<&'a str>,
}

/// A decoded scalar; plain scalars still need the YAML core-schema type check.
pub(super) enum Scalar {
    /// Unquoted text; may still be a null, bool or number.
    Plain(String),
    /// Quoted or block text: always a string.
    Quoted(String),
}

impl Drop for Scalar {
    fn drop(&mut self) {
        match self {
            Self::Plain(text) | Self::Quoted(text) => text.zeroize(),
        }
    }
}

pub(super) fn split(document: &str) -> MemoryResult<(&str, &str)> {
    static FENCE: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let fence = FENCE.get_or_init(|| {
        regex::Regex::new(r"(?s)\A---\r?\n(.*?)\r?\n---(?:\r?\n|\z)(.*)\z")
            .expect("static frontmatter expression")
    });
    let source = document.strip_prefix('\u{FEFF}').unwrap_or(document);
    let captures = fence
        .captures(source)
        .ok_or(MemoryDocumentError::InvalidDocument)?;
    let (header, body) = (captures.get(1), captures.get(2));
    match (header, body) {
        (Some(header), Some(body)) => Ok((header.as_str(), body.as_str())),
        _ => invalid(),
    }
}

/// Top-level keys at column 0; indented and blank lines continue the last key.
pub(super) fn entries<'a>(header: &'a str, keys: &[&str]) -> MemoryResult<Vec<Entry<'a>>> {
    static KEY: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let key = KEY.get_or_init(|| {
        regex::Regex::new(r"\A([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:(?:[ \t]+(.*))?\z")
            .expect("static key expression")
    });
    let mut out: Vec<Entry<'a>> = Vec::new();
    for line in header.split('\n') {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.starts_with('#') {
            continue;
        }
        if line.is_empty() || line.starts_with([' ', '\t']) {
            match out.last_mut() {
                Some(entry) => entry.rest.push(line),
                None if line.trim().is_empty() => {}
                None => return invalid(),
            }
            continue;
        }
        let found = key
            .captures(line)
            .ok_or(MemoryDocumentError::InvalidDocument)?;
        let name = found.get(1).map_or("", |m| m.as_str());
        if !keys.contains(&name) || out.iter().any(|e| e.key == name) {
            return invalid();
        }
        out.push(Entry {
            key: name,
            first: found.get(2).map_or("", |m| m.as_str()),
            rest: Vec::new(),
        });
    }
    // Trailing blank lines belong to no value.
    for entry in &mut out {
        while entry.rest.last().is_some_and(|l| l.trim().is_empty()) {
            entry.rest.pop();
        }
    }
    Ok(out)
}

pub(super) fn strip_comment(text: &str) -> &str {
    match text.find(" #").or_else(|| text.find("\t#")) {
        Some(at) => &text[..at],
        None if text.starts_with('#') => "",
        None => text,
    }
}

pub(super) fn leading_spaces(line: &str) -> usize {
    line.len() - line.trim_start_matches(' ').len()
}

/// `|` and `>` block scalars with chomping and indentation indicators.
fn block(indicator: &str, rest: &[&str]) -> MemoryResult<String> {
    let mut chars = strip_comment(indicator).trim_end().chars();
    let folded = chars.next() == Some('>');
    let (mut chomp, mut indent) = ('c', None);
    for c in chars {
        match c {
            '-' | '+' if chomp == 'c' => chomp = c,
            '1'..='9' if indent.is_none() => indent = c.to_digit(10).map(|d| d as usize),
            _ => return invalid(),
        }
    }
    let indent = indent.unwrap_or_else(|| {
        rest.iter()
            .find(|l| !l.trim().is_empty())
            .map_or(1, |l| leading_spaces(l))
    });
    let mut lines = Vec::with_capacity(rest.len());
    for line in rest {
        if line.trim().is_empty() {
            lines.push("");
        } else if leading_spaces(line) < indent {
            return invalid();
        } else {
            lines.push(&line[indent..]);
        }
    }
    let mut out = String::new();
    if folded {
        let (mut previous, mut empty) = (None::<bool>, 0usize);
        for line in &lines {
            if line.is_empty() {
                empty += 1;
                continue;
            }
            let more = line.starts_with([' ', '\t']);
            match previous {
                None => out.push_str(&"\n".repeat(empty)),
                Some(false) if !more && empty == 0 => out.push(' '),
                Some(false) if !more => out.push_str(&"\n".repeat(empty)),
                Some(_) => out.push_str(&"\n".repeat(empty + 1)),
            }
            out.push_str(line);
            (previous, empty) = (Some(more), 0);
        }
    } else {
        out = lines.join("\n");
    }
    let content = out.trim_end_matches('\n').len();
    let trailing = out.len() - content;
    out.truncate(content);
    match chomp {
        '-' => {}
        '+' => out.push_str(&"\n".repeat(trailing.max(1))),
        _ if !out.is_empty() => out.push('\n'),
        _ => {}
    }
    Ok(out)
}

/// Line folding of flow scalars: a break becomes a space, `n` empty lines become `n` newlines.
fn fold_break(out: &mut String, raw: &[char], at: &mut usize) {
    while out.ends_with([' ', '\t']) {
        out.pop();
    }
    let mut empty = 0;
    loop {
        while *at < raw.len() && matches!(raw[*at], ' ' | '\t') {
            *at += 1;
        }
        if *at < raw.len() && raw[*at] == '\n' {
            empty += 1;
            *at += 1;
        } else {
            break;
        }
    }
    if empty == 0 {
        out.push(' ');
    } else {
        out.push_str(&"\n".repeat(empty));
    }
}

fn escape(raw: &[char], at: &mut usize) -> MemoryResult<Option<char>> {
    let c = *raw.get(*at).ok_or(MemoryDocumentError::InvalidDocument)?;
    *at += 1;
    let hex = |at: &mut usize, n: usize| -> MemoryResult<char> {
        let digits: String = raw.get(*at..*at + n).unwrap_or_default().iter().collect();
        *at += n;
        u32::from_str_radix(&digits, 16)
            .ok()
            .filter(|_| digits.len() == n)
            .and_then(char::from_u32)
            .ok_or(MemoryDocumentError::InvalidDocument)
    };
    Ok(Some(match c {
        '0' => '\0',
        'a' => '\u{7}',
        'b' => '\u{8}',
        't' | '\t' => '\t',
        'n' => '\n',
        'v' => '\u{b}',
        'f' => '\u{c}',
        'r' => '\r',
        'e' => '\u{1b}',
        ' ' => ' ',
        '"' => '"',
        '/' => '/',
        '\\' => '\\',
        'N' => '\u{85}',
        '_' => '\u{a0}',
        'L' => '\u{2028}',
        'P' => '\u{2029}',
        'x' => hex(at, 2)?,
        'u' => hex(at, 4)?,
        'U' => hex(at, 8)?,
        '\n' => {
            // Escaped line break: join without a space.
            while *at < raw.len() && matches!(raw[*at], ' ' | '\t') {
                *at += 1;
            }
            return Ok(None);
        }
        _ => return invalid(),
    }))
}

/// `"..."` and `'...'` scalars, possibly over several lines.
fn quoted(first: &str, rest: &[&str]) -> MemoryResult<String> {
    let double = first.starts_with('"');
    let mut joined = Zeroizing::new(first[1..].to_owned());
    for line in rest {
        joined.push('\n');
        joined.push_str(line);
    }
    let raw: Zeroizing<Vec<char>> = Zeroizing::new(joined.chars().collect());
    let (mut out, mut at) = (String::new(), 0usize);
    loop {
        let c = *raw.get(at).ok_or(MemoryDocumentError::InvalidDocument)?;
        at += 1;
        match c {
            '"' if double => break,
            '\'' if !double && raw.get(at) == Some(&'\'') => {
                out.push('\'');
                at += 1;
            }
            '\'' if !double => break,
            '\\' if double => {
                if let Some(c) = escape(&raw, &mut at)? {
                    out.push(c);
                }
            }
            '\n' => fold_break(&mut out, &raw, &mut at),
            c => out.push(c),
        }
    }
    let tail: String = raw[at..].iter().collect();
    if !strip_comment(&tail).trim().is_empty() {
        return invalid();
    }
    Ok(out)
}

fn plain(first: &str, rest: &[&str]) -> MemoryResult<String> {
    let mut out = strip_comment(first).trim().to_owned();
    if out.contains(": ") || out.ends_with(':') {
        // `key: a: b` is a YAML error, not the text `a: b`.
        return invalid();
    }
    let mut empty = 0;
    for line in rest {
        let line = strip_comment(line).trim();
        if line.is_empty() {
            empty += 1;
            continue;
        }
        if line.starts_with("- ") || line == "-" || line.contains(": ") || line.ends_with(':') {
            // A nested sequence or mapping, not a scalar.
            return invalid();
        }
        if !out.is_empty() {
            out.push_str(&if empty == 0 {
                " ".into()
            } else {
                "\n".repeat(empty)
            });
        }
        out.push_str(line);
        empty = 0;
    }
    Ok(out)
}

pub(super) fn scalar(first: &str, rest: &[&str]) -> MemoryResult<Scalar> {
    let first = first.trim_start();
    match first.chars().next() {
        Some('"' | '\'') => quoted(first, rest).map(Scalar::Quoted),
        Some('|' | '>') => block(first, rest).map(Scalar::Quoted),
        // Flow collections, anchors, aliases, tags and reserved indicators.
        Some('[' | '{' | '&' | '*' | '!' | '%' | '@' | '`') => invalid(),
        _ => plain(first, rest).map(Scalar::Plain),
    }
}

/// YAML 1.2 core schema: plain scalars that are not strings.
pub(super) fn non_string(plain: &str) -> bool {
    static SPECIAL: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let special = SPECIAL.get_or_init(|| {
        regex::Regex::new(concat!(
            r"\A(?:~|null|Null|NULL|true|True|TRUE|false|False|FALSE",
            r"|[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+",
            r"|[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?",
            r"|[-+]?\.(?:inf|Inf|INF)|\.nan|\.NaN|\.NAN)\z"
        ))
        .expect("static core schema expression")
    });
    plain.is_empty() || special.is_match(plain)
}

/// A YAML double-quoted scalar. JSON escapes are valid YAML escapes; the
/// characters YAML treats as line breaks or non-printable are escaped too,
/// so the web (`yaml`) and server (PyYAML) parsers read the exact text.
pub(super) fn yaml_quoted(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('"');
    for c in value.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            c if (c as u32) < 0x20
                || ('\u{7f}'..='\u{9f}').contains(&c)
                || matches!(
                    c,
                    '\u{2028}' | '\u{2029}' | '\u{feff}' | '\u{fffe}' | '\u{ffff}'
                ) =>
            {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}
