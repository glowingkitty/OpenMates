// frontend/packages/ui/src/services/searchService.ts
// Core search engine service for offline full-text search across chats, messages, settings,
// apps, skills, focus modes, and memories.
// Uses an in-memory index (Option D: Hybrid warm cache) for zero-knowledge encryption compatibility.
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
  isPublicChat,
  isExampleChat,
  getExampleChatEmbed,
  INTRO_CHATS,
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
  /** App ID associated with embed content when available (used for app icon rendering) */
  embedAppId?: string;
  /** Skill ID associated with embed content when available (used for skill icon rendering) */
  embedSkillId?: string;
  /** Focus mode ID for focus-mode activation embeds (e.g., "jobs-career_insights") */
  embedFocusId?: string;
  /** Focus mode display name or translation key from embed payload */
  embedFocusModeName?: string;
  /** Whether this focus mode is currently active for the chat (computed at search time) */
  embedFocusIsActive?: boolean;
}

/** A single metadata snippet showing context around a search match in summary, tags, or draft preview */
export interface MetadataMatchSnippet {
  chatId: string;
  /** The snippet text with context words around the match */
  snippet: string;
  /** Start index of the match within the snippet (for highlighting) */
  matchStart: number;
  /** Length of the matched text within the snippet */
  matchLength: number;
  /** Where the match was found */
  matchSource: "summary" | "tags" | "draft";
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
  /** Metadata matches (summary/tags) for this chat — used for metadata-only chats */
  metadataSnippets: MetadataMatchSnippet[];
}

/** A locally indexed embed that can be opened from the message input. */
export interface EmbedSearchResult {
  embedId: string;
  embedType: string;
  chatId: string;
  messageId: string;
  title: string;
  subtitle: string;
  appId?: string;
  createdAt: number;
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
  entryType: "app" | "skill" | "focus_mode";
}

