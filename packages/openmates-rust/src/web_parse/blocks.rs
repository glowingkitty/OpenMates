//! Assistant render-plan block model: safe-block partitioning, block ids,
//! convergence operations and semantic normalization.
//!
//! Shared core of the web `parse` unit. Mirrors the pure parts of
//! `frontend/packages/ui/src/message_parsing/streamingMessageBlocks.ts`
//! (`hashText`, `findSafeParagraphEnds`, `hasBalancedInlineSyntax`,
//! `isSafeCompletedBlock`, `isClosedStandaloneFence`, `partitionAuthoredMarkdown`,
//! block id/reuse assignment, `deriveOperations`, `normalizeAssistantRenderPlan`).
//! Compiled TipTap documents stay opaque JSON owned by the page compiler.
//! Spec: specifications/surfaces/sdk (sdk.client.thin-platform-boundary).
use serde_json::{json, Map, Value};
use std::collections::HashMap;

/// The only error code of this module (malformed request payload).
pub const PROTOCOL: &str = "protocol";

/// JS `String.prototype.trim` whitespace (differs from Rust: U+FEFF yes, U+0085 no).
fn js_ws(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{0B}' | '\u{0C}' | '\r' | ' ' | '\u{A0}' | '\u{1680}' | '\u{2000}'..='\u{200A}'
            | '\u{2028}' | '\u{2029}' | '\u{202F}' | '\u{205F}' | '\u{3000}' | '\u{FEFF}'
    )
}

fn trim(s: &str) -> &str {
    s.trim_matches(js_ws)
}

fn trim_start(s: &str) -> &str {
    s.trim_start_matches(js_ws)
}

/// FNV-1a over UTF-16 code units, base 36 (`hashText`); block ids derive from it.
pub fn hash_text(value: &str) -> String {
    let mut hash: u32 = 2_166_136_261;
    for unit in value.encode_utf16() {
        hash ^= u32::from(unit);
        hash = hash.wrapping_mul(16_777_619);
    }
    to_base36(hash)
}

fn to_base36(mut n: u32) -> String {
    if n == 0 {
        return "0".into();
    }
    let mut digits = Vec::new();
    while n > 0 {
        digits.push(char::from_digit(n % 36, 36).expect("digit below 36"));
        n /= 36;
    }
    digits.iter().rev().collect()
}

/// Byte offsets of `\n\n` outside ``` fences.
fn safe_paragraph_ends(markdown: &str) -> Vec<usize> {
    let bytes = markdown.as_bytes();
    let mut ends = Vec::new();
    let (mut in_fence, mut index) = (false, 0);
    while index < bytes.len() {
        if bytes[index..].starts_with(b"```") {
            in_fence = !in_fence;
            index += 3;
        } else if !in_fence && bytes[index..].starts_with(b"\n\n") {
            ends.push(index);
            index += 2;
        } else {
            index += 1;
        }
    }
    ends
}

fn balanced_inline_syntax(markdown: &str) -> bool {
    let (mut square, mut round, mut escaped) = (0usize, 0usize, false);
    for c in markdown.chars() {
        if escaped {
            escaped = false;
        } else if c == '\\' {
            escaped = true;
        } else if c == '[' {
            square += 1;
        } else if c == ']' {
            square = square.saturating_sub(1);
        } else if c == '(' && square == 0 {
            round += 1;
        } else if c == ')' && square == 0 {
            round = round.saturating_sub(1);
        }
    }
    square == 0 && round == 0
}

/// `^\s*\[!\]\(embed:[^)]+\)\s*$`.
fn standalone_large_preview(markdown: &str) -> bool {
    let t = trim(markdown);
    match t.strip_prefix("[!](embed:").and_then(|r| r.strip_suffix(')')) {
        Some(inner) => !inner.is_empty() && !inner.contains(')'),
        None => false,
    }
}

