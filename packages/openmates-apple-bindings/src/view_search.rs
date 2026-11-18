//! UniFFI export of the shared client search for the Apple shell: the same
//! core engine the web `search` Worker unit runs (`openmates_sdk::web_search_*`),
//! so ranking, UTF-16 match ranges and snippets are identical on both shells.
//! A `CoreChatSearchIndex` object owns the per-chat message index (the page
//! ingests each chat's decrypted entries once); `query` runs one complete
//! search over chats, settings and app catalogs, and optionally embeds. The
//! free functions cover in-chat message matching. Records only marshal; no
//! search logic lives here. Spec: `sdk.client.thin-platform-boundary`.
use std::collections::HashMap;
use std::sync::{Mutex, MutexGuard, PoisonError};

use openmates_sdk::web_search::{find_match_ranges, MatchRange};
use openmates_sdk::web_search_chats::{ChatSearchIndex, EntryMeta, IngestEntry};
use openmates_sdk::web_search_query::{
    run_search, CatalogAccess, CatalogEntry, CatalogKind, MetadataSource, QueryChat, SearchQuery,
};

/// One match range in UTF-16 code units of the lowercased text.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Record)]
pub struct SearchMatchRangeRecord {
    /// Start offset in UTF-16 units.
    pub start: u32,
    /// Length in UTF-16 units.
    pub length: u32,
}

/// Optional embed fields of an indexed entry (`nil` entry meta = message text).
#[derive(Debug, Clone, Default, PartialEq, Eq, uniffi::Record)]
pub struct SearchEntryMetaRecord {
    /// Label of the embed source (set for every embed entry).
    pub source_label: Option<String>,
    /// Embed id.
    pub embed_id: Option<String>,
    /// Embed type.
    pub embed_type: Option<String>,
    /// Embed title.
    pub title: Option<String>,
    /// Embed subtitle.
    pub subtitle: Option<String>,
    /// Owning app id.
    pub app_id: Option<String>,
    /// Skill id.
    pub skill_id: Option<String>,
    /// Focus mode id of a focus-mode activation.
    pub focus_id: Option<String>,
    /// Focus mode display name.
    pub focus_mode_name: Option<String>,
}

/// One searchable entry of a chat: message text or extracted embed text.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchIndexEntryRecord {
    /// Parent message id (snippet target).
    pub message_id: String,
    /// Searchable plaintext.
    pub content: String,
    /// Message timestamp (any monotonic unit; newest first).
    pub created_at: f64,
    /// Embed fields; `nil` for message text.
    pub meta: Option<SearchEntryMetaRecord>,
}

/// Visibility of a settings catalog entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Enum)]
pub enum SearchCatalogAccessRecord {
    /// Everyone.
    Public,
    /// Signed-in users.
    Authenticated,
    /// Admins.
    Admin,
}

/// Result list a catalog entry belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Enum)]
pub enum SearchCatalogKindRecord {
    /// Settings entry (filtered by access).
    Settings,
    /// App catalog entry (never filtered).
    App,
}

/// One settings or app catalog entry with its translated label.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct SearchCatalogEntryRecord {
    /// Result list.
    pub kind: SearchCatalogKindRecord,
    /// Visibility.
    pub access: SearchCatalogAccessRecord,
    /// Translated label.
    pub label: String,
    /// Keyword synonyms.
    pub keywords: Vec<String>,
}

/// Page data for one searchable chat, in display order.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchChatRecord {
    /// Chat id (also the index key; entries must be ingested under it).
    pub chat_id: String,
    /// Whether message entries are searched (ingested); `false` = metadata only.
    pub search_messages: bool,
    /// Decrypted title.
    pub title: Option<String>,
    /// Active focus mode id.
    pub active_focus_id: Option<String>,
    /// Summary to search (`nil` for public chats).
    pub summary: Option<String>,
    /// Tags to search.
    pub tags: Option<Vec<String>>,
    /// Unsent draft preview to search.
    pub draft: Option<String>,
    /// Last edited timestamp, the recency tie-breaker.
    pub last_edited: f64,
}

