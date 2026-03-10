// frontend/packages/ui/src/services/chatImportService.ts
//
// Chat import service for Settings → Account → Import.
// Parses user-supplied YAML export files (produced by chatExportService.ts),
// optionally resolves embed IDs from local IndexedDB, then submits chats to
// the backend POST /v1/settings/import-chat for safety-scanning and storage.
//
// See docs/architecture/account-backup.md for the full export/import model.
// Tests: none yet (UI-level integration tests planned).

import { parse } from "yaml";
import { getApiEndpoint, apiEndpoints } from "../config/api";
import { resolveEmbed, storeEmbed, type EmbedData } from "./embedResolver";

// ============================================================================
// CONSTANTS
// ============================================================================

/** Safety model input cost: $0.075/M tokens → 333.33/0.075 = 4444 tokens/credit */
const TOKENS_PER_CREDIT = 4444;

/** Conservative chars-per-token estimate used for client-side cost preview. */
const CHARS_PER_TOKEN = 4;

// ============================================================================
// TYPES
// ============================================================================

export interface ParsedImportMessage {
  role: "user" | "assistant" | "system";
  content: string;
  completed_at?: string;
  assistant_category?: string;
  thinking?: string;
  has_thinking?: boolean;
  thinking_tokens?: number;
}

export interface ParsedImportChat {
  title: string | null;
  draft: string | null;
  summary: string | null;
  messages: ParsedImportMessage[];
  /** Original embed entries from YAML — used for local ID resolution. */
  rawEmbeds: RawYamlEmbed[];
}

export interface RawYamlEmbed {
  embed_id: string;
  type: string;
  status: string;
  content: unknown;
  createdAt?: string;
  updatedAt?: string;
  text_preview?: string;
}

export interface ImportCostEstimate {
  totalInputTokens: number;
  estimatedCredits: number;
  chatCount: number;
  messageCount: number;
}

export interface ImportedChatResult {
  chat_id: string;
  title: string | null;
  messages_imported: number;
  messages_blocked: number;
  credits_charged: number;
}

export interface ImportChatApiResponse {
  imported: ImportedChatResult[];
  total_credits_charged: number;
}

export type ImportProgressCallback = (
  phase: "resolving-embeds" | "submitting" | "done",
  detail: string,
) => void;

// ============================================================================
// PARSING
// ============================================================================

/**
 * Parse a YAML string (single-chat or multi-chat OpenMates export format) and
 * return a list of ParsedImportChat objects ready for submission.
 *
 * Throws a user-readable error if the YAML is invalid or unrecognisable.
 */
export function parseImportYaml(yamlText: string): ParsedImportChat[] {
  let parsed: unknown;
  try {
    parsed = parse(yamlText);
  } catch (e) {
    throw new Error(
      "Invalid YAML file: " + (e instanceof Error ? e.message : String(e)),
    );
  }

  if (!parsed || typeof parsed !== "object") {
    throw new Error("YAML file is empty or not an object.");
  }

  // Multi-chat format: top-level has a "chats" array
  if ("chats" in (parsed as Record<string, unknown>)) {
    const root = parsed as { chats: unknown[] };
    if (!Array.isArray(root.chats) || root.chats.length === 0) {
      throw new Error("No chats found in YAML file.");
    }
    return root.chats.map((c, i) => parseSingleChatBlock(c, i));
  }

  // Single-chat format: top-level has "chat" + "messages" keys
  if (
    "chat" in (parsed as Record<string, unknown>) ||
    "messages" in (parsed as Record<string, unknown>)
  ) {
    return [parseSingleChatBlock(parsed, 0)];
  }

  throw new Error(
    "Unrecognised YAML format. Expected an OpenMates chat export file.",
  );
}

