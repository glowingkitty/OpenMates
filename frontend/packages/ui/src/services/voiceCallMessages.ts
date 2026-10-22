/** Ordinary chat messages created by a live, chat-bound voice call. */
import type { Chat, Message, ChatCompressionCheckpoint } from "../types/chat";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { ensureChatKeySafeForWrite } from "./chatKeyWriteGuard";
import { webSocketService } from "./websocketService";
import { get } from "svelte/store";
import { callArtifactReferencesInText, formatVoiceArtifactReference, loadVoiceArtifactReference,
  parseVoiceArtifactReference, type VoiceArtifactReference } from "./voiceCallArtifactReferences";
import { websocketStatus } from "../stores/websocketStatusStore";
import { getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { fetchAuthenticatedChatMessageWindow, loadCanonicalCallCheckpoints } from "./authenticatedChatMessageWindow";
import { getWorkspaceCacheEpoch } from "./workspaceCacheLifecycle";
import { initialChatHistoryGate } from "./initialChatHistoryGate";
import { matesMetadata } from "../data/matesMetadata";
import { userDB } from "./userDB";
import { parseVoiceCallHistoryEvent, voiceCallLifecycleMessageId, type VoiceCallLifecycleEvent } from "./voiceCallLifecycleEvent";

export interface CallTranscriptUpdate {
  callId: string;
  chatId: string;
  messageId: string;
  role: "user" | "assistant";
  text: string;
  final: boolean;
  interrupted?: boolean;
  userMessageId?: string;
  createdAt?: number;
  modelName?: string;
  category?: string;
  senderName?: string;
  embedRefs?: string[];
  embedReferences?: VoiceArtifactReference[];
}

export interface VoiceCallContext {
  history: Array<{ role: "user" | "assistant"; text: string; message_id?: string; created_at?: number }>;
  summary?: string;
  activeFocus?: { app_id: string; focus_id: string; state?: unknown };
  memoryMetadata?: string[];
  mateCategory?: string;
}

const MAX_CONTEXT_MESSAGES = 30; // Matches call-gateway admission.
const CONTEXT_WINDOW_SIZE = 24;
const MAX_CONTEXT_SCAN_MESSAGES = 120;
const MAX_CONTEXT_CHARS = 64_000;
const MAX_CHECKPOINT_CHARS = 48_000;
export class VoiceCallContextError extends Error {
  constructor(readonly code: "context_too_large" | "context_unavailable") { super(code); }
}
const RECEIPT_TIMEOUT_MS = 15_000;
const MAX_SEND_ATTEMPTS = 3;
const messageQueues = new Map<string, Promise<unknown>>();
export interface CallMessagePersistenceProof { revision: number; ciphertext: string }
type CallAttribution = Pick<Message, "encrypted_category" | "encrypted_model_name" | "encrypted_sender_name">;
type CallOutbox = { lifecycle_event?: true; call_id: string; typed_pending?: boolean; typed_pending_at?: number;
  entries: Array<{ revision: number; ciphertext: string } & CallAttribution> };
type CallRow = Message & { call_persistence_v1?: CallOutbox; call_last_final_revision?: number };
const typedCleanupTimers = new Map<string, ReturnType<typeof setTimeout>>();
const TYPED_ACCEPTANCE_GRACE_MS = 30_000;

function seconds(): number { return Math.floor(Date.now() / 1000); }

async function emitChatUpdate(chatId: string, message?: Message): Promise<void> {
  const { chatSyncService } = await import("./chatSyncService");
  const chat = await chatDB.getChat(chatId);
  if (chat) chatSyncService.dispatchEvent(new CustomEvent("chatUpdated", {
    detail: { chat_id: chatId, chat, ...(message ? { newMessage: message } : {}) },
  }));
}

async function emitStoredMessage(messageId: string): Promise<void> {
  const message = await chatDB.getMessage(messageId);
  if (message) await emitChatUpdate(message.chat_id, message);
}

function awaitReceipt(type: "encrypted_metadata_stored" | "call_message_confirmed" | "system_message_confirmed",
                      matches: (payload: Record<string, unknown>) => boolean): {
  promise: Promise<Record<string, unknown>>; cancel: () => void;
} {
  let cancel = () => {};
  const promise = new Promise<Record<string, unknown>>((resolve, reject) => {
    let unsubscribeStatus = () => {};
    let wasConnected = get(websocketStatus).status === "connected";
    const cleanup = () => {
      clearTimeout(timer);
      webSocketService.off(type, onSuccess);
      webSocketService.off("call_message_rejected", onReject);
      unsubscribeStatus();
    };
    const onSuccess = (payload: Record<string, unknown>) => {
      if (!matches(payload)) return;
      cleanup();
      resolve(payload);
    };
    const onReject = (payload: Record<string, unknown>) => {
      if (type !== "call_message_confirmed" || !matches(payload)) return;
      cleanup();
      const error = new Error(`Call message storage rejected: ${String(payload.code ?? "unknown")}`) as Error & { code?: string };
      error.code = typeof payload.code === "string" ? payload.code : undefined;
      reject(error);
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`${type} timed out`));
    }, RECEIPT_TIMEOUT_MS);
    cancel = cleanup;
    webSocketService.on(type, onSuccess);
    if (type === "call_message_confirmed") webSocketService.on("call_message_rejected", onReject);
    if (type === "call_message_confirmed") {
      unsubscribeStatus = websocketStatus.subscribe(({ status }) => {
        if (status === "connected") wasConnected = true;
        else if (wasConnected) {
          cleanup();
          reject(new Error("Call message socket disconnected before confirmation"));
        }
      });
    }
  });
  // A close can arrive while sendMessage is still awaiting its own connection.
  // The caller awaits this promise after sendMessage returns, so attach a handler
  // now to avoid an interim unhandled rejection.
  void promise.catch(() => {});
  return { promise, cancel };
}

