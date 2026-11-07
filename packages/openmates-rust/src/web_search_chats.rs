//! Worker-resident chat message search index (shared core; served by the
//! shared Rust core Worker's `search` unit through openmates-browser-bindings).
//! Mirrors searchService.ts: the `messageIndex` BoundedCache (newest-first
//! entries, byte/chat budget, LRU) and `searchMessagesInChat` (per-chat caps).
//! The page builds entries from decrypted messages once per chat and transfers
//! them here; it keeps no copy. Vectors: web_search_chats_ts_vectors.json.
//! Spec: sdk.client.thin-platform-boundary.
//! spec: sdk.client.thin-platform-boundary
use crate::web_search::{context_bounds, plan_snippet, plan_window, utf16_len, utf16_window};
use std::cmp::Ordering;
use std::collections::HashMap;

/// Snippets per chat (`MAX_SNIPPETS_PER_CHAT` in searchService.ts).
pub const MAX_SNIPPETS_PER_CHAT: usize = 5;
/// Snippets from any one message, so an embed-heavy message cannot fill a chat's slots.
pub const MAX_SNIPPETS_PER_MESSAGE: usize = 2;
/// Distinct titled embed results per chat when embeds are requested.
pub const MAX_EMBED_RESULTS_PER_CHAT: usize = 6;
/// Retained-bytes budget of the index (`MAX_SEARCH_INDEX_BYTES`).
pub const MAX_INDEX_BYTES: usize = 32 * 1024 * 1024;
/// Chats held at most (`MAX_SEARCH_INDEX_CHATS`).
pub const MAX_INDEX_CHATS: usize = 500;
/// Optional entry fields on the wire (`EntryMeta` field order, searchUnitProtocol.ts `META_FIELDS`).
pub const META_FIELDS: usize = 9;
/// Approximate fixed cost of one stored entry (struct, boxes, allocator slack).
const ENTRY_OVERHEAD_BYTES: usize = 64;

/// Malformed ingest columns; the unit refuses the request with `code()`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SearchWireError {
    /// Column lengths disagree, a mask names a missing value, or values are left over.
    Protocol,
}

impl SearchWireError {
    /// Stable refusal code shared with the web unit protocol.
    pub fn code(self) -> &'static str {
        match self {
            SearchWireError::Protocol => "protocol",
        }
    }
}

/// Optional embed fields of an entry (searchService.ts `SearchEntries` item).
/// `source_label` is set exactly for embed entries; `None` mirrors `undefined`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct EntryMeta {
    /// `embedSourceLabel`.
    pub source_label: Option<String>,
    /// `embedId`.
    pub embed_id: Option<String>,
    /// `embedType`.
    pub embed_type: Option<String>,
    /// `embedTitle`.
    pub title: Option<String>,
    /// `embedSubtitle`.
    pub subtitle: Option<String>,
    /// `embedAppId`.
    pub app_id: Option<String>,
    /// `embedSkillId`.
    pub skill_id: Option<String>,
    /// `embedFocusId`.
    pub focus_id: Option<String>,
    /// `embedFocusModeName`.
    pub focus_mode_name: Option<String>,
}

impl EntryMeta {
    /// Builds the fields from `mask` (bit `i` = field `i` present, wire order) and
    /// takes each present value from `values` in order.
    ///
    /// # Errors
    /// `Protocol` when `values` runs out or the mask has bits past the last field.
    pub fn from_wire(
        mask: u16,
        values: &mut impl Iterator<Item = String>,
    ) -> Result<Self, SearchWireError> {
        if mask >> META_FIELDS != 0 {
            return Err(SearchWireError::Protocol);
        }
        let mut slot = |bit: usize| -> Result<Option<String>, SearchWireError> {
            if mask & (1 << bit) == 0 {
                return Ok(None);
            }
            values.next().map(Some).ok_or(SearchWireError::Protocol)
        };
        Ok(EntryMeta {
            source_label: slot(0)?,
            embed_id: slot(1)?,
            embed_type: slot(2)?,
            title: slot(3)?,
            subtitle: slot(4)?,
            app_id: slot(5)?,
            skill_id: slot(6)?,
            focus_id: slot(7)?,
            focus_mode_name: slot(8)?,
        })
    }