/// `^>\s*\[[^\]]+\]\(embed:[^)]+\)\s*$` on trimmed text.
fn complete_source_quote(trimmed: &str) -> bool {
    let Some(rest) = trimmed.strip_prefix('>') else { return false };
    let Some(rest) = trim_start(rest).strip_prefix('[') else { return false };
    let Some(close) = rest.find(']') else { return false };
    if close == 0 {
        return false;
    }
    match rest[close + 1..].strip_prefix("(embed:").and_then(|r| r.strip_suffix(')')) {
        Some(inner) => !inner.is_empty() && !inner.contains(')'),
        None => false,
    }
}

/// `^\s*(?:[-*+] |\d+\. )`.
fn list_line(line: &str) -> bool {
    let t = trim_start(line);
    let b = t.as_bytes();
    if b.len() >= 2 && matches!(b[0], b'-' | b'*' | b'+') && b[1] == b' ' {
        return true;
    }
    let digits = b.iter().take_while(|c| c.is_ascii_digit()).count();
    digits > 0 && b[digits..].starts_with(b". ")
}

/// `^\s*\|?.*\|.*\|?\s*$` (`.` excludes line terminators other than `\n`).
fn table_row_line(line: &str) -> bool {
    let core = trim(line);
    core.contains('|') && !core.contains(['\r', '\u{2028}', '\u{2029}'])
}

/// `^\s*\|?\s*:?-{3,}`.
fn table_separator_line(line: &str) -> bool {
    let t = trim_start(line);
    let t = trim_start(t.strip_prefix('|').unwrap_or(t));
    let t = t.strip_prefix(':').unwrap_or(t);
    t.bytes().take_while(|c| *c == b'-').count() >= 3
}

fn fence_count(s: &str) -> usize {
    s.matches("```").count()
}

fn safe_completed_block(markdown: &str, remaining: &str) -> bool {
    let trimmed = trim(markdown);
    if trimmed.is_empty() || !balanced_inline_syntax(trimmed) || fence_count(trimmed) % 2 != 0 {
        return false;
    }
    let lines: Vec<&str> = trimmed.split('\n').collect();
    let is_list = lines.iter().any(|l| list_line(l));
    let is_table = lines.iter().any(|l| table_row_line(l)) && lines.iter().any(|l| table_separator_line(l));
    let source_quote = complete_source_quote(trimmed);
    let other_quote = lines.iter().any(|l| trim_start(l).starts_with('>')) && !source_quote;
    if is_list || is_table || other_quote {
        return false;
    }
    if standalone_large_preview(trimmed) {
        let next = remaining.split("\n\n").next().unwrap_or("");
        return !standalone_large_preview(next);
    }
    true
}

fn closed_standalone_fence(markdown: &str) -> bool {
    let t = trim(markdown);
    t.starts_with("```") && fence_count(t) >= 2 && t.ends_with("```")
}

/// Splits markdown into committed blocks and an optional mutable tail.
pub fn partition(markdown: &str, final_phase: bool) -> (Vec<String>, Option<String>) {
    let mut committed = Vec::new();
    let mut start = 0usize;
    for end in safe_paragraph_ends(markdown) {
        if end < start {
            continue;
        }
        let block = trim(&markdown[start..end]);
        let remaining = trim_start(&markdown[end + 2..]);
        if !block.is_empty() && safe_completed_block(block, remaining) {
            committed.push(block.to_string());
            start = end + 2;
        }
    }
    let remainder = trim(&markdown[start..]);
    if remainder.is_empty() {
        return (committed, None);
    }
    if final_phase || closed_standalone_fence(remainder) {
        committed.push(remainder.to_string());
        return (committed, None);
    }
    (committed, Some(remainder.to_string()))
}

struct Block {
    id: String,
    markdown: String,
    reuse: Option<usize>,
}

struct Previous {
    final_phase: bool,
    committed: Vec<(String, String)>,
    tail: Option<(String, String)>,
}

fn str_field<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value.get(key).and_then(Value::as_str).ok_or_else(|| PROTOCOL.to_string())
}

fn block_pair(value: &Value) -> Result<(String, String), String> {
    Ok((str_field(value, "id")?.to_string(), str_field(value, "markdown")?.to_string()))
}

