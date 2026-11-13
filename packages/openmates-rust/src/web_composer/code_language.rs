//! Code-language detection of pasted and attached text for the web composer.
//! Ports `detectLanguageFromVSCode` and `detectLanguageFromContent`
//! (`enter_message/services/codeEmbedService.ts`) onto the shared `composer` unit.
//! Pure: no IO, no account state. JavaScript regex semantics are kept explicitly
//! (`\s` is the JS whitespace set, `\w` is ASCII, `.` excludes the four line
//! terminators, `/i` is ASCII-only) so the answer equals the TypeScript original.
//! spec: specifications/features/message-input#message-input.suggestions.contextual
use super::protocol;
use super::utf16::{WS_CLASS, js_trim};
use regex::Regex;
use serde::de::IgnoredAny;
use serde_json::{Value, json};
use std::sync::OnceLock;

/// Compiles a JS-flavoured pattern: `\s`/`\S` use the JS whitespace set, `\w` is
/// ASCII and `§` stands for the JS `.` (no `\n`, `\r`, U+2028, U+2029).
fn js_regex(pattern: &str) -> Regex {
    let expanded = pattern
        .replace("[\\w-]", "[A-Za-z0-9_-]")
        .replace("\\w", "[A-Za-z0-9_]")
        .replace("\\S", &format!("[^{WS_CLASS}]"))
        .replace("\\s", &format!("[{WS_CLASS}]"))
        .replace('§', "[^\\n\\r\\x{2028}\\x{2029}]");
    Regex::new(&expanded).expect("fixed language pattern compiles")
}

/// The ordered first-line and content patterns of `detectLanguageFromContent`.
struct Patterns {
    python_import: Regex,
    python_def: Regex,
    python_class: Regex,
    ts_import: Regex,
    js_require: Regex,
    ts_export: Regex,
    go_package: Regex,
    rust_item: Regex,
    java_package: Regex,
    java_class: Regex,
    c_include: Regex,
    c_main: Regex,
    ruby_require: Regex,
    ruby_class: Regex,
    sql: Regex,
    yaml_key: Regex,
    json_start: Regex,
    shell_command: Regex,
    shell_prompt: Regex,
    css_rule: Regex,
    css_root: Regex,
    markdown_heading: Regex,
    markdown_item: Regex,
}