/// One complete search request (trimmed, non-empty query).
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchRequestRecord {
    /// Trimmed query.
    pub query: String,
    /// Collect embed results (composer suggestions).
    pub include_embeds: bool,
    /// Caller is signed in.
    pub authenticated: bool,
    /// Caller is an admin.
    pub admin: bool,
    /// Searchable chats in display order.
    pub chats: Vec<SearchChatRecord>,
    /// Settings entries followed by app entries.
    pub catalog: Vec<SearchCatalogEntryRecord>,
}

/// A message or embed snippet of a chat result.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchMessageSnippetRecord {
    /// Snippet text (a cut surrogate pair becomes U+FFFD).
    pub snippet: String,
    /// Match start in UTF-16 units of the snippet.
    pub match_start: u32,
    /// Match length in UTF-16 units.
    pub match_length: u32,
    /// Parent message id.
    pub message_id: String,
    /// Embed fields when the snippet came from an embed.
    pub meta: Option<SearchEntryMetaRecord>,
    /// Focus-mode activation: is it the chat's active focus mode? `nil` otherwise.
    pub focus_active: Option<bool>,
}

/// Where a metadata snippet matched.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Enum)]
pub enum SearchMetadataSourceRecord {
    /// Chat summary.
    Summary,
    /// One tag.
    Tags,
    /// Unsent draft preview.
    Draft,
}

/// A summary, tag or draft snippet.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchMetadataSnippetRecord {
    /// Snippet text.
    pub snippet: String,
    /// Match start in UTF-16 units of the snippet.
    pub match_start: u32,
    /// Match length in UTF-16 units.
    pub match_length: u32,
    /// Matched field.
    pub source: SearchMetadataSourceRecord,
}

/// One matching chat in final display order.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchChatResultRecord {
    /// Chat id.
    pub chat_id: String,
    /// Title match ranges (title matched when non-empty).
    pub title_ranges: Vec<SearchMatchRangeRecord>,
    /// Message and embed snippets.
    pub messages: Vec<SearchMessageSnippetRecord>,
    /// Summary, tag and draft snippets.
    pub metadata: Vec<SearchMetadataSnippetRecord>,
}

/// One ranked embed result.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchEmbedResultRecord {
    /// Chat id.
    pub chat_id: String,
    /// Embed id.
    pub embed_id: String,
    /// Embed type (empty when unknown).
    pub embed_type: String,
    /// Parent message id.
    pub message_id: String,
    /// Embed title.
    pub title: String,
    /// Subtitle, source label or "Embed".
    pub subtitle: String,
    /// Owning app id.
    pub app_id: Option<String>,
    /// Embed message timestamp.
    pub created_at: f64,
}

/// Result of one search.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct SearchResultRecord {
    /// Matching chats: title matches, then message matches, then by recency.
    pub chats: Vec<SearchChatResultRecord>,
    /// Ranked, deduplicated, capped embeds.
    pub embeds: Vec<SearchEmbedResultRecord>,
    /// Indices into the request catalog of matching settings entries.
    pub settings: Vec<u32>,
    /// Indices into the request catalog of matching app entries.
    pub apps: Vec<u32>,
}

/// One message text for in-chat search.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct InChatSearchMessageRecord {
    /// Message id.
    pub message_id: String,
    /// Searchable plaintext of the message.
    pub text: String,
}

/// Matches of one message in an in-chat search.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct InChatSearchMatchRecord {
    /// Message id.
    pub message_id: String,
    /// Non-overlapping ranges in UTF-16 units of the lowercased text.
    pub ranges: Vec<SearchMatchRangeRecord>,
}

fn range_record(range: &MatchRange) -> SearchMatchRangeRecord {
    SearchMatchRangeRecord {
        start: range.start as u32,
        length: range.length as u32,
    }
}

