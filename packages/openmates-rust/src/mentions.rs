//! Chat @mention resolution: display mentions to backend wire syntax.
//!
//! Pure port of `frontend/packages/openmates-cli/src/mentions.ts::parseMentions`
//! (itself mirroring the web `mentionSearchService.ts`). Resolution order per
//! token: model alias, chat model, mate, app skill, focus mode, memory
//! category, memory entry. File paths, `@TASK-*` and Wikipedia tokens pass
//! through unchanged for their own callers; anything else is unresolved and
//! reported with fuzzy suggestions (the message keeps the original text).
//!
//! No network or terminal access happens here; `Client::resolve_mentions`
//! (client/mention_context.rs) supplies the server Apps catalog.
use serde::Serialize;
use serde_json::Value;

/// `@best` / `@fast` aliases (mentions.ts MODEL_ALIASES).
pub const MODEL_ALIASES: &[(&str, &str)] = &[("best", "gpt-6-astra"), ("fast", "mercury-3")];

/// Mate category id → display name (client.ts MATE_NAMES, same order).
pub const MATE_NAMES: &[(&str, &str)] = &[
    ("software_development", "Sophia"),
    ("business_development", "Burton"),
    ("life_coach_psychology", "Lisa"),
    ("medical_health", "Melvin"),
    ("legal_law", "Leon"),
    ("finance", "Finn"),
    ("design", "Denise"),
    ("marketing_sales", "Mark"),
    ("science", "Scarlett"),
    ("history", "Hiro"),
    ("cooking_food", "Colin"),
    ("electrical_engineering", "Elton"),
    ("maker_prototyping", "Makani"),
    ("movies_tv", "Monika"),
    ("activism", "Ace"),
    ("general_knowledge", "George"),
    ("onboarding_support", "Suki"),
];

