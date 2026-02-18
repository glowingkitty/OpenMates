// frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts
/**
 * WebSocket handlers for app settings and memories requests.
 *
 * Implements permission-based data sharing with the AI assistant:
 * 1. Server's preprocessor determines which app settings/memories could be relevant
 * 2. Server sends "request_app_settings_memories" WebSocket message with requested keys
 * 3. Client shows Permission Dialog with toggles for each category
 * 4. User accepts/rejects each category
 * 5. Client decrypts and sends accepted data to server
 * 6. Server caches data for AI processing (chat-specific, auto-evicted)
 *
 * The request is stored in chat history so users can respond hours/days later.
 */

import type { ChatSynchronizationService } from "./chatSyncService";
import { notificationStore } from "../stores/notificationStore";
import { chatDB } from "./db";
import { decryptWithMasterKey } from "./cryptoService";
import { aiTypingStore } from "../stores/aiTypingStore";
import { get } from "svelte/store";

/**
 * Payload structure for request_app_settings_memories WebSocket message
 */
interface RequestAppSettingsMemoriesPayload {
  request_id: string;
  chat_id: string;
  requested_keys: string[]; // Array of "app_id-item_type" format (e.g., "code-preferred_technologies")
  yaml_content: string; // YAML structure for the request (for chat history storage)
  message_id?: string; // User message ID that triggered this request (for UI display)
}

/**
 * Individual entry within a category for entry-level selection in the permission dialog.
 */
export interface AppSettingsMemoriesEntryInfo {
  id: string; // Entry ID
  title: string; // Display title (from is_title schema field)
  subtitle?: string; // Display subtitle (from is_subtitle schema field)
  selected: boolean; // Whether this individual entry is selected for sharing
}

/**
 * Parsed category for the permission dialog
 */
export interface AppSettingsMemoriesCategory {
  key: string; // Original key format: "app_id-item_type"
  appId: string; // App ID (e.g., "code")
  itemType: string; // Category/item type (e.g., "preferred_technologies")
  displayName: string; // Human-readable name
  entryCount: number; // Number of entries in this category
  iconGradient?: string; // Optional CSS gradient for the icon background
  selected: boolean; // Whether this category is selected for sharing
  entries?: AppSettingsMemoriesEntryInfo[]; // Individual entries for entry-level selection (loaded on expand)
}

/**
 * Active permission request data (stored for the dialog)
 */
export interface PendingPermissionRequest {
  requestId: string;
  chatId: string;
  messageId?: string; // User message ID that triggered this request (for UI display)
  categories: AppSettingsMemoriesCategory[];
  yamlContent: string;
  createdAt: number;
}

// Store for pending permission requests (keyed by request_id)
// This allows the dialog to be shown and the user to respond later
const pendingPermissionRequests = new Map<string, PendingPermissionRequest>();

/**
 * Get a pending permission request by ID
 */
export function getPendingPermissionRequest(
  requestId: string,
): PendingPermissionRequest | undefined {
  return pendingPermissionRequests.get(requestId);
}

/**
 * Get all pending permission requests for a chat
 */
export function getPendingPermissionRequestsForChat(
  chatId: string,
): PendingPermissionRequest[] {
  const requests: PendingPermissionRequest[] = [];
  pendingPermissionRequests.forEach((request) => {
    if (request.chatId === chatId) {
      requests.push(request);
    }
  });
  return requests;
}

/**
 * Remove a pending permission request
 */
export function removePendingPermissionRequest(requestId: string): void {
  pendingPermissionRequests.delete(requestId);
}

/**
 * Generate a human-readable display name from an item_type
 * Converts "preferred_technologies" -> "Preferred technologies"
 */
export function formatDisplayName(itemType: string): string {
  return itemType
    .split("_")
    .map((word, index) =>
      index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word,
    )
    .join(" ");
}

/**
 * Get CSS gradient for an app ID from theme variables
 */
export function getAppGradient(appId: string): string {
  const gradientMap: Record<string, string> = {
    code: "linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)",
    travel: "linear-gradient(135deg, #059DB3 9.04%, #13DAF5 90.06%)",
    finance: "linear-gradient(135deg, #119106 9.04%, #15780D 90.06%)",
    health: "linear-gradient(135deg, #FD50A0 9.04%, #F42C2D 90.06%)",
    news: "linear-gradient(135deg, #F53F5B 9.04%, #DD0B2B 90.06%)",
    weather: "linear-gradient(135deg, #005BA5 9.04%, #00A7C9 90.06%)",
    jobs: "linear-gradient(135deg, #049363 9.04%, #00C382 90.06%)",
    legal: "linear-gradient(135deg, #239CFF 9.04%, #005BA5 90.06%)",
    files: "linear-gradient(135deg, #1E3A8A 9.04%, #29BEFB 90.06%)",
    ai: "linear-gradient(135deg, #CB7D5D 9.04%, #CB685D 90.06%)",
    tv: "linear-gradient(135deg, #8B5CF6 9.04%, #6D28D9 90.06%)",
    videos: "linear-gradient(135deg, #EF4444 9.04%, #DC2626 90.06%)",
    maps: "linear-gradient(135deg, #10B981 9.04%, #059669 90.06%)",
    study: "linear-gradient(135deg, #F59E0B 9.04%, #D97706 90.06%)",
    plants: "linear-gradient(135deg, #22C55E 9.04%, #16A34A 90.06%)",
  };
  return (
    gradientMap[appId] ||
    "linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)"
  );
}

/**
 * Populate individual entry info for categories so the permission dialog
 * can show expandable entry-level selection. Uses the appSettingsMemoriesStore
 * which has already-decrypted entries in memory.
 *
 * Falls back gracefully if entries can't be loaded (dialog still works at category level).
 */
