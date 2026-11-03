//! Owner-side historical assistant speech (`chats speak`). Decrypted assistant
//! markdown is projected locally into bounded transient paragraph text, sent
//! only on the first-party speech WebSocket contract, and summarized without
//! content, keys, provider IDs or storage paths.
use super::*;
use regex::{Captures, Regex};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

const MAX_SPEECH_SEGMENTS: usize = 20;
const MAX_SEGMENT_UNITS: usize = 2_000;
const MESSAGE_TIMEOUT: Duration = Duration::from_secs(10 * 60);

/// One projected speech segment. `kind` is `prose_paragraph`, `code_summary`,
/// `table_summary` or `embed_summary`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectedSpeechSegment {
    pub sequence: usize,
    pub kind: &'static str,
    pub speakable_text: String,
}

/// Exactly one of `message_id` (full ID or prefix) or `all`.
#[derive(Clone, Debug, Default)]
pub struct SpeechSelection {
    pub message_id: Option<String>,
    pub all: bool,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SpeechMessageResult {
    pub generated: u64,
    pub reused: u64,
    pub failed: u64,
    pub charged: u64,
}

/// Preserved CLI summary JSON.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct AssistantSpeechSummary {
    pub chat_id: String,
    pub messages: u64,
    pub generated_segments: u64,
    pub reused_segments: u64,
    pub failed_segments: u64,
    pub charged_segments: u64,
}

pub fn summarize_assistant_speech(
    chat_id: &str,
    results: &[SpeechMessageResult],
) -> AssistantSpeechSummary {
    let sum = |field: fn(&SpeechMessageResult) -> u64| results.iter().map(field).sum::<u64>();
    AssistantSpeechSummary {
        chat_id: chat_id.to_owned(),
        messages: results.len() as u64,
        generated_segments: sum(|r| r.generated),
        reused_segments: sum(|r| r.reused),
        failed_segments: sum(|r| r.failed),
        charged_segments: sum(|r| r.charged),
    }
}

impl Client {
    /// Bounded selected-chat read, then one dedicated socket for the selected
    /// assistant messages. No account sync, cache write or audio download.
    pub async fn generate_existing_assistant_speech(
        &mut self,
        chat_id: &str,
        selection: &SpeechSelection,
    ) -> Result<AssistantSpeechSummary> {
        let chat = self.open_chat(chat_id).await?;
        let selected: Vec<(String, Vec<Value>)> =
            select_assistant_messages(&chat.messages, selection)?
                .into_iter()
                .map(|message| {
                    (
                        message.id.clone(),
                        speech_request_segments(&message.content),
                    )
                })
                .collect();
        if selected.is_empty() {
            return Err(Error::Invalid(
                "This chat has no eligible assistant messages.",
            ));
        }
        let cancel = self.operation_cancel.clone();
        let team = self.team()?.map(str::to_owned);
        let mut ws = self.socket_with_task_jobs(false).await?;
        let result = async {
            let mut active = json!({"chat_id": chat.id});
            if let Some(team) = &team {
                active["team_id"] = json!(team);
            }
            transport::send(&mut ws, "set_active_chat", active).await?;
            let mut results = vec![];
            for (message_id, segments) in selected {
                transport::send(
                    &mut ws,
                    "assistant_speech",
                    json!({"action":"request","chat_id":chat.id,"assistant_message_id":message_id,"segments":segments}),
                )
                .await?;
                let mut tracker = SpeechStatusTracker::new(&message_id);
                let outcome = crate::platform::time::timeout(MESSAGE_TIMEOUT, async {
                    loop {
                        let (event, payload) = transport::receive(&mut ws).await?;
                        if cancel.is_cancelled() {
                            return Err(Error::Cancelled);
                        }
                        if event == "assistant_speech_status"
                            && let Some(result) = tracker.consume(&payload)?
                        {
                            return Ok(result);
                        }
                    }
                })
                .await
                .map_err(|_| Error::Invalid("Timed out waiting for assistant speech generation."))??;
                results.push(outcome);
            }
            Ok(summarize_assistant_speech(&chat.id, &results))
        }
        .await;
        let _ = crate::platform::time::timeout(Duration::from_millis(100), ws.close(None)).await;
        result
    }
}

