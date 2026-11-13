// frontend/packages/ui/src/services/chatImportService.ts
//
// Account Import V1 browser service for Settings -> Account -> Import.
// Parses provider exports locally, then uses the resumable preview -> confirm ->
// scan -> status -> compress -> encrypt -> persist -> complete contract.
// Permanent server persistence receives only client-encrypted private fields.
//
// Spec: docs/specs/account-import-v1/spec.yml

import { getApiEndpoint, apiEndpoints } from "../config/api";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
import type { Chat, Message } from "../types/chat";
import type {
  AccountImportParserFormat, AccountImportSource, ImportCostEstimate, ImportFileType, ImportProgressCallback,
  ParsedAccountImport, ParsedImportChat, ParsedImportMessage,
} from "./chatImportTypes";
import {
  rustBuildMessageBatches, rustEstimateImportCost, rustParseImportFile,
} from "./rustCore/transfer/rustChatImport";

export type * from "./chatImportTypes";

const DEFAULT_TITLE = "Imported chat";
const IMPORT_MESSAGE_BATCH_SIZE = 250;
const COMPRESSION_SUMMARY_CATEGORY = "compression_summary";


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
  batch_id?: string;
  sequence?: number;
  status?: "acknowledged" | "failed";
  chats: ParsedImportChat[];
  credits_reserved: number;
  messages_blocked: Array<Record<string, unknown>>;
  failures: Array<Record<string, unknown>>;
}

interface ImportCompressionResponse {
  batch_id: string;
  sequence: number;
  status: "acknowledged" | "failed";
  summary?: string;
  retryable?: boolean;
  failures: Array<Record<string, unknown>>;
}

interface ImportStatusResponse {
  last_scan_sequence: number;
  last_compression_sequence: number;
}

interface SanitizedImportBatch {
  messages: ParsedImportMessage[];
  scanSequence: number;
  sourceFingerprint: string;
  chunkIndex: number;
}

interface ImportResumeState {
  signature: string;
  confirmed: boolean;
  batches: Awaited<ReturnType<typeof rustBuildMessageBatches>>;
  sanitizedChats: ParsedImportChat[];
  sanitizedBatches: SanitizedImportBatch[];
  summaries: Map<string, string>;
  scan: ImportScanResponse;
  lastScanSequence: number;
  lastCompressionSequence: number;
  encryptedPackage?: Awaited<ReturnType<typeof buildEncryptedImportPackage>>;
  persistence?: ImportPersistResponse;
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

const recentImportedChats = new Map<string, RecentImportedChatData>();
const importResumeStates = new Map<string, ImportResumeState>();

export function clearImportResumeState(importId: string | null | undefined): void {
  if (importId) importResumeStates.delete(importId);
}

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
  // Synchronous by contract (reactive selection UI): the chats were parsed by the Rust unit.
  return rustEstimateImportCost(chats);
}