async function populateCategoryEntries(
  categories: AppSettingsMemoriesCategory[],
): Promise<void> {
  try {
    const { appSettingsMemoriesStore } =
      await import("../stores/appSettingsMemoriesStore");
    const { appSkillsStore } = await import("../stores/appSkillsStore");
    const storeState = get(appSettingsMemoriesStore);

    console.debug(
      `[ChatSyncService:AppSettings] Populating entries for ${categories.length} categories. ` +
        `Total decrypted entries in store: ${storeState.decryptedEntries.size}`,
    );

    for (const category of categories) {
      // Find schema for is_title / is_subtitle fields
      const app = appSkillsStore.apps[category.appId];
      let titleField: string | null = null;
      let subtitleField: string | null = null;

      if (app) {
        const memoryMeta = app.settings_and_memories.find(
          (m) => m.id === category.itemType,
        );
        if (memoryMeta?.schema_definition?.properties) {
          for (const [key, prop] of Object.entries(
            memoryMeta.schema_definition.properties,
          )) {
            if (prop.is_title) titleField = key;
            if (prop.is_subtitle) subtitleField = key;
          }
        }
      }

      // Get decrypted entries for this category
      const entries: AppSettingsMemoriesEntryInfo[] = [];
      for (const decryptedEntry of Array.from(
        storeState.decryptedEntries.values(),
      )) {
        if (
          decryptedEntry.app_id === category.appId &&
          decryptedEntry.settings_group === category.itemType
        ) {
          const title = titleField
            ? String(
                decryptedEntry.item_value[titleField] ||
                  decryptedEntry.item_key,
              )
            : decryptedEntry.item_key;
          const subtitle = subtitleField
            ? String(decryptedEntry.item_value[subtitleField] || "")
            : undefined;

          entries.push({
            id: decryptedEntry.id,
            title,
            subtitle,
            selected: true, // Default to selected (same as category)
          });
        }
      }

      category.entries = entries;
      console.debug(
        `[ChatSyncService:AppSettings] Populated ${entries.length} entries for category ${category.key} (${category.displayName})`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error populating category entries:",
      error,
    );
    throw error; // Re-throw so caller can handle it
  }
}

/**
 * Handles server request for app settings/memories.
 *
 * 1. Parse the requested keys and build categories with entry counts
 * 2. Store the request for later reference
 * 3. Dispatch event to show Permission Dialog
 * 4. User can respond immediately or hours/days later
 */
export async function handleRequestAppSettingsMemoriesImpl(
  serviceInstance: ChatSynchronizationService,
  payload: RequestAppSettingsMemoriesPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'request_app_settings_memories':",
    payload,
  );

  const { request_id, chat_id, requested_keys, yaml_content } = payload;

  if (
    !request_id ||
    !chat_id ||
    !requested_keys ||
    !Array.isArray(requested_keys) ||
    requested_keys.length === 0
  ) {
    console.error(
      "[ChatSyncService:AppSettings] Invalid request payload:",
      payload,
    );
    return;
  }

  try {
    // Get entry counts from IndexedDB to show in the dialog
    const entryCounts = await chatDB.getAppSettingsMemoriesEntryCounts();

    // Build categories from requested keys
    const categories: AppSettingsMemoriesCategory[] = [];
    const validKeys: string[] = [];

    for (const key of requested_keys) {
      // Parse "app_id-item_type" format
      const dashIndex = key.indexOf("-");
      if (dashIndex === -1) {
        console.warn(
          `[ChatSyncService:AppSettings] Invalid key format (missing hyphen): ${key}`,
        );
        continue;
      }

      const appId = key.substring(0, dashIndex);
      const itemType = key.substring(dashIndex + 1);

      if (!appId || !itemType) {
        console.warn(
          `[ChatSyncService:AppSettings] Invalid key format (empty parts): ${key}`,
        );
        continue;
      }

      // Check if this category exists in IndexedDB
      const entryCount = entryCounts.get(key) || 0;

      if (entryCount === 0) {
        console.warn(
          `[ChatSyncService:AppSettings] No entries found for key: ${key}, skipping`,
        );
        continue;
      }

      validKeys.push(key);
      categories.push({
        key,
        appId,
        itemType,
        displayName: formatDisplayName(itemType),
        entryCount,
        iconGradient: getAppGradient(appId),
        selected: true, // Default to selected
      });
    }

    if (categories.length === 0) {
      console.warn(
        "[ChatSyncService:AppSettings] No valid categories found in request, skipping dialog",
      );
      return;
    }

    // Populate individual entry info for each category (for entry-level selection in the dialog)
    // IMPORTANT: If this fails, categories will have no entry-level info (only category-level)
    try {
      await populateCategoryEntries(categories);
      console.info(
        `[ChatSyncService:AppSettings] Successfully populated entries for ${categories.length} categories`,
      );
    } catch (populateError) {
      console.error(
        "[ChatSyncService:AppSettings] Failed to populate category entries. Dialog will only show category-level selection:",
        populateError,
      );
      // Initialize entries as empty array for each category so the UI can still work
      for (const category of categories) {
        if (!category.entries) {
          category.entries = [];
        }
      }
    }

    console.info(
      `[ChatSyncService:AppSettings] Built ${categories.length} categories for permission dialog`,
    );

    // Clear the typing indicator - AI processing is now paused waiting for user input
    // The server has sent this request because it needs user permission before continuing
    const currentTypingStatus = get(aiTypingStore);
    if (
      currentTypingStatus.chatId === chat_id &&
      currentTypingStatus.isTyping
    ) {
      console.info(
        `[ChatSyncService:AppSettings] Clearing typing indicator for chat ${chat_id} - waiting for user permission`,
      );
      aiTypingStore.reset();
    }

    // Clear the active AI task so the stop button disappears
    // The task is paused waiting for user input - it's not actively processing
    const taskInfo = serviceInstance.activeAITasks.get(chat_id);
    if (taskInfo) {
      console.info(
        `[ChatSyncService:AppSettings] Clearing active AI task ${taskInfo.taskId} for chat ${chat_id} - waiting for user permission`,
      );
      serviceInstance.activeAITasks.delete(chat_id);
      // Dispatch aiTaskEnded event so MessageInput component updates
      serviceInstance.dispatchEvent(
        new CustomEvent("aiTaskEnded", {
          detail: {
            chatId: chat_id,
            taskId: taskInfo.taskId,
            status: "waiting_for_permission",
          },
        }),
      );
    }

    // Update user message status from 'processing' to 'waiting_for_user' since we're waiting for input
    // This shows "Waiting for you..." in the sidebar and typing indicator instead of "Processing..."
    if (payload.message_id) {
      try {
        const userMessage = await chatDB.getMessage(payload.message_id);
        if (userMessage && userMessage.status === "processing") {
          // Update the message status and save it back
          const updatedMessage = {
            ...userMessage,
            status: "waiting_for_user" as const,
          };
          await chatDB.saveMessage(updatedMessage);
          console.info(
            `[ChatSyncService:AppSettings] Updated user message ${payload.message_id} status from 'processing' to 'waiting_for_user'`,
          );

          // Dispatch event to update UI immediately
          if (typeof window !== "undefined") {
            window.dispatchEvent(
              new CustomEvent("messageStatusUpdated", {
                detail: {
                  messageId: payload.message_id,
                  status: "waiting_for_user",
                  chatId: chat_id,
                },
              }),
            );
          }
        }
      } catch (msgError) {
        console.warn(
          `[ChatSyncService:AppSettings] Could not update user message status:`,
          msgError,
        );
      }
    }

    // Persist the request as a system message in chat history.
    // This ensures the request survives logout/login and cross-device sync.
    // ChatHistory.svelte will detect "unpaired" requests (no matching response)
    // and re-show the permission dialog automatically.
    if (payload.message_id) {
      try {
        await saveAppSettingsMemoriesRequestMessage(
          serviceInstance,
          chat_id,
          payload.message_id,
          request_id,
          validKeys,
          categories.map((cat) => ({
            appId: cat.appId,
            itemType: cat.itemType,
            entryCount: cat.entryCount,
          })),
        );
        console.info(
          `[ChatSyncService:AppSettings] Persisted request ${request_id} as system message for message ${payload.message_id}`,
        );
      } catch (saveError) {
        console.error(
          "[ChatSyncService:AppSettings] Error saving request system message:",
          saveError,
        );
        // Continue - dialog can still show from in-memory state even if persistence fails
      }
    }

    // Store the pending request in-memory for immediate dialog display
    // NOTE: This in-memory Map will be removed in a follow-up task once ChatHistory.svelte
    // drives the dialog from the persisted system message instead
    const pendingRequest: PendingPermissionRequest = {
      requestId: request_id,
      chatId: chat_id,
      messageId: payload.message_id, // User message that triggered this request
      categories,
      yamlContent: yaml_content || "",
      createdAt: Date.now(),
    };
    pendingPermissionRequests.set(request_id, pendingRequest);

    // Dispatch event to show the Permission Dialog
    // The ActiveChat component or a global listener should handle this event
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("showAppSettingsMemoriesPermissionDialog", {
          detail: pendingRequest,
        }),
      );
      console.info(
        `[ChatSyncService:AppSettings] Dispatched showAppSettingsMemoriesPermissionDialog event for request ${request_id}`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error handling app settings/memories request:",
      error,
    );
    notificationStore.addNotification(
      "error",
      "Failed to process app settings/memories request",
      5000,
    );
  }
}

/**
 * Handle user confirmation of app settings/memories sharing.
 * Called when user clicks "Include" in the Permission Dialog.
 *
 * 1. Load and decrypt the selected app settings/memories entries
 * 2. Send decrypted data to server via WebSocket
 * 3. Server caches data for AI processing
 * 4. Create a system message with response metadata (synced to server for cross-device display)
 *
 * The request data is retrieved from the permission store (which may have been populated
 * from the in-memory Map for fresh requests, or from a recovered system message after
 * session recovery). The in-memory Map is checked as a fallback.
 */