/// Selects assistant messages per the preserved CLI rules.
pub fn select_assistant_messages<'a>(
    messages: &'a [Message],
    selection: &SpeechSelection,
) -> Result<Vec<&'a Message>> {
    let wanted = selection.message_id.as_deref().filter(|id| !id.is_empty());
    if wanted.is_some() == selection.all {
        return Err(Error::Invalid(
            "Select exactly one of --message <id> or --all.",
        ));
    }
    let Some(wanted) = wanted else {
        return Ok(messages
            .iter()
            .filter(|m| {
                m.role == "assistant" && !project_assistant_speech(&m.content, "en").is_empty()
            })
            .collect());
    };
    match messages
        .iter()
        .find(|m| m.id == wanted || m.id.starts_with(wanted))
    {
        Some(message) if message.role == "assistant" => Ok(vec![message]),
        _ => Err(Error::Invalid(
            "The selected message is not an eligible assistant message.",
        )),
    }
}

/// Request segments: projection plus SHA-256 hex of each speakable text.
pub fn speech_request_segments(content: &str) -> Vec<Value> {
    project_assistant_speech(content, "en")
        .into_iter()
        .map(|s| {
            json!({"source_version":1,"sequence":s.sequence,"kind":s.kind,
                "source_hash":sha256(&s.speakable_text),"speakable_text":s.speakable_text})
        })
        .collect()
}

fn server_error(code: Option<&str>) -> Error {
    Error::Invalid(match code.unwrap_or("") {
        "assistant_message_required" => "assistant_message_required",
        "authentication_required" => "authentication_required",
        "canonical_segment_required" => "canonical_segment_required",
        "forbidden" => "forbidden",
        "insufficient_budget" => "insufficient_budget",
        "invalid_action" => "invalid_action",
        "invalid_segments" => "invalid_segments",
        "rate_limited" => "rate_limited",
        "segment_text_too_long" => "segment_text_too_long",
        "speech_source_no_longer_current" => "speech_source_no_longer_current",
        "too_many_segments" => "too_many_segments",
        _ => "Assistant speech request failed.",
    })
}

fn id_string(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => String::new(),
    }
}

/// Per-message status state machine over `assistant_speech_status` payloads.
pub struct SpeechStatusTracker {
    message_id: String,
    expected: HashSet<String>,
    queued: HashSet<String>,
    terminal: HashMap<String, bool>,
    accepted: bool,
}
impl SpeechStatusTracker {
    pub fn new(message_id: &str) -> Self {
        Self {
            message_id: message_id.to_owned(),
            expected: HashSet::new(),
            queued: HashSet::new(),
            terminal: HashMap::new(),
            accepted: false,
        }
    }
    fn record(&mut self, status: &Value) {
        let segment = id_string(&status["segment_id"]);
        if segment.is_empty() || (!self.expected.is_empty() && !self.expected.contains(&segment)) {
            return;
        }
        match status["status"].as_str() {
            Some("queued" | "generating") => {
                self.queued.insert(segment);
            }
            Some(state @ ("ready" | "error")) => {
                self.terminal.insert(segment, state == "ready");
            }
            _ => {}
        }
    }
    /// `Ok(Some)` once every accepted segment is terminal.
    pub fn consume(&mut self, payload: &Value) -> Result<Option<SpeechMessageResult>> {
        if let Some(segments) = payload["segments"].as_array() {
            self.accepted = true;
            for status in segments {
                let segment = id_string(&status["segment_id"]);
                if !segment.is_empty() {
                    self.expected.insert(segment);
                }
                self.record(status);
            }
            if self.expected.is_empty() {
                return Err(Error::Invalid(
                    "No canonical speech segments are available for this historical message.",
                ));
            }
        } else if payload["status"] == "error" {
            return Err(server_error(payload["error"].as_str()));
        } else if id_string(&payload["message_id"]) == self.message_id
            || self.expected.contains(&id_string(&payload["segment_id"]))
        {
            self.record(payload);
        }
        if !self.accepted || self.expected.is_empty() || self.terminal.len() != self.expected.len()
        {
            return Ok(None);
        }
        let mut result = SpeechMessageResult::default();
        for (segment, ready) in &self.terminal {
            match (*ready, self.queued.contains(segment)) {
                (true, true) => {
                    result.generated += 1;
                    result.charged += 1;
                }
                (true, false) => result.reused += 1,
                (false, _) => result.failed += 1,
            }
        }
        Ok(Some(result))
    }
}

