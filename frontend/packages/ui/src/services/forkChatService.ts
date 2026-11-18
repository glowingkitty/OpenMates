// frontend/packages/ui/src/services/forkChatService.ts
//
// Implements the "Fork Conversation" feature.
//
// A fork creates a brand-new chat that contains a copy of all messages from
// the source chat up to and including a selected message. Everything runs
// entirely on the client (zero-knowledge: the server never decrypts anything).
//
// Architecture overview:
//   1. Fetch all messages for the source chat from IndexedDB (already decrypted).
//   2. Slice the list to include only messages up to the fork point.
//   3. Generate a new chat ID and new AES chat key.
//   4. Re-encrypt every message field with the new key.
//   5. Copy category + icon from source chat (decrypt with source key, re-encrypt with new key).
//   6. Save the new chat + all copied messages in one IndexedDB transaction.
//   7. Sync to the server via encrypted_chat_metadata:
//      - message_history (encrypted) + chat metadata → Directus
//        (permanent encrypted persistence of all messages + title/category/icon)
//   8. Update forkProgressStore throughout to drive UI.
//   9. On completion: fire a "fork complete" notification that opens the new chat.
//
// AI context on first follow-up:
//   The forked chat has no server-side AI cache. When the user sends their first
//   follow-up message, the backend sends request_chat_history, and the client
//   responds with all messages from IndexedDB (including active_focus_id). This
//   is the same recovery mechanism used by all client-created chats (inspiration,
//   onboarding, etc.) — no proactive plaintext sync is needed.
//
// Background processing:
//   The caller can navigate away freely while the fork runs. The operation is
//   async and non-blocking. forkProgressStore is global and survives navigation.

