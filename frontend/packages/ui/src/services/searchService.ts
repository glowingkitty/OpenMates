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
  /**
   * The embed ID (without "embed:" prefix) when this snippet comes from an embed.
   * Used to dispatch an embedfullscreen event when the user clicks the snippet,
   * opening the embed and highlighting the matched text inside it.
   * Undefined for regular message text snippets.
   */
  embedId?: string;
  /**
   * The normalized embed type (e.g., "web-website-group", "code-code") when this
   * snippet comes from an embed. Passed to the embedfullscreen event so ActiveChat
   * can select the correct fullscreen component.
   * Undefined for regular message text snippets.
   */
  embedType?: string;
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
/**
 * Maximum number of message snippets to show per chat.
 * Raised to 5 so results from multiple messages can all appear.
 */
const MAX_SNIPPETS_PER_CHAT = 5;
/**
 * Maximum snippets shown from a single message.
 * Caps how many embed variants of the same message are shown,
 * so different messages each get representation in the results.
 */
const MAX_SNIPPETS_PER_MESSAGE = 2;
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
 * Fields to SKIP during generic recursive extraction — these are internal
 * identifiers, hashes, timestamps, UUIDs, and metadata fields that add noise
 * to search results without containing meaningful user-readable text.
 */
const EMBED_SKIP_FIELDS = new Set([
  "embed_id",
  "parent_embed_id",
  "embed_ids",
  "hashed_chat_id",
  "hashed_message_id",
  "hashed_task_id",
  "hashed_user_id",
  "content_hash",
  "encryption_mode",
  "vault_key_id",
  "status",
  "result_count",
  "text_length_chars",
  "version_number",
  "is_private",
  "is_shared",
  "file_path",
  "created_at",
  "updated_at",
  "createdAt",
  "updatedAt",
  "word_count",
  "rows",
  "cols",
  "line_count",
  "cell_count",
  "app_id",
  "skill_id", // These are internal IDs, not user-visible text
  // Image / media URLs that aren't useful for text search
  "favicon",
  "meta_url_favicon",
  "image",
  "thumbnail",
  "thumbnail_original",
  "thumbnail_small",
  "thumbnail_medium",
  "thumbnail_large",
  "channel_thumbnail",
  "channel_id",
  "video_id",
  // Numeric/location fields
  "lat",
  "lon",
  "precise_lat",
  "precise_lon",
  "zoom",
  "duration_seconds",
  "view_count",
  "like_count",
]);

/**
 * Recursively collect all meaningful string values from a decoded embed object.
 * This generic approach handles any embed type regardless of field names or nesting depth.
 *
 * The backend's _flatten_for_toon_tabular creates arbitrary field names like
 * "library_id", "library_title", "meta_url_description" — rather than maintaining
 * an exhaustive per-type field list, we walk the whole tree and collect strings.
 *
 * We use a budget to avoid spending all characters on one deeply-nested field.
 * Longer strings (documentation, descriptions) get a higher per-field cap.
 */
function collectEmbedStrings(
  obj: unknown,
  budget: number,
  depth: number = 0,
): string[] {
  if (budget <= 0 || depth > 5) return [];
  if (obj === null || obj === undefined) return [];

  const parts: string[] = [];

  if (typeof obj === "string") {
    const trimmed = obj.trim();
    if (trimmed.length < 3) return []; // Skip very short strings (single chars, IDs)
    // Skip pure URLs (not useful for keyword search unless they're short domain refs)
    if (
      trimmed.startsWith("http") &&
      !trimmed.includes(" ") &&
      trimmed.length > 80
    )
      return [];
    // Skip base64-looking strings
    if (/^[A-Za-z0-9+/]{40,}={0,2}$/.test(trimmed)) return [];
    // Limit per-field to avoid one giant field consuming the whole budget
    const fieldCap = Math.min(budget, depth === 0 ? 1200 : 400);
    parts.push(trimmed.slice(0, fieldCap));
  } else if (Array.isArray(obj)) {
    // For arrays, limit to first 10 items to avoid huge web-search result sets
    for (const item of obj.slice(0, 10)) {
      if (budget <= 0) break;
      const sub = collectEmbedStrings(item, Math.min(budget, 300), depth + 1);
      for (const s of sub) {
        parts.push(s);
        budget -= s.length;
      }
    }
  } else if (typeof obj === "object") {
    for (const [key, value] of Object.entries(obj)) {
      if (budget <= 0) break;
      if (EMBED_SKIP_FIELDS.has(key)) continue;
      const sub = collectEmbedStrings(value, Math.min(budget, 600), depth + 1);
      for (const s of sub) {
        parts.push(s);
        budget -= s.length;
      }
    }
  }

  return parts;
}

