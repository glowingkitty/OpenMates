// frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
import type { ChatSynchronizationService } from "./chatSyncService";
import { aiTypingStore } from "../stores/aiTypingStore";
import { chatDB } from "./db"; // Import chatDB
import { storeEmbed } from "./embedResolver"; // Import storeEmbed
import { chatMetadataCache } from "./chatMetadataCache"; // Import for cache invalidation after post-processing
import type { EmbedType } from "../message_parsing/types";
import type { SuggestedSettingsMemoryEntry } from "../types/apps";
import { activeChatStore } from "../stores/activeChatStore";
import { notificationStore } from "../stores/notificationStore";
import { unreadMessagesStore } from "../stores/unreadMessagesStore";
import { webSocketService } from "./websocketService"; // For notifying data activity during AI streaming

// Safe TOON decoder for metadata extraction (local to avoid circular deps)
let toonDecode:
  | ((toonString: string, options?: { strict?: boolean }) => unknown)
  | null = null;
async function decodeToonContentSafe(
  toonContent: string | null | undefined,
): Promise<unknown> {
  if (!toonContent) return null;
  if (typeof toonContent !== "string") {
    if (typeof toonContent === "object") return toonContent;
    return null;
  }
  if (!toonDecode) {
    try {
      const toonModule = await import("@toon-format/toon");
      toonDecode = toonModule.decode;
    } catch (error) {
      console.warn(
        "[ChatSyncService:AI] TOON decoder not available, using JSON fallback:",
        error,
      );
    }
  }
  if (toonDecode) {
    try {
      // Use non-strict mode to be lenient with content that may have edge-case formatting
      // (e.g., large pasted text with unusual indentation or special characters)
      return toonDecode(toonContent, { strict: false });
    } catch (err) {
      console.debug(
        "[ChatSyncService:AI] TOON decode failed, JSON fallback:",
        err instanceof Error ? err.message : String(err),
        {
          contentLength: toonContent.length,
          contentPreview: toonContent.substring(0, 200),
        },
      );
    }
  }
  try {
    return JSON.parse(toonContent);
  } catch {
    return null;
  }
}
import * as LucideIcons from "@lucide/svelte";

/**
 * Check if a string is a valid Lucide icon name
 */
function isValidLucideIcon(iconName: string): boolean {
  // Convert kebab-case to PascalCase (e.g., 'help-circle' -> 'HelpCircle')
  const pascalCaseName = iconName
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join("");

  return pascalCaseName in LucideIcons;
}

/**
 * Get fallback icon for a category when no icon names are provided
 */
function getFallbackIconForCategory(category: string): string {
  const categoryIcons: Record<string, string> = {
    software_development: "code",
    business_development: "briefcase",
    medical_health: "heart",
    legal_law: "gavel",
    maker_prototyping: "wrench",
    marketing_sales: "megaphone",
    finance: "dollar-sign",
    design: "palette",
    electrical_engineering: "zap",
    movies_tv: "tv",
    history: "clock",
    science: "microscope",
    life_coach_psychology: "users",
    cooking_food: "utensils",
    activism: "trending-up",
    general_knowledge: "help-circle",
  };

  return categoryIcons[category] || "help-circle";
}

import type {
  Chat, // Import Chat type
  Message,
  AITaskInitiatedPayload,
  AIMessageUpdatePayload,
  AIBackgroundResponseCompletedPayload,
  AITypingStartedPayload,
  AIMessageReadyPayload,
  AITaskCancelRequestedPayload,
  EmbedUpdatePayload,
  SendEmbedDataPayload,
  AIThinkingChunkPayload,
  AIThinkingCompletePayload,
} from "../types/chat"; // Assuming these types might be moved or are already in a shared types file

// --- Deduplication tracking for embed processing ---
// Track which finalized embeds have already been processed to prevent duplicate key generation
// Key: embed_id, Value: true if already processed
const processedFinalizedEmbeds = new Set<string>();

// --- Thinking content buffering (cross-device persistence) ---
// We buffer thinking content per message_id so we can:
// 1) Stream updates to the active chat immediately (UI),
// 2) Persist the completed thinking content to IndexedDB on ALL devices,
//    so reopening the chat shows the thinking section.
type ThinkingBufferEntry = {
  chatId: string;
  content: string;
  signature?: string | null;
  totalTokens?: number | null;
};
const thinkingBufferByMessageId = new Map<string, ThinkingBufferEntry>();

/**
 * Persist completed thinking content into IndexedDB so it syncs across devices.
 * This intentionally runs outside ActiveChat so background tabs/devices still store it.
 */
async function persistThinkingToDb(
  messageId: string,
  chatId: string,
  entry: ThinkingBufferEntry,
): Promise<void> {
  try {
    const existingMessage = await chatDB.getMessage(messageId);

    // If the assistant message doesn't exist yet, create a minimal placeholder.
    // The streaming handler will later update it with full content.
    const messageToSave: Message = existingMessage
      ? { ...existingMessage }
      : {
          message_id: messageId,
          chat_id: chatId,
          role: "assistant",
          created_at: Math.floor(Date.now() / 1000),
          status: "processing",
          encrypted_content: "",
        };

    // Attach thinking metadata so the UI can render it after reload.
    messageToSave.thinking_content = entry.content;
    messageToSave.thinking_signature = entry.signature || undefined;
    if (entry.totalTokens !== undefined && entry.totalTokens !== null) {
      messageToSave.thinking_token_count = entry.totalTokens;
    }
    messageToSave.has_thinking = !!entry.content;

    await chatDB.saveMessage(messageToSave);
    console.debug(
      `[ChatSyncService:AI] ✅ Persisted thinking content for message ${messageId} (chat ${chatId})`,
    );
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error persisting thinking content for message ${messageId}:`,
      error,
    );
  }
}

/**
 * Check if a finalized embed has already been processed
 */
function isEmbedAlreadyProcessed(embedId: string): boolean {
  return processedFinalizedEmbeds.has(embedId);
}

/**
 * Mark an embed as processed (for finalized embeds only)
 */
function markEmbedAsProcessed(embedId: string): void {
  processedFinalizedEmbeds.add(embedId);
}

/**
 * Clear processed embeds tracking (e.g., on logout)
 */
export function clearProcessedEmbedsTracking(): void {
  processedFinalizedEmbeds.clear();
}

// --- AI Task and Stream Event Handler Implementations ---

export function handleAITaskInitiatedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AITaskInitiatedPayload,
): void {
  console.info("[ChatSyncService:AI] Received 'ai_task_initiated':", payload);
  // Accessing public member activeAITasks
  serviceInstance.activeAITasks.set(payload.chat_id, {
    taskId: payload.ai_task_id,
    userMessageId: payload.user_message_id,
  });
  serviceInstance.dispatchEvent(
    new CustomEvent("aiTaskInitiated", { detail: payload }),
  );
}

// --- Thinking/Reasoning Event Handlers ---
// These handlers process thinking content from thinking models (Gemini, Anthropic Claude)
// Thinking content is streamed to a separate channel and displayed above the main response

/**
 * Handle thinking content chunks from thinking models.
 * Dispatches 'aiThinkingChunk' event for ActiveChat to display.
 */
export function handleAIThinkingChunkImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AIThinkingChunkPayload,
): void {
  const messageId = payload.message_id || payload.task_id;
  const contentLength = payload.content?.length || 0;
  const contentPreview =
    payload.content?.substring(0, 80).replace(/\n/g, "\\n") || "(empty)";

  console.log(
    `[ChatSyncService:AI] 🧠 THINKING CHUNK | ` +
      `chat_id: ${payload.chat_id} | ` +
      `task_id: ${payload.task_id} | ` +
      `message_id: ${messageId} | ` +
      `content_length: ${contentLength} chars | ` +
      `preview: "${contentPreview}${contentLength > 80 ? "..." : ""}"`,
  );

  // Buffer thinking content so we can persist on completion.
  // This runs for ALL devices, not just the active chat tab.
  const existing = thinkingBufferByMessageId.get(messageId);
  const updatedEntry: ThinkingBufferEntry = {
    chatId: payload.chat_id,
    content: (existing?.content || "") + (payload.content || ""),
    signature: existing?.signature,
    totalTokens: existing?.totalTokens,
  };
  thinkingBufferByMessageId.set(messageId, updatedEntry);

  // Dispatch event for ActiveChat component to display thinking content
  serviceInstance.dispatchEvent(
    new CustomEvent("aiThinkingChunk", { detail: payload }),
  );
}

/**
 * Handle thinking completion from thinking models.
 * Contains the signature (if provided) and total token count for cost tracking.
 * Dispatches 'aiThinkingComplete' event for ActiveChat to finalize thinking display.
 */
export function handleAIThinkingCompleteImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AIThinkingCompletePayload,
): void {
  const messageId = payload.message_id || payload.task_id;
  console.log(
    `[ChatSyncService:AI] 🧠 THINKING COMPLETE | ` +
      `chat_id: ${payload.chat_id} | ` +
      `task_id: ${payload.task_id} | ` +
      `message_id: ${messageId} | ` +
      `has_signature: ${!!payload.signature} | ` +
      `total_tokens: ${payload.total_tokens || "unknown"}`,
  );

  // Update the buffer with signature/token metadata for persistence.
  const existing = thinkingBufferByMessageId.get(messageId);
  if (existing) {
    thinkingBufferByMessageId.set(messageId, {
      ...existing,
      signature: payload.signature ?? existing.signature,
      totalTokens: payload.total_tokens ?? existing.totalTokens,
    });
  }

  // Dispatch event for ActiveChat component to finalize thinking
  serviceInstance.dispatchEvent(
    new CustomEvent("aiThinkingComplete", { detail: payload }),
  );

  // Persist completed thinking content to IndexedDB so it's available after reload/sync.
  const entryToPersist = thinkingBufferByMessageId.get(messageId);
  if (entryToPersist) {
    void persistThinkingToDb(messageId, payload.chat_id, entryToPersist);
  } else {
    console.warn(
      `[ChatSyncService:AI] Thinking complete received with no buffered content for message ${messageId}`,
    );
  }
}
// --- End Thinking/Reasoning Event Handlers ---

export function handleAIMessageUpdateImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AIMessageUpdatePayload,
): void {
  // Receiving an AI streaming chunk is proof the WebSocket connection is alive.
  // Notify the WebSocket service so it doesn't fire a pong timeout mid-stream
  // (the server may delay its pong response while busy pushing chunks).
  webSocketService.notifyDataActivity();

  // 🔍 STREAMING DEBUG: Log chunk reception with detailed info
  const contentLength = payload.full_content_so_far?.length || 0;
  const contentPreview =
    payload.full_content_so_far?.substring(0, 100).replace(/\n/g, "\\n") ||
    "(empty)";
  const timestamp = new Date().toISOString();

  console.log(
    `[ChatSyncService:AI] 🔵 CHUNK RECEIVED | ` +
      `seq: ${payload.sequence} | ` +
      `chat_id: ${payload.chat_id} | ` +
      `message_id: ${payload.message_id} | ` +
      `content_length: ${contentLength} chars | ` +
      `is_final: ${payload.is_final_chunk} | ` +
      `timestamp: ${timestamp} | ` +
      `preview: "${contentPreview}${contentLength > 100 ? "..." : ""}"`,
  );

  console.debug("[ChatSyncService:AI] Full payload:", payload);

  // Dispatch event for ActiveChat component
  console.log(
    `[ChatSyncService:AI] 🟢 Dispatching 'aiMessageChunk' event (seq: ${payload.sequence})`,
  );
  serviceInstance.dispatchEvent(
    new CustomEvent("aiMessageChunk", { detail: payload }),
  );

  // Process embeds from content if present (streaming or final)
  if (payload.full_content_so_far) {
    processEmbedsFromContent(payload.full_content_so_far).catch((err) => {
      console.error(
        "[ChatSyncService:AI] Error processing embeds from AI message chunk:",
        err,
      );
    });
  }

  if (payload.is_final_chunk) {
    console.log(
      `[ChatSyncService:AI] 🏁 FINAL CHUNK received (seq: ${payload.sequence}, total_length: ${contentLength} chars)`,
    );

    // CRITICAL FIX: ALWAYS clear typing indicator when final chunk is received
    // The typing indicator must be cleared regardless of whether we have task tracking info.
    // Previously, clearTyping was only called if taskInfo existed AND task IDs matched,
    // which caused the typing indicator to persist forever if:
    // 1. ai_task_initiated event was missed (websocket hiccup)
    // 2. Task IDs didn't match for some reason
    aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
    console.info(
      `[ChatSyncService:AI] Typing status cleared for chat ${payload.chat_id} (message_id: ${payload.message_id})`,
    );

    // Clean up task tracking if we have matching task info
    const taskInfo = serviceInstance.activeAITasks.get(payload.chat_id);
    if (taskInfo && taskInfo.taskId === payload.task_id) {
      serviceInstance.activeAITasks.delete(payload.chat_id);
      serviceInstance.dispatchEvent(
        new CustomEvent("aiTaskEnded", {
          detail: {
            chatId: payload.chat_id,
            taskId: payload.task_id,
            status: payload.interrupted_by_revocation
              ? "cancelled"
              : payload.interrupted_by_soft_limit
                ? "timed_out"
                : "completed",
          },
        }),
      );
      console.info(
        `[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${payload.chat_id} considered ended due to final chunk marker.`,
      );
    } else {
      // Task info missing or mismatched - still dispatch event but log warning
      console.warn(
        `[ChatSyncService:AI] ⚠️ Task tracking mismatch for chat ${payload.chat_id}: taskInfo=${taskInfo ? `{taskId: ${taskInfo.taskId}}` : "undefined"}, payload.task_id=${payload.task_id}`,
      );

      // CRITICAL FIX: Clear the active task for this chat anyway to ensure the stop button disappears
      // This handles cases where task IDs might be out of sync or mismatched due to websocket hiccups
      if (taskInfo) {
        serviceInstance.activeAITasks.delete(payload.chat_id);
        console.info(
          `[ChatSyncService:AI] Cleared mismatched active task ${taskInfo.taskId} for chat ${payload.chat_id} because another task ended.`,
        );
      }

      serviceInstance.dispatchEvent(
        new CustomEvent("aiTaskEnded", {
          detail: {
            chatId: payload.chat_id,
            taskId: payload.task_id,
            status: payload.interrupted_by_revocation
              ? "cancelled"
              : payload.interrupted_by_soft_limit
                ? "timed_out"
                : "completed",
          },
        }),
      );
    }
  }
}

/**
 * Process content to extract and fetch embeds found in JSON code blocks (new architecture)
 * and TOON blocks (legacy format)
 */
async function processEmbedsFromContent(content: string): Promise<void> {
  // NEW ARCHITECTURE: Find JSON code blocks with embed references
  // Format: ```json\n{"type": "app_skill_use", "embed_id": "..."}\n```
  const jsonBlockRegex = /```json\n([\s\S]*?)\n```/g;
  let jsonMatch;

  while ((jsonMatch = jsonBlockRegex.exec(content)) !== null) {
    const jsonContent = jsonMatch[1];
    try {
      const embedRef = JSON.parse(jsonContent.trim());
      // Check if this is an embed reference (has type and embed_id)
      if (embedRef.type && embedRef.embed_id) {
        console.debug(
          `[ChatSyncService:AI] Found embed reference in JSON block: ${embedRef.embed_id} (${embedRef.type})`,
        );

        // Request embed data from server via WebSocket
        await requestEmbedFromServer(embedRef.embed_id);
      }
    } catch (e) {
      // Not a valid embed reference, continue
      console.debug(
        "[ChatSyncService:AI] JSON block is not an embed reference:",
        e,
      );
    }
  }

  // LEGACY: Find toon blocks (backward compatibility)
  const toonBlockRegex = /```toon\n([\s\S]*?)\n```/g;
  let toonMatch;

  while ((toonMatch = toonBlockRegex.exec(content)) !== null) {
    const toonContent = toonMatch[1];
    try {
      // We need to find the embed_id associated with this toon content.
      // Look for embed_reference field which contains the ID
      // embed_reference: "{\"type\": \"app_skill_use\", \"embed_id\": \"...\"}"
      // We handle both escaped quotes (in JSON string) and regular quotes
      const embedIdMatch = toonContent.match(
        /embed_id\\?":\s*\\?"([a-f0-9-]+)\\?"/,
      );

      if (embedIdMatch && embedIdMatch[1]) {
        const embedId = embedIdMatch[1];
        const typeMatch = toonContent.match(/type\\?":\s*\\?"([a-z_]+)\\?"/);
        const type = typeMatch ? typeMatch[1] : "app_skill_use";

        console.debug(
          `[ChatSyncService:AI] Found embed in TOON block: ${embedId} (${type})`,
        );

        await storeEmbed({
          embed_id: embedId,
          type: type,
          status: "finished", // Assume finished if we got the response
          content: toonContent, // Store the raw TOON content
          createdAt: Date.now(),
          updatedAt: Date.now(),
        });
      }
    } catch (e) {
      console.error("[ChatSyncService:AI] Error processing TOON block:", e);
    }
  }
}

/**
 * Request embed data from server via WebSocket
 * Server will respond with the vault-encrypted embed from cache
 */
async function requestEmbedFromServer(embedId: string): Promise<void> {
  try {
    const { webSocketService } = await import("./websocketService");

    // Check if embed already exists in local store
    const { embedStore } = await import("./embedStore");
    const existingEmbed = await embedStore.get(`embed:${embedId}`);

    if (existingEmbed && existingEmbed.status === "finished") {
      console.debug(
        `[ChatSyncService:AI] Embed ${embedId} already in local store with finished status, skipping fetch`,
      );
      return;
    }

    // Send request to server via WebSocket
    await webSocketService.sendMessage("request_embed", {
      embed_id: embedId,
    });

    console.debug(
      `[ChatSyncService:AI] Requested embed ${embedId} from server via WebSocket`,
    );
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error requesting embed ${embedId} from server:`,
      error,
    );
  }
}