/** Create and durably store the empty encrypted personal chat before call admission. */
export async function prepareVoiceCallChat(existingChatId?: string, transportOnly = false): Promise<{ chatId: string } & VoiceCallContext> {
  if (existingChatId) {
    const chat = await chatDB.getChat(existingChatId);
    if (!chat || chat.team_id || chat.chat_visibility === "direct") throw new Error("Voice calls need a personal chat");
    const key = await chatKeyManager.getKey(existingChatId);
    if (!key || !await ensureChatKeySafeForWrite(existingChatId, key, "voice call")) {
      throw new Error("Chat key unavailable for voice call");
    }
    return { chatId: existingChatId, ...(transportOnly ? { history: [] } : await loadCallContext(existingChatId)) };
  }

  const chatId = crypto.randomUUID();
  const now = seconds();
  const profile = await userDB.getUserProfile();
  if (!profile?.user_id) throw new Error("Sign in to start a voice call");
  const shell: Chat = {
    chat_id: chatId, user_id: profile.user_id, team_id: null, encrypted_title: null,
    messages_v: 0, title_v: 0, metadata_v: 0, draft_v: 0,
    created_at: now, updated_at: now, last_edited_overall_timestamp: now,
    unread_count: 0,
  };
  await chatDB.addChat(shell);
  const { chatKey, encryptedChatKey } = await chatKeyManager.createAndPersistKeyLocked(chatId);
  if (!await ensureChatKeySafeForWrite(chatId, chatKey, "voice call")) {
    throw new Error("New chat key unavailable for voice call");
  }
  const stored = awaitReceipt("encrypted_metadata_stored", (event) => event.chat_id === chatId);
  try {
    await webSocketService.sendMessage("encrypted_chat_metadata", {
      chat_id: chatId, encrypted_chat_key: encryptedChatKey, created_at: now,
      versions: { messages_v: 0, title_v: 0, metadata_v: 0, last_edited_overall_timestamp: now },
    });
    await stored.promise;
  } catch (error) {
    stored.cancel();
    throw error;
  }
  await emitChatUpdate(chatId);
  return { chatId, ...(transportOnly ? { history: [] } : await loadCallContext(chatId, false)) };
}