export async function handlePermissionDialogConfirm(
  serviceInstance: ChatSynchronizationService,
  requestId: string,
  selectedKeys: string[],
  selectedEntryIdsByCategory?: Map<string, string[] | null>,
): Promise<void> {
  // Try in-memory Map first (fresh request), fall back to permission store (recovered request)
  let pendingRequest = pendingPermissionRequests.get(requestId);
  if (!pendingRequest) {
    // Request was recovered from system message - build from the store
    const { appSettingsMemoriesPermissionStore } =
      await import("../stores/appSettingsMemoriesPermissionStore");
    const { get: getStoreValue } = await import("svelte/store");
    const storeState = getStoreValue(appSettingsMemoriesPermissionStore);
    if (
      storeState.currentRequest &&
      storeState.currentRequest.requestId === requestId
    ) {
      pendingRequest = storeState.currentRequest;
      console.info(
        `[ChatSyncService:AppSettings] Using permission store for recovered request ${requestId}`,
      );
    }
  }
  if (!pendingRequest) {
    console.error(
      `[ChatSyncService:AppSettings] No pending request found for ID: ${requestId}`,
    );
    return;
  }

  const { chatId, messageId, categories } = pendingRequest;

  try {
    console.info(
      `[ChatSyncService:AppSettings] Processing confirmation for ${selectedKeys.length} selected categories`,
    );

    // Load and decrypt entries for selected categories
    const appSettingsMemories: Array<{
      app_id: string;
      item_key: string;
      content: unknown;
    }> = [];

    // Build metadata for selected categories (for UI display)
    const selectedCategories = categories.filter((cat) =>
      selectedKeys.includes(cat.key),
    );

    for (const key of selectedKeys) {
      const dashIndex = key.indexOf("-");
      if (dashIndex === -1) continue;

      const appId = key.substring(0, dashIndex);
      const itemType = key.substring(dashIndex + 1);

      // Check if specific entries were selected for this category
      // null means "all entries" (no entry-level filtering)
      const selectedEntryIds = selectedEntryIdsByCategory?.get(key) ?? null;

      // Get entries for this category
      const entries = await chatDB.getAppSettingsMemoriesEntriesByAppAndType(
        appId,
        itemType,
      );

      for (const entry of entries) {
        // If entry-level selection is active, skip entries that weren't selected
        if (selectedEntryIds !== null && !selectedEntryIds.includes(entry.id)) {
          continue;
        }

        try {
          // Decrypt the entry content
          const decryptedJson = await decryptWithMasterKey(
            entry.encrypted_item_json,
          );
          if (decryptedJson) {
            const content = JSON.parse(decryptedJson);
            // IMPORTANT: Use itemType (human-readable like 'preferred_tech') NOT entry.item_key (hash)
            // The server cache lookup uses the human-readable key from preprocessing LLM output
            appSettingsMemories.push({
              app_id: appId,
              item_key: itemType,
              content,
            });
          }
        } catch (decryptError) {
          console.error(
            `[ChatSyncService:AppSettings] Failed to decrypt entry ${entry.id}:`,
            decryptError,
          );
        }
      }
    }

    if (appSettingsMemories.length === 0) {
      console.warn(
        "[ChatSyncService:AppSettings] No entries to send after decryption",
      );
      removePendingPermissionRequest(requestId);
      return;
    }

    // Import and call the sender function
    console.info(
      `[ChatSyncService:AppSettings] About to send ${appSettingsMemories.length} entries to server...`,
    );
    const { sendAppSettingsMemoriesConfirmedImpl } =
      await import("./chatSyncServiceSenders");
    await sendAppSettingsMemoriesConfirmedImpl(
      serviceInstance,
      chatId,
      appSettingsMemories,
    );

    console.info(
      `[ChatSyncService:AppSettings] Successfully sent ${appSettingsMemories.length} entries to server`,
    );

    // Create system message with response metadata (synced to server for cross-device display)
    // This stores ONLY essential metadata (appId, itemType, entryCount), NOT display info or actual content
    // Display name and icon are loaded client-side based on appId and itemType
    if (messageId) {
      try {
        const categoryMetadata: AppSettingsMemoriesResponseCategory[] =
          selectedCategories.map((cat) => ({
            appId: cat.appId,
            itemType: cat.itemType,
            entryCount: cat.entryCount,
          }));

        await saveAppSettingsMemoriesResponseMessage(
          serviceInstance,
          chatId,
          messageId,
          "included",
          categoryMetadata,
        );
        console.info(
          `[ChatSyncService:AppSettings] Created system message for 'included' action on message ${messageId}`,
        );
      } catch (saveError) {
        console.error(
          "[ChatSyncService:AppSettings] Error saving response message:",
          saveError,
        );
      }
    }

    // Clean up the pending request
    removePendingPermissionRequest(requestId);

    // Notify user
    notificationStore.addNotification(
      "success",
      "App settings & memories shared with assistant",
      3000,
    );
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error processing permission confirmation:",
      error,
    );
    notificationStore.addNotification(
      "error",
      "Failed to share app settings & memories",
      5000,
    );
  }
}

/**
 * Handle user exclusion of app settings/memories sharing.
 * Called when user clicks "Reject all" in the Permission Dialog.
 * Creates a system message with 'rejected' action (synced to server for cross-device display).
 *
 * IMPORTANT: Sends an empty app_settings_memories array to the server, which triggers
 * the AI continuation task to process the request WITHOUT the app settings/memories.
 * The server's app_settings_memories_confirmed_handler detects is_rejection=true
 * when the array is empty and continues processing accordingly.
 *
 * The request data is retrieved from the in-memory Map (fresh request) or from
 * the permission store (recovered request from system message).
 */
export async function handlePermissionDialogExclude(
  serviceInstance: ChatSynchronizationService,
  requestId: string,
): Promise<void> {
  // Try in-memory Map first (fresh request), fall back to permission store (recovered request)
  let pendingRequest = pendingPermissionRequests.get(requestId);
  if (!pendingRequest) {
    const { appSettingsMemoriesPermissionStore } =
      await import("../stores/appSettingsMemoriesPermissionStore");
    const { get: getStoreValue } = await import("svelte/store");
    const storeState = getStoreValue(appSettingsMemoriesPermissionStore);
    if (
      storeState.currentRequest &&
      storeState.currentRequest.requestId === requestId
    ) {
      pendingRequest = storeState.currentRequest;
      console.info(
        `[ChatSyncService:AppSettings] Using permission store for recovered request ${requestId}`,
      );
    }
  }

  console.info(
    `[ChatSyncService:AppSettings] User rejected app settings/memories for request ${requestId}`,
  );

  // CRITICAL: Send empty array to server to trigger continuation WITHOUT app settings/memories
  // The server handler detects is_rejection=true when the array is empty and continues processing
  if (pendingRequest?.chatId) {
    try {
      const { sendAppSettingsMemoriesConfirmedImpl } =
        await import("./chatSyncServiceSenders");
      // Send empty array - server will detect this as a rejection and continue processing without the data
      await sendAppSettingsMemoriesConfirmedImpl(
        serviceInstance,
        pendingRequest.chatId,
        [],
      );
      console.info(
        `[ChatSyncService:AppSettings] Sent rejection (empty array) to server for chat ${pendingRequest.chatId}`,
      );
    } catch (sendError) {
      console.error(
        "[ChatSyncService:AppSettings] Error sending rejection to server:",
        sendError,
      );
    }
  }

  // Create system message with response metadata (synced to server for cross-device display)
  if (pendingRequest?.messageId && pendingRequest?.chatId) {
    try {
      await saveAppSettingsMemoriesResponseMessage(
        serviceInstance,
        pendingRequest.chatId,
        pendingRequest.messageId,
        "rejected",
      );
      console.info(
        `[ChatSyncService:AppSettings] Created system message for 'rejected' action on message ${pendingRequest.messageId}`,
      );
    } catch (saveError) {
      console.error(
        "[ChatSyncService:AppSettings] Error saving rejected response message:",
        saveError,
      );
    }
  }

  removePendingPermissionRequest(requestId);
}

/**
 * Locally dismiss the permission dialog without sending a WebSocket rejection to the server.
 *
 * This is used when the user sends a follow-up message while a permission dialog is pending.
 * Instead of sending an explicit rejection (which would trigger a server-side continuation task
 * and produce a SEPARATE AI response), we only:
 * 1. Create a "rejected" system message in the local chat history (for UI display)
 * 2. Clear the permission dialog UI
 * 3. Remove the pending request from the in-memory Map
 *
 * The server's main_processor.py already handles auto-rejecting the pending context when it
 * receives the new message (deletes from Redis + sends dismiss event). By not sending the
 * WebSocket rejection, we avoid triggering _trigger_continuation which would create a duplicate
 * AI response alongside the response from the new message.
 *
 * The request data is retrieved from the in-memory Map (fresh request) or from
 * the permission store (recovered request from system message).
 */
