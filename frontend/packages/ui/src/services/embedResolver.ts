/**
 * Embed Resolver Service
 * Resolves embed references (embed_id) to actual embed content from ContentStore or Directus.
 * Handles TOON-encoded content decoding when needed.
 *
 * For example chats, embeds are stored in the exampleChatStore (cleartext).
 * This resolver checks both the regular embedStore and the example chat store.
 */

import { embedStore } from "./embedStore";
import {
  getExampleChatEmbed,
} from "../demo_chats/exampleChatStore";
import { EmbedNodeAttributes, EmbedType } from "../message_parsing/types";
import { generateUUID } from "../message_parsing/utils";
import { normalizeEmbedType } from "../data/embedRegistry.generated";
import { authStore } from "../stores/authState";
import { get } from "svelte/store";

/**
 * Tracks embed IDs that are known to be in an error or cancelled state.
 * This prevents the infinite loop where:
 *   1. resolveEmbed() finds no embed in store
 *   2. sends request_embed to server
 *   3. server responds with send_embed_data (status=error)
 *   4. client cleans up without persisting
 *   5. embedUpdated triggers re-render -> back to step 1
 *
 * By tracking error embed IDs here, resolveEmbed() can return a synthetic
 * error response instead of re-requesting from the server.
 */
const knownErrorEmbeds = new Map<
  string,
  { status: string; timestamp: number }
>();

/**
 * Mark an embed as having an error/cancelled status.
 * Called from chatSyncServiceHandlersAI when an error embed is received.
 */
export function markEmbedAsError(embedId: string, status: string): void {
  knownErrorEmbeds.set(embedId, { status, timestamp: Date.now() });
}

/**
 * Check if an embed is known to be in an error state.
 */
export function isEmbedKnownError(embedId: string): boolean {
  return knownErrorEmbeds.has(embedId);
}

/**
 * Clear error state for an embed (e.g., if it gets retried and succeeds).
 */
export function clearEmbedError(embedId: string): void {
  knownErrorEmbeds.delete(embedId);
}

// TOON decoder (will be imported when available)
// Using official @toon-format/toon package
let toonDecode:
  | ((toonString: string, options?: { strict?: boolean }) => unknown)
  | null = null;

const CODE_TOON_FOLLOWER_FIELDS = [
  "filename",
  "embed_ref",
  "status",
  "line_count",
  "code_run_output",
  "task_id",
];

function parseSimpleToonField(toonContent: string, key: string): string | undefined {
  const match = toonContent.match(new RegExp(`(?:^|\\n)${key}:\\s*([^\\n]*)`));
  if (!match) return undefined;
  const value = unquoteToonValue(match[1]);
  return value === "null" ? undefined : value;
}

function unquoteToonValue(value: string): string {
  const trimmed = value.trim();
  const quote = trimmed[0];
  const hasMatchingQuotes =
    (quote === '"' || quote === "'") && trimmed.endsWith(quote);
  const unquoted = hasMatchingQuotes ? trimmed.slice(1, -1) : trimmed;
  return unquoted
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'");
}

function parseCodeBlockFromToon(toonContent: string): string | undefined {
  const codeMatch = toonContent.match(/(?:^|\n)code:\s*/);
  if (!codeMatch || codeMatch.index === undefined) return undefined;

  const start = codeMatch.index + codeMatch[0].length;
  let end = toonContent.length;
  for (const field of CODE_TOON_FOLLOWER_FIELDS) {
    const marker = `\n${field}:`;
    const markerIndex = toonContent.indexOf(marker, start);
    if (markerIndex !== -1 && markerIndex < end) {
      end = markerIndex;
    }
  }

  const rawCode = toonContent.slice(start, end).trim();
  return rawCode ? unquoteToonValue(rawCode) : undefined;
}

