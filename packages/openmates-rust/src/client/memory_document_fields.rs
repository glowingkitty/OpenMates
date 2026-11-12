//! Typed fields of one personal Memory document: read, write, save stamps and
//! expiry, without a YAML library (the Apple framework builds without
//! `workflow-yaml`). Mirrors `frontend/packages/ui/src/utils/ruleDocuments.ts`
//! (`parseRuleDocument`, `serializeRuleDocument`, `stampMemorySave`,
//! `isMemoryExpired`) and the expiry sweep of `ruleDocumentService.ts`.
//! Spec: `features.app-memories`.
use super::memory_documents::{
    MemoryDocumentError, MemoryResult, PersonalMemoryDocument, validate_memory_document,
};
use super::memory_frontmatter::{
    Scalar, entries, leading_spaces, non_string, scalar, split, strip_comment, yaml_quoted,
};
use super::*;
use crate::chat_state::js::{js_trim, utf16_len};
use std::fmt;
use zeroize::{Zeroize, ZeroizeOnDrop, Zeroizing};

const MAX_TITLE: usize = 180;
const MAX_TEXT: usize = 1200;
const MAX_APP_ID: usize = 64;
const MAX_REFERENCES: usize = 50;
const MAX_REFERENCE_ID: usize = 240;
/// `Number.MAX_SAFE_INTEGER`: the web parser accepts only safe integers.
const MAX_SAFE_INTEGER: u64 = (1 << 53) - 1;
const KEYS: [&str; 10] = [
    "title",
    "description",
    "when_to_use",
    "load_mode",
    "valid_from",
    "valid_until",
    "references",
    "created_at",
    "updated_at",
    "app_id",
];

/// When the assistant loads a Memory (`load_mode`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MemoryLoadMode {
    /// `auto_include`: loaded whenever it applies.
    AutoInclude,
    /// `ask_first`: the user is asked before it is loaded.
    AskFirst,
    /// `mention_only`: only when the user mentions it.
    MentionOnly,
}

impl MemoryLoadMode {
    /// The stored literal.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AutoInclude => "auto_include",
            Self::AskFirst => "ask_first",
            Self::MentionOnly => "mention_only",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "auto_include" => Some(Self::AutoInclude),
            "ask_first" => Some(Self::AskFirst),
            "mention_only" => Some(Self::MentionOnly),
            _ => None,
        }
    }
}

/// `RuleDocumentFields`: what a Memory page shows and edits. Private text,
/// wiped on drop and never printed.
#[derive(Clone, Default, PartialEq, Eq, Zeroize, ZeroizeOnDrop)]
pub struct MemoryDocumentFields {
    /// Title (trimmed, at most 180 UTF-16 units).
    pub title: String,
    /// Legacy summary; new documents leave it `None`.
    pub description: Option<String>,
    /// When the assistant should use it; empty means always considered.
    pub when_to_use: String,
    /// Markdown body (trimmed, at most 20,000 characters).
    pub body: String,
    /// Load mode; `None` when the document names none.
    #[zeroize(skip)]
    pub load_mode: Option<MemoryLoadMode>,
    /// Start of the validity window (ISO 8601 as stored).
    pub valid_from: Option<String>,
    /// Expiry (ISO 8601 as stored); the Memory is deleted once it passed.
    pub valid_until: Option<String>,
    /// Embed ids referenced by the body (`references: [{kind: embed, id}]`);
    /// legacy chat references are dropped on read, like the web parser.
    pub references: Vec<String>,
    /// Unix seconds of the first save.
    pub created_at: Option<u64>,
    /// Unix seconds of the latest save.
    pub updated_at: Option<u64>,
    /// Optional app the Memory belongs to (icon and colour only).
    pub app_id: Option<String>,
}

impl fmt::Debug for MemoryDocumentFields {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Never print private Memory text.
        f.debug_struct("MemoryDocumentFields")
            .field("load_mode", &self.load_mode)
            .field("created_at", &self.created_at)
            .field("updated_at", &self.updated_at)
            .finish_non_exhaustive()
    }
}

fn invalid<T>() -> MemoryResult<T> {
    Err(MemoryDocumentError::InvalidDocument)
}

fn string(value: Scalar) -> MemoryResult<String> {
    match &value {
        Scalar::Quoted(text) => Ok(text.clone()),
        Scalar::Plain(text) if !non_string(text) => Ok(text.clone()),
        Scalar::Plain(_) => invalid(),
    }
}