export async function handlePermissionDialogLocalDismiss(
  serviceInstance: ChatSynchronizationService,
  requestId: string,
): Promise<void> {
  // Try in-memory Map first (fresh request), fall back to permission store (recovered request)
  let pendingRequest = pendingPermissionRequests.get(requestId);
  if (!pendingRequest) {
    const { appSettingsMemoriesPermissionStore } =
      await import("../stores/appSettingsMemoriesPermissionStore");
    const { get: getStoreValue } = await import("svelte/store");
    const storeState = getStoreValue(appSettingsMemoriesPermissionStore);
    if (
      storeState.currentRequest &&
      storeState.currentRequest.requestId === requestId
    ) {
      pendingRequest = storeState.currentRequest;
      console.info(
        `[ChatSyncService:AppSettings] Using permission store for recovered request ${requestId}`,
      );
    }
  }

  console.info(
    `[ChatSyncService:AppSettings] Locally dismissing permission dialog for request ${requestId} ` +
      `(user sent follow-up message - server will auto-reject pending context)`,
  );

  // Create system message with "rejected" metadata (synced to server for cross-device display)
  // This ensures the "Rejected App settings & memories request." badge shows under the original user message
  if (pendingRequest?.messageId && pendingRequest?.chatId) {
    try {
      await saveAppSettingsMemoriesResponseMessage(
        serviceInstance,
        pendingRequest.chatId,
        pendingRequest.messageId,
        "rejected",
      );
      console.info(
        `[ChatSyncService:AppSettings] Created system message for locally dismissed request on message ${pendingRequest.messageId}`,
      );
    } catch (saveError) {
      console.error(
        "[ChatSyncService:AppSettings] Error saving locally dismissed response message:",
        saveError,
      );
    }
  }

  // Remove from pending requests (no WebSocket send - server handles its own cleanup)
  removePendingPermissionRequest(requestId);

  // Clear the dialog UI
  const { appSettingsMemoriesPermissionStore } =
    await import("../stores/appSettingsMemoriesPermissionStore");
  appSettingsMemoriesPermissionStore.clear();
}

/**
 * Category metadata for app settings/memories request.
 * Simplified structure - display name and icon are loaded client-side based on appId and itemType.
 */
export interface AppSettingsMemoriesRequestCategory {
  appId: string; // e.g., "code"
  itemType: string; // e.g., "preferred_technologies" (without app prefix)
  entryCount: number; // Number of entries in this category
}

/**
 * Content structure for app settings/memories REQUEST system message.
 * This is JSON-stringified and stored in the message content field.
 *
 * Persisting the request as a system message means it survives logout/login,
 * cross-device sync, and browser refreshes. ChatHistory.svelte can then detect
 * "unpaired" requests (no matching response system message) to re-show the dialog.
 */
export interface AppSettingsMemoriesRequestContent {
  type: "app_settings_memories_request";
  user_message_id: string; // The user message that triggered this request
  request_id: string; // Server-assigned request ID (for WebSocket confirm/reject)
  requested_keys: string[]; // Array of "app_id-item_type" format (e.g., "code-preferred_technologies")
  categories: AppSettingsMemoriesRequestCategory[]; // Parsed category metadata for dialog display
}

/**
 * Category metadata for app settings/memories response.
 * Simplified structure - display name and icon are loaded client-side based on appId and itemType.
 */
export interface AppSettingsMemoriesResponseCategory {
  appId: string; // e.g., "code"
  itemType: string; // e.g., "preferred_technologies" (without app prefix)
  entryCount: number; // Number of entries included
}

/**
 * Content structure for app settings/memories response system message
 * This is JSON-stringified and stored in the message content field
 */
export interface AppSettingsMemoriesResponseContent {
  type: "app_settings_memories_response";
  user_message_id: string;
  action: "included" | "rejected";
  categories?: AppSettingsMemoriesResponseCategory[];
}

/**
 * Create and save a system message for app settings/memories response.
 * This message is stored in IndexedDB and synced to the server for cross-device display.
 *
 * IMPORTANT: System messages are encrypted client-side with the chat key (zero-knowledge architecture)
 * just like regular messages. The server stores the encrypted content directly in Directus
 * and can only decrypt using the vault key for AI processing if needed.
 *
 * @param serviceInstance - The ChatSynchronizationService instance
 * @param chatId - The chat ID
 * @param userMessageId - The user message ID that triggered the request
 * @param action - 'included' or 'rejected'
 * @param categories - Category metadata (only for 'included' action)
 */
async function saveAppSettingsMemoriesResponseMessage(
  serviceInstance: ChatSynchronizationService,
  chatId: string,
  userMessageId: string,
  action: "included" | "rejected",
  categories?: AppSettingsMemoriesResponseCategory[],
): Promise<void> {
  // Import required utilities
  const { generateUUID } = await import("../message_parsing/utils");
  const { webSocketService } = await import("./websocketService");
  const { encryptWithChatKey } = await import("./cryptoService");

  // Generate unique message ID (format: last 10 chars of chat_id + uuid)
  const chatIdSuffix = chatId.slice(-10);
  const messageId = `${chatIdSuffix}-${generateUUID()}`;

  // Create system message content
  const responseContent: AppSettingsMemoriesResponseContent = {
    type: "app_settings_memories_response",
    user_message_id: userMessageId,
    action,
    categories: action === "included" ? categories : undefined,
  };

  const contentString = JSON.stringify(responseContent);

  // Get chat key for encryption (zero-knowledge architecture)
  const chatKey = chatDB.getChatKey(chatId);
  if (!chatKey) {
    console.error(
      `[ChatSyncService:AppSettings] No chat key found for chat ${chatId}, cannot encrypt system message`,
    );
    throw new Error(`No chat key found for chat ${chatId}`);
  }

  // Encrypt content with chat key (same as regular messages)
  const encryptedContent = await encryptWithChatKey(contentString, chatKey);
  if (!encryptedContent) {
    console.error(
      `[ChatSyncService:AppSettings] Failed to encrypt system message content`,
    );
    throw new Error("Failed to encrypt system message content");
  }

  // Create the system message
  const now = Math.floor(Date.now() / 1000);
  const systemMessage = {
    message_id: messageId,
    chat_id: chatId,
    role: "system" as const,
    content: contentString,
    created_at: now,
    status: "sending" as const,
    encrypted_content: encryptedContent, // Pre-encrypted with chat key
  };

  // Save to IndexedDB (already has encrypted_content, won't re-encrypt)
  await chatDB.saveMessage(systemMessage);
  console.debug(
    `[ChatSyncService:AppSettings] Saved system message ${messageId} to IndexedDB`,
  );

  // Send ENCRYPTED content to server for persistence and cross-device sync
  // Server stores this directly in Directus without re-encryption (zero-knowledge)
  const payload = {
    chat_id: chatId,
    message: {
      message_id: messageId,
      role: "system",
      encrypted_content: encryptedContent, // Send encrypted, not plaintext!
      created_at: now,
    },
  };

  try {
    await webSocketService.sendMessage("chat_system_message_added", payload);

    // Update message status to synced
    const syncedMessage = { ...systemMessage, status: "synced" as const };
    await chatDB.saveMessage(syncedMessage);

    console.debug(
      `[ChatSyncService:AppSettings] Sent system message ${messageId} to server`,
    );

    // Dispatch chatUpdated event to trigger UI refresh
    // ActiveChat listens for 'chatUpdated' with newMessage to update the chat history
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chatId,
          type: "system_message_added",
          newMessage: syncedMessage,
        },
      }),
    );
  } catch (sendError) {
    console.error(
      `[ChatSyncService:AppSettings] Error sending system message to server:`,
      sendError,
    );
    // Message is still saved locally, will be synced later
  }
}

/**
 * Create and save a system message for app settings/memories REQUEST.
 * This message is stored in IndexedDB and synced to the server for cross-device persistence.
 *
 * By persisting the request as a system message, it survives logout/login and
 * cross-device sync. ChatHistory.svelte detects "unpaired" requests (no matching
 * response system message with the same user_message_id) to re-show the permission dialog.
 *
 * IMPORTANT: System messages are encrypted client-side with the chat key (zero-knowledge architecture)
 * just like regular messages. The server stores the encrypted content directly in Directus.
 *
 * @param serviceInstance - The ChatSynchronizationService instance
 * @param chatId - The chat ID
 * @param userMessageId - The user message ID that triggered the request
 * @param requestId - The server-assigned request ID (for WebSocket confirm/reject)
 * @param requestedKeys - Array of "app_id-item_type" format keys
 * @param categories - Parsed category metadata for dialog display
 */