fn parse_previous(text: &str) -> Result<Option<Previous>, String> {
    let value: Value = serde_json::from_str(text).map_err(|_| PROTOCOL.to_string())?;
    if value.is_null() {
        return Ok(None);
    }
    let committed = value.get("committed").and_then(Value::as_array).ok_or_else(|| PROTOCOL.to_string())?;
    let tail = match value.get("tail") {
        None | Some(Value::Null) => None,
        Some(t) => Some(block_pair(t)?),
    };
    Ok(Some(Previous {
        final_phase: str_field(&value, "phase")? == "final",
        committed: committed.iter().map(block_pair).collect::<Result<_, _>>()?,
        tail,
    }))
}

fn convergence_failure() -> Vec<Value> {
    vec![json!({"kind": "convergence-failure", "reason": "non-local-divergence"})]
}

fn derive_operations(blocks: &mut [Block], tail: &Option<String>, prev: &Previous) -> Vec<Value> {
    let mut ops = Vec::new();
    let (pb, nb) = (&prev.committed, blocks.len());
    let shared = pb.len().min(nb);
    for index in 0..shared {
        if pb[index].1 != blocks[index].markdown {
            blocks[index].id = pb[index].0.clone();
            ops.push(json!({"kind": "replace-block", "index": index, "blockId": pb[index].0}));
        }
    }
    if pb.len() == nb + 1 {
        let next: Vec<&str> = blocks.iter().map(|b| b.markdown.as_str()).collect();
        let removed = (0..pb.len()).find(|candidate| {
            let remaining = pb.iter().enumerate().filter(|(i, _)| i != candidate).map(|(_, b)| b.1.as_str());
            remaining.eq(next.iter().copied())
        });
        let Some(removed) = removed else { return convergence_failure() };
        ops.push(json!({"kind": "delete-block", "index": removed, "blockId": pb[removed].0}));
    } else if pb.len() > nb {
        return convergence_failure();
    }
    let mut committed_tail = false;
    if nb > pb.len() {
        let first = pb.len();
        let commits = prev.tail.as_ref().is_some_and(|t| t.1 == blocks[first].markdown);
        if commits {
            committed_tail = true;
            blocks[first].id = prev.tail.as_ref().map(|t| t.0.clone()).unwrap_or_default();
            ops.push(json!({"kind": "commit-tail"}));
            if nb - first > 1 {
                let ids: Vec<&str> = blocks[first + 1..].iter().map(|b| b.id.as_str()).collect();
                ops.push(json!({"kind": "append-blocks", "blockIds": ids}));
            }
        } else {
            let ids: Vec<&str> = blocks[first..].iter().map(|b| b.id.as_str()).collect();
            ops.push(json!({"kind": "append-blocks", "blockIds": ids}));
        }
    }
    if !committed_tail && tail.as_deref() != prev.tail.as_ref().map(|t| t.1.as_str()) {
        ops.push(json!({"kind": "replace-tail"}));
    }
    ops
}