/// The web `text()` rule: a non-blank string of at most `max` UTF-16 units once trimmed.
fn text(value: Scalar, max: usize) -> MemoryResult<String> {
    let value = Zeroizing::new(string(value)?);
    let trimmed = js_trim(&value);
    if trimmed.is_empty() || utf16_len(trimmed) > max {
        return invalid();
    }
    Ok(trimmed.to_owned())
}

fn seconds(value: Scalar) -> MemoryResult<u64> {
    let parsed = match &value {
        Scalar::Plain(text) => {
            let digits = text.strip_prefix('+').unwrap_or(text);
            if let Some(hex) = digits.strip_prefix("0x") {
                u64::from_str_radix(hex, 16).ok()
            } else if let Some(octal) = digits.strip_prefix("0o") {
                u64::from_str_radix(octal, 8).ok()
            } else if digits.bytes().all(|b| b.is_ascii_digit()) {
                digits.parse::<u64>().ok()
            } else {
                // Negative times are refused (the web accepts only `-0`).
                None
            }
        }
        Scalar::Quoted(_) => None,
    };
    parsed
        .filter(|s| *s <= MAX_SAFE_INTEGER)
        .ok_or(MemoryDocumentError::InvalidDocument)
}

fn reference_item(lines: &[String]) -> MemoryResult<Option<String>> {
    let (mut kind, mut id) = (None, None);
    for line in lines {
        let (key, value) = line
            .split_once(':')
            .ok_or(MemoryDocumentError::InvalidDocument)?;
        let value = string(scalar(value, &[])?)?;
        let slot = match key.trim() {
            "kind" => &mut kind,
            "id" => &mut id,
            _ => return invalid(),
        };
        if slot.replace(value).is_some() {
            return invalid();
        }
    }
    match (kind.as_deref(), id) {
        // Legacy chat references are dropped on read.
        (Some("chat"), _) => Ok(None),
        (Some("embed"), Some(id))
            if !js_trim(&id).is_empty() && utf16_len(&id) <= MAX_REFERENCE_ID =>
        {
            Ok(Some(id))
        }
        _ => invalid(),
    }
}

/// `references:` as a block sequence of `{kind, id}` mappings (or `[]`).
fn references(first: &str, rest: &[&str]) -> MemoryResult<Vec<String>> {
    let first = strip_comment(first).trim();
    if first == "[]" && rest.iter().all(|l| l.trim().is_empty()) {
        return Ok(Vec::new());
    }
    if !first.is_empty() {
        return invalid();
    }
    let mut items: Vec<Vec<String>> = Vec::new();
    let mut dash = None;
    for line in rest.iter().filter(|l| !l.trim().is_empty()) {
        let indent = leading_spaces(line);
        let body = &line[indent..];
        let starts = body == "-" || body.starts_with("- ");
        match dash {
            None if starts => dash = Some(indent),
            None => return invalid(),
            Some(_) => {}
        }
        let column = dash.unwrap_or(indent);
        if starts && indent == column {
            items.push(Vec::new());
            let inner = body[1..].trim();
            if let (false, Some(item)) = (inner.is_empty(), items.last_mut()) {
                item.push(inner.to_owned());
            }
        } else if indent > column {
            let item = items
                .last_mut()
                .ok_or(MemoryDocumentError::InvalidDocument)?;
            item.push(body.to_owned());
        } else {
            return invalid();
        }
    }
    if items.len() > MAX_REFERENCES {
        return invalid();
    }
    let mut ids: Vec<String> = Vec::new();
    for item in &items {
        if let Some(id) = reference_item(item)? {
            if ids.contains(&id) {
                return invalid();
            }
            ids.push(id);
        }
    }
    Ok(ids)
}