/**
 * Extract a searchable plaintext string from a decoded embed content object.
 * Returns null if no meaningful text can be extracted.
 *
 * Uses a generic recursive walker (collectEmbedStrings) that handles any embed type
 * regardless of TOON field name flattening (e.g. library_title, meta_url_description).
 * Text is truncated to MAX_EMBED_TEXT_CHARS to keep RAM usage bounded.
 *
 * @param _embedType - Normalized embed type (unused; kept for future type-specific overrides)
 * @param decoded    - Decoded JS object from TOON content
 */
function extractTextFromEmbed(
  _embedType: string,
  decoded: Record<string, unknown>,
): string | null {
  if (!decoded || typeof decoded !== "object") return null;

  const strings = collectEmbedStrings(decoded, MAX_EMBED_TEXT_CHARS);
  if (strings.length === 0) return null;

  const combined = strings.join(" ").replace(/\s+/g, " ").trim();
  return combined.slice(0, MAX_EMBED_TEXT_CHARS) || null;
}

/**
 * Resolve embed content for a single embed_id and return extracted searchable text.
 * Uses embedStore (IndexedDB + memory cache) to load encrypted embed content.
 * All decryption happens client-side — no plaintext ever leaves the device.
 *
 * Handles composite embeds: when the decoded content has an `embed_ids` array (e.g.,
 * web search results where each result is a separate child embed), this function
 * also loads and extracts text from each child embed and concatenates it.
 * This is critical for web/news/maps search results where the parent embed only
 * contains metadata ({app_id, skill_id, result_count, embed_ids}) and the actual
 * searchable text lives in the child website/place/event embeds.
 *
 * Returns null if the embed is unavailable, still processing, or has no useful text.
 *
 * @param embedId        - The embed identifier (without "embed:" prefix)
 * @param embedType      - The embed type from the JSON reference block (e.g., "app_skill_use")
 * @param _referenceData - Optional extra data from the JSON reference block (may include query)
 */