fn regex(pattern: &str) -> Regex {
    Regex::new(pattern).expect("static speech projection regex")
}
static FENCE_SPLIT: LazyLock<Regex> = LazyLock::new(|| regex(r"(?s)```.*?```"));
static FENCED_BLOCK: LazyLock<Regex> = LazyLock::new(|| regex(r"(?s)\A```.*```\z"));
static PARAGRAPH_BREAK: LazyLock<Regex> = LazyLock::new(|| regex(r"\n\n+"));
static FENCE_OPEN: LazyLock<Regex> = LazyLock::new(|| regex(r"\A```[^\n]*\n"));
static FENCE_CLOSE: LazyLock<Regex> = LazyLock::new(|| regex(r"\n?```\z"));
static TABLE_LINE: LazyLock<Regex> = LazyLock::new(|| regex(r"\A\s*\|.*\|\s*\z"));
static TABLE_LINES: LazyLock<Regex> = LazyLock::new(|| regex(r"(?m)^\s*\|.*\|\s*$"));
static LEADING_LINK: LazyLock<Regex> = LazyLock::new(|| regex(r"\A\[[^\]]+\]\([^)]*\)"));
static LINK: LazyLock<Regex> = LazyLock::new(|| regex(r"\[([^\]]+)\]\([^)]*\)"));
static INLINE_CODE: LazyLock<Regex> = LazyLock::new(|| regex(r"`[^`]*`"));
static URL: LazyLock<Regex> =
    LazyLock::new(|| regex(r"(?i)(?:https?|ftp)://[^\s)\]>]+|[a-z][a-z0-9+.-]*://[^\s)\]>]+"));