/// `Date.parse` of the ISO 8601 forms the web and server write (date only,
/// or date and time with optional fraction and `Z`/offset), as unix
/// milliseconds. A date-time without an offset is read as UTC (the browser
/// reads it as local time); other `Date.parse` formats are refused.
pub fn iso_millis(value: &str) -> Option<i64> {
    static ISO: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    let iso = ISO.get_or_init(|| {
        regex::Regex::new(concat!(
            r"\A([+-][0-9]{6}|[0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?",
            r"(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?(Z|[+-][0-9]{2}:[0-9]{2})?)?\z"
        ))
        .expect("static ISO 8601 expression")
    });
    let found = iso.captures(value)?;
    let number = |i: usize, default: i64| -> Option<i64> {
        found
            .get(i)
            .map_or(Some(default), |m| m.as_str().parse().ok())
    };
    let (year, month, day) = (number(1, 0)?, number(2, 1)?, number(3, 1)?);
    let (hour, minute, second) = (number(4, 0)?, number(5, 0)?, number(6, 0)?);
    let millis = found.get(7).map_or(Some(0), |m| {
        let digits: String = m.as_str().chars().chain("00".chars()).take(3).collect();
        digits.parse::<i64>().ok()
    })?;
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let days_in = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let valid_day = usize::try_from(month - 1)
        .ok()
        .and_then(|m| days_in.get(m))
        .is_some_and(|max| (1..=*max).contains(&day));
    let midnight_end = hour == 24 && minute == 0 && second == 0 && millis == 0;
    if !valid_day || !(hour < 24 || midnight_end) || minute > 59 || second > 59 {
        return None;
    }
    let offset = match found.get(8).map(|m| m.as_str()) {
        None | Some("Z") => 0,
        Some(text) => {
            let sign = if text.starts_with('-') { -1 } else { 1 };
            let (h, m) = (
                text[1..3].parse::<i64>().ok()?,
                text[4..6].parse::<i64>().ok()?,
            );
            if h > 23 || m > 59 {
                return None;
            }
            sign * (h * 60 + m)
        }
    };
    // Days from the civil date (H. Hinnant's algorithm), proleptic Gregorian.
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    let minutes = (days * 24 + hour) * 60 + minute - offset;
    Some((minutes * 60 + second) * 1000 + millis)
}

fn date(value: Scalar) -> MemoryResult<String> {
    let value = string(value)?;
    if iso_millis(&value).is_none() {
        return invalid();
    }
    Ok(value)
}

/// `parseRuleDocument`: the typed fields of a stored Memory document.
///
/// Reads the YAML subset Memory documents use (plain, quoted and block
/// scalars, the `references` block sequence); flow collections, anchors and
/// tags are refused, as are documents the web parser refuses.
///
/// # Errors
/// [`MemoryDocumentError::InvalidDocument`].
pub fn parse_memory_document(document: &str) -> MemoryResult<MemoryDocumentFields> {
    validate_memory_document(document)?;
    let (header, body) = split(document)?;
    // No struct update syntax: the fields type wipes itself on drop.
    let mut fields = MemoryDocumentFields::default();
    fields.body = js_trim(body).to_owned();
    for entry in entries(header, &KEYS)? {
        let (first, rest) = (entry.first, entry.rest.as_slice());
        match entry.key {
            "title" => fields.title = text(scalar(first, rest)?, MAX_TITLE)?,
            "description" => fields.description = Some(text(scalar(first, rest)?, MAX_TEXT)?),
            "when_to_use" => fields.when_to_use = text(scalar(first, rest)?, MAX_TEXT)?,
            "load_mode" => {
                let mode = string(scalar(first, rest)?)?;
                fields.load_mode =
                    Some(MemoryLoadMode::parse(&mode).ok_or(MemoryDocumentError::InvalidDocument)?);
            }
            "valid_from" => fields.valid_from = Some(date(scalar(first, rest)?)?),
            "valid_until" => fields.valid_until = Some(date(scalar(first, rest)?)?),
            "references" => fields.references = references(first, rest)?,
            "created_at" => fields.created_at = Some(seconds(scalar(first, rest)?)?),
            "updated_at" => fields.updated_at = Some(seconds(scalar(first, rest)?)?),
            "app_id" => {
                let raw = Zeroizing::new(string(scalar(first, rest)?)?);
                let trimmed = js_trim(&raw);
                if trimmed.is_empty() || utf16_len(&raw) > MAX_APP_ID {
                    return invalid();
                }
                fields.app_id = Some(trimmed.to_owned());
            }
            _ => return invalid(),
        }
    }
    if fields.title.is_empty() {
        return invalid();
    }
    if let (Some(from), Some(until)) = (&fields.valid_from, &fields.valid_until)
        && iso_millis(from) > iso_millis(until)
    {
        return invalid();
    }
    Ok(fields)
}