async function saveAppSettingsMemoriesRequestMessage(
  serviceInstance: ChatSynchronizationService,
  chatId: string,
  userMessageId: string,
  requestId: string,
  requestedKeys: string[],
  categories: AppSettingsMemoriesRequestCategory[],
): Promise<void> {
  // Import required utilities
  const { generateUUID } = await import("../message_parsing/utils");
  const { webSocketService } = await import("./websocketService");
  const { encryptWithChatKey } = await import("./cryptoService");

  // Generate unique message ID (format: last 10 chars of chat_id + uuid)
  const chatIdSuffix = chatId.slice(-10);
  const messageId = `${chatIdSuffix}-${generateUUID()}`;

  // Create system message content with request metadata
  // Categories are stored with minimal metadata (appId, itemType, entryCount)
  // Display name and icon gradient are loaded client-side based on appId and itemType
  const requestContent: AppSettingsMemoriesRequestContent = {
    type: "app_settings_memories_request",
    user_message_id: userMessageId,
    request_id: requestId,
    requested_keys: requestedKeys,
    categories: categories.map((cat) => ({
      appId: cat.appId,
      itemType: cat.itemType,
      entryCount: cat.entryCount,
    })),
  };

  const contentString = JSON.stringify(requestContent);

  // Get chat key for encryption (zero-knowledge architecture)
  const chatKey = chatDB.getChatKey(chatId);
  if (!chatKey) {
    console.error(
      `[ChatSyncService:AppSettings] No chat key found for chat ${chatId}, cannot encrypt request system message`,
    );
    throw new Error(`No chat key found for chat ${chatId}`);
  }

  // Encrypt content with chat key (same as regular messages)
  const encryptedContent = await encryptWithChatKey(contentString, chatKey);
  if (!encryptedContent) {
    console.error(
      `[ChatSyncService:AppSettings] Failed to encrypt request system message content`,
    );
    throw new Error("Failed to encrypt request system message content");
  }

  // Create the system message
  const now = Math.floor(Date.now() / 1000);
  const systemMessage = {
    message_id: messageId,
    chat_id: chatId,
    role: "system" as const,
    content: contentString,
    created_at: now,
    status: "sending" as const,
    encrypted_content: encryptedContent, // Pre-encrypted with chat key
  };

  // Save to IndexedDB (already has encrypted_content, won't re-encrypt)
  await chatDB.saveMessage(systemMessage);
  console.debug(
    `[ChatSyncService:AppSettings] Saved request system message ${messageId} to IndexedDB`,
  );

  // Send ENCRYPTED content to server for persistence and cross-device sync
  // Server stores this directly in Directus without re-encryption (zero-knowledge)
  const payload = {
    chat_id: chatId,
    message: {
      message_id: messageId,
      role: "system",
      encrypted_content: encryptedContent, // Send encrypted, not plaintext!
      created_at: now,
    },
  };

  try {
    await webSocketService.sendMessage("chat_system_message_added", payload);

    // Update message status to synced
    const syncedMessage = { ...systemMessage, status: "synced" as const };
    await chatDB.saveMessage(syncedMessage);

    console.debug(
      `[ChatSyncService:AppSettings] Sent request system message ${messageId} to server`,
    );

    // Dispatch chatUpdated event to trigger UI refresh
    // ActiveChat listens for 'chatUpdated' with newMessage to update the chat history
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chatId,
          type: "system_message_added",
          newMessage: syncedMessage,
        },
      }),
    );
  } catch (sendError) {
    console.error(
      `[ChatSyncService:AppSettings] Error sending request system message to server:`,
      sendError,
    );
    // Message is still saved locally, will be synced later
  }
}

/**
 * Payload structure for app_settings_memories_sync_ready WebSocket message
 */
interface AppSettingsMemoriesSyncReadyPayload {
  entries: Array<{
    id: string;
    app_id: string;
    item_key: string;
    item_type: string; // Category ID for filtering (e.g., 'preferred_technologies')
    encrypted_item_json: string;
    encrypted_app_key: string;
    created_at: number;
    updated_at: number;
    item_version: number;
    sequence_number?: number;
  }>;
  entry_count: number;
}

/**
 * Handles app settings/memories sync ready event (after Phase 3 chat sync completes).
 *
 * This function:
 * 1. Receives encrypted app settings/memories entries from server
 * 2. Stores encrypted entries in IndexedDB (encrypted with app-specific keys)
 * 3. Handles conflict resolution based on item_version (higher version wins)
 * 4. Dispatches event to notify App Store components
 *
 * **Zero-Knowledge Architecture**: All entries remain encrypted in IndexedDB.
 * Decryption happens on-demand when needed for display in App Store settings or chat context.
 */
export async function handleAppSettingsMemoriesSyncReadyImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AppSettingsMemoriesSyncReadyPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'app_settings_memories_sync_ready':",
    {
      entry_count: payload.entry_count,
      entries_received: payload.entries?.length || 0,
    },
  );

  const { entries } = payload;

  if (!entries || !Array.isArray(entries)) {
    console.error(
      "[ChatSyncService:AppSettings] Invalid sync payload - entries is not an array:",
      payload,
    );
    return;
  }

  try {
    // Store encrypted app settings/memories entries in IndexedDB
    // The storeAppSettingsMemoriesEntries method handles conflict resolution
    // based on item_version (higher version wins, or updated_at if versions are equal)
    await chatDB.storeAppSettingsMemoriesEntries(entries);

    console.info(
      `[ChatSyncService:AppSettings] Successfully synced ${entries.length} app settings/memories entries`,
    );

    // Refresh the in-memory store so entries are immediately available for the
    // @ mention dropdown. Without this, the dropdown reads stale (empty) store
    // state even though IndexedDB now has the entries.
    // Non-blocking: a failure here must never break the sync flow.
    const { appSettingsMemoriesStore } =
      await import("../stores/appSettingsMemoriesStore");
    appSettingsMemoriesStore.loadEntries().catch((err) => {
      console.warn(
        "[ChatSyncService:AppSettings] Failed to refresh store after sync (non-fatal):",
        err,
      );
    });

    // Dispatch custom event to notify App Store components that sync is complete
    // This allows the App Store UI to refresh if it's currently open
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("appSettingsMemoriesSyncReady", {
          detail: {
            entry_count: entries.length,
            synced_at: Date.now(),
          },
        }),
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error handling app settings/memories sync:",
      error,
    );
    // Don't throw - this is a non-critical sync that shouldn't block other operations
  }
}

/**
 * Payload structure for app_settings_memories_entry_stored WebSocket message
 * This is an acknowledgment from the server that it successfully stored an entry
 */
interface AppSettingsMemoriesEntryStoredPayload {
  entry_id: string;
  app_id: string;
  item_key: string;
  success: boolean;
}

/**
 * Handles acknowledgment that server stored an app settings/memories entry.
 *
 * This is sent by the server after successfully storing an entry in Directus.
 * The source device receives this as confirmation that the entry was persisted.
 *
 * This handler dispatches an event so UI components can update accordingly
 * (e.g., show a success indicator, remove pending state).
 */
export async function handleAppSettingsMemoriesEntryStoredImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AppSettingsMemoriesEntryStoredPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'app_settings_memories_entry_stored' acknowledgment:",
    {
      entry_id: payload.entry_id,
      app_id: payload.app_id,
      item_key: payload.item_key,
      success: payload.success,
    },
  );

  if (!payload.success) {
    console.warn(
      "[ChatSyncService:AppSettings] Server reported entry storage failed:",
      payload,
    );
    return;
  }

  // Dispatch custom event to notify UI components that the entry was successfully stored
  // This allows components to update their state (e.g., remove pending indicator)
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent("appSettingsMemoriesEntryStored", {
        detail: {
          entry_id: payload.entry_id,
          app_id: payload.app_id,
          item_key: payload.item_key,
          stored_at: Date.now(),
        },
      }),
    );
  }
}

/**
 * Payload structure for app_settings_memories_entry_synced WebSocket message
 * This is received when another device creates/updates an entry
 */