    fn fields(&self) -> [&Option<String>; META_FIELDS] {
        [
            &self.source_label,
            &self.embed_id,
            &self.embed_type,
            &self.title,
            &self.subtitle,
            &self.app_id,
            &self.skill_id,
            &self.focus_id,
            &self.focus_mode_name,
        ]
    }

    fn bytes(&self) -> usize {
        self.fields()
            .iter()
            .map(|field| field.as_ref().map_or(0, String::len))
            .sum()
    }
}

/// One entry as the page built it (without `normalizedContent`; the index lowercases).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct IngestEntry {
    /// Parent message id (snippet click target).
    pub message_id: String,
    /// Searchable plaintext (markdown-stripped message text or extracted embed text).
    pub content: String,
    /// Message timestamp; entries are ordered newest first.
    pub created_at: f64,
    /// Embed fields; `None` for message text.
    pub meta: Option<EntryMeta>,
}

/// Decodes one chat's ingest columns (searchUnitProtocol.ts `SearchIngestChat`).
///
/// # Errors
/// `Protocol` when the columns disagree in length, a meta row points past the
/// entries or is repeated, or meta values do not match the masks exactly.
pub fn decode_ingest(
    message_ids: Vec<String>,
    contents: Vec<String>,
    created_at: &[f64],
    meta_entries: &[u32],
    meta_masks: &[u16],
    meta_values: Vec<String>,
) -> Result<Vec<IngestEntry>, SearchWireError> {
    let length = message_ids.len();
    if contents.len() != length
        || created_at.len() != length
        || meta_entries.len() != meta_masks.len()
    {
        return Err(SearchWireError::Protocol);
    }
    let mut entries: Vec<IngestEntry> = message_ids
        .into_iter()
        .zip(contents)
        .zip(created_at)
        .map(|((message_id, content), &created_at)| IngestEntry {
            message_id,
            content,
            created_at,
            meta: None,
        })
        .collect();
    let mut values = meta_values.into_iter();
    for (&row, &mask) in meta_entries.iter().zip(meta_masks) {
        let entry = entries
            .get_mut(row as usize)
            .ok_or(SearchWireError::Protocol)?;
        if entry.meta.is_some() {
            return Err(SearchWireError::Protocol);
        }
        entry.meta = Some(EntryMeta::from_wire(mask, &mut values)?);
    }
    if values.next().is_some() {
        return Err(SearchWireError::Protocol);
    }
    Ok(entries)
}

struct ChatEntry {
    message: u32,
    created_at: f64,
    text: Box<str>,
    /// Lowercased text, kept only for non-ASCII text: ASCII text is matched
    /// case-insensitively in place, which halves the index for typical chats.
    lower: Option<Box<str>>,
    lower_ascii: bool,
    /// Interned embed id (0 = none) when the entry is an embed with a non-empty title.
    titled_embed: u32,
    meta: Option<Box<EntryMeta>>,
}

struct Chat {
    entries: Vec<ChatEntry>,
    message_ids: Vec<Box<str>>,
    bytes: usize,
    used: u64,
}

/// Read view of one stored entry.
#[derive(Debug, Clone, Copy)]
pub struct EntryView<'a> {
    /// Parent message id.
    pub message_id: &'a str,
    /// Original entry text.
    pub text: &'a str,
    /// Message timestamp.
    pub created_at: f64,
    /// Embed fields (`None` for message text).
    pub meta: Option<&'a EntryMeta>,
}

/// `buildSnippet` result as a slice plan in UTF-16 units of the entry's original
/// text: snippet = optional `"... "` + `content[from..to]` + optional `" ..."`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SnippetSlice {
    /// First UTF-16 unit of the body.
    pub from: usize,
    /// End (exclusive) UTF-16 unit of the body.
    pub to: usize,
    /// The snippet starts with `"... "`.
    pub front_ellipsis: bool,
    /// The snippet ends with `" ..."`.
    pub back_ellipsis: bool,
    /// Match offset inside the finished snippet (`snippetMatchStart`).
    pub match_start: usize,
}

