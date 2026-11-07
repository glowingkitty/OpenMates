//! Paste classification of the message composer: prose stays text, obvious code
//! becomes a code embed, long or formatted documents a docs embed, tabular
//! clipboard data a sheet embed. Port of `pasteClassification.ts`.
//! spec: specifications/features/message-input#message-input.embeds.gated-send
use super::protocol;
use super::utf16::{WS_CLASS, js_trim, len16};
use regex::{NoExpand, Regex};
use serde_json::{Value, json};
use std::sync::OnceLock;

const LONG_DOCUMENT_MIN_CHARS: usize = 1800;
const LONG_DOCUMENT_MIN_WORDS: usize = 180;
const LONG_DOCUMENT_MIN_LINES: usize = 10;

const CODE_LIKE_LANGUAGES: &[&str] = &[
    "bash", "c", "cpp", "css", "go", "html", "java", "javascript", "json", "kotlin", "php", "python",
    "ruby", "rust", "sql", "svelte", "swift", "typescript", "xml", "yaml", "zsh",
];

struct Patterns {
    table_html: Regex,
    document_tag: Regex,
    row: Regex,
    cell: Regex,
    br: Regex,
    tag: Regex,
    spaces: Regex,
    table_separator_at_line: Regex,
    heading_at_line: Regex,
}

fn patterns() -> &'static Patterns {
    static P: OnceLock<Patterns> = OnceLock::new();
    P.get_or_init(|| {
        let ws = WS_CLASS;
        let lt = r"\n\r\x{2028}\x{2029}";
        let build = |p: String| Regex::new(&p).expect("fixed paste pattern compiles");
        Patterns {
            table_html: build(r"(?i-u:<table(?-u:\b))".to_string()),
            document_tag: build(r"(?i-u:<(?:h[1-6]|article|section|blockquote|ol|ul|li)\b)".to_string()),
            row: build(r"(?i-u:<tr\b)[^>]*>((?s:.)*?)(?i-u:</tr>)".to_string()),
            cell: build(r"(?i-u:<t[hd]\b)[^>]*>((?s:.)*?)(?i-u:</t[hd]>)".to_string()),
            br: build(format!(r"(?i-u:<br)[{ws}]*/?[{ws}]*>")),
            tag: build(r"<[^>]+>".to_string()),
            spaces: build(format!(r"[{ws}]+")),
            // JS `/m` anchors at \n \r U+2028 U+2029; tried per line start with `\A`.
            table_separator_at_line: build(format!(
                r"\A[{ws}]*\|?[{ws}]*:?-{{3,}}:?[{ws}]*(?:\|[{ws}]*:?-{{3,}}:?[{ws}]*)+\|?[{ws}]*(?:\z|[{lt}])"
            )),
            heading_at_line: build(format!(r"\A#{{1,6}}[{ws}]+[^{ws}]")),
        }
    })
}

/// Byte offsets where a JS multiline `^` can match.
fn line_starts(text: &str) -> Vec<usize> {
    let mut starts = vec![0];
    for (i, c) in text.char_indices() {
        if matches!(c, '\n' | '\r' | '\u{2028}' | '\u{2029}') {
            starts.push(i + c.len_utf8());
        }
    }
    starts
}

fn any_line(text: &str, re: &Regex) -> bool {
    line_starts(text).into_iter().any(|s| re.is_match(&text[s..]))
}

fn escape_html(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#39;")
}

/// `plainTextToDocumentHtml`: paragraphs split on blank lines, `\n` to `<br>`.
pub(crate) fn plain_text_to_document_html(text: &str) -> String {
    let blocks = split_blank_lines(js_trim(text));
    blocks
        .iter()
        .map(|p| js_trim(p))
        .filter(|p| !p.is_empty())
        .map(|p| format!("<p>{}</p>", escape_html(p).replace('\n', "<br>")))
        .collect::<Vec<_>>()
        .join("\n")
}