/**
 * Handles background AI response completion for inactive chats.
 * This allows AI processing to continue when user switches chats,
 * storing the completed response in IndexedDB for later retrieval.
 */
export async function handleAIBackgroundResponseCompletedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AIBackgroundResponseCompletedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AI] Received 'ai_background_response_completed' for inactive chat:",
    payload,
  );

  try {
    // Get chat from DB or incognito service to update messages_v
    let chat: Chat | null = null;
    let isIncognitoChat = false;

    // First check if it's an incognito chat
    const { incognitoChatService } = await import("./incognitoChatService");
    try {
      chat = await incognitoChatService.getChat(payload.chat_id);
      if (chat) {
        isIncognitoChat = true;
      }
    } catch {
      // Not an incognito chat, continue to check IndexedDB
    }

    // If not found in incognito service, check IndexedDB
    if (!chat) {
      chat = await chatDB.getChat(payload.chat_id);
    }

    if (!chat) {
      console.error(
        `[ChatSyncService:AI] Chat ${payload.chat_id} not found in DB or incognito service for background response`,
      );
      return;
    }

    // Get the category and model_name from the payload first (most reliable source),
    // then fall back to typing store if not available (e.g., for older payloads)
    const { get } = await import("svelte/store");
    const typingStatus = get(aiTypingStore);
    let category =
      payload.category ||
      (typingStatus?.chatId === payload.chat_id
        ? typingStatus.category
        : undefined);
    const modelName =
      payload.model_name ||
      (typingStatus?.chatId === payload.chat_id
        ? typingStatus.modelName
        : undefined);

    console.debug(
      `[ChatSyncService:AI] Background response model_name: "${modelName}" for message ${payload.message_id}`,
    );

    // CRITICAL FIX for Issue 2: If category not in typing store (because user switched chats),
    // decrypt the category from the chat's encrypted_category field
    if (!category && chat.encrypted_category) {
      try {
        const { decryptWithChatKey } = await import("./cryptoService");
        const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
        category =
          (await decryptWithChatKey(chat.encrypted_category, chatKey)) ||
          undefined;
        console.info(
          `[ChatSyncService:AI] Retrieved category from chat metadata for background response: ${category}`,
        );
      } catch (error) {
        console.error(
          `[ChatSyncService:AI] Failed to decrypt category from chat metadata:`,
          error,
        );
      }
    }

    // Process embeds from full content
    if (payload.full_content) {
      await processEmbedsFromContent(payload.full_content);
    }

    // Process embeds from full content
    if (payload.full_content) {
      await processEmbedsFromContent(payload.full_content);
    }

    // Process embeds from full content
    if (payload.full_content) {
      await processEmbedsFromContent(payload.full_content);
    }

    // CRITICAL: Retrieve thinking content from buffer if available
    // Thinking content was buffered separately via aiThinkingChunk/aiThinkingComplete events
    // and must be attached to the final message for persistence and cross-device sync.
    const thinkingEntry = thinkingBufferByMessageId.get(payload.message_id);

    // Create the completed AI message
    // CRITICAL: Store AI response as markdown string, not Tiptap JSON
    // Tiptap JSON is only for UI rendering, never stored in database
    // For rejection messages (e.g., insufficient credits), use role 'system' and status 'waiting_for_user'
    const isRejection = !!payload.rejection_reason;
    const aiMessage: Message = {
      message_id: payload.message_id,
      chat_id: payload.chat_id,
      user_message_id: payload.user_message_id,
      role: isRejection ? "system" : "assistant",
      category: category || undefined,
      model_name: modelName || undefined,
      content: payload.full_content, // Store as markdown string, not Tiptap JSON
      status: isRejection ? "waiting_for_user" : "synced",
      created_at: Math.floor(Date.now() / 1000),
      // Note: encrypted fields will be populated by encryptMessageFields in chatDB.saveMessage()
      // Do NOT set encrypted_* fields here as they should only exist after encryption
      encrypted_content: "", // Will be set by encryption
      // Attach thinking content from buffer (for thinking models like Gemini, Claude)
      thinking_content: thinkingEntry?.content || undefined,
      thinking_signature: thinkingEntry?.signature || undefined,
      thinking_token_count: thinkingEntry?.totalTokens ?? undefined,
      has_thinking: !!thinkingEntry?.content,
    };

    // Save message to IndexedDB or incognito service
    if (isIncognitoChat) {
      // Save to incognito service (no encryption needed for incognito chats)
      await incognitoChatService.addMessage(payload.chat_id, aiMessage);
      const newMessagesV = (chat.messages_v || 0) + 1;
      const newLastEdited = Math.floor(Date.now() / 1000);
      await incognitoChatService.updateChat(payload.chat_id, {
        messages_v: newMessagesV,
        last_edited_overall_timestamp: newLastEdited,
      });
      chat.messages_v = newMessagesV;
      chat.last_edited_overall_timestamp = newLastEdited;
      console.info(
        `[ChatSyncService:AI] Saved background AI response to incognito service for chat ${payload.chat_id}`,
      );
    } else {
      // Save message to IndexedDB (encryption handled by chatDB)
      // This will encrypt all fields including encrypted_category
      await chatDB.saveMessage(aiMessage);
      console.info(
        `[ChatSyncService:AI] Saved background AI response to DB for chat ${payload.chat_id} with category: ${category || "none"}`,
      );

      // Update chat metadata with new messages_v
      const newMessagesV = (chat.messages_v || 0) + 1;
      const newLastEdited = Math.floor(Date.now() / 1000);
      const updatedChat: Chat = {
        ...chat,
        messages_v: newMessagesV,
        last_edited_overall_timestamp: newLastEdited,
      };
      await chatDB.updateChat(updatedChat);
      chat = updatedChat;
      console.info(
        `[ChatSyncService:AI] Updated chat ${payload.chat_id} metadata: messages_v=${newMessagesV}`,
      );
    }

    // Clear AI task tracking
    const taskInfo = serviceInstance.activeAITasks.get(payload.chat_id);
    if (taskInfo && taskInfo.taskId === payload.task_id) {
      serviceInstance.activeAITasks.delete(payload.chat_id);
      console.info(
        `[ChatSyncService:AI] Cleared active AI task for chat ${payload.chat_id}`,
      );
    }

    // Clear typing status using message_id (which is what setTyping stores as aiMessageId)
    // Previously used task_id which caused mismatch - typing indicator wouldn't clear
    aiTypingStore.clearTyping(payload.chat_id, payload.message_id);

    // Dispatch chatUpdated event to notify UI (e.g., update chat list)
    // This will NOT update ActiveChat if the chat is not currently open
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: payload.chat_id,
          chat: chat,
          newMessage: aiMessage,
          type: "background_ai_completion",
        },
      }),
    );

    // Dispatch aiTaskEnded event for cleanup
    serviceInstance.dispatchEvent(
      new CustomEvent("aiTaskEnded", {
        detail: {
          chatId: payload.chat_id,
          taskId: payload.task_id,
          status: payload.interrupted_by_revocation
            ? "cancelled"
            : payload.interrupted_by_soft_limit
              ? "timed_out"
              : "completed",
        },
      }),
    );

    console.info(
      `[ChatSyncService:AI] Background AI response processing completed for chat ${payload.chat_id}`,
    );

    // CRITICAL: Send encrypted AI response back to server for Directus storage (zero-knowledge architecture)
    // Skip for incognito chats (they're not stored on the server)
    if (!isIncognitoChat) {
      try {
        console.debug(
          "[ChatSyncService:AI] Sending completed background AI response to server for encrypted Directus storage:",
          {
            messageId: aiMessage.message_id,
            chatId: aiMessage.chat_id,
            contentLength: aiMessage.content?.length || 0,
          },
        );
        await serviceInstance.sendCompletedAIResponse(aiMessage);
      } catch (error) {
        console.error(
          "[ChatSyncService:AI] Error sending completed background AI response to server:",
          error,
        );
      }
    } else {
      console.debug(
        "[ChatSyncService:AI] Skipping server storage for incognito chat - not persisted on server",
      );
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error handling background AI response for chat ${payload.chat_id}:`,
      error,
    );
  }
}

export async function handleAITypingStartedImpl( // Changed to async
  serviceInstance: ChatSynchronizationService,
  payload: AITypingStartedPayload,
): Promise<void> {
  // Added Promise<void>
  console.debug("[ChatSyncService:AI] Received 'ai_typing_started':", payload);

  // Update aiTypingStore first
  aiTypingStore.setTyping(
    payload.chat_id,
    payload.user_message_id,
    payload.message_id,
    payload.category,
    payload.model_name,
    payload.provider_name,
    payload.server_region,
  );

  // DUAL-PHASE ARCHITECTURE: Always send encrypted user message storage
  // For NEW chats (with icon_names): Also handle metadata encryption
  // For FOLLOW-UPS (no icon_names): Only send encrypted user message

  try {
    // Get the current chat (check incognito service first)
    let chat: Chat | null = null;
    let isIncognitoChat = false;

    const { incognitoChatService } = await import("./incognitoChatService");
    try {
      chat = await incognitoChatService.getChat(payload.chat_id);
      if (chat) {
        isIncognitoChat = true;
      }
    } catch {
      // Not an incognito chat, continue to check IndexedDB
    }

    if (!chat) {
      chat = await chatDB.getChat(payload.chat_id);
    }

    if (!chat) {
      console.error(
        `[ChatSyncService:AI] Chat ${payload.chat_id} not found for processing`,
      );
      return;
    }

    // Skip metadata processing for incognito chats (they don't go through post-processing)
    if (isIncognitoChat) {
      console.debug(
        `[ChatSyncService:AI] Skipping metadata processing for incognito chat ${payload.chat_id}`,
      );
      return;
    }

    // CRITICAL: Skip user message persistence for continuation tasks (after app settings/memories confirmation)
    // The user message was already persisted during the initial ai_typing_started event before the pause.
    // Re-persisting would create a duplicate message in Directus.
    if (payload.is_continuation) {
      console.info(
        `[ChatSyncService:AI] Skipping user message persistence for CONTINUATION task in chat ${payload.chat_id} - message already persisted before app settings/memories pause`,
      );
      // Still dispatch the typing event for UI updates
      serviceInstance.dispatchEvent(
        new CustomEvent("aiTypingStarted", { detail: payload }),
      );
      return;
    }

    const isNewChat = payload.icon_names && payload.icon_names.length > 0;

    if (isNewChat) {
      console.info(
        `[ChatSyncService:AI] DUAL-PHASE: Processing metadata encryption for NEW CHAT ${payload.chat_id}:`,
        {
          hasTitle: !!payload.title,
          category: payload.category,
          iconNames: payload.icon_names,
        },
      );
    } else {
      console.info(
        `[ChatSyncService:AI] DUAL-PHASE: Processing FOLLOW-UP message for chat ${payload.chat_id} (no metadata update)`,
      );
    }

    // ONLY for new chats: Update local chat with encrypted metadata
    if (isNewChat) {
      // Encrypt title, icon, and category with chat-specific key for local storage
      let encryptedTitle: string | null = null;
      let encryptedIcon: string | null = null;
      let encryptedCategory: string | null = null;

      // Get or generate chat key for encryption
      const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
      const { encryptWithChatKey } = await import("./cryptoService");

      // Encrypt title if payload has one (only for new chats on first message)
      if (payload.title) {
        encryptedTitle = await encryptWithChatKey(payload.title, chatKey);
        if (!encryptedTitle) {
          console.error(
            `[ChatSyncService:AI] Failed to encrypt title for chat ${payload.chat_id}`,
          );
          return;
        }
      }

      // Encrypt icon and category ONLY if payload has icon_names (only for new chats on first message)
      // Server only sends icon_names when chat doesn't have a title yet
      // CRITICAL: Only update icon and category when icon_names is present to avoid overwriting on follow-ups
      if (payload.icon_names && payload.icon_names.length > 0) {
        console.info(
          `[ChatSyncService:AI] Validating ${payload.icon_names.length} icon names for NEW CHAT: ${payload.icon_names.join(", ")}`,
        );

        // Find the first valid Lucide icon name from the list
        let validIconName: string | null = null;
        for (const iconName of payload.icon_names) {
          if (isValidLucideIcon(iconName)) {
            validIconName = iconName;
            console.info(
              `[ChatSyncService:AI] ✅ Found valid icon: ${iconName}`,
            );
            break;
          } else {
            console.warn(
              `[ChatSyncService:AI] ❌ Invalid icon name: ${iconName}, trying next...`,
            );
          }
        }

        // If no valid icon found, use category fallback
        if (!validIconName) {
          validIconName = getFallbackIconForCategory(
            payload.category || "general_knowledge",
          );
          console.info(
            `[ChatSyncService:AI] 🔄 No valid icons found, using category fallback: ${validIconName}`,
          );
        }

        encryptedIcon = await encryptWithChatKey(validIconName, chatKey);
        if (!encryptedIcon) {
          console.error(
            `[ChatSyncService:AI] Failed to encrypt icon for chat ${payload.chat_id}`,
          );
          return;
        }

        // CRITICAL: Only encrypt and update category when icon_names is present (NEW CHAT ONLY)
        // This prevents overwriting category on follow-up messages
        if (payload.category) {
          encryptedCategory = await encryptWithChatKey(
            payload.category,
            chatKey,
          );
          if (!encryptedCategory) {
            console.error(
              `[ChatSyncService:AI] Failed to encrypt category for chat ${payload.chat_id}`,
            );
            return;
          }
          console.info(
            `[ChatSyncService:AI] ✅ Encrypted category for NEW CHAT: ${payload.category}`,
          );
        } else {
          console.warn(
            `[ChatSyncService:AI] ⚠️ icon_names present but no category - using general_knowledge`,
          );
          encryptedCategory = await encryptWithChatKey(
            "general_knowledge",
            chatKey,
          );
        }
      } else {
        console.debug(
          `[ChatSyncService:AI] No icon_names in payload - chat already has icon/category (follow-up message). NOT updating icon or category.`,
        );
      }

      // Update local chat with encrypted metadata
      try {
        const chatToUpdate = await chatDB.getChat(payload.chat_id);
        if (chatToUpdate) {
          console.info(`[ChatSyncService:AI] ✅ Chat loaded for update:`, {
            chatId: payload.chat_id,
            currentTitleV: chatToUpdate.title_v,
            hasEncryptedIcon: !!chatToUpdate.encrypted_icon,
            hasEncryptedCategory: !!chatToUpdate.encrypted_category,
          });

          // Update chat with encrypted title
          if (encryptedTitle) {
            chatToUpdate.encrypted_title = encryptedTitle;
            chatToUpdate.title_v = (chatToUpdate.title_v || 0) + 1; // Frontend increments title_v
            console.info(
              `[ChatSyncService:AI] ✅ SET encrypted_title, version: ${chatToUpdate.title_v}`,
            );
          }

          // Update chat with encrypted icon (ONLY if encryptedIcon is set - i.e., new chat)
          if (encryptedIcon) {
            chatToUpdate.encrypted_icon = encryptedIcon;
            console.info(
              `[ChatSyncService:AI] ✅ SET encrypted_icon (NEW CHAT):`,
              encryptedIcon.substring(0, 30) + "...",
            );
          } else {
            console.debug(
              `[ChatSyncService:AI] No encrypted_icon to set (follow-up message - preserving existing icon)`,
            );
          }

          // Update chat with encrypted category (ONLY if encryptedCategory is set - i.e., new chat)
          if (encryptedCategory) {
            chatToUpdate.encrypted_category = encryptedCategory;
            console.info(
              `[ChatSyncService:AI] ✅ SET encrypted_category (NEW CHAT):`,
              encryptedCategory.substring(0, 30) + "...",
            );
          } else {
            console.debug(
              `[ChatSyncService:AI] No encrypted_category to set (follow-up message - preserving existing category)`,
            );
          }

          // Ensure chat key is stored for decryption
          const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
          const encryptedChatKey = await import("./cryptoService").then((m) =>
            m.encryptChatKeyWithMasterKey(chatKey),
          );
          if (encryptedChatKey) {
            chatToUpdate.encrypted_chat_key = encryptedChatKey;
            console.info(
              `[ChatSyncService:AI] Stored encrypted chat key for chat ${payload.chat_id}`,
            );
          }

          // Update timestamps
          chatToUpdate.updated_at = Math.floor(Date.now() / 1000);

          console.info(
            `[ChatSyncService:AI] 🔵 BEFORE updateChat - Chat object has:`,
            {
              chatId: chatToUpdate.chat_id,
              hasEncryptedTitle: !!chatToUpdate.encrypted_title,
              hasEncryptedIcon: !!chatToUpdate.encrypted_icon,
              hasEncryptedCategory: !!chatToUpdate.encrypted_category,
              encryptedIconPreview:
                chatToUpdate.encrypted_icon?.substring(0, 20) || "null",
              encryptedCategoryPreview:
                chatToUpdate.encrypted_category?.substring(0, 20) || "null",
            },
          );

          // CRITICAL: Clear waiting_for_metadata flag now that all metadata is ready
          // This transitions the chat from "waiting" state to regular display with full metadata
          if (chatToUpdate.waiting_for_metadata) {
            console.info(
              `[ChatSyncService:AI] 🔄 BEFORE clearing waiting_for_metadata flag:`,
              {
                chatId: chatToUpdate.chat_id,
                waiting_for_metadata: chatToUpdate.waiting_for_metadata,
                hasTitle: !!chatToUpdate.encrypted_title,
                hasIcon: !!chatToUpdate.encrypted_icon,
                hasCategory: !!chatToUpdate.encrypted_category,
              },
            );
            chatToUpdate.waiting_for_metadata = false;
            console.info(
              `[ChatSyncService:AI] ✅ AFTER clearing waiting_for_metadata flag - chat ready for regular display:`,
              {
                chatId: chatToUpdate.chat_id,
                waiting_for_metadata: chatToUpdate.waiting_for_metadata,
              },
            );
          }
          // Also clear deprecated processing_metadata for backwards compatibility
          if (chatToUpdate.processing_metadata) {
            chatToUpdate.processing_metadata = false;
          }

          await chatDB.updateChat(chatToUpdate);

          console.info(
            `[ChatSyncService:AI] ✅ Local chat ${payload.chat_id} updated with encrypted title, icon, category and chat key`,
          );

          // Verify the save by reading back
          const verifyChat = await chatDB.getChat(payload.chat_id);
          console.info(
            `[ChatSyncService:AI] 🔍 VERIFICATION - Chat after save:`,
            {
              chatId: payload.chat_id,
              hasEncryptedTitle: !!verifyChat?.encrypted_title,
              hasEncryptedIcon: !!verifyChat?.encrypted_icon,
              hasEncryptedCategory: !!verifyChat?.encrypted_category,
              encryptedIconPreview:
                verifyChat?.encrypted_icon?.substring(0, 20) || "null",
              encryptedCategoryPreview:
                verifyChat?.encrypted_category?.substring(0, 20) || "null",
              processing_metadata: verifyChat?.processing_metadata,
              processing_metadata_type: typeof verifyChat?.processing_metadata,
            },
          );

          // CRITICAL: Dispatch localChatListChanged event to trigger immediate UI update
          // This ensures the chat appears in the sidebar now that processing_metadata is cleared
          window.dispatchEvent(
            new CustomEvent("localChatListChanged", {
              detail: { chat_id: payload.chat_id },
            }),
          );
          console.info(
            `[ChatSyncService:AI] 📢 Dispatched localChatListChanged event to show chat in sidebar`,
          );

          serviceInstance.dispatchEvent(
            new CustomEvent("chatUpdated", {
              detail: {
                chat_id: payload.chat_id,
                type: "title_updated",
                chat: chatToUpdate,
              },
            }),
          );
        } else {
          console.error(
            `[ChatSyncService:AI] Chat ${payload.chat_id} not found for title update`,
          );
          return;
        }
      } catch (error) {
        console.error(
          `[ChatSyncService:AI] Error updating local chat ${payload.chat_id}:`,
          error,
        );
        return;
      }
    } // END if (isNewChat) - metadata encryption block

    // ALWAYS send encrypted storage package (for both NEW chats and FOLLOW-UPS)
    const { sendEncryptedStoragePackage } =
      await import("./chatSyncServiceSenders");

    // Get the user's pending message (the one being processed)
    // CRITICAL: Use user_message_id from payload if available (most reliable)
    let userMessage: Message | null = null;

    if (payload.user_message_id) {
      // Try to get the specific message by ID first (most reliable)
      userMessage = await chatDB.getMessage(payload.user_message_id);
      if (!userMessage) {
        console.warn(
          `[ChatSyncService:AI] Message ${payload.user_message_id} not found by ID, falling back to latest user message`,
        );
      }
    }

    // Fallback: Get latest user message if ID lookup failed
    if (!userMessage) {
      const messages = await chatDB.getMessagesForChat(payload.chat_id);
      userMessage =
        messages
          .filter((m) => m.role === "user")
          .sort((a, b) => b.created_at - a.created_at)[0] || null;
    }

    if (!userMessage) {
      console.error(
        `[ChatSyncService:AI] No user message found for chat ${payload.chat_id} to encrypt`,
      );
      return;
    }

    // CRITICAL: Validate that message has content (should be decrypted by getMessagesForChat)
    if (!userMessage.content && !userMessage.encrypted_content) {
      console.error(
        `[ChatSyncService:AI] ❌ User message ${userMessage.message_id} has neither content nor encrypted_content! Cannot send to server.`,
      );
      return;
    }

    // CRITICAL: If content is missing but encrypted_content exists, decrypt it now
    if (!userMessage.content && userMessage.encrypted_content) {
      console.warn(
        `[ChatSyncService:AI] Message ${userMessage.message_id} missing content field, decrypting from encrypted_content`,
      );
      const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
      const { decryptWithChatKey } = await import("./cryptoService");
      try {
        const decrypted = await decryptWithChatKey(
          userMessage.encrypted_content,
          chatKey,
        );
        if (decrypted) {
          userMessage.content = decrypted;
          console.info(
            `[ChatSyncService:AI] Successfully decrypted content for message ${userMessage.message_id}`,
          );
        } else {
          console.error(
            `[ChatSyncService:AI] Failed to decrypt content for message ${userMessage.message_id} - decryption returned null`,
          );
          return;
        }
      } catch (decryptError) {
        console.error(
          `[ChatSyncService:AI] Failed to decrypt content for message ${userMessage.message_id}:`,
          decryptError,
        );
        return;
      }
    }

    console.debug(
      `[ChatSyncService:AI] User message retrieved for encryption:`,
      {
        messageId: userMessage.message_id,
        hasContent: !!userMessage.content,
        hasEncryptedContent: !!userMessage.encrypted_content,
        contentLength: userMessage.content?.length || 0,
      },
    );

    // Get the updated chat object
    const updatedChat = await chatDB.getChat(payload.chat_id);
    if (!updatedChat) {
      console.error(
        `[ChatSyncService:AI] Updated chat ${payload.chat_id} not found for sending to server`,
      );
      return;
    }

    // Prepare metadata ONLY for new chats
    let validIconName: string | undefined = undefined;
    let categoryForServer: string | undefined = undefined;
    let titleForServer: string | undefined = undefined;

    if (isNewChat) {
      // NEW CHAT ONLY - validate and prepare icon, category, and title for server
      console.info(
        `[ChatSyncService:AI] Server sync - Validating ${payload.icon_names!.length} icon names for NEW CHAT: ${payload.icon_names!.join(", ")}`,
      );

      for (const iconName of payload.icon_names!) {
        if (isValidLucideIcon(iconName)) {
          validIconName = iconName;
          console.info(
            `[ChatSyncService:AI] Server sync - ✅ Found valid icon: ${iconName}`,
          );
          break;
        } else {
          console.warn(
            `[ChatSyncService:AI] Server sync - ❌ Invalid icon name: ${iconName}, trying next...`,
          );
        }
      }
      // If no valid icon found, use category fallback
      if (!validIconName) {
        validIconName = getFallbackIconForCategory(
          payload.category || "general_knowledge",
        );
        console.info(
          `[ChatSyncService:AI] Server sync - 🔄 No valid icons found, using category fallback: ${validIconName}`,
        );
      }

      // Only include category and title for new chats
      categoryForServer = payload.category;
      titleForServer = payload.title;
      console.info(
        `[ChatSyncService:AI] Server sync - Preparing metadata for NEW CHAT: title=${!!titleForServer}, category=${categoryForServer}, icon=${validIconName}`,
      );
    } else {
      console.debug(
        `[ChatSyncService:AI] Server sync - FOLLOW-UP message. NOT sending icon/category/title to server.`,
      );
    }

    // Send encrypted storage package with metadata (for new chats) or just user message (for follow-ups)
    await sendEncryptedStoragePackage(serviceInstance, {
      chat_id: payload.chat_id,
      plaintext_title: titleForServer, // Only set for new chats
      plaintext_category: categoryForServer, // Only set for new chats
      plaintext_icon: validIconName, // Only set for new chats
      user_message: userMessage,
      task_id: payload.task_id,
      updated_chat: updatedChat, // Pass the updated chat object with incremented title_v
    });

    if (isNewChat) {
      console.info(
        `[ChatSyncService:AI] DUAL-PHASE: Sent encrypted storage package with metadata for NEW CHAT ${payload.chat_id}`,
      );
    } else {
      console.info(
        `[ChatSyncService:AI] DUAL-PHASE: Sent encrypted storage package for FOLLOW-UP message in chat ${payload.chat_id}`,
      );
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] DUAL-PHASE: Error processing for chat ${payload.chat_id}:`,
      error,
    );
  }

  serviceInstance.dispatchEvent(
    new CustomEvent("aiTypingStarted", { detail: payload }),
  );
}