impl SnippetSlice {
    /// The finished snippet as UTF-16 units of `text` (exact, lone surrogates included).
    pub fn units(&self, text: &str) -> Vec<u16> {
        let mut units = Vec::with_capacity(self.to.saturating_sub(self.from) + 8);
        if self.front_ellipsis {
            units.extend("... ".encode_utf16());
        }
        if text.is_ascii() {
            let end = self.to.min(text.len());
            units.extend(
                text.as_bytes()[self.from.min(end)..end]
                    .iter()
                    .map(|b| u16::from(*b)),
            );
        } else {
            units.extend(utf16_window(text, self.from, self.to));
        }
        if self.back_ellipsis {
            units.extend(" ...".encode_utf16());
        }
        units
    }
}

/// One snippet hit of `searchMessagesInChat`.
#[derive(Debug, Clone, Copy)]
pub struct SnippetHit<'a> {
    /// Matched entry.
    pub entry: EntryView<'a>,
    /// Snippet plan over `entry.text`.
    pub slice: SnippetSlice,
}

/// `searchMessagesInChat` result for one chat: snippet hits then titled embed hits, in entry order.
#[derive(Debug, Clone, Default)]
pub struct ChatHits<'a> {
    /// At most `MAX_SNIPPETS_PER_CHAT`, at most `MAX_SNIPPETS_PER_MESSAGE` per message.
    pub snippets: Vec<SnippetHit<'a>>,
    /// Distinct titled embeds, at most `MAX_EMBED_RESULTS_PER_CHAT` (only when requested).
    pub embeds: Vec<EntryView<'a>>,
}

/// A query lowercased once for every chat of a search.
#[derive(Debug, Clone)]
pub struct LoweredQuery {
    lower: String,
    ascii: bool,
    /// UTF-16 length of the original (not lowercased) query: `matchLength`.
    pub length: usize,
}

impl LoweredQuery {
    /// Lowercases `query` (`String.prototype.toLowerCase` and Rust agree, final sigma included).
    pub fn new(query: &str) -> Self {
        let lower = query.to_lowercase();
        let ascii = lower.is_ascii();
        LoweredQuery {
            lower,
            ascii,
            length: utf16_len(query),
        }
    }

    /// The lowercased query.
    pub fn lower(&self) -> &str {
        &self.lower
    }

    /// True for an empty query, which matches nothing (the page never sends one).
    pub fn is_empty(&self) -> bool {
        self.lower.is_empty()
    }
}

/// Per-chat search entries addressed by page-assigned `u32` handles, bounded
/// like the page's `BoundedCache` (bytes and chats, least recently used first).
/// Evicted handles are reported to the caller so the page re-indexes them from
/// the source on demand instead of believing them indexed.
pub struct ChatSearchIndex {
    chats: HashMap<u32, Chat>,
    bytes: usize,
    clock: u64,
    max_bytes: usize,
    max_chats: usize,
}

impl Default for ChatSearchIndex {
    fn default() -> Self {
        Self::with_limits(MAX_INDEX_BYTES, MAX_INDEX_CHATS)
    }
}

impl ChatSearchIndex {
    /// Empty index with explicit budgets (tests use small ones).
    pub fn with_limits(max_bytes: usize, max_chats: usize) -> Self {
        ChatSearchIndex {
            chats: HashMap::new(),
            bytes: 0,
            clock: 0,
            max_bytes,
            max_chats,
        }
    }