/// `text.split(/\n{2,}/)`.
fn split_blank_lines(text: &str) -> Vec<&str> {
    let mut parts = Vec::new();
    let bytes = text.as_bytes();
    let (mut start, mut i) = (0, 0);
    while i < bytes.len() {
        if bytes[i] == b'\n' {
            let mut j = i;
            while j < bytes.len() && bytes[j] == b'\n' {
                j += 1;
            }
            if j - i >= 2 {
                parts.push(&text[start..i]);
                start = j;
            }
            i = j;
        } else {
            i += 1;
        }
    }
    parts.push(&text[start..]);
    parts
}

fn has_document_formatting(text: &str, html: &str) -> bool {
    let p = patterns();
    p.table_html.is_match(html) || p.document_tag.is_match(html) || any_line(text, &p.heading_at_line)
}

fn is_long_document(text: &str) -> bool {
    let words = text.split(super::utf16::is_js_ws).filter(|w| !w.is_empty()).count();
    let lines = text.split('\n').filter(|l| !js_trim(l).is_empty()).count();
    len16(text) >= LONG_DOCUMENT_MIN_CHARS || words >= LONG_DOCUMENT_MIN_WORDS || lines >= LONG_DOCUMENT_MIN_LINES
}

fn is_code_language(language: Option<&str>) -> bool {
    language.is_some_and(|l| !l.is_empty() && CODE_LIKE_LANGUAGES.contains(&l.to_lowercase().as_str()))
}

fn extract_markdown_table(text: &str) -> Option<String> {
    if !text.contains('|') || !any_line(text, &patterns().table_separator_at_line) {
        return None;
    }
    let table: Vec<&str> = text.split('\n').map(js_trim).filter(|l| l.starts_with('|') && l.ends_with('|')).collect();
    (table.len() >= 2).then(|| table.join("\n"))
}

fn escape_table_cell(value: &str) -> String {
    let piped = value.replace('|', "\\|");
    js_trim(&patterns().spaces.replace_all(&piped, NoExpand(" "))).to_string()
}

fn rows_to_markdown_table(rows: &[Vec<String>]) -> String {
    let render = |row: &[String]| format!("| {} |", row.iter().map(|c| escape_table_cell(c)).collect::<Vec<_>>().join(" | "));
    let separator = format!("| {} |", rows[0].iter().map(|_| "---").collect::<Vec<_>>().join(" | "));
    let mut lines = vec![render(&rows[0]), separator];
    lines.extend(rows[1..].iter().map(|r| render(r)));
    lines.join("\n")
}

fn split_delimited_row(line: &str, tab: bool) -> Vec<String> {
    if tab {
        return line.split('\t').map(|c| js_trim(c).to_string()).collect();
    }
    line.split(',')
        .map(|cell| {
            let cell = js_trim(cell);
            // `/^"|"$/g`: a leading quote goes first, so a lone quote is removed once.
            let rest = cell.strip_prefix('"').unwrap_or(cell);
            let dropped_front = rest.len() != cell.len();
            let rest = if dropped_front || cell.ends_with('"') { rest.strip_suffix('"').unwrap_or(rest) } else { rest };
            rest.to_string()
        })
        .collect()
}

fn extract_delimited_table(text: &str) -> Option<String> {
    let lines: Vec<&str> = text.split('\n').map(js_trim).filter(|l| !l.is_empty()).collect();
    if lines.len() < 2 {
        return None;
    }
    let tab = lines.iter().any(|l| l.contains('\t'));
    if !tab && (!lines.iter().all(|l| l.contains(',')) || lines.len() < 3) {
        return None;
    }
    let rows: Vec<Vec<String>> = lines.iter().map(|l| split_delimited_row(l, tab)).collect();
    let columns = rows[0].len();
    (columns >= 2 && rows.iter().all(|r| r.len() == columns)).then(|| rows_to_markdown_table(&rows))
}