export function recoverCodeEmbedFromToon(
  toonContent: string,
  decoded: unknown,
): unknown {
  if (!toonContent.includes("code:")) return decoded;

  const record =
    decoded && typeof decoded === "object"
      ? { ...(decoded as Record<string, unknown>) }
      : {};

  if (typeof record.code !== "string" || record.code.length === 0) {
    const code = parseCodeBlockFromToon(toonContent);
    if (code) record.code = code;
  }

  if (typeof record.lineCount !== "number") {
    const rawLineCount = record.line_count ?? parseSimpleToonField(toonContent, "line_count");
    const lineCount = Number(rawLineCount);
    if (Number.isFinite(lineCount)) record.lineCount = lineCount;
  }

  for (const key of ["type", "language", "filename", "embed_ref", "status"] as const) {
    if (typeof record[key] !== "string") {
      const value = parseSimpleToonField(toonContent, key);
      if (value) record[key] = value;
    }
  }

  return Object.keys(record).length > 0 ? record : decoded;
}

function toRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

function numberField(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];
  return typeof value === "number" ? value : undefined;
}

/**
 * Initialize TOON decoder
 * Uses the official @toon-format/toon package for decoding TOON-encoded content
 */
async function initToonDecoder() {
  if (!toonDecode) {
    try {
      // Dynamic import for TOON decoder from official package
      const toonModule = await import("@toon-format/toon");
      toonDecode = toonModule.decode;
      console.debug("[embedResolver] TOON decoder initialized successfully");
    } catch (error) {
      console.warn(
        "[embedResolver] TOON decoder not available, will use JSON fallback:",
        error,
      );
      // Keep toonDecode as null to use JSON fallback
    }
  }
}

/**
 * Embed data structure from server/cache
 */
export interface EmbedData {
  embed_id: string;
  type: string; // Decrypted type (client-side only)
  // See embedStateMachine.ts for the canonical status type and valid transitions
  status: "processing" | "finished" | "error" | "cancelled";
  content: string; // TOON-encoded string
  text_preview?: string;
  embed_ids?: string[]; // For composite embeds (app_skill_use)
  file_path?: string; // For code embeds: relative file path (e.g., "src/components/Button.tsx")
  createdAt: number;
  [key: string]: unknown; // Dynamic fields from TOON-decoded embed content
  updatedAt: number;
}

/**
 * Resolve an embed by embed_id
 * Checks both the regular embedStore and the example chat store for cleartext embeds
 * @param embed_id - The embed identifier
 * @returns Embed data or null if not found
 */
