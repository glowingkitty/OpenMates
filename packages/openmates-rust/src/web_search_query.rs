//! One complete client search over the worker-resident chat index plus the
//! page's per-chat metadata and the settings/app catalogs (shared core; served
//! by the shared Rust core Worker's `search` unit). Mirrors searchService.ts
//! `search`: title ranges, message/metadata snippets, focus-mode activity,
//! chat ranking, embed ranking/dedupe/cap and catalog access filters.
//! Vectors: web_search_query_ts_vectors.json. Spec: sdk.client.thin-platform-boundary.
use crate::web_search::{lowered_ranges, utf16_len, MatchRange};
use crate::web_search_chats::{
    snippet_slice, ChatSearchIndex, EntryMeta, LoweredQuery, SearchWireError,
};
use std::cmp::Ordering;

/// Embed results across all chats (`MAX_EMBED_RESULTS_TOTAL`).
pub const MAX_EMBED_RESULTS_TOTAL: usize = 6;
/// Rows sentinel for an absent (`undefined`) text.
pub const NO_TEXT: u32 = u32::MAX;
/// `focusActive` row values.
pub const FOCUS_INACTIVE: u32 = 0;
/// The focus-mode activation embed names the chat's active focus mode.
pub const FOCUS_ACTIVE: u32 = 1;
/// Not a focus-mode activation snippet (`embedFocusIsActive: undefined`).
pub const FOCUS_NONE: u32 = 2;
/// Words per message snippet row (layout in `EncodedOutcome`).
pub const MESSAGE_SNIPPET_WORDS: usize = 12;
/// Words per metadata snippet row.
pub const METADATA_SNIPPET_WORDS: usize = 4;
/// Words per embed row.
pub const EMBED_WORDS: usize = 7;
/// Query flags (`SearchQuery::from_wire` `flags`).
pub const FLAG_INCLUDE_EMBEDS: u32 = 1;
/// The caller is signed in (authenticated settings are visible).
pub const FLAG_AUTHENTICATED: u32 = 2;
/// The caller is an admin (admin settings are visible).
pub const FLAG_ADMIN: u32 = 4;

/// Page data for one searchable chat, in the page's chat order.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct QueryChat {
    /// Index handle (0 = no message search: metadata-only or not indexed yet).
    pub handle: u32,
    /// Decrypted title (`metadata?.title || chat.title || null`).
    pub title: Option<String>,
    /// Active focus mode id of the chat.
    pub active_focus_id: Option<String>,
    /// Summary to search (`null` for public chats).
    pub summary: Option<String>,
    /// Tags to search.
    pub tags: Option<Vec<String>>,
    /// Unsent draft preview to search.
    pub draft: Option<String>,
    /// `last_edited_overall_timestamp`, the recency tie-breaker.
    pub last_edited: f64,
}

/// Who may see a settings catalog entry (`SettingsCatalogEntry.access`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CatalogAccess {
    /// Everyone (`public` or unset).
    Public,
    /// Signed-in users.
    Authenticated,
    /// Admins.
    Admin,
}

/// Which result list a catalog entry belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CatalogKind {
    /// `searchSettings` (access filtered).
    Settings,
    /// `searchAppCatalog` (never access filtered).
    App,
}

/// One settings or app catalog entry with its translated label.
#[derive(Debug, Clone, PartialEq)]
pub struct CatalogEntry {
    /// Result list.
    pub kind: CatalogKind,
    /// Visibility.
    pub access: CatalogAccess,
    /// Translated label.
    pub label: String,
    /// Keyword synonyms.
    pub keywords: Vec<String>,
}

/// One search request (the page trims the query and never sends an empty one).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SearchQuery {
    /// Trimmed query text.
    pub query: String,
    /// Collect embed results (composer suggestions).
    pub include_embeds: bool,
    /// Caller is signed in.
    pub authenticated: bool,
    /// Caller is an admin.
    pub admin: bool,
    /// Searchable chats in the page's order (visible then hidden).
    pub chats: Vec<QueryChat>,
    /// Settings entries followed by app catalog entries.
    pub catalog: Vec<CatalogEntry>,
}