export async function loadCallContext(chatId: string, canonical = true): Promise<VoiceCallContext> {
  const owner = getWorkspaceCacheIdentity();
  const epoch = getWorkspaceCacheEpoch();
  if (initialChatHistoryGate.pending(chatId)) throw new VoiceCallContextError("context_unavailable");
  const chat = await chatDB.getChat(chatId);
  if (!chat || chat.team_id || chat.chat_visibility === "direct") throw new Error("Voice call chat unavailable");
  const key = await chatKeyManager.getKey(chatId);
  if (!key) throw new VoiceCallContextError("context_unavailable");
  const { decryptWithChatKey } = await import("./encryption/MessageEncryptor");
  let remoteCheckpoints: ChatCompressionCheckpoint[] = [];
  if (canonical) {
    try { remoteCheckpoints = await loadCanonicalCallCheckpoints(chatId); }
    catch { throw new VoiceCallContextError("context_unavailable"); }
  }
  const checkpoints = [...remoteCheckpoints, ...(await chatDB.getChatCompressionCheckpoints(chatId))]
    .filter((entry) => entry.chat_id === chatId && entry.encrypted_summary &&
      Number.isSafeInteger(entry.compressed_up_to_timestamp) && entry.compressed_up_to_timestamp > 0 &&
      Number.isSafeInteger(entry.compressed_message_count) && entry.compressed_message_count > 0 &&
      typeof entry.compressed_up_to_message_id === "string" && entry.compressed_up_to_message_id.length > 0)
    .sort((a, b) => b.created_at - a.created_at || b.id.localeCompare(a.id));
  let checkpoint: ChatCompressionCheckpoint | undefined;
  let summary: string | undefined;
  for (const candidate of checkpoints) {
    try {
      const decrypted = await decryptWithChatKey(candidate.encrypted_summary!, key);
      if (decrypted?.trim()) { checkpoint = candidate; summary = decrypted.trim(); break; }
    } catch { /* An older valid client-encrypted checkpoint is preferable to corrupted ciphertext. */ }
  }
  if (checkpoints.length && !checkpoint) throw new VoiceCallContextError("context_unavailable");
  // A checkpoint is a semantic summary, not a disposable overview. Never slice
  // it or silently replace it with chat_summary when the call context is full.
  if ((summary?.length ?? 0) > MAX_CHECKPOINT_CHARS) throw new VoiceCallContextError("context_too_large");
  const covered = new Set(checkpoint?.covered_message_ids ?? []);
  const includeMessage = (message: Message) => {
      if (message.status === "streaming") return false;
      const callRow = message as CallRow;
      // A late final ASR correction keeps its original ID/time. Without a
      // covered-revision manifest, replaying that retained correction is safer
      // than treating the older checkpoint as its authoritative content.
      const correctedCallFinal = !!callRow.call_persistence_v1 && (message.queue_revision ?? 0) > 1;
      const uncovered = !covered.has(message.message_id) &&
        (!checkpoint || message.created_at > checkpoint.compressed_up_to_timestamp ||
          (message.created_at === checkpoint.compressed_up_to_timestamp &&
            message.message_id > checkpoint.compressed_up_to_message_id!));
      return (uncovered || correctedCallFinal) &&
      (message.role === "user" || message.role === "assistant") &&
      typeof message.content === "string" && !!message.content.trim();
    };
  const history: Array<{ role: "user" | "assistant"; text: string; messageId: string;
    userMessageId?: string; createdAt: number }> = [];
  const seen = new Set<string>();
  let fallbackMate: { category: string; createdAt: number } | undefined;
  const knownMate = (category: unknown): category is string => typeof category === "string" && matesMetadata.some(mate => mate.id === category);
  let scanned = 0;
  let before: { timestamp: number; id: string } | undefined;
  for (;;) {
    let window;
    const options = before
      ? { direction: "before" as const, limit: CONTEXT_WINDOW_SIZE, beforeTimestamp: before.timestamp, beforeMessageId: before.id }
      : { direction: "latest" as const, limit: CONTEXT_WINDOW_SIZE };
    try {
      if (canonical) {
        const remote = await fetchAuthenticatedChatMessageWindow(chatId, { ...options, includeCanonicalMessages: true });
        window = { ...remote, messages: remote.canonicalMessages ?? remote.messages };
      } else window = await chatDB.getMessageWindowForChat(chatId, options);
    }
    catch { throw new VoiceCallContextError("context_unavailable"); }
    scanned += window.messages.length;
    for (const message of window.messages) {
      if (seen.has(message.message_id)) continue;
      seen.add(message.message_id);
      if (message.role === "assistant" && knownMate(message.category) && (!fallbackMate || message.created_at >= fallbackMate.createdAt)) {
        fallbackMate = { category: message.category, createdAt: message.created_at };
      }
      if (includeMessage(message)) history.push({ role: message.role as "user" | "assistant", text: message.content!.trim(),
        messageId: message.message_id, userMessageId: message.user_message_id, createdAt: message.created_at });
    }
    if (history.length > MAX_CONTEXT_MESSAGES || scanned > MAX_CONTEXT_SCAN_MESSAGES ||
        JSON.stringify(history).length + (summary?.length ?? 0) > MAX_CONTEXT_CHARS) {
      throw new VoiceCallContextError("context_too_large");
    }
    if (!window.hasMoreBefore) break;
    const timestamp = window.startCursor;
    const id = window.startCursorMessageId;
    if (!Number.isSafeInteger(timestamp) || !timestamp || typeof id !== "string" || !id ||
        before && (timestamp > before.timestamp || timestamp === before.timestamp && id >= before.id)) {
      throw new VoiceCallContextError("context_unavailable");
    }
    // The next page belongs entirely to the covered archive. Retained final
    // corrections in this boundary page were already included above.
    if (checkpoint && (timestamp < checkpoint.compressed_up_to_timestamp ||
        timestamp === checkpoint.compressed_up_to_timestamp && id <= checkpoint.compressed_up_to_message_id!)) break;
    if (scanned >= MAX_CONTEXT_SCAN_MESSAGES) throw new VoiceCallContextError("context_too_large");
    before = { timestamp, id };
  }
  history.sort((a, b) => a.createdAt - b.createdAt || a.messageId.localeCompare(b.messageId));
  // Preserve user/assistant ordering even when both were stored in one second.
  for (let index = 0; index < history.length; index++) {
    const turn = history[index];
    if (turn.role !== "assistant" || !turn.userMessageId) continue;
    const userIndex = history.findIndex((candidate) => candidate.messageId === turn.userMessageId);
    if (userIndex > index) { history.splice(index, 1); history.splice(userIndex, 0, turn); }
  }
  let activeFocus: VoiceCallContext["activeFocus"];
  if (chat.encrypted_active_focus_id) {
    const focusId = await decryptWithChatKey(chat.encrypted_active_focus_id, key);
    if (!focusId?.trim() || !focusId.includes("-")) throw new VoiceCallContextError("context_unavailable");
    const separator = focusId.indexOf("-");
    activeFocus = { app_id: focusId.slice(0, separator), focus_id: focusId };
    if (chat.encrypted_focus_phase_state) {
      const phases = await decryptWithChatKey(chat.encrypted_focus_phase_state, key);
      if (!phases) throw new VoiceCallContextError("context_unavailable");
      activeFocus.state = JSON.parse(phases)[focusId];
    }
  }
  // Keys advertise available private memories without granting access to their
  // plaintext. Previously authorized chat-scoped entries remain server-managed.
  const memoryMetadata = await chatDB.getAppSettingsMemoriesMetadataKeys();
  let mateCategory = knownMate(chat.category) ? chat.category : fallbackMate?.category;
  if (chat.encrypted_category) {
    const category = await decryptWithChatKey(chat.encrypted_category, key);
    if (knownMate(category)) mateCategory = category;
  }
  if (owner !== getWorkspaceCacheIdentity() || epoch !== getWorkspaceCacheEpoch()) throw new VoiceCallContextError("context_unavailable");
  const context: VoiceCallContext = { ...(mateCategory ? { mateCategory } : {}), history: history.map(({ role, text, messageId, createdAt }) => ({ role, text, message_id: messageId, created_at: createdAt })),
    ...(summary ? { summary } : {}), ...(activeFocus ? { activeFocus } : {}),
    ...(memoryMetadata.length ? { memoryMetadata } : {}) };
  if (JSON.stringify(context).length > MAX_CONTEXT_CHARS) throw new VoiceCallContextError("context_too_large");
  return context;
}

