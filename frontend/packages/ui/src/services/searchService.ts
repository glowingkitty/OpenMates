// frontend/packages/ui/src/services/searchService.ts
// Core search engine service for offline full-text search across chats, messages, settings,
// apps, skills, focus modes, and memories.
// Uses an in-memory index (Option D: Hybrid warm cache) for E2E encryption compatibility.
// All data lives in RAM only — nothing is persisted to disk as plaintext.
//
// EMBED CONTENT SEARCH:
// In addition to message text, the index includes text extracted from embed content
// (web pages, code, documents, skill results, etc.). Embeds are resolved via the
// embedStore (IndexedDB) and decoded from TOON format. Each embed's text is stored
// alongside its parent message entry, identified by embedType for display context.
// Extraction is capped at MAX_EMBED_TEXT_CHARS per embed to keep RAM usage bounded.

import type { Chat, Message } from "../types/chat";
import { chatDB } from "./db";
import { chatMetadataCache } from "./chatMetadataCache";
import {
  getSettingsSearchCatalog,
  getAppSearchCatalog,
  type SettingsCatalogEntry,
  type AppCatalogEntry,
} from "./searchSettingsCatalog";
import {
  getDemoMessages,
  isDemoChat,
  isLegalChat,
  INTRO_CHATS,
  LEGAL_CHATS,
} from "../demo_chats";
import { extractEmbedReferences } from "./embedResolver";

// --- Types ---

/** A single message snippet showing context around a search match */
export interface MessageMatchSnippet {
  messageId: string;
  chatId: string;
  /** The snippet text with context words around the match (e.g., "... could we run on ios as well? ...") */
  snippet: string;
  /** Start index of the match within the snippet (for highlighting) */
  matchStart: number;
  /** Length of the matched text within the snippet */
  matchLength: number;
  /**
   * Human-readable label describing the source of this snippet.
   * Undefined for regular message text. Set for embed content (e.g., "Web page", "Code", "Document").
   * Used by SearchResults.svelte to show "Found in: Web page" context labels.
   */
  embedSourceLabel?: string;
}

/** A chat search result containing title match info and message match snippets */
export interface ChatSearchResult {
  chat: Chat;
  /** Whether the chat title matched the query */
  titleMatch: boolean;
  /** Indices within the title where the match occurs (for highlighting) */
  titleMatchRanges: Array<{ start: number; length: number }>;
  /** The decrypted title text */
  decryptedTitle: string | null;
  /** Message content matches within this chat, sorted by recency */
  messageSnippets: MessageMatchSnippet[];
}

/** A settings search result (settings pages) */
export interface SettingsSearchResult {
  entry: SettingsCatalogEntry;
  /** The resolved label text (translated) */
  label: string;
  /** The resolved icon name */
  icon: string | null;
}

/** An app/skill/focus-mode/memory search result */
export interface AppCatalogSearchResult {
  entry: AppCatalogEntry;
  /** The resolved label text (translated) */
  label: string;
  /** The resolved icon name */
  icon: string | null;
  /** The type of entry for display grouping */
  entryType: "app" | "skill" | "focus_mode" | "memory";
}

/** Complete search results across all categories */
export interface SearchResults {
  /** Chats with title or message matches, sorted by relevance then recency */
  chats: ChatSearchResult[];
  /** Settings pages that match the query */
  settings: SettingsSearchResult[];
  /** App catalog entries (apps, skills, focus modes, memories) that match */
  appCatalog: AppCatalogSearchResult[];
  /** Total number of matches across all categories */
  totalCount: number;
  /** Whether the search index is still warming up (first search may need message decryption) */
  isWarmingUp: boolean;
}

// --- Configuration ---

/** Number of characters to show before and after a match in message snippets */
const SNIPPET_CONTEXT_CHARS = 50;
/** Maximum number of message snippets to show per chat */
const MAX_SNIPPETS_PER_CHAT = 3;
/**
 * Maximum characters to extract from a single embed for search indexing.
 * Caps RAM usage per embed — a typical web page scrape can be 10k+ chars.
 */
const MAX_EMBED_TEXT_CHARS = 1500;

