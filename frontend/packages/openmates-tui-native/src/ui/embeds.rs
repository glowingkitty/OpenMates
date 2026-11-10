//! Opened-chat embed references, matching the TypeScript TUI carousel.
//!
//! Assistant messages carry saved results as ```json {"embed_id": ...}``` fences.
//! They render as compact cards in a centered carousel ("Embed n/N · ←/→ choose ·
//! Enter open"), never as raw payloads. Cards use only the reference metadata so
//! opening a chat performs no extra decryption or network work; Enter opens the
//! embed detail through the existing SDK `embed:` read, whose decrypted item is
//! summarized per type by [`detail_rows`].
mod test_result;

use super::markdown::{self, Link, Part, Row};
use super::{ACCENT, MUTED, TEXT};
use crate::model::{Chat, Item, Message};
use ratatui::style::{Color, Modifier, Style};
use serde_json::Value;
use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthStr;

/// Chat-scoped carousel state lives in the existing per-chat `embed_offsets`
/// map, which every chat switch and private-data clear already resets.
pub(super) const SELECTED: &str = "\u{0}embed-selected";
pub(super) const FOLLOW: &str = "\u{0}embed-follow";
const CARD_WIDTH: usize = 62;
/// The TS card border (#77717b); the panel border is too dark for card edges.
const BORDER: Color = Color::Rgb(0x77, 0x71, 0x7b);

#[derive(Clone, Debug, Default, PartialEq)]
pub(super) struct EmbedRef {
    pub id: String,
    pub kind: String,
    pub app: String,
    pub skill: String,
    pub query: String,
    pub title: String,
    pub status: String,
}

#[derive(Debug, PartialEq)]
pub(super) enum Segment<'a> {
    Text(&'a str),
    Embed(EmbedRef),
}

fn meta_text<'a>(meta: &'a Value, key: &str) -> &'a str {
    meta.get(key).and_then(Value::as_str).map(str::trim).unwrap_or("")
}

impl EmbedRef {
    fn from_meta(id: &str, meta: &Value) -> Self {
        let first = |keys: &[&str]| {
            keys.iter().map(|key| meta_text(meta, key)).find(|v| !v.is_empty()).unwrap_or("").to_owned()
        };
        Self {
            id: id.into(),
            kind: first(&["type"]),
            app: first(&["app_id", "app"]),
            skill: first(&["skill_id", "skill"]),
            query: first(&["query", "search_query"]),
            title: first(&["title", "name", "filename"]),
            status: first(&["status"]),
        }
    }
    /// A live-stream artifact item: the same compact card as an inline reference.
    fn from_item(item: &Item) -> Self {
        let mut found = Self::from_meta(&item.id, &item.fields);
        if found.kind.is_empty() {
            found.kind = item.category.clone();
        }
        if found.title.is_empty() {
            found.title = item.title.clone();
        }
        found
    }
}

/// Split a message into text and embed references, exactly like the TS
/// `parseMessageSegments`: only closed `json`/`json_embed` fences whose body is
/// an object with a non-empty `embed_id` are references; other fences stay text
/// and nothing inside an enclosing fence is scanned.
pub(super) fn segments(content: &str) -> Vec<Segment<'_>> {
    if !content.contains("embed_id") {
        return vec![Segment::Text(content)];
    }
    let rows: Vec<(usize, &str)> = content
        .split_inclusive('\n')
        .scan(0, |offset, row| {
            let start = *offset;
            *offset += row.len();
            Some((start, row))
        })
        .collect();
    let trim_eol = |row: &str| row.trim_end_matches('\n').trim_end_matches('\r').to_owned();
    let mut out = vec![];
    let mut last = 0;
    let mut index = 0;
    while index < rows.len() {
        let line = trim_eol(rows[index].1);
        let Some((marker, count, info)) = fence_open(&line) else {
            index += 1;
            continue;
        };
        let mut end = index + 1;
        while end < rows.len() && !fence_close(&trim_eol(rows[end].1), marker, count) {
            end += 1;
        }
        if end == rows.len() {
            break;
        }
        let language = info.trim();
        let start = rows[index].0;
        let finish = rows[end].0 + trim_eol(rows[end].1).len();
        let body: String = rows[index + 1..end].iter().map(|(_, row)| *row).collect();
        index = end + 1;
        if language != "json" && language != "json_embed" {
            continue;
        }
        let Ok(meta) = serde_json::from_str::<Value>(body.trim()) else { continue };
        let id = meta_text(&meta, "embed_id");
        if !meta.is_object() || id.is_empty() {
            continue;
        }
        if start > last {
            out.push(Segment::Text(&content[last..start]));
        }
        out.push(Segment::Embed(EmbedRef::from_meta(id, &meta)));
        last = finish;
    }
    if last < content.len() {
        out.push(Segment::Text(&content[last..]));
    }
    out
}