/// `serializeRuleDocument`: the canonical document of `fields`, keys in the
/// web order, strings double-quoted. Equal to the web output as YAML values,
/// not byte for byte (the web emits plain scalars where it can).
///
/// # Errors
/// [`MemoryDocumentError::InvalidDocument`] when the result is not a valid
/// Memory (blank title or body, a field over its limit, a bad date).
pub fn serialize_memory_document(fields: &MemoryDocumentFields) -> MemoryResult<Zeroizing<String>> {
    let mut header = Zeroizing::new(String::new());
    let mut line = |key: &str, value: &str| {
        header.push_str(key);
        header.push_str(": ");
        header.push_str(value);
        header.push('\n');
    };
    line("title", &yaml_quoted(js_trim(&fields.title)));
    if let Some(description) = fields
        .description
        .as_deref()
        .map(js_trim)
        .filter(|d| !d.is_empty())
    {
        line("description", &yaml_quoted(description));
    }
    let when = js_trim(&fields.when_to_use);
    if !when.is_empty() {
        line("when_to_use", &yaml_quoted(when));
    }
    if let Some(mode) = fields.load_mode {
        line("load_mode", mode.as_str());
    }
    if let Some(from) = &fields.valid_from {
        line("valid_from", &yaml_quoted(from));
    }
    if let Some(until) = &fields.valid_until {
        line("valid_until", &yaml_quoted(until));
    }
    if !fields.references.is_empty() {
        let mut list = String::new();
        for id in &fields.references {
            list.push_str(&format!("\n  - kind: embed\n    id: {}", yaml_quoted(id)));
        }
        header.push_str("references:");
        header.push_str(&list);
        header.push('\n');
    }
    let mut line = |key: &str, value: &str| {
        header.push_str(key);
        header.push_str(": ");
        header.push_str(value);
        header.push('\n');
    };
    if let Some(created) = fields.created_at {
        line("created_at", &created.to_string());
    }
    if let Some(updated) = fields.updated_at {
        line("updated_at", &updated.to_string());
    }
    if let Some(app) = fields
        .app_id
        .as_deref()
        .map(js_trim)
        .filter(|a| !a.is_empty())
    {
        line("app_id", &yaml_quoted(app));
    }
    let document = Zeroizing::new(format!(
        "---\n{}---\n{}\n",
        header.as_str(),
        js_trim(&fields.body)
    ));
    parse_memory_document(&document)?;
    Ok(document)
}

/// `stampMemorySave`: `created_at` stays the stored one (or the draft's, or
/// now on the first save); `updated_at` is always now.
pub fn stamp_memory_save(
    fields: &mut MemoryDocumentFields,
    previous: Option<&MemoryDocumentFields>,
    now_s: u64,
) {
    fields.created_at = previous
        .and_then(|p| p.created_at)
        .or(fields.created_at)
        .or(Some(now_s));
    fields.updated_at = Some(now_s);
}

/// `isMemoryExpired`: true as soon as `valid_until` is in the past.
pub fn is_memory_expired(fields: &MemoryDocumentFields, now_ms: i64) -> bool {
    fields
        .valid_until
        .as_deref()
        .and_then(iso_millis)
        .is_some_and(|until| now_ms > until)
}

/// Ids of the expired personal Memories; documents that cannot be read are
/// never treated as expired (nothing unreadable is deleted).
pub fn expired_memory_ids(documents: &[PersonalMemoryDocument], now_ms: i64) -> Vec<String> {
    documents
        .iter()
        .filter(|d| parse_memory_document(&d.document).is_ok_and(|f| is_memory_expired(&f, now_ms)))
        .map(|d| d.id.clone())
        .collect()
}

impl Client {
    /// The web expiry sweep (`deleteExpiredPersonalMemories`): delete every
    /// personal Memory whose `valid_until` passed; returns how many. One
    /// settings round trip per expired Memory (expiry is rare).
    ///
    /// # Errors
    /// The list and delete errors of `memory_documents`; a failure stops the
    /// sweep with the Memories deleted so far kept deleted.
    pub async fn delete_expired_personal_memories(&mut self, now_ms: i64) -> MemoryResult<u32> {
        let documents = self.personal_memory_documents().await?;
        let mut deleted = 0;
        for id in expired_memory_ids(&documents, now_ms) {
            self.delete_personal_memory_document(&id).await?;
            deleted += 1;
        }
        Ok(deleted)
    }
}

#[cfg(test)]
#[path = "memory_document_fields_tests.rs"]
mod tests;