export function handleAITypingEndedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string; message_id: string },
): void {
  console.debug("[ChatSyncService:AI] Received 'ai_typing_ended':", payload);
  aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
  serviceInstance.dispatchEvent(
    new CustomEvent("aiTypingEnded", { detail: payload }),
  );
}

export async function handleAIMessageReadyImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AIMessageReadyPayload,
): Promise<void> {
  console.debug("[ChatSyncService:AI] Received 'ai_message_ready':", payload);
  serviceInstance.dispatchEvent(
    new CustomEvent("aiMessageCompletedOnServer", { detail: payload }),
  );
  const taskInfo = serviceInstance.activeAITasks.get(payload.chat_id);
  if (taskInfo && taskInfo.taskId === payload.message_id) {
    serviceInstance.activeAITasks.delete(payload.chat_id);
    serviceInstance.dispatchEvent(
      new CustomEvent("aiTaskEnded", {
        detail: {
          chatId: payload.chat_id,
          taskId: payload.message_id,
          status: "completed",
        },
      }),
    );
    console.info(
      `[ChatSyncService:AI] AI Task ${payload.message_id} for chat ${payload.chat_id} considered ended due to 'ai_message_ready'.`,
    );

    // Check if this message is for a background chat (not currently active)
    // If so, show a notification and increment unread count
    const activeChatId = activeChatStore.get();
    if (activeChatId !== payload.chat_id) {
      console.debug(
        `[ChatSyncService:AI] AI message completed for background chat ${payload.chat_id} (active: ${activeChatId})`,
      );

      // Increment unread count for this chat
      unreadMessagesStore.incrementUnread(payload.chat_id);

      // Try to get chat title and message preview for the notification
      try {
        const chat = await chatDB.getChat(payload.chat_id);
        if (chat) {
          // Get decrypted title if available
          let chatTitle = "New message";
          if (chat.title) {
            chatTitle = chat.title;
          } else if (chat.encrypted_title) {
            // The title will be decrypted by the chatMetadataCache in Chat.svelte
            // For notification, we use a generic title for now
            chatTitle = "Chat"; // TODO: Decrypt title if needed
          }

          // Show notification for background chat message
          // Message preview would come from the AI response - for now use generic text
          // The actual message content isn't available here yet (it's in the payload)
          notificationStore.chatMessage(
            payload.chat_id,
            chatTitle,
            "New AI response ready", // TODO: Extract preview from message content when available
            undefined, // avatarUrl - could be set based on mate category
          );
        }
      } catch (error) {
        console.warn(
          "[ChatSyncService:AI] Error fetching chat for notification:",
          error,
        );
        // Still show a notification even if we can't get chat details
        notificationStore.chatMessage(
          payload.chat_id,
          "New message",
          "New AI response ready",
          undefined,
        );
      }
    }
  }
}

export async function handleAITaskCancelRequestedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AITaskCancelRequestedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AI] Received 'ai_task_cancel_requested' acknowledgement:",
    payload,
  );
  serviceInstance.dispatchEvent(
    new CustomEvent("aiTaskCancellationAcknowledged", { detail: payload }),
  );

  // Clear activeAITasks for all statuses when cancellation is acknowledged
  // This ensures the frontend state matches the backend state
  const chatIdsToClear: string[] = [];
  serviceInstance.activeAITasks.forEach(
    (value: { taskId: string }, key: string) => {
      if (value.taskId === payload.task_id) {
        chatIdsToClear.push(key);
      }
    },
  );
  // Cancel all processing embeds for affected chats and dispatch UI updates
  // This is done BEFORE dispatching aiTaskEnded so the embed UI updates immediately
  for (const chatId of chatIdsToClear) {
    try {
      const { embedStore } = await import("./embedStore");
      const cancelledEmbedIds = embedStore.cancelProcessingEmbeds(chatId);

      // Dispatch embedUpdated events for each cancelled embed so UnifiedEmbedPreview updates
      for (const embedId of cancelledEmbedIds) {
        serviceInstance.dispatchEvent(
          new CustomEvent("embedUpdated", {
            detail: {
              embed_id: embedId,
              chat_id: chatId,
              status: "cancelled",
            },
          }),
        );
      }

      if (cancelledEmbedIds.length > 0) {
        console.info(
          `[ChatSyncService:AI] Cancelled ${cancelledEmbedIds.length} processing embed(s) for chat ${chatId} due to task cancellation`,
        );
      }
    } catch (err) {
      console.warn(
        `[ChatSyncService:AI] Failed to cancel processing embeds for chat ${chatId}:`,
        err,
      );
    }
  }

  chatIdsToClear.forEach((chatId) => {
    serviceInstance.activeAITasks.delete(chatId);
    // Clear typing status for this cancelled task
    // Use clearTypingForChat since we only have task_id, not message_id
    // (message_id is what setTyping stores as aiMessageId)
    aiTypingStore.clearTypingForChat(chatId);
    serviceInstance.dispatchEvent(
      new CustomEvent("aiTaskEnded", {
        detail: {
          chatId: chatId,
          taskId: payload.task_id,
          status:
            payload.status === "revocation_sent" ? "cancelled" : payload.status,
        },
      }),
    );
    console.info(
      `[ChatSyncService:AI] AI Task ${payload.task_id} for chat ${chatId} cleared due to cancel ack status: ${payload.status}.`,
    );
  });
}

/**
 * Handle message queued notification from server.
 * This occurs when a user sends a message while an AI task is still processing.
 * The message is queued and will be processed after the current task completes.
 *
 * The message should be displayed in MessageInput.svelte, not as a notification.
 */
export function handleMessageQueuedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: {
    chat_id: string;
    user_message_id: string;
    active_task_id: string;
    message: string;
  },
): void {
  console.info(
    `[ChatSyncService:AI] Message ${payload.user_message_id} queued for chat ${payload.chat_id}. Active task: ${payload.active_task_id}`,
  );

  // Dispatch event for MessageInput component to handle the UI display
  // Don't show notification - MessageInput will display the message instead
  serviceInstance.dispatchEvent(
    new CustomEvent("messageQueued", { detail: payload }),
  );
}

/**
 * Handle AI response storage confirmation from server
 * This confirms that the encrypted AI response has been stored in Directus
 */
export function handleAIResponseStorageConfirmedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string; message_id: string; task_id?: string },
): void {
  console.info(
    "[ChatSyncService:AI] Received 'ai_response_storage_confirmed':",
    payload,
  );

  // Unmark message as syncing
  serviceInstance.unmarkMessageSyncing(payload.message_id);

  // Dispatch event to notify components that AI response storage is confirmed
  serviceInstance.dispatchEvent(
    new CustomEvent("aiResponseStorageConfirmed", {
      detail: {
        chatId: payload.chat_id,
        messageId: payload.message_id,
        taskId: payload.task_id,
      },
    }),
  );

  console.debug(
    `[ChatSyncService:AI] AI response storage confirmed for message ${payload.message_id} in chat ${payload.chat_id}`,
  );
}

/**
 * Handles the 'encrypted_metadata_stored' event from the server.
 * This confirms that encrypted chat metadata has been successfully stored on the server.
 */
export function handleEncryptedMetadataStoredImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string; message_id: string; task_id?: string },
): void {
  console.debug(
    `[ChatSyncService:AI] Received 'encrypted_metadata_stored':`,
    payload,
  );

  // Unmark message as syncing if message_id is provided
  if (payload.message_id) {
    serviceInstance.unmarkMessageSyncing(payload.message_id);
  }

  console.debug(
    `[ChatSyncService:AI] Encrypted metadata storage confirmed for chat ${payload.chat_id}`,
  );
}

/**
 * Handle post-processing metadata stored confirmation from server.
 * This confirms that encrypted follow-up suggestions, summary, and tags were stored in Directus.
 */
export function handlePostProcessingMetadataStoredImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string; task_id?: string },
): void {
  console.info(
    `[ChatSyncService:AI] Received 'post_processing_metadata_stored' confirmation for chat ${payload.chat_id}`,
  );
  // Nothing to do here - the data is already encrypted and stored locally
  // This is just an acknowledgment that the server successfully stored it in Directus
}

/**
 * Handle post-processing completed event from the server.
 * This includes follow-up suggestions, new chat suggestions, summary, tags,
 * and suggested settings/memories entries.
 */