/** Complete search results across all categories */
export interface SearchResults {
  /** Chats with title or message matches, sorted by relevance then recency */
  chats: ChatSearchResult[];
  /** Capped exact embed matches, populated only when requested by the composer. */
  embeds: EmbedSearchResult[];
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

/**
 * Maximum characters to extract from a single embed for search indexing.
 * Caps RAM usage per embed — a typical web page scrape can be 10k+ chars.
 */
const MAX_EMBED_TEXT_CHARS = 1500;
const MAX_CHILD_EMBEDS_TO_INDEX = 50;
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

function embedDisplayTitle(decoded: Record<string, unknown>, fallback: string): string {
  for (const field of ['title', 'name', 'filename', 'route_display', 'query', 'search_query']) {
    const value = decoded[field];
    if (typeof value === 'string' && value.trim()) return value.trim().slice(0, 140);
  }
  return fallback;
}

function compactChildSearchText(decoded: Record<string, unknown>, title: string): string {
  const fields = [
    title, decoded.venue_name, decoded.venue_city, decoded.location,
    decoded.provider, decoded.date_start, decoded.description,
  ];
  return fields.filter((value): value is string => typeof value === 'string' && !!value.trim())
    .join(' ').replace(/\s+/g, ' ').slice(0, 320);
}

function parseChildEmbedIds(value: unknown): string[] {
  const values = Array.isArray(value) ? value : typeof value === 'string' ? value.split('|') : [];
  return values.filter((id): id is string => typeof id === 'string' && id.trim().length > 0);
}

function previewChildMetadata(
  preview: unknown,
  embedId: string,
  embedType: string,
): { embedId: string; embedType: string; title: string; text: string } | null {
  if (!preview || typeof preview !== 'object' || Array.isArray(preview)) return null;
  const record = preview as Record<string, unknown>;
  const title = embedDisplayTitle(record, '');
  if (!title) return null;
  return { embedId, embedType, title, text: compactChildSearchText(record, title) };
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
  sourceChatId?: string,
): Promise<{
  text: string;
  title: string;
  sourceLabel: string;
  embedType: string;
  children: Array<{ embedId: string; embedType: string; title: string; text: string }>;
  appId?: string;
  skillId?: string;
  focusId?: string;
  focusModeName?: string;
} | null> {
  try {
    // Normalize the embed type for consistent label lookup.
    // Server uses underscores ("app_skill_use"), frontend uses hyphens ("app-skill-use").
    const normalizedType = embedType.replace(/_/g, "-");

    const getEmbedMeta = (decoded: Record<string, unknown>) => ({
      appId:
        typeof decoded.app_id === "string" && decoded.app_id.trim().length > 0
          ? decoded.app_id
          : undefined,
      skillId:
        typeof decoded.skill_id === "string" &&
        decoded.skill_id.trim().length > 0
          ? decoded.skill_id
          : undefined,
      focusId:
        typeof decoded.focus_id === "string" &&
        decoded.focus_id.trim().length > 0
          ? decoded.focus_id
          : undefined,
      focusModeName:
        typeof decoded.focus_mode_name === "string" &&
        decoded.focus_mode_name.trim().length > 0
          ? decoded.focus_mode_name
          : undefined,
    });

    // --- Example chat embed path (unauthenticated users) ---
    // Example chat embeds live in exampleChatStore (cleartext, separate from embedStore),
    // but their content is still TOON-encoded like regular embed rows.
    const demoEmbed = getExampleChatEmbed(embedId, sourceChatId);
    if (demoEmbed) {
      try {
        const { decodeToonContent } = await import("./embedResolver");
        const decoded = await decodeToonContent(demoEmbed.content) as Record<string, unknown> | null;
        if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) return null;
        const text = extractTextFromEmbed(normalizedType, decoded);
        if (!text) return null;
        const sourceLabel = EMBED_TYPE_LABELS[normalizedType] || "Embed";
        const children: Array<{ embedId: string; embedType: string; title: string; text: string }> = [];
        const previews = Array.isArray(decoded.preview_results) ? decoded.preview_results : [];
        const exampleChildIds = parseChildEmbedIds(decoded.embed_ids ?? demoEmbed.embed_ids).slice(0, MAX_CHILD_EMBEDS_TO_INDEX);
        for (let index = 0; index < exampleChildIds.length; index++) {
          const childId = exampleChildIds[index];
          const child = getExampleChatEmbed(childId, sourceChatId);
          if (!child) continue;
          const preview = previewChildMetadata(previews[index], childId, child.type.replace(/_/g, '-'));
          if (preview) {
            children.push(preview);
            continue;
          }
          const childDecoded = await decodeToonContent(child.content) as Record<string, unknown> | null;
          if (!childDecoded || typeof childDecoded !== "object" || Array.isArray(childDecoded)) continue;
          const childType = String(child.type || "").replace(/_/g, "-");
          const childTitle = embedDisplayTitle(childDecoded, EMBED_TYPE_LABELS[childType] || "Embed");
          children.push({
            embedId: childId,
            embedType: childType,
            title: childTitle,
            text: compactChildSearchText(childDecoded, childTitle),
          });
        }
        return {
          text,
          title: embedDisplayTitle(decoded, sourceLabel),
          sourceLabel,
          embedType: normalizedType,
          children,
          ...getEmbedMeta(decoded),
        };
      } catch (parseError) {
        console.debug(
          `[SearchService] Could not parse demo embed ${embedId} content:`,
          parseError instanceof Error ? parseError.message : String(parseError),
        );
        return null;
      }
    }

    // --- Authenticated user embed path ---
    // Lazy-load the heavy embedStore and TOON decoder only when needed.
    // Both are imported here (inside the function) to avoid a circular dependency,
    // since embedResolver imports searchService indirectly via the store chain.
    const { embedStore } = await import("./embedStore");
    const { decodeToonContent } = await import("./embedResolver");

    // Load from IndexedDB / memory cache — does NOT trigger a WebSocket request.
    // If the embed isn't available locally, we simply skip it (it won't be in the index).
    const embedData = await embedStore.get(`embed:${embedId}`);
    if (!embedData || typeof embedData === "string") {
      return null;
    }
    // embedData is now guaranteed to be Record<string, unknown>
    if (embedData.status === "processing") {
      return null;
    }

    const allParts: string[] = [];
    const children: Array<{ embedId: string; embedType: string; title: string; text: string }> = [];
    let title = EMBED_TYPE_LABELS[normalizedType] || 'Embed';
    let parentEmbedMeta: {
      appId?: string;
      skillId?: string;
      focusId?: string;
      focusModeName?: string;
    } = {
      appId:
        typeof _referenceData?.app_id === "string"
          ? (_referenceData.app_id as string)
          : undefined,
      skillId:
        typeof _referenceData?.skill_id === "string"
          ? (_referenceData.skill_id as string)
          : undefined,
      focusId:
        typeof _referenceData?.focus_id === "string"
          ? (_referenceData.focus_id as string)
          : undefined,
      focusModeName:
        typeof _referenceData?.focus_mode_name === "string"
          ? (_referenceData.focus_mode_name as string)
          : undefined,
    };

    // Extract query from the JSON reference block if present (e.g., "query":"Twilio").
    // This is stored directly in the message markdown reference, separate from the embed.
    if (_referenceData?.query && typeof _referenceData.query === "string") {
      allParts.push(_referenceData.query);
    }

    // Decode parent embed TOON content
    if (embedData.content) {
      const decoded = await decodeToonContent(embedData.content as string);
      if (decoded) {
        const decodedRecord = decoded as Record<string, unknown>;
        parentEmbedMeta = getEmbedMeta(decodedRecord);
        title = embedDisplayTitle(decodedRecord, title);
        const parentText = extractTextFromEmbed(normalizedType, decodedRecord);
        if (parentText) allParts.push(parentText);

        // COMPOSITE EMBEDS: if embed_ids is present, this is a parent embed (e.g., web search,
        // news search, maps search). The actual searchable content lives in the CHILD embeds —
        // the parent only has metadata like {app_id, skill_id, result_count, embed_ids, query}.
        // Load each child embed and extract its text.
        const embedIds = parseChildEmbedIds(decodedRecord.embed_ids ?? embedData.embed_ids);
        const previews = Array.isArray(decodedRecord.preview_results) ? decodedRecord.preview_results : [];

        if (embedIds.length > 0) {
          // Index concise child metadata once, in bounded batches. Parent full-text
          // search keeps its old first-ten limit and 1,500-character RAM budget.
          for (let offset = 0; offset < Math.min(embedIds.length, MAX_CHILD_EMBEDS_TO_INDEX); offset += 5) {
            const batch = embedIds.slice(offset, offset + 5);
            const loaded = await Promise.all(batch.map(async (childId, batchIndex) => {
              const childIndex = offset + batchIndex;
              const preview = previewChildMetadata(previews[childIndex], childId, '');
              // The parent already carries one compact metadata row per result.
              // Use it for later children without decrypting every child upfront.
              if (childIndex >= 10 && preview) return preview;
              try {
                const childData = await embedStore.get(`embed:${childId}`);
                if (
                  !childData ||
                  typeof childData === "string" ||
                  !childData.content ||
                  childData.status === "processing"
                ) return preview;

                const childDecoded = await decodeToonContent(childData.content as string);
                if (!childDecoded || typeof childDecoded !== "object" || Array.isArray(childDecoded)) return preview;

                // Child type comes from the child embed's stored type, not the parent reference.
                const childType = (
                  (childData.type as string) ||
                  (childData.embed_type as string) ||
                  ""
                ).replace(/_/g, "-");
                const childRecord = childDecoded as Record<string, unknown>;
                const childTitle = embedDisplayTitle(childRecord, EMBED_TYPE_LABELS[childType] || "Embed");
                const childText = compactChildSearchText(childRecord, childTitle);
                if (!childText) return preview;
                return { embedId: childId, embedType: childType, title: childTitle, text: childText };
              } catch {
                // Skip individual child embed failures silently.
                return preview;
              }
            }));
            for (const child of loaded) {
              if (!child) continue;
              children.push(child);
              if (offset < 10) allParts.push(child.text);
            }
            if (offset + 5 < Math.min(embedIds.length, MAX_CHILD_EMBEDS_TO_INDEX)) {
              await new Promise((resolve) => setTimeout(resolve, 0));
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

    return {
      text: combined,
      title,
      sourceLabel,
      embedType: normalizedType,
      children,
      ...parentEmbedMeta,
    };
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
const MAX_CONCURRENT_INDEX_JOBS = 5;
export type SearchEntries = Array<{
    messageId: string;
    content: string;
    createdAt: number;
    /** Present when this entry represents embed content rather than raw message text */
    embedSourceLabel?: string;
    /** The embed ID (without "embed:" prefix) when this entry is from an embed */
    embedId?: string;
    /** The normalized embed type (e.g., "web-website-group", "code-code") for fullscreen dispatch */
    embedType?: string;
    embedTitle?: string;
    embedSubtitle?: string;
    /** Embed app identifier (for icon rendering in search snippets) */
    embedAppId?: string;
    /** Embed skill identifier when present (for secondary icon rendering) */
    embedSkillId?: string;
    /** Focus mode identifier for focus-mode activation embeds */
    embedFocusId?: string;
    /** Focus mode display name/translation key from embed payload */
    embedFocusModeName?: string;
  }>;
let activeIndexJobs = 0;
const indexWaiters: Array<() => void> = [];

/** Re-read a chat after its messages change, including newly arrived embeds. */
export function invalidateChatSearchIndex(chatId: string): void {
  rustSearch?.invalidateRustChat(chatId);
}
let indexGeneration = 0;

/** buildChatMessageIndex plus a performance measure (both arms of the paired search bench read it). */
async function measuredBuild(chatId: string, generation: number): Promise<SearchEntries> {
  const start = performance.now();
  const entries = await buildChatMessageIndex(chatId, generation);
  performance.measure("openmates:search:build", { start, end: performance.now(), detail: { entries: entries.length } });
  return entries;
}


/**
 * Metadata search index for expanded search (chats 101–1000).
 * Stores decrypted summary, tags, and draft previews for metadata-only chats so they
 * can be searched without loading messages from the server.
 *
 * Key: chatId, Value: { summary, tags, draftPreview } — already decrypted plaintext.
 */
const metadataIndex = new Map<
  string,
  { summary: string | null; tags: string[] | null; draftPreview: string | null }
>();

/** Track which chats have had their metadata indexed */
const indexedMetadataChatIds = new Set<string>();

/** Flag to track if warm-up is in progress */
let warmUpInProgress = false;

/** Flag to track if metadata warm-up is in progress */
let metadataWarmUpInProgress = false;

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
async function buildChatMessageIndex(chatId: string, generation: number): Promise<SearchEntries> {

  try {
    let messages: Message[];

    if (isPublicChat(chatId)) {
      // Public chats (demo, legal, example, newsletter) have messages in-memory, NOT in chatDB
      // getDemoMessages handles all four cases (including newsletter via ALL_NEWSLETTER_CHATS)
      messages = getDemoMessages(chatId, INTRO_CHATS);
    } else {
      // Authenticated user chats — decrypt from IndexedDB
      messages = await chatDB.getMessagesForChat(chatId);
    }

    const entries: SearchEntries = [];

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
      //    Example chats have real embeds (cleartext, stored in exampleChatStore).
      //    Static intro chats and legal chats only have inline text, no embed references.
      //    Authenticated user chats have encrypted embeds resolved via embedStore.
      const hasChatEmbeds =
        isExampleChat(chatId) ||
        (!isPublicChat(chatId));
      if (hasChatEmbeds) {
        const embedRefs = extractEmbedReferences(rawContent);
        for (const ref of embedRefs) {
          // Pass the full ref object as _referenceData so resolveEmbedText can
          // extract the "query" field stored directly in the message markdown
          // (e.g., the search term the user typed for a web/news/code search).
          const result = await resolveEmbedText(ref.embed_id, ref.type, ref, chatId);
          if (!result) continue;

          entries.push({
            messageId: msg.message_id,
            content: result.text,
            createdAt: msg.created_at,
            embedSourceLabel: result.sourceLabel,
            // Store embed ID and type so clicking the search result can open the embed
            embedId: ref.embed_id,
            embedType: result.embedType,
            embedTitle: result.title,
            embedSubtitle: result.sourceLabel,
            embedAppId: result.appId,
            embedSkillId: result.skillId,
            embedFocusId: result.focusId,
            embedFocusModeName: result.focusModeName,
          });
          for (const child of result.children) {
            entries.push({
              messageId: msg.message_id,
              content: child.text,
              createdAt: msg.created_at,
              embedSourceLabel: EMBED_TYPE_LABELS[child.embedType] || result.sourceLabel,
              embedId: child.embedId,
              embedType: child.embedType,
              embedTitle: child.title,
              embedSubtitle: EMBED_TYPE_LABELS[child.embedType] || result.sourceLabel,
              embedAppId: result.appId,
              embedSkillId: result.skillId,
            });
          }
        }
      }
    }

    if (generation !== indexGeneration) return [];
    // indexChatInRustUnit transfers the entries to the Worker index (it sorts them); the page keeps no copy.
    return entries;
  } catch (error) {
    console.error(
      `[SearchService] Error indexing messages for chat ${chatId}:`,
      error,
    );
    return [];
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
  const generation = indexGeneration;

  console.debug(
    `[SearchService] Warming up search index for ${chatIds.length} chats...`,
  );
  const startTime = performance.now();

  try {
    // Process chats in small batches to avoid blocking the main thread
    const BATCH_SIZE = 5;
    for (let i = 0; i < chatIds.length; i += BATCH_SIZE) {
      if (generation !== indexGeneration) break;
      const batch = chatIds.slice(i, i + BATCH_SIZE);
      await Promise.all(batch.map((chatId) => indexChatInRustUnit(chatId)));

      // Yield to the event loop between batches so UI stays responsive
      if (i + BATCH_SIZE < chatIds.length) {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }

    const elapsed = performance.now() - startTime;
    performance.measure("openmates:search:warmup", { start: startTime, end: performance.now(), detail: { chats: chatIds.length } });
    console.debug(
      `[SearchService] Search index warmed up in ${elapsed.toFixed(0)}ms (${chatIds.length} chats)`,
    );
  } catch (error) {
    console.error("[SearchService] Error during search index warm-up:", error);
  } finally {
    if (generation === indexGeneration) warmUpInProgress = false;
  }
}

/**
 * Index metadata (summary, tags) for a single chat.
 * Used for metadata-only chats that don't have messages in IndexedDB.
 * Decrypts via chatMetadataCache which handles key management.
 *
 * @param chat - The chat object to index metadata for
 */
async function indexChatMetadata(chat: Chat): Promise<void> {
  if (indexedMetadataChatIds.has(chat.chat_id)) return;

  const generation = indexGeneration;
  try {
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (generation !== indexGeneration) return;
    if (metadata) {
      metadataIndex.set(chat.chat_id, {
        summary: metadata.summary,
        tags: metadata.tags,
        draftPreview: metadata.draftPreview,
      });
    }
    indexedMetadataChatIds.add(chat.chat_id);
  } catch (error) {
    console.error(
      `[SearchService] Error indexing metadata for chat ${chat.chat_id}:`,
      error,
    );
    if (generation === indexGeneration) indexedMetadataChatIds.add(chat.chat_id);
  }
}

/**
 * Warm up the metadata search index for metadata-only chats.
 * Called after metadata chats are synced from the server (Phase 4).
 * Runs in the background without blocking the UI.
 *
 * @param chats - Array of metadata-only Chat objects to warm up
 */
export async function warmUpMetadataSearchIndex(chats: Chat[]): Promise<void> {
  if (metadataWarmUpInProgress) return;
  metadataWarmUpInProgress = true;
  const generation = indexGeneration;

  const metadataOnlyChats = chats.filter(
    (c) => c.is_metadata_only && !indexedMetadataChatIds.has(c.chat_id),
  );

  if (metadataOnlyChats.length === 0) {
    metadataWarmUpInProgress = false;
    return;
  }

  console.debug(
    `[SearchService] Warming up metadata index for ${metadataOnlyChats.length} metadata-only chats...`,
  );
  const startTime = performance.now();

  try {
    // Process in batches of 10 (metadata decryption is lighter than message indexing)
    const BATCH_SIZE = 10;
    for (let i = 0; i < metadataOnlyChats.length; i += BATCH_SIZE) {
      if (generation !== indexGeneration) break;
      const batch = metadataOnlyChats.slice(i, i + BATCH_SIZE);
      await Promise.all(batch.map((chat) => indexChatMetadata(chat)));

      // Yield to the event loop between batches
      if (i + BATCH_SIZE < metadataOnlyChats.length) {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }

    const elapsed = performance.now() - startTime;
    console.debug(
      `[SearchService] Metadata index warmed up in ${elapsed.toFixed(0)}ms (${indexedMetadataChatIds.size} chats)`,
    );
  } catch (error) {
    console.error(
      "[SearchService] Error during metadata index warm-up:",
      error,
    );
  } finally {
    if (generation === indexGeneration) metadataWarmUpInProgress = false;
  }
}

// --- Rust search unit (the only search path) ---
// The shared Worker's `search` unit owns the message index and runs the search
// (rustCore/search/rustChatSearch.ts). The page builds a chat's entries from the
// source with buildChatMessageIndex, transfers them once and keeps no copy; after
// a Worker crash the next search re-indexes from the source.

let rustSearch: typeof import("./rustCore/search/rustChatSearch") | null = null;
const pendingRustIndexJobs = new Map<string, Promise<void>>();

async function loadRustSearch() {
  rustSearch ??= await import("./rustCore/search/rustChatSearch");
  return rustSearch;
}

/**
 * Called when the search bar opens, before the first query: load the
 * search unit while the user types, so the first warm-up ingest does not wait for it.
 * A failed open is reported by the search that needs the unit.
 */
export function prepareSearchBackend(): void {
  loadRustSearch().then((rust) => rust.prepareRustChatSearch()).catch((error: unknown) => {
    console.warn("[SearchService] Preparing the search unit failed:", error instanceof Error ? error.message : "unknown");
  });
}

/** Build and ingest one chat into the Worker index: same dedupe and global concurrency limit. */
async function indexChatInRustUnit(chatId: string): Promise<void> {
  const rust = await loadRustSearch();
  if (rust.isRustChatIndexed(chatId)) return;
  const pending = pendingRustIndexJobs.get(chatId);
  if (pending) return pending;
  const generation = indexGeneration;
  const epoch = rust.rustChatEpoch(chatId);
  const job = (async () => {
    if (activeIndexJobs >= MAX_CONCURRENT_INDEX_JOBS) {
      await new Promise<void>(resolve => indexWaiters.push(resolve));
    } else { activeIndexJobs++; }
    let entries: SearchEntries;
    try {
      if (generation !== indexGeneration) return;
      entries = await measuredBuild(chatId, generation);
    } finally {
      const next = indexWaiters.shift();
      if (next) next(); else activeIndexJobs--;
    }
    if (generation !== indexGeneration) return;
    await rust.ingestRustChat(chatId, entries, epoch);
  })();
  pendingRustIndexJobs.set(chatId, job);
  try { await job; } finally {
    if (pendingRustIndexJobs.get(chatId) === job) pendingRustIndexJobs.delete(chatId);
  }
}

/**
 * `search` on the Worker: the page resolves per-chat metadata exactly like the
 * TypeScript loop (I/O and decryption stay here), indexes chats on demand, then
 * one request returns ranked chats, snippets, embeds and catalog matches.
 */
async function searchViaRustUnit(
  query: string,
  chats: Chat[],
  textFn: (key: string) => string,
  isAuthenticated: boolean,
  isAdmin: boolean,
  signal: AbortSignal | undefined,
  includeEmbeds: boolean,
  warmIndexOnly: boolean,
): Promise<SearchResults> {
  const rust = await loadRustSearch();
  // Open the Worker unit while the page reads metadata and indexes chats.
  const opening = rust.prepareRustChatSearch();
  const inputs: import("./rustCore/search/rustChatSearch").RustQueryChat[] = new Array(chats.length);
  for (let offset = 0; offset < chats.length; offset += MAX_CONCURRENT_INDEX_JOBS) {
    await Promise.all(chats.slice(offset, offset + MAX_CONCURRENT_INDEX_JOBS).map(async (chat, slot) => {
      signal?.throwIfAborted();
      const input: import("./rustCore/search/rustChatSearch").RustQueryChat = {
        chatId: chat.chat_id, messages: !chat.is_metadata_only, title: null, activeFocusId: null,
        summary: null, tags: null, draft: null, lastEdited: chat.last_edited_overall_timestamp,
      };
      if (isPublicChat(chat.chat_id)) {
        input.title = chat.title || null;
      } else {
        const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
        signal?.throwIfAborted();
        input.title = metadata?.title || chat.title || null;
        input.activeFocusId = metadata?.activeFocusId || null;
        if (!chat.is_metadata_only && metadata) {
          input.summary = metadata.summary ?? null;
          input.tags = metadata.tags ?? null;
          input.draft = metadata.draftPreview ?? null;
        }
      }
      if (chat.is_metadata_only) {
        const meta = metadataIndex.get(chat.chat_id);
        input.summary = meta?.summary ?? null;
        input.tags = meta?.tags ?? null;
        input.draft = meta?.draftPreview ?? null;
      } else if (!warmIndexOnly) {
        await indexChatInRustUnit(chat.chat_id);
        signal?.throwIfAborted();
      }
      inputs[offset + slot] = input;
    }));
  }
  const settingsCatalog = getSettingsSearchCatalog();
  const settingsLabels = settingsCatalog.map((entry) => textFn(entry.translationKey));
  const appCatalog = getAppCatalog(textFn);
  await opening;
  const found = await rust.queryRustSearch({
    query, includeEmbeds, isAuthenticated, isAdmin, chats: inputs,
    settings: settingsCatalog.map((entry, index) => ({ label: settingsLabels[index], keywords: entry.keywords, access: entry.access })),
    apps: appCatalog.map((entry) => ({ label: entry.label, keywords: entry.keywords })),
  }, signal);
  const chatResults: ChatSearchResult[] = found.chats.map((hit) => ({
    chat: chats[hit.position],
    titleMatch: hit.titleMatchRanges.length > 0,
    titleMatchRanges: hit.titleMatchRanges,
    decryptedTitle: inputs[hit.position].title,
    messageSnippets: hit.messageSnippets,
    metadataSnippets: hit.metadataSnippets,
  }));
  const settingsResults: SettingsSearchResult[] = [
    ...found.settings.map((index) => ({ entry: settingsCatalog[index], label: settingsLabels[index], icon: settingsCatalog[index].icon })),
  ];
  const appCatalogResults: AppCatalogSearchResult[] = found.apps.map((index) => ({
    entry: appCatalog[index], label: appCatalog[index].label, icon: appCatalog[index].icon, entryType: appCatalog[index].entryType,
  }));
  return {
    chats: chatResults,
    embeds: found.embeds,
    settings: settingsResults,
    appCatalog: appCatalogResults,
    totalCount: chatResults.length + settingsResults.length + appCatalogResults.length,
    isWarmingUp: warmUpInProgress,
  };
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
  signal?: AbortSignal,
  includeEmbedResults = false,
): Promise<SearchResults> {
  signal?.throwIfAborted();
  if (!query || query.trim().length === 0) {
    return {
      chats: [],
      embeds: [],
      settings: [],
      appCatalog: [],
      totalCount: 0,
      isWarmingUp: false,
    };
  }

  const trimmedQuery = query.trim();
  const allSearchableChats = [...chats, ...hiddenChats];

  const metadataOnlyChats = allSearchableChats.filter(c => c.is_metadata_only);
  // During initial warm-up show cached/title matches immediately. On its refresh,
  // search evicted chats directly and keep only their snippets, never all indexes.
  const useWarmIndexOnly = warmUpInProgress;

  // Lazy-index metadata for metadata-only chats not yet indexed
  const unindexedMetadataChats = metadataOnlyChats.filter(
    (c) => !indexedMetadataChatIds.has(c.chat_id),
  );
  if (unindexedMetadataChats.length > 0) {
    await Promise.all(unindexedMetadataChats.map((c) => indexChatMetadata(c)));
    signal?.throwIfAborted();
  }

  // The shared Worker's search unit holds the message index and runs the whole search (rustCore/search/).
  return searchViaRustUnit(trimmedQuery, allSearchableChats, textFn, isAuthenticated, isAdmin, signal, includeEmbedResults, useWarmIndexOnly);
}

if (typeof window !== "undefined") {
  window.addEventListener("userLoggingOut", () => {
    indexGeneration++;
    metadataIndex.clear();
    indexedMetadataChatIds.clear();
    pendingRustIndexJobs.clear();
    metadataWarmUpInProgress = false;
    warmUpInProgress = false;
  });
}