fn meta_record(meta: &EntryMeta) -> SearchEntryMetaRecord {
    SearchEntryMetaRecord {
        source_label: meta.source_label.clone(),
        embed_id: meta.embed_id.clone(),
        embed_type: meta.embed_type.clone(),
        title: meta.title.clone(),
        subtitle: meta.subtitle.clone(),
        app_id: meta.app_id.clone(),
        skill_id: meta.skill_id.clone(),
        focus_id: meta.focus_id.clone(),
        focus_mode_name: meta.focus_mode_name.clone(),
    }
}

fn core_meta(meta: SearchEntryMetaRecord) -> EntryMeta {
    EntryMeta {
        source_label: meta.source_label,
        embed_id: meta.embed_id,
        embed_type: meta.embed_type,
        title: meta.title,
        subtitle: meta.subtitle,
        app_id: meta.app_id,
        skill_id: meta.skill_id,
        focus_id: meta.focus_id,
        focus_mode_name: meta.focus_mode_name,
    }
}

#[derive(Default)]
struct EngineState {
    index: ChatSearchIndex,
    handles: HashMap<String, u32>,
    next_handle: u32,
}

impl EngineState {
    fn chat_id(&self, handle: u32) -> Option<String> {
        self.handles
            .iter()
            .find(|(_, held)| **held == handle)
            .map(|(id, _)| id.clone())
    }
}

/// Resident chat search index: ingest each chat's entries once, query per keystroke.
/// Named `CoreChatSearchIndex` because the Apple app module already has a Swift
/// `ChatSearchEngine` (the shell code this object replaces) and the bindings share that module.
#[derive(uniffi::Object, Default)]
pub struct CoreChatSearchIndex {
    state: Mutex<EngineState>,
}

impl CoreChatSearchIndex {
    fn lock(&self) -> MutexGuard<'_, EngineState> {
        // The state holds no cross-field invariant a panic could break midway.
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[uniffi::export]
impl CoreChatSearchIndex {
    /// An empty index.
    #[uniffi::constructor]
    pub fn new() -> Self {
        Self::default()
    }

    /// Replaces the entries of `chat_id`; returns the chat ids the index budget evicted
    /// (re-ingest them before they are queried with `search_messages`).
    pub fn ingest_chat(
        &self,
        chat_id: String,
        entries: Vec<SearchIndexEntryRecord>,
    ) -> Vec<String> {
        let mut state = self.lock();
        let handle = match state.handles.get(&chat_id) {
            Some(handle) => *handle,
            None => {
                state.next_handle += 1;
                let handle = state.next_handle;
                state.handles.insert(chat_id, handle);
                handle
            }
        };
        let entries = entries
            .into_iter()
            .map(|entry| IngestEntry {
                message_id: entry.message_id,
                content: entry.content,
                created_at: entry.created_at,
                meta: entry.meta.map(core_meta),
            })
            .collect();
        let evicted = state.index.ingest_chat(handle, entries);
        let mut ids = Vec::new();
        for handle in evicted {
            if let Some(id) = state.chat_id(handle) {
                state.handles.remove(&id);
                ids.push(id);
            }
        }
        ids
    }

    /// Drops one chat's entries.
    pub fn remove_chat(&self, chat_id: String) {
        let mut state = self.lock();
        if let Some(handle) = state.handles.remove(&chat_id) {
            state.index.remove_chat(handle);
        }
    }

    /// Drops every chat (logout).
    pub fn clear(&self) {
        let mut state = self.lock();
        state.index.clear();
        state.handles.clear();
    }

    /// Number of chats held.
    pub fn chat_count(&self) -> u32 {
        self.lock().index.chat_count() as u32
    }