/// Wire columns of a search request (searchUnitProtocol.ts `SearchQueryRequest`).
pub struct QueryColumns<'a> {
    /// Trimmed query.
    pub query: &'a str,
    /// `FLAG_*` bits.
    pub flags: u32,
    /// One handle per chat.
    pub handles: &'a [u32],
    /// Per chat: bit 0 title, 1 focus, 2 summary, 3 draft, 4 tags present.
    pub chat_masks: &'a [u8],
    /// Present chat values in mask order, tags last.
    pub chat_values: Vec<String>,
    /// Tag count per chat (0 when tags are absent).
    pub tag_counts: &'a [u32],
    /// `last_edited_overall_timestamp` per chat.
    pub last_edited: &'a [f64],
    /// Per entry: bits 0-1 access (0 public, 1 authenticated, 2 admin), bit 2 app entry.
    pub catalog_flags: &'a [u8],
    /// Translated label per entry.
    pub catalog_labels: Vec<String>,
    /// Keyword count per entry.
    pub catalog_keyword_counts: &'a [u32],
    /// Keywords of all entries in order.
    pub catalog_keywords: Vec<String>,
}

impl SearchQuery {
    /// Decodes the request columns.
    ///
    /// # Errors
    /// `Protocol` when column lengths disagree, a mask or flag has unknown bits,
    /// or values do not match the masks and counts exactly.
    pub fn from_wire(columns: QueryColumns<'_>) -> Result<Self, SearchWireError> {
        let count = columns.handles.len();
        let catalog_count = columns.catalog_flags.len();
        if columns.chat_masks.len() != count
            || columns.tag_counts.len() != count
            || columns.last_edited.len() != count
            || columns.catalog_labels.len() != catalog_count
            || columns.catalog_keyword_counts.len() != catalog_count
            || columns.flags & !(FLAG_INCLUDE_EMBEDS | FLAG_AUTHENTICATED | FLAG_ADMIN) != 0
        {
            return Err(SearchWireError::Protocol);
        }
        let mut values = columns.chat_values.into_iter();
        let mut chats = Vec::with_capacity(count);
        for index in 0..count {
            let mask = columns.chat_masks[index];
            if mask >> 5 != 0 || (mask & 16 == 0 && columns.tag_counts[index] != 0) {
                return Err(SearchWireError::Protocol);
            }
            let mut take = |bit: u8| -> Result<Option<String>, SearchWireError> {
                if mask & bit == 0 {
                    return Ok(None);
                }
                values.next().map(Some).ok_or(SearchWireError::Protocol)
            };
            let title = take(1)?;
            let active_focus_id = take(2)?;
            let summary = take(4)?;
            let draft = take(8)?;
            let tags = if mask & 16 == 0 {
                None
            } else {
                let tags: Vec<String> = values
                    .by_ref()
                    .take(columns.tag_counts[index] as usize)
                    .collect();
                if tags.len() != columns.tag_counts[index] as usize {
                    return Err(SearchWireError::Protocol);
                }
                Some(tags)
            };
            chats.push(QueryChat {
                handle: columns.handles[index],
                title,
                active_focus_id,
                summary,
                tags,
                draft,
                last_edited: columns.last_edited[index],
            });
        }
        if values.next().is_some() {
            return Err(SearchWireError::Protocol);
        }
        let mut keywords = columns.catalog_keywords.into_iter();
        let mut catalog = Vec::with_capacity(catalog_count);
        for (index, label) in columns.catalog_labels.into_iter().enumerate() {
            let flags = columns.catalog_flags[index];
            let access = match flags & 3 {
                0 => CatalogAccess::Public,
                1 => CatalogAccess::Authenticated,
                2 => CatalogAccess::Admin,
                _ => return Err(SearchWireError::Protocol),
            };
            if flags >> 3 != 0 {
                return Err(SearchWireError::Protocol);
            }
            let kind = if flags & 4 == 0 {
                CatalogKind::Settings
            } else {
                CatalogKind::App
            };
            let wanted = columns.catalog_keyword_counts[index] as usize;
            let entry_keywords: Vec<String> = keywords.by_ref().take(wanted).collect();
            if entry_keywords.len() != wanted {
                return Err(SearchWireError::Protocol);
            }
            catalog.push(CatalogEntry {
                kind,
                access,
                label,
                keywords: entry_keywords,
            });
        }
        if keywords.next().is_some() {
            return Err(SearchWireError::Protocol);
        }
        Ok(SearchQuery {
            query: columns.query.to_string(),
            include_embeds: columns.flags & FLAG_INCLUDE_EMBEDS != 0,
            authenticated: columns.flags & FLAG_AUTHENTICATED != 0,
            admin: columns.flags & FLAG_ADMIN != 0,
            chats,
            catalog,
        })
    }

    /// Handles of the chats that have an index (for LRU recency).
    pub fn handles(&self) -> Vec<u32> {
        self.chats
            .iter()
            .map(|chat| chat.handle)
            .filter(|handle| *handle != 0)
            .collect()
    }
}