import { chatDB } from "./db";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { forkProgressStore } from "../stores/forkProgressStore";
import { notificationStore } from "../stores/notificationStore";
import { activeChatStore } from "../stores/activeChatStore";
import { chatSyncService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import { websocketStatus } from "../stores/websocketStatusStore";
import { text } from "@repo/ui";
import { get } from "svelte/store";
import type { Message, Chat } from "../types/chat";
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from "./drafts/draftConstants";

// Delay between batches (ms) to allow the UI to breathe.
const BATCH_DELAY_MS = 0; // Use microtask-level yield (requestAnimationFrame below)

interface StartForkOptions {
  suppressCompleteNotification?: boolean;
  afterForkComplete?: (newChatId: string) => Promise<void> | void;
  awaitStorageSync?: boolean;
}

interface ExplainInNewChatOptions {
  sourceChatId: string;
  upToMessageId: string;
  selectedText: string;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Start a background fork operation.
 *
 * @param sourceChatId   The chat being forked.
 * @param upToMessageId  The ID of the last message to include (inclusive).
 * @param forkTitle      Plaintext title for the new chat.
 * @returns              The new chat ID (so the caller can deep-link to it later).
 */
export async function startFork(
  sourceChatId: string,
  upToMessageId: string,
  forkTitle: string,
  options: StartForkOptions = {},
): Promise<string> {
  // Guard: only one fork at a time
  const current = forkProgressStore.getSnapshot();
  if (current.status === "running") {
    console.warn(
      "[ForkChatService] Fork already in progress — ignoring new request",
    );
    return current.forkChatId ?? "";
  }

  // Generate new identifiers for the fork
  const newChatId = crypto.randomUUID();

  // Fetch + slice messages synchronously before yielding
  let messages: Message[];
  try {
    messages = await chatDB.getMessagesForChat(sourceChatId);
  } catch (err) {
    console.error("[ForkChatService] Failed to fetch messages for fork:", err);
    throw err;
  }

  // Rust selects (stable created_at sort, up to and including the fork point).
  const rust = await import("./rustCore/chatState/rustFork");
  const messagesToCopy: Message[] = await rust.rustForkSelect(messages, upToMessageId);

  // Register in the progress store — UI components can now render progress
  forkProgressStore.start(
    sourceChatId,
    newChatId,
    forkTitle,
    messagesToCopy.length,
  );

  // Run the actual work asynchronously so the caller returns immediately
  runForkAsync(sourceChatId, newChatId, forkTitle, messagesToCopy, options).catch(
    (err) => {
      console.error("[ForkChatService] Fork failed:", err);
      forkProgressStore.fail(err?.message ?? "Unknown error");
      notificationStore.error("fork.error_notification");
    },
  );

  return newChatId;
}

export async function startExplainInNewChat({
  selectedText,
}: ExplainInNewChatOptions): Promise<string> {
  const normalizedSelection = await (await import("./rustCore/chatState/rustFork")).rustNormalizeExplainSelection(selectedText);
  if (!normalizedSelection) {
    throw new Error("Selected text is required to start an explanation chat");
  }

  const $text = get(text);
  const prompt = $text("chats.explain_in_new_chat.prompt", {
    values: { term: normalizedSelection },
  });

  const newChatId = await createCleanExplanationChat(prompt);

  notificationStore.addNotificationWithOptions("info", {
    title: $text("chats.explain_in_new_chat.started_title"),
    message: $text("chats.explain_in_new_chat.started_message", {
      values: { term: normalizedSelection },
    }),
    duration: 12_000,
    dismissible: true,
    actionLabel: $text("chats.explain_in_new_chat.open_action"),
    dedupeKey: `explain-in-new-chat:${newChatId}`,
    onAction: () => {
      void openChatWhenAvailable(newChatId);
    },
  });

  return newChatId;
}

// ---------------------------------------------------------------------------
// Internal async implementation
// ---------------------------------------------------------------------------

async function runForkAsync(
  sourceChatId: string,
  newChatId: string,
  forkTitle: string,
  messagesToCopy: Message[],
  options: StartForkOptions,
): Promise<void> {
  console.info(
    `[ForkChatService] Starting fork: ${sourceChatId} → ${newChatId} ` +
      `(${messagesToCopy.length} messages)`,
  );

  return runRustForkAsync(sourceChatId, newChatId, forkTitle, messagesToCopy, options);
}

/**
 * Fork: Rust re-encrypts the messages and builds the chat record and the
 * `encrypted_chat_metadata` payload; the page keeps key creation, IndexedDB,
 * progress, the socket send and the notification.
 */
async function runRustForkAsync(
  sourceChatId: string,
  newChatId: string,
  forkTitle: string,
  messagesToCopy: Message[],
  options: StartForkOptions,
): Promise<void> {
  const rust = await import("./rustCore/chatState/rustFork");
  const { chatKey: newChatKey, encryptedChatKey: encryptedNewChatKey } =
    await chatKeyManager.createAndPersistKey(newChatId);
  const nowTimestamp = Math.floor(Date.now() / 1000);
  const sourceChat = await chatDB.getChat(sourceChatId);
  const sourceChatKey = await chatKeyManager.getKey(sourceChatId);
  const built = await rust.rustForkBuild({
    sourceChat, sourceChatKey, newChatId, newChatKey, encryptedNewChatKey, forkTitle,
    messages: messagesToCopy, nowSeconds: nowTimestamp,
    onProgress: (processed) => forkProgressStore.updateProgress(processed),
    yieldToEventLoop,
  });

  chatDB.setChatKey(newChatId, newChatKey);
  await chatDB.addChat(built.record);
  await chatDB.batchSaveMessages(built.rows);

  const storageSync = get(websocketStatus).status === "connected"
    ? webSocketService.sendMessage("encrypted_chat_metadata", built.payload).catch((err) => {
        console.warn("[ForkChatService] Encrypted storage sync failed (will reconcile via phased_sync):", err);
      })
    : Promise.resolve();
  if (options.awaitStorageSync) await storageSync;
  if (options.afterForkComplete) await options.afterForkComplete(newChatId);

  forkProgressStore.complete();
  if (options.suppressCompleteNotification) return;
  const $text = get(text);
  notificationStore.addNotificationWithOptions("success", {
    message: $text("chats.fork.complete_notification"),
    duration: 12000,
    dismissible: true,
    onAction: () => {
      void openChatWhenAvailable(newChatId).finally(() => {
        forkProgressStore.reset();
      });
    },
    actionLabel: $text("chats.fork.complete_notification"),
  });
}

/** Options of a background chat whose first message is sent through the normal send path. */
export interface BackgroundChatPromptOptions {
  chatId: string;
  prompt: string;
  senderName?: string;
  /** Chat that spawned this chat (chat orchestration). */
  creatorChatId?: string;
  /** Transient server classification of a creator-sent message. */
  orchestrationJobId?: string;
}

async function sendBackgroundExplanationPrompt(
  chatId: string, prompt: string, options: Pick<BackgroundChatPromptOptions, "senderName" | "orchestrationJobId"> = {},
): Promise<void> {
  const nowTimestamp = Math.floor(Date.now() / 1000);
  const message: Message = {
    message_id: `${chatId.slice(-10)}-${crypto.randomUUID()}`,
    chat_id: chatId,
    role: "user",
    content: prompt,
    status: get(websocketStatus).status === "connected" ? "sending" : "waiting_for_internet",
    created_at: nowTimestamp,
    sender_name: options.senderName ?? "user",
    encrypted_content: null,
    ...(options.orchestrationJobId ? { orchestration_job_id: options.orchestrationJobId } : {}),
  };

  await chatDB.saveMessage(message);

  const chat = await chatDB.getChat(chatId);
  if (chat) {
    await chatDB.addChat({
      ...chat,
      messages_v: (chat.messages_v ?? 0) + 1,
      updated_at: nowTimestamp,
      last_edited_overall_timestamp: nowTimestamp,
    });
  }

  window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: chatId } }));
  await chatSyncService.sendNewMessage(message);
}

