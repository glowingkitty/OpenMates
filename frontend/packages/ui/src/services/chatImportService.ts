// frontend/packages/ui/src/services/chatImportService.ts
//
// Account Import V1 browser service for Settings -> Account -> Import.
// Parses Claude official exports and OpenMates Export V1 archives locally,
// then uses the preview -> scan -> client-encrypt -> persist-encrypted ->
// complete control-plane contract. Permanent server persistence must receive
// only client-encrypted private chat/message fields.
//
// Spec: docs/specs/account-import-v1/spec.yml

import JSZip from "jszip";
import { parse } from "yaml";
import { getApiEndpoint, apiEndpoints } from "../config/api";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
import type { Chat, Message } from "../types/chat";

const DEFAULT_TITLE = "Imported chat";
const CHARS_PER_TOKEN = 4;

export type AccountImportSource = "claude" | "openmates";
export type ImportFileType = "claude-json" | "claude-zip" | "openmates-zip";

export interface ParsedImportMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  source_message_id?: string | null;
  provider_metadata: Record<string, unknown>;
}

export interface ParsedImportUpload {
  source_upload_id: string;
  file_name: string;
  mime_type?: string | null;
  bytes?: number | null;
  content_ref: string;
}

export interface ParsedImportChat {
  provider: AccountImportSource;
  source_chat_id: string;
  source_fingerprint: string;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  messages: ParsedImportMessage[];
  embeds: Array<Record<string, unknown>>;
  uploads: ParsedImportUpload[];
  provider_labels: string[];
  source_metadata: Record<string, unknown>;
}

export interface ParsedAccountImport {
  source: AccountImportSource;
  fileType: ImportFileType;
  chats: ParsedImportChat[];
  skippedDomains: string[];
}

export interface ImportCostEstimate {
  totalInputTokens: number;
  estimatedCredits: number;
  chatCount: number;
  messageCount: number;
}

export interface ImportPreviewResponse {
  import_id: string;
  free_remaining?: number;
  chat_limit?: number;
  default_selection_count: number;
  max_batch_count: number;
  duplicate_fingerprints: string[];
  estimated_credits: number;
  can_import: boolean;
  reason: string;
}

export interface ImportScanResponse {
  chats: ParsedImportChat[];
  credits_reserved: number;
  messages_blocked: Array<Record<string, unknown>>;
  failures: Array<Record<string, unknown>>;
}

export interface ImportPersistResponse {
  status: "complete" | "partial" | string;
  imported_chat_ids: string[];
  encrypted_record_counts: Record<string, number>;
  failures: Array<Record<string, unknown>>;
}

export interface ImportCompleteResponse {
  status: "complete" | "partial" | string;
  imported_count: number;
  credits_charged: number;
  credits_released: number;
  failures: Array<Record<string, unknown>>;
}

export interface ImportedChatResult {
  chat_id: string;
  title: string | null;
  messages_imported: number;
  messages_blocked: number;
  credits_charged: number;
  messages?: ParsedImportMessage[];
}

export interface ImportChatApiResponse {
  imported: ImportedChatResult[];
  total_credits_charged: number;
  import_id: string;
  preview: ImportPreviewResponse;
  scan: ImportScanResponse;
  persistence: ImportPersistResponse;
  complete: ImportCompleteResponse;
}

export interface RecentImportedChatData {
  chat: Chat;
  messages: Message[];
}

export type ImportProgressPhase =
  | "parsing"
  | "previewing"
  | "scanning"
  | "encrypting"
  | "persisting"
  | "completing"
  | "done";

export type ImportProgressCallback = (
  phase: ImportProgressPhase,
  detail: string,
) => void;

const recentImportedChats = new Map<string, RecentImportedChatData>();

export function getRecentImportedChatData(
  chatId: string,
): RecentImportedChatData | undefined {
  return recentImportedChats.get(chatId);
}