static MARKUP: LazyLock<Regex> = LazyLock::new(|| regex(r"(?:\A|\s)[#>*_~]+|[_~]{1,3}"));
static SPACES: LazyLock<Regex> = LazyLock::new(|| regex(r"\s+"));
static SPACE_BEFORE_PUNCT: LazyLock<Regex> = LazyLock::new(|| regex(r"\s+([,.;:!?])"));
static EDGES: LazyLock<Regex> = LazyLock::new(|| regex(r"\A[\s,;:-]+|[\s,;:-]+\z"));
static SENTENCE_END: LazyLock<Regex> =
    LazyLock::new(|| regex(r#"[.!?。！？]["'”’)\]]*(?:\s+|\z)"#));

fn localized(text: &'static str, language: &str) -> &'static str {
    if !language.to_lowercase().starts_with("de") {
        return text;
    }
    match text {
        "Search results are available." => "Suchergebnisse sind verfügbar.",
        "I used the News Search skill." => "Ich habe die News-Suche verwendet.",
        "App results are available." => "App-Ergebnisse sind verfügbar.",
        "Structured data is available." => "Strukturierte Daten sind verfügbar.",
        "A code example is available." => "Ein Codebeispiel ist verfügbar.",
        "A table is available." => "Eine Tabelle ist verfügbar.",
        other => other,
    }
}

fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Value::String(s) => !s.is_empty(),
        _ => true,
    }
}

fn js_string(value: &Value) -> String {
    match value {
        Value::Null => "null".into(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

fn project_fence(markdown: &str, language: &str) -> (&'static str, &'static str) {
    let opened = FENCE_OPEN.replace(markdown, "");
    let body = FENCE_CLOSE.replace(&opened, "");
    let payload = match serde_json::from_str::<Value>(body.trim()) {
        Ok(Value::Object(map)) => Some(map),
        _ => None,
    };
    if let Some(payload) = &payload {
        let kind = payload.get("type").unwrap_or(&Value::Null);
        if kind == "app_skill_use" {
            let text = if payload.get("skill_id").is_some_and(|v| v == "search") {
                if payload.get("app_id").is_some_and(|v| v == "news") {
                    "I used the News Search skill."
                } else {
                    "Search results are available."
                }
            } else {
                "App results are available."
            };
            return ("embed_summary", localized(text, language));
        }
        let kind = if payload.contains_key("type") {
            js_string(kind)
        } else {
            "undefined".into()
        };
        if payload.get("embed_id").is_some_and(truthy)
            || ["website", "image", "audio", "video"].contains(&kind.as_str())
        {
            return (
                "embed_summary",
                localized("Structured data is available.", language),
            );
        }
    }
    (
        "code_summary",
        localized("A code example is available.", language),
    )
}

fn project_paragraph(markdown: &str, language: &str) -> (&'static str, String) {
    let trimmed = markdown.trim();
    if FENCED_BLOCK.is_match(trimmed) {
        let (kind, text) = project_fence(trimmed, language);
        return (kind, text.into());
    }
    let lines: Vec<&str> = trimmed
        .split('\n')
        .filter(|line| !line.trim().is_empty())
        .collect();
    if lines.len() >= 2 && lines.iter().all(|line| TABLE_LINE.is_match(line)) {
        return (
            "table_summary",
            localized("A table is available.", language).into(),
        );
    }
    if trimmed.starts_with('{') || (trimmed.starts_with('[') && !LEADING_LINK.is_match(trimmed)) {
        return (
            "embed_summary",
            localized("Structured data is available.", language).into(),
        );
    }
    let table = format!(" {} ", localized("A table is available.", language));
    let text = FENCE_SPLIT.replace_all(trimmed, |c: &Captures| {
        format!(" {} ", project_fence(&c[0], language).1)
    });
    let text = TABLE_LINES.replace_all(&text, table.as_str());
    let text = LINK.replace_all(&text, "${1}");
    let text = INLINE_CODE.replace_all(&text, "");
    let text = URL.replace_all(&text, "");
    let text = MARKUP.replace_all(&text, " ");
    let text = SPACES.replace_all(&text, " ");
    let text = SPACE_BEFORE_PUNCT.replace_all(&text, "${1}");
    let text = EDGES.replace_all(&text, "");
    ("prose_paragraph", text.into_owned())
}

/// Byte offset of the first character starting at or after UTF-16 offset `units`.
fn byte_at_units(text: &str, units: usize) -> usize {
    let mut seen = 0;
    for (index, ch) in text.char_indices() {
        if seen >= units {
            return index;
        }
        seen += ch.len_utf16();
    }
    text.len()
}

fn units(text: &str) -> usize {
    text.encode_utf16().count()
}

fn split_long_paragraph(paragraph: &str) -> Vec<String> {
    let mut chunks = vec![];
    let mut remainder = paragraph.to_owned();
    while units(&remainder) > MAX_SEGMENT_UNITS {
        let window = &remainder[..byte_at_units(&remainder, MAX_SEGMENT_UNITS + 1)];
        let mut boundary = SENTENCE_END
            .find_iter(window)
            .last()
            .map(|m| m.start() + m.as_str().trim_end().len())
            .unwrap_or(0);
        if boundary == 0 || units(&remainder[..boundary]) > MAX_SEGMENT_UNITS {
            let limit = byte_at_units(&remainder, MAX_SEGMENT_UNITS);
            boundary = if remainder[limit..].starts_with(' ') {
                limit
            } else {
                remainder[..limit].rfind(' ').unwrap_or(0)
            };
        }
        if boundary == 0 {
            boundary = byte_at_units(&remainder, MAX_SEGMENT_UNITS);
        }
        chunks.push(remainder[..boundary].trim().to_owned());
        remainder = remainder[boundary..].trim_start().to_owned();
    }
    if !remainder.is_empty() {
        chunks.push(remainder);
    }
    chunks
}

/// Bounded speakable projection shared with the web assistant speech flow.
pub fn project_assistant_speech(content: &str, language: &str) -> Vec<ProjectedSpeechSegment> {
    let mut blocks = Vec::<&str>::new();
    let mut last = 0;
    for fence in FENCE_SPLIT.find_iter(content) {
        blocks.push(&content[last..fence.start()]);
        blocks.push(fence.as_str());
        last = fence.end();
    }
    blocks.push(&content[last..]);
    let paragraphs: Vec<&str> = blocks
        .into_iter()
        .flat_map(|block| {
            if FENCED_BLOCK.is_match(block.trim()) {
                vec![block]
            } else {
                PARAGRAPH_BREAK.split(block).collect()
            }
        })
        .map(str::trim)
        .filter(|block| !block.is_empty())
        .collect();
    let mut segments = Vec::<ProjectedSpeechSegment>::new();
    let mut summaries = HashSet::<String>::new();
    for paragraph in paragraphs {
        let (kind, text) = project_paragraph(paragraph, language);
        for speakable_text in split_long_paragraph(&text) {
            if kind == "embed_summary" && !summaries.insert(format!("{kind}:{speakable_text}")) {
                continue;
            }
            if segments.len() == MAX_SPEECH_SEGMENTS {
                return segments;
            }
            segments.push(ProjectedSpeechSegment {
                sequence: segments.len(),
                kind,
                speakable_text,
            });
        }
    }
    segments
}

#[cfg(test)]
#[path = "assistant_speech_tests.rs"]
mod tests;
