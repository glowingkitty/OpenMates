// frontend/packages/ui/src/services/searchService.ts
// Core search engine service for offline full-text search across chats, messages, and settings.
// Uses an in-memory index (Option D: Hybrid warm cache) for E2E encryption compatibility.
// All data lives in RAM only — nothing is persisted to disk as plaintext.

import type { Chat, Message } from "../types/chat";
import { chatDB } from "./db";
import { chatMetadataCache } from "./chatMetadataCache";
import {
  getSettingsSearchCatalog,
  type SettingsCatalogEntry,
} from "./searchSettingsCatalog";

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

/** A settings search result */
export interface SettingsSearchResult {
  entry: SettingsCatalogEntry;
  /** The resolved label text (translated) */
  label: string;
  /** The resolved icon name */
  icon: string | null;
}

/** Complete search results across all categories */
export interface SearchResults {
  /** Chats with title or message matches, sorted by relevance then recency */
  chats: ChatSearchResult[];
  /** Settings pages that match the query */
  settings: SettingsSearchResult[];
  /** Total number of matches across all categories */
  totalCount: number;
  /** Whether the search index is still warming up (first search may need message decryption) */
  isWarmingUp: boolean;
}

// --- Configuration ---

/** Number of characters to show before and after a match in message snippets */
const SNIPPET_CONTEXT_CHARS = 30;
/** Maximum number of message snippets to show per chat */
const MAX_SNIPPETS_PER_CHAT = 3;

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
 * Index messages for a single chat by decrypting from IndexedDB.
 * This is called lazily when a chat's messages are needed for search.
 * @param chatId - The chat ID to index
 */
async function indexChatMessages(chatId: string): Promise<void> {
  if (indexedChatIds.has(chatId)) return;

  try {
    const messages = await chatDB.getMessagesForChat(chatId);
    const entries = messages
      .filter(
        (msg) =>
          msg.content &&
          typeof msg.content === "string" &&
          msg.content.trim().length > 0,
      )
      .map((msg) => ({
        messageId: msg.message_id,
        content: msg.content as string,
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
 * Warm up the search index by pre-decrypting messages for all available chats.
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
    content: message.content,
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
function findMatchRanges(
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
 * Produces text like "... words before **match** words after ..."
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

  // Add ellipsis for truncated context
  if (contextStart > 0) {
    // Find the nearest word boundary after contextStart to avoid cutting words
    const firstSpace = snippet.indexOf(" ");
    if (firstSpace > 0 && firstSpace < snippetMatchStart) {
      snippet = snippet.slice(firstSpace + 1);
      snippetMatchStart -= firstSpace + 1;
    }
    snippet = "... " + snippet;
    snippetMatchStart += 4; // Account for "... " prefix
  }
  if (contextEnd < content.length) {
    // Find the nearest word boundary before the end
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
 * @param query - Search query string
 * @param textFn - Translation function ($text)
 * @returns Array of matching settings entries
 */
function searchSettings(
  query: string,
  textFn: (key: string) => string,
): SettingsSearchResult[] {
  const catalog = getSettingsSearchCatalog();
  const lowerQuery = query.toLowerCase();
  const results: SettingsSearchResult[] = [];

  for (const entry of catalog) {
    const label = textFn(entry.translationKey);
    const lowerLabel = label.toLowerCase();

    // Check label match
    if (lowerLabel.includes(lowerQuery)) {
      results.push({ entry, label, icon: entry.icon });
      continue;
    }

    // Check keyword matches
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
 * Main search function. Searches across all chats, messages, and settings.
 *
 * Performance characteristics (100 chats, ~5000 messages):
 * - Chat titles: <5ms (already in chatMetadataCache)
 * - Messages (warm index): <15ms (string matching in RAM)
 * - Messages (cold - first search): 200-500ms (batch decrypt from IndexedDB)
 * - Settings: <1ms (static catalog)
 *
 * @param query - The search query (minimum 1 character)
 * @param chats - Array of all available chats (from Chats.svelte's allChats derived)
 * @param textFn - Translation function ($text) for settings labels and i18n
 * @param hiddenChats - Optional array of hidden chats to include in search (only when unlocked)
 * @returns SearchResults with categorized matches
 */
export async function search(
  query: string,
  chats: Chat[],
  textFn: (key: string) => string,
  hiddenChats: Chat[] = [],
): Promise<SearchResults> {
  if (!query || query.trim().length === 0) {
    return { chats: [], settings: [], totalCount: 0, isWarmingUp: false };
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
    // Get decrypted title from cache
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    const decryptedTitle = metadata?.title || chat.title || null;

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
    // Title matches rank higher
    if (a.titleMatch && !b.titleMatch) return -1;
    if (!a.titleMatch && b.titleMatch) return 1;
    // Then sort by last_edited_overall_timestamp (most recent first)
    return (
      b.chat.last_edited_overall_timestamp -
      a.chat.last_edited_overall_timestamp
    );
  });

  // Search settings
  const settingsResults = searchSettings(trimmedQuery, textFn);

  const totalCount = chatResults.length + settingsResults.length;

  return {
    chats: chatResults,
    settings: settingsResults,
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