async function putEncryptedMessage(message: Message, revision: number, callId?: string,
                                   final = false, lifecycle = false, writeGuard?: () => void): Promise<string> {
  writeGuard?.();
  const identity = getWorkspaceCacheIdentity();
  const key = await chatKeyManager.getKey(message.chat_id);
  if (!key || !await ensureChatKeySafeForWrite(message.chat_id, key, "voice transcript")) {
    throw new Error("Chat key unavailable for transcript");
  }
  const encrypted = await chatDB.getEncryptedFields(message, message.chat_id);
  if (!encrypted.encrypted_content) throw new Error("Transcript encryption failed");
  const attribution: CallAttribution = {
    encrypted_category: encrypted.encrypted_category,
    encrypted_model_name: encrypted.encrypted_model_name,
    encrypted_sender_name: encrypted.encrypted_sender_name,
  };
  if (lifecycle && (!identity || identity !== getWorkspaceCacheIdentity())) throw new Error("Call event account changed");
  writeGuard?.();
  const transaction = await chatDB.getTransaction("messages", "readwrite");
  await new Promise<void>((resolve, reject) => {
    const store = transaction.objectStore("messages");
    const request = store.get(message.message_id);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      try { writeGuard?.(); } catch (error) { transaction.abort(); reject(error); return; }
      const previous = request.result as CallRow | undefined;
      if (previous && (previous.chat_id !== message.chat_id || previous.role !== message.role)) {
        transaction.abort();
        reject(new Error("Call message identity conflict"));
        return;
      }
      if (previous && (previous.queue_revision ?? 0) > revision) return;
      const outbox: CallOutbox | undefined = callId ? {
        call_id: callId,
        ...(lifecycle ? { lifecycle_event: true as const } : {}),
        typed_pending: !lifecycle && !final && message.status === "sending",
        ...(!lifecycle && !final && message.status === "sending" ? { typed_pending_at: Date.now() } : {}),
        entries: [...(previous?.call_persistence_v1?.entries ?? []),
          ...(final ? [{ revision, ciphertext: encrypted.encrypted_content!, ...attribution }] : [])],
      } : previous?.call_persistence_v1;
      const raw: CallRow = {
        ...previous, message_id: message.message_id, chat_id: message.chat_id,
        role: message.role, created_at: previous?.created_at ?? message.created_at,
        status: message.status, queue_revision: revision,
        encrypted_content: encrypted.encrypted_content, ...attribution,
        ...(final ? { call_last_final_revision: Math.max(previous?.call_last_final_revision ?? 0, revision) } : {}),
        ...(outbox ? { call_persistence_v1: outbox } : {}),
        ...(message.user_message_id ? { user_message_id: message.user_message_id } : {}),
      };
      delete raw.content;
      delete raw.sender_name;
      delete raw.category;
      delete raw.model_name;
      store.put(raw);
    };
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error("Transcript write aborted"));
  });
  // Emit the stored, decrypted row so the active chat sees the same call-origin
  // marker as a later reload. The constructed message has no outbox metadata.
  await emitStoredMessage(message.message_id);
  if (final) {
    const timer = typedCleanupTimers.get(message.message_id);
    if (timer) clearTimeout(timer);
    typedCleanupTimers.delete(message.message_id);
  }
  return encrypted.encrypted_content;
}