interface AppSettingsMemoriesEntrySyncedPayload {
  entries: Array<{
    id: string;
    app_id: string;
    item_key: string;
    item_type: string; // Category ID for filtering (e.g., 'preferred_technologies')
    encrypted_item_json: string;
    encrypted_app_key: string;
    created_at: number;
    updated_at: number;
    item_version: number;
    sequence_number?: number;
  }>;
  entry_count: number;
  source_device: string; // Device fingerprint hash of the source device
}

/**
 * Handles app settings/memories entry synced from another device.
 *
 * When another device creates or updates an app settings/memories entry:
 * 1. Server broadcasts the encrypted entry to all other logged-in devices
 * 2. This handler receives the entry and stores it in IndexedDB
 * 3. Dispatches event to notify App Store components to refresh
 *
 * **Zero-Knowledge Architecture**: Entry remains encrypted - server never decrypts it.
 * This device decrypts on-demand when displaying in App Store settings.
 */
export async function handleAppSettingsMemoriesEntrySyncedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: AppSettingsMemoriesEntrySyncedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'app_settings_memories_entry_synced' from another device:",
    {
      entry_count: payload.entry_count,
      source_device: payload.source_device?.substring(0, 8) + "...",
    },
  );

  const { entries } = payload;

  if (!entries || !Array.isArray(entries) || entries.length === 0) {
    console.warn(
      "[ChatSyncService:AppSettings] Invalid entry_synced payload - no entries",
    );
    return;
  }

  try {
    // Store encrypted entries in IndexedDB
    // The storeAppSettingsMemoriesEntries method handles conflict resolution
    await chatDB.storeAppSettingsMemoriesEntries(entries);

    console.info(
      `[ChatSyncService:AppSettings] Synced ${entries.length} entries from another device`,
    );

    // Refresh the in-memory store so the new entry is immediately available for
    // the @ mention dropdown on this device.
    // Non-blocking: a failure here must never break the sync flow.
    const { appSettingsMemoriesStore } =
      await import("../stores/appSettingsMemoriesStore");
    appSettingsMemoriesStore.loadEntries().catch((err) => {
      console.warn(
        "[ChatSyncService:AppSettings] Failed to refresh store after cross-device sync (non-fatal):",
        err,
      );
    });

    // Dispatch custom event to notify App Store components to refresh
    // This allows the UI to show the new entry immediately
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("appSettingsMemoriesEntrySynced", {
          detail: {
            entries: entries,
            entry_count: entries.length,
            synced_at: Date.now(),
          },
        }),
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error handling entry sync from other device:",
      error,
    );
  }
}

/**
 * Payload structure for dismiss_app_settings_memories_dialog WebSocket message
 * Sent when user sends a new message without responding to the permission dialog
 */
interface DismissAppSettingsMemoriesDialogPayload {
  chat_id: string;
  request_id: string;
  reason: string; // e.g., "new_message_sent"
  message_id: string; // Original message that triggered the request
}

/**
 * Handles auto-dismissal of app settings/memories permission dialog.
 *
 * This is called when user sends a new message without responding to the
 * permission dialog. The server auto-rejects the pending request and sends
 * this event to dismiss the UI.
 *
 * The UI should:
 * 1. Close the permission dialog if shown
 * 2. Update the chat message to show "rejected" state (like user clicked Reject All)
 * 3. Remove from pending requests
 */
export async function handleDismissAppSettingsMemoriesDialogImpl(
  serviceInstance: ChatSynchronizationService,
  payload: DismissAppSettingsMemoriesDialogPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'dismiss_app_settings_memories_dialog':",
    payload,
  );

  const { chat_id, request_id, reason, message_id } = payload;

  if (!chat_id || !request_id) {
    console.warn(
      "[ChatSyncService:AppSettings] Invalid dismiss payload:",
      payload,
    );
    return;
  }

  // Get the pending request before removing it - try in-memory Map then permission store
  let pendingRequest = pendingPermissionRequests.get(request_id);
  if (!pendingRequest) {
    const { appSettingsMemoriesPermissionStore } =
      await import("../stores/appSettingsMemoriesPermissionStore");
    const { get: getStoreValue } = await import("svelte/store");
    const storeState = getStoreValue(appSettingsMemoriesPermissionStore);
    if (
      storeState.currentRequest &&
      storeState.currentRequest.requestId === request_id
    ) {
      pendingRequest = storeState.currentRequest;
    }
  }

  // If the pending request was already removed locally (e.g., by handlePermissionDialogLocalDismiss
  // when user sent a follow-up message on THIS device), skip creating a duplicate system message
  // and notification. The local dismiss already handled everything.
  if (!pendingRequest) {
    console.info(
      `[ChatSyncService:AppSettings] Request ${request_id} already handled locally for chat ${chat_id} ` +
        `(reason: ${reason}) - skipping duplicate dismiss`,
    );

    // Still dispatch the dismiss event to clear any lingering dialog UI (defensive)
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("dismissAppSettingsMemoriesPermissionDialog", {
          detail: {
            requestId: request_id,
            chatId: chat_id,
            reason: reason,
            messageId: message_id,
          },
        }),
      );
    }
    return;
  }

  console.info(
    `[ChatSyncService:AppSettings] Auto-rejecting request ${request_id} for chat ${chat_id} ` +
      `(reason: ${reason}, original_message: ${message_id})`,
  );

  // Create system message to show "rejected" state in chat UI
  // This is identical to what happens when user clicks "Reject All"
  if (pendingRequest.messageId && pendingRequest.chatId) {
    try {
      await saveAppSettingsMemoriesResponseMessage(
        serviceInstance,
        pendingRequest.chatId,
        pendingRequest.messageId,
        "rejected", // Shows as rejected in chat UI
      );
      console.info(
        `[ChatSyncService:AppSettings] Created system message for auto-rejected request on message ${pendingRequest.messageId}`,
      );
    } catch (saveError) {
      console.error(
        "[ChatSyncService:AppSettings] Error saving auto-rejected response message:",
        saveError,
      );
    }
  }

  // Remove from pending requests
  removePendingPermissionRequest(request_id);

  // Dispatch event to dismiss the Permission Dialog UI
  // The dialog component should listen for this and close itself
  if (typeof window !== "undefined") {
    window.dispatchEvent(
      new CustomEvent("dismissAppSettingsMemoriesPermissionDialog", {
        detail: {
          requestId: request_id,
          chatId: chat_id,
          reason: reason,
          messageId: message_id,
        },
      }),
    );
    console.info(
      `[ChatSyncService:AppSettings] Dispatched dismissAppSettingsMemoriesPermissionDialog event for request ${request_id}`,
    );
  }

  // Show a brief notification to user explaining what happened
  // This only shows for server-initiated dismisses (e.g., from another device)
  notificationStore.addNotification(
    "info",
    "Previous data request was cancelled because you sent a new message",
    4000,
  );
}

/**
 * Payload structure for new_system_message WebSocket broadcast
 * Sent by server when a system message is added from another device
 */
interface NewSystemMessagePayload {
  event: string;
  chat_id: string;
  data: {
    message_id: string;
    role: "system";
    encrypted_content: string; // Encrypted with chat key (zero-knowledge)
    created_at: number;
  };
  versions: {
    messages_v: number;
  };
}

/**
 * Handles new system messages broadcast from other devices.
 *
 * When another device creates a system message (like app settings/memories response):
 * 1. Server broadcasts the encrypted message to all other logged-in devices
 * 2. This handler receives the message and stores it in IndexedDB
 * 3. Dispatches event to notify UI components to refresh
 *
 * **Zero-Knowledge Architecture**: Message content is encrypted with chat key.
 * Server stores but cannot decrypt. Decryption happens client-side on-demand.
 */