export async function parseImportFile(
  file: File,
  selectedSourceOrProgress?: AccountImportSource | ImportProgressCallback,
  progressCallback?: ImportProgressCallback,
): Promise<ParsedAccountImport> {
  const selectedSource = typeof selectedSourceOrProgress === "string" ? selectedSourceOrProgress : undefined;
  const onProgress = typeof selectedSourceOrProgress === "function" ? selectedSourceOrProgress : progressCallback;
  return rustParseImportFile(file, selectedSource, onProgress);
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
        parser_format: parsed.parserFormat ?? parserFormatForFileType(parsed.fileType),
        chat_count: parsed.chats.length,
        source_fingerprints: parsed.chats.map((chat) => chat.source_fingerprint),
        estimated_tokens: estimate.totalInputTokens,
        estimated_tokens_by_chat: parsed.chats.map((chat) => estimateImportCost([chat]).totalInputTokens),
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
  options: { maxMessagesPerBatch?: number } = {},
): Promise<ImportChatApiResponse> {
  if (selectedChats.length === 0) throw new Error("No chats selected for import.");
  if (!preview.can_import) {
    throw new Error(`Import is not available: ${preview.reason || "unknown"}`);
  }
  if (selectedChats.length > preview.max_batch_count) {
    throw new Error(`Select ${preview.max_batch_count} chats or fewer for this import.`);
  }

  const importId = preview.import_id;
  const maxMessagesPerBatch = options.maxMessagesPerBatch ?? IMPORT_MESSAGE_BATCH_SIZE;
  const signature = JSON.stringify({
    source: parsed.source,
    fingerprints: selectedChats.map((chat) => chat.source_fingerprint),
    maxMessagesPerBatch,
  });
  let state = importResumeStates.get(importId);
  if (state && state.signature !== signature) {
    clearImportResumeState(importId);
    throw new Error("Import resume state does not match the selected chats. Start a new import preview.");
  }
  if (!state) {
    state = {
      signature,
      confirmed: false,
      batches: await rustBuildMessageBatches(selectedChats, maxMessagesPerBatch),
      sanitizedChats: selectedChats.map((chat) => ({ ...chat, messages: [] as ParsedImportMessage[] })),
      sanitizedBatches: [],
      summaries: new Map<string, string>(),
      scan: { chats: [], credits_reserved: 0, messages_blocked: [], failures: [] },
      lastScanSequence: -1,
      lastCompressionSequence: -1,
    };
    importResumeStates.set(importId, state);
  }

  if (!state.confirmed) {
    onProgress?.("confirming", "Confirming selected chats...");
    await postImportJson(apiEndpoints.accountImports.confirm(importId), {
      selected_fingerprints: selectedChats.map((chat) => chat.source_fingerprint),
    }, "Import confirmation failed");
    state.confirmed = true;
  }
  const initialStatus = await getImportStatus(importId);
  assertResumeCursors(importId, state, initialStatus);

  const { batches, sanitizedChats, sanitizedBatches, summaries } = state;
  onProgress?.("scanning", `Safety-scanning ${selectedChats.length} chat(s)...`);
  for (let sequence = initialStatus.last_scan_sequence + 1; sequence < batches.length; sequence++) {
    const batch = batches[sequence];
    const scanResponse = await postImportJson<ImportScanResponse>(apiEndpoints.accountImports.scan(importId), {
      batch_id: batch.batchId,
      sequence,
      final_batch: sequence === batches.length - 1,
      chats: [batch.chat],
    }, "Import scan failed");
    if (scanResponse.status !== "acknowledged" || scanResponse.sequence !== sequence || scanResponse.batch_id !== batch.batchId || !Array.isArray(scanResponse.chats)) {
      throw new Error("Import scan failed: batch was not acknowledged at the expected cursor.");
    }
    if (scanResponse.failures?.length) {
      await completeFailedImport(importId, scanResponse.failures);
      clearImportResumeState(importId);
      throw new Error("Import scan failed for one or more selected chats. No content was imported; try again.");
    }
    const sanitizedChat = scanResponse.chats[0];
    if (!sanitizedChat && scanResponse.messages_blocked?.length) {
      state.scan = mergeScanResponses(state.scan, scanResponse);
      state.lastScanSequence = sequence;
      continue;
    }
    if (!sanitizedChat) throw new Error("Import scan failed: response omitted the sanitized batch.");
    sanitizedChats[batch.chatIndex].messages.push(...sanitizedChat.messages);
    sanitizedBatches.push({ messages: sanitizedChat.messages, scanSequence: sequence, sourceFingerprint: batch.sourceFingerprint, chunkIndex: batch.chunkIndex });
    state.scan = mergeScanResponses(state.scan, scanResponse);
    state.lastScanSequence = sequence;
  }
  const postScanStatus = await getImportStatus(importId);
  assertResumeCursors(importId, state, postScanStatus);
  if (postScanStatus.last_scan_sequence !== batches.length - 1) {
    throw new Error("Import scan status cursor did not advance as expected. Retry the import.");
  }
  if (sanitizedChats.every((chat) => chat.messages.length === 0)) {
    clearImportResumeState(importId);
    throw new Error("Import scan blocked all selected chats. No content was imported.");
  }

  onProgress?.("compressing", "Compressing sanitized imported chats...");
  for (let sequence = postScanStatus.last_compression_sequence + 1; sequence < sanitizedBatches.length; sequence++) {
    const batch = sanitizedBatches[sequence];
    const batchId = `compress-${batch.sourceFingerprint.slice(0, 16)}-${batch.chunkIndex}`;
    const priorSummary = summaries.get(batch.sourceFingerprint);
    const finalChatBatch = sanitizedBatches[sequence + 1]?.sourceFingerprint !== batch.sourceFingerprint;
    const compression = await postImportJson<ImportCompressionResponse>(apiEndpoints.accountImports.compress(importId), {
      batch_id: batchId,
      sequence,
      final_batch: finalChatBatch,
      scan_sequence: batch.scanSequence,
      source_fingerprint: batch.sourceFingerprint,
      sanitized_messages: batch.messages,
      ...(priorSummary ? { prior_summary: priorSummary } : {}),
    }, "Import compression failed");
    if (compression.status !== "acknowledged" || compression.sequence !== sequence || compression.batch_id !== batchId) {
      throw new Error("Import compression failed: batch was not acknowledged at the expected cursor.");
    }
    if (compression.failures?.length) {
      throw new Error("Import compression failed retryably. No content was persisted; try again.");
    }
    if (compression.summary?.trim()) summaries.set(batch.sourceFingerprint, compression.summary);
    state.lastCompressionSequence = sequence;
  }
  const postCompressionStatus = await getImportStatus(importId);
  assertResumeCursors(importId, state, postCompressionStatus);
  if (postCompressionStatus.last_compression_sequence !== sanitizedBatches.length - 1) {
    throw new Error("Import compression status cursor did not advance as expected. Retry the import.");
  }
  const chatsWithSummaries = sanitizedChats.map((chat) => appendCompressionSummary(chat, summaries.get(chat.source_fingerprint)));

  onProgress?.("encrypting", "Encrypting imported chats on this device...");
  const encryptedPackage = state.encryptedPackage ?? await buildEncryptedImportPackage(chatsWithSummaries);
  state.encryptedPackage = encryptedPackage;

  let persistence = state.persistence;
  if (!persistence) {
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
    persistence = await readJsonResponse<ImportPersistResponse>(
      persistResponse,
      "Encrypted import persistence failed",
    );
    state.persistence = persistence;
  }

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
  clearImportResumeState(importId);

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
      const importedMessages = acceptedMessages.filter((message) => message.category !== COMPRESSION_SUMMARY_CATEGORY);
      return {
        chat_id: chatId,
        title: local?.source.title ?? null,
        messages_imported: importedMessages.length,
        messages_blocked: countBlockedMessages(state.scan.messages_blocked ?? [], local?.source.source_chat_id),
        credits_charged: complete.credits_charged ?? 0,
        messages: local?.source.messages.filter(
          (message, index) => message.provider_metadata.import_type !== COMPRESSION_SUMMARY_CATEGORY && !failedMessageIds.has(local.messages[index]?.message_id ?? ""),
        ),
      } satisfies ImportedChatResult;
    });

  onProgress?.("done", "Import complete.");
  return {
    imported,
    total_credits_charged: complete.credits_charged ?? 0,
    import_id: importId,
    preview,
    scan: state.scan,
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

async function getImportStatus(importId: string): Promise<ImportStatusResponse> {
  const response = await fetch(getApiEndpoint(apiEndpoints.accountImports.status(importId)), { credentials: "include" });
  return readJsonResponse<ImportStatusResponse>(response, "Import status check failed");
}

function assertResumeCursors(
  importId: string,
  state: ImportResumeState,
  status: ImportStatusResponse,
): void {
  const scanCursorValid = status.last_scan_sequence === state.lastScanSequence
    && status.last_scan_sequence >= -1
    && status.last_scan_sequence < state.batches.length;
  const compressionCursorValid = status.last_compression_sequence === state.lastCompressionSequence
    && status.last_compression_sequence >= -1
    && status.last_compression_sequence < state.sanitizedBatches.length;
  if (scanCursorValid && compressionCursorValid) return;

  clearImportResumeState(importId);
  throw new Error("Import resume cursor does not match this tab's retained sanitized state. Start a new import preview.");
}

function mergeScanResponses(
  previous: ImportScanResponse,
  current: ImportScanResponse,
): ImportScanResponse {
  return {
    ...current,
    chats: [...previous.chats, ...current.chats],
    credits_reserved: Math.max(previous.credits_reserved, current.credits_reserved),
    messages_blocked: [...previous.messages_blocked, ...current.messages_blocked],
    failures: [...previous.failures, ...current.failures],
  };
}

async function postImportJson<T = Record<string, unknown>>(
  endpoint: string,
  body: Record<string, unknown>,
  label: string,
): Promise<T> {
  const response = await fetch(getApiEndpoint(endpoint), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  return readJsonResponse<T>(response, label);
}

function parserFormatForFileType(fileType: ImportFileType): AccountImportParserFormat {
  if (fileType.startsWith("chatgpt")) return "chatgpt";
  if (fileType.startsWith("opencode")) return "opencode";
  if (fileType.startsWith("openmates")) return "openmates";
  if (fileType.startsWith("generic")) return "generic";
  return "claude";
}

function appendCompressionSummary(chat: ParsedImportChat, summary: string | undefined): ParsedImportChat {
  if (!summary?.trim()) return chat;
  return {
    ...chat,
    messages: [...chat.messages, {
      role: "system",
      content: summary,
      created_at: null,
      source_message_id: null,
      provider_metadata: { import_type: COMPRESSION_SUMMARY_CATEGORY },
      imported_assistant_identity: null,
    }],
  };
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
    const encryptedTitle = await encryptWithChatKey(title, chatKey);
    const messages: Message[] = [];
    const encryptedMessages: Array<Record<string, unknown>> = [];
    let previousUserMessageId: string | null = null;

    for (const sourceMessage of source.messages) {
      const messageId = `${chatId.slice(-10)}-${crypto.randomUUID()}`;
      const messageCreatedAt = parseImportTimestamp(sourceMessage.created_at, updatedAt);
      const identity = sourceMessage.role === "assistant" ? sourceMessage.imported_assistant_identity : null;
      const isCompressionSummary = sourceMessage.provider_metadata.import_type === COMPRESSION_SUMMARY_CATEGORY;
      const senderName = sourceMessage.role === "assistant"
        ? identity?.sender_name ?? "AI assistant"
        : sourceMessage.role === "system"
          ? "System"
          : "User";
      encryptedMessages.push({
        message_id: messageId,
        role: sourceMessage.role,
        encrypted_content: await encryptWithChatKey(sourceMessage.content, chatKey),
        encrypted_sender_name: await encryptWithChatKey(senderName, chatKey),
        ...(identity ? {
          encrypted_category: await encryptWithChatKey(identity.category, chatKey),
          encrypted_model_name: await encryptWithChatKey(identity.model_name, chatKey),
        } : isCompressionSummary ? {
          encrypted_category: await encryptWithChatKey(COMPRESSION_SUMMARY_CATEGORY, chatKey),
          encrypted_model_name: await encryptWithChatKey(source.selected_source ?? source.provider, chatKey),
        } : {}),
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
        ...(identity ? {
          sender_name: identity.sender_name,
          category: identity.category,
          model_name: identity.model_name,
        } : isCompressionSummary ? { category: COMPRESSION_SUMMARY_CATEGORY } : {}),
      });
      if (sourceMessage.role === "user") previousUserMessageId = messageId;
    }

    const chat: Chat = {
      chat_id: chatId,
      title,
      encrypted_title: encryptedTitle,
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
      encrypted_title: encryptedTitle,
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
  if ((data as { retryable?: unknown }).retryable === true) {
    throw new Error(`${detail || label}. Nothing was persisted; try again.`);
  }
  throw new Error(detail || `${label} (HTTP ${response.status})`);
}