    /// Replaces `handle`'s entries with `entries`, ordered newest first (ties:
    /// message text before embeds; stable like `compareSearchEntriesNewestFirst`).
    /// Returns the handles evicted to stay within budget, possibly `handle` itself
    /// when one chat alone exceeds it (the page's cache drops it the same way).
    pub fn ingest_chat(&mut self, handle: u32, entries: Vec<IngestEntry>) -> Vec<u32> {
        self.remove_chat(handle);
        let mut messages: HashMap<String, u32> = HashMap::new();
        let mut embeds: HashMap<String, u32> = HashMap::new();
        let mut bytes = 0usize;
        let mut stored: Vec<ChatEntry> = Vec::with_capacity(entries.len());
        for entry in entries {
            let next = messages.len() as u32;
            let message = *messages.entry(entry.message_id).or_insert(next);
            let titled_embed = match &entry.meta {
                Some(EntryMeta {
                    embed_id: Some(id),
                    title: Some(title),
                    ..
                }) if !id.is_empty() && !title.is_empty() => {
                    let next = embeds.len() as u32 + 1;
                    *embeds.entry(id.clone()).or_insert(next)
                }
                _ => 0,
            };
            let lower = if entry.content.is_ascii() {
                None
            } else {
                Some(entry.content.to_lowercase().into_boxed_str())
            };
            bytes += ENTRY_OVERHEAD_BYTES
                + entry.content.len()
                + lower.as_ref().map_or(0, |lower| lower.len())
                + entry.meta.as_ref().map_or(0, EntryMeta::bytes);
            stored.push(ChatEntry {
                message,
                created_at: entry.created_at,
                lower_ascii: lower.as_ref().is_none_or(|lower| lower.is_ascii()),
                lower,
                text: entry.content.into_boxed_str(),
                titled_embed,
                meta: entry.meta.map(Box::new),
            });
        }
        stored.sort_by(newest_first);
        let mut message_ids = vec![Box::<str>::default(); messages.len()];
        for (id, index) in messages {
            bytes += id.len();
            message_ids[index as usize] = id.into_boxed_str();
        }
        self.clock += 1;
        self.bytes += bytes;
        self.chats.insert(
            handle,
            Chat {
                entries: stored,
                message_ids,
                bytes,
                used: self.clock,
            },
        );
        self.trim()
    }

    /// Marks `handles` as used now (the page's cache refreshes recency on every read).
    pub fn touch(&mut self, handles: &[u32]) {
        for handle in handles {
            if let Some(chat) = self.chats.get_mut(handle) {
                self.clock += 1;
                chat.used = self.clock;
            }
        }
    }

    fn trim(&mut self) -> Vec<u32> {
        let mut evicted = Vec::new();
        while self.bytes > self.max_bytes || self.chats.len() > self.max_chats {
            let Some((&oldest, _)) = self.chats.iter().min_by_key(|(_, chat)| chat.used) else {
                break;
            };
            self.remove_chat(oldest);
            evicted.push(oldest);
        }
        evicted
    }

    /// Forgets `handle` (the page invalidated that chat).
    pub fn remove_chat(&mut self, handle: u32) {
        if let Some(chat) = self.chats.remove(&handle) {
            self.bytes -= chat.bytes;
        }
    }

    /// Forgets every chat (logout).
    pub fn clear(&mut self) {
        self.chats.clear();
        self.bytes = 0;
    }

    /// Number of chats currently held.
    pub fn chat_count(&self) -> usize {
        self.chats.len()
    }

    /// Entries held for `handle` (0 when unknown).
    pub fn entry_count(&self, handle: u32) -> usize {
        self.chats.get(&handle).map_or(0, |chat| chat.entries.len())
    }

    /// Estimated retained bytes (the budget measure).
    pub fn retained_bytes(&self) -> usize {
        self.bytes
    }

    /// `searchMessagesInChat` over `handle`'s entries; `None` for an unknown handle
    /// (the page searches nothing for a chat it has not indexed).
    pub fn chat_hits(
        &self,
        handle: u32,
        query: &LoweredQuery,
        include_embeds: bool,
    ) -> Option<ChatHits<'_>> {
        let chat = self.chats.get(&handle)?;
        let mut hits = ChatHits::default();
        if query.is_empty() {
            return Some(hits);
        }
        let mut seen_embeds: Vec<u32> = Vec::new();
        let mut per_message: HashMap<u32, usize> = HashMap::new();
        for entry in &chat.entries {
            if hits.snippets.len() >= MAX_SNIPPETS_PER_CHAT
                && (!include_embeds || hits.embeds.len() >= MAX_EMBED_RESULTS_PER_CHAT)
            {
                break;
            }
            let Some(start) = find_entry(entry, query) else {
                continue;
            };
            let view = EntryView {
                message_id: &chat.message_ids[entry.message as usize],
                text: &entry.text,
                created_at: entry.created_at,
                meta: entry.meta.as_deref(),
            };
            if include_embeds
                && entry.titled_embed != 0
                && hits.embeds.len() < MAX_EMBED_RESULTS_PER_CHAT
                && !seen_embeds.contains(&entry.titled_embed)
            {
                hits.embeds.push(view);
                seen_embeds.push(entry.titled_embed);
            }
            if hits.snippets.len() >= MAX_SNIPPETS_PER_CHAT {
                continue;
            }
            let count = per_message.entry(entry.message).or_insert(0);
            if *count >= MAX_SNIPPETS_PER_MESSAGE {
                continue;
            }
            *count += 1;
            let slice = snippet_slice(&entry.text, entry.lower.is_none(), start, query.length);
            hits.snippets.push(SnippetHit { entry: view, slice });
        }
        Some(hits)
    }
}