export async function handleNewSystemMessageImpl(
  serviceInstance: ChatSynchronizationService,
  payload: NewSystemMessagePayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'new_system_message' from another device:",
    {
      chat_id: payload.chat_id,
      message_id: payload.data?.message_id,
      messages_v: payload.versions?.messages_v,
    },
  );

  const { chat_id, data, versions } = payload;

  if (!chat_id || !data || !data.message_id || !data.encrypted_content) {
    console.warn(
      "[ChatSyncService:AppSettings] Invalid new_system_message payload:",
      payload,
    );
    return;
  }

  try {
    // Check if chat exists locally
    const chat = await chatDB.getChat(chat_id);
    if (!chat) {
      console.warn(
        `[ChatSyncService:AppSettings] Chat ${chat_id} not found locally, skipping system message sync`,
      );
      return;
    }

    // Create message object for IndexedDB
    // Content is encrypted with chat key - will be decrypted when loaded
    const systemMessage = {
      message_id: data.message_id,
      chat_id: chat_id,
      role: "system" as const,
      encrypted_content: data.encrypted_content,
      created_at: data.created_at,
      status: "synced" as const,
    };

    // Save to IndexedDB
    await chatDB.saveMessage(systemMessage);
    console.debug(
      `[ChatSyncService:AppSettings] Saved system message ${data.message_id} from other device`,
    );

    // Update chat's messages_v version counter
    if (versions?.messages_v !== undefined) {
      await chatDB.updateChatComponentVersion(
        chat_id,
        "messages_v",
        versions.messages_v,
      );
      console.debug(
        `[ChatSyncService:AppSettings] Updated chat ${chat_id} messages_v to ${versions.messages_v}`,
      );
    }

    // Dispatch chatUpdated event to trigger UI refresh
    // ActiveChat listens for 'chatUpdated' with newMessage to update the chat history
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chat_id,
          type: "system_message_synced",
          messagesUpdated: true,
        },
      }),
    );
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error handling new_system_message:",
      error,
    );
  }
}

/**
 * Payload structure for system_message_confirmed WebSocket message
 * Sent by server when a system message is successfully persisted
 */
interface SystemMessageConfirmedPayload {
  chat_id: string;
  message_id: string;
  messages_v: number;
}

/**
 * Handles confirmation that a system message was successfully persisted.
 *
 * This is called when the server confirms that a system message (like app settings/memories response)
 * has been stored in Directus. The handler:
 * 1. Updates the message status from 'sending' to 'synced' (if needed)
 * 2. Updates the chat's messages_v version counter
 * 3. Dispatches event to update UI
 */
export async function handleSystemMessageConfirmedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: SystemMessageConfirmedPayload,
): Promise<void> {
  console.info(
    "[ChatSyncService:AppSettings] Received 'system_message_confirmed':",
    payload,
  );

  const { chat_id, message_id, messages_v } = payload;

  if (!chat_id || !message_id) {
    console.warn(
      "[ChatSyncService:AppSettings] Invalid system_message_confirmed payload:",
      payload,
    );
    return;
  }

  try {
    // Update message status to synced (if it's still 'sending')
    const message = await chatDB.getMessage(message_id);
    if (message && message.status === "sending") {
      const syncedMessage = { ...message, status: "synced" as const };
      await chatDB.saveMessage(syncedMessage);
      console.debug(
        `[ChatSyncService:AppSettings] Updated system message ${message_id} status to 'synced'`,
      );
    }

    // Update the chat's messages_v version counter
    if (messages_v !== undefined) {
      await chatDB.updateChatComponentVersion(
        chat_id,
        "messages_v",
        messages_v,
      );
      console.debug(
        `[ChatSyncService:AppSettings] Updated chat ${chat_id} messages_v to ${messages_v}`,
      );
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:AppSettings] Error handling system_message_confirmed:",
      error,
    );
  }
}

/**
 * Payload structure for pending_ai_response WebSocket message.
 *
 * Sent by the backend pending delivery system when the user reconnects
 * after an AI response completed while they were offline. Contains
 * PLAINTEXT content that the client must encrypt with the chat key
 * before persisting (zero-knowledge architecture).
 */
interface PendingAIResponsePayload {
  type: "ai_response";
  chat_id: string;
  message_id: string; // AI task ID / message ID (for deduplication)
  content: string; // PLAINTEXT AI response content (full_content_so_far)
  user_id: string; // User's UUID
  fired_at: number; // Unix timestamp when the AI response was generated
  model_name?: string; // AI model name used for the response (for encryption and display)
  category?: string; // Mate category of the response (for encryption and display)
}

/**
 * Handles the pending_ai_response WebSocket event when an AI response that completed
 * while the user was offline is delivered on reconnect.
 *
 * ARCHITECTURE (Zero-Knowledge Pending Delivery):
 * The backend queued the AI response plaintext in the pending delivery cache (60-day TTL).
 * On reconnect, the WebSocket endpoint sends it as a pending_ai_response event.
 * This handler is responsible for:
 * 1. Deduplicating by message_id (response may already have arrived via normal flow)
 * 2. Looking up the chat and chat key
 * 3. Creating an assistant message in IndexedDB
 * 4. Encrypting and sending back to server via sendCompletedAIResponse
 * 5. Dispatching UI events so the chat shows the response
 */
export async function handlePendingAIResponseImpl(
  serviceInstance: ChatSynchronizationService,
  payload: PendingAIResponsePayload,
): Promise<void> {
  console.info("[ChatSyncService:PendingAI] Received 'pending_ai_response':", {
    chat_id: payload.chat_id,
    message_id: payload.message_id,
    content_length: payload.content?.length || 0,
    fired_at: payload.fired_at,
  });

  const { chat_id, message_id, content } = payload;

  if (!chat_id || !message_id || !content) {
    console.warn(
      "[ChatSyncService:PendingAI] Invalid pending_ai_response payload:",
      payload,
    );
    return;
  }

  try {
    // Deduplicate: if this message already exists locally (e.g., the response
    // was already delivered via normal streaming or background completion), skip it.
    const existingMessage = await chatDB.getMessage(message_id);
    if (existingMessage) {
      console.debug(
        `[ChatSyncService:PendingAI] Message ${message_id} already exists locally, skipping duplicate`,
      );
      return;
    }

    // Look up the chat - it must exist locally for us to encrypt with its key
    const chat = await chatDB.getChat(chat_id);
    if (!chat) {
      console.warn(
        `[ChatSyncService:PendingAI] Chat ${chat_id} not found locally for pending AI response. ` +
          `Message will be picked up on next full sync.`,
      );
      return;
    }

    // Get the chat key for encryption
    const chatKey = chatDB.getChatKey(chat_id);
    if (!chatKey) {
      console.error(
        `[ChatSyncService:PendingAI] No chat key available for chat ${chat_id}, cannot encrypt pending AI response`,
      );
      return;
    }

    // Skip error responses - they shouldn't be persisted
    if (content.includes("[ERROR") || content === "chat.an_error_occured") {
      console.debug(
        `[ChatSyncService:PendingAI] Skipping error response for message ${message_id}`,
      );
      return;
    }

    // Create the assistant message
    // Store as markdown string (same as handleAIBackgroundResponseCompletedImpl)
    // Include model_name and category so they get encrypted by chatDB.saveMessage
    // and sent back to server via sendCompletedAIResponse for proper display
    const now = Math.floor(Date.now() / 1000);
    const aiMessage = {
      message_id: message_id,
      chat_id: chat_id,
      role: "assistant" as const,
      content: content, // Store as markdown string
      status: "synced" as const,
      created_at: payload.fired_at || now,
      encrypted_content: "", // Will be set by encryption in chatDB.saveMessage
      // Include model_name and category if available from the pending delivery payload.
      // These are needed for proper mate icon display and model badge rendering.
      // When encrypted by chatDB.saveMessage, they become encrypted_model_name and encrypted_category.
      model_name: payload.model_name || undefined,
      category: payload.category || undefined,
    };

    // Save to IndexedDB (chatDB handles encryption with chat key)
    await chatDB.saveMessage(aiMessage);
    console.info(
      `[ChatSyncService:PendingAI] Saved pending AI response ${message_id} to IndexedDB for chat ${chat_id}`,
    );

    // Update chat metadata with new messages_v
    const newMessagesV = (chat.messages_v || 0) + 1;
    const newLastEdited = Math.floor(Date.now() / 1000);
    const updatedChat = {
      ...chat,
      messages_v: newMessagesV,
      last_edited_overall_timestamp: newLastEdited,
    };
    await chatDB.updateChat(updatedChat as import("../types/chat").Chat);
    console.info(
      `[ChatSyncService:PendingAI] Updated chat ${chat_id} metadata: messages_v=${newMessagesV}`,
    );

    // Dispatch chatUpdated event to trigger UI refresh
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chat_id,
          chat: updatedChat,
          newMessage: aiMessage,
          type: "pending_ai_response",
          messagesUpdated: true,
        },
      }),
    );

    // Send encrypted AI response back to server for Directus storage (zero-knowledge)
    try {
      console.debug(
        "[ChatSyncService:PendingAI] Sending encrypted pending AI response to server:",
        {
          messageId: aiMessage.message_id,
          chatId: aiMessage.chat_id,
          contentLength: aiMessage.content?.length || 0,
        },
      );
      await serviceInstance.sendCompletedAIResponse(
        aiMessage as import("../types/chat").Message,
      );
      console.info(
        `[ChatSyncService:PendingAI] Sent encrypted AI response ${message_id} to server for Directus storage`,
      );
    } catch (sendError) {
      console.error(
        "[ChatSyncService:PendingAI] Error sending encrypted AI response to server:",
        sendError,
      );
      // Message is saved locally, will be synced on next sendCompletedAIResponse attempt
    }
  } catch (error) {
    console.error(
      "[ChatSyncService:PendingAI] Error handling pending_ai_response:",
      error,
    );
  }
}

