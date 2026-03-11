// frontend/packages/ui/src/services/chatImportService.ts
//
// Chat import service for Settings → Account → Import.
//
// Supports two file formats produced by the OpenMates export pipeline:
//
// 1. ZIP (primary) — account export ZIP or single-chat ZIP
//    - Account ZIP: chats/<folder>/<folder>.yml  (one per chat)
//    - Single-chat ZIP: <name>.yml at root
//    Both ZIPs are produced by accountExportService.ts / zipExportService.ts.
//
// 2. YAML (.yml / .yaml) — single-chat or multi-chat YAML
//    Produced by chatExportService.ts convertChatToYaml().
//
// After parsing, selected chats are submitted to:
//   POST /v1/settings/import-chat
// where each message is safety-scanned via gpt-oss-safeguard-20b (OpenRouter)
// before being stored. Blocked messages get a visible placeholder.
//
// See docs/architecture/account-backup.md for the export/import model.
// Tests: none yet (UI-level integration tests planned).

import JSZip from "jszip";
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
  /** Source filename (for display). */
  sourceFile?: string;
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

export type ImportFileType = "zip" | "yaml";

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
  phase: "parsing" | "resolving-embeds" | "submitting" | "done",
  detail: string,
) => void;

// ============================================================================
// FILE TYPE DETECTION
// ============================================================================

export function detectFileType(file: File): ImportFileType {
  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) return "zip";
  return "yaml";
}

// ============================================================================
// ZIP PARSING
// ============================================================================

/**
 * Parse an OpenMates export ZIP file.
 *
 * Handles two ZIP layouts produced by the export pipeline:
 *
 * Account export ZIP:
 *   chats/<folder-name>/<folder-name>.yml   ← one per chat
 *   (may also contain images/, audio/, code/, etc. — ignored for import)
 *
 * Single-chat ZIP:
 *   <chat-name>.yml   ← single YAML at root (no chats/ prefix)
 *
 * Any .yml file found inside a chats/ subfolder OR at the root that
 * matches the OpenMates chat YAML format is treated as a chat to import.
 */
export async function parseImportZip(file: File): Promise<ParsedImportChat[]> {
  const arrayBuffer = await file.arrayBuffer();
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(arrayBuffer);
  } catch (e) {
    throw new Error(
      "Cannot read ZIP file: " + (e instanceof Error ? e.message : String(e)),
    );
  }

  const chats: ParsedImportChat[] = [];

  // Collect candidate .yml files
  const ymlFiles: { path: string; file: JSZip.JSZipObject }[] = [];
  zip.forEach((relativePath, zipEntry) => {
    if (zipEntry.dir) return;
    const lower = relativePath.toLowerCase();
    if (!lower.endsWith(".yml") && !lower.endsWith(".yaml")) return;
    // Skip non-chat YML files (metadata, usage, settings, compliance, invoices)
    const base = relativePath.split("/").pop()?.toLowerCase() ?? "";
    const skipPatterns = [
      "metadata",
      "profile",
      "usage_history",
      "invoices",
      "app_settings",
      "compliance_logs",
    ];
    if (skipPatterns.some((p) => base.includes(p))) return;
    ymlFiles.push({ path: relativePath, file: zipEntry });
  });

  if (ymlFiles.length === 0) {
    throw new Error(
      "No chat YAML files found in ZIP. Make sure this is an OpenMates export.",
    );
  }

  // Sort: chats/ folder entries first, then root-level
  ymlFiles.sort((a, b) => {
    const aInChats = a.path.startsWith("chats/");
    const bInChats = b.path.startsWith("chats/");
    if (aInChats && !bInChats) return -1;
    if (!aInChats && bInChats) return 1;
    return a.path.localeCompare(b.path);
  });

  for (const { path, file: zipEntry } of ymlFiles) {
    try {
      const yamlText = await zipEntry.async("string");
      const parsed = tryParseSingleChatYaml(yamlText);
      if (parsed) {
        parsed.sourceFile = path;
        chats.push(parsed);
      }
    } catch {
      // Skip unreadable/non-chat YML files silently
    }
  }

  if (chats.length === 0) {
    throw new Error(
      "No valid OpenMates chats found in ZIP. The file may be corrupted or in an unsupported format.",
    );
  }

  return chats;
}