async function rawCallRow(messageId: string): Promise<CallRow | undefined> {
  const tx = await chatDB.getTransaction("messages", "readonly");
  return new Promise((resolve, reject) => {
    const read = tx.objectStore("messages").get(messageId);
    read.onsuccess = () => resolve(read.result as CallRow | undefined);
    read.onerror = () => reject(read.error);
  });
}

async function removeAcknowledgedEntry(messageId: string, revision: number): Promise<void> {
  const tx = await chatDB.getTransaction("messages", "readwrite");
  await new Promise<void>((resolve, reject) => {
    const store = tx.objectStore("messages");
    const read = store.get(messageId);
    read.onsuccess = () => {
      const row = read.result as CallRow | undefined;
      if (!row?.call_persistence_v1) return;
      const entries = row.call_persistence_v1.entries.filter((entry) => entry.revision !== revision);
      store.put({ ...row, status: entries.length ? "sending" : "synced",
        call_persistence_v1: { ...row.call_persistence_v1, typed_pending: false, entries } });
    };
    read.onerror = () => reject(read.error);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("Call receipt update aborted"));
  });
  await emitStoredMessage(messageId);
}

async function sendFinalCiphertext(callId: string, message: CallRow, revision: number,
                                   ciphertext: string, attribution: CallAttribution): Promise<void> {
  // Use the same ciphertext for each retry: a randomized second encryption is
  // a different attempted revision and must not masquerade as an idempotent replay.
  const requestId = crypto.randomUUID();
  for (let attempt = 0; attempt < MAX_SEND_ATTEMPTS; attempt++) {
    const receipt = awaitReceipt("call_message_confirmed", (event) => event.request_id === requestId);
    try {
      await webSocketService.sendMessage("call_message_completed", {
        request_id: requestId, call_id: callId, chat_id: message.chat_id,
        message_id: message.message_id, role: message.role,
        encrypted_content: ciphertext, encrypted_category: attribution.encrypted_category,
        encrypted_model_name: attribution.encrypted_model_name, encrypted_sender_name: attribution.encrypted_sender_name,
        created_at: message.created_at,
        revision, ...(message.user_message_id ? { user_message_id: message.user_message_id } : {}),
      });
      const result = await receipt.promise;
      const confirmedRevision = Number(result.revision);
      if (confirmedRevision !== revision || !["created", "updated", "replayed"].includes(String(result.outcome))) {
        throw new Error("Transcript revision not stored");
      }
      await removeAcknowledgedEntry(message.message_id, revision);
      return;
    } catch (error) {
      receipt.cancel();
      const code = (error as Error & { code?: string }).code;
      if (code === "call_message_not_authorized" || code === "call_message_revision_conflict" ||
          code === "chat_key_mismatch" || code === "call_chat_not_owned") {
        await chatDB.updateMessageStatus(message.message_id, "failed");
        await emitStoredMessage(message.message_id);
        throw error;
      }
      if (attempt === MAX_SEND_ATTEMPTS - 1) throw error;
    }
  }
}

async function drainCallOutbox(messageId: string): Promise<void> {
  while (true) {
    const row = await rawCallRow(messageId);
    const entry = row?.call_persistence_v1?.entries[0];
    if (!row || !entry) return;
    await sendFinalCiphertext(row.call_persistence_v1!.call_id, row, entry.revision, entry.ciphertext, entry);
  }
}

function serializeMessage<T>(messageId: string, work: () => Promise<T>): Promise<T> {
  const previous = messageQueues.get(messageId) ?? Promise.resolve();
  const current = previous.catch(() => {}).then(work);
  messageQueues.set(messageId, current);
  void current.finally(() => { if (messageQueues.get(messageId) === current) messageQueues.delete(messageId); }).catch(() => {});
  return current;
}

async function confirmedCallMessageProof(event: CallTranscriptUpdate,
                                         revision: number): Promise<CallMessagePersistenceProof | undefined> {
  // Decrypted getMessage() results deliberately omit ciphertext. A replay must
  // prove the current encrypted row was server-confirmed, without re-encrypting it.
  const row = await rawCallRow(event.messageId);
  if (!row) return;
  if (row.message_id !== event.messageId || row.chat_id !== event.chatId ||
      row.role !== event.role || row.call_persistence_v1?.call_id !== event.callId) {
    throw new Error("Call message identity conflict");
  }
  if (row.status !== "synced" || row.call_persistence_v1.entries.length ||
      row.call_persistence_v1.typed_pending || row.queue_revision !== revision ||
      !Number.isInteger(revision) || revision < 1 ||
      (row.call_last_final_revision ?? revision) !== revision || !row.encrypted_content) return;
  return { revision, ciphertext: row.encrypted_content };
}