/**
 * Payload structure for reminder_fired WebSocket message.
 *
 * Sent by the backend Celery task when a scheduled reminder becomes due.
 * Contains PLAINTEXT content that the client must encrypt with the chat key
 * before persisting (zero-knowledge architecture).
 */
interface ReminderFiredPayload {
  reminder_id: string;
  chat_id: string;
  message_id: string;
  target_type: "new_chat" | "existing_chat";
  is_repeating: boolean;
  content: string; // PLAINTEXT reminder content
  chat_title?: string; // For new_chat target
  user_id: string; // User's UUID (used for WebSocket routing)
}

/**
 * Handles the reminder_fired WebSocket event when a scheduled reminder fires.
 *
 * ARCHITECTURE (Zero-Knowledge Reminder Delivery):
 * The backend Celery task sends the PLAINTEXT reminder content via WebSocket.
 * This handler is responsible for:
 * 1. Encrypting the content with the chat key (zero-knowledge)
 * 2. Creating a system message in IndexedDB
 * 3. Sending the encrypted message back to the server via chat_system_message_added
 * 4. Dispatching events so the UI shows the system message
 * 5. Dispatching a reminderFiredInChat event to trigger an AI follow-up response
 *
 * This ensures the server never stores messages encrypted with the wrong key
 * (vault key vs chat key mismatch that causes "Content decryption failed").
 */
export async function handleReminderFiredImpl(
  serviceInstance: ChatSynchronizationService,
  payload: ReminderFiredPayload,
): Promise<void> {
  console.info("[ChatSyncService:Reminder] Received 'reminder_fired':", {
    reminder_id: payload.reminder_id,
    chat_id: payload.chat_id,
    target_type: payload.target_type,
    is_repeating: payload.is_repeating,
  });

  const { chat_id, message_id, content, target_type, chat_title } = payload;

  if (!chat_id || !message_id || !content) {
    console.warn(
      "[ChatSyncService:Reminder] Invalid reminder_fired payload:",
      payload,
    );
    return;
  }

  try {
    // Deduplicate: if this message already exists locally (e.g., the user received it
    // via real-time WebSocket AND again via pending delivery on reconnect), skip it.
    const existingMessage = await chatDB.getMessage(message_id);
    if (existingMessage) {
      console.debug(
        `[ChatSyncService:Reminder] Message ${message_id} already exists locally, skipping duplicate`,
      );
      return;
    }
    const { encryptWithChatKey } = await import("./cryptoService");
    const { webSocketService } = await import("./websocketService");

    // For existing_chat: chat must exist locally with a chat key
    // For new_chat: we need to create the chat locally first
    let chatKey: Uint8Array | null = null;

    if (target_type === "existing_chat") {
      // Chat should already exist locally
      const chat = await chatDB.getChat(chat_id);
      if (!chat) {
        console.warn(
          `[ChatSyncService:Reminder] Chat ${chat_id} not found locally for existing_chat reminder. ` +
            `Message will be picked up on next sync.`,
        );
        return;
      }
      chatKey = chatDB.getChatKey(chat_id);
    } else {
      // new_chat: Create the chat locally first
      // Generate a new chat key for this chat
      const { generateChatKey } = await import("./cryptoService");
      chatKey = generateChatKey();

      if (!chatKey) {
        console.error(
          "[ChatSyncService:Reminder] Failed to generate chat key for new reminder chat",
        );
        return;
      }

      // Store the chat key
      chatDB.setChatKey(chat_id, chatKey);

      const now = Math.floor(Date.now() / 1000);

      // Encrypt the title with the new chat key
      const titleText = chat_title || "Reminder";
      const encryptedTitle = await encryptWithChatKey(titleText, chatKey);

      const newChat = {
        chat_id: chat_id,
        title: titleText, // Plaintext for local display
        encrypted_title: encryptedTitle,
        created_at: now,
        updated_at: now,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: now,
        unread_count: 1,
      };

      await chatDB.updateChat(newChat as import("../types/chat").Chat);
      console.info(
        `[ChatSyncService:Reminder] Created new local chat ${chat_id} for reminder`,
      );
    }

    if (!chatKey) {
      console.error(
        `[ChatSyncService:Reminder] No chat key available for chat ${chat_id}, cannot encrypt reminder`,
      );
      return;
    }

    // Encrypt the reminder content with the chat key (zero-knowledge)
    const encryptedContent = await encryptWithChatKey(content, chatKey);
    if (!encryptedContent) {
      console.error(
        "[ChatSyncService:Reminder] Failed to encrypt reminder content",
      );
      return;
    }

    // Create the system message
    const now = Math.floor(Date.now() / 1000);
    const systemMessage = {
      message_id: message_id,
      chat_id: chat_id,
      role: "system" as const,
      content: content, // Plaintext for local display
      created_at: now,
      status: "sending" as const,
      encrypted_content: encryptedContent,
    };

    // Save to IndexedDB
    await chatDB.saveMessage(systemMessage);
    console.debug(
      `[ChatSyncService:Reminder] Saved reminder system message ${message_id} to IndexedDB`,
    );

    // Send encrypted content to server for persistence via existing system message flow
    const serverPayload = {
      chat_id: chat_id,
      message: {
        message_id: message_id,
        role: "system",
        encrypted_content: encryptedContent,
        created_at: now,
      },
    };

    try {
      await webSocketService.sendMessage(
        "chat_system_message_added",
        serverPayload,
      );

      // Update status to synced
      const syncedMessage = { ...systemMessage, status: "synced" as const };
      await chatDB.saveMessage(syncedMessage);
      console.debug(
        `[ChatSyncService:Reminder] Sent reminder system message ${message_id} to server for persistence`,
      );
    } catch (sendError) {
      console.error(
        "[ChatSyncService:Reminder] Error sending reminder message to server:",
        sendError,
      );
      // Message is saved locally, will be synced later
    }

    // Dispatch chatUpdated event to trigger UI refresh
    // This makes the system message appear in the chat immediately
    serviceInstance.dispatchEvent(
      new CustomEvent("chatUpdated", {
        detail: {
          chat_id: chat_id,
          type: "reminder_system_message_added",
          newMessage: systemMessage,
          messagesUpdated: true,
        },
      }),
    );

    // Dispatch reminderFiredInChat event so ActiveChat can trigger an AI follow-up
    // The AI should acknowledge the reminder and help the user with the task
    serviceInstance.dispatchEvent(
      new CustomEvent("reminderFiredInChat", {
        detail: {
          chat_id: chat_id,
          message_id: message_id,
          content: content,
          target_type: target_type,
        },
      }),
    );

    // Show in-app notification for the reminder
    // This ensures the user sees a toast notification even if they're in a different chat
    const notificationTitle = chat_title || "Reminder";
    // Extract the prompt from the reminder message content (strip the markdown formatting)
    const promptMatch = content.match(/\*\*Reminder\*\*\n\n([\s\S]*?)\n\n---/);
    const notificationPreview = promptMatch
      ? promptMatch[1].substring(0, 100)
      : "Your reminder has triggered";
    notificationStore.chatMessage(
      chat_id,
      notificationTitle,
      notificationPreview,
      undefined,
    );

    console.info(
      `[ChatSyncService:Reminder] Processed reminder for chat ${chat_id} (${target_type})`,
    );
  } catch (error) {
    console.error(
      "[ChatSyncService:Reminder] Error handling reminder_fired:",
      error,
    );
  }
}