export async function handlePostProcessingCompletedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: {
    chat_id: string;
    task_id: string;
    follow_up_request_suggestions: string[];
    new_chat_request_suggestions: string[];
    chat_summary: string;
    chat_tags: string[];
    harmful_response: number;
    top_recommended_apps_for_user?: string[]; // Optional: Top 5 recommended app IDs
    suggested_settings_memories?: SuggestedSettingsMemoryEntry[]; // Optional: Settings/memories suggestions from Phase 2
  },
): Promise<void> {
  console.info(
    `[ChatSyncService:AI] Received 'post_processing_completed' for chat ${payload.chat_id}`,
  );

  try {
    // Capture encrypted values for syncing back to Directus
    let encryptedFollowUpSuggestions: string | null = null;
    let encryptedNewChatSuggestions: string[] = [];
    let encryptedChatSummary: string | null = null;
    let encryptedChatTags: string | null = null;
    let encryptedTopRecommendedApps: string | null = null;
    let encryptedSettingsMemoriesSuggestions: string | null = null;

    const chat = await chatDB.getChat(payload.chat_id);
    if (!chat) {
      throw new Error(`Chat ${payload.chat_id} not found`);
    }

    const chatKey = chatDB.getOrGenerateChatKey(payload.chat_id);
    const {
      encryptWithChatKey,
      encryptArrayWithChatKey,
      encryptWithMasterKey,
    } = await import("./cryptoService");

    // Encrypt and save follow-up suggestions to chat record (last 18)
    // CRITICAL FIX: await encryption operation since encryptArrayWithChatKey is async
    if (
      payload.follow_up_request_suggestions &&
      payload.follow_up_request_suggestions.length > 0
    ) {
      encryptedFollowUpSuggestions = await encryptArrayWithChatKey(
        payload.follow_up_request_suggestions.slice(0, 18), // Keep last 18
        chatKey,
      );

      chat.encrypted_follow_up_request_suggestions =
        encryptedFollowUpSuggestions;
      console.debug(
        `[ChatSyncService:AI] Saved ${payload.follow_up_request_suggestions.length} follow-up suggestions for chat ${payload.chat_id}`,
      );
    }

    // Save new chat suggestions to separate store (keep last 50)
    // Encrypt each suggestion with master key for global pool
    if (
      payload.new_chat_request_suggestions &&
      payload.new_chat_request_suggestions.length > 0
    ) {
      await chatDB.saveNewChatSuggestions(
        payload.new_chat_request_suggestions,
        payload.chat_id,
      );

      // Encrypt new chat suggestions for server sync (max 6)
      // CRITICAL FIX: await all encryption operations since encryptWithMasterKey is async
      encryptedNewChatSuggestions = await Promise.all(
        payload.new_chat_request_suggestions
          .slice(0, 6)
          .map(async (suggestion) => {
            const encrypted = await encryptWithMasterKey(suggestion);
            if (!encrypted)
              throw new Error("Failed to encrypt new chat suggestion");
            return encrypted;
          }),
      );

      console.debug(
        `[ChatSyncService:AI] Saved ${payload.new_chat_request_suggestions.length} new chat suggestions`,
      );
    }

    // Encrypt chat summary and tags
    // CRITICAL FIX: await all encryption operations since encrypt functions are async
    if (payload.chat_summary) {
      encryptedChatSummary = await encryptWithChatKey(
        payload.chat_summary,
        chatKey,
      );
      chat.encrypted_chat_summary = encryptedChatSummary;
    }

    if (payload.chat_tags && payload.chat_tags.length > 0) {
      encryptedChatTags = await encryptArrayWithChatKey(
        payload.chat_tags.slice(0, 10), // Max 10 tags
        chatKey,
      );
      chat.encrypted_chat_tags = encryptedChatTags;
    }

    // Encrypt and save top recommended apps for this chat
    if (
      payload.top_recommended_apps_for_user &&
      payload.top_recommended_apps_for_user.length > 0
    ) {
      encryptedTopRecommendedApps = await encryptArrayWithChatKey(
        payload.top_recommended_apps_for_user.slice(0, 5), // Max 5 apps
        chatKey,
      );
      chat.encrypted_top_recommended_apps_for_chat =
        encryptedTopRecommendedApps;
      console.debug(
        `[ChatSyncService:AI] Saved top recommended apps for chat ${payload.chat_id}`,
      );
    }

    // Encrypt and save settings/memories suggestions (overwrites previous suggestions)
    // These are shown to user as suggestion cards with "Add" and "Reject" options
    if (
      payload.suggested_settings_memories &&
      payload.suggested_settings_memories.length > 0
    ) {
      // Encrypt the suggestions array as JSON string with chat key
      const suggestionsJson = JSON.stringify(
        payload.suggested_settings_memories.slice(0, 3), // Max 3 suggestions
      );
      encryptedSettingsMemoriesSuggestions = await encryptWithChatKey(
        suggestionsJson,
        chatKey,
      );
      chat.encrypted_settings_memories_suggestions =
        encryptedSettingsMemoriesSuggestions;
      console.debug(
        `[ChatSyncService:AI] Saved ${payload.suggested_settings_memories.length} settings/memories suggestions for chat ${payload.chat_id}`,
      );
    }

    // Update chat with all encrypted metadata at once
    if (
      payload.follow_up_request_suggestions?.length > 0 ||
      payload.chat_summary ||
      payload.chat_tags?.length > 0 ||
      encryptedTopRecommendedApps ||
      encryptedSettingsMemoriesSuggestions
    ) {
      await chatDB.updateChat(chat);
      // CRITICAL: Invalidate metadata cache so context menu shows updated summary
      chatMetadataCache.invalidateChat(payload.chat_id);
      console.debug(
        `[ChatSyncService:AI] Updated chat ${payload.chat_id} with encrypted post-processing metadata`,
      );

      // CRITICAL: Dispatch chatUpdated so Chats.svelte updates its in-memory chat list.
      // Without this, the chat object held by the sidebar still has encrypted_chat_summary=null
      // and the context menu won't show the summary until a full page reload.
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: payload.chat_id,
            type: "post_processing_metadata",
            chat,
          },
        }),
      );
    }

    // Sync encrypted data back to Directus via WebSocket
    if (
      encryptedFollowUpSuggestions ||
      encryptedNewChatSuggestions.length > 0 ||
      encryptedChatSummary ||
      encryptedChatTags ||
      encryptedTopRecommendedApps ||
      encryptedSettingsMemoriesSuggestions
    ) {
      const { sendPostProcessingMetadataImpl } =
        await import("./chatSyncServiceSenders");
      await sendPostProcessingMetadataImpl(
        serviceInstance,
        payload.chat_id,
        encryptedFollowUpSuggestions || "",
        encryptedNewChatSuggestions,
        encryptedChatSummary || "",
        encryptedChatTags || "",
        encryptedTopRecommendedApps || "",
        encryptedSettingsMemoriesSuggestions || "",
      );
      console.debug(
        `[ChatSyncService:AI] Sent encrypted post-processing metadata to server for Directus sync`,
      );
    }

    // Aggregate recommendations from recent chats and update user profile
    if (
      payload.top_recommended_apps_for_user &&
      payload.top_recommended_apps_for_user.length > 0
    ) {
      await aggregateAndUpdateTopRecommendedApps(
        payload.top_recommended_apps_for_user,
      );
    }

    // Dispatch event to notify components (e.g., to update UI with new suggestions)
    const event = new CustomEvent("postProcessingCompleted", {
      detail: {
        chatId: payload.chat_id,
        taskId: payload.task_id,
        followUpSuggestions: payload.follow_up_request_suggestions,
        harmfulResponse: payload.harmful_response,
        // Include settings/memories suggestions for UI to display suggestion cards
        suggestedSettingsMemories: payload.suggested_settings_memories || [],
      },
    });
    console.info(
      `[ChatSyncService:AI] 🚀 Dispatching 'postProcessingCompleted' event for chat ${payload.chat_id} with ${payload.follow_up_request_suggestions?.length || 0} follow-up suggestions and ${payload.suggested_settings_memories?.length || 0} settings/memories suggestions`,
    );
    serviceInstance.dispatchEvent(event);
    console.debug(`[ChatSyncService:AI] ✅ Event dispatched successfully`);
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error handling post-processing results for chat ${payload.chat_id}:`,
      error,
    );
  }
}

/**
 * Aggregates top recommended apps from the last 20 chats and updates user profile.
 * This runs client-side to maintain zero-knowledge architecture.
 */
async function aggregateAndUpdateTopRecommendedApps(
  currentChatApps: string[],
): Promise<void> {
  try {
    const { chatDB } = await import("./db");
    const { decryptArrayWithChatKey } = await import("./cryptoService");

    // Get last 20 chats sorted by last_edited_overall_timestamp
    const allChats = await chatDB.getAllChats();
    const sortedChats = allChats
      .filter((chat) => chat.last_edited_overall_timestamp)
      .sort(
        (a, b) =>
          (b.last_edited_overall_timestamp || 0) -
          (a.last_edited_overall_timestamp || 0),
      )
      .slice(0, 20); // Last 20 chats

    // Collect all recommended apps from these chats
    const appCounts = new Map<string, number>();

    for (const chat of sortedChats) {
      if (chat.encrypted_top_recommended_apps_for_chat) {
        try {
          const chatKey = chatDB.getOrGenerateChatKey(chat.chat_id);
          const decryptedApps = await decryptArrayWithChatKey(
            chat.encrypted_top_recommended_apps_for_chat,
            chatKey,
          );

          // Count each app
          if (decryptedApps && Array.isArray(decryptedApps)) {
            for (const appId of decryptedApps) {
              if (typeof appId === "string" && appId.length > 0) {
                appCounts.set(appId, (appCounts.get(appId) || 0) + 1);
              }
            }
          }
        } catch (error) {
          console.warn(
            `[AggregateApps] Failed to decrypt apps for chat ${chat.chat_id}:`,
            error,
          );
          // Continue with other chats
        }
      }
    }

    // Also include current chat's apps
    for (const appId of currentChatApps) {
      if (typeof appId === "string" && appId.length > 0) {
        appCounts.set(appId, (appCounts.get(appId) || 0) + 1);
      }
    }

    // Get top 5 most mentioned apps
    const topApps = Array.from(appCounts.entries())
      .sort((a, b) => b[1] - a[1]) // Sort by count descending
      .slice(0, 5)
      .map(([appId]) => appId); // Extract app IDs

    // Update user profile in IndexedDB (decrypted)
    const { updateProfile } = await import("../stores/userProfile");
    updateProfile({
      top_recommended_apps: topApps,
    });

    // Encrypt and sync to server for Directus storage
    await syncTopRecommendedAppsToServer(topApps);

    console.debug(`[AggregateApps] Updated top recommended apps:`, topApps);
  } catch (error) {
    console.error(
      "[AggregateApps] Error aggregating top recommended apps:",
      error,
    );
  }
}

/**
 * Encrypts and syncs top recommended apps to server for Directus storage.
 */
async function syncTopRecommendedAppsToServer(appIds: string[]): Promise<void> {
  try {
    const { encryptWithMasterKey } = await import("./cryptoService");

    if (appIds.length === 0) {
      return; // Don't sync empty arrays
    }

    // Encrypt array using master key
    // Convert array to JSON string first, then encrypt with master key
    // This follows the same pattern as encryptArrayWithChatKey but uses master key instead
    const jsonString = JSON.stringify(appIds);
    const encrypted = await encryptWithMasterKey(jsonString);
    if (!encrypted) {
      throw new Error("Failed to encrypt top recommended apps");
    }

    // Update user profile with encrypted value
    const { updateProfile } = await import("../stores/userProfile");
    updateProfile({
      encrypted_top_recommended_apps: encrypted,
    });

    // TODO: Sync to server via WebSocket when user profile sync is implemented
    // For now, this is stored locally and will be synced during next user profile sync
    console.debug(
      `[SyncApps] Encrypted and stored top recommended apps locally (will sync to server on next profile sync)`,
    );
  } catch (error) {
    console.error("[SyncApps] Error syncing top recommended apps:", error);
  }
}

/**
 * Handle server request for chat history when cache is stale or missing
 * Server sends this when it cannot decrypt cached messages
 */
export async function handleRequestChatHistoryImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { chat_id: string; reason: string; message?: string },
): Promise<void> {
  console.warn(
    `[ChatSyncService:AI] Server requested chat history for chat ${payload.chat_id}. Reason: ${payload.reason}`,
  );

  try {
    // Get all messages for this chat from IndexedDB
    const allMessages = await chatDB.getMessagesForChat(payload.chat_id);

    if (allMessages.length === 0) {
      console.error(
        `[ChatSyncService:AI] No messages found for chat ${payload.chat_id} to send to server`,
      );
      return;
    }

    // Convert to format expected by server (plaintext for AI processing)
    const messageHistory = allMessages.map((msg) => ({
      message_id: msg.message_id,
      role: msg.role,
      content: msg.content, // Plaintext content
      sender_name: msg.sender_name,
      category: msg.category,
      created_at: msg.created_at,
    }));

    console.info(
      `[ChatSyncService:AI] Sending ${messageHistory.length} messages to server for cache refresh`,
    );

    // Get the most recent user message (the one that triggered the request)
    const latestUserMessage = allMessages
      .filter((m) => m.role === "user")
      .sort((a, b) => b.created_at - a.created_at)[0];

    if (!latestUserMessage) {
      console.error(
        `[ChatSyncService:AI] No user message found to resend with history`,
      );
      return;
    }

    // Get chat metadata
    const chat = await chatDB.getChat(payload.chat_id);
    const chatHasMessages = (chat?.messages_v ?? 0) > 1;

    // Resend the message with full history
    const resendPayload = {
      chat_id: payload.chat_id,
      message: {
        message_id: latestUserMessage.message_id,
        role: latestUserMessage.role,
        content: latestUserMessage.content,
        created_at: latestUserMessage.created_at,
        sender_name: latestUserMessage.sender_name,
        chat_has_title: chatHasMessages,
        message_history: messageHistory, // Include full history
      },
    };

    console.info(
      `[ChatSyncService:AI] Resending message with ${messageHistory.length} historical messages`,
    );

    // Import webSocketService
    const { webSocketService } = await import("./websocketService");
    await webSocketService.sendMessage("chat_message_added", resendPayload);
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error handling chat history request for chat ${payload.chat_id}:`,
      error,
    );
  }
}

/**
 * Handle embed_update event from server
 * This updates an existing "processing" embed with finished results.
 *
 * CRITICAL: When transitioning from "processing" to "finished", we need to:
 * 1. Encrypt the plaintext content that was stored during processing
 * 2. Create and persist embed key wrappers (master + chat) to IndexedDB
 * 3. Store the encrypted embed properly
 *
 * Without this, the embed key stays only in memory cache and is lost on page refresh,
 * causing fullscreen views to fail loading child embeds.
 */