/** Upsert cumulative provisional text; only complete or interrupted text reaches storage. */
async function applyCallTranscript(event: CallTranscriptUpdate, writeGuard?: () => void): Promise<CallMessagePersistenceProof | undefined> {
    writeGuard?.();
    const existing = await chatDB.getMessage(event.messageId);
    if (existing && (existing.chat_id !== event.chatId || existing.role !== event.role ||
        (existing as CallRow).call_persistence_v1?.call_id &&
        (existing as CallRow).call_persistence_v1?.call_id !== event.callId)) {
      throw new Error("Call message identity conflict");
    }
    const references = new Map<string, VoiceArtifactReference>();
    for (const reference of [...callArtifactReferencesInText(existing?.content ?? ""), ...(event.embedReferences ?? [])]) {
      const canonical = parseVoiceArtifactReference(reference);
      if (canonical) references.set(canonical.embed_id, canonical);
    }
    const legacyIds = [...(existing?.content ?? "").matchAll(/\[embed:([A-Za-z0-9_-]{1,240})\]/g)].map((match) => match[1]);
    const refs = [...new Set([...(event.embedRefs ?? []), ...references.keys(), ...legacyIds])]
      .filter((id) => /^[A-Za-z0-9_-]{1,240}$/.test(id));
    for (const id of refs) if (!references.has(id)) {
      const reference = await loadVoiceArtifactReference(id);
      if (reference) references.set(id, reference);
    }
    const existingTextRefs = new Set(callArtifactReferencesInText(event.text).map((reference) => reference.embed_id));
    const spokenText = event.text.replace(/\[embed:([A-Za-z0-9_-]{1,240})\]/g,
      (token, id) => refs.includes(id) ? "" : token).trim();
    const text = [spokenText, ...[...references.values()].filter((reference) => !existingTextRefs.has(reference.embed_id))
      .map(formatVoiceArtifactReference)].filter(Boolean).join("\n\n");
    if (!text) return;
    const content = text;
    const attribution = event.role === "assistant" ? {
      model_name: event.modelName ?? existing?.model_name,
      category: event.category ?? existing?.category,
      sender_name: event.senderName ?? existing?.sender_name,
    } : {};
    if (existing?.content === content && Object.entries(attribution).every(([key, value]) => existing[key as keyof Message] === value)) {
      if (!event.final) return;
      if (existing.status === "synced") return confirmedCallMessageProof(event, existing.queue_revision ?? 1);
      if (existing.status !== "streaming" && (existing as CallRow).call_persistence_v1?.entries.length) {
        await drainCallOutbox(event.messageId);
        return confirmedCallMessageProof(event, existing.queue_revision ?? 1);
      }
    }
    const lastFinalRevision = (existing as CallRow | null)?.call_last_final_revision ??
      (existing && existing.status !== "streaming" && !(existing as CallRow).call_persistence_v1?.typed_pending
        ? existing.queue_revision ?? 0 : 0);
    const revision = event.final
      ? Math.max(1, lastFinalRevision + 1, existing?.queue_revision ?? 1)
      : Math.max(1, existing?.queue_revision ?? 1);
    const message: Message = {
      message_id: event.messageId, chat_id: event.chatId,
      role: event.role, content, ...attribution,
      created_at: existing?.created_at ?? event.createdAt ?? seconds(),
      status: event.final ? "sending" : "streaming",
      ...(event.role === "assistant" && event.userMessageId ? { user_message_id: event.userMessageId } : {}),
    };
    const ciphertext = await putEncryptedMessage(message, revision, event.callId, event.final, false, writeGuard);
    if (!event.final) return;
    await drainCallOutbox(event.messageId);
    return { revision, ciphertext };
}

export function upsertCallTranscript(event: CallTranscriptUpdate): Promise<void> {
  return serializeMessage(event.messageId, () => applyCallTranscript(event)).then(() => {});
}

/** A committed tool artifact is durable even if speech never begins. */
export function upsertCallArtifact(event: Pick<CallTranscriptUpdate,
  "callId" | "chatId" | "messageId" | "userMessageId" | "createdAt" | "embedReferences" | "modelName" | "category" | "senderName"> & { embedRefs: string[] }): Promise<CallMessagePersistenceProof | undefined> {
  return serializeMessage(event.messageId, async () => {
    const existing = await chatDB.getMessage(event.messageId);
    return applyCallTranscript({ ...event, role: "assistant", text: existing?.content ?? "",
      final: true, userMessageId: existing?.user_message_id ?? event.userMessageId });
  });
}

/** Save source snapshots on their issued user turn, including artifact-only turns. */
export function upsertCallUserArtifact(event: Pick<CallTranscriptUpdate,
  "callId" | "chatId" | "messageId" | "createdAt" | "embedReferences">, writeGuard?: () => void): Promise<CallMessagePersistenceProof | undefined> {
  return serializeMessage(event.messageId, async () => {
    const existing = await chatDB.getMessage(event.messageId);
    return applyCallTranscript({ ...event, role: "user", text: existing?.content ?? "", final: true }, writeGuard);
  });
}