/// A message snippet (`MessageMatchSnippet` without `chatId`, which the page adds).
#[derive(Debug, Clone, PartialEq)]
pub struct MessageSnippet<'a> {
    /// Snippet text as UTF-16 units (exact `buildSnippet` output).
    pub snippet: Vec<u16>,
    /// `matchStart`.
    pub match_start: usize,
    /// `matchLength` (UTF-16 length of the query).
    pub match_length: usize,
    /// Parent message.
    pub message_id: &'a str,
    /// Embed fields of the matched entry.
    pub meta: Option<&'a EntryMeta>,
    /// `embedFocusIsActive`.
    pub focus_active: Option<bool>,
}

/// Where a metadata snippet matched.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetadataSource {
    /// Chat summary.
    Summary = 0,
    /// One tag.
    Tags = 1,
    /// Unsent draft preview.
    Draft = 2,
}

/// A metadata snippet (`MetadataMatchSnippet` without `chatId`).
#[derive(Debug, Clone, PartialEq)]
pub struct MetadataSnippet {
    /// Snippet text as UTF-16 units.
    pub snippet: Vec<u16>,
    /// `matchStart`.
    pub match_start: usize,
    /// `matchLength`.
    pub match_length: usize,
    /// `matchSource`.
    pub source: MetadataSource,
}

/// One matching chat, in final display order.
#[derive(Debug, Clone, PartialEq)]
pub struct ChatResult<'a> {
    /// Index of the chat in the request.
    pub position: usize,
    /// `titleMatchRanges` (title matched when non-empty).
    pub title_ranges: Vec<MatchRange>,
    /// `messageSnippets`.
    pub messages: Vec<MessageSnippet<'a>>,
    /// `metadataSnippets`.
    pub metadata: Vec<MetadataSnippet>,
}

/// One ranked embed result (`EmbedSearchResult` without `chatId`).
#[derive(Debug, Clone, PartialEq)]
pub struct EmbedResult<'a> {
    /// Index of the chat in the request.
    pub position: usize,
    /// `embedId`.
    pub embed_id: &'a str,
    /// `embedType || ''`.
    pub embed_type: &'a str,
    /// `messageId`.
    pub message_id: &'a str,
    /// `title`.
    pub title: &'a str,
    /// `embedSubtitle || embedSourceLabel || 'Embed'`.
    pub subtitle: &'a str,
    /// `appId`.
    pub app_id: Option<&'a str>,
    /// `createdAt`.
    pub created_at: f64,
}

/// Complete result of `run_search`.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SearchOutcome<'a> {
    /// Matching chats: title matches, then chats with message snippets, then by recency.
    pub chats: Vec<ChatResult<'a>>,
    /// Embeds ranked title-match first then newest, deduplicated, capped.
    pub embeds: Vec<EmbedResult<'a>>,
    /// Matching settings entries (catalog indices, in catalog order).
    pub settings: Vec<usize>,
    /// Matching app catalog entries (catalog indices, in catalog order).
    pub apps: Vec<usize>,
}

