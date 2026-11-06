//! Shared-core chat message search for the web Worker `search` unit; mirrors
//! `searchMessagesInChat` in frontend/packages/ui/src/services/searchService.ts
//! (spec `specifications/surfaces/sdk` assertion sdk.client.thin-platform-boundary).
//! The index lives next to its data in the Worker; a query returns only flat
//! `u32` rows with UTF-16 snippet slice plans, never text, so the page rebuilds
//! snippets exactly (lone surrogates included) from content it already holds.
use crate::web_search::{context_bounds, plan_snippet, plan_window, utf16_len, utf16_window};
use std::collections::HashMap;

/// Snippets per chat (`MAX_SNIPPETS_PER_CHAT` in searchService.ts).
pub const MAX_SNIPPETS_PER_CHAT: usize = 5;
/// Snippets from any one message, so an embed-heavy message cannot fill a chat's slots.
pub const MAX_SNIPPETS_PER_MESSAGE: usize = 2;
/// Distinct titled embed results per chat when embeds are requested.
pub const MAX_EMBED_RESULTS_PER_CHAT: usize = 6;

/// Row header: `[chat_position, snippet_count, embed_count]`.
pub const HEADER_WORDS: usize = 3;
/// Snippet row: `[entry, from, to, flags, snippet_match_start]`; flags bit 0 = leading
/// `"... "`, bit 1 = trailing `" ..."`.
pub const SNIPPET_WORDS: usize = 5;

struct ChatEntry {
    message: u32,
    text: String,
    lower: String,
    lower_ascii: bool,
    text_ascii: bool,
    /// Interned embed id (0 = none) when the entry is an embed that has a title.
    titled_embed: u32,
}

#[derive(Default)]
struct Chat {
    entries: Vec<ChatEntry>,
    messages: HashMap<String, u32>,
    embeds: HashMap<String, u32>,
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

/// Per-chat search entries addressed by page-assigned `u32` handles. Entries
/// keep ingest order, which the page sorts newest first, because the result
/// caps make the first hits win exactly as in the TypeScript loop.
#[derive(Default)]
pub struct ChatSearchIndex {
    chats: HashMap<u32, Chat>,
}

impl ChatSearchIndex {
    /// Drops whatever `handle` held; the next `push_entry` calls rebuild it.
    pub fn reset_chat(&mut self, handle: u32) {
        self.chats.insert(handle, Chat::default());
    }

    /// Appends one entry. `embed_id` is empty for message text; `embed_titled`
    /// mirrors the page's `entry.embedId && entry.embedTitle` check.
    pub fn push_entry(
        &mut self,
        handle: u32,
        message_id: &str,
        text: &str,
        embed_id: &str,
        embed_titled: bool,
    ) {
        let chat = self.chats.entry(handle).or_default();
        let next = chat.messages.len() as u32;
        let message = *chat.messages.entry(message_id.to_string()).or_insert(next);
        let titled_embed = if embed_id.is_empty() || !embed_titled {
            0
        } else {
            let next = chat.embeds.len() as u32 + 1;
            *chat.embeds.entry(embed_id.to_string()).or_insert(next)
        };
        let lower = text.to_lowercase();
        chat.entries.push(ChatEntry {
            message,
            lower_ascii: lower.is_ascii(),
            text_ascii: text.is_ascii(),
            lower,
            text: text.to_string(),
            titled_embed,
        });
    }

    /// Forgets `handle` (the page evicted or invalidated that chat's index).
    pub fn remove_chat(&mut self, handle: u32) {
        self.chats.remove(&handle);
    }

    /// Forgets every chat (logout).
    pub fn clear(&mut self) {
        self.chats.clear();
    }

    /// Number of chats currently held.
    pub fn chat_count(&self) -> usize {
        self.chats.len()
    }

    /// Entries held for `handle` (0 when unknown).
    pub fn entry_count(&self, handle: u32) -> usize {
        self.chats.get(&handle).map_or(0, |chat| chat.entries.len())
    }

    /// Searches the chats in `handles` order. For every chat with at least one
    /// snippet or embed hit, appends a header row, its snippet rows, then one
    /// word per embed hit (the entry index). Unknown handles have no entries.
    pub fn search(&self, query: &str, handles: &[u32], include_embeds: bool) -> Vec<u32> {
        let mut rows = Vec::new();
        let lower_query = query.to_lowercase();
        // `search()` never runs an empty query; an empty needle would match every entry.
        if lower_query.is_empty() {
            return rows;
        }
        let query_len = utf16_len(query);
        let mut embeds: Vec<u32> = Vec::new();
        let mut seen_embeds: Vec<u32> = Vec::new();
        let mut per_message: HashMap<u32, usize> = HashMap::new();
        for (position, handle) in handles.iter().enumerate() {
            let Some(chat) = self.chats.get(handle) else {
                continue;
            };
            let header = rows.len();
            rows.extend_from_slice(&[position as u32, 0, 0]);
            let mut snippets = 0usize;
            embeds.clear();
            seen_embeds.clear();
            per_message.clear();
            for (index, entry) in chat.entries.iter().enumerate() {
                if snippets >= MAX_SNIPPETS_PER_CHAT
                    && (!include_embeds || embeds.len() >= MAX_EMBED_RESULTS_PER_CHAT)
                {
                    break;
                }
                let Some(byte) = entry.lower.find(lower_query.as_str()) else {
                    continue;
                };
                if include_embeds
                    && entry.titled_embed != 0
                    && embeds.len() < MAX_EMBED_RESULTS_PER_CHAT
                    && !seen_embeds.contains(&entry.titled_embed)
                {
                    embeds.push(index as u32);
                    seen_embeds.push(entry.titled_embed);
                }
                if snippets >= MAX_SNIPPETS_PER_CHAT {
                    continue;
                }
                let count = per_message.entry(entry.message).or_insert(0);
                if *count >= MAX_SNIPPETS_PER_MESSAGE {
                    continue;
                }
                *count += 1;
                snippets += 1;
                let start = if entry.lower_ascii {
                    byte
                } else {
                    utf16_len(&entry.lower[..byte])
                };
                let slice = snippet_slice(&entry.text, entry.text_ascii, start, query_len);
                let flags = u32::from(slice.front_ellipsis) | (u32::from(slice.back_ellipsis) << 1);
                rows.extend_from_slice(&[
                    index as u32,
                    slice.from as u32,
                    slice.to as u32,
                    flags,
                    slice.match_start as u32,
                ]);
            }
            if snippets == 0 && embeds.is_empty() {
                rows.truncate(header);
                continue;
            }
            rows[header + 1] = snippets as u32;
            rows[header + 2] = embeds.len() as u32;
            rows.extend_from_slice(&embeds);
        }
        rows
    }
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
    // One unit past the context end tells whether text follows it, so the full
    // UTF-16 length is only needed when the window is empty.
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