/** Keep submitted text locally until the live model accepts and echoes its issued ID. */
export async function persistTypedCallMessage(callId: string, chatId: string, id: string,
                                              text: string, createdAt: number): Promise<void> {
  if (!callId || !text.trim()) throw new Error("No call text to submit");
  await serializeMessage(id, async () => {
    const existing = await chatDB.getMessage(id);
    if (existing && (existing.chat_id !== chatId || existing.role !== "user")) {
      throw new Error("Call message identity conflict");
    }
    await putEncryptedMessage({
      message_id: id, chat_id: chatId, role: "user", content: text,
      created_at: existing?.created_at ?? createdAt, status: "sending",
    }, 1, callId);
  });
}

/** Roll back an unaccepted typed turn; the controller retains its composer draft. */
export async function markTypedCallMessageFailed(callId: string, chatId: string, id: string): Promise<void> {
  await serializeMessage(id, async () => {
    let deleted = false;
    const tx = await chatDB.getTransaction("messages", "readwrite");
    await new Promise<void>((resolve, reject) => {
      const store = tx.objectStore("messages");
      const read = store.get(id);
      read.onsuccess = () => {
        const row = read.result as CallRow | undefined;
        if (row?.chat_id === chatId && row.role === "user" &&
            row.call_persistence_v1?.call_id === callId &&
            row.call_persistence_v1.typed_pending && !row.call_persistence_v1.entries.length) {
          store.delete(id);
          deleted = true;
        }
      };
      read.onerror = () => reject(read.error);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error ?? new Error("Typed call rollback aborted"));
    });
    const timer = typedCleanupTimers.get(id);
    if (timer) clearTimeout(timer);
    typedCleanupTimers.delete(id);
    if (deleted) {
      const { chatSyncService } = await import("./chatSyncService");
      chatSyncService.dispatchEvent(new CustomEvent("messageDeleted", {
        detail: { chatId, messageId: id },
      }));
    }
  });
}

/** Persist first-party lifecycle notices through the existing encrypted system-message protocol.
 * The raw IndexedDB row is the outbox: never retain the plaintext event there.
 * Stable call/kind IDs survive duplicate close callbacks and an interrupted save.
 */
export async function recordCallLifecycle(event: VoiceCallLifecycleEvent): Promise<void> {
  if (!event.chatId || !/^[A-Za-z0-9_-]{8,128}$/.test(event.callId) ||
      !["started", "ended"].includes(event.type) || !Number.isSafeInteger(event.occurredAt) ||
      event.occurredAt <= 0 || !Number.isFinite(event.activeElapsedSeconds) || event.activeElapsedSeconds < 0) {
    throw new Error("Invalid voice call lifecycle event");
  }
  const messageId = voiceCallLifecycleMessageId(event.callId, event.type);
  await serializeMessage(messageId, async () => {
    const identity = getWorkspaceCacheIdentity();
    const chat = await chatDB.getChat(event.chatId);
    if (!identity || !chat || chat.team_id || chat.chat_visibility === "direct") {
      throw new Error("Voice call lifecycle needs a personal chat");
    }
    const existing = await rawCallRow(messageId);
    if (existing && (existing.chat_id !== event.chatId || existing.role !== "system" ||
        (existing.call_persistence_v1 && existing.call_persistence_v1.call_id !== event.callId))) {
      throw new Error("Call event identity conflict");
    }
    if (existing?.status === "synced") {
      // Normal history reload has no local outbox metadata. Verify the encrypted
      // event identity before treating the deterministic ID as a confirmed replay.
      const saved = parseVoiceCallHistoryEvent((await chatDB.getMessage(messageId))?.content ?? "");
      if (saved?.call_id !== event.callId || saved.action !== event.type) throw new Error("Call event identity conflict");
      return;
    }
    if (!existing) {
      const message: Message = { message_id: messageId, chat_id: event.chatId, role: "system",
        content: JSON.stringify({ schema_version: 1, type: "voice_call", action: event.type,
          call_id: event.callId, created_at: event.occurredAt,
          active_elapsed_seconds: Math.floor(event.activeElapsedSeconds) }),
        created_at: event.occurredAt, status: "sending" };
      await putEncryptedMessage(message, 1, event.callId, false, true);
    }
    if (identity !== getWorkspaceCacheIdentity()) throw new Error("Call event account changed");
    const row = await rawCallRow(messageId);
    if (row) await sendCallLifecycleCiphertext(row);
  });
}

async function sendCallLifecycleCiphertext(row: CallRow): Promise<void> {
  if (row.role !== "system" || !row.encrypted_content || !row.call_persistence_v1?.lifecycle_event) return;
  const identity = getWorkspaceCacheIdentity();
  const chat = await chatDB.getChat(row.chat_id);
  const key = await chatKeyManager.getKey(row.chat_id);
  if (!identity || !chat || chat.team_id || chat.chat_visibility === "direct" || !key ||
      !await ensureChatKeySafeForWrite(row.chat_id, key, "voice call lifecycle retry") ||
      identity !== getWorkspaceCacheIdentity()) throw new Error("Call event retry unavailable");
  const receipt = awaitReceipt("system_message_confirmed", (event) =>
    event.chat_id === row.chat_id && event.message_id === row.message_id);
  try {
    await webSocketService.sendMessage("chat_system_message_added", { chat_id: row.chat_id,
      message: { message_id: row.message_id, role: "system", encrypted_content: row.encrypted_content,
        created_at: row.created_at } });
    await receipt.promise;
    if (identity !== getWorkspaceCacheIdentity()) throw new Error("Call event account changed");
    await chatDB.updateMessageStatus(row.message_id, "synced");
    await emitStoredMessage(row.message_id);
  } finally { receipt.cancel(); }
}