/// Runs one search. Chats are visited in request order; ties in every sort keep
/// that order (JS sort is stable), so results are deterministic.
pub fn run_search<'a>(index: &'a ChatSearchIndex, request: &SearchQuery) -> SearchOutcome<'a> {
    let query = LoweredQuery::new(&request.query);
    let mut outcome = SearchOutcome::default();
    if query.is_empty() {
        return outcome;
    }
    let mut embeds: Vec<EmbedResult<'a>> = Vec::new();
    for (position, chat) in request.chats.iter().enumerate() {
        let title_ranges = match &chat.title {
            Some(title) if !title.is_empty() => {
                lowered_ranges(&title.to_lowercase(), query.lower())
            }
            _ => Vec::new(),
        };
        let mut messages = Vec::new();
        if chat.handle != 0 {
            if let Some(hits) = index.chat_hits(chat.handle, &query, request.include_embeds) {
                for hit in hits.snippets {
                    let meta = hit.entry.meta;
                    let focus_active =
                        meta.and_then(|meta| match (&meta.embed_type, &meta.focus_id) {
                            (Some(kind), Some(focus))
                                if kind == "focus-mode-activation" && !focus.is_empty() =>
                            {
                                Some(chat.active_focus_id.as_deref() == Some(focus.as_str()))
                            }
                            _ => None,
                        });
                    messages.push(MessageSnippet {
                        snippet: hit.slice.units(hit.entry.text),
                        match_start: hit.slice.match_start,
                        match_length: query.length,
                        message_id: hit.entry.message_id,
                        meta,
                        focus_active,
                    });
                }
                for entry in hits.embeds {
                    let Some(meta) = entry.meta else { continue };
                    let (Some(embed_id), Some(title)) =
                        (meta.embed_id.as_deref(), meta.title.as_deref())
                    else {
                        continue;
                    };
                    let subtitle = [meta.subtitle.as_deref(), meta.source_label.as_deref()]
                        .into_iter()
                        .flatten()
                        .find(|text| !text.is_empty())
                        .unwrap_or("Embed");
                    embeds.push(EmbedResult {
                        position,
                        embed_id,
                        embed_type: meta.embed_type.as_deref().unwrap_or(""),
                        message_id: entry.message_id,
                        title,
                        subtitle,
                        app_id: meta.app_id.as_deref(),
                        created_at: entry.created_at,
                    });
                }
            }
        }
        let metadata = metadata_snippets(chat, &query);
        if !title_ranges.is_empty() || !messages.is_empty() || !metadata.is_empty() {
            outcome.chats.push(ChatResult {
                position,
                title_ranges,
                messages,
                metadata,
            });
        }
    }
    outcome.chats.sort_by(|a, b| {
        let (a_title, b_title) = (!a.title_ranges.is_empty(), !b.title_ranges.is_empty());
        let (a_messages, b_messages) = (!a.messages.is_empty(), !b.messages.is_empty());
        b_title
            .cmp(&a_title)
            .then(b_messages.cmp(&a_messages))
            .then_with(|| {
                let (a_time, b_time) = (
                    request.chats[a.position].last_edited,
                    request.chats[b.position].last_edited,
                );
                b_time.partial_cmp(&a_time).unwrap_or(Ordering::Equal)
            })
    });
    let title_hit = |embed: &EmbedResult<'_>| embed.title.to_lowercase().contains(query.lower());
    embeds.sort_by(|a, b| {
        title_hit(b).cmp(&title_hit(a)).then_with(|| {
            b.created_at
                .partial_cmp(&a.created_at)
                .unwrap_or(Ordering::Equal)
        })
    });
    let mut seen: Vec<&str> = Vec::new();
    for embed in embeds {
        if seen.contains(&embed.embed_id) {
            continue;
        }
        seen.push(embed.embed_id);
        if outcome.embeds.len() < MAX_EMBED_RESULTS_TOTAL {
            outcome.embeds.push(embed);
        }
    }
    for (at, entry) in request.catalog.iter().enumerate() {
        if entry.kind == CatalogKind::Settings
            && (entry.access == CatalogAccess::Admin && !request.admin
                || entry.access == CatalogAccess::Authenticated && !request.authenticated)
        {
            continue;
        }
        let matched = entry.label.to_lowercase().contains(query.lower())
            || entry
                .keywords
                .iter()
                .any(|keyword| keyword.to_lowercase().contains(query.lower()));
        if matched {
            match entry.kind {
                CatalogKind::Settings => outcome.settings.push(at),
                CatalogKind::App => outcome.apps.push(at),
            }
        }
    }
    outcome
}

/// `searchMetadataInline`: summary, first matching tag, draft preview.
fn metadata_snippets(chat: &QueryChat, query: &LoweredQuery) -> Vec<MetadataSnippet> {
    let mut snippets = Vec::new();
    let around = |text: &str, source: MetadataSource| -> Option<MetadataSnippet> {
        let start = lowered_start(text, query)?;
        let slice = snippet_slice(text, text.is_ascii(), start, query.length);
        Some(MetadataSnippet {
            snippet: slice.units(text),
            match_start: slice.match_start,
            match_length: query.length,
            source,
        })
    };
    if let Some(summary) = chat.summary.as_deref().filter(|text| !text.is_empty()) {
        snippets.extend(around(summary, MetadataSource::Summary));
    }
    if let Some(tags) = &chat.tags {
        for tag in tags {
            if let Some(start) = lowered_start(tag, query) {
                snippets.push(MetadataSnippet {
                    snippet: tag.encode_utf16().collect(),
                    match_start: start,
                    match_length: query.length,
                    source: MetadataSource::Tags,
                });
                break;
            }
        }
    }
    if let Some(draft) = chat.draft.as_deref().filter(|text| !text.is_empty()) {
        snippets.extend(around(draft, MetadataSource::Draft));
    }
    snippets
}

/// `text.toLowerCase().indexOf(lowerQuery)` in UTF-16 units of the lowercased text.
fn lowered_start(text: &str, query: &LoweredQuery) -> Option<usize> {
    let lower = text.to_lowercase();
    let byte = lower.find(query.lower())?;
    Some(utf16_len(&lower[..byte]))
}