fn fence_open(line: &str) -> Option<(char, usize, &str)> {
    let rest = line.trim_start_matches(' ');
    if line.len() - rest.len() > 3 {
        return None;
    }
    let marker = rest.chars().next().filter(|c| *c == '`' || *c == '~')?;
    let count = rest.chars().take_while(|c| *c == marker).count();
    let info = &rest[count..];
    (count >= 3 && !info.contains(['`', '~'])).then_some((marker, count, info))
}

fn fence_close(line: &str, marker: char, count: usize) -> bool {
    let rest = line.trim_start_matches(' ');
    if line.len() - rest.len() > 3 {
        return false;
    }
    let run = rest.chars().take_while(|c| *c == marker).count();
    run >= count && rest[run..].chars().all(|c| c == ' ' || c == '\t')
}

fn message_refs(message: &Message) -> Vec<EmbedRef> {
    let mut refs: Vec<EmbedRef> = vec![];
    for segment in segments(&message.content) {
        if let Segment::Embed(found) = segment
            && !refs.iter().any(|known| known.id == found.id)
        {
            refs.push(found);
        }
    }
    for item in &message.embeds {
        if !refs.iter().any(|known| known.id == item.id) {
            refs.push(EmbedRef::from_item(item));
        }
    }
    refs
}

/// Every reference of the opened chat in transcript order, without duplicates.
pub(super) fn chat_refs(chat: &Chat) -> Vec<EmbedRef> {
    let mut refs: Vec<EmbedRef> = vec![];
    for message in &chat.messages {
        for found in message_refs(message) {
            if !refs.iter().any(|known| known.id == found.id) {
                refs.push(found);
            }
        }
    }
    refs
}

thread_local! {
    /// `(chat id, [(embed id, alias)])`: aliases stay stable while the opened
    /// chat gains older messages, like the TS `state.embedAliases`.
    static ALIASES: std::cell::RefCell<(String, Vec<(String, String)>)> = const { std::cell::RefCell::new((String::new(), Vec::new())) };
}

fn short_part(value: &str) -> String {
    let mut out = String::new();
    for c in value.to_lowercase().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c);
        } else if !out.ends_with('_') {
            out.push('_');
        }
    }
    out.trim_matches('_').to_owned()
}

/// TS `embedAliasPrefix`: three letters of the app plus skill initials.
fn alias_prefix(app: &str, skill: &str) -> String {
    let app: String = short_part(app).chars().take(3).collect();
    let skill: Vec<String> = short_part(skill).split('_').filter_map(|w| w.chars().next()).map(String::from).collect();
    format!(
        "{}-{}",
        if app.is_empty() { "emb" } else { &app },
        if skill.is_empty() { "v".into() } else { skill.join("_") }
    )
}

/// Allocate `emb-v-6`-style aliases for the opened chat's references.
pub(super) fn register(chat: &Chat) {
    ALIASES.with(|cell| {
        let mut state = cell.borrow_mut();
        if state.0 != chat.id {
            *state = (chat.id.clone(), Vec::new());
        }
        for found in chat_refs(chat) {
            if state.1.iter().any(|(id, _)| *id == found.id) {
                continue;
            }
            let prefix = alias_prefix(
                if found.app.is_empty() { "embed" } else { &found.app },
                if found.skill.is_empty() { "view" } else { &found.skill },
            );
            let mut count = 1;
            while state.1.iter().any(|(_, alias)| *alias == format!("{prefix}-{count}")) {
                count += 1;
            }
            state.1.push((found.id, format!("{prefix}-{count}")));
        }
    });
}

/// The command shortcut shown for an embed; ids outside the opened chat stay whole.
pub(super) fn short_id(id: &str) -> String {
    ALIASES.with(|cell| {
        cell.borrow().1.iter().find(|(known, _)| known == id).map(|(_, alias)| alias.clone())
    })
    .unwrap_or_else(|| id.to_owned())
}

/// `/embed <shortcut>` accepts the displayed alias of an opened-chat reference.
pub(super) fn resolve_alias(chat: Option<&Chat>, value: &str) -> String {
    if uuid::Uuid::parse_str(value).is_ok() {
        return value.into();
    }
    if let Some(chat) = chat {
        register(chat);
    }
    ALIASES
        .with(|cell| cell.borrow().1.iter().find(|(_, alias)| alias == value).map(|(id, _)| id.clone()))
        .unwrap_or_else(|| value.into())
}