export async function resolveEmbed(
  embed_id: string,
): Promise<EmbedData | null> {
  try {
    // Initialize TOON decoder
    await initToonDecoder();

    // Normalize the embed_id: callers may pass either a bare UUID ("bec138d0-...")
    // or a prefixed form ("embed:bec138d0-..."). Strip the prefix here so all
    // downstream lookups use the canonical bare UUID. Without this, callers that
    // already prefix the ID (e.g. handleInspirationEmbedFullscreen) would cause
    // embedStore.get() to look up "embed:embed:<uuid>" — a key that never exists —
    // resulting in a guaranteed cache miss and an unnecessary server round-trip.
    const bareId = embed_id.startsWith("embed:")
      ? embed_id.slice("embed:".length)
      : embed_id;

    const demoEmbed = getExampleChatEmbed(bareId);
    if (demoEmbed) {
      console.debug(
        "[embedResolver] Found embed in example chat store:",
        bareId,
      );
      // Convert ExampleChatEmbed to EmbedData format
      return {
        embed_id: demoEmbed.embed_id,
        type: demoEmbed.type,
        status: "finished" as const,
        content: demoEmbed.content, // Already cleartext (TOON string)
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
    }

    // Second, try to load from EmbedStore (IndexedDB) for regular encrypted embeds
    const cachedEmbed = await embedStore.get(`embed:${bareId}`);
    if (cachedEmbed) {
      // If decryption failed (key mismatch), register as known error to stop the infinite
      // retry loop — every subsequent get() would re-read the IDB entry without the cached
      // _decryptionFailed flag and retry decryption endlessly (see embedStore.ts Fix 1).
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- _decryptionFailed is a runtime-only flag set on EmbedStoreEntry by embedStore.getFromSeparateFields()
      if ((cachedEmbed as any)._decryptionFailed) {
        knownErrorEmbeds.set(bareId, {
          status: "error",
          timestamp: Date.now(),
        });
        console.warn(
          `[embedResolver] Embed ${bareId} has decryption failure — marking as known error to stop retry loop`,
        );
        return null;
      }
      console.debug("[embedResolver] Found embed in EmbedStore:", bareId);
      return cachedEmbed as EmbedData;
    }

    // Check if this embed is known to be in an error/cancelled state.
    // This breaks the infinite loop: error embeds are never persisted to IndexedDB,
    // so without this check, every render cycle would re-request them from the server,
    // which would send them back with status=error, which would trigger another re-render.
    const errorInfo = knownErrorEmbeds.get(bareId);
    if (errorInfo) {
      console.debug(
        `[embedResolver] Embed ${bareId} is known ${errorInfo.status} (since ${new Date(errorInfo.timestamp).toISOString()}), returning null without re-requesting`,
      );
      return null;
    }

    // If not in any store, request from server via WebSocket (async, non-blocking)
    // This handles cases where embeds weren't in the sync payload
    // The embed will be stored when the server responds, and the UI will re-render
    //
    // IMPORTANT: Only request via WebSocket if user is authenticated.
    // For unauthenticated users viewing demo chats, embeds will be available
    // once the example chat store finishes loading from server.
    const isAuthenticated = get(authStore).isAuthenticated;
    if (!isAuthenticated) {
      console.debug(
        "[embedResolver] User not authenticated, skipping WebSocket request for embed:",
        bareId,
      );
    } else {
      console.warn(
        "[embedResolver] Embed not in EmbedStore or demo store, requesting from server (async):",
        bareId,
      );

      try {
        const { webSocketService } = await import("./websocketService");

        // Request embed from server via WebSocket (non-blocking)
        // Server will respond with send_embed_data event, which will store the embed
        // The UI will automatically re-render when the embed is stored
        webSocketService
          .sendMessage("request_embed", {
            embed_id: bareId,
          })
          .catch((error) => {
            // Downgrade to warn when WebSocket is unavailable due to auth —
            // expected on public pages like embed showcase and demo chats.
            const msg = error?.message || String(error);
            const isAuthRelated =
              msg.includes("not connected") ||
              msg.includes("not authenticated");
            const logFn = isAuthRelated ? console.warn : console.error;
            logFn(
              "[embedResolver] Error requesting embed from server:",
              error,
            );
          });
      } catch (error) {
        console.error("[embedResolver] Error setting up embed request:", error);
      }
    }

    // Return null for now - the embed will be available after server responds
    // The renderer should handle null gracefully and show a loading/error state
    return null;
  } catch (error) {
    console.error("[embedResolver] Error resolving embed:", embed_id, error);
    return null;
  }
}

/**
 * Decode TOON content to JavaScript object
 * @param toonContent - TOON-encoded string
 * @returns Decoded object or null if content is invalid/missing
 */
export async function decodeToonContent(
  toonContent: string | null | undefined,
): Promise<Record<string, unknown> | null> {
  // CRITICAL: Handle null/undefined content gracefully to prevent crashes
  // This can happen when embeds fail to decrypt (e.g., missing embed keys)
  if (!toonContent) {
    console.warn(
      "[embedResolver] decodeToonContent called with null/undefined content",
    );
    return null;
  }

  // Also check if it's not a string (could be an object if already decoded)
  if (typeof toonContent !== "string") {
    console.warn(
      "[embedResolver] decodeToonContent called with non-string content:",
      typeof toonContent,
    );
    // If it's already an object, return it as-is
    if (typeof toonContent === "object") {
      return toonContent as Record<string, unknown>;
    }
    return null;
  }

  await initToonDecoder();

  if (toonDecode) {
    try {
      // Use non-strict mode to be lenient with content that may have edge-case formatting
      // (e.g., large pasted text with unusual indentation or special characters)
      const decoded = toonDecode(toonContent, { strict: false });
      return toRecord(recoverCodeEmbedFromToon(toonContent, decoded));
    } catch (error) {
      console.error(
        "[embedResolver] Error decoding TOON content:",
        error instanceof Error ? error.message : String(error),
        {
          contentLength: toonContent.length,
          contentPreview: toonContent.substring(0, 200),
        },
      );
      // Fallback to treating as JSON string
      try {
        return toRecord(recoverCodeEmbedFromToon(toonContent, JSON.parse(toonContent)));
      } catch (jsonError) {
        console.error(
          "[embedResolver] Error parsing as JSON fallback:",
          jsonError instanceof Error ? jsonError.message : String(jsonError),
          {
            contentLength: toonContent.length,
            contentPreview: toonContent.substring(0, 200),
          },
        );
        return null;
      }
    }
  } else {
    // Fallback to JSON parsing if TOON decoder not available
    try {
      return JSON.parse(toonContent);
    } catch (error) {
      console.error(
        "[embedResolver] Error parsing content as JSON:",
        error instanceof Error ? error.message : String(error),
      );
      return null;
    }
  }
}

/**
 * Convert embed data to EmbedNodeAttributes for rendering
 * @param embedData - Embed data from resolver
 * @param embedType - The embed type (app_skill_use, website, etc.)
 * @returns EmbedNodeAttributes for TipTap rendering
 */
export async function embedDataToNodeAttributes(
  embedData: EmbedData,
  embedType: string,
): Promise<EmbedNodeAttributes | null> {
  try {
    // Decode TOON content
    const decodedContent = await decodeToonContent(embedData.content);
    if (!decodedContent) {
      console.warn(
        "[embedResolver] Failed to decode embed content:",
        embedData.embed_id,
      );
      return null;
    }

    // Create embed node attributes based on type
    const nodeAttrs: EmbedNodeAttributes = {
      id: generateUUID(),
      type: mapEmbedTypeToNodeType(embedType),
      status: embedData.status,
      contentRef: `embed:${embedData.embed_id}`,
      contentHash: undefined, // Will be computed if needed
    };

    // Add type-specific attributes
    if (embedType === "app_skill_use") {
      // For app_skill_use, we might need to handle composite embeds
      // For now, store the decoded content
      // The actual rendering will be handled by the embed renderer
      nodeAttrs.title = stringField(decodedContent, "skill_id") || stringField(decodedContent, "app_id");
    } else if (embedType === "website") {
      // Extract website-specific fields
      nodeAttrs.url = stringField(decodedContent, "url");
      nodeAttrs.title = stringField(decodedContent, "title");
      nodeAttrs.description = stringField(decodedContent, "description");
      nodeAttrs.favicon =
        stringField(decodedContent, "meta_url_favicon") || stringField(decodedContent, "favicon");
      nodeAttrs.image =
        stringField(decodedContent, "thumbnail_original") || stringField(decodedContent, "image");
    } else if (embedType === "video") {
      // Extract video-specific fields (YouTube, etc.)
      nodeAttrs.url = stringField(decodedContent, "url");
      nodeAttrs.title = stringField(decodedContent, "title");
      nodeAttrs.description = stringField(decodedContent, "description");
      // Video-specific fields
      const videoAttrs = nodeAttrs as EmbedNodeAttributes & Record<string, unknown>;
      videoAttrs.video_id = decodedContent.video_id;
      videoAttrs.channel_name = decodedContent.channel_name;
      videoAttrs.thumbnail = decodedContent.thumbnail;
      videoAttrs.duration_seconds = decodedContent.duration_seconds;
      videoAttrs.duration_formatted = decodedContent.duration_formatted;
      videoAttrs.view_count = decodedContent.view_count;
    } else if (embedType === "code") {
      nodeAttrs.language = stringField(decodedContent, "language");
      nodeAttrs.filename = stringField(decodedContent, "filename");
      nodeAttrs.lineCount = numberField(decodedContent, "lineCount");
    } else if (embedType === "sheet") {
      nodeAttrs.rows = numberField(decodedContent, "rows");
      nodeAttrs.cols = numberField(decodedContent, "cols");
      nodeAttrs.cellCount = numberField(decodedContent, "cellCount");
    }

    return nodeAttrs;
  } catch (error) {
    console.error(
      "[embedResolver] Error converting embed data to node attributes:",
      error,
    );
    return null;
  }
}

/**
 * Map embed type from server to EmbedNodeType
 * @param embedType - Server embed type (app_skill_use, website, code, etc.)
 * @returns EmbedNodeType for TipTap
 */
function mapEmbedTypeToNodeType(embedType: string): EmbedType {
  // Uses the auto-generated EMBED_TYPE_NORMALIZATION_MAP from app.yml definitions.
  // To add a new type mapping, add an embed_types entry to the relevant app.yml
  // and rebuild — do NOT add manual entries here.
  return normalizeEmbedType(embedType);
}

/**
 * Store embed in EmbedStore with TOON content
 * @param embedData - Embed data to store
 */
export async function storeEmbed(embedData: EmbedData): Promise<void> {
  try {
    // Store embed with TOON content as-is (no decoding needed for storage)
    // Content will be decoded when needed for rendering
    await embedStore.put(
      `embed:${embedData.embed_id}`,
      embedData,
      mapEmbedTypeToNodeType(embedData.type),
    );
    console.debug(
      "[embedResolver] Stored embed in EmbedStore:",
      embedData.embed_id,
    );
  } catch (error) {
    console.error("[embedResolver] Error storing embed:", error);
  }
}

/**
 * Extract embed references from markdown content
 * Finds all JSON code blocks with embed references: {"type": "...", "embed_id": "..."}
 * @param markdown - The markdown content to parse
 * @returns Array of embed reference objects with embed_id and type
 */
export function extractEmbedReferences(
  markdown: string,
): Array<{ type: string; embed_id: string; version?: number }> {
  const embedRefs: Array<{ type: string; embed_id: string; version?: number }> =
    [];

  // Regex to match JSON code blocks: ```json\n{...}\n```
  const jsonCodeBlockRegex = /```json\n([\s\S]*?)\n```/g;
  let match;

  while ((match = jsonCodeBlockRegex.exec(markdown)) !== null) {
    try {
      const jsonContent = match[1].trim();
      const parsed = JSON.parse(jsonContent);

      // Check if this is an embed reference (has type and embed_id)
      if (parsed.type && parsed.embed_id) {
        embedRefs.push({
          type: parsed.type,
          embed_id: parsed.embed_id,
          version: parsed.version, // Optional version number
        });
      }
    } catch {
      // Not a valid embed reference — expected for non-embed JSON blocks
    }
  }

  return embedRefs;
}

/**
 * Load embeds from EmbedStore by embed_ids
 * @param embedIds - Array of embed IDs to load
 * @returns Array of embed data (with TOON content)
 */
export async function loadEmbeds(embedIds: string[]): Promise<EmbedData[]> {
  const embeds: EmbedData[] = [];

  for (const embedId of embedIds) {
    try {
      const embed = await resolveEmbed(embedId);
      if (embed) {
        embeds.push(embed);
      } else {
        console.warn("[embedResolver] Embed not found:", embedId);
      }
    } catch (error) {
      console.error("[embedResolver] Error loading embed:", embedId, error);
    }
  }

  return embeds;
}

/**
 * Load embeds with retry logic for race conditions
 * Useful when child embeds might not be persisted yet (arriving via websocket)
 *
 * @param embedIds - Array of embed IDs to load
 * @param maxRetries - Maximum number of retry attempts (default: 5)
 * @param retryDelayMs - Delay between retries in ms (default: 300ms)
 * @returns Array of embed data (with TOON content)
 */
export async function loadEmbedsWithRetry(
  embedIds: string[],
  maxRetries: number = 5,
  retryDelayMs: number = 300,
): Promise<EmbedData[]> {
  const embeds: EmbedData[] = [];
  const pendingIds = new Set(embedIds);

  for (
    let attempt = 0;
    attempt <= maxRetries && pendingIds.size > 0;
    attempt++
  ) {
    if (attempt > 0) {
      // Wait before retry
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      console.debug(
        `[embedResolver] Retry attempt ${attempt}/${maxRetries} for ${pendingIds.size} missing embeds`,
      );
    }

    const idsToTry = Array.from(pendingIds);
    for (const embedId of idsToTry) {
      try {
        const embed = await resolveEmbed(embedId);
        if (embed) {
          embeds.push(embed);
          pendingIds.delete(embedId);
        }
      } catch (error) {
        console.error("[embedResolver] Error loading embed:", embedId, error);
      }
    }
  }

  if (pendingIds.size > 0) {
    console.warn(
      `[embedResolver] ${pendingIds.size} embeds not found after ${maxRetries} retries:`,
      Array.from(pendingIds),
    );
  }

  return embeds;
}