export async function handleEmbedUpdateImpl(
  serviceInstance: ChatSynchronizationService,
  payload: EmbedUpdatePayload,
): Promise<void> {
  console.info(
    `[ChatSyncService:AI] Received 'embed_update' for embed ${payload.embed_id}`,
  );

  // CRITICAL FIX: If this embed was already fully processed by handleSendEmbedDataImpl
  // (which handles encryption, key storage, and Directus persistence), skip the embed_update
  // entirely. The embed_update is redundant in this case and can cause race conditions
  // (e.g., trying to access embed keys before IndexedDB storage completes).
  if (isEmbedAlreadyProcessed(payload.embed_id)) {
    console.debug(
      `[ChatSyncService:AI] embed_update: Skipping ${payload.embed_id} - already fully processed by send_embed_data handler`,
    );
    // Still dispatch a lightweight UI refresh event (status may have changed)
    serviceInstance.dispatchEvent(
      new CustomEvent("embedUpdated", {
        detail: {
          embed_id: payload.embed_id,
          chat_id: payload.chat_id,
          message_id: payload.message_id,
          status: payload.status,
          child_embed_ids: payload.child_embed_ids,
        },
      }),
    );
    return;
  }

  try {
    // Load the existing embed from cache (may be in-memory only from processing stage)
    const { embedStore } = await import("./embedStore");
    const embedRef = `embed:${payload.embed_id}`;

    // Get the existing embed (from memory cache or IndexedDB)
    const existingEmbed = await embedStore.get(embedRef);
    if (existingEmbed) {
      // Check if this embed needs encryption + key storage
      // Processing embeds have plaintext content and only in-memory keys
      const wasProcessing = !existingEmbed.encrypted_content;
      const isNowFinished =
        payload.status === "finished" || payload.status === "completed";

      // Update status to finished
      existingEmbed.status = payload.status;

      // Store child embed IDs if provided (for composite embeds)
      if (payload.child_embed_ids && payload.child_embed_ids.length > 0) {
        existingEmbed.embed_ids = payload.child_embed_ids;
        console.debug(
          `[ChatSyncService:AI] embed_update added ${payload.child_embed_ids.length} child embed_ids`,
        );
      }

      // Update timestamp
      existingEmbed.updatedAt = Date.now();

      // CRITICAL FIX: If transitioning from processing to finished, we need to:
      // 1. Encrypt the content and persist key wrappers
      // 2. This ensures the key survives page refresh
      //
      // IMPORTANT: SKIP this if the content is still the "processing" placeholder!
      // The `send_embed_data` event with the actual finished content should handle encryption/storage.
      // This prevents a race condition where `embed_update` arrives before `send_embed_data` finishes,
      // causing the OLD placeholder content to be encrypted and stored to Directus.
      //
      // Detection: If existingEmbed.content contains 'status: processing' or 'status: "processing"',
      // it's still the placeholder and we should NOT encrypt it here.
      const contentString =
        typeof existingEmbed.content === "string" ? existingEmbed.content : "";
      const isStillPlaceholderContent =
        contentString.includes("status: processing") ||
        contentString.includes('status: "processing"') ||
        contentString.includes("status: 'processing'");

      if (isStillPlaceholderContent) {
        // CRITICAL FIX: Don't store to IndexedDB when content is still placeholder!
        // Only update the in-memory status - the send_embed_data (finished) event will store the actual content.
        // Previously, this was calling embedStore.put() with placeholder content, overwriting memory-only data.
        console.warn(
          `[ChatSyncService:AI] embed_update: SKIPPING storage for ${payload.embed_id} - ` +
            `content still contains "processing" status. The send_embed_data event with actual content should handle storage.`,
        );

        // existingEmbed.status was already updated above (line 1268)
        // Since memory-only embeds are references, this update persists in the cache

        // Dispatch event for UI refresh (status changed, but content still loading)
        serviceInstance.dispatchEvent(
          new CustomEvent("embedUpdated", {
            detail: {
              embed_id: payload.embed_id,
              chat_id: payload.chat_id,
              message_id: payload.message_id,
              status: payload.status,
              child_embed_ids: payload.child_embed_ids,
              isWaitingForContent: true, // Flag to indicate content is still coming
            },
          }),
        );
        return; // CRITICAL: Early return - don't call embedStore.put() with placeholder content
      } else if (wasProcessing && isNowFinished && existingEmbed.content) {
        console.info(
          `[ChatSyncService:AI] embed_update: Transitioning ${payload.embed_id} from processing to finished - encrypting and persisting keys`,
        );

        try {
          // Import crypto utilities
          const { computeSHA256 } = await import("../message_parsing/utils");
          const {
            generateEmbedKey,
            encryptWithEmbedKey,
            wrapEmbedKeyWithMasterKey,
            wrapEmbedKeyWithChatKey,
          } = await import("./cryptoService");
          const { chatDB } = await import("./db");

          // Get chat_id from payload or existing embed
          const chatId = payload.chat_id || existingEmbed.chat_id;
          // Get user_id from payload (user_id_uuid) or existing embed
          const userId = payload.user_id_uuid || existingEmbed.user_id;

          if (!chatId) {
            console.warn(
              `[ChatSyncService:AI] embed_update: No chat_id available for ${payload.embed_id}, skipping key persistence`,
            );
          } else {
            // Compute hashed IDs
            const hashedChatId = await computeSHA256(chatId);
            const hashedEmbedId = await computeSHA256(payload.embed_id);
            const hashedUserId = userId
              ? await computeSHA256(userId)
              : "unknown";

            // Get or generate embed key (may already exist in memory cache from processing stage)
            let embedKey = await embedStore.getEmbedKey(
              payload.embed_id,
              hashedChatId,
            );
            if (!embedKey) {
              // Key not in cache, generate a new one
              embedKey = generateEmbedKey();
              console.debug(
                `[ChatSyncService:AI] embed_update: Generated new embed key for ${payload.embed_id}`,
              );
            } else {
              console.debug(
                `[ChatSyncService:AI] embed_update: Using cached embed key for ${payload.embed_id}`,
              );
            }

            // CRITICAL: Cache the embed key immediately after generation/retrieval
            // This prevents race conditions where concurrent operations try to access the key
            embedStore.setEmbedKeyInCache(
              payload.embed_id,
              embedKey,
              hashedChatId,
            );
            embedStore.setEmbedKeyInCache(
              payload.embed_id,
              embedKey,
              undefined,
            ); // master fallback
            console.debug(
              `[ChatSyncService:AI] embed_update: ✅ Cached embed key immediately for ${payload.embed_id}`,
            );

            // If this embed has child embed_ids, pre-cache the key for children immediately
            if (
              existingEmbed.embed_ids &&
              Array.isArray(existingEmbed.embed_ids) &&
              existingEmbed.embed_ids.length > 0
            ) {
              console.debug(
                `[ChatSyncService:AI] embed_update: Pre-caching parent key for ${existingEmbed.embed_ids.length} known child embeds`,
              );
              for (const childEmbedId of existingEmbed.embed_ids) {
                embedStore.setEmbedKeyInCache(
                  childEmbedId,
                  embedKey,
                  hashedChatId,
                );
                embedStore.setEmbedKeyInCache(
                  childEmbedId,
                  embedKey,
                  undefined,
                ); // 'master' fallback
              }
            }

            // Encrypt the content
            const plaintextContent = existingEmbed.content;
            const encryptedContent = await encryptWithEmbedKey(
              plaintextContent,
              embedKey,
            );
            if (!encryptedContent) {
              throw new Error("Failed to encrypt embed content");
            }

            // Encrypt the type if available
            let encryptedType: string | undefined;
            if (existingEmbed.type) {
              encryptedType =
                (await encryptWithEmbedKey(existingEmbed.type, embedKey)) ||
                undefined;
            }

            // Create key wrappers (only for parent embeds)
            const isChildEmbed = !!existingEmbed.parent_embed_id;

            if (!isChildEmbed) {
              // Create master key wrapper
              const wrappedMasterKey =
                await wrapEmbedKeyWithMasterKey(embedKey);
              if (!wrappedMasterKey) {
                throw new Error("Failed to wrap embed key with master key");
              }

              // Create chat key wrapper
              const chatKey = chatDB.getOrGenerateChatKey(chatId);
              if (!chatKey) {
                throw new Error("Failed to get chat key for wrapping");
              }
              const wrappedChatKey = await wrapEmbedKeyWithChatKey(
                embedKey,
                chatKey,
              );
              if (!wrappedChatKey) {
                throw new Error("Failed to wrap embed key with chat key");
              }

              // Store key wrappers to IndexedDB
              const now = Math.floor(Date.now() / 1000);
              const embedKeysForStorage = [
                {
                  hashed_embed_id: hashedEmbedId,
                  key_type: "master" as const,
                  hashed_chat_id: null,
                  encrypted_embed_key: wrappedMasterKey,
                  hashed_user_id: hashedUserId,
                  created_at: now,
                },
                {
                  hashed_embed_id: hashedEmbedId,
                  key_type: "chat" as const,
                  hashed_chat_id: hashedChatId,
                  encrypted_embed_key: wrappedChatKey,
                  hashed_user_id: hashedUserId,
                  created_at: now,
                },
              ];

              await embedStore.storeEmbedKeys(embedKeysForStorage);
              console.info(
                `[ChatSyncService:AI] embed_update: ✅ Stored key wrappers for ${payload.embed_id} to IndexedDB`,
              );

              // Also send key wrappers to server
              try {
                const sendersModule = await import("./chatSyncServiceSenders");
                const sendStoreEmbedKeysFunction =
                  sendersModule.sendStoreEmbedKeysImpl ||
                  (
                    sendersModule as {
                      default?: {
                        sendStoreEmbedKeysImpl?: typeof sendersModule.sendStoreEmbedKeysImpl;
                      };
                    }
                  ).default?.sendStoreEmbedKeysImpl;

                if (typeof sendStoreEmbedKeysFunction === "function") {
                  await sendStoreEmbedKeysFunction(serviceInstance, {
                    keys: embedKeysForStorage,
                  });
                  console.debug(
                    `[ChatSyncService:AI] embed_update: Sent key wrappers to server for ${payload.embed_id}`,
                  );
                }
              } catch (sendError) {
                // Non-fatal - keys are stored locally
                console.warn(
                  `[ChatSyncService:AI] embed_update: Failed to send key wrappers to server:`,
                  sendError,
                );
              }
            }

            // Update the embed with encrypted content
            existingEmbed.encrypted_content = encryptedContent;
            existingEmbed.encrypted_type = encryptedType;
            existingEmbed.hashed_chat_id = hashedChatId;
            // Clear plaintext content (it's now encrypted)
            delete existingEmbed.content;

            // NOTE: Primary key caching is now done immediately after key generation (above)
            // This section kept as safety fallback - won't hurt to re-cache the same values

            // Build encrypted embed object for putEncrypted (new format with separate fields)
            // This is the same format used by handleSendEmbedDataImpl for finalized embeds
            const hashedMessageId = payload.message_id
              ? await computeSHA256(payload.message_id)
              : existingEmbed.hashed_message_id;

            const encryptedEmbedForStorage = {
              embed_id: payload.embed_id,
              encrypted_type: encryptedType,
              encrypted_content: encryptedContent,
              status: existingEmbed.status,
              hashed_chat_id: hashedChatId,
              hashed_message_id: hashedMessageId,
              hashed_task_id: existingEmbed.hashed_task_id,
              hashed_user_id: hashedUserId,
              embed_ids: existingEmbed.embed_ids,
              parent_embed_id: existingEmbed.parent_embed_id,
              version_number: existingEmbed.version_number,
              file_path: existingEmbed.file_path,
              content_hash: existingEmbed.content_hash,
              text_length_chars: existingEmbed.text_length_chars,
              is_private: existingEmbed.is_private ?? false,
              is_shared: existingEmbed.is_shared ?? false,
              createdAt: existingEmbed.createdAt,
              updatedAt: existingEmbed.updatedAt,
            };

            // Extract app_id/skill_id from plaintext content for metadata
            const preExtractedMetadata = {
              app_id: existingEmbed.app_id,
              skill_id: existingEmbed.skill_id,
            };

            // Use putEncrypted for proper separate field storage (instead of put)
            // This ensures embed_ids is stored as a separate field that can be queried
            await embedStore.putEncrypted(
              embedRef,
              encryptedEmbedForStorage,
              existingEmbed.type,
              plaintextContent,
              preExtractedMetadata,
            );

            console.info(
              `[ChatSyncService:AI] embed_update: ✅ Encrypted and stored ${payload.embed_id} with putEncrypted`,
            );

            // Send encrypted embed to server for Directus storage
            try {
              const sendersModule = await import("./chatSyncServiceSenders");
              const sendStoreFunction =
                sendersModule.sendStoreEmbedImpl ||
                (
                  sendersModule as {
                    default?: {
                      sendStoreEmbedImpl?: typeof sendersModule.sendStoreEmbedImpl;
                    };
                  }
                ).default?.sendStoreEmbedImpl;

              if (typeof sendStoreFunction === "function") {
                // CRITICAL: Convert camelCase timestamps to snake_case and milliseconds to seconds for Directus
                const nowSecs = Math.floor(Date.now() / 1000);
                const { createdAt, updatedAt, ...restFields } =
                  encryptedEmbedForStorage;
                const storePayload = {
                  ...restFields,
                  created_at: createdAt
                    ? Math.floor(createdAt / 1000)
                    : nowSecs,
                  updated_at: updatedAt
                    ? Math.floor(updatedAt / 1000)
                    : nowSecs,
                };
                await sendStoreFunction(serviceInstance, storePayload);
                console.debug(
                  `[ChatSyncService:AI] embed_update: Sent encrypted embed to server for ${payload.embed_id}`,
                );
              }
            } catch (sendError) {
              // Non-fatal - embed is stored locally
              console.warn(
                `[ChatSyncService:AI] embed_update: Failed to send encrypted embed to server:`,
                sendError,
              );
            }

            // Skip the regular put() call since we've already stored via putEncrypted
            // Dispatch event for UI to refresh the embed preview
            serviceInstance.dispatchEvent(
              new CustomEvent("embedUpdated", {
                detail: {
                  embed_id: payload.embed_id,
                  chat_id: payload.chat_id,
                  message_id: payload.message_id,
                  status: payload.status,
                  child_embed_ids: payload.child_embed_ids,
                },
              }),
            );
            return; // Early return - already handled storage and event dispatch
          }
        } catch (encryptError) {
          console.error(
            `[ChatSyncService:AI] embed_update: Failed to encrypt/persist keys for ${payload.embed_id}:`,
            encryptError,
          );
          // Continue anyway - embed will still be stored (unencrypted), just won't survive page refresh well
        }
      }

      // Save updated embed (for non-encryption cases or fallback)
      await embedStore.put(embedRef, existingEmbed, existingEmbed.type);

      console.info(
        `[ChatSyncService:AI] Updated embed ${payload.embed_id} to status ${payload.status}`,
      );

      // Dispatch event for UI to refresh the embed preview
      serviceInstance.dispatchEvent(
        new CustomEvent("embedUpdated", {
          detail: {
            embed_id: payload.embed_id,
            chat_id: payload.chat_id,
            message_id: payload.message_id,
            status: payload.status,
            child_embed_ids: payload.child_embed_ids,
          },
        }),
      );
    } else {
      // CRITICAL FIX: If embed doesn't exist yet, request it from server
      // This can happen if embed_update is sent before send_embed_data is processed
      // or if the embed was not properly stored
      console.warn(
        `[ChatSyncService:AI] Embed ${payload.embed_id} not found in cache for update. Requesting from server.`,
      );

      // Request embed from server via request_embed event
      const { sendRequestEmbed } = await import("./chatSyncServiceSenders");
      try {
        await sendRequestEmbed(serviceInstance, payload.embed_id);
        console.info(
          `[ChatSyncService:AI] Requested embed ${payload.embed_id} from server`,
        );
      } catch (error) {
        console.error(
          `[ChatSyncService:AI] Error requesting embed ${payload.embed_id} from server:`,
          error,
        );
      }
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error handling embed_update for embed ${payload.embed_id}:`,
      error,
    );
  }
}

// Type alias for the inner embed data structure (used when WebSocket passes payload directly)
type EmbedDataPayload = SendEmbedDataPayload["payload"];

/**
 * Handle send_embed_data event from server
 * This receives plaintext TOON content, encrypts it client-side, stores in IndexedDB,
 * and sends the encrypted version back to server for Directus storage.
 */
export async function handleSendEmbedDataImpl(
  serviceInstance: ChatSynchronizationService,
  payload: SendEmbedDataPayload,
): Promise<void> {
  // FIX: The WebSocket service extracts rawMessage.payload and passes it to handlers,
  // so 'payload' here is already the inner embed data object, NOT the full message structure.
  // Handle both cases for backwards compatibility:
  // 1. payload.embed_id exists: WebSocket passed inner payload directly (correct behavior)
  // 2. payload.payload.embed_id exists: Full message structure was passed (legacy/edge case)
  const payloadWithEmbedId = payload as unknown as EmbedDataPayload;
  const payloadWithNestedData = payload as SendEmbedDataPayload;
  const embedData: EmbedDataPayload | undefined = payloadWithEmbedId.embed_id
    ? payloadWithEmbedId
    : payloadWithNestedData.payload;

  if (!embedData?.embed_id) {
    console.warn(
      "[ChatSyncService:AI] Received send_embed_data payload without embed_id. Raw payload:",
      payload,
    );
    return;
  }
  // Enhanced logging for send_embed_data events (helps debug composite embed issues)
  const contentPreview =
    typeof embedData.content === "string"
      ? embedData.content.substring(0, 300)
      : "NOT_STRING";
  const hasResultsInContent =
    typeof embedData.content === "string" &&
    embedData.content.includes("results:");
  const hasEmbedIdsInContent =
    typeof embedData.content === "string" &&
    embedData.content.includes("embed_ids:");
  const embedIdsInPayload = embedData.embed_ids;
  console.info(
    `[ChatSyncService:AI] [EMBED_EVENT] 📦 Received 'send_embed_data' for embed ${embedData.embed_id}:\n` +
      `  status=${embedData.status}, type=${embedData.type}\n` +
      `  hasResultsInContent=${hasResultsInContent}, hasEmbedIdsInContent=${hasEmbedIdsInContent}\n` +
      `  embedIdsInPayload=${JSON.stringify(embedIdsInPayload)} (count=${embedIdsInPayload?.length || 0})\n` +
      `  contentPreview="${contentPreview}..."`,
  );

  // DEBUG: Check if embedData contains any Promises
  for (const [key, value] of Object.entries(embedData)) {
    if (value instanceof Promise) {
      console.error(
        `[ChatSyncService:AI] ERROR: embedData field "${key}" is a Promise!`,
        value,
      );
    }
  }

  try {
    // Determine if this is a "processing" placeholder or a finalized embed
    const isProcessingPlaceholder = embedData.status === "processing";

    if (isProcessingPlaceholder) {
      // ============================================================
      // "PROCESSING" STATUS: In-memory only, but generate key early for children
      // ============================================================
      console.info(
        `[ChatSyncService:AI] Embed ${embedData.embed_id} is "processing" - storing in memory cache for rendering`,
      );

      // CRITICAL FIX: Store the processing embed in memory cache so resolveEmbed() can find it
      // During streaming, the UI renders embed nodes which call resolveEmbed(). If the embed
      // is not in memory cache, resolveEmbed() returns null and "Processing..." is shown.
      // By storing here, the next render cycle will find the embed data.
      try {
        const { embedStore } = await import("./embedStore");
        const embedRef = `embed:${embedData.embed_id}`;

        // Store in memory cache (not persisted to IndexedDB for processing embeds)
        // CRITICAL: Include ALL fields needed for rendering, especially:
        // - skill_id: Determines which component to render (news vs web search)
        // - app_id: Parent app identifier
        // - query: Search query to display in the preview
        // NOTE: Use type assertion for dynamic payload fields that aren't in the base type
        const embedPayload = embedData as Record<string, unknown>;
        embedStore.setInMemoryOnly(embedRef, {
          embed_id: embedData.embed_id,
          type: embedData.type,
          status: embedData.status,
          content: embedData.content, // Plaintext TOON content
          text_preview: embedData.text_preview,
          task_id: embedData.task_id,
          embed_ids: embedData.embed_ids,
          parent_embed_id: embedData.parent_embed_id,
          chat_id: embedData.chat_id,
          message_id: embedData.message_id,
          // CRITICAL: App skill metadata for rendering the correct component
          // These fields come from the server but aren't in the base type definition
          skill_id: embedPayload.skill_id as string | undefined,
          app_id: embedPayload.app_id as string | undefined,
          query: embedPayload.query as string | undefined, // Search query for search skills
          provider: embedPayload.provider as string | undefined, // Provider name (e.g., "Brave Search")
          results: embedPayload.results as unknown[] | undefined, // Results array if available
          createdAt: embedData.createdAt || Date.now(),
          updatedAt: embedData.updatedAt || Date.now(),
        });
        const queryStr = embedPayload.query as string | undefined;
        console.info(
          `[ChatSyncService:AI] ✅ Stored processing embed ${embedData.embed_id} in memory cache`,
          {
            skill_id: embedPayload.skill_id,
            app_id: embedPayload.app_id,
            query: queryStr?.substring(0, 30),
          },
        );
      } catch (err) {
        console.warn(
          `[ChatSyncService:AI] Failed to store processing embed in memory cache:`,
          err,
        );
      }

      // Generate embed-specific encryption key early (if not already exists)
      // This is CRITICAL for key inheritance: child embeds arrive while parent is still processing
      // and they need the parent's key to encrypt themselves.
      try {
        const { generateEmbedKey } = await import("./cryptoService");
        const { computeSHA256 } = await import("../message_parsing/utils");
        const { embedStore } = await import("./embedStore");
        const hashedChatId = await computeSHA256(embedData.chat_id);

        // Only generate if not already in cache
        const existingKey = await embedStore.getEmbedKey(
          embedData.embed_id,
          hashedChatId,
        );
        if (!existingKey) {
          const newKey = generateEmbedKey();
          // Cache the key so children can find it
          embedStore.setEmbedKeyInCache(
            embedData.embed_id,
            newKey,
            hashedChatId,
          );
          embedStore.setEmbedKeyInCache(embedData.embed_id, newKey, undefined); // master fallback
          console.debug(
            `[ChatSyncService:AI] Generated and cached early key for processing parent embed ${embedData.embed_id}`,
          );
        }
      } catch (err) {
        console.warn(
          `[ChatSyncService:AI] Failed to generate early key for processing embed:`,
          err,
        );
      }

      // Dispatch event with FULL embed data so UI can render from it directly
      serviceInstance.dispatchEvent(
        new CustomEvent("embedUpdated", {
          detail: {
            embed_id: embedData.embed_id,
            chat_id: embedData.chat_id,
            message_id: embedData.message_id,
            status: embedData.status,
            type: embedData.type,
            content: embedData.content, // Plaintext TOON for in-memory rendering
            text_preview: embedData.text_preview,
            task_id: embedData.task_id,
            embed_ids: embedData.embed_ids,
            parent_embed_id: embedData.parent_embed_id,
            // Include all fields UI might need for rendering
            isProcessing: true,
          },
        }),
      );
    } else {
      // ============================================================
      // FINALIZED STATUS (completed/error/cancelled/etc): Full encryption and persistence
      // ============================================================
      // CRITICAL: Check if this embed has already been processed to prevent duplicate keys
      // The same send_embed_data event may be received multiple times (e.g., duplicate WebSocket messages)
      if (isEmbedAlreadyProcessed(embedData.embed_id)) {
        console.warn(
          `[ChatSyncService:AI] [EMBED_EVENT] ⚠️ DUPLICATE DETECTED: Embed ${embedData.embed_id} already processed ` +
            `(status=${embedData.status}) - skipping duplicate processing. ` +
            `This should not happen if deduplication is working correctly!`,
        );
        // Still dispatch event for UI refresh, but don't re-encrypt or re-send
        serviceInstance.dispatchEvent(
          new CustomEvent("embedUpdated", {
            detail: {
              embed_id: embedData.embed_id,
              chat_id: embedData.chat_id,
              message_id: embedData.message_id,
              status: embedData.status,
              child_embed_ids: embedData.embed_ids,
              isProcessing: false,
            },
          }),
        );
        return;
      }

      // Mark as processed BEFORE starting async operations to prevent race conditions
      markEmbedAsProcessed(embedData.embed_id);
      console.info(
        `[ChatSyncService:AI] [EMBED_EVENT] Marked embed ${embedData.embed_id} as processed. ` +
          `Total processed embeds: ${processedFinalizedEmbeds.size}`,
      );

      // CHECK: If this embed arrives with already_encrypted flag, it means the server
      // is sending back client-encrypted data from Directus (e.g., when the cache had stale
      // "processing" status but Directus had the finished embed). In this case, store directly
      // in IndexedDB without re-encryption and do NOT send back to server (it's already there).
      const alreadyEncrypted =
        (embedData as unknown as Record<string, unknown>).already_encrypted ===
        true;
      if (alreadyEncrypted) {
        console.info(
          `[ChatSyncService:AI] Embed ${embedData.embed_id} arrived with already_encrypted=true - storing directly without re-encryption`,
        );

        const { embedStore } = await import("./embedStore");
        const { computeSHA256 } = await import("../message_parsing/utils");
        const embedRef = `embed:${embedData.embed_id}`;
        const hashedChatId = await computeSHA256(embedData.chat_id || "");

        // The content and type are already encrypted - store as-is
        const encryptedEmbedForStorage = {
          embed_id: embedData.embed_id,
          encrypted_type: embedData.type, // Already encrypted
          encrypted_content: embedData.content, // Already encrypted
          encrypted_text_preview: embedData.text_preview,
          status: embedData.status,
          hashed_chat_id: hashedChatId,
          embed_ids: embedData.embed_ids,
          parent_embed_id: embedData.parent_embed_id,
          version_number: embedData.version_number,
          file_path: embedData.file_path,
          content_hash: embedData.content_hash,
          text_length_chars: embedData.text_length_chars,
          is_private: embedData.is_private ?? false,
          is_shared: embedData.is_shared ?? false,
          createdAt: embedData.createdAt,
          updatedAt: embedData.updatedAt,
        };

        await embedStore.putEncrypted(
          embedRef,
          encryptedEmbedForStorage,
          (embedData.type || "app-skill-use") as EmbedType,
        );
        console.info(
          `[ChatSyncService:AI] ✅ Stored already-encrypted embed ${embedData.embed_id} in IndexedDB (no re-encryption, no server round-trip)`,
        );

        // Dispatch event for UI refresh
        serviceInstance.dispatchEvent(
          new CustomEvent("embedUpdated", {
            detail: {
              embed_id: embedData.embed_id,
              chat_id: embedData.chat_id,
              message_id: embedData.message_id,
              status: embedData.status,
              child_embed_ids: embedData.embed_ids,
              isProcessing: false,
            },
          }),
        );
        return;
      }

      // HYBRID ENCRYPTION: Check if this is a server-managed (Vault) embed
      // If encryption_mode is "vault", we skip local encryption and key generation
      // because the server already has the record and handles decryption via API.
      const encryptionMode = (embedData as any).encryption_mode || "client";
      if (encryptionMode === "vault") {
        console.info(
          `[ChatSyncService:AI] Embed ${embedData.embed_id} uses Vault encryption - skipping local re-encryption`,
        );

        const { embedStore } = await import("./embedStore");
        const embedRef = `embed:${embedData.embed_id}`;

        // Store in local IndexedDB as-is (plaintext content, but marked as vault)
        // We use put() instead of putEncrypted() because put() encrypts with the master key,
        // which is safe for local storage of server-managed metadata.
        await embedStore.put(
          embedRef,
          {
            ...embedData,
            encryption_mode: "vault",
            vault_key_id: (embedData as any).vault_key_id,
          },
          embedData.type as EmbedType,
        );

        console.info(
          `[ChatSyncService:AI] ✅ Stored Vault-managed embed ${embedData.embed_id} locally`,
        );

        // Dispatch event for UI refresh
        serviceInstance.dispatchEvent(
          new CustomEvent("embedUpdated", {
            detail: {
              embed_id: embedData.embed_id,
              chat_id: embedData.chat_id,
              message_id: embedData.message_id,
              status: embedData.status,
              child_embed_ids: embedData.embed_ids,
              isProcessing: false,
              encryption_mode: "vault",
            },
          }),
        );
        return;
      }

      // Generate embed key, encrypt content, store locally, send to Directus
      console.info(
        `[ChatSyncService:AI] Embed ${embedData.embed_id} is finalized (status=${embedData.status}) - encrypting and persisting`,
      );

      // Import dependencies
      const embedStoreModule = await import("./embedStore");
      const embedStore = embedStoreModule.embedStore;
      const cryptoService = await import("./cryptoService");
      const { computeSHA256 } = await import("../message_parsing/utils");
      const { chatDB } = await import("./db");

      const {
        generateEmbedKey,
        encryptWithEmbedKey,
        wrapEmbedKeyWithMasterKey,
        wrapEmbedKeyWithChatKey,
      } = cryptoService;

      // 0. Hash IDs first (needed for parent key lookup if this is a child embed)
      const hashedChatId = await computeSHA256(embedData.chat_id);
      const hashedMessageId = await computeSHA256(embedData.message_id);
      const hashedUserId = await computeSHA256(embedData.user_id);
      const hashedEmbedId = await computeSHA256(embedData.embed_id);

      let hashedTaskId: string | undefined;
      if (embedData.task_id) {
        hashedTaskId = await computeSHA256(embedData.task_id);
      }

      // 1. Determine embed encryption key (Option A - key inheritance)
      // - Parent embeds: Generate new unique key (or use early-generated key from processing state)
      // - Child embeds: Use parent embed's key (key inheritance)
      // Backend now sends parent_embed_id with child embeds, so we can use it directly
      let embedKey: Uint8Array;
      const isChildEmbed = !!embedData.parent_embed_id;
      const parentEmbedId = embedData.parent_embed_id;

      if (isChildEmbed) {
        // Child embed: Use parent embed's key (key inheritance - Option A)
        console.debug(
          `[ChatSyncService:AI] Child embed detected (parent: ${parentEmbedId}), using parent embed key`,
        );

        // Use exponential backoff retry mechanism since parent might still be processing
        // This handles race conditions where child embed arrives before parent finishes
        const maxRetries = 5;
        const baseDelay = 100; // Start with 100ms
        let parentKey: Uint8Array | null = null;

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
          parentKey = await embedStore.getEmbedKey(
            parentEmbedId!,
            hashedChatId,
          );

          if (parentKey) {
            if (attempt > 0) {
              console.info(
                `[ChatSyncService:AI] ✅ Parent key found on attempt ${attempt + 1} for child ${embedData.embed_id}`,
              );
            }
            break;
          }

          if (attempt < maxRetries) {
            // Exponential backoff: 100ms, 200ms, 400ms, 800ms, 1600ms (total ~3s max wait)
            const delay = baseDelay * Math.pow(2, attempt);
            console.debug(
              `[ChatSyncService:AI] Parent key not found for child ${embedData.embed_id}, retry ${attempt + 1}/${maxRetries} in ${delay}ms...`,
            );
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }

        if (!parentKey) {
          // Log detailed error for debugging
          console.error(
            `[ChatSyncService:AI] ❌ CRITICAL: Failed to get parent embed key after ${maxRetries} retries`,
            {
              childEmbedId: embedData.embed_id,
              parentEmbedId,
              hashedChatId: hashedChatId?.substring(0, 16) + "...",
            },
          );
          throw new Error(
            `Failed to get parent embed key for child embed ${embedData.embed_id} (parent: ${parentEmbedId}) after ${maxRetries} retries`,
          );
        }
        embedKey = parentKey;
        console.debug(
          `[ChatSyncService:AI] Using parent embed key for child embed ${embedData.embed_id}`,
        );

        // CRITICAL: Cache the child embed's key immediately so it's available for decryption
        // This prevents race conditions where the embed is stored but key lookup fails
        embedStore.setEmbedKeyInCache(
          embedData.embed_id,
          embedKey,
          hashedChatId,
        );
        embedStore.setEmbedKeyInCache(embedData.embed_id, embedKey, undefined); // 'master' fallback
        console.debug(
          `[ChatSyncService:AI] Cached inherited key for child embed ${embedData.embed_id}`,
        );
      } else {
        // Parent embed: Use already cached key or generate new unique key
        const cachedKey = await embedStore.getEmbedKey(
          embedData.embed_id,
          hashedChatId,
        );
        if (cachedKey) {
          embedKey = cachedKey;
          console.debug(
            `[ChatSyncService:AI] Using existing early-generated key for finalized parent embed ${embedData.embed_id}`,
          );
        } else {
          embedKey = generateEmbedKey();
          console.debug(
            `[ChatSyncService:AI] Generated new embed_key for finalized parent embed ${embedData.embed_id}`,
          );
        }

        // CRITICAL: Cache the parent embed key immediately after generation/retrieval
        // This ensures the key is available for:
        // 1. Child embeds that may be processed concurrently
        // 2. UI decryption when embedUpdated event is dispatched
        // 3. Any other code that needs the key before IndexedDB storage completes
        embedStore.setEmbedKeyInCache(
          embedData.embed_id,
          embedKey,
          hashedChatId,
        );
        embedStore.setEmbedKeyInCache(embedData.embed_id, embedKey, undefined); // 'master' fallback
        console.debug(
          `[ChatSyncService:AI] ✅ Cached embed key immediately for parent embed ${embedData.embed_id}`,
        );

        // CRITICAL: Pre-cache parent key for all known child embeds
        // This prevents race conditions where child embeds try to get parent key before it's cached
        if (
          embedData.embed_ids &&
          Array.isArray(embedData.embed_ids) &&
          embedData.embed_ids.length > 0
        ) {
          console.debug(
            `[ChatSyncService:AI] Pre-caching parent key for ${embedData.embed_ids.length} known child embeds`,
          );
          for (const childEmbedId of embedData.embed_ids) {
            embedStore.setEmbedKeyInCache(childEmbedId, embedKey, hashedChatId);
            embedStore.setEmbedKeyInCache(childEmbedId, embedKey, undefined); // 'master' fallback
          }
          console.debug(
            `[ChatSyncService:AI] ✅ Pre-cached parent key for children: ${embedData.embed_ids.join(", ")}`,
          );
        }
      }

      // 2. Encrypt content with embed_key
      const encryptedContent = await encryptWithEmbedKey(
        embedData.content,
        embedKey,
      );
      if (!encryptedContent) {
        throw new Error("Failed to encrypt embed content with embed_key");
      }

      // 3. Encrypt type with embed_key
      const encryptedType = await encryptWithEmbedKey(embedData.type, embedKey);
      if (!encryptedType) {
        throw new Error("Failed to encrypt embed type with embed_key");
      }

      // 4. Encrypt text preview if present
      let encryptedTextPreview: string | undefined;
      if (embedData.text_preview) {
        const encrypted = await encryptWithEmbedKey(
          embedData.text_preview,
          embedKey,
        );
        if (encrypted) {
          encryptedTextPreview = encrypted;
        }
      }

      // 3. Create key wrappers for offline sharing support (ONLY for parent embeds)
      // Child embeds inherit the parent's key, so they don't need their own wrappers
      // Master key wrapper: AES(embed_key, master_key) - for owner's cross-chat access
      // Chat key wrapper: AES(embed_key, chat_key) - for shared chat access
      let wrappedMasterKey: string | null = null;
      let wrappedChatKey: string | null = null;

      if (!isChildEmbed) {
        // Only create key wrappers for parent embeds
        wrappedMasterKey = await wrapEmbedKeyWithMasterKey(embedKey);
        if (!wrappedMasterKey) {
          throw new Error("Failed to wrap embed_key with master key");
        }

        const chatKey = chatDB.getOrGenerateChatKey(embedData.chat_id);
        if (!chatKey) {
          throw new Error("Failed to get chat key for wrapping embed_key");
        }
        wrappedChatKey = await wrapEmbedKeyWithChatKey(embedKey, chatKey);

        console.debug(
          `[ChatSyncService:AI] Created key wrappers for parent embed ${embedData.embed_id}`,
        );
      } else {
        console.debug(
          `[ChatSyncService:AI] Skipping key wrapper creation for child embed ${embedData.embed_id} (uses parent key)`,
        );
      }

      // 7. Store encrypted embed locally in IndexedDB
      // This uses putEncrypted() since content is already encrypted with embed_key
      // CRITICAL: Pass plaintext content to extract app_id/skill_id metadata BEFORE encryption
      // This avoids needing to decrypt later when embed keys might not be available yet
      const embedRef = `embed:${embedData.embed_id}`;
      // Extract metadata from plaintext content (best effort)
      let preExtractedMetadata:
        | { app_id?: string; skill_id?: string }
        | undefined;
      try {
        const decoded = await decodeToonContentSafe(embedData.content);
        if (decoded && typeof decoded === "object" && decoded !== null) {
          const decodedObj = decoded as Record<string, unknown>;
          preExtractedMetadata = {
            app_id:
              typeof decodedObj.app_id === "string"
                ? decodedObj.app_id
                : undefined,
            skill_id:
              typeof decodedObj.skill_id === "string"
                ? decodedObj.skill_id
                : undefined,
          };
          console.debug(
            "[ChatSyncService:AI] Pre-extracted app metadata from plaintext:",
            preExtractedMetadata,
          );
        }
      } catch (metaErr) {
        console.debug(
          "[ChatSyncService:AI] Failed to pre-extract app metadata:",
          metaErr,
        );
      }
      const encryptedEmbedForStorage = {
        embed_id: embedData.embed_id,
        encrypted_type: encryptedType,
        encrypted_content: encryptedContent,
        encrypted_text_preview: encryptedTextPreview,
        status: embedData.status,
        hashed_chat_id: hashedChatId,
        hashed_message_id: hashedMessageId,
        hashed_task_id: hashedTaskId,
        embed_ids: embedData.embed_ids,
        parent_embed_id: parentEmbedId || embedData.parent_embed_id, // Use detected parent_embed_id if found
        version_number: embedData.version_number,
        file_path: embedData.file_path,
        content_hash: embedData.content_hash,
        text_length_chars: embedData.text_length_chars,
        is_private: embedData.is_private ?? false,
        is_shared: embedData.is_shared ?? false,
        createdAt: embedData.createdAt,
        updatedAt: embedData.updatedAt,
      };

      // Pass plaintext content to extract app_id/skill_id metadata
      await embedStore.putEncrypted(
        embedRef,
        encryptedEmbedForStorage,
        embedData.type as EmbedType,
        embedData.content,
        preExtractedMetadata,
      );
      console.info(
        `[ChatSyncService:AI] Stored encrypted embed ${embedData.embed_id} in local IndexedDB`,
      );

      // 8. Store embed keys locally in IndexedDB (ONLY for parent embeds)
      // Child embeds don't have their own key wrappers - they use the parent's key
      if (!isChildEmbed && wrappedMasterKey && wrappedChatKey) {
        const now = Math.floor(Date.now() / 1000);
        const embedKeysForStorage = [
          {
            hashed_embed_id: hashedEmbedId,
            key_type: "master" as const,
            hashed_chat_id: null,
            encrypted_embed_key: wrappedMasterKey,
            hashed_user_id: hashedUserId,
            created_at: now,
          },
          {
            hashed_embed_id: hashedEmbedId,
            key_type: "chat" as const,
            hashed_chat_id: hashedChatId,
            encrypted_embed_key: wrappedChatKey,
            hashed_user_id: hashedUserId,
            created_at: now,
          },
        ];

        await embedStore.storeEmbedKeys(embedKeysForStorage);
        console.info(
          `[ChatSyncService:AI] Stored key wrappers for parent embed ${embedData.embed_id} locally`,
        );
      } else if (isChildEmbed) {
        console.debug(
          `[ChatSyncService:AI] Skipping key wrapper storage for child embed ${embedData.embed_id} (uses parent key)`,
        );
      }

      // 9. Send encrypted embed to server for Directus storage
      // CRITICAL: Use snake_case for Directus fields and Unix timestamps in SECONDS
      // embedData.createdAt/updatedAt may be in milliseconds, must convert to seconds
      const nowSeconds = Math.floor(Date.now() / 1000);
      const storePayload: import("../types/chat").StoreEmbedPayload = {
        embed_id: embedData.embed_id,
        encrypted_type: encryptedType,
        encrypted_content: encryptedContent,
        encrypted_text_preview: encryptedTextPreview,
        status: embedData.status,
        hashed_chat_id: hashedChatId,
        hashed_message_id: hashedMessageId,
        hashed_task_id: hashedTaskId,
        hashed_user_id: hashedUserId,
        embed_ids: embedData.embed_ids,
        parent_embed_id: parentEmbedId || embedData.parent_embed_id, // Use detected parent_embed_id if found
        version_number: embedData.version_number,
        file_path: embedData.file_path,
        content_hash: embedData.content_hash,
        text_length_chars: embedData.text_length_chars,
        is_private: embedData.is_private ?? false,
        is_shared: embedData.is_shared ?? false,
        // Convert milliseconds to seconds for Directus storage
        created_at: embedData.createdAt
          ? Math.floor(embedData.createdAt / 1000)
          : nowSeconds,
        updated_at: embedData.updatedAt
          ? Math.floor(embedData.updatedAt / 1000)
          : nowSeconds,
      };

      const sendersModule = await import("./chatSyncServiceSenders");
      const sendStoreFunction =
        sendersModule.sendStoreEmbedImpl ||
        (
          sendersModule as {
            default?: {
              sendStoreEmbedImpl?: typeof sendersModule.sendStoreEmbedImpl;
            };
          }
        ).default?.sendStoreEmbedImpl;

      if (typeof sendStoreFunction !== "function") {
        throw new Error("sendStoreEmbedImpl function not found");
      }

      await sendStoreFunction(serviceInstance, storePayload);
      console.info(
        `[ChatSyncService:AI] Sent encrypted embed ${embedData.embed_id} to Directus`,
      );

      // 10. Send key wrappers to server for embed_keys collection (ONLY for parent embeds)
      // Child embeds don't have their own key wrappers - they use the parent's key
      if (!isChildEmbed && wrappedMasterKey && wrappedChatKey) {
        const now = Math.floor(Date.now() / 1000);
        const embedKeysForStorage = [
          {
            hashed_embed_id: hashedEmbedId,
            key_type: "master" as const,
            hashed_chat_id: null,
            encrypted_embed_key: wrappedMasterKey,
            hashed_user_id: hashedUserId,
            created_at: now,
          },
          {
            hashed_embed_id: hashedEmbedId,
            key_type: "chat" as const,
            hashed_chat_id: hashedChatId,
            encrypted_embed_key: wrappedChatKey,
            hashed_user_id: hashedUserId,
            created_at: now,
          },
        ];

        const embedKeysPayload = { keys: embedKeysForStorage };

        const sendStoreEmbedKeysFunction =
          sendersModule.sendStoreEmbedKeysImpl ||
          (
            sendersModule as {
              default?: {
                sendStoreEmbedKeysImpl?: typeof sendersModule.sendStoreEmbedKeysImpl;
              };
            }
          ).default?.sendStoreEmbedKeysImpl;

        if (typeof sendStoreEmbedKeysFunction !== "function") {
          throw new Error("sendStoreEmbedKeysImpl function not found");
        }

        await sendStoreEmbedKeysFunction(serviceInstance, embedKeysPayload);
        console.info(
          `[ChatSyncService:AI] [EMBED_EVENT] ✅ Sent key wrappers for parent embed ${embedData.embed_id} to Directus ` +
            `(master + chat). This should only happen ONCE per finalized embed!`,
        );
      } else if (isChildEmbed) {
        console.debug(
          `[ChatSyncService:AI] Skipping key wrapper sending for child embed ${embedData.embed_id} (uses parent key)`,
        );
      }

      // 11. SAFETY FALLBACK: Re-cache parent key for children at the end
      // NOTE: Primary key caching now happens early (right after key generation) to prevent race conditions.
      // This fallback ensures keys are cached even if the early caching was somehow missed,
      // or if new child embed IDs were discovered during processing.
      if (
        !isChildEmbed &&
        embedData.embed_ids &&
        Array.isArray(embedData.embed_ids) &&
        embedData.embed_ids.length > 0
      ) {
        console.debug(
          `[ChatSyncService:AI] [FALLBACK] Re-caching parent key for ${embedData.embed_ids.length} child embeds (safety measure)`,
        );
        for (const childEmbedId of embedData.embed_ids) {
          embedStore.setEmbedKeyInCache(childEmbedId, embedKey, hashedChatId);
          embedStore.setEmbedKeyInCache(childEmbedId, embedKey, undefined); // 'master' fallback
        }
      }

      // 12. Dispatch event for UI to refresh from stored data
      console.debug(
        `[ChatSyncService:AI] 📤 Dispatching embedUpdated event for embed ${embedData.embed_id}`,
        {
          embed_id: embedData.embed_id,
          status: embedData.status,
          chat_id: embedData.chat_id,
        },
      );
      serviceInstance.dispatchEvent(
        new CustomEvent("embedUpdated", {
          detail: {
            embed_id: embedData.embed_id,
            chat_id: embedData.chat_id,
            message_id: embedData.message_id,
            status: embedData.status,
            child_embed_ids: embedData.embed_ids,
            isProcessing: false,
          },
        }),
      );
    }
  } catch (error) {
    console.error(
      `[ChatSyncService:AI] Error handling send_embed_data for embed ${embedData.embed_id}:`,
      error,
    );
  }
}