type ModelRow = (&'static str, &'static str, Option<&'static str>, Option<&'static str>, Option<&'static str>);
/// (id, name, provider, legacy release date, API retirement date): mentions.ts CHAT_MODELS.
const CHAT_MODELS: &[ModelRow] = &[
    ("claude-fable-5-1", "Claude Fable 5.1", None, None, None),
    ("claude-opus-5-5", "Claude Opus 5.5", None, None, None),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", None, None, None),
    ("claude-haiku-5-5", "Claude Haiku 5.5", None, None, None),
    ("claude-fable-5", "Claude Fable 5", None, Some("2026-06-09"), None),
    ("claude-opus-5", "Claude Opus 5", None, Some("2026-07-24"), None),
    ("claude-sonnet-5", "Claude Sonnet 5", None, Some("2026-06-30"), None),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5", None, Some("2025-10-15"), None),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6", None, Some("2026-02-17"), None),
    ("claude-opus-4-6", "Claude Opus 4.6", None, Some("2026-02-05"), None),
    ("claude-opus-4-7", "Claude Opus 4.7", None, Some("2026-04-16"), None),
    ("claude-opus-4-8", "Claude Opus 4.8", None, Some("2026-05-28"), None),
    ("claude-opus-4-5-20251101", "Claude Opus 4.5", None, Some("2025-11-24"), None),
    ("gpt-6-astra", "GPT-6 Astra", None, None, None),
    ("gpt-6.1-sol", "GPT-6.1 Sol", None, None, None),
    ("gpt-6-luna", "GPT-6 Luna", None, None, None),
    ("gpt-5.6-terra", "GPT-5.6 Terra", None, None, None),
    ("gpt-6-sol", "GPT-6 Sol", None, Some("2026-09-22"), None),
    ("gpt-5.6-sol", "GPT-5.6 Sol", None, Some("2026-07-09"), None),
    ("gpt-5.6-luna", "GPT-5.6 Luna", None, Some("2026-07-09"), None),
    ("gpt-5.5", "GPT-5.5", None, Some("2026-04-24"), None),
    ("gpt-5.5-pro", "GPT-5.5 Pro", None, Some("2026-04-24"), None),
    ("gpt-5.4", "GPT-5.4", None, Some("2026-03-05"), None),
    ("gpt-5.4-pro", "GPT-5.4 Pro", None, Some("2026-03-05"), None),
    ("gpt-5.4-mini", "GPT-5.4 Mini", None, Some("2026-03-17"), None),
    ("gpt-5.4-nano", "GPT-5.4 nano", None, Some("2026-03-17"), Some("2027-04-01")),
    ("gpt-5.2", "GPT-5.2", None, Some("2025-12-11"), None),
    ("gpt-5.2-pro", "GPT-5.2 Pro", None, Some("2025-12-11"), None),
    ("gpt-5.1", "GPT-5.1", None, Some("2025-11-13"), Some("2027-04-01")),
    ("gpt-oss-120b", "GPT-OSS-120b", None, None, None),
    ("gemma-4-31b", "Gemma 4 31B", None, None, None),
    ("gemini-3-flash-preview", "Gemini 3 Flash", None, None, None),
    ("gemini-3.8-flash", "Gemini 3.8 Flash", None, None, None),
    ("gemini-3.7-flash", "Gemini 3.7 Flash", None, None, None),
    ("gemini-3-pro-image-preview", "Gemini 3 Pro", None, None, None),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro", None, None, None),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", None, None, None),
    ("deepseek-v4-pro", "DeepSeek V4 Pro", None, None, None),
    ("deepseek-v4-flash", "DeepSeek V4 Flash", None, None, None),
    ("qwen-3.8-27b", "Qwen 3.8 27B", None, None, None),
    ("mercury-3", "Mercury 3", None, None, None),
    ("kimi-k2.5", "Kimi K2.5", None, None, None),
    ("kimi-k2.6", "Kimi K2.6", None, None, None),
    ("kimi-k3", "Kimi K3", None, None, None),
    ("zai-glm-4.7", "GLM 4.7", None, None, None),
    ("mistral-medium-latest", "Mistral Medium 3.5", Some("mistral"), None, None),
    ("mistral-large-4", "Mistral Large 4", Some("mistral"), None, None),
    ("mistral-small-latest", "Mistral Small 4", Some("mistral"), None, None),
];

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    pub provider_id: Option<String>,
    pub legacy_model: bool,
    pub release_date: Option<String>,
    pub api_retirement_date: Option<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NamedEntry {
    pub id: String,
    pub name: String,
    /// Memory categories only; mentions.ts defaults a missing type to "list".
    pub kind: Option<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AppInfo {
    pub id: String,
    pub name: String,
    pub skills: Vec<NamedEntry>,
    pub focus_modes: Vec<NamedEntry>,
    pub settings_and_memories: Vec<NamedEntry>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MemoryEntryInfo {
    pub id: String,
    pub app_id: String,
    pub item_type: String,
    pub title: Option<String>,
}
#[derive(Clone, Debug, Default)]
pub struct MentionContext {
    pub models: Vec<ModelInfo>,
    pub mates: Vec<(String, String)>,
    pub apps: Vec<AppInfo>,
    pub memory_entries: Vec<MemoryEntryInfo>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MentionType {
    Model,
    ModelAlias,
    Mate,
    Skill,
    FocusMode,
    SettingsMemory,
    SettingsMemoryEntry,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ResolvedMention {
    pub original: String,
    #[serde(rename = "type")]
    pub kind: MentionType,
    pub wire_syntax: String,
    pub display_name: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct UnresolvedMention {
    pub original: String,
    pub suggestions: Vec<String>,
}
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct MentionParseResult {
    pub processed_message: String,
    pub resolved: Vec<ResolvedMention>,
    pub file_paths: Vec<String>,
    pub unresolved: Vec<UnresolvedMention>,
}

/// The built-in chat model catalog used for model mentions.
pub fn chat_models() -> Vec<ModelInfo> {
    CHAT_MODELS
        .iter()
        .map(|(id, name, provider, release, retirement)| ModelInfo {
            id: (*id).into(),
            name: (*name).into(),
            provider_id: provider.map(Into::into),
            legacy_model: release.is_some(),
            release_date: release.map(Into::into),
            api_retirement_date: retirement.map(Into::into),
        })
        .collect()
}

impl MentionContext {
    /// Static models/mates plus the given server Apps (no memory entries).
    pub fn with_apps(apps: Vec<AppInfo>) -> Self {
        Self {
            models: chat_models(),
            mates: MATE_NAMES.iter().map(|(id, name)| ((*id).into(), (*name).into())).collect(),
            apps,
            memory_entries: vec![],
        }
    }
}

/// Parse the `/v1/apps` list response (`{"apps":[...]}` or a bare array).
pub fn apps_from_json(data: &Value) -> Vec<AppInfo> {
    let rows = data.get("apps").unwrap_or(data);
    let entries = |row: &Value, key: &str| -> Vec<NamedEntry> {
        row.get(key)
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|entry| {
                Some(NamedEntry {
                    id: entry.get("id")?.as_str()?.into(),
                    name: entry.get("name")?.as_str()?.into(),
                    kind: entry.get("type").and_then(Value::as_str).map(Into::into),
                })
            })
            .collect()
    };
    rows.as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| {
            Some(AppInfo {
                id: row.get("id")?.as_str()?.into(),
                name: row.get("name")?.as_str()?.into(),
                skills: entries(row, "skills"),
                focus_modes: entries(row, "focus_modes"),
                settings_and_memories: entries(row, "settings_and_memories"),
            })
        })
        .collect()
}

/// Decrypted memory rows (`Account::memories`) to memory-entry candidates;
/// the title comes from the decrypted `data.title` like the TS CLI.
pub fn memory_entries_from_json(rows: &[Value]) -> Vec<MemoryEntryInfo> {
    rows.iter()
        .filter_map(|row| {
            Some(MemoryEntryInfo {
                id: row.get("id")?.as_str().filter(|id| !id.is_empty())?.into(),
                app_id: row.get("app_id")?.as_str()?.into(),
                item_type: row.get("item_type")?.as_str()?.into(),
                title: row.pointer("/data/title").and_then(Value::as_str).map(Into::into),
            })
        })
        .collect()
}

/// JavaScript `\s` (ECMAScript WhiteSpace + LineTerminator).
fn js_space(c: char) -> bool {
    matches!(c, '\u{0009}'..='\u{000d}' | '\u{0020}' | '\u{00a0}' | '\u{1680}' | '\u{2000}'..='\u{200a}'
        | '\u{2028}' | '\u{2029}' | '\u{202f}' | '\u{205f}' | '\u{3000}' | '\u{feff}')
}

/// Tokens of `/(?:^|\s)@(\/[^\s]+|\.\/[^\s]+|~\/[^\s]+|[^\s@]+)/g`, without `@`.
pub fn extract_mention_tokens(message: &str) -> Vec<String> {
    let chars: Vec<(usize, char)> = message.char_indices().collect();
    let mut tokens = vec![];
    // Global-regex lastIndex in char positions: a match consumes its leading space.
    let mut last = 0usize;
    let run = |from: usize, stop_at: fn(char) -> bool| -> usize {
        let mut end = from;
        while end < chars.len() && !stop_at(chars[end].1) {
            end += 1;
        }
        end
    };
    let mut i = 0usize;
    while i < chars.len() {
        if chars[i].1 != '@' || !(i == 0 && last == 0 || i > 0 && i - 1 >= last && js_space(chars[i - 1].1)) {
            i += 1;
            continue;
        }
        let body = i + 1;
        let starts = |prefix: &str| {
            prefix.chars().enumerate().all(|(n, c)| chars.get(body + n).is_some_and(|(_, v)| *v == c))
        };
        let mut end = None;
        for prefix in ["/", "./", "~/"] {
            if starts(prefix) {
                let after = body + prefix.chars().count();
                let stop = run(after, js_space);
                if stop > after {
                    end = Some(stop);
                    break;
                }
            }
        }
        let end = end.unwrap_or_else(|| run(body, |c| js_space(c) || c == '@'));
        if end > body {
            let from = chars[body].0;
            let to = chars.get(end).map(|(b, _)| *b).unwrap_or(message.len());
            tokens.push(message[from..to].to_owned());
            last = end;
            i = end;
        } else {
            i += 1;
        }
    }
    tokens
}

fn is_file_path(token: &str) -> bool {
    ["/", "./", "~/", "../"].iter().any(|p| token.starts_with(p))
}
fn is_task_short_id(token: &str) -> bool {
    let Some(rest) = token.strip_prefix("TASK-") else { return false };
    let rest = rest.strip_suffix(['.', ',', ';', ':', '!', '?', ')']).unwrap_or(rest);
    !rest.is_empty() && rest.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}
fn is_wikipedia(token: &str) -> bool {
    let lower = token.to_lowercase();
    if lower.strip_prefix("wiki:").is_some_and(|rest| !rest.is_empty()) {
        return true;
    }
    let mut parts = token.splitn(3, ':');
    parts.next().is_some_and(|p| p.eq_ignore_ascii_case("wikipedia"))
        && parts.next().is_some_and(|l| (2..=10).contains(&l.len()) && l.chars().all(|c| c.is_ascii_alphabetic()))
        && parts.next().is_some_and(|rest| !rest.is_empty())
}

/// "Claude Opus 5.5" → "claude-opus-5.5"; strips everything outside [a-z0-9._-].
pub fn normalize(name: &str) -> String {
    let lower = name.to_lowercase();
    let mut spaced = String::with_capacity(lower.len());
    let mut in_space = false;
    for c in lower.chars() {
        if js_space(c) {
            if !in_space {
                spaced.push('-');
            }
            in_space = true;
        } else {
            spaced.push(c);
            in_space = false;
        }
    }
    spaced.chars().filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '.' | '_' | '-')).collect()
}

/// `s.split(/[\s_]+/).map(upper-first).join(" ")`.
fn capitalize(s: &str) -> String {
    let mut words = vec![String::new()];
    let mut separator = false;
    for c in s.chars() {
        if js_space(c) || c == '_' {
            if !separator {
                words.push(String::new());
            }
            separator = true;
        } else {
            separator = false;
            words.last_mut().unwrap().push(c);
        }
    }
    words
        .into_iter()
        .map(|w| {
            let mut chars = w.chars();
            chars.next().map(|f| f.to_uppercase().chain(chars).collect()).unwrap_or_default()
        })
        .collect::<Vec<String>>()
        .join(" ")
}
fn hyphenate(s: &str) -> String {
    let mut out = String::new();
    let mut in_space = false;
    for c in s.chars() {
        if js_space(c) {
            if !in_space {
                out.push('-');
            }
            in_space = true;
        } else {
            out.push(c);
            in_space = false;
        }
    }
    out
}
fn display(app: &str, name: &str) -> String {
    format!("{}-{}", capitalize(app), hyphenate(&capitalize(name)))
}

fn valid_date(value: &str) -> Option<(i64, u32, u32)> {
    let bytes = value.as_bytes();
    if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
        return None;
    }
    let year = value[0..4].parse().ok()?;
    let month: u32 = value[5..7].parse().ok()?;
    let day: u32 = value[8..10].parse().ok()?;
    (1..=12).contains(&month).then_some(())?;
    (1..=days_in_month(year, month)).contains(&day).then_some((year, month, day))
}
fn days_in_month(year: i64, month: u32) -> u32 {
    match month {
        2 if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}
/// Current UTC date as `YYYY-MM-DD`.
pub fn today_utc() -> String {
    // Browser-safe wall clock (std SystemTime panics on wasm32).
    let days = (crate::platform::unix_ms() / 86_400_000) as i64;
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

/// mentions.ts `isAvailableChatModel`: legacy models stay mentionable for one
/// year after release; any model stops at its API retirement date.
pub fn is_available_chat_model(model: &ModelInfo, today: &str) -> bool {
    let Some((year, month, day)) = valid_date(today) else { return false };
    if model.legacy_model {
        let Some(release) = model.release_date.as_deref().filter(|r| valid_date(r).is_some()) else {
            return false;
        };
        let cutoff_day = day.min(days_in_month(year - 1, month));
        let cutoff = format!("{:04}-{month:02}-{cutoff_day:02}", year - 1);
        if release < cutoff.as_str() || release > today {
            return false;
        }
    }
    model
        .api_retirement_date
        .as_deref()
        .is_none_or(|retire| valid_date(retire).is_some() && today < retire)
}

fn resolved(token: &str, kind: MentionType, wire: String, display_name: String) -> Option<ResolvedMention> {
    Some(ResolvedMention { original: format!("@{token}"), kind, wire_syntax: wire, display_name })
}

fn resolve_token(token: &str, context: &MentionContext, today: &str) -> Option<ResolvedMention> {
    let ident = |s: &str| !s.is_empty() && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-');
    if let Some(rest) = token.get(..5).filter(|p| p.eq_ignore_ascii_case("mate:")).map(|_| &token[5..])
        && ident(rest)
    {
        let category = rest.to_ascii_lowercase();
        let (_, name) = context.mates.iter().find(|(id, _)| *id == category)?;
        if name.is_empty() {
            return None;
        }
        return resolved(token, MentionType::Mate, format!("@mate:{category}"), format!("@{name}"));
    }
    if let Some(rest) = token.get(..6).filter(|p| p.eq_ignore_ascii_case("focus:")).map(|_| &token[6..])
        && let Some((app_id, focus_id)) = rest.split_once(':')
        && ident(app_id)
        && ident(focus_id)
        && let Some(app) = context.apps.iter().find(|a| a.id == app_id)
        && let Some(focus) = app.focus_modes.iter().find(|f| f.id == focus_id)
    {
        return resolved(token, MentionType::FocusMode, format!("@focus:{}:{}", app.id, focus.id), format!("@{}", display(&app.name, &focus.name)));
    }
    let normalized = normalize(token);
    if MODEL_ALIASES.iter().any(|(alias, _)| *alias == normalized) {
        let mut chars = token.chars();
        let first = chars.next().map(|c| c.to_uppercase().collect::<String>()).unwrap_or_default();
        return resolved(token, MentionType::ModelAlias, format!("@best-model:{normalized}"), format!("@{first}{}", chars.as_str().to_lowercase()));
    }
    for model in context.models.iter().filter(|m| is_available_chat_model(m, today)) {
        if normalize(&model.name) == normalized || model.id == normalized {
            let provider = model.provider_id.as_deref().map(|p| format!(":{p}")).unwrap_or_default();
            return resolved(token, MentionType::Model, format!("@ai-model:{}{provider}", model.id), format!("@{}", hyphenate(&model.name)));
        }
    }
    for (category, name) in &context.mates {
        if normalize(name) == normalized || normalize(category) == normalized {
            return resolved(token, MentionType::Mate, format!("@mate:{category}"), format!("@{name}"));
        }
    }
    let matches = |app: &AppInfo, entry: &NamedEntry| {
        normalized == normalize(&format!("{}-{}", app.name, entry.name)) || normalized == normalize(&format!("{}-{}", app.id, entry.id))
    };
    for app in &context.apps {
        if let Some(skill) = app.skills.iter().find(|s| matches(app, s)) {
            return resolved(token, MentionType::Skill, format!("@skill:{}:{}", app.id, skill.id), format!("@{}", display(&app.name, &skill.name)));
        }
    }
    for app in &context.apps {
        if let Some(focus) = app.focus_modes.iter().find(|f| matches(app, f)) {
            return resolved(token, MentionType::FocusMode, format!("@focus:{}:{}", app.id, focus.id), format!("@{}", display(&app.name, &focus.name)));
        }
    }
    for app in &context.apps {
        if let Some(memory) = app.settings_and_memories.iter().find(|m| matches(app, m)) {
            let kind = memory.kind.as_deref().filter(|k| !k.is_empty()).unwrap_or("list");
            return resolved(token, MentionType::SettingsMemory, format!("@memory:{}:{}:{kind}", app.id, memory.id), format!("@{}", display(&app.name, &memory.name)));
        }
    }
    for entry in &context.memory_entries {
        let Some(app) = context.apps.iter().find(|a| a.id == entry.app_id) else { continue };
        let title = entry.title.as_deref().filter(|t| !t.is_empty()).unwrap_or(&entry.id);
        if normalized == normalize(&format!("{}-{}-{title}", app.name, entry.item_type)) || normalized == normalize(&format!("{}-{title}", app.name)) {
            let category = app
                .settings_and_memories
                .iter()
                .find(|m| m.id == entry.item_type || normalize(&m.name) == normalize(&entry.item_type))
                .map(|m| m.id.as_str())
                .unwrap_or(&entry.item_type);
            return resolved(
                token,
                MentionType::SettingsMemoryEntry,
                format!("@memory-entry:{}:{category}:{}", app.id, entry.id),
                format!("@{}-{}-{}", capitalize(&app.name), hyphenate(&capitalize(&entry.item_type)), hyphenate(&capitalize(title))),
            );
        }
    }
    None
}

fn fuzzy_score(query: &str, candidate: &str) -> u32 {
    let (q, c) = (normalize(query), normalize(candidate));
    if q == c {
        return 100;
    }
    if c.starts_with(&q) {
        return 75;
    }
    if c.contains(&q) {
        return 50;
    }
    let q: Vec<char> = q.chars().collect();
    let mut matched = 0;
    for ch in c.chars() {
        if matched < q.len() && ch == q[matched] {
            matched += 1;
        }
    }
    // Math.round(x * 40) with x = matched / max(len, 1).
    ((matched as f64 / q.len().max(1) as f64) * 40.0 + 0.5).floor() as u32
}

fn known_mentions(context: &MentionContext, today: &str) -> Vec<String> {
    let mut out: Vec<String> = MODEL_ALIASES
        .iter()
        .map(|(alias, _)| {
            let mut c = alias.chars();
            c.next().map(|f| f.to_uppercase().chain(c).collect()).unwrap_or_default()
        })
        .collect();
    out.extend(context.models.iter().filter(|m| is_available_chat_model(m, today)).map(|m| hyphenate(&m.name)));
    out.extend(context.mates.iter().map(|(_, name)| name.clone()));
    for app in &context.apps {
        for entry in app.skills.iter().chain(&app.focus_modes).chain(&app.settings_and_memories) {
            out.push(display(&app.name, &entry.name));
        }
    }
    out
}

/// Replace every `@token` that is followed by JS whitespace or the end.
fn replace_token(message: &str, token: &str, wire: &str) -> String {
    let needle = format!("@{token}");
    let mut out = String::with_capacity(message.len());
    let mut rest = message;
    while let Some(at) = rest.find(&needle) {
        let after = &rest[at + needle.len()..];
        out.push_str(&rest[..at]);
        if after.chars().next().is_none_or(js_space) {
            out.push_str(wire);
        } else {
            out.push_str(&needle);
        }
        rest = after;
    }
    out.push_str(rest);
    out
}

/// mentions.ts `parseMentions` for an explicit `today` (`YYYY-MM-DD`, UTC).
pub fn parse_mentions(message: &str, context: &MentionContext, today: &str) -> MentionParseResult {
    let mut result = MentionParseResult { processed_message: message.to_owned(), ..Default::default() };
    for token in extract_mention_tokens(message) {
        if is_file_path(&token) {
            result.file_paths.push(token);
        } else if is_task_short_id(&token) || is_wikipedia(&token) {
            continue;
        } else if let Some(mention) = resolve_token(&token, context, today) {
            result.processed_message = replace_token(&result.processed_message, &token, &mention.wire_syntax);
            result.resolved.push(mention);
        } else {
            let mut scored: Vec<(String, u32)> = known_mentions(context, today)
                .into_iter()
                .map(|name| {
                    let score = fuzzy_score(&token, &name);
                    (name, score)
                })
                .filter(|(_, score)| *score >= 30)
                .collect();
            scored.sort_by(|a, b| b.1.cmp(&a.1));
            result.unresolved.push(UnresolvedMention {
                original: format!("@{token}"),
                suggestions: scored.into_iter().take(5).map(|(name, _)| format!("@{name}")).collect(),
            });
        }
    }
    result
}

#[cfg(test)]
#[path = "mentions_tests.rs"]
mod tests;