function parseSingleChatBlock(block: unknown, index: number): ParsedImportChat {
  if (!block || typeof block !== "object") {
    throw new Error(`Chat ${index + 1} is not an object.`);
  }
  const b = block as Record<string, unknown>;

  const chatMeta = (b.chat as Record<string, unknown> | undefined) ?? b;
  const messagesRaw = Array.isArray(b.messages) ? b.messages : [];
  const embedsRaw = Array.isArray(b.embeds) ? b.embeds : [];

  const messages: ParsedImportMessage[] = messagesRaw.map(
    (m: unknown, mi: number) => {
      if (!m || typeof m !== "object") {
        throw new Error(
          `Message ${mi + 1} in chat ${index + 1} is not an object.`,
        );
      }
      const msg = m as Record<string, unknown>;
      const role = String(msg.role ?? "user") as
        | "user"
        | "assistant"
        | "system";
      if (!["user", "assistant", "system"].includes(role)) {
        throw new Error(
          `Invalid role "${role}" in message ${mi + 1} of chat ${index + 1}.`,
        );
      }
      return {
        role,
        content: typeof msg.content === "string" ? msg.content : "",
        completed_at:
          typeof msg.completed_at === "string" ? msg.completed_at : undefined,
        assistant_category:
          typeof msg.assistant_category === "string"
            ? msg.assistant_category
            : undefined,
        thinking: typeof msg.thinking === "string" ? msg.thinking : undefined,
        has_thinking:
          typeof msg.has_thinking === "boolean" ? msg.has_thinking : undefined,
        thinking_tokens:
          typeof msg.thinking_tokens === "number"
            ? msg.thinking_tokens
            : undefined,
      };
    },
  );

  const rawEmbeds: RawYamlEmbed[] = embedsRaw
    .map((e: unknown) => {
      if (!e || typeof e !== "object") return null;
      const em = e as Record<string, unknown>;
      return {
        embed_id: String(em.embed_id ?? ""),
        type: String(em.type ?? ""),
        status: String(em.status ?? ""),
        content: em.content,
        createdAt: typeof em.createdAt === "string" ? em.createdAt : undefined,
        updatedAt: typeof em.updatedAt === "string" ? em.updatedAt : undefined,
        text_preview:
          typeof em.text_preview === "string" ? em.text_preview : undefined,
      };
    })
    .filter(Boolean) as RawYamlEmbed[];

  const meta = chatMeta as Record<string, unknown>;
  return {
    title: typeof meta.title === "string" ? meta.title || null : null,
    draft: typeof meta.draft === "string" ? meta.draft || null : null,
    summary: typeof meta.summary === "string" ? meta.summary || null : null,
    messages,
    rawEmbeds,
  };
}

// ============================================================================
// COST ESTIMATION
// ============================================================================

/**
 * Estimate import cost entirely on the client (no network round-trip).
 * Uses the same formula as the backend: floor(totalTokens / 4444), minimum 1
 * per chat that has at least one non-empty message.
 */
export function estimateImportCost(
  chats: ParsedImportChat[],
): ImportCostEstimate {
  let totalInputTokens = 0;
  let messageCount = 0;

  for (const chat of chats) {
    for (const msg of chat.messages) {
      if (msg.content.trim()) {
        totalInputTokens += Math.max(
          1,
          Math.ceil(msg.content.length / CHARS_PER_TOKEN),
        );
        messageCount++;
      }
    }
  }

  const estimatedCredits = Math.max(
    chats.length,
    Math.floor(totalInputTokens / TOKENS_PER_CREDIT),
  );

  return {
    totalInputTokens,
    estimatedCredits,
    chatCount: chats.length,
    messageCount,
  };
}

// ============================================================================
// EMBED RESOLUTION
// ============================================================================

/**
 * For each embed in the chat, try to resolve it from local IndexedDB.
 * If found, reuse the same embed_id (no change needed in message content).
 * If not found and it's a pure-data embed, re-store it with the same ID.
 * File-backed embeds that aren't in IndexedDB are left as-is (the backend
 * message content will still reference them, but they won't be resolvable).
 *
 * Returns a map of { oldEmbedId → resolvedEmbedId } for content substitution.
 * In v1 we keep the same IDs, so this map is identity if the embed exists locally.
 */