/// Plans the blocks of one assistant message.
///
/// `previous_json` is `null` or `{phase, committed:[{id,markdown}], tail:{id,markdown}|null}`.
/// Returns `{committed:[{id,markdown,reuse}], tail:string|null, operations, failed}`
/// where `reuse` is the previous committed index whose compiled document the page
/// reuses (`null` means compile), and `failed` marks a convergence failure (the
/// page then keeps the previous plan and appends the failure notice).
///
/// # Errors
/// `protocol` for an unknown phase or malformed `previous_json`.
pub fn plan_blocks_json(markdown: &str, phase: &str, previous_json: &str) -> Result<String, String> {
    let final_phase = match phase {
        "final" => true,
        "streaming" => false,
        _ => return Err(PROTOCOL.to_string()),
    };
    // A streaming restart after a final plan must not diff against the final blocks.
    let previous = parse_previous(previous_json)?.filter(|p| !(p.final_phase && !final_phase));
    let (committed_md, tail) = partition(markdown, final_phase);

    let mut by_key: HashMap<(&str, usize), usize> = HashMap::new();
    let mut prev_occurrences: HashMap<&str, usize> = HashMap::new();
    for (index, (_, md)) in previous.iter().flat_map(|p| p.committed.iter()).enumerate() {
        let occurrence = prev_occurrences.entry(md.as_str()).or_insert(0);
        by_key.insert((md.as_str(), *occurrence), index);
        *occurrence += 1;
    }
    let mut occurrences: HashMap<&str, usize> = HashMap::new();
    let mut blocks: Vec<Block> = committed_md
        .iter()
        .map(|md| {
            let occurrence = *occurrences.entry(md.as_str()).and_modify(|n| *n += 1).or_insert(0);
            let found = by_key.get(&(md.as_str(), occurrence)).copied();
            let id = match (&previous, found) {
                (Some(p), Some(i)) => p.committed[i].0.clone(),
                _ => format!("assistant-block:{}:{}", hash_text(md), occurrence),
            };
            Block { id, markdown: md.clone(), reuse: found }
        })
        .collect();
    if let Some(p) = &previous {
        for (index, block) in blocks.iter_mut().enumerate().take(p.committed.len()) {
            if block.markdown == p.committed[index].1 {
                block.id = p.committed[index].0.clone();
                block.reuse = Some(index);
            }
        }
    }
    let operations = match &previous {
        Some(p) => derive_operations(&mut blocks, &tail, p),
        None => Vec::new(),
    };
    let failed = previous.is_some() && operations.first().is_some_and(|op| op["kind"] == "convergence-failure");
    let committed: Vec<Value> = blocks
        .iter()
        .map(|b| json!({"id": b.id, "markdown": b.markdown, "reuse": b.reuse}))
        .collect();
    serde_json::to_string(&json!({"committed": committed, "tail": tail, "operations": operations, "failed": failed}))
        .map_err(|_| PROTOCOL.to_string())
}

fn collect_node_types(node: &Value, out: &mut Vec<String>) {
    if let Some(kind) = node.get("type").and_then(Value::as_str) {
        out.push(kind.to_string());
    }
    for child in node.get("content").and_then(Value::as_array).into_iter().flatten() {
        collect_node_types(child, out);
    }
}

fn collect_app_skill_ids(node: &Value, out: &mut Vec<String>) {
    if let (Some("embed"), Some(attrs)) = (node.get("type").and_then(Value::as_str), node.get("attrs")) {
        match attrs.get("type").and_then(Value::as_str) {
            Some("app-skill-use") => out.extend(attrs.get("id").and_then(Value::as_str).map(str::to_string)),
            Some("app-skill-use-group") => {
                for item in attrs.get("groupedItems").and_then(Value::as_array).into_iter().flatten() {
                    out.extend(item.get("id").and_then(Value::as_str).map(str::to_string));
                }
            }
            _ => {}
        }
    }
    for child in node.get("content").and_then(Value::as_array).into_iter().flatten() {
        collect_app_skill_ids(child, out);
    }
}

/// Semantic summary of a compiled plan (`normalizeAssistantRenderPlan`).
///
/// `plan_json` is `{document, committed:[{markdown,document}], tail:{markdown,document}|null}`.
///
/// # Errors
/// `protocol` for malformed input.
pub fn normalize_json(plan_json: &str) -> Result<String, String> {
    let plan: Value = serde_json::from_str(plan_json).map_err(|_| PROTOCOL.to_string())?;
    let document = plan.get("document").ok_or_else(|| PROTOCOL.to_string())?;
    let mut app_skill_ids = Vec::new();
    collect_app_skill_ids(document, &mut app_skill_ids);
    let committed = plan.get("committed").and_then(Value::as_array).ok_or_else(|| PROTOCOL.to_string())?;
    let tail = plan.get("tail").filter(|t| !t.is_null());
    let mut blocks = Vec::new();
    for block in committed.iter().chain(tail) {
        let mut node_types = Vec::new();
        collect_node_types(block.get("document").ok_or_else(|| PROTOCOL.to_string())?, &mut node_types);
        let mut entry = Map::new();
        entry.insert("id".into(), Value::String(format!("semantic:{}", hash_text(str_field(block, "markdown")?))));
        entry.insert("nodeTypes".into(), json!(node_types));
        blocks.push(Value::Object(entry));
    }
    serde_json::to_string(&json!({"appSkillIds": app_skill_ids, "blocks": blocks})).map_err(|_| PROTOCOL.to_string())
}