fn newest_first(a: &ChatEntry, b: &ChatEntry) -> Ordering {
    let is_embed = |entry: &ChatEntry| {
        entry
            .meta
            .as_ref()
            .is_some_and(|meta| meta.source_label.is_some())
    };
    b.created_at
        .partial_cmp(&a.created_at)
        .unwrap_or(Ordering::Equal)
        .then_with(|| is_embed(a).cmp(&is_embed(b)))
}

/// UTF-16 offset of the first match in the lowercased entry text
/// (`normalizedContent.indexOf(lowerQuery)`).
fn find_entry(entry: &ChatEntry, query: &LoweredQuery) -> Option<usize> {
    match &entry.lower {
        // ASCII text lowercases byte for byte, so its offsets are UTF-16 offsets, and
        // a lowercased query with non-ASCII characters cannot occur in it.
        None if query.ascii => {
            find_ascii_case_insensitive(entry.text.as_bytes(), query.lower.as_bytes())
        }
        None => None,
        Some(lower) => {
            let byte = lower.find(query.lower.as_str())?;
            Some(if entry.lower_ascii {
                byte
            } else {
                utf16_len(&lower[..byte])
            })
        }
    }
}

/// First `i` where `haystack[i..]` lowercased starts with `needle` (already lowercase ASCII).
fn find_ascii_case_insensitive(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    let (&first, rest) = needle.split_first()?;
    if haystack.len() < needle.len() {
        return None;
    }
    let last = haystack.len() - needle.len();
    let mut at = 0;
    while at <= last {
        let offset = haystack[at..=last]
            .iter()
            .position(|byte| byte.to_ascii_lowercase() == first)?;
        at += offset;
        if haystack[at + 1..at + needle.len()]
            .iter()
            .zip(rest)
            .all(|(byte, want)| byte.to_ascii_lowercase() == *want)
        {
            return Some(at);
        }
        at += 1;
    }
    None
}

/// `buildSnippet(content, match_start, match_length)` as a slice plan; `ascii`
/// lets ASCII content plan over bytes (one byte is one UTF-16 unit). Offsets past
/// the text (lowercasing can lengthen it) clamp like `String.prototype.slice`.
pub fn snippet_slice(
    content: &str,
    ascii: bool,
    match_start: usize,
    match_length: usize,
) -> SnippetSlice {
    if ascii {
        let plan = plan_snippet(content.as_bytes(), b' ', match_start, match_length);
        return SnippetSlice {
            from: plan.from,
            to: plan.to,
            front_ellipsis: plan.front_ellipsis,
            back_ellipsis: plan.back_ellipsis,
            match_start: plan.match_start,
        };
    }
    let target = match_start + match_length + crate::web_search::SNIPPET_CONTEXT_CHARS;
    let window_start = match_start.saturating_sub(crate::web_search::SNIPPET_CONTEXT_CHARS);
    let window = utf16_window(content, window_start, target + 1);
    let total = if window.is_empty() {
        utf16_len(content)
    } else {
        window_start + window.len()
    };
    let (context_start, context_end) = context_bounds(total, match_start, match_length);
    let base = context_start.min(context_end);
    let window = if base == context_start {
        window
    } else {
        Vec::new()
    };
    let plan = plan_window(&window, b' ' as u16, base, total, match_start, match_length);
    SnippetSlice {
        from: plan.from,
        to: plan.to,
        front_ellipsis: plan.front_ellipsis,
        back_ellipsis: plan.back_ellipsis,
        match_start: plan.match_start,
    }
}