/// A text cell of the encoded result.
#[derive(Debug, Clone, PartialEq)]
pub enum Text<'a> {
    /// Borrowed from the index or request.
    Str(&'a str),
    /// Exact UTF-16 units (snippets may end in half a surrogate pair, like JS `slice`).
    Units(Vec<u16>),
}

/// Flat wire form of a `SearchOutcome` (searchUnitProtocol.ts `SearchQueryReply`).
///
/// `rows` (u32; text cells index `texts`, `NO_TEXT` = undefined):
/// - header `[chatCount, embedCount, settingsCount, appCount]`;
/// - per chat `[position, rangeCount, messageCount, metadataCount]`, then
///   `[start, length]` per title range, then per message snippet `[snippet,
///   matchStart, matchLength, messageId, sourceLabel, embedId, embedType, appId,
///   skillId, focusId, focusModeName, focusActive]`, then per metadata snippet
///   `[snippet, matchStart, matchLength, source]`;
/// - per embed `[position, embedId, embedType, messageId, title, subtitle, appId]`
///   with `createdAt` in `numbers` (same order);
/// - settings catalog indices, then app catalog indices.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct EncodedOutcome<'a> {
    /// Layout above.
    pub rows: Vec<u32>,
    /// Text cells.
    pub texts: Vec<Text<'a>>,
    /// Embed `createdAt` values.
    pub numbers: Vec<f64>,
}

impl<'a> SearchOutcome<'a> {
    /// Encodes the outcome for the page (no text crosses as JSON).
    pub fn encode(&self) -> EncodedOutcome<'a> {
        let mut out = EncodedOutcome::default();
        let text = |out: &mut EncodedOutcome<'a>, cell: Option<Text<'a>>| -> u32 {
            match cell {
                None => NO_TEXT,
                Some(cell) => {
                    out.texts.push(cell);
                    (out.texts.len() - 1) as u32
                }
            }
        };
        out.rows.extend(
            [
                self.chats.len(),
                self.embeds.len(),
                self.settings.len(),
                self.apps.len(),
            ]
            .map(|n| n as u32),
        );
        for chat in &self.chats {
            out.rows.extend(
                [
                    chat.position,
                    chat.title_ranges.len(),
                    chat.messages.len(),
                    chat.metadata.len(),
                ]
                .map(|n| n as u32),
            );
            for range in &chat.title_ranges {
                out.rows.extend([range.start as u32, range.length as u32]);
            }
            for snippet in &chat.messages {
                let field = |pick: fn(&EntryMeta) -> &Option<String>| -> Option<Text<'a>> {
                    snippet
                        .meta
                        .and_then(|meta| pick(meta).as_deref())
                        .map(Text::Str)
                };
                let cells = [
                    Some(Text::Units(snippet.snippet.clone())),
                    None,
                    None,
                    Some(Text::Str(snippet.message_id)),
                    field(|meta| &meta.source_label),
                    field(|meta| &meta.embed_id),
                    field(|meta| &meta.embed_type),
                    field(|meta| &meta.app_id),
                    field(|meta| &meta.skill_id),
                    field(|meta| &meta.focus_id),
                    field(|meta| &meta.focus_mode_name),
                ];
                let mut row = [0u32; MESSAGE_SNIPPET_WORDS];
                for (slot, cell) in cells.into_iter().enumerate() {
                    row[slot] = text(&mut out, cell);
                }
                row[1] = snippet.match_start as u32;
                row[2] = snippet.match_length as u32;
                row[11] = match snippet.focus_active {
                    None => FOCUS_NONE,
                    Some(true) => FOCUS_ACTIVE,
                    Some(false) => FOCUS_INACTIVE,
                };
                out.rows.extend(row);
            }
            for snippet in &chat.metadata {
                let cell = text(&mut out, Some(Text::Units(snippet.snippet.clone())));
                out.rows.extend([
                    cell,
                    snippet.match_start as u32,
                    snippet.match_length as u32,
                    snippet.source as u32,
                ]);
            }
        }
        for embed in &self.embeds {
            let cells = [
                Some(Text::Str(embed.embed_id)),
                Some(Text::Str(embed.embed_type)),
                Some(Text::Str(embed.message_id)),
                Some(Text::Str(embed.title)),
                Some(Text::Str(embed.subtitle)),
                embed.app_id.map(Text::Str),
            ];
            out.rows.push(embed.position as u32);
            for cell in cells {
                let at = text(&mut out, cell);
                out.rows.push(at);
            }
            out.numbers.push(embed.created_at);
        }
        out.rows.extend(self.settings.iter().map(|at| *at as u32));
        out.rows.extend(self.apps.iter().map(|at| *at as u32));
        out
    }
}
