/** Ordinary chat messages created by a live, chat-bound voice call. */
import type { Chat, Message } from "../types/chat";
import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { ensureChatKeySafeForWrite } from "./chatKeyWriteGuard";
import { webSocketService } from "./websocketService";
import { get } from "svelte/store";
import { websocketStatus } from "../stores/websocketStatusStore";
import { text as translatedText } from "../i18n/translations";
import { getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { userDB } from "./userDB";

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
}

export interface VoiceCallContext {
  history: Array<{ role: "user" | "assistant"; text: string }>;
  summary?: string;
}

const MAX_CONTEXT_MESSAGES = 24;
const MAX_CONTEXT_CHARS = 12_000;
const RECEIPT_TIMEOUT_MS = 15_000;
const MAX_SEND_ATTEMPTS = 3;
const messageQueues = new Map<string, Promise<void>>();
type CallOutbox = { call_id: string; typed_pending?: boolean; typed_pending_at?: number;
  entries: Array<{ revision: number; ciphertext: string }> };
type CallRow = Message & { call_persistence_v1?: CallOutbox };
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

function awaitReceipt(type: "encrypted_metadata_stored" | "call_message_confirmed",
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
export async function prepareVoiceCallChat(existingChatId?: string): Promise<{ chatId: string } & VoiceCallContext> {
  if (existingChatId) {
    const chat = await chatDB.getChat(existingChatId);
    if (!chat || chat.team_id || chat.chat_visibility === "direct") throw new Error("Voice calls need a personal chat");
    const key = await chatKeyManager.getKey(existingChatId);
    if (!key || !await ensureChatKeySafeForWrite(existingChatId, key, "voice call")) {
      throw new Error("Chat key unavailable for voice call");
    }
    return { chatId: existingChatId, ...await loadCallContext(existingChatId) };
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
  return { chatId, history: [] };
}

export async function loadCallContext(chatId: string): Promise<VoiceCallContext> {
  const chat = await chatDB.getChat(chatId);
  if (!chat || chat.team_id || chat.chat_visibility === "direct") throw new Error("Voice call chat unavailable");
  const window = await chatDB.getMessageWindowForChat(chatId, { limit: MAX_CONTEXT_MESSAGES });
  const summary = typeof chat.chat_summary === "string" ? chat.chat_summary.trim().slice(0, 2_000) : undefined;
  const history = window.messages
    .filter((message) => (message.role === "user" || message.role === "assistant") &&
      typeof message.content === "string" && message.content.trim())
    .map((message) => ({ role: message.role as "user" | "assistant", text: message.content!.trim().slice(-4_000),
      messageId: message.message_id, userMessageId: message.user_message_id }));
  // The stored window is ordered by (second, ID). A linked assistant must never
  // precede its user turn if both happened in the same second.
  for (let index = 0; index < history.length; index++) {
    const turn = history[index];
    if (turn.role !== "assistant" || !turn.userMessageId) continue;
    const userIndex = history.findIndex((candidate) => candidate.messageId === turn.userMessageId);
    if (userIndex > index) {
      history.splice(index, 1);
      history.splice(userIndex, 0, turn);
    }
  }
  let remaining = MAX_CONTEXT_CHARS - (summary?.length ?? 0);
  const bounded: VoiceCallContext["history"] = [];
  for (const turn of history.reverse()) {
    if (!remaining) break;
    const text = turn.text.slice(-remaining);
    bounded.unshift({ role: turn.role, text });
    remaining -= text.length;
  }
  return { history: bounded, ...(summary ? { summary } : {}) };
}

async function putEncryptedMessage(message: Message, revision: number, callId?: string,
                                   final = false): Promise<string> {
  const key = await chatKeyManager.getKey(message.chat_id);
  if (!key || !await ensureChatKeySafeForWrite(message.chat_id, key, "voice transcript")) {
    throw new Error("Chat key unavailable for transcript");
  }
  const encrypted = await chatDB.getEncryptedFields(message, message.chat_id);
  if (!encrypted.encrypted_content) throw new Error("Transcript encryption failed");
  const transaction = await chatDB.getTransaction("messages", "readwrite");
  await new Promise<void>((resolve, reject) => {
    const store = transaction.objectStore("messages");
    const request = store.get(message.message_id);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const previous = request.result as CallRow | undefined;
      if (previous && (previous.chat_id !== message.chat_id || previous.role !== message.role)) {
        transaction.abort();
        reject(new Error("Call message identity conflict"));
        return;
      }
      if (previous && (previous.queue_revision ?? 0) > revision) return;
      const outbox: CallOutbox | undefined = callId ? {
        call_id: callId,
        typed_pending: !final && message.status === "sending",
        ...(!final && message.status === "sending" ? { typed_pending_at: Date.now() } : {}),
        entries: [...(previous?.call_persistence_v1?.entries ?? []),
          ...(final ? [{ revision, ciphertext: encrypted.encrypted_content! }] : [])],
      } : previous?.call_persistence_v1;
      const raw: CallRow = {
        ...previous, message_id: message.message_id, chat_id: message.chat_id,
        role: message.role, created_at: previous?.created_at ?? message.created_at,
        status: message.status, queue_revision: revision,
        encrypted_content: encrypted.encrypted_content,
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
  await emitChatUpdate(message.chat_id, message);
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
                                   ciphertext: string): Promise<void> {
  // Use the same ciphertext for each retry: a randomized second encryption is
  // a different attempted revision and must not masquerade as an idempotent replay.
  const requestId = crypto.randomUUID();
  for (let attempt = 0; attempt < MAX_SEND_ATTEMPTS; attempt++) {
    const receipt = awaitReceipt("call_message_confirmed", (event) => event.request_id === requestId);
    try {
      await webSocketService.sendMessage("call_message_completed", {
        request_id: requestId, call_id: callId, chat_id: message.chat_id,
        message_id: message.message_id, role: message.role,
        encrypted_content: ciphertext, created_at: message.created_at,
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
    await sendFinalCiphertext(row.call_persistence_v1!.call_id, row, entry.revision, entry.ciphertext);
  }
}

function serializeMessage(messageId: string, work: () => Promise<void>): Promise<void> {
  const previous = messageQueues.get(messageId) ?? Promise.resolve();
  const current = previous.catch(() => {}).then(work);
  messageQueues.set(messageId, current);
  void current.finally(() => { if (messageQueues.get(messageId) === current) messageQueues.delete(messageId); }).catch(() => {});
  return current;
}

/** Upsert cumulative provisional text; only complete or interrupted text reaches storage. */
export function upsertCallTranscript(event: CallTranscriptUpdate): Promise<void> {
  return serializeMessage(event.messageId, async () => {
    const text = event.text.trim();
    if (!text) return;
    const existing = await chatDB.getMessage(event.messageId);
    if (existing && (existing.chat_id !== event.chatId || existing.role !== event.role)) {
      throw new Error("Call message identity conflict");
    }
    const content = event.interrupted && event.role === "assistant"
      ? `${text}\n\n_(${get(translatedText)("voicecall.interrupted")})_` : text;
    if (existing?.content === content) {
      if (!event.final || existing.status === "synced") return;
      if ((existing as CallRow).call_persistence_v1?.entries.length) {
        await drainCallOutbox(event.messageId);
        return;
      }
    }
    const revision = event.final
      ? (existing && existing.status !== "streaming" && existing.content !== content
        ? (existing.queue_revision ?? 1) + 1 : Math.max(1, existing?.queue_revision ?? 1))
      : Math.max(1, existing?.queue_revision ?? 1);
    const message: Message = {
      message_id: event.messageId, chat_id: event.chatId,
      role: event.role, content,
      created_at: existing?.created_at ?? event.createdAt ?? seconds(),
      status: event.final ? "sending" : "streaming",
      ...(event.role === "assistant" && event.userMessageId ? { user_message_id: event.userMessageId } : {}),
    };
    await putEncryptedMessage(message, revision, event.callId, event.final);
    if (!event.final) return;
    await drainCallOutbox(event.messageId);
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

/** Replay only server-issued ciphertext; never invoke the ordinary AI sender. */
export async function retryPendingCallMessages(): Promise<void> {
  let cursor: [number | string, number, string] | null = null;
  do {
    const page = await chatDB.getPendingMessageRetryPage("sending", cursor);
    for (const row of page.rows as CallRow[]) {
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
      if (previous && previous.queue_revision === revision && previous.encrypted_content === ciphertext) return;
      store.put({
        ...previous, message_id: messageId, chat_id: chatId, role,
        encrypted_content: ciphertext, created_at: previous?.created_at ?? createdAt,
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