fn html_to_plain_text(html: &str) -> String {
    let p = patterns();
    let text = p.br.replace_all(html, NoExpand(" ")).into_owned();
    let text = p.tag.replace_all(&text, NoExpand("")).into_owned();
    let mut text = text;
    for (entity, rep) in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", "\"")] {
        text = replace_ascii_ci(&text, entity, rep);
    }
    let text = text.replace("&#39;", "'");
    js_trim(&p.spaces.replace_all(&text, NoExpand(" "))).to_string()
}

/// Case-insensitive (ASCII) global literal replace, like `/&amp;/gi`.
fn replace_ascii_ci(text: &str, needle: &str, rep: &str) -> String {
    let lower = text.to_ascii_lowercase();
    let mut out = String::with_capacity(text.len());
    let mut cursor = 0;
    while let Some(found) = lower[cursor..].find(needle) {
        out.push_str(&text[cursor..cursor + found]);
        out.push_str(rep);
        cursor += found + needle.len();
    }
    out.push_str(&text[cursor..]);
    out
}

fn extract_html_table(html: &str) -> Option<String> {
    let p = patterns();
    if !p.table_html.is_match(html) {
        return None;
    }
    let rows: Vec<Vec<String>> = p
        .row
        .captures_iter(html)
        .map(|row| p.cell.captures_iter(&row[1]).map(|cell| html_to_plain_text(&cell[1])).collect::<Vec<_>>())
        .filter(|row| !row.is_empty())
        .collect();
    if rows.len() < 2 || rows[0].len() < 2 {
        return None;
    }
    let columns = rows[0].len();
    let padded: Vec<Vec<String>> = rows
        .into_iter()
        .map(|mut row| {
            row.resize(columns, String::new());
            row
        })
        .collect();
    Some(rows_to_markdown_table(&padded))
}

/// `classifyPastedContent`: `{text, html?, vsCodeLanguage?, detectedLanguage?}` ->
/// `{kind, reason, sheetMarkdown?, documentHtml?}`.
///
/// # Errors
/// `protocol` when the payload is not an object with a string `text`.
pub fn classify_pasted_content_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = value.get("text").and_then(Value::as_str).ok_or("protocol")?;
    let opt = |key: &str| value.get(key).and_then(Value::as_str);
    let (html, vscode, detected) = (opt("html"), opt("vsCodeLanguage"), opt("detectedLanguage"));
    let text = js_trim(text);
    let html = js_trim(html.unwrap_or(""));
    let out = if text.is_empty() && html.is_empty() {
        json!({"kind": "text", "reason": "empty"})
    } else if let Some(table) = extract_html_table(html) {
        json!({"kind": "sheet", "reason": "html-table", "sheetMarkdown": table})
    } else if let Some(table) = extract_markdown_table(text) {
        json!({"kind": "sheet", "reason": "markdown-table", "sheetMarkdown": table})
    } else if let Some(table) = extract_delimited_table(text) {
        json!({"kind": "sheet", "reason": "delimited-table", "sheetMarkdown": table})
    } else if vscode.is_some_and(|l| !l.is_empty()) {
        json!({"kind": "code", "reason": "vscode"})
    } else if has_document_formatting(text, html) {
        let document = if html.is_empty() { plain_text_to_document_html(text) } else { html.to_string() };
        json!({"kind": "document", "reason": "formatted-document", "documentHtml": document})
    } else if is_code_language(detected) {
        json!({"kind": "code", "reason": "language-detection"})
    } else if is_long_document(text) {
        json!({"kind": "document", "reason": "long-prose", "documentHtml": plain_text_to_document_html(text)})
    } else {
        json!({"kind": "text", "reason": "short-plain-text"})
    };
    Ok(out.to_string())
}

/// `plainTextToDocumentHtml` as a JSON op: `{text}` -> JSON string.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn plain_text_to_document_html_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = value.get("text").and_then(Value::as_str).ok_or("protocol")?;
    Ok(Value::String(plain_text_to_document_html(text)).to_string())
}