    /// One complete search (`web_search_query::run_search`).
    pub fn query(&self, request: SearchRequestRecord) -> SearchResultRecord {
        let mut state = self.lock();
        let chat_ids: Vec<String> = request.chats.iter().map(|c| c.chat_id.clone()).collect();
        let core_request = SearchQuery {
            query: request.query,
            include_embeds: request.include_embeds,
            authenticated: request.authenticated,
            admin: request.admin,
            chats: request
                .chats
                .into_iter()
                .map(|chat| QueryChat {
                    handle: if chat.search_messages {
                        state.handles.get(&chat.chat_id).copied().unwrap_or(0)
                    } else {
                        0
                    },
                    title: chat.title,
                    active_focus_id: chat.active_focus_id,
                    summary: chat.summary,
                    tags: chat.tags,
                    draft: chat.draft,
                    last_edited: chat.last_edited,
                })
                .collect(),
            catalog: request
                .catalog
                .into_iter()
                .map(|entry| CatalogEntry {
                    kind: match entry.kind {
                        SearchCatalogKindRecord::Settings => CatalogKind::Settings,
                        SearchCatalogKindRecord::App => CatalogKind::App,
                    },
                    access: match entry.access {
                        SearchCatalogAccessRecord::Public => CatalogAccess::Public,
                        SearchCatalogAccessRecord::Authenticated => CatalogAccess::Authenticated,
                        SearchCatalogAccessRecord::Admin => CatalogAccess::Admin,
                    },
                    label: entry.label,
                    keywords: entry.keywords,
                })
                .collect(),
        };
        state.index.touch(&core_request.handles());
        let outcome = run_search(&state.index, &core_request);
        SearchResultRecord {
            chats: outcome
                .chats
                .iter()
                .map(|chat| SearchChatResultRecord {
                    chat_id: chat_ids[chat.position].clone(),
                    title_ranges: chat.title_ranges.iter().map(range_record).collect(),
                    messages: chat
                        .messages
                        .iter()
                        .map(|m| SearchMessageSnippetRecord {
                            snippet: String::from_utf16_lossy(&m.snippet),
                            match_start: m.match_start as u32,
                            match_length: m.match_length as u32,
                            message_id: m.message_id.to_string(),
                            meta: m.meta.map(meta_record),
                            focus_active: m.focus_active,
                        })
                        .collect(),
                    metadata: chat
                        .metadata
                        .iter()
                        .map(|m| SearchMetadataSnippetRecord {
                            snippet: String::from_utf16_lossy(&m.snippet),
                            match_start: m.match_start as u32,
                            match_length: m.match_length as u32,
                            source: match m.source {
                                MetadataSource::Summary => SearchMetadataSourceRecord::Summary,
                                MetadataSource::Tags => SearchMetadataSourceRecord::Tags,
                                MetadataSource::Draft => SearchMetadataSourceRecord::Draft,
                            },
                        })
                        .collect(),
                })
                .collect(),
            embeds: outcome
                .embeds
                .iter()
                .map(|e| SearchEmbedResultRecord {
                    chat_id: chat_ids[e.position].clone(),
                    embed_id: e.embed_id.to_string(),
                    embed_type: e.embed_type.to_string(),
                    message_id: e.message_id.to_string(),
                    title: e.title.to_string(),
                    subtitle: e.subtitle.to_string(),
                    app_id: e.app_id.map(str::to_string),
                    created_at: e.created_at,
                })
                .collect(),
            settings: outcome.settings.iter().map(|i| *i as u32).collect(),
            apps: outcome.apps.iter().map(|i| *i as u32).collect(),
        }
    }
}

/// Case-insensitive non-overlapping match ranges of `query` in `text` (UTF-16 units).
#[uniffi::export]
pub fn search_find_match_ranges(text: String, query: String) -> Vec<SearchMatchRangeRecord> {
    find_match_ranges(&text, &query)
        .iter()
        .map(range_record)
        .collect()
}

/// In-chat search: the messages of one chat that contain `query`, in input
/// order, with their match ranges (an empty query matches nothing).
#[uniffi::export]
pub fn search_in_chat_messages(
    query: String,
    messages: Vec<InChatSearchMessageRecord>,
) -> Vec<InChatSearchMatchRecord> {
    messages
        .into_iter()
        .filter_map(|message| {
            let ranges = find_match_ranges(&message.text, &query);
            (!ranges.is_empty()).then(|| InChatSearchMatchRecord {
                message_id: message.message_id,
                ranges: ranges.iter().map(range_record).collect(),
            })
        })
        .collect()
}
