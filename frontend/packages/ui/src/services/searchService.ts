// frontend/packages/ui/src/services/searchService.ts
// Core search engine service for offline full-text search across chats, messages, settings,
// apps, skills, focus modes, and memories.
// Uses an in-memory index (Option D: Hybrid warm cache) for E2E encryption compatibility.
// All data lives in RAM only — nothing is persisted to disk as plaintext.

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

// --- In-Memory Search Index ---

/**
 * Stores decrypted message content for searching.
 * Key: chatId, Value: array of { messageId, content, createdAt }
 * This data is RAM-only and cleared when the page unloads.
 */
const messageIndex = new Map<
  string,
  Array<{
    messageId: string;
    content: string;
    createdAt: number;
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
 * Index messages for a single authenticated user chat by decrypting from IndexedDB.
 * For demo/public chats, use getDemoMessages() instead.
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

    const entries = messages
      .filter(
        (msg) =>
          msg.content &&
          typeof msg.content === "string" &&
          msg.content.trim().length > 0,
      )
      .map((msg) => ({
        messageId: msg.message_id,
        // Strip markdown so snippets display clean plaintext without ** / ## / etc.
        content: stripMarkdown(msg.content as string),
        createdAt: msg.created_at,
      }));

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
 * Add or update a single message in the search index.
 * Called when new messages arrive via WebSocket.
 * @param chatId - The chat ID the message belongs to
 * @param message - The decrypted message to add
 */
export function addMessageToIndex(chatId: string, message: Message): void {
  if (!message.content || typeof message.content !== "string") return;

  const existing = messageIndex.get(chatId) || [];

  // Check for duplicate (update if exists)
  const idx = existing.findIndex((m) => m.messageId === message.message_id);
  const entry = {
    messageId: message.message_id,
    content: stripMarkdown(message.content),
    createdAt: message.created_at,
  };

  if (idx !== -1) {
    existing[idx] = entry;
  } else {
    existing.push(entry);
  }

  messageIndex.set(chatId, existing);
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
 * Search messages in a single chat.
 * Returns up to MAX_SNIPPETS_PER_CHAT snippet matches.
 */
function searchMessagesInChat(
  chatId: string,
  query: string,
): MessageMatchSnippet[] {
  const messages = messageIndex.get(chatId);
  if (!messages) return [];

  const snippets: MessageMatchSnippet[] = [];
  const lowerQuery = query.toLowerCase();

  // Search messages from newest to oldest (most relevant first)
  const sortedMessages = [...messages].sort(
    (a, b) => b.createdAt - a.createdAt,
  );

  for (const msg of sortedMessages) {
    if (snippets.length >= MAX_SNIPPETS_PER_CHAT) break;

    const lowerContent = msg.content.toLowerCase();
    const idx = lowerContent.indexOf(lowerQuery);
    if (idx === -1) continue;

    const { snippet, snippetMatchStart, snippetMatchLength } = buildSnippet(
      msg.content,
      idx,
      query.length,
    );

    snippets.push({
      messageId: msg.messageId,
      chatId,
      snippet,
      matchStart: snippetMatchStart,
      matchLength: snippetMatchLength,
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