async function resolveEmbedText(
  embedId: string,
  embedType: string,
  _referenceData?: Record<string, unknown>,
): Promise<{ text: string; sourceLabel: string; embedType: string } | null> {
  try {
    // Lazy-load the heavy embedStore and TOON decoder only when needed.
    // Both are imported here (inside the function) to avoid a circular dependency,
    // since embedResolver imports searchService indirectly via the store chain.
    const { embedStore } = await import("./embedStore");
    const { decodeToonContent } = await import("./embedResolver");

    // Normalize the embed type for consistent label lookup.
    // Server uses underscores ("app_skill_use"), frontend uses hyphens ("app-skill-use").
    const normalizedType = embedType.replace(/_/g, "-");

    // Load from IndexedDB / memory cache — does NOT trigger a WebSocket request.
    // If the embed isn't available locally, we simply skip it (it won't be in the index).
    const embedData = await embedStore.get(`embed:${embedId}`);
    if (!embedData || embedData.status === "processing") {
      return null;
    }

    const allParts: string[] = [];

    // Extract query from the JSON reference block if present (e.g., "query":"Twilio").
    // This is stored directly in the message markdown reference, separate from the embed.
    if (_referenceData?.query && typeof _referenceData.query === "string") {
      allParts.push(_referenceData.query);
    }

    // Decode parent embed TOON content
    if (embedData.content) {
      const decoded = await decodeToonContent(embedData.content);
      if (decoded) {
        const parentText = extractTextFromEmbed(normalizedType, decoded);
        if (parentText) allParts.push(parentText);

        // COMPOSITE EMBEDS: if embed_ids is present, this is a parent embed (e.g., web search,
        // news search, maps search). The actual searchable content lives in the CHILD embeds —
        // the parent only has metadata like {app_id, skill_id, result_count, embed_ids, query}.
        // Load each child embed and extract its text.
        const embedIds: string[] = Array.isArray(decoded.embed_ids)
          ? decoded.embed_ids
          : [];

        if (embedIds.length > 0) {
          // Limit to first 10 child embeds to bound the async work during warm-up
          for (const childId of embedIds.slice(0, 10)) {
            try {
              const childData = await embedStore.get(`embed:${childId}`);
              if (
                !childData ||
                !childData.content ||
                childData.status === "processing"
              )
                continue;

              const childDecoded = await decodeToonContent(childData.content);
              if (!childDecoded) continue;

              // Child type comes from the child embed's stored type, not the parent reference
              const childType = (
                childData.type ||
                childData.embed_type ||
                ""
              ).replace(/_/g, "-");
              const childText = extractTextFromEmbed(childType, childDecoded);
              if (childText) allParts.push(childText);
            } catch {
              // Skip individual child embed failures silently
            }
          }
        }
      }
    }

    if (allParts.length === 0) return null;

    const combined = allParts
      .join(" ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, MAX_EMBED_TEXT_CHARS);
    if (!combined) return null;

    // Determine the human-readable source label for this embed type
    const sourceLabel = EMBED_TYPE_LABELS[normalizedType] || "Embed";

    return { text: combined, sourceLabel, embedType: normalizedType };
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
    /** The embed ID (without "embed:" prefix) when this entry is from an embed */
    embedId?: string;
    /** The normalized embed type (e.g., "web-website-group", "code-code") for fullscreen dispatch */
    embedType?: string;
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
      embedId?: string;
      embedType?: string;
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
          // Pass the full ref object as _referenceData so resolveEmbedText can
          // extract the "query" field stored directly in the message markdown
          // (e.g., the search term the user typed for a web/news/code search).
          const result = await resolveEmbedText(ref.embed_id, ref.type, ref);
          if (!result) continue;

          entries.push({
            messageId: msg.message_id,
            content: result.text,
            createdAt: msg.created_at,
            embedSourceLabel: result.sourceLabel,
            // Store embed ID and type so clicking the search result can open the embed
            embedId: ref.embed_id,
            embedType: result.embedType,
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
    embedId?: string;
    embedType?: string;
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
    const result = await resolveEmbedText(ref.embed_id, ref.type, ref);
    if (!result) continue;
    newEntries.push({
      messageId: message.message_id,
      content: result.text,
      createdAt: message.created_at,
      embedSourceLabel: result.sourceLabel,
      embedId: ref.embed_id,
      embedType: result.embedType,
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
 * Returns up to MAX_SNIPPETS_PER_CHAT snippet matches across distinct messages,
 * with at most MAX_SNIPPETS_PER_MESSAGE snippets from any single message.
 * Preferring message-text matches over embed matches (message text shown first).
 *
 * Embed-sourced snippets include an embedSourceLabel so the results UI can show
 * "Found in: Web page" / "Found in: Code" context labels, and an embedId so
 * clicking the result opens the embed fullscreen view.
 */
function searchMessagesInChat(
  chatId: string,
  query: string,
): MessageMatchSnippet[] {
  const entries = messageIndex.get(chatId);
  if (!entries) return [];

  const snippets: MessageMatchSnippet[] = [];
  // Count how many snippets we've already emitted for each message ID
  const snippetsPerMessage = new Map<string, number>();
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

    // Cap how many snippets come from the same message (prevents one embed-heavy
    // message from consuming all result slots and hiding other messages)
    const countForMsg = snippetsPerMessage.get(entry.messageId) ?? 0;
    if (countForMsg >= MAX_SNIPPETS_PER_MESSAGE) continue;

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
      embedId: entry.embedId,
      embedType: entry.embedType,
    });
    snippetsPerMessage.set(entry.messageId, countForMsg + 1);
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