/** Replay only server-issued ciphertext; never invoke the ordinary AI sender. */
export async function retryPendingCallMessages(): Promise<void> {
  let cursor: [number | string, number, string] | null = null;
  do {
    const page = await chatDB.getPendingMessageRetryPage("sending", cursor);
    for (const row of page.rows as CallRow[]) {
      if (row.call_persistence_v1?.lifecycle_event) {
        try { await serializeMessage(row.message_id, () => sendCallLifecycleCiphertext(row)); }
        catch { /* Durable encrypted row stays pending for reconnect. */ }
        continue;
      }
      if (row.call_persistence_v1?.typed_pending && !row.call_persistence_v1.entries.length) {
        const pendingAt = row.call_persistence_v1.typed_pending_at ?? 0;
        const remaining = TYPED_ACCEPTANCE_GRACE_MS - (Date.now() - pendingAt);
        if (remaining <= 0) {
          await markTypedCallMessageFailed(row.call_persistence_v1.call_id, row.chat_id, row.message_id);
        } else if (!typedCleanupTimers.has(row.message_id)) {
          const timer = setTimeout(() => {
            typedCleanupTimers.delete(row.message_id);
            void markTypedCallMessageFailed(row.call_persistence_v1!.call_id,
              row.chat_id, row.message_id);
          }, remaining);
          typedCleanupTimers.set(row.message_id, timer);
        }
        continue;
      }
      if (!row.call_persistence_v1?.entries.length) continue;
      try { await serializeMessage(row.message_id, () => drainCallOutbox(row.message_id)); }
      catch { /* Leave the ciphertext and unsynced state for the next authorized retry. */ }
    }
    cursor = page.nextCursor;
  } while (cursor);
}

/** Hydrate another device's server-verified ciphertext without re-encryption. */
export async function applyCallMessageChanged(event: Record<string, unknown>): Promise<void> {
  const { chat_id: chatId, message_id: messageId, role, encrypted_content: ciphertext,
    revision, created_at: createdAt, user_message_id: userMessageId } = event;
  if (typeof chatId !== "string" || typeof messageId !== "string" ||
      (role !== "user" && role !== "assistant") || typeof ciphertext !== "string" ||
      !ciphertext || typeof revision !== "number" || !Number.isSafeInteger(revision) ||
      typeof createdAt !== "number" || !Number.isSafeInteger(createdAt)) return;
  const identity = getWorkspaceCacheIdentity();
  if (!identity) return;
  const chat = await chatDB.getChat(chatId);
  if (!chat || chat.team_id || chat.chat_visibility === "direct" || identity !== getWorkspaceCacheIdentity()) return;
  const key = await chatKeyManager.getKey(chatId);
  if (!key || !await ensureChatKeySafeForWrite(chatId, key, "voice transcript sync")) return;
  if (identity !== getWorkspaceCacheIdentity()) return;
  const tx = await chatDB.getTransaction("messages", "readwrite");
  await new Promise<void>((resolve, reject) => {
    const store = tx.objectStore("messages");
    const read = store.get(messageId);
    read.onerror = () => reject(read.error);
    read.onsuccess = () => {
      const previous = read.result as Message | undefined;
      if (previous && (previous.chat_id !== chatId || previous.role !== role)) return;
      if ((previous as CallRow | undefined)?.call_persistence_v1?.entries.length) return;
      if (previous && (previous.queue_revision ?? 0) > (revision as number)) return;
      const attribution: CallAttribution = {};
      for (const key of ["encrypted_category", "encrypted_model_name", "encrypted_sender_name"] as const) {
        if (typeof event[key] === "string") attribution[key] = event[key] as string;
      }
      if (previous && previous.queue_revision === revision && previous.encrypted_content === ciphertext &&
          Object.entries(attribution).every(([key, value]) => previous[key as keyof Message] === value)) return;
      store.put({
        ...previous, message_id: messageId, chat_id: chatId, role,
        encrypted_content: ciphertext, ...attribution, created_at: previous?.created_at ?? createdAt,
        queue_revision: revision, status: "synced",
        ...(role === "assistant" && typeof userMessageId === "string" ? { user_message_id: userMessageId } : {}),
      } as Message);
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("Transcript sync aborted"));
  });
  if (identity !== getWorkspaceCacheIdentity()) return;
  const message = await chatDB.getMessage(messageId);
  if (message?.content) await emitChatUpdate(chatId, message);
}