async function createCleanExplanationChat(prompt: string): Promise<string> {
  const chatId = crypto.randomUUID();
  await createBackgroundChatWithPrompt({ chatId, prompt });
  return chatId;
}

/**
 * Creates a chat with a NEW key locally and sends `prompt` as its first user
 * message through the normal send path, without opening it.
 */
export async function createBackgroundChatWithPrompt(options: BackgroundChatPromptOptions): Promise<void> {
  const { chatId, prompt } = options;
  const nowTimestamp = Math.floor(Date.now() / 1000);
  const { encryptedChatKey } = await chatKeyManager.createAndPersistKey(chatId);

  const chat: Chat = {
    chat_id: chatId,
    encrypted_title: null,
    encrypted_chat_key: encryptedChatKey,
    messages_v: 0,
    title_v: 0,
    draft_v: 0,
    encrypted_draft_md: null,
    encrypted_draft_preview: null,
    last_edited_overall_timestamp: nowTimestamp,
    unread_count: 0,
    created_at: nowTimestamp,
    updated_at: nowTimestamp,
    processing_metadata: false,
    waiting_for_metadata: true,
    is_incognito: false,
    ...(options.creatorChatId ? { creator_chat_id: options.creatorChatId } : {}),
  };

  await chatDB.addChat(chat);
  window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: chatId } }));
  await sendBackgroundExplanationPrompt(chatId, prompt, options);
}

/** Sends `text` as a user message of an existing chat through the normal send path. */
export async function sendBackgroundChatMessage(
  chatId: string, text: string, options: Pick<BackgroundChatPromptOptions, "senderName" | "orchestrationJobId">,
): Promise<void> {
  await sendBackgroundExplanationPrompt(chatId, text, options);
}

export async function openChatWhenAvailable(chatId: string): Promise<void> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const chat = await chatDB.getChat(chatId);
    if (chat) {
      window.dispatchEvent(new CustomEvent("chatHeaderNavigation", {
        detail: { chat, scrollToTop: false },
      }));
      activeChatStore.setActiveChat(chatId);
      void chatSyncService.sendSetActiveChat(chatId).catch((error) => {
        console.warn("[ForkChatService] Failed to persist opened explanation chat:", error);
      });
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  notificationStore.error(get(text)("chats.explain_in_new_chat.failed"));
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Yield execution to the event loop so the browser can process other tasks
 * (re-renders, user input, etc.) between encryption batches.
 */
function yieldToEventLoop(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== "undefined") {
      requestAnimationFrame(() => resolve());
    } else {
      setTimeout(resolve, BATCH_DELAY_MS);
    }
  });
}