// ============================================================================
// YAML PARSING
// ============================================================================

/**
 * Parse a YAML string (single-chat or multi-chat OpenMates export format)
 * and return a list of ParsedImportChat objects ready for submission.
 *
 * Throws a user-readable error if the YAML is invalid or unrecognisable.
 */
export function parseImportYaml(yamlText: string): ParsedImportChat[] {
  let parsed: unknown;
  try {
    parsed = parse(yamlText);
  } catch (e) {
    throw new Error(
      "Invalid YAML: " + (e instanceof Error ? e.message : String(e)),
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

/**
 * Try to parse a single YAML string as an OpenMates chat.
 * Returns null if it doesn't look like a chat (used during ZIP scanning).
 */
function tryParseSingleChatYaml(yamlText: string): ParsedImportChat | null {
  try {
    const parsed = parse(yamlText);
    if (!parsed || typeof parsed !== "object") return null;
    const block = parsed as Record<string, unknown>;
    // Must have a "messages" key to be a chat
    if (!("messages" in block) && !("chat" in block)) return null;
    return parseSingleChatBlock(parsed, 0);
  } catch {
    return null;
  }
}

function parseSingleChatBlock(block: unknown, index: number): ParsedImportChat {
  if (!block || typeof block !== "object") {
    throw new Error(`Chat ${index + 1} is not an object.`);
  }
  const b = block as Record<string, unknown>;

  // "chat" key holds metadata in single-chat YAML format
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

  const rawEmbeds: RawYamlEmbed[] = (embedsRaw as unknown[])
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
// UNIFIED FILE PARSER
// ============================================================================

/**
 * Parse any supported import file (ZIP or YAML) and return chats.
 * This is the main entry point called by the UI.
 */
export async function parseImportFile(
  file: File,
  onProgress?: ImportProgressCallback,
): Promise<{ chats: ParsedImportChat[]; fileType: ImportFileType }> {
  const fileType = detectFileType(file);

  if (fileType === "zip") {
    onProgress?.("parsing", "Reading ZIP file…");
    const chats = await parseImportZip(file);
    return { chats, fileType };
  } else {
    onProgress?.("parsing", "Reading YAML file…");
    const yamlText = await file.text();
    const chats = parseImportYaml(yamlText);
    return { chats, fileType };
  }
}

// ============================================================================
// COST ESTIMATION
// ============================================================================

/**
 * Estimate import cost entirely on the client (no network round-trip).
 * Uses the same formula as the backend:
 *   credits = max(chats.length, floor(totalTokens / 4444))
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

/**
 * For each embed listed in the chat's YAML, try to resolve it from local
 * IndexedDB. Pure-data embeds that are missing locally are re-stored so they
 * render correctly after import. File-backed embeds are left as-is.
 */
async function resolveEmbeds(rawEmbeds: RawYamlEmbed[]): Promise<void> {
  for (const raw of rawEmbeds) {
    if (!raw.embed_id) continue;

    const existing = await resolveEmbed(raw.embed_id);
    if (existing) continue; // Already in local store — nothing to do

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
      } catch {
        // Non-fatal — embed just won't be resolvable locally
      }
    }
  }
}

// ============================================================================
// IMPORT API CALL
// ============================================================================

/**
 * Import selected chats to the backend.
 *
 * Steps:
 * 1. Resolve embeds from local IndexedDB (pure-data embeds only).
 * 2. Submit all selected chats to POST /v1/settings/import-chat.
 * 3. Return per-chat results and total credits charged.
 *
 * Throws on network/API errors. Progress callback is optional.
 */
export async function importChats(
  chats: ParsedImportChat[],
  onProgress?: ImportProgressCallback,
): Promise<ImportChatApiResponse> {
  if (chats.length === 0) throw new Error("No chats selected for import.");

  // Step 1: Resolve embeds from local IndexedDB
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