const PURE_DATA_EMBED_TYPES = new Set([
  "code-code",
  "docs-doc",
  "sheets-sheet",
  "web-website",
  "videos-video",
  "maps-location",
  "maps-directions",
  "focus-mode-activation",
  "app-skill-use",
]);

async function resolveEmbeds(
  rawEmbeds: RawYamlEmbed[],
): Promise<Map<string, string>> {
  const idMap = new Map<string, string>();

  for (const raw of rawEmbeds) {
    if (!raw.embed_id) continue;

    // Try local IndexedDB first
    const existing = await resolveEmbed(raw.embed_id);
    if (existing) {
      // Already in local store — reuse as-is
      idMap.set(raw.embed_id, raw.embed_id);
      continue;
    }

    // Not found locally — only re-store pure-data embeds
    if (PURE_DATA_EMBED_TYPES.has(raw.type) && raw.content) {
      try {
        const nowMs = Date.now();
        const embedData: EmbedData = {
          embed_id: raw.embed_id,
          type: raw.type as EmbedData["type"],
          status: (raw.status as EmbedData["status"]) ?? "finished",
          content: raw.content as EmbedData["content"],
          createdAt: raw.createdAt ? new Date(raw.createdAt).getTime() : nowMs,
          updatedAt: raw.updatedAt ? new Date(raw.updatedAt).getTime() : nowMs,
        };
        await storeEmbed(embedData);
        idMap.set(raw.embed_id, raw.embed_id);
      } catch {
        // Ignore store errors — embed just won't be resolvable
      }
    }
    // File-backed embeds not in local store: no substitution needed
    // The embed reference stays in message content; it just won't render.
  }

  return idMap;
}

// ============================================================================
// IMPORT API CALL
// ============================================================================

/**
 * Import selected chats to the backend.
 *
 * Steps:
 * 1. Resolve embeds from local IndexedDB.
 * 2. Submit to POST /v1/settings/import-chat.
 * 3. Return results.
 *
 * Throws on network/API errors. Progress callback is optional.
 */
export async function importChats(
  chats: ParsedImportChat[],
  onProgress?: ImportProgressCallback,
): Promise<ImportChatApiResponse> {
  if (chats.length === 0) throw new Error("No chats selected for import.");

  // Step 1: Resolve embeds
  onProgress?.(
    "resolving-embeds",
    `Resolving embeds for ${chats.length} chat(s)…`,
  );
  for (const chat of chats) {
    if (chat.rawEmbeds.length > 0) {
      await resolveEmbeds(chat.rawEmbeds);
    }
  }

  // Step 2: Submit to backend
  onProgress?.("submitting", `Scanning and importing ${chats.length} chat(s)…`);

  const payload = {
    chats: chats.map((c) => ({
      title: c.title,
      draft: c.draft,
      summary: c.summary,
      messages: c.messages.map((m) => ({
        role: m.role,
        content: m.content,
        completed_at: m.completed_at ?? null,
        assistant_category: m.assistant_category ?? null,
        thinking: m.thinking ?? null,
        has_thinking: m.has_thinking ?? null,
        thinking_tokens: m.thinking_tokens ?? null,
      })),
    })),
  };

  const response = await fetch(
    getApiEndpoint(apiEndpoints.settings.importChat),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const detail = (err as { detail?: string }).detail;
    if (response.status === 429) {
      throw new Error(
        "Too many import requests. Please wait a moment and try again.",
      );
    }
    if (response.status === 402) {
      throw new Error(
        "Insufficient credits to import. Please top up your balance.",
      );
    }
    throw new Error(detail || `Import failed (HTTP ${response.status})`);
  }

  const data = (await response.json()) as ImportChatApiResponse;
  onProgress?.("done", "Import complete.");
  return data;
}