fn pretty(value: &str) -> String {
    value
        .split(['_', '-', '/'])
        .filter(|word| !word.is_empty())
        .map(|word| {
            let mut chars = word.chars();
            chars.next().map(|c| c.to_uppercase().chain(chars).collect::<String>()).unwrap_or_default()
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn fit(text: &str, width: usize) -> String {
    let mut out = String::new();
    let mut used = 0;
    let clean = markdown::clean(text).replace(['\n', '\t'], " ");
    let truncate = clean.width() > width;
    let limit = if truncate { width.saturating_sub(1) } else { width };
    for g in clean.graphemes(true) {
        if used + g.width() > limit {
            break;
        }
        out.push_str(g);
        used += g.width();
    }
    if truncate && width > 0 {
        out.push('…');
        used += 1;
    }
    out.push_str(&" ".repeat(width.saturating_sub(used)));
    out
}

/// One compact card; the final two inner rows are the shared basic-info bar.
fn card(found: &EmbedRef, width: usize) -> Vec<Row> {
    let inner = width.saturating_sub(4);
    let link = Some(Link::Embed(found.id.clone()));
    let category = if found.app.is_empty() { found.kind.as_str() } else { found.app.as_str() };
    let color = super::app_color(category);
    let border = Style::default().fg(BORDER);
    let part = |text: String, style: Style| Part { text, style, link: link.clone() };
    let row = |text: &str, style: Style| vec![part("│ ".into(), border), part(fit(text, inner), style), part(" │".into(), border)];
    let title = [&found.title, &found.query]
        .into_iter()
        .find(|v| !v.is_empty())
        .cloned()
        .unwrap_or_else(|| pretty(if found.kind.is_empty() { "result" } else { &found.kind }));
    let detail = if !found.query.is_empty() && found.query != title {
        found.query.clone()
    } else if !found.status.is_empty() && found.status != "finished" {
        pretty(&found.status)
    } else {
        String::new()
    };
    let app = pretty(if found.app.is_empty() { "embed" } else { &found.app });
    let skill = pretty(if !found.skill.is_empty() { &found.skill } else if !found.kind.is_empty() { &found.kind } else { "view" });
    vec![
        vec![part(format!("╭{}╮", "─".repeat(width - 2)), border)],
        row(&title, Style::default().fg(TEXT).add_modifier(Modifier::BOLD)),
        row(&detail, Style::default().fg(MUTED)),
        vec![part(format!("├{}┤", "─".repeat(width - 2)), border)],
        row(&format!("{app} · {skill}"), Style::default().fg(color).add_modifier(Modifier::BOLD)),
        row(&format!("/embed {}", short_id(&found.id)), Style::default().fg(color)),
        vec![part(format!("╰{}╯", "─".repeat(width - 2)), border)],
    ]
}

/// Copy the cells `[from, from + len)` of a styled row.
fn crop(row: &Row, from: usize, len: usize) -> Row {
    let mut out = vec![];
    let mut column = 0;
    for source in row {
        let mut text = String::new();
        for g in source.text.graphemes(true) {
            let w = g.width();
            if column >= from && column + w <= from + len {
                text.push_str(g);
            }
            column += w;
        }
        if !text.is_empty() {
            out.push(Part { text, style: source.style, link: source.link.clone() });
        }
    }
    out
}

/// Centered card viewport: the selected card in the middle, neighbours cropped.
fn carousel(cards: &[Vec<Row>], width: usize, selected: usize, card_width: usize) -> Vec<Row> {
    let stride = (card_width + 2) as i64;
    let center = ((width - card_width) / 2) as i64;
    let height = cards.iter().map(Vec::len).max().unwrap_or(0);
    (0..height)
        .map(|line| {
            let mut out: Row = vec![];
            let mut column = 0usize;
            for (index, rows) in cards.iter().enumerate() {
                let left = center + (index as i64 - selected as i64) * stride;
                let right = left + card_width as i64;
                if left >= width as i64 || right <= 0 {
                    continue;
                }
                let start = left.max(0) as usize;
                let end = (right as usize).min(width);
                if start > column {
                    out.push(Part { text: " ".repeat(start - column), style: Style::default(), link: None });
                }
                if let Some(row) = rows.get(line) {
                    out.extend(crop(row, (start as i64 - left) as usize, end - start));
                }
                column = end;
            }
            out
        })
        .collect()
}

fn centered(text: String, width: usize, link: Link) -> Row {
    let text = fit(&text, width).trim_end().to_owned();
    let pad = width.saturating_sub(text.width()) / 2;
    vec![
        Part { text: " ".repeat(pad), style: Style::default(), link: None },
        Part { text, style: Style::default().fg(MUTED), link: Some(link) },
    ]
}

/// Render one message. Consecutive references (only whitespace between them)
/// share one carousel; the group holding the selected reference shows the
/// TS "Embed n/N · ←/→ choose · Enter open" line. Returns the first row of that
/// group so the caller can scroll a newly chosen embed into view.
pub(super) fn message_rows(message: &Message, width: usize, selected: Option<&str>) -> (Vec<Row>, Option<usize>) {
    let text_width = width.saturating_sub(2);
    if message.embeds.is_empty() && !message.content.contains("embed_id") {
        return (markdown::render(&message.content, text_width), None);
    }
    let mut rows = vec![];
    let mut at = None;
    let mut pending: Vec<EmbedRef> = vec![];
    let mut flush = |pending: &mut Vec<EmbedRef>, rows: &mut Vec<Row>| {
        if pending.is_empty() {
            return;
        }
        let card_width = width.clamp(8, CARD_WIDTH).min(width.max(1));
        if card_width < 8 {
            for found in pending.drain(..) {
                rows.push(vec![Part {
                    text: format!("/embed {}", short_id(&found.id)),
                    style: Style::default().fg(MUTED),
                    link: Some(Link::Embed(found.id)),
                }]);
            }
            return;
        }
        if !rows.is_empty() {
            rows.push(vec![]);
        }
        let index = selected.and_then(|id| pending.iter().position(|r| r.id == id));
        if index.is_some() {
            at = Some(rows.len());
        }
        let cards: Vec<Vec<Row>> = pending.iter().map(|r| card(r, card_width)).collect();
        rows.extend(carousel(&cards, width, index.unwrap_or(0), card_width));
        if let Some(index) = index {
            let id = pending[index].id.clone();
            rows.push(centered(
                format!(
                    "Embed {}/{} · ←/→ choose · Enter open · /embed {}",
                    index + 1,
                    pending.len(),
                    short_id(&id)
                ),
                width,
                Link::Embed(id),
            ));
        }
        pending.clear();
    };
    let parsed = segments(&message.content);
    let inline: Vec<String> = parsed
        .iter()
        .filter_map(|segment| match segment {
            Segment::Embed(found) => Some(found.id.clone()),
            Segment::Text(_) => None,
        })
        .collect();
    for segment in parsed {
        match segment {
            Segment::Embed(found) => {
                if !pending.iter().any(|known| known.id == found.id) {
                    pending.push(found);
                }
            }
            Segment::Text(text) if !text.trim().is_empty() => {
                flush(&mut pending, &mut rows);
                rows.extend(markdown::render(text, text_width));
            }
            Segment::Text(_) => {}
        }
    }
    for item in message.embeds.iter().filter(|item| !inline.contains(&item.id)) {
        if !pending.iter().any(|known| known.id == item.id) {
            pending.push(EmbedRef::from_item(item));
        }
    }
    flush(&mut pending, &mut rows);
    (rows, at)
}

impl super::Ui {
    /// The chat-wide selected reference (default: the first, as in TS).
    pub(super) fn selected_embed(&self) -> Option<EmbedRef> {
        let refs = chat_refs(self.chat.as_ref()?);
        let index = self.embed_offsets.get(SELECTED).copied().unwrap_or(0);
        refs.get(index.min(refs.len().saturating_sub(1))).cloned()
    }
    /// After a layout rebuild: scroll a newly chosen embed into view and keep
    /// the keyboard highlight on the selected card's links.
    pub(super) fn follow_selected_embed(&mut self, row: Option<usize>, rows: &[Row]) {
        let Some(row) = row else { return };
        if self.embed_offsets.remove(FOLLOW).is_some() {
            self.scroll = row.saturating_sub(2);
            self.follow_tail = false;
        }
        let Some(found) = self.selected_embed() else { return };
        let target = Link::Embed(found.id);
        let mut links: Vec<&Link> = vec![];
        for link in rows.iter().flatten().filter_map(|part| part.link.as_ref()) {
            if !links.contains(&link) {
                links.push(link);
            }
        }
        if let Some(index) = links.iter().position(|link| **link == target) {
            self.content_action = index;
        }
    }
    /// ←/→ choose and Enter opens, when the opened chat has references.
    pub(super) fn embed_carousel_key(&mut self, code: crossterm::event::KeyCode) -> Option<Vec<super::UiCommand>> {
        use crossterm::event::KeyCode;
        let refs = chat_refs(self.chat.as_ref()?);
        if refs.is_empty() {
            return None;
        }
        let index = self.embed_offsets.get(SELECTED).copied().unwrap_or(0).min(refs.len() - 1);
        match code {
            KeyCode::Enter => Some(self.activate(super::HitAction::Link(Link::Embed(refs[index].id.clone())))),
            KeyCode::Left | KeyCode::Right => {
                let next = if code == KeyCode::Left { index.saturating_sub(1) } else { (index + 1).min(refs.len() - 1) };
                self.embed_offsets.insert(SELECTED.into(), next);
                self.embed_offsets.insert(FOLLOW.into(), 1);
                self.chat_layout = None;
                self.hits.clear();
                Some(vec![])
            }
            _ => None,
        }
    }
}

fn text<'a>(value: &'a Value, keys: &[&str]) -> &'a str {
    keys.iter().filter_map(|key| value.get(key)).find_map(|v| v.as_str().map(str::trim).filter(|v| !v.is_empty())).unwrap_or("")
}

fn scalar(value: &Value, keys: &[&str]) -> String {
    for key in keys {
        match value.get(key) {
            Some(Value::String(v)) if !v.trim().is_empty() => return v.trim().into(),
            Some(Value::Number(n)) => return n.to_string(),
            _ => {}
        }
    }
    String::new()
}

fn child_ids(content: &Value) -> Vec<String> {
    match content.get("embed_ids") {
        Some(Value::Array(ids)) => ids.iter().filter_map(Value::as_str).map(str::to_owned).collect(),
        Some(Value::String(ids)) => ids.split(['|', ',']).map(str::trim).filter(|v| !v.is_empty()).map(str::to_owned).collect(),
        _ => vec![],
    }
}

/// Per-type detail summary for a decrypted embed item (`fields.type`,
/// `fields.content`). Unknown types get a short type + title card; a raw JSON
/// payload is never shown. `None` when the item is not a decrypted embed.
pub(super) fn detail_rows(item: &Item, width: usize) -> Option<Vec<Row>> {
    let kind = item.fields.get("type").and_then(Value::as_str)?;
    let content = item.fields.get("content")?;
    let width = width.max(1);
    let app = text(content, &["app_id"]);
    let skill = text(content, &["skill_id"]);
    let mut rows: Vec<Row> = vec![];
    let label = if !app.is_empty() {
        format!("{} · {}", pretty(app), pretty(if skill.is_empty() { kind } else { skill }))
    } else {
        pretty(if kind.is_empty() { "embed" } else { kind })
    };
    let status = text(content, &["status"]);
    let status = if status.is_empty() { item.status.as_str() } else { status };
    let mut header = format!("{label}  ·  {}", short_id(&item.id));
    if !status.is_empty() && status != "finished" {
        header.push_str(&format!("  ·  {}", pretty(status)));
    }
    rows.push(markdown::styled(header, Style::default().fg(super::app_color(if app.is_empty() { kind } else { app })).bold()));
    let title = text(content, &["title", "name", "filename"]);
    if !title.is_empty() {
        rows.extend(markdown::wrap(markdown::styled(title, Style::default().fg(TEXT).bold()), width));
    }
    let field = |rows: &mut Vec<Row>, name: &str, value: &str| {
        if !value.is_empty() {
            rows.extend(markdown::wrap(
                vec![
                    Part { text: format!("{name}: "), style: Style::default().fg(MUTED), link: None },
                    Part { text: markdown::clean(value), style: Style::default().fg(TEXT), link: None },
                ],
                width,
            ));
        }
    };
    let url_row = |rows: &mut Vec<Row>, url: &str| {
        if url.starts_with("https://") || url.starts_with("http://") {
            rows.extend(markdown::wrap(
                vec![Part { text: markdown::clean(url), style: Style::default().fg(super::BLUE), link: Some(Link::Url(url.into())) }],
                width,
            ));
        }
    };
    let body = |rows: &mut Vec<Row>, value: &str| {
        if !value.is_empty() {
            rows.push(vec![]);
            rows.extend(markdown::render(value, width));
        }
    };
    let error = text(content, &["error", "error_message"]);
    match (kind, app) {
        ("code" | "code-code", _) => {
            let language = text(content, &["language"]);
            field(&mut rows, "File", text(content, &["filename", "file_path"]));
            field(&mut rows, "Language", language);
            field(&mut rows, "Lines", &scalar(content, &["line_count"]));
            let code = text(content, &["code", "content"]);
            if !code.is_empty() {
                let fence = if code.contains("```") { "~~~~" } else { "```" };
                body(&mut rows, &format!("{fence}{language}\n{code}\n{fence}"));
            }
        }
        ("code-test-result" | "test_result", _) => match test_result::rows(content, width) {
            Some(result_rows) => rows.extend(result_rows),
            None => field(&mut rows, "Result", "Unreadable test result"),
        },
        ("code-application" | "application", _) => {
            field(&mut rows, "Framework", text(content, &["framework"]));
            field(&mut rows, "Runtime", text(content, &["runtime"]));
        }
        ("image" | "images-image-result" | "file" | "pdf" | "upload" | "document" | "audio" | "video", _)
        | (_, "images") => {
            field(&mut rows, "Prompt", text(content, &["prompt"]));
            field(&mut rows, "Type", text(content, &["mime_type", "content_type", "file_type", "format"]));
            let size = scalar(content, &["size_bytes", "file_size", "size"]);
            field(&mut rows, "Size", &if size.chars().all(|c| c.is_ascii_digit()) && !size.is_empty() { format!("{size} bytes") } else { size });
            let (w, h) = (scalar(content, &["width"]), scalar(content, &["height"]));
            if !w.is_empty() && !h.is_empty() {
                field(&mut rows, "Dimensions", &format!("{w} × {h}"));
            }
            field(&mut rows, "Model", text(content, &["model", "model_name"]));
            url_row(&mut rows, text(content, &["url", "source_page_url", "image_url"]));
        }
        ("web-website" | "news-article" | "videos-video", _) => {
            field(&mut rows, "Source", text(content, &["source", "channel", "author", "provider"]));
            field(&mut rows, "Published", text(content, &["page_age", "published_at", "date"]));
            url_row(&mut rows, text(content, &["url", "link"]));
            body(&mut rows, text(content, &["description", "snippet", "summary"]));
        }
        ("events-event" | "calendar-event" | "calendar_event", _) => {
            let when = [text(content, &["date", "start_date", "start_time", "dateTime"]), text(content, &["end_date", "end_time"])]
                .into_iter()
                .filter(|v| !v.is_empty())
                .collect::<Vec<_>>()
                .join(" → ");
            field(&mut rows, "When", &when);
            field(&mut rows, "Where", text(content, &["venue_name", "venue", "location", "address"]));
            url_row(&mut rows, text(content, &["url", "link"]));
            body(&mut rows, text(content, &["description", "summary"]));
        }
        (_, "reminder") => {
            field(&mut rows, "Message", text(content, &["prompt", "message", "reminder_text"]));
            field(&mut rows, "Time", text(content, &["trigger_at_formatted", "trigger_at"]));
            let target = match text(content, &["target_type"]) {
                "new_chat" => "Opens new chat",
                "same_chat" => "Continues this chat",
                other => other,
            };
            field(&mut rows, "Target", target);
            if let Some(repeat) = content.get("is_repeating").and_then(Value::as_bool) {
                field(&mut rows, "Repeating", if repeat { "Yes" } else { "No" });
            }
        }
        ("app_skill_use", _) | ("app-skill-use", _) => {
            field(&mut rows, "Query", text(content, &["query", "search_query", "question"]));
            field(&mut rows, "Provider", text(content, &["provider"]));
            let when = [text(content, &["start_date"]), text(content, &["end_date"])]
                .into_iter()
                .filter(|v| !v.is_empty())
                .collect::<Vec<_>>()
                .join(" → ");
            field(&mut rows, "Dates", &when);
            field(&mut rows, "Location", text(content, &["location"]));
            let results = super::apps::result_rows(item, width);
            let children = child_ids(content);
            let noun = match skill {
                "search" if app == "events" => "events",
                _ if app == "videos" => "videos",
                _ => "results",
            };
            if !results.is_empty() {
                rows.push(vec![]);
                rows.extend(results);
            } else if !children.is_empty() {
                rows.push(vec![]);
                rows.push(markdown::styled(format!("{} {noun}", children.len()), Style::default().fg(MUTED)));
                for (index, id) in children.iter().enumerate() {
                    rows.push(vec![Part {
                        text: format!("  {}. Open result · /embed {}", index + 1, short_id(id)),
                        style: Style::default().fg(super::BLUE),
                        link: Some(Link::Embed(id.clone())),
                    }]);
                }
            } else if status == "finished" && skill.contains("search") {
                rows.push(markdown::styled(format!("No {noun}"), Style::default().fg(MUTED)));
            }
        }
        _ => {}
    }
    if title.is_empty() && !item.description.is_empty() {
        body(&mut rows, &item.description);
    }
    if !error.is_empty() {
        rows.push(vec![]);
        rows.push(markdown::styled(format!("Error: {error}"), Style::default().fg(ACCENT)));
    }
    Some(rows)
}

#[cfg(test)]
mod tests {
    use super::*;

    const ID: &str = "237a754b-f65c-4e2c-aea2-edaf207b0998";
    const ID2: &str = "9b4f1c2e-0000-4000-8000-000000000002";

    fn text_of(rows: &[Row]) -> String {
        rows.iter().map(|row| row.iter().map(|p| p.text.as_str()).collect::<String>()).collect::<Vec<_>>().join("\n")
    }

    #[test]
    fn parses_json_fences_as_references_and_keeps_other_fences() {
        let content = format!(
            "Intro\n```json\n{{\"type\": \"code\", \"embed_id\": \"{ID}\"}}\n```\n\n```json\n{{\"a\":1}}\n```\n````md\n```json\n{{\"embed_id\":\"inner\"}}\n```\n````\nEnd"
        );
        let found = segments(&content);
        let refs: Vec<_> = found.iter().filter_map(|s| match s { Segment::Embed(r) => Some(r.id.as_str()), _ => None }).collect();
        assert_eq!(refs, [ID]);
        let text: String = found.iter().filter_map(|s| match s { Segment::Text(t) => Some(*t), _ => None }).collect();
        assert!(text.starts_with("Intro\n"));
        assert!(text.contains("{\"a\":1}"), "non-reference fences stay text");
        assert!(text.contains("\"inner\""), "fences inside a fence are not scanned");
        assert!(!text.contains(ID));
        assert_eq!(segments("plain"), vec![Segment::Text("plain")]);
    }

    #[test]
    fn unclosed_fence_is_text() {
        let content = format!("```json\n{{\"embed_id\":\"{ID}\"}}");
        assert_eq!(segments(&content), vec![Segment::Text(&content)]);
    }

    #[test]
    fn message_renders_compact_cards_and_carousel_footer_not_raw_json() {
        let message = Message {
            content: format!(
                "Here you go\n\n```json\n{{\"type\":\"code\",\"embed_id\":\"{ID}\"}}\n```\n\n```json\n{{\"type\":\"app_skill_use\",\"embed_id\":\"{ID2}\",\"app_id\":\"web\",\"skill_id\":\"search\",\"query\":\"rail passes\"}}\n```\n\nDone"
            ),
            ..Default::default()
        };
        register(&Chat { messages: vec![message.clone()], ..Default::default() });
        let (rows, at) = message_rows(&message, 100, Some(ID2));
        let text = text_of(&rows);
        assert!(!text.contains("embed_id"), "{text}");
        assert!(!text.contains("```"));
        assert!(text.contains("Web · Search"));
        assert!(text.contains("rail passes"));
        assert!(text.contains("Embed 2/2 · ←/→ choose · Enter open · /embed web-s-1"));
        let at = at.expect("selected group row");
        assert!(text_of(&rows[at..at + 1]).contains('╭'));
        assert!(rows.iter().flatten().any(|p| p.link == Some(Link::Embed(ID.into()))));
        // The first card is centered when it is selected.
        let (rows, _) = message_rows(&message, 100, Some(ID));
        assert!(text_of(&rows).contains("Embed · Code"));
        assert!(text_of(&rows).contains("Embed 1/2"));
        // A non-selected group still shows cards but no footer.
        let (rows, at) = message_rows(&message, 100, None);
        assert!(at.is_none());
        assert!(text_of(&rows).contains("Embed · Code"));
        assert!(!text_of(&rows).contains("←/→ choose"));
    }

    #[test]
    fn carousel_centers_selected_card_and_rows_fit_width() {
        let refs: Vec<EmbedRef> = (0..3).map(|i| EmbedRef { id: format!("id-{i}"), title: format!("Card {i}"), ..Default::default() }).collect();
        let cards: Vec<_> = refs.iter().map(|r| card(r, 30)).collect();
        let rows = carousel(&cards, 80, 1, 30);
        for row in &rows {
            assert!(row.iter().map(|p| p.text.width()).sum::<usize>() <= 80);
        }
        let title_row = text_of(&rows[1..2]);
        let selected = title_row.find("Card 1").unwrap();
        // Centered at (80 - 30) / 2, after the "│ " border.
        assert_eq!(title_row[..selected].width(), 27, "{title_row}");
        // Neighbours are cropped at the viewport edges, not wrapped.
        assert!(title_row.starts_with('0'), "{title_row}");
        assert!(title_row.contains("│ Card 2"));
    }

    #[test]
    fn narrow_width_falls_back_to_plain_refs() {
        let message = Message { content: format!("```json\n{{\"embed_id\":\"{ID}\"}}\n```"), ..Default::default() };
        register(&Chat { messages: vec![message.clone()], ..Default::default() });
        let (rows, _) = message_rows(&message, 6, Some(ID));
        assert_eq!(text_of(&rows), "/embed emb-v-1");
    }

    #[test]
    fn short_ids_resolve_within_the_opened_chat() {
        let chat = Chat {
            messages: vec![Message { content: format!("```json\n{{\"embed_id\":\"{ID}\"}}\n```"), ..Default::default() }],
            ..Default::default()
        };
        assert_eq!(resolve_alias(Some(&chat), "emb-v-1"), ID);
        assert_eq!(short_id(ID), "emb-v-1");
        assert_eq!(short_id("not-a-uuid"), "not-a-uuid");
        assert_eq!(resolve_alias(Some(&chat), ID), ID);
        assert_eq!(resolve_alias(None, "emb-v-9"), "emb-v-9");
    }

    #[test]
    fn aliases_follow_ts_prefix_and_count_per_app_skill() {
        assert_eq!(alias_prefix("web", "search"), "web-s");
        assert_eq!(alias_prefix("embed", "view"), "emb-v");
        assert_eq!(alias_prefix("", ""), "emb-v");
        assert_eq!(alias_prefix("travel", "search_connections"), "tra-s_c");
        let body = |id: &str, app: &str| format!("```json\n{{\"embed_id\":\"{id}\",\"app_id\":\"{app}\",\"skill_id\":\"search\"}}\n```\n");
        let chat = Chat {
            messages: vec![Message { content: format!("{}{}{}", body(ID, "web"), body(ID2, "web"), body("c", "web")), ..Default::default() }],
            ..Default::default()
        };
        register(&chat);
        assert_eq!((short_id(ID), short_id(ID2), short_id("c")), ("web-s-1".into(), "web-s-2".into(), "web-s-3".into()));
    }

    fn embed(kind: &str, content: Value) -> Item {
        Item { id: ID.into(), title: "t".into(), category: kind.into(), fields: serde_json::json!({"type": kind, "content": content}), ..Default::default() }
    }

    #[test]
    fn code_detail_shows_file_language_and_code_block() {
        let item = embed("code", serde_json::json!({"language":"tsx","filename":"App.tsx","line_count":3,"code":"export const A = () => <div/>;"}));
        let text = text_of(&detail_rows(&item, 80).unwrap());
        assert!(text.starts_with(&format!("Code  ·  {ID}")));
        assert!(text.contains("File: App.tsx"));
        assert!(text.contains("Language: tsx"));
        assert!(text.contains("Lines: 3"));
        assert!(text.contains("export const A"));
        assert!(!text.contains("\"code\""));
    }

    #[test]
    fn search_detail_lists_query_and_child_results() {
        let item = embed("app_skill_use", serde_json::json!({"app_id":"web","skill_id":"search","query":"night trains","provider":"Brave","status":"finished","embed_ids":format!("{ID2}|{ID}")}));
        let rows = detail_rows(&item, 80).unwrap();
        let text = text_of(&rows);
        assert!(text.starts_with("Web · Search"));
        assert!(text.contains("Query: night trains"));
        assert!(text.contains("Provider: Brave"));
        assert!(text.contains("2 results"));
        assert!(rows.iter().flatten().any(|p| p.link == Some(Link::Embed(ID2.into()))));
        // Non-search skills never claim an empty result list.
        let create = embed("app_skill_use", serde_json::json!({"app_id":"projects","skill_id":"create","title":"Recipe Web App","status":"finished"}));
        assert_eq!(text_of(&detail_rows(&create, 80).unwrap()), format!("Projects · Create  ·  {ID}\nRecipe Web App"));
    }

    #[test]
    fn image_event_and_reminder_details_are_summaries() {
        let image = text_of(&detail_rows(&embed("image", serde_json::json!({"filename":"cat.png","mime_type":"image/png","width":640,"height":480,"size_bytes":2048})), 80).unwrap());
        assert!(image.contains("File") || image.contains("cat.png"));
        assert!(image.contains("Dimensions: 640 × 480"));
        assert!(image.contains("Size: 2048 bytes"));
        let event = text_of(&detail_rows(&embed("events-event", serde_json::json!({"name":"Jazz night","date":"2026-11-08","venue":"Club","url":"https://example.org/e"})), 80).unwrap());
        assert!(event.contains("Jazz night") && event.contains("When: 2026-11-08") && event.contains("Where: Club"));
        let reminder = text_of(&detail_rows(&embed("app_skill_use", serde_json::json!({"app_id":"reminder","skill_id":"set-reminder","prompt":"Call mom","trigger_at_formatted":"Fri 9:00","target_type":"same_chat","is_repeating":false})), 80).unwrap());
        assert!(reminder.contains("Message: Call mom") && reminder.contains("Time: Fri 9:00") && reminder.contains("Continues this chat") && reminder.contains("Repeating: No"));
    }

    #[test]
    fn unknown_types_get_a_short_card_never_raw_json() {
        let item = embed("mindmap", serde_json::json!({"title":"Plan","nodes":[{"id":"x","secret":"value"}]}));
        let text = text_of(&detail_rows(&item, 80).unwrap());
        assert_eq!(text, format!("Mindmap  ·  {ID}\nPlan"));
        assert!(detail_rows(&Item::default(), 80).is_none());
    }
}