// --- Helpers ---

/**
 * Strip markdown formatting from text so snippets display clean plaintext.
 * Removes: bold/italic markers, headings, links, images, code fences, inline code,
 * bullet markers, blockquote markers, and JSON embed code blocks.
 * This is intentionally lightweight — accuracy > completeness.
 */
function stripMarkdown(text: string): string {
  return (
    text
      // Remove JSON embed code blocks (```json {...} ```) entirely
      .replace(/```json\s*\{[\s\S]*?\}\s*```/g, "")
      // Remove fenced code block markers (``` ... ```)
      .replace(/```[\s\S]*?```/g, (match) => {
        // Keep the content between fences, just remove the fences
        const inner = match.slice(3, -3).replace(/^\w*\n/, "");
        return inner;
      })
      // Remove inline code backticks
      .replace(/`([^`]+)`/g, "$1")
      // Remove images ![alt](url)
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1")
      // Remove links [text](url) — keep text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      // Remove bold/italic markers (*** ** * __ _)
      .replace(/(\*{1,3}|_{1,3})(\S[\s\S]*?\S)\1/g, "$2")
      // Remove heading markers
      .replace(/^#{1,6}\s+/gm, "")
      // Remove blockquote markers
      .replace(/^>\s?/gm, "")
      // Remove bullet/list markers
      .replace(/^[\s]*[-*+]\s+/gm, "")
      // Remove numbered list markers
      .replace(/^[\s]*\d+\.\s+/gm, "")
      // Collapse multiple whitespace/newlines
      .replace(/\s+/g, " ")
      .trim()
  );
}

// --- Embed Text Extraction ---

/**
 * Map of embed types to human-readable source labels shown in search results.
 * The label appears as "Found in: <label>" in SearchResults.svelte.
 */
const EMBED_TYPE_LABELS: Record<string, string> = {
  "web-website": "Web page",
  "web-website-group": "Web search",
  "videos-video": "Video",
  "code-code": "Code",
  "sheets-sheet": "Table",
  "docs-doc": "Document",
  maps: "Map",
  audio: "Audio",
  image: "Image",
  file: "File",
  text: "Text",
  pdf: "PDF",
  book: "Book",
  recording: "Recording",
  "app-skill-use": "Skill result",
  "app-skill-use-group": "Skill results",
  news: "News",
  travel: "Travel",
  "focus-mode-activation": "Focus mode",
};

/**
 * Extract a searchable plaintext string from a decoded embed content object.
 * Returns null if no meaningful text can be extracted.
 *
 * Text is truncated to MAX_EMBED_TEXT_CHARS to keep RAM usage bounded.
 * Each embed type has different fields — we pull the most text-rich ones.
 *
 * @param embedType - Normalized embed type (e.g., "web-website", "code-code")
 * @param decoded   - Decoded JS object from TOON content
 */
function extractTextFromEmbed(
  embedType: string,
  decoded: Record<string, any>,
): string | null {
  if (!decoded || typeof decoded !== "object") return null;

  const parts: string[] = [];

  if (embedType === "web-website") {
    // Website embeds: title + description are the most searchable fields.
    // The URL is also useful to match domain names.
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.description) parts.push(String(decoded.description));
    // Handle TOON-flattened field names from backend (meta_url_description, etc.)
    if (decoded.meta_url_title && decoded.meta_url_title !== decoded.title)
      parts.push(String(decoded.meta_url_title));
    if (
      decoded.meta_url_description &&
      decoded.meta_url_description !== decoded.description
    )
      parts.push(String(decoded.meta_url_description));
    if (decoded.url) parts.push(String(decoded.url));
    if (decoded.site_name) parts.push(String(decoded.site_name));
  } else if (embedType === "web-website-group") {
    // Web search result groups: extract from the results array
    // Each result item typically has url, title, description
    const results = decoded.results || decoded.items || [];
    if (Array.isArray(results)) {
      for (const item of results) {
        if (typeof item === "object" && item) {
          if (item.title) parts.push(String(item.title));
          if (item.description) parts.push(String(item.description));
          if (item.url) parts.push(String(item.url));
        }
      }
    }
    // Also check top-level query field
    if (decoded.query) parts.push(String(decoded.query));
  } else if (embedType === "videos-video") {
    // Video embeds: title + channel name + description
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.channel_name) parts.push(String(decoded.channel_name));
    if (decoded.description)
      parts.push(String(decoded.description).slice(0, 500));
    if (decoded.url) parts.push(String(decoded.url));
  } else if (embedType === "code-code") {
    // Code embeds: filename is most useful; code content itself can be very large
    // so we limit it aggressively — developers searching for a function name should still match
    if (decoded.filename) parts.push(String(decoded.filename));
    if (decoded.language) parts.push(String(decoded.language));
    if (decoded.code) parts.push(String(decoded.code).slice(0, 800));
  } else if (embedType === "sheets-sheet") {
    // Table embeds: title + raw table markdown
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.code) parts.push(String(decoded.code).slice(0, 600));
  } else if (embedType === "docs-doc") {
    // Document embeds: title + content body
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.content) parts.push(String(decoded.content).slice(0, 800));
    if (decoded.description) parts.push(String(decoded.description));
  } else if (embedType === "app-skill-use") {
    // App skill results: query + result summaries
    // These are the most varied — try common field patterns
    if (decoded.query) parts.push(String(decoded.query));
    if (decoded.skill_id) parts.push(String(decoded.skill_id));
    if (decoded.summary) parts.push(String(decoded.summary));
    if (decoded.result) parts.push(String(decoded.result).slice(0, 600));
    // Handle nested results array (e.g., news search, web search via skill)
    const results = decoded.results || decoded.items || [];
    if (Array.isArray(results)) {
      for (const item of results.slice(0, 5)) {
        if (typeof item === "object" && item) {
          if (item.title) parts.push(String(item.title));
          if (item.description) parts.push(String(item.description));
          if (item.url) parts.push(String(item.url));
        }
      }
    }
  } else if (embedType === "app-skill-use-group") {
    // Skill result groups: aggregate text from child results
    if (decoded.query) parts.push(String(decoded.query));
    const results = decoded.results || decoded.items || [];
    if (Array.isArray(results)) {
      for (const item of results.slice(0, 5)) {
        if (typeof item === "object" && item) {
          if (item.title) parts.push(String(item.title));
          if (item.description) parts.push(String(item.description));
        }
      }
    }
  } else if (embedType === "maps") {
    // Map embeds: name + address
    if (decoded.name) parts.push(String(decoded.name));
    if (decoded.address) parts.push(String(decoded.address));
    if (decoded.place_type) parts.push(String(decoded.place_type));
  } else if (embedType === "pdf" || embedType === "book") {
    // PDF/book embeds: title + author
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.author) parts.push(String(decoded.author));
    if (decoded.description) parts.push(String(decoded.description));
  } else if (embedType === "text" || embedType === "file") {
    // Plain text / file embeds: filename + content
    if (decoded.filename || decoded.name)
      parts.push(String(decoded.filename || decoded.name));
    if (decoded.content) parts.push(String(decoded.content).slice(0, 600));
    if (decoded.text) parts.push(String(decoded.text).slice(0, 600));
  } else {
    // Unknown embed type: try generic field names that often contain useful text
    if (decoded.title) parts.push(String(decoded.title));
    if (decoded.description) parts.push(String(decoded.description));
    if (decoded.query) parts.push(String(decoded.query));
    if (decoded.url) parts.push(String(decoded.url));
  }

  if (parts.length === 0) return null;

  const combined = parts.join(" ").replace(/\s+/g, " ").trim();
  return combined.slice(0, MAX_EMBED_TEXT_CHARS) || null;
}

/**
 * Resolve embed content for a single embed_id and return extracted searchable text.
 * Uses embedStore (IndexedDB + memory cache) to load encrypted embed content.
 * All decryption happens client-side — no plaintext ever leaves the device.
 *
 * Returns null if the embed is unavailable, still processing, or has no useful text.
 *
 * @param embedId   - The embed identifier (without "embed:" prefix)
 * @param embedType - The embed type from the JSON reference block (e.g., "app_skill_use")
 */
async function resolveEmbedText(
  embedId: string,
  embedType: string,
): Promise<{ text: string; sourceLabel: string } | null> {
  try {
    // Lazy-load the heavy embedStore and TOON decoder only when needed.
    // Both are imported here (inside the function) to avoid a circular dependency,
    // since embedResolver imports searchService indirectly via the store chain.
    const { embedStore } = await import("./embedStore");
    const { decodeToonContent } = await import("./embedResolver");

    // Load from IndexedDB / memory cache — does NOT trigger a WebSocket request.
    // If the embed isn't available locally, we simply skip it (it won't be in the index).
    const embedData = await embedStore.get(`embed:${embedId}`);
    if (!embedData || !embedData.content || embedData.status === "processing") {
      return null;
    }

    // Decode TOON → JS object
    const decoded = await decodeToonContent(embedData.content);
    if (!decoded) return null;

    // Normalize the embed type for consistent label lookup
    // Server uses underscores ("app_skill_use"), frontend uses hyphens ("app-skill-use")
    const normalizedType = embedType.replace(/_/g, "-");

    // Extract type-appropriate searchable text
    const text = extractTextFromEmbed(normalizedType, decoded);
    if (!text) return null;

    // Determine the human-readable source label for this embed type
    const sourceLabel = EMBED_TYPE_LABELS[normalizedType] || "Embed";

    return { text, sourceLabel };
  } catch (error) {
    // Non-critical: if embed resolution fails, simply skip this embed
    console.debug(
      `[SearchService] Could not resolve embed ${embedId} for indexing:`,
      error instanceof Error ? error.message : String(error),
    );
    return null;
  }
}

// --- In-Memory Search Index ---

/**
 * Stores decrypted message content (and embed content) for searching.
 * Key: chatId, Value: array of index entries — one per message text block or embed.
 *
 * Each entry carries:
 *   messageId   — parent message (used to scroll-to on click)
 *   content     — searchable plaintext (markdown-stripped message text, or embed text)
 *   createdAt   — timestamp for newest-first sorting
 *   embedSourceLabel — undefined for message text; human-readable label for embed content
 *                      (e.g., "Web page", "Code", "Document") used in the results UI
 *
 * This data is RAM-only and cleared when the page unloads.
 */
const messageIndex = new Map<
  string,
  Array<{
    messageId: string;
    content: string;
    createdAt: number;
    /** Present when this entry represents embed content rather than raw message text */
    embedSourceLabel?: string;
  }>
>();

/** Track which chats have had their messages indexed */
const indexedChatIds = new Set<string>();

/** Flag to track if warm-up is in progress */
let warmUpInProgress = false;

/** Flag to track if warm-up has completed at least once */
let warmUpCompleted = false;

// --- Index Management ---

/**
 * Index messages (and their embedded content) for a single chat.
 *
 * For demo/legal chats, messages live in-memory. For authenticated user chats
 * they are decrypted from IndexedDB by chatDB.getMessagesForChat().
 *
 * After indexing each message's text, we also scan the message markdown for
 * embed references (JSON code blocks) and resolve each embed's content via
 * the embedStore. The extracted embed text is stored as additional index entries
 * linked to the same parent message ID so that clicking a result scrolls to the
 * correct message.
 *
 * Embed resolution is best-effort:
 *   - Only embeds already in IndexedDB/memory cache are indexed (no WebSocket requests).
 *   - Embeds still processing (status="processing") are skipped.
 *   - Any per-embed error is caught silently so one bad embed doesn't abort the chat.
 *
 * @param chatId - The chat ID to index
 */
async function indexChatMessages(chatId: string): Promise<void> {
  if (indexedChatIds.has(chatId)) return;

  try {
    let messages: Message[];

    if (isDemoChat(chatId) || isLegalChat(chatId)) {
      // Demo and legal chats have messages in-memory, NOT in chatDB
      messages = getDemoMessages(chatId, INTRO_CHATS, LEGAL_CHATS);
    } else {
      // Authenticated user chats — decrypt from IndexedDB
      messages = await chatDB.getMessagesForChat(chatId);
    }

    const entries: Array<{
      messageId: string;
      content: string;
      createdAt: number;
      embedSourceLabel?: string;
    }> = [];

    for (const msg of messages) {
      if (!msg.content || typeof msg.content !== "string") continue;
      const rawContent = msg.content.trim();
      if (!rawContent) continue;

      // 1. Index the message's own text (markdown-stripped)
      const messageText = stripMarkdown(rawContent);
      if (messageText) {
        entries.push({
          messageId: msg.message_id,
          content: messageText,
          createdAt: msg.created_at,
          // No embedSourceLabel — this is the base message text
        });
      }

      // 2. Extract embed references from the raw markdown and index their content.
      //    Only authenticated chats have real embeds — demo chats have inline text content
      //    already present in the message body.
      if (!isDemoChat(chatId) && !isLegalChat(chatId)) {
        const embedRefs = extractEmbedReferences(rawContent);
        for (const ref of embedRefs) {
          const result = await resolveEmbedText(ref.embed_id, ref.type);
          if (!result) continue;

          entries.push({
            messageId: msg.message_id,
            content: result.text,
            createdAt: msg.created_at,
            embedSourceLabel: result.sourceLabel,
          });
        }
      }
    }

    messageIndex.set(chatId, entries);
    indexedChatIds.add(chatId);
  } catch (error) {
    console.error(
      `[SearchService] Error indexing messages for chat ${chatId}:`,
      error,
    );
    // Mark as indexed even on error to avoid repeated failures
    indexedChatIds.add(chatId);
    messageIndex.set(chatId, []);
  }
}

/**
 * Warm up the search index by pre-loading messages for all available chats.
 * Called after sync phases complete. Runs in the background without blocking the UI.
 * @param chatIds - Array of chat IDs to warm up
 */
export async function warmUpSearchIndex(chatIds: string[]): Promise<void> {
  if (warmUpInProgress) return;
  warmUpInProgress = true;

  console.debug(
    `[SearchService] Warming up search index for ${chatIds.length} chats...`,
  );
  const startTime = performance.now();

  try {
    // Process chats in small batches to avoid blocking the main thread
    const BATCH_SIZE = 5;
    for (let i = 0; i < chatIds.length; i += BATCH_SIZE) {
      const batch = chatIds.slice(i, i + BATCH_SIZE);
      await Promise.all(batch.map((chatId) => indexChatMessages(chatId)));

      // Yield to the event loop between batches so UI stays responsive
      if (i + BATCH_SIZE < chatIds.length) {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }

    const elapsed = performance.now() - startTime;
    console.debug(
      `[SearchService] Search index warmed up in ${elapsed.toFixed(0)}ms (${indexedChatIds.size} chats)`,
    );
  } catch (error) {
    console.error("[SearchService] Error during search index warm-up:", error);
  } finally {
    warmUpInProgress = false;
    warmUpCompleted = true;
  }
}

/**
 * Add or update a single message (and its embed content) in the search index.
 * Called when new messages arrive via WebSocket or when messages are updated.
 *
 * This function is async to support embed resolution, but callers that don't
 * await it (fire-and-forget) are fine — the index update will complete in the
 * background and the next search will pick up the new entries.
 *
 * @param chatId  - The chat ID the message belongs to
 * @param message - The decrypted message to add
 */
export async function addMessageToIndex(
  chatId: string,
  message: Message,
): Promise<void> {
  if (!message.content || typeof message.content !== "string") return;

  const rawContent = message.content.trim();
  if (!rawContent) return;

  // Remove all existing entries for this message (clean slate for update)
  const existing = messageIndex.get(chatId) || [];
  const withoutThisMessage = existing.filter(
    (e) => e.messageId !== message.message_id,
  );

  const newEntries: Array<{
    messageId: string;
    content: string;
    createdAt: number;
    embedSourceLabel?: string;
  }> = [];

  // 1. Index the message's own text
  const messageText = stripMarkdown(rawContent);
  if (messageText) {
    newEntries.push({
      messageId: message.message_id,
      content: messageText,
      createdAt: message.created_at,
    });
  }

  // 2. Index embed content referenced in the message
  const embedRefs = extractEmbedReferences(rawContent);
  for (const ref of embedRefs) {
    const result = await resolveEmbedText(ref.embed_id, ref.type);
    if (!result) continue;
    newEntries.push({
      messageId: message.message_id,
      content: result.text,
      createdAt: message.created_at,
      embedSourceLabel: result.sourceLabel,
    });
  }

  messageIndex.set(chatId, [...withoutThisMessage, ...newEntries]);
}

/**
 * Remove a chat from the search index (e.g., when deleted).
 * @param chatId - The chat ID to remove
 */
export function removeChatFromIndex(chatId: string): void {
  messageIndex.delete(chatId);
  indexedChatIds.delete(chatId);
}

/**
 * Clear the entire search index (e.g., on logout).
 */
export function clearSearchIndex(): void {
  messageIndex.clear();
  indexedChatIds.clear();
  warmUpCompleted = false;
  warmUpInProgress = false;
  console.debug("[SearchService] Search index cleared");
}

// --- Search Logic ---

/**
 * Find all non-overlapping occurrences of a query within a text (case-insensitive).
 * @returns Array of { start, length } for each match
 */
export function findMatchRanges(
  text: string,
  query: string,
): Array<{ start: number; length: number }> {
  const ranges: Array<{ start: number; length: number }> = [];
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();

  let searchFrom = 0;
  while (searchFrom < lowerText.length) {
    const idx = lowerText.indexOf(lowerQuery, searchFrom);
    if (idx === -1) break;
    ranges.push({ start: idx, length: lowerQuery.length });
    searchFrom = idx + lowerQuery.length;
  }

  return ranges;
}

/**
 * Build a snippet around a match position, showing surrounding context.
 * Produces text like "... words before match words after ..."
 * @param content - Full message content
 * @param matchStart - Start index of the match
 * @param matchLength - Length of the match
 * @returns Object with snippet text and match position within the snippet
 */
function buildSnippet(
  content: string,
  matchStart: number,
  matchLength: number,
): { snippet: string; snippetMatchStart: number; snippetMatchLength: number } {
  const contextStart = Math.max(0, matchStart - SNIPPET_CONTEXT_CHARS);
  const contextEnd = Math.min(
    content.length,
    matchStart + matchLength + SNIPPET_CONTEXT_CHARS,
  );

  let snippet = content.slice(contextStart, contextEnd);
  let snippetMatchStart = matchStart - contextStart;

  // Add ellipsis for truncated context, trimming to nearest word boundary
  if (contextStart > 0) {
    const firstSpace = snippet.indexOf(" ");
    if (firstSpace > 0 && firstSpace < snippetMatchStart) {
      snippet = snippet.slice(firstSpace + 1);
      snippetMatchStart -= firstSpace + 1;
    }
    snippet = "... " + snippet;
    snippetMatchStart += 4; // Account for "... " prefix
  }
  if (contextEnd < content.length) {
    const lastSpace = snippet.lastIndexOf(" ");
    if (lastSpace > snippetMatchStart + matchLength) {
      snippet = snippet.slice(0, lastSpace);
    }
    snippet = snippet + " ...";
  }

  return {
    snippet,
    snippetMatchStart,
    snippetMatchLength: matchLength,
  };
}

/**
 * Search messages (and embed content) in a single chat.
 * Returns up to MAX_SNIPPETS_PER_CHAT snippet matches, preferring message-text matches
 * over embed matches when both exist (message text is always shown first in the UI).
 *
 * Embed-sourced snippets include an embedSourceLabel so the results UI can show
 * "Found in: Web page" / "Found in: Code" context labels.
 */
function searchMessagesInChat(
  chatId: string,
  query: string,
): MessageMatchSnippet[] {
  const entries = messageIndex.get(chatId);
  if (!entries) return [];

  const snippets: MessageMatchSnippet[] = [];
  const lowerQuery = query.toLowerCase();

  // Search from newest to oldest (most relevant first).
  // Sort by createdAt DESC; within the same timestamp, put message-text entries
  // before embed entries so base text snippets appear first.
  const sorted = [...entries].sort((a, b) => {
    if (b.createdAt !== a.createdAt) return b.createdAt - a.createdAt;
    // Same timestamp: message text (no label) before embed content
    const aIsEmbed = a.embedSourceLabel !== undefined ? 1 : 0;
    const bIsEmbed = b.embedSourceLabel !== undefined ? 1 : 0;
    return aIsEmbed - bIsEmbed;
  });

  for (const entry of sorted) {
    if (snippets.length >= MAX_SNIPPETS_PER_CHAT) break;

    const lowerContent = entry.content.toLowerCase();
    const idx = lowerContent.indexOf(lowerQuery);
    if (idx === -1) continue;

    const { snippet, snippetMatchStart, snippetMatchLength } = buildSnippet(
      entry.content,
      idx,
      query.length,
    );

    snippets.push({
      messageId: entry.messageId,
      chatId,
      snippet,
      matchStart: snippetMatchStart,
      matchLength: snippetMatchLength,
      embedSourceLabel: entry.embedSourceLabel,
    });
  }

  return snippets;
}

/**
 * Search settings catalog against the query.
 * Matches against the translated label and keyword synonyms.
 * Filters out entries that require authentication or admin access based on the caller's context.
 * @param query - Search query string
 * @param textFn - Translation function ($text)
 * @param isAuthenticated - Whether the current user is authenticated
 * @param isAdmin - Whether the current user has admin privileges
 * @returns Array of matching settings entries visible to the current user
 */
function searchSettings(
  query: string,
  textFn: (key: string) => string,
  isAuthenticated: boolean,
  isAdmin: boolean,
): SettingsSearchResult[] {
  const catalog = getSettingsSearchCatalog();
  const lowerQuery = query.toLowerCase();
  const results: SettingsSearchResult[] = [];

  for (const entry of catalog) {
    // Access control: skip entries that the current user cannot access.
    // - 'admin' entries: only visible to admin users
    // - 'authenticated' entries: only visible to logged-in users
    // - 'public' / undefined (default): visible to everyone
    const access = entry.access ?? "public";
    if (access === "admin" && !isAdmin) continue;
    if (access === "authenticated" && !isAuthenticated) continue;

    const label = textFn(entry.translationKey);
    const lowerLabel = label.toLowerCase();

    if (lowerLabel.includes(lowerQuery)) {
      results.push({ entry, label, icon: entry.icon });
      continue;
    }

    const keywordMatch = entry.keywords.some((kw) =>
      kw.toLowerCase().includes(lowerQuery),
    );
    if (keywordMatch) {
      results.push({ entry, label, icon: entry.icon });
    }
  }

  return results;
}

/**
 * Search the app catalog (apps, skills, focus modes, memories) against the query.
 * @param query - Search query string
 * @param textFn - Translation function ($text)
 * @returns Array of matching app catalog entries
 */
function searchAppCatalog(
  query: string,
  textFn: (key: string) => string,
): AppCatalogSearchResult[] {
  const catalog = getAppCatalog(textFn);
  const lowerQuery = query.toLowerCase();
  const results: AppCatalogSearchResult[] = [];

  for (const entry of catalog) {
    const label = entry.label;
    const lowerLabel = label.toLowerCase();

    if (lowerLabel.includes(lowerQuery)) {
      results.push({
        entry,
        label,
        icon: entry.icon,
        entryType: entry.entryType,
      });
      continue;
    }

    const keywordMatch = entry.keywords.some((kw) =>
      kw.toLowerCase().includes(lowerQuery),
    );
    if (keywordMatch) {
      results.push({
        entry,
        label,
        icon: entry.icon,
        entryType: entry.entryType,
      });
    }
  }

  return results;
}

/**
 * Build the runtime app catalog using translated labels from appsMetadata.
 * This is cached per-search since it requires translation resolution.
 */
function getAppCatalog(
  textFn: (key: string) => string,
): Array<AppCatalogEntry & { label: string }> {
  const staticEntries = getAppSearchCatalog();
  return staticEntries.map((entry) => ({
    ...entry,
    label: entry.nameTranslationKey
      ? textFn(entry.nameTranslationKey)
      : entry.path,
  }));
}

/**
 * Main search function. Searches across all chats, messages, settings, apps, skills, focus modes, and memories.
 *
 * Performance characteristics (100 chats, ~5000 messages):
 * - Chat titles: <5ms (already in chatMetadataCache or plaintext for demo chats)
 * - Messages (warm index): <15ms (string matching in RAM)
 * - Messages (cold - first search): 200-500ms (batch decrypt from IndexedDB or load from memory)
 * - Settings + apps: <5ms (static catalog)
 *
 * @param query - The search query (minimum 1 character)
 * @param chats - Array of all available chats (from Chats.svelte's allChats derived)
 * @param textFn - Translation function ($text) for settings labels and i18n
 * @param hiddenChats - Optional array of hidden chats to include in search (only when unlocked)
 * @param isAuthenticated - Whether the current user is authenticated (filters auth-only settings)
 * @param isAdmin - Whether the current user has admin privileges (filters admin-only settings)
 * @returns SearchResults with categorized matches
 */
export async function search(
  query: string,
  chats: Chat[],
  textFn: (key: string) => string,
  hiddenChats: Chat[] = [],
  isAuthenticated: boolean = false,
  isAdmin: boolean = false,
): Promise<SearchResults> {
  if (!query || query.trim().length === 0) {
    return {
      chats: [],
      settings: [],
      appCatalog: [],
      totalCount: 0,
      isWarmingUp: false,
    };
  }

  const trimmedQuery = query.trim();
  const allSearchableChats = [...chats, ...hiddenChats];

  // Ensure all chats are indexed (lazy indexing for chats not yet warmed up)
  const unindexedChats = allSearchableChats.filter(
    (c) => !indexedChatIds.has(c.chat_id),
  );

  if (unindexedChats.length > 0) {
    // Index unindexed chats — this is the "cold start" path
    await Promise.all(unindexedChats.map((c) => indexChatMessages(c.chat_id)));
  }

  const chatResults: ChatSearchResult[] = [];

  // Search each chat
  for (const chat of allSearchableChats) {
    let decryptedTitle: string | null = null;

    if (isDemoChat(chat.chat_id) || isLegalChat(chat.chat_id)) {
      // Demo/legal chats have plaintext titles (translation key resolved at build time)
      decryptedTitle = chat.title || null;
    } else {
      // Authenticated user chats — get decrypted title from cache
      const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
      decryptedTitle = metadata?.title || chat.title || null;
    }

    // Check title match
    let titleMatch = false;
    let titleMatchRanges: Array<{ start: number; length: number }> = [];
    if (decryptedTitle) {
      titleMatchRanges = findMatchRanges(decryptedTitle, trimmedQuery);
      titleMatch = titleMatchRanges.length > 0;
    }

    // Check message matches
    const messageSnippets = searchMessagesInChat(chat.chat_id, trimmedQuery);

    // Include chat if title or any message matches
    if (titleMatch || messageSnippets.length > 0) {
      chatResults.push({
        chat,
        titleMatch,
        titleMatchRanges,
        decryptedTitle,
        messageSnippets,
      });
    }
  }

  // Sort results: title matches first, then by recency
  chatResults.sort((a, b) => {
    if (a.titleMatch && !b.titleMatch) return -1;
    if (!a.titleMatch && b.titleMatch) return 1;
    return (
      b.chat.last_edited_overall_timestamp -
      a.chat.last_edited_overall_timestamp
    );
  });

  // Search settings and app catalog — pass auth context so access-controlled entries are filtered
  const settingsResults = searchSettings(
    trimmedQuery,
    textFn,
    isAuthenticated,
    isAdmin,
  );
  const appCatalogResults = searchAppCatalog(trimmedQuery, textFn);

  const totalCount =
    chatResults.length + settingsResults.length + appCatalogResults.length;

  return {
    chats: chatResults,
    settings: settingsResults,
    appCatalog: appCatalogResults,
    totalCount,
    isWarmingUp: warmUpInProgress,
  };
}

/**
 * Check if the search index has been warmed up.
 * Used to show a loading indicator on first search.
 */
export function isSearchIndexReady(): boolean {
  return warmUpCompleted;
}