export function getAllRecentImportedChatData(): RecentImportedChatData[] {
  return Array.from(recentImportedChats.values());
}

export function estimateImportCost(
  chats: ParsedImportChat[],
): ImportCostEstimate {
  let totalInputTokens = 0;
  let messageCount = 0;
  for (const chat of chats) {
    for (const message of chat.messages) {
      if (!message.content.trim()) continue;
      totalInputTokens += Math.max(
        1,
        Math.ceil(message.content.length / CHARS_PER_TOKEN),
      );
      messageCount++;
    }
  }
  return {
    totalInputTokens,
    estimatedCredits: chats.length,
    chatCount: chats.length,
    messageCount,
  };
}

export async function parseImportFile(
  file: File,
  onProgress?: ImportProgressCallback,
): Promise<ParsedAccountImport> {
  onProgress?.("parsing", "Reading import file...");
  const lowerName = file.name.toLowerCase();

  if (lowerName.endsWith(".json")) {
    const raw = await file.text();
    return parseClaudeConversations(JSON.parse(raw), "claude-json", file.name);
  }

  if (!lowerName.endsWith(".zip")) {
    throw new Error(
      "Unsupported import file. Choose a Claude export .zip/.json file or an OpenMates Export V1 .zip archive.",
    );
  }

  const payload = await file.arrayBuffer();
  let zip: JSZip;
  try {
    zip = await JSZip.loadAsync(payload);
  } catch (error) {
    throw new Error(
      `Cannot read ZIP file: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  if (zip.file("conversations.json")) {
    const raw = await zip.file("conversations.json")!.async("string");
    return parseClaudeConversations(JSON.parse(raw), "claude-zip", file.name);
  }

  if (zip.file("manifest.yml")) {
    return parseOpenMatesArchive(zip, file.name);
  }

  throw new Error(
    "Unsupported ZIP archive. Expected Claude conversations.json or OpenMates Export V1 manifest.yml.",
  );
}

export async function previewImport(
  parsed: ParsedAccountImport,
  onProgress?: ImportProgressCallback,
): Promise<ImportPreviewResponse> {
  onProgress?.("previewing", "Checking import limits and estimated cost...");
  const estimate = estimateImportCost(parsed.chats);
  const response = await fetch(
    getApiEndpoint(apiEndpoints.accountImports.preview),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        source: parsed.source,
        chat_count: parsed.chats.length,
        source_fingerprints: parsed.chats.map((chat) => chat.source_fingerprint),
        estimated_tokens: estimate.totalInputTokens,
        estimated_bytes: new TextEncoder().encode(
          JSON.stringify({ source: parsed.source, chats: parsed.chats }),
        ).byteLength,
      }),
    },
  );
  return readJsonResponse<ImportPreviewResponse>(response, "Import preview failed");
}

export async function importChats(
  parsed: ParsedAccountImport,
  selectedChats: ParsedImportChat[],
  preview: ImportPreviewResponse,
  onProgress?: ImportProgressCallback,
): Promise<ImportChatApiResponse> {
  if (selectedChats.length === 0) throw new Error("No chats selected for import.");
  if (!preview.can_import) {
    throw new Error(`Import is not available: ${preview.reason || "unknown"}`);
  }
  if (selectedChats.length > preview.max_batch_count) {
    throw new Error(`Select ${preview.max_batch_count} chats or fewer for this import.`);
  }

  const importId = preview.import_id;
  onProgress?.("scanning", `Safety-scanning ${selectedChats.length} chat(s)...`);
  const scanResponse = await fetch(
    getApiEndpoint(apiEndpoints.accountImports.scan(importId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ chats: selectedChats }),
    },
  );
  const scan = await readJsonResponse<ImportScanResponse>(
    scanResponse,
    "Import scan failed",
  );
  if (!Array.isArray(scan.chats)) {
    throw new Error("Import scan failed: response did not include sanitized chats.");
  }
  if (Array.isArray(scan.failures) && scan.failures.length > 0) {
    await completeFailedImport(importId, scan.failures);
    throw new Error("Import scan failed for one or more selected chats. No content was imported.");
  }
  const sanitizedChats = scan.chats;
  if (sanitizedChats.length === 0) {
    throw new Error("Import scan blocked all selected chats. No content was imported.");
  }

  onProgress?.("encrypting", "Encrypting imported chats on this device...");
  const encryptedPackage = await buildEncryptedImportPackage(sanitizedChats);

  onProgress?.("persisting", "Saving encrypted imported chats...");
  const persistResponse = await fetch(
    getApiEndpoint(apiEndpoints.accountImports.persistEncrypted(importId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ chats: encryptedPackage.chats }),
    },
  );
  const persistence = await readJsonResponse<ImportPersistResponse>(
    persistResponse,
    "Encrypted import persistence failed",
  );

  onProgress?.("completing", "Finalizing import...");
  const completeResponse = await fetch(
    getApiEndpoint(apiEndpoints.accountImports.complete(importId)),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        imported_chat_ids: persistence.imported_chat_ids,
        source_fingerprints: acceptedSourceFingerprints(
          encryptedPackage.localChats,
          persistence.imported_chat_ids,
          persistence.failures ?? [],
        ),
        encrypted_record_counts: persistence.encrypted_record_counts,
        client_failures: persistence.failures ?? [],
      }),
    },
  );
  const complete = await readJsonResponse<ImportCompleteResponse>(
    completeResponse,
    "Import completion failed",
  );

  await cacheAcceptedImportsLocally(
    encryptedPackage.localChats,
    persistence.imported_chat_ids,
    persistence.failures ?? [],
  ).catch((error) => {
    console.warn("[ChatImport] Local import cache failed:", error);
  });

  const failedMessageIds = failedMessageIdsFromPersistence(persistence.failures ?? []);
  const chatLevelFailureIds = chatLevelFailureIdsFromPersistence(persistence.failures ?? []);
  const imported = persistence.imported_chat_ids
    .filter((chatId) => !chatLevelFailureIds.has(chatId))
    .map((chatId) => {
      const local = encryptedPackage.localChats.find((item) => item.chat.chat_id === chatId);
      const acceptedMessages = local?.messages.filter(
        (message) => !failedMessageIds.has(message.message_id),
      ) ?? [];
      return {
        chat_id: chatId,
        title: local?.source.title ?? null,
        messages_imported: acceptedMessages.length,
        messages_blocked: countBlockedMessages(scan.messages_blocked ?? [], local?.source.source_chat_id),
        credits_charged: complete.credits_charged ?? 0,
        messages: local?.source.messages.filter(
          (_message, index) => !failedMessageIds.has(local.messages[index]?.message_id ?? ""),
        ),
      } satisfies ImportedChatResult;
    });

  onProgress?.("done", "Import complete.");
  return {
    imported,
    total_credits_charged: complete.credits_charged ?? 0,
    import_id: importId,
    preview,
    scan,
    persistence,
    complete,
  };
}

async function completeFailedImport(
  importId: string,
  failures: Array<Record<string, unknown>>,
): Promise<void> {
  try {
    const response = await fetch(
      getApiEndpoint(apiEndpoints.accountImports.complete(importId)),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          imported_chat_ids: [],
          source_fingerprints: [],
          encrypted_record_counts: {},
          client_failures: failures,
        }),
      },
    );
    await readJsonResponse<ImportCompleteResponse>(response, "Import completion failed");
  } catch (error) {
    console.warn("[ChatImport] Failed to finalize failed import:", error);
  }
}

function normalizeRole(value: unknown): "user" | "assistant" | "system" {
  const role = String(value ?? "user");
  return role === "assistant" || role === "system" ? role : "user";
}

function claudeMessageContent(message: Record<string, unknown>): {
  content: string;
  blockTypes: string[];
} {
  const blocks = Array.isArray(message.content) ? message.content : [];
  const blockTypes: string[] = [];
  const textParts: string[] = [];
  for (const rawBlock of blocks) {
    if (!rawBlock || typeof rawBlock !== "object") continue;
    const block = rawBlock as Record<string, unknown>;
    const type = String(block.type ?? "unknown");
    blockTypes.push(type);
    if (type === "text" && typeof block.text === "string") textParts.push(block.text);
    if (type === "tool_result" && typeof block.content === "string") {
      textParts.push(block.content);
    }
  }
  return {
    content: textParts.length > 0 ? textParts.join("\n") : String(message.text ?? ""),
    blockTypes,
  };
}

function claudeUploads(message: Record<string, unknown>): ParsedImportUpload[] {
  const items = [
    ...(Array.isArray(message.attachments) ? message.attachments : []),
    ...(Array.isArray(message.files) ? message.files : []),
  ];
  return items
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    .map((item, index) => {
      const fileName = String(item.file_name ?? item.name ?? `attachment-${index + 1}`);
      return {
        source_upload_id: String(item.uuid ?? item.id ?? fileName),
        file_name: fileName,
        mime_type: typeof item.mime_type === "string"
          ? item.mime_type
          : typeof item.file_type === "string"
            ? item.file_type
            : null,
        bytes: typeof item.file_size === "number"
          ? item.file_size
          : typeof item.bytes === "number"
            ? item.bytes
            : null,
        content_ref: fileName,
      };
    });
}

async function parseClaudeConversations(
  raw: unknown,
  fileType: Extract<ImportFileType, "claude-json" | "claude-zip">,
  sourceName: string,
): Promise<ParsedAccountImport> {
  const conversations = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as Record<string, unknown>).conversations)
      ? ((raw as Record<string, unknown>).conversations as unknown[])
      : null;
  if (!conversations) throw new Error("Claude export conversations must be an array.");

  const chats: ParsedImportChat[] = [];
  for (const item of conversations) {
    if (!item || typeof item !== "object") continue;
    const conversation = item as Record<string, unknown>;
    const sourceChatId = String(conversation.uuid ?? "");
    if (!sourceChatId) throw new Error("Claude conversation is missing uuid.");

    const rawMessages = Array.isArray(conversation.chat_messages)
      ? conversation.chat_messages
      : [];
    const messages = rawMessages
      .filter((message): message is Record<string, unknown> => Boolean(message && typeof message === "object"))
      .map((message) => {
        const { content, blockTypes } = claudeMessageContent(message);
        const sender = String(message.sender ?? "");
        return {
          role: sender === "human" ? "user" : sender === "assistant" ? "assistant" : "system",
          content,
          created_at: typeof message.created_at === "string" ? message.created_at : null,
          source_message_id: typeof message.uuid === "string" ? message.uuid : null,
          provider_metadata: { content_block_types: blockTypes },
        } satisfies ParsedImportMessage;
      });

    chats.push({
      provider: "claude",
      source_chat_id: sourceChatId,
      source_fingerprint: await stableFingerprint("claude", sourceChatId, messages),
      title: typeof conversation.name === "string" ? conversation.name : null,
      created_at: typeof conversation.created_at === "string" ? conversation.created_at : null,
      updated_at: typeof conversation.updated_at === "string" ? conversation.updated_at : null,
      messages,
      embeds: [],
      uploads: rawMessages
        .filter((message): message is Record<string, unknown> => Boolean(message && typeof message === "object"))
        .flatMap(claudeUploads),
      provider_labels: ["claude"],
      source_metadata: { source_name: sourceName, message_count: messages.length },
    });
  }

  return { source: "claude", fileType, chats: newestFirst(chats), skippedDomains: [] };
}

async function parseOpenMatesArchive(
  zip: JSZip,
  sourceName: string,
): Promise<ParsedAccountImport> {
  const manifestText = await zip.file("manifest.yml")!.async("string");
  const manifest = parse(manifestText) as Record<string, unknown> | null;
  if (!manifest || manifest.format !== "openmates-account-export" || String(manifest.version) !== "1") {
    throw new Error("Unsupported OpenMates Export V1 archive format or version.");
  }

  const domainRecord = manifest.domains && typeof manifest.domains === "object"
    ? (manifest.domains as Record<string, unknown>)
    : {};
  const skippedDomains = Object.keys(domainRecord)
    .filter((domain) => !["chats", "embeds", "uploads", "referenced_uploads"].includes(domain))
    .sort();

  const embedsById = await readYamlRecordsById(zip, "embeds/");
  const uploadsById = await readYamlRecordsById(zip, "uploads/");
  const chatFiles = Object.keys(zip.files)
    .filter((name) => name.startsWith("chats/") && /\.ya?ml$/i.test(name))
    .sort();
  if (chatFiles.length === 0) {
    throw new Error("OpenMates Export V1 archive contains no chat YAML files.");
  }

  const chats: ParsedImportChat[] = [];
  for (const name of chatFiles) {
    const text = await zip.file(name)!.async("string");
    const chatData = parse(text) as Record<string, unknown> | null;
    if (!chatData || typeof chatData !== "object") continue;
    const sourceChatId = String(chatData.id ?? name.replace(/\.ya?ml$/i, ""));
    if (!sourceChatId) throw new Error("OpenMates chat YAML is missing id.");
    const messages = (Array.isArray(chatData.messages) ? chatData.messages : [])
      .filter((message): message is Record<string, unknown> => Boolean(message && typeof message === "object"))
      .map((message) => ({
        role: normalizeRole(message.role),
        content: typeof message.content === "string" ? message.content : "",
        created_at: typeof message.created_at === "string" ? message.created_at : null,
        source_message_id: typeof message.id === "string" ? message.id : null,
        provider_metadata: { embed_refs: Array.isArray(message.embed_refs) ? message.embed_refs : [] },
      }));
    const embedRefs = (Array.isArray(chatData.embed_refs) ? chatData.embed_refs : []).map(String);
    const uploadRefs = (Array.isArray(chatData.upload_refs) ? chatData.upload_refs : []).map(String);

    chats.push({
      provider: "openmates",
      source_chat_id: sourceChatId,
      source_fingerprint: await stableFingerprint("openmates", sourceChatId, messages),
      title: typeof chatData.title === "string" ? chatData.title : null,
      created_at: typeof chatData.created_at === "string" ? chatData.created_at : null,
      updated_at: typeof chatData.updated_at === "string" ? chatData.updated_at : null,
      messages,
      embeds: embedRefs.map((embedId) => ({
        source_embed_id: embedId,
        type: String(embedsById.get(embedId)?.type ?? "unknown"),
        content: embedsById.get(embedId)?.content ?? {},
        referenced_upload_ids: embedsById.get(embedId)?.referenced_upload_ids ?? [],
      })),
      uploads: uploadRefs.map((uploadId) => ({
        source_upload_id: uploadId,
        file_name: String(uploadsById.get(uploadId)?.file_name ?? uploadId),
        mime_type: typeof uploadsById.get(uploadId)?.mime_type === "string"
          ? String(uploadsById.get(uploadId)?.mime_type)
          : null,
        bytes: typeof uploadsById.get(uploadId)?.bytes === "number"
          ? Number(uploadsById.get(uploadId)?.bytes)
          : null,
        content_ref: String(uploadsById.get(uploadId)?.path ?? ""),
      })),
      provider_labels: ["openmates"],
      source_metadata: { source_name: sourceName, archive_path: name },
    });
  }

  return { source: "openmates", fileType: "openmates-zip", chats: newestFirst(chats), skippedDomains };
}

async function readYamlRecordsById(
  zip: JSZip,
  prefix: string,
): Promise<Map<string, Record<string, unknown>>> {
  const records = new Map<string, Record<string, unknown>>();
  for (const name of Object.keys(zip.files).filter((path) => path.startsWith(prefix) && /\.ya?ml$/i.test(path))) {
    const parsed = parse(await zip.file(name)!.async("string")) as Record<string, unknown> | null;
    if (!parsed || typeof parsed !== "object") continue;
    const id = String(parsed.id ?? "");
    if (id) records.set(id, parsed);
  }
  return records;
}

async function stableFingerprint(
  provider: AccountImportSource,
  sourceChatId: string,
  messages: ParsedImportMessage[],
): Promise<string> {
  const input = JSON.stringify({
    provider,
    source_chat_id: sourceChatId,
    messages: messages.map((message) => ({
      role: message.role,
      source_message_id: message.source_message_id ?? null,
      content: message.content,
    })),
  });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function newestFirst(chats: ParsedImportChat[]): ParsedImportChat[] {
  return [...chats].sort((left, right) => {
    const leftMs = Date.parse(left.updated_at ?? left.created_at ?? "");
    const rightMs = Date.parse(right.updated_at ?? right.created_at ?? "");
    return (Number.isFinite(rightMs) ? rightMs : 0) - (Number.isFinite(leftMs) ? leftMs : 0);
  });
}

async function buildEncryptedImportPackage(chats: ParsedImportChat[]): Promise<{
  chats: Array<Record<string, unknown>>;
  localChats: Array<{ source: ParsedImportChat; chat: Chat; messages: Message[] }>;
}> {
  const encryptedChats: Array<Record<string, unknown>> = [];
  const localChats: Array<{ source: ParsedImportChat; chat: Chat; messages: Message[] }> = [];

  for (const source of chats) {
    const chatId = crypto.randomUUID();
    const { chatKey, encryptedChatKey } = await chatKeyManager.createAndPersistKey(chatId);
    const now = Math.floor(Date.now() / 1000);
    const createdAt = parseImportTimestamp(source.created_at, now);
    const updatedAt = parseImportTimestamp(source.updated_at, createdAt);
    const title = source.title || DEFAULT_TITLE;
    const messages: Message[] = [];
    const encryptedMessages: Array<Record<string, unknown>> = [];
    let previousUserMessageId: string | null = null;

    for (const sourceMessage of source.messages) {
      const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;
      const messageCreatedAt = parseImportTimestamp(sourceMessage.created_at, updatedAt);
      const senderName = sourceMessage.role === "assistant"
        ? "Assistant"
        : sourceMessage.role === "system"
          ? "System"
          : "User";
      encryptedMessages.push({
        message_id: messageId,
        role: sourceMessage.role,
        encrypted_content: await encryptWithChatKey(sourceMessage.content, chatKey),
        encrypted_sender_name: await encryptWithChatKey(senderName, chatKey),
        created_at: messageCreatedAt,
        updated_at: now,
        ...(sourceMessage.role === "assistant" && previousUserMessageId
          ? { user_message_id: previousUserMessageId }
          : {}),
      });
      messages.push({
        message_id: messageId,
        chat_id: chatId,
        role: sourceMessage.role,
        created_at: messageCreatedAt,
        status: "synced",
        content: sourceMessage.content,
      });
      if (sourceMessage.role === "user") previousUserMessageId = messageId;
    }

    const chat: Chat = {
      chat_id: chatId,
      title,
      encrypted_title: null,
      encrypted_chat_key: encryptedChatKey,
      messages_v: messages.length,
      title_v: title ? 1 : 0,
      draft_v: 0,
      last_edited_overall_timestamp: updatedAt,
      unread_count: 0,
      created_at: createdAt,
      updated_at: updatedAt,
      chat_summary: null,
    };
    localChats.push({ source, chat, messages });
    encryptedChats.push({
      chat_id: chatId,
      encrypted_title: await encryptWithChatKey(title, chatKey),
      encrypted_chat_key: encryptedChatKey,
      created_at: createdAt,
      updated_at: updatedAt,
      source_fingerprint: source.source_fingerprint,
      messages: encryptedMessages,
    });
  }

  return { chats: encryptedChats, localChats };
}

async function cacheAcceptedImportsLocally(
  localChats: Array<{ chat: Chat; messages: Message[] }>,
  importedChatIds: string[],
  failures: Array<Record<string, unknown>>,
): Promise<void> {
  const imported = new Set(importedChatIds);
  const failedMessageIds = failedMessageIdsFromPersistence(failures);
  const chatLevelFailureIds = chatLevelFailureIdsFromPersistence(failures);
  for (const item of localChats) {
    if (!imported.has(item.chat.chat_id)) continue;
    if (chatLevelFailureIds.has(item.chat.chat_id)) continue;
    const acceptedMessages = item.messages.filter(
      (message) => !failedMessageIds.has(message.message_id),
    );
    const acceptedChat = { ...item.chat, messages_v: acceptedMessages.length };
    recentImportedChats.set(item.chat.chat_id, {
      chat: acceptedChat,
      messages: acceptedMessages,
    });
    await chatDB.addChat(acceptedChat);
    await chatDB.batchSaveMessages(acceptedMessages);
  }
}

function failedMessageIdsFromPersistence(
  failures: Array<Record<string, unknown>>,
): Set<string> {
  return new Set(
    failures
      .map((failure) => failure.message_id)
      .filter((messageId): messageId is string => typeof messageId === "string" && messageId.length > 0),
  );
}

function failedChatIdsFromPersistence(
  failures: Array<Record<string, unknown>>,
): Set<string> {
  return new Set(
    failures
      .map((failure) => failure.chat_id)
      .filter((chatId): chatId is string => typeof chatId === "string" && chatId.length > 0),
  );
}

function chatLevelFailureIdsFromPersistence(
  failures: Array<Record<string, unknown>>,
): Set<string> {
  return new Set(
    failures
      .filter((failure) => typeof failure.message_id !== "string")
      .map((failure) => failure.chat_id)
      .filter((chatId): chatId is string => typeof chatId === "string" && chatId.length > 0),
  );
}

function acceptedSourceFingerprints(
  localChats: Array<{ source: ParsedImportChat; chat: Chat; messages: Message[] }>,
  importedChatIds: string[],
  failures: Array<Record<string, unknown>>,
): string[] {
  const imported = new Set(importedChatIds);
  const failedChatIds = failedChatIdsFromPersistence(failures);
  return localChats
    .filter((item) => imported.has(item.chat.chat_id) && !failedChatIds.has(item.chat.chat_id))
    .map((item) => item.source.source_fingerprint);
}

function countBlockedMessages(
  blockedMessages: Array<Record<string, unknown>>,
  sourceChatId: string | null | undefined,
): number {
  if (!sourceChatId) return 0;
  return blockedMessages.filter((item) => {
    const blockedChatId = item.source_chat_id ?? item.chat_id;
    return typeof blockedChatId === "string" && blockedChatId === sourceChatId;
  }).length;
}

function parseImportTimestamp(value: string | null | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : fallback;
}

async function readJsonResponse<T>(response: Response, label: string): Promise<T> {
  const data = await response.json().catch(() => ({}));
  if (response.ok) return data as T;
  const detail = typeof (data as { detail?: unknown }).detail === "string"
    ? (data as { detail: string }).detail
    : null;
  if (response.status === 429) {
    throw new Error("Too many import requests. Please wait a moment and try again.");
  }
  if (response.status === 402) {
    throw new Error("Insufficient credits to import. Please top up your balance.");
  }
  throw new Error(detail || `${label} (HTTP ${response.status})`);
}