fn patterns() -> &'static Patterns {
    static PATTERNS: OnceLock<Patterns> = OnceLock::new();
    PATTERNS.get_or_init(|| Patterns {
        python_import: js_regex(r"^(from\s+\S+\s+import|import\s+\S+)"),
        python_def: js_regex(r"^def\s+\w+\s*\("),
        python_class: js_regex(r"^class\s+\w+§*:"),
        ts_import: js_regex(r#"^import\s+§*\s+from\s+['"]"#),
        js_require: js_regex(r"^const\s+\w+\s*=\s*require\s*\("),
        ts_export: js_regex(r"^export\s+(default\s+)?(function|class|const|let|var|interface|type)"),
        go_package: js_regex(r"^package\s+\w+"),
        rust_item: js_regex(r"^(use\s+\w+|fn\s+\w+|pub\s+fn|impl\s+)"),
        java_package: js_regex(r"^package\s+[\w.]+;"),
        java_class: js_regex(r"^public\s+class\s+\w+"),
        c_include: js_regex(r#"^#include\s*[<"]"#),
        c_main: js_regex(r"^int\s+main\s*\("),
        ruby_require: js_regex(r#"^require\s+['"]"#),
        ruby_class: js_regex(r"^class\s+\w+\s*(<\s*\w+)?$"),
        // `/i` in JS folds ASCII only here (ſ and the Kelvin sign do not match), so the keywords are ASCII-folded.
        sql: js_regex(r"^(?i-u:(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP))\s+"),
        yaml_key: js_regex(r"^\w+:\s*$"),
        json_start: js_regex(r"^\s*[{\[]"),
        shell_command: js_regex(r"^(sudo\s+|apt\s+|npm\s+|yarn\s+|pip\s+|docker\s+|git\s+|curl\s+|wget\s+)"),
        shell_prompt: js_regex(r"^\$\s+\w+"),
        css_rule: js_regex(r"^[.#@][\w-]+\s*\{"),
        css_root: js_regex(r"^:\s*root\s*\{"),
        markdown_heading: js_regex(r"^#{1,6}\s+"),
        markdown_item: js_regex(r"^[-*+]\s+"),
    })
}

/// First 2000 UTF-16 units of `text` (`text.slice(0, 2000)`). A surrogate pair cut
/// in half is dropped: no pattern can match half a pair, so the answer is the same.
fn analysed_prefix(text: &str) -> &str {
    let mut units = 0usize;
    for (byte, c) in text.char_indices() {
        units += c.len_utf16();
        if units > 2000 {
            return &text[..byte];
        }
    }
    text
}

/// `detectLanguageFromVSCode`: the non-empty string `mode` of the clipboard JSON.
pub(crate) fn language_from_vscode(data: Option<&str>) -> Option<String> {
    let data = data.filter(|d| !d.is_empty())?;
    let parsed: Value = serde_json::from_str(data).ok()?;
    parsed.get("mode").and_then(Value::as_str).filter(|m| !m.is_empty()).map(str::to_string)
}

/// Language named by a shebang line, when it names a known interpreter.
fn shebang_language(first_line: &str) -> Option<&'static str> {
    let shebang = first_line.to_lowercase();
    // Order matters: a `python3 ... bash` line is python, exactly as in TypeScript.
    [
        (shebang.contains("python"), "python"),
        (shebang.contains("node"), "javascript"),
        (shebang.contains("bash") || shebang.contains("/sh"), "bash"),
        (shebang.contains("zsh"), "zsh"),
        (shebang.contains("ruby"), "ruby"),
        (shebang.contains("perl"), "perl"),
        (shebang.contains("php"), "php"),
    ]
    .into_iter()
    .find_map(|(hit, name)| hit.then_some(name))
}

/// `detectLanguageFromContent`: heuristic language of code text, `None` without a confident match.
pub(crate) fn language_from_content(text: &str) -> Option<&'static str> {
    let p = patterns();
    let first_line = js_trim(text.split('\n').next().unwrap_or(""));
    let content = analysed_prefix(text);
    let starts = |prefix: &str| first_line.starts_with(prefix);

    if starts("#!") {
        if let Some(language) = shebang_language(first_line) {
            return Some(language);
        }
    }
    if starts("<?xml") {
        return Some("xml");
    }
    if starts("<!DOCTYPE html") || starts("<html") {
        return Some("html");
    }
    if p.python_import.is_match(first_line) || p.python_def.is_match(first_line) || p.python_class.is_match(first_line) {
        return Some("python");
    }
    if p.ts_import.is_match(first_line) {
        return Some("typescript");
    }
    if p.js_require.is_match(first_line) {
        return Some("javascript");
    }
    if p.ts_export.is_match(first_line) {
        return Some("typescript");
    }
    if p.go_package.is_match(first_line) {
        return Some("go");
    }
    if p.rust_item.is_match(first_line) || (content.contains("fn main()") && content.contains("println!")) {
        return Some("rust");
    }
    if p.java_package.is_match(first_line) || p.java_class.is_match(content) {
        return Some("java");
    }
    if p.c_include.is_match(first_line) {
        return Some("cpp");
    }
    if p.c_main.is_match(content) {
        return Some("c");
    }
    if p.ruby_require.is_match(first_line) || p.ruby_class.is_match(first_line) {
        return Some("ruby");
    }
    if starts("<?php") {
        return Some("php");
    }
    if p.sql.is_match(first_line) {
        return Some("sql");
    }
    if p.yaml_key.is_match(first_line) && content.contains("\n  ") {
        return Some("yaml");
    }
    // The whole text must parse, not only the analysed prefix (as `JSON.parse(text)`).
    if p.json_start.is_match(first_line) && serde_json::from_str::<IgnoredAny>(text).is_ok() {
        return Some("json");
    }
    if p.shell_command.is_match(first_line) || p.shell_prompt.is_match(first_line) {
        return Some("bash");
    }
    if p.css_rule.is_match(first_line) || p.css_root.is_match(first_line) {
        return Some("css");
    }
    if p.markdown_heading.is_match(first_line) {
        return Some("markdown");
    }
    if p.markdown_item.is_match(first_line) && content.split('\n').filter(|l| p.markdown_item.is_match(l)).count() > 2 {
        return Some("markdown");
    }
    None
}

/// `{text?, vsCodeEditorData?}` -> `{vsCode, content}` (each a language or `null`).
/// `content` is `null` when no `text` is sent; `vsCode` is `null` without clipboard data.
///
/// # Errors
/// `protocol` when the payload is not an object or a present field has the wrong type.
pub fn language_detect_json(input: &str) -> Result<String, String> {
    let payload: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = match payload.get("text") {
        None | Some(Value::Null) => None,
        Some(Value::String(text)) => Some(text.as_str()),
        Some(_) => return Err(protocol(())),
    };
    let clipboard = match payload.get("vsCodeEditorData") {
        None | Some(Value::Null) => None,
        Some(Value::String(data)) => Some(data.as_str()),
        Some(_) => return Err(protocol(())),
    };
    if !payload.is_object() {
        return Err(protocol(()));
    }
    Ok(json!({"vsCode": language_from_vscode(clipboard), "content": text.and_then(language_from_content)}).to_string())
}
