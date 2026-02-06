// frontend/packages/ui/src/services/chatSyncService.ts
// Handles chat data synchronization between client and server via WebSockets.
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { websocketStatus } from "../stores/websocketStatusStore";
import { notificationStore } from "../stores/notificationStore";
import type {
  OfflineChange,
  Message,
  AITaskInitiatedPayload,
  AIMessageUpdatePayload,
  AIBackgroundResponseCompletedPayload,
  AITypingStartedPayload,
  AIMessageReadyPayload,
  AITaskCancelRequestedPayload,
  ChatDraftUpdatedPayload,
  ChatMessageReceivedPayload,
  ChatMessageConfirmedPayload,
  ChatDeletedPayload,
  InitialSyncResponsePayload,
  Phase1LastChatPayload,
  CachePrimedPayload,
  CacheStatusResponsePayload,
  ChatContentBatchResponsePayload,
  OfflineSyncCompletePayload,
  // New phased sync types
  PhasedSyncRequestPayload,
  PhasedSyncCompletePayload,
  SyncStatusResponsePayload,
  Phase2RecentChatsPayload,
  Phase3FullSyncPayload,
  // Client to Server specific payloads (if not already covered or if preferred to list them all here)
  // UpdateTitlePayload, // Now in types/chat.ts
  // UpdateDraftPayload, // Now in types/chat.ts
  // SyncOfflineChangesPayload, // Now in types/chat.ts
  RequestChatContentBatchPayload, // Now in types/chat.ts
  // DeleteChatPayload, // Now in types/chat.ts
  // DeleteDraftPayload, // Now in types/chat.ts
  // SendChatMessagePayload, // Now in types/chat.ts
  RequestCacheStatusPayload, // Now in types/chat.ts
  // SetActiveChatPayload, // Now in types/chat.ts
  // CancelAITaskPayload // Now in types/chat.ts
  SendEmbedDataPayload,
  StoreEmbedPayload,
} from "../types/chat";
import * as aiHandlers from "./chatSyncServiceHandlersAI";
import * as chatUpdateHandlers from "./chatSyncServiceHandlersChatUpdates";
import * as coreSyncHandlers from "./chatSyncServiceHandlersCoreSync";
import * as phasedSyncHandlers from "./chatSyncServiceHandlersPhasedSync";
import * as senders from "./chatSyncServiceSenders";

// All payload interface definitions are now expected to be in types/chat.ts

export class ChatSynchronizationService extends EventTarget {
  private isSyncing = false;
  private serverChatOrder: string[] = [];
  private webSocketConnected = false;
  private cachePrimed = false;
  private initialSyncAttempted = false;
  private cacheStatusRequestTimeout: NodeJS.Timeout | null = null;
  private readonly CACHE_STATUS_REQUEST_DELAY = 0; // INSTANT - cache is pre-warmed during /lookup
  public activeAITasks: Map<string, { taskId: string; userMessageId: string }> =
    new Map(); // Made public for handlers
  private syncingMessageIds: Set<string> = new Set(); // Track message IDs being sent to server to prevent duplicates

  // CRITICAL: Sync timeout mechanism to prevent UI from being stuck in "Loading chats..." state
  // This handles cases where the server never sends phased_sync_complete or events are missed
  private phasedSyncTimeout: NodeJS.Timeout | null = null;
  private readonly PHASED_SYNC_TIMEOUT_MS = 30000; // 30 seconds timeout for phased sync
  private syncCompletedViaTimeout = false; // Track if completion was via timeout (for debugging)

  constructor() {
    super();
    this.registerWebSocketHandlers();

    // Listen for handlers being cleared (e.g., during logout)
    // and reset the registration flag so they can be re-registered on next login
    webSocketService.addEventListener("handlers_cleared", () => {
      console.info(
        "[ChatSyncService] WebSocket handlers were cleared. Resetting registration flag.",
      );
      this.handlersRegistered = false;
    });

    websocketStatus.subscribe((storeState) => {
      this.webSocketConnected = storeState.status === "connected";
      if (this.webSocketConnected) {
        console.info("[ChatSyncService] WebSocket connected.");

        // CRITICAL: Re-register handlers on connection if they were cleared
        // This ensures sync works correctly after login without requiring a page reload
        this.registerWebSocketHandlers();

        // Dispatch event for components that need to know when WebSocket is ready
        this.dispatchEvent(new CustomEvent("webSocketConnected"));

        // Stop periodic retry since we're now connected
        this.stopPendingMessageRetry();

        // CRITICAL: Retry sending pending messages when connection is restored
        // This handles messages that were created while offline
        this.retryPendingMessages().catch((error) => {
          console.error(
            "[ChatSyncService] Error retrying pending messages:",
            error,
          );
        });

        if (this.cacheStatusRequestTimeout) {
          clearTimeout(this.cacheStatusRequestTimeout);
          this.cacheStatusRequestTimeout = null;
        }
        if (this.cachePrimed) {
          this.attemptInitialSync();
        } else {
          this.cacheStatusRequestTimeout = setTimeout(() => {
            if (!this.cachePrimed && this.webSocketConnected) {
              this.requestCacheStatus();
            }
          }, this.CACHE_STATUS_REQUEST_DELAY);
        }
      } else {
        console.debug(
          "[ChatSyncService] WebSocket disconnected or error. Resetting sync state.",
        );
        this.cachePrimed = false;
        this.isSyncing = false;
        this.initialSyncAttempted = false;
        if (this.cacheStatusRequestTimeout) {
          clearTimeout(this.cacheStatusRequestTimeout);
          this.cacheStatusRequestTimeout = null;
        }

        // CRITICAL: Clear the phased sync timeout on disconnect to prevent stale timeouts
        // A new timeout will be started when connection is restored and sync starts again
        this.clearPhasedSyncTimeout();

        // Start periodic retry for pending messages when connection is lost
        // This ensures messages are automatically retried every few seconds
        this.startPendingMessageRetry();
      }
    });
  }

  private handlersRegistered = false; // Prevent duplicate registration

  private registerWebSocketHandlers() {
    // CRITICAL FIX: Prevent duplicate handler registration
    // This can happen due to HMR (Hot Module Reload) during development
    // or multiple instances being created accidentally
    if (this.handlersRegistered) {
      console.warn(
        "[ChatSyncService] Handlers already registered, skipping duplicate registration",
      );
      return;
    }

    this.handlersRegistered = true;

    webSocketService.on("initial_sync_response", (payload) =>
      coreSyncHandlers.handleInitialSyncResponseImpl(
        this,
        payload as InitialSyncResponsePayload,
      ),
    );
    webSocketService.on("initial_sync_error", (payload) =>
      coreSyncHandlers.handleInitialSyncErrorImpl(
        this,
        payload as { message: string },
      ),
    );
    webSocketService.on("phase_1_last_chat_ready", (payload) =>
      coreSyncHandlers.handlePhase1LastChatImpl(
        this,
        payload as Phase1LastChatPayload,
      ),
    );
    webSocketService.on("cache_primed", (payload) =>
      coreSyncHandlers.handleCachePrimedImpl(
        this,
        payload as CachePrimedPayload,
      ),
    );
    webSocketService.on("cache_status_response", (payload) =>
      coreSyncHandlers.handleCacheStatusResponseImpl(
        this,
        payload as CacheStatusResponsePayload,
      ),
    );

    // New phased sync event handlers (delegated to chatSyncServiceHandlersPhasedSync.ts)
    webSocketService.on("phase_2_last_20_chats_ready", (payload) =>
      phasedSyncHandlers.handlePhase2RecentChatsImpl(
        this,
        payload as Phase2RecentChatsPayload,
      ),
    );
    webSocketService.on("phase_3_last_100_chats_ready", (payload) =>
      phasedSyncHandlers.handlePhase3FullSyncImpl(
        this,
        payload as Phase3FullSyncPayload,
      ),
    );
    webSocketService.on("phased_sync_complete", (payload) =>
      phasedSyncHandlers.handlePhasedSyncCompleteImpl(
        this,
        payload as PhasedSyncCompletePayload,
      ),
    );
    webSocketService.on("sync_status_response", (payload) =>
      phasedSyncHandlers.handleSyncStatusResponseImpl(
        this,
        payload as SyncStatusResponsePayload,
      ),
    );
    // chat_title_updated removed - titles now handled via ai_typing_started in dual-phase architecture
    webSocketService.on("chat_draft_updated", (payload) =>
      chatUpdateHandlers.handleChatDraftUpdatedImpl(
        this,
        payload as ChatDraftUpdatedPayload,
      ),
    );
    // Handle draft deletion broadcasts from other devices
    webSocketService.on("draft_deleted", (payload) =>
      chatUpdateHandlers.handleDraftDeletedImpl(
        this,
        payload as { chat_id: string },
      ),
    );
    webSocketService.on("new_chat_message", (payload) =>
      chatUpdateHandlers.handleNewChatMessageImpl(this, payload),
    ); // Handler for new chat messages from other devices
    webSocketService.on("chat_message_added", (payload) =>
      chatUpdateHandlers.handleChatMessageReceivedImpl(
        this,
        payload as ChatMessageReceivedPayload,
      ),
    );
    webSocketService.on("chat_message_confirmed", (payload) =>
      chatUpdateHandlers.handleChatMessageConfirmedImpl(
        this,
        payload as ChatMessageConfirmedPayload,
      ),
    );
    webSocketService.on("chat_deleted", (payload) =>
      chatUpdateHandlers.handleChatDeletedImpl(
        this,
        payload as ChatDeletedPayload,
      ),
    );
    // Handle encrypted_chat_metadata updates (e.g., when chat is hidden/unhidden on another device)
    webSocketService.on("encrypted_chat_metadata", (payload) =>
      chatUpdateHandlers.handleEncryptedChatMetadataImpl(
        this,
        payload as {
          chat_id: string;
          encrypted_chat_key?: string;
          versions?: {
            messages_v?: number;
            title_v?: number;
            draft_v?: number;
          };
        },
      ),
    );
    // Note: chat_metadata_for_encryption handler removed - using ai_typing_started for dual-phase architecture
    webSocketService.on("offline_sync_complete", (payload) =>
      coreSyncHandlers.handleOfflineSyncCompleteImpl(
        this,
        payload as OfflineSyncCompletePayload,
      ),
    );
    webSocketService.on("chat_content_batch_response", (payload) =>
      coreSyncHandlers.handleChatContentBatchResponseImpl(
        this,
        payload as ChatContentBatchResponsePayload,
      ),
    );

    webSocketService.on("ai_message_update", (payload) =>
      aiHandlers.handleAIMessageUpdateImpl(
        this,
        payload as AIMessageUpdatePayload,
      ),
    );
    webSocketService.on("ai_background_response_completed", (payload) =>
      aiHandlers.handleAIBackgroundResponseCompletedImpl(
        this,
        payload as AIBackgroundResponseCompletedPayload,
      ),
    );
    webSocketService.on("ai_typing_started", (payload) =>
      aiHandlers.handleAITypingStartedImpl(
        this,
        payload as AITypingStartedPayload,
      ),
    );
    webSocketService.on("ai_typing_ended", (payload) =>
      aiHandlers.handleAITypingEndedImpl(
        this,
        payload as { chat_id: string; message_id: string },
      ),
    );
    webSocketService.on("request_chat_history", (payload) =>
      aiHandlers.handleRequestChatHistoryImpl(
        this,
        payload as { chat_id: string; reason: string; message?: string },
      ),
    );
    webSocketService.on("embed_update", (payload) =>
      aiHandlers.handleEmbedUpdateImpl(
        this,
        payload as import("../types/chat").EmbedUpdatePayload,
      ),
    );
    webSocketService.on("send_embed_data", (payload) =>
      aiHandlers.handleSendEmbedDataImpl(this, payload as SendEmbedDataPayload),
    );

    // Thinking/Reasoning handlers for thinking models (Gemini, Anthropic Claude)
    webSocketService.on("thinking_chunk", (payload) =>
      aiHandlers.handleAIThinkingChunkImpl(
        this,
        payload as import("../types/chat").AIThinkingChunkPayload,
      ),
    );
    webSocketService.on("thinking_complete", (payload) =>
      aiHandlers.handleAIThinkingCompleteImpl(
        this,
        payload as import("../types/chat").AIThinkingCompletePayload,
      ),
    );

    // Import and register app settings/memories handlers
    import("./chatSyncServiceHandlersAppSettings").then((module) => {
      webSocketService.on("request_app_settings_memories", (payload) =>
        module.handleRequestAppSettingsMemoriesImpl(this, payload),
      );
      webSocketService.on("dismiss_app_settings_memories_dialog", (payload) =>
        module.handleDismissAppSettingsMemoriesDialogImpl(this, payload),
      );
      webSocketService.on("app_settings_memories_sync_ready", (payload) =>
        module.handleAppSettingsMemoriesSyncReadyImpl(this, payload),
      );
      webSocketService.on("app_settings_memories_entry_synced", (payload) =>
        module.handleAppSettingsMemoriesEntrySyncedImpl(this, payload),
      );
      webSocketService.on("app_settings_memories_entry_stored", (payload) =>
        module.handleAppSettingsMemoriesEntryStoredImpl(this, payload),
      );
      webSocketService.on("system_message_confirmed", (payload) =>
        module.handleSystemMessageConfirmedImpl(this, payload),
      );
      // Handle system messages broadcast from other devices (cross-device sync)
      webSocketService.on("new_system_message", (payload) =>
        module.handleNewSystemMessageImpl(this, payload),
      );
      // Handle reminder fired events from server (scheduled reminder became due)
      // The server sends plaintext content; this handler encrypts with chat key and persists
      webSocketService.on("reminder_fired", (payload) =>
        module.handleReminderFiredImpl(this, payload),
      );
    });
    webSocketService.on("ai_message_ready", (payload) =>
      aiHandlers
        .handleAIMessageReadyImpl(this, payload as AIMessageReadyPayload)
        .catch((e) =>
          console.error(
            "[ChatSyncService] Error in handleAIMessageReadyImpl:",
            e,
          ),
        ),
    );
    webSocketService.on("ai_task_initiated", (payload) =>
      aiHandlers.handleAITaskInitiatedImpl(
        this,
        payload as AITaskInitiatedPayload,
      ),
    );
    webSocketService.on("ai_task_cancel_requested", (payload) =>
      aiHandlers.handleAITaskCancelRequestedImpl(
        this,
        payload as AITaskCancelRequestedPayload,
      ),
    );
    webSocketService.on("ai_response_storage_confirmed", (payload) =>
      aiHandlers.handleAIResponseStorageConfirmedImpl(
        this,
        payload as { chat_id: string; message_id: string; task_id?: string },
      ),
    );
    webSocketService.on("encrypted_metadata_stored", (payload) =>
      aiHandlers.handleEncryptedMetadataStoredImpl(
        this,
        payload as { chat_id: string; message_id: string; task_id?: string },
      ),
    );
    webSocketService.on("post_processing_completed", (payload) =>
      aiHandlers.handlePostProcessingCompletedImpl(
        this,
        payload as {
          chat_id: string;
          task_id: string;
          follow_up_request_suggestions: string[];
          new_chat_request_suggestions: string[];
          chat_summary: string;
          chat_tags: string[];
          harmful_response: number;
          top_recommended_apps_for_user?: string[];
          suggested_settings_memories?: import("../types/apps").SuggestedSettingsMemoryEntry[];
        },
      ),
    );
    webSocketService.on("post_processing_metadata_stored", (payload) =>
      aiHandlers.handlePostProcessingMetadataStoredImpl(
        this,
        payload as { chat_id: string; task_id?: string },
      ),
    );

    // Handler for settings/memory suggestion rejection broadcast from other devices
    // When user rejects a suggestion on one device, other devices receive this to update their local state
    webSocketService.on(
      "settings_memory_suggestion_rejected",
      async (payload) => {
        const { chat_id, rejection_hash } = payload as {
          chat_id: string;
          rejection_hash: string;
        };
        console.info(
          `[ChatSyncService] Received suggestion rejection broadcast for chat ${chat_id}`,
        );
        try {
          // Update local chat record with the new rejection hash
          const chat = await chatDB.getChat(chat_id);
          if (chat) {
            const existingHashes = chat.rejected_suggestion_hashes ?? [];
            if (!existingHashes.includes(rejection_hash)) {
              chat.rejected_suggestion_hashes = [
                ...existingHashes,
                rejection_hash,
              ];
              await chatDB.updateChat(chat);
              console.debug(
                `[ChatSyncService] Added rejection hash to chat ${chat_id} from other device`,
              );
              // Dispatch event so UI can update if needed
              this.dispatchEvent(
                new CustomEvent("suggestionRejected", {
                  detail: { chatId: chat_id, rejectionHash: rejection_hash },
                }),
              );
            }
          }
        } catch (error) {
          console.error(
            `[ChatSyncService] Error handling rejection broadcast for chat ${chat_id}:`,
            error,
          );
        }
      },
    );

    webSocketService.on("message_queued", (payload) =>
      aiHandlers.handleMessageQueuedImpl(
        this,
        payload as {
          chat_id: string;
          user_message_id: string;
          active_task_id: string;
          message: string;
        },
      ),
    );

    // Register skill preview service handlers (async import to avoid circular dependencies)
    import("./skillPreviewService")
      .then(({ skillPreviewService }) => {
        skillPreviewService.registerWebSocketHandlers();
      })
      .catch((err) => {
        console.warn(
          "[ChatSyncService] Failed to register skill preview service handlers:",
          err,
        );
      });
  }

  // --- Getters/Setters for handlers ---
  public get isSyncing_FOR_HANDLERS_ONLY(): boolean {
    return this.isSyncing;
  }
  public set isSyncing_FOR_HANDLERS_ONLY(value: boolean) {
    this.isSyncing = value;
  }
  public get cachePrimed_FOR_HANDLERS_ONLY(): boolean {
    return this.cachePrimed;
  }
  public set cachePrimed_FOR_HANDLERS_ONLY(value: boolean) {
    this.cachePrimed = value;
  }
  public get initialSyncAttempted_FOR_HANDLERS_ONLY(): boolean {
    return this.initialSyncAttempted;
  }
  public set initialSyncAttempted_FOR_HANDLERS_ONLY(value: boolean) {
    this.initialSyncAttempted = value;
  }
  public get serverChatOrder_FOR_HANDLERS_ONLY(): string[] {
    return this.serverChatOrder;
  }
  public set serverChatOrder_FOR_HANDLERS_ONLY(value: string[]) {
    this.serverChatOrder = value;
  }
  public get webSocketConnected_FOR_SENDERS_ONLY(): boolean {
    return this.webSocketConnected;
  }

  // --- Syncing Message IDs Tracking ---
  public isMessageSyncing(messageId: string): boolean {
    return this.syncingMessageIds.has(messageId);
  }

  public markMessageSyncing(messageId: string): void {
    this.syncingMessageIds.add(messageId);
  }

  public unmarkMessageSyncing(messageId: string): void {
    this.syncingMessageIds.delete(messageId);
  }

  // --- Core Sync Methods ---
  public attemptInitialSync_FOR_HANDLERS_ONLY(immediate_view_chat_id?: string) {
    this.attemptInitialSync(immediate_view_chat_id);
  }

  private attemptInitialSync(immediate_view_chat_id?: string) {
    console.log("[ChatSyncService] ⚡ attemptInitialSync called:", {
      isSyncing: this.isSyncing,
      initialSyncAttempted: this.initialSyncAttempted,
      webSocketConnected: this.webSocketConnected,
      cachePrimed: this.cachePrimed,
      immediate_view_chat_id,
    });

    if (this.isSyncing || this.initialSyncAttempted) {
      console.warn(
        "[ChatSyncService] ❌ Skipping sync - already in progress or attempted",
      );
      return;
    }

    if (this.webSocketConnected && this.cachePrimed) {
      console.info(
        "[ChatSyncService] ✅ Conditions met, starting phased sync NOW!",
      );
      // Use phased sync instead of old initial_sync for proper Phase 1/2/3 handling
      // This ensures new chat suggestions are synced and last opened chat loads via Phase 1
      this.initialSyncAttempted = true; // Mark as attempted
      this.startPhasedSync();
    } else {
      console.error("[ChatSyncService] ❌ Conditions NOT met for sync:", {
        webSocketConnected: this.webSocketConnected,
        cachePrimed: this.cachePrimed,
        needsWebSocket: !this.webSocketConnected,
        needsCachePrimed: !this.cachePrimed,
      });
    }
  }

  // Removed legacy initial sync. Phased sync is the only sync path.

  public requestChatContentBatch_FOR_HANDLERS_ONLY(
    chat_ids: string[],
  ): Promise<void> {
    return this.requestChatContentBatch(chat_ids);
  }

  private async requestChatContentBatch(chat_ids: string[]): Promise<void> {
    if (!this.webSocketConnected || chat_ids.length === 0) return;
    const payload: RequestChatContentBatchPayload = { chat_ids };
    try {
      await webSocketService.sendMessage("request_chat_content_batch", payload);
    } catch {
      notificationStore.error(
        "Failed to request additional chat messages from server.",
      );
    }
  }

  private async requestCacheStatus(): Promise<void> {
    if (!this.webSocketConnected) return;
    try {
      await webSocketService.sendMessage(
        "request_cache_status",
        {} as RequestCacheStatusPayload,
      );
    } catch (error) {
      console.error(
        "[ChatSyncService] Error sending 'request_cache_status':",
        error,
      );
    }
  }

  // --- AI Info Getters ---
  public getActiveAITaskIdForChat(chatId: string): string | null {
    return this.activeAITasks.get(chatId)?.taskId || null;
  }

  public getActiveAIUserMessageIdForChat(chatId: string): string | null {
    return this.activeAITasks.get(chatId)?.userMessageId || null;
  }

  // --- Senders (delegating to chatSyncServiceSenders.ts) ---
  public async sendUpdateTitle(chat_id: string, new_title: string) {
    await senders.sendUpdateTitleImpl(this, chat_id, new_title);
  }
  public async sendUpdateDraft(
    chat_id: string,
    draft_content: string | null,
    draft_preview?: string | null,
  ) {
    await senders.sendUpdateDraftImpl(
      this,
      chat_id,
      draft_content,
      draft_preview,
    );
  }
  public async sendUpdateEncryptedChatKey(
    chat_id: string,
    encrypted_chat_key: string,
  ) {
    await senders.sendUpdateChatKeyImpl(this, chat_id, encrypted_chat_key);
  }
  public async sendDeleteDraft(chat_id: string) {
    await senders.sendDeleteDraftImpl(this, chat_id);
  }
  public async sendDeleteChat(
    chat_id: string,
    embed_ids_to_delete: string[] = [],
  ) {
    await senders.sendDeleteChatImpl(this, chat_id, embed_ids_to_delete);
  }
  public async sendNewMessage(
    message: Message,
    encryptedSuggestionToDelete?: string | null,
  ): Promise<void> {
    await senders.sendNewMessageImpl(
      this,
      message,
      encryptedSuggestionToDelete,
    );
  }
  public async sendCompletedAIResponse(aiMessage: Message): Promise<void> {
    await senders.sendCompletedAIResponseImpl(this, aiMessage);
  }
  public async sendSetActiveChat(chatId: string | null): Promise<void> {
    await senders.sendSetActiveChatImpl(this, chatId);
  }
  public async sendCancelAiTask(
    taskId: string,
    chatId?: string,
  ): Promise<void> {
    await senders.sendCancelAiTaskImpl(this, taskId, chatId);
  }
  /**
   * Cancel a specific skill execution without stopping the entire AI response.
   * Use this when you want to skip a long-running skill but continue AI processing.
   *
   * @param skillTaskId - Unique ID for the skill invocation (from embed content)
   * @param embedId - Optional embed ID for logging purposes
   */
  public async sendCancelSkill(
    skillTaskId: string,
    embedId?: string,
  ): Promise<void> {
    await senders.sendCancelSkillImpl(this, skillTaskId, embedId);
  }
  public async sendStoreEmbed(payload: StoreEmbedPayload): Promise<void> {
    await senders.sendStoreEmbedImpl(this, payload);
  }
  public async sendDeleteNewChatSuggestion(
    encryptedSuggestion: string,
  ): Promise<void> {
    await senders.sendDeleteNewChatSuggestionImpl(this, encryptedSuggestion);
  }

  public async sendDeleteNewChatSuggestionById(
    suggestionId: string,
  ): Promise<void> {
    await senders.sendDeleteNewChatSuggestionByIdImpl(this, suggestionId);
  }
  /**
   * Sends an app settings/memories entry to server for permanent storage in Directus.
   *
   * This is used when creating entries from the App Store settings UI:
   * 1. Client encrypts entry with master key and stores in IndexedDB
   * 2. Client sends encrypted entry to server via this function
   * 3. Server stores encrypted entry in Directus (zero-knowledge)
   * 4. Server broadcasts to other logged-in devices for multi-device sync
   */
  public async sendStoreAppSettingsMemoriesEntry(entry: {
    id: string;
    app_id: string;
    item_key: string;
    item_type: string;
    encrypted_item_json: string;
    encrypted_app_key: string;
    created_at: number;
    updated_at: number;
    item_version: number;
    sequence_number?: number;
  }): Promise<boolean> {
    return await senders.sendStoreAppSettingsMemoriesEntryImpl(this, entry);
  }
  public async queueOfflineChange(
    change: Omit<OfflineChange, "change_id">,
  ): Promise<void> {
    // This one is tricky as it's called by senders. For now, keep it public or make senders pass `this` to it.
    // For simplicity, making it public for now.
    await senders.queueOfflineChangeImpl(this, change);
  }
  public async sendOfflineChanges(): Promise<void> {
    await senders.sendOfflineChangesImpl();
  }

  // Scroll position and read status sync methods
  public async sendScrollPositionUpdate(
    chat_id: string,
    message_id: string,
  ): Promise<void> {
    await senders.sendScrollPositionUpdateImpl(this, chat_id, message_id);
  }

  public async sendChatReadStatus(
    chat_id: string,
    unread_count: number,
  ): Promise<void> {
    await senders.sendChatReadStatusImpl(this, chat_id, unread_count);
  }

  // --- New Phased Sync Methods ---

  /**
   * Start the new 3-phase sync process with version-aware delta checking.
   * Sends client version data to avoid receiving data that's already up-to-date.
   *
   * CRITICAL: This method now includes a timeout mechanism to prevent the UI from
   * being stuck in "Loading chats..." state if the server never sends phased_sync_complete
   * or if events are missed due to timing issues.
   */
  public async startPhasedSync(): Promise<void> {
    if (!this.webSocketConnected) {
      console.warn(
        "[ChatSyncService] Cannot start phased sync - WebSocket not connected",
      );
      return;
    }

    try {
      console.log("[ChatSyncService] 1/4: Starting phased sync...");

      // CRITICAL: Start timeout for sync completion
      // If the server doesn't respond within the timeout, we'll mark sync as complete
      // to prevent the UI from being stuck forever in "Loading chats..." state
      this.startPhasedSyncTimeout();

      // Get client version data for delta checking
      const allChats = await chatDB.getAllChats();
      console.log(
        `[ChatSyncService] 2/4: Found ${allChats.length} chats locally in IndexedDB.`,
      );

      const client_chat_versions: Record<
        string,
        { messages_v: number; title_v: number; draft_v: number }
      > = {};
      const client_chat_ids: string[] = [];

      for (const chat of allChats) {
        client_chat_ids.push(chat.chat_id);
        client_chat_versions[chat.chat_id] = {
          messages_v: chat.messages_v || 0,
          title_v: chat.title_v || 0,
          draft_v: chat.draft_v || 0,
        };
      }

      // Get client suggestions count
      const clientSuggestions = await chatDB.getAllNewChatSuggestions();
      const client_suggestions_count = clientSuggestions.length;

      console.log(
        `[ChatSyncService] 3/4: Phased sync preparing request with client state: ${client_chat_ids.length} chats, ${client_suggestions_count} suggestions`,
      );

      const payload: PhasedSyncRequestPayload = {
        phase: "all",
        client_chat_versions,
        client_chat_ids,
        client_suggestions_count,
      };

      await webSocketService.sendMessage("phased_sync_request", payload);
      console.log(
        "[ChatSyncService] 4/4: ✅ Successfully sent 'phased_sync_request' to server.",
      );
    } catch (error) {
      console.error(
        "[ChatSyncService] ❌ CRITICAL: Error during startPhasedSync:",
        error,
      );
      notificationStore.error("Failed to start chat synchronization.");
      // Clear timeout on error and dispatch a synthetic complete event to unblock UI
      this.clearPhasedSyncTimeout();
      this.dispatchSyncTimeoutComplete("error");
    }
  }

  /**
   * Start the timeout timer for phased sync.
   * If the server doesn't respond with phased_sync_complete within the timeout,
   * we'll dispatch a synthetic completion event to prevent UI from being stuck.
   */
  private startPhasedSyncTimeout(): void {
    // Clear any existing timeout first
    this.clearPhasedSyncTimeout();

    console.debug(
      `[ChatSyncService] Starting phased sync timeout (${this.PHASED_SYNC_TIMEOUT_MS}ms)`,
    );

    this.phasedSyncTimeout = setTimeout(() => {
      console.warn(
        `[ChatSyncService] ⚠️ Phased sync timeout reached (${this.PHASED_SYNC_TIMEOUT_MS}ms) - dispatching synthetic completion event`,
      );
      this.syncCompletedViaTimeout = true;
      this.dispatchSyncTimeoutComplete("timeout");
    }, this.PHASED_SYNC_TIMEOUT_MS);
  }

  /**
   * Clear the phased sync timeout.
   * Should be called when sync completes successfully or when disconnecting.
   */
  public clearPhasedSyncTimeout(): void {
    if (this.phasedSyncTimeout) {
      clearTimeout(this.phasedSyncTimeout);
      this.phasedSyncTimeout = null;
      console.debug("[ChatSyncService] Cleared phased sync timeout");
    }
  }

  /**
   * Dispatch a synthetic phasedSyncComplete event when timeout is reached.
   * This ensures the UI doesn't stay stuck in "Loading chats..." state forever.
   *
   * @param reason - The reason for the synthetic completion ('timeout' or 'error')
   */
  private dispatchSyncTimeoutComplete(reason: "timeout" | "error"): void {
    console.info(
      `[ChatSyncService] Dispatching synthetic phasedSyncComplete event (reason: ${reason})`,
    );

    // Dispatch the event so +page.svelte and Chats.svelte can mark sync as complete
    this.dispatchEvent(
      new CustomEvent("phasedSyncComplete", {
        detail: {
          status: "completed_via_" + reason,
          synthetic: true,
          reason,
        },
      }),
    );
  }

  /**
   * Request current sync status from server
   */
  public async requestSyncStatus(): Promise<void> {
    if (!this.webSocketConnected) return;

    try {
      await webSocketService.sendMessage("sync_status_request", {});
    } catch (error) {
      console.error("[ChatSyncService] Error requesting sync status:", error);
    }
  }

  // NOTE: Phased sync handlers (handlePhase2RecentChats, handlePhase3FullSync, etc.)
  // and storage helpers (storeRecentChats, storeAllChats, etc.) are in chatSyncServiceHandlersPhasedSync.ts

  /**
   * Retry sending messages that are pending (status: 'waiting_for_internet' or 'sending')
   * This is called automatically when WebSocket connection is restored
   * Messages are retried every few seconds until successfully sent or connection is lost again
   */
  private async retryPendingMessages(): Promise<void> {
    if (!this.webSocketConnected) {
      console.debug(
        "[ChatSyncService] Skipping pending message retry - WebSocket not connected",
      );
      return;
    }

    try {
      console.info(
        "[ChatSyncService] Retrying pending messages after connection restored...",
      );

      // Get all messages from database
      const allMessages = await chatDB.getAllMessages();

      // Filter for messages that need to be retried
      const pendingMessages = allMessages.filter(
        (msg) =>
          msg.status === "waiting_for_internet" ||
          (msg.status === "sending" && msg.role === "user"),
      );

      if (pendingMessages.length === 0) {
        console.debug("[ChatSyncService] No pending messages to retry");
        return;
      }

      console.info(
        `[ChatSyncService] Found ${pendingMessages.length} pending message(s) to retry`,
      );

      // Update status to 'sending' and retry each message
      for (const message of pendingMessages) {
        try {
          // Update status to 'sending' before retry
          const updatedMessage: Message = { ...message, status: "sending" };
          await chatDB.saveMessage(updatedMessage);

          // Dispatch event to update UI
          this.dispatchEvent(
            new CustomEvent("messageStatusChanged", {
              detail: {
                chatId: message.chat_id,
                messageId: message.message_id,
                status: "sending",
              },
            }),
          );

          // Retry sending the message
          console.debug(
            `[ChatSyncService] Retrying message ${message.message_id} for chat ${message.chat_id}`,
          );
          await this.sendNewMessage(updatedMessage);
        } catch (error) {
          console.error(
            `[ChatSyncService] Error retrying message ${message.message_id}:`,
            error,
          );

          // Update status back to 'waiting_for_internet' if retry failed
          try {
            const failedMessage: Message = {
              ...message,
              status: "waiting_for_internet",
            };
            await chatDB.saveMessage(failedMessage);

            this.dispatchEvent(
              new CustomEvent("messageStatusChanged", {
                detail: {
                  chatId: message.chat_id,
                  messageId: message.message_id,
                  status: "waiting_for_internet",
                },
              }),
            );
          } catch (dbError) {
            console.error(
              `[ChatSyncService] Error updating message status after retry failure:`,
              dbError,
            );
          }
        }
      }

      console.info(
        `[ChatSyncService] Completed retry attempt for ${pendingMessages.length} pending message(s)`,
      );
    } catch (error) {
      console.error("[ChatSyncService] Error in retryPendingMessages:", error);
    }
  }

  /**
   * Start periodic retry of pending messages when offline
   * This ensures messages are automatically retried every few seconds
   * until connection is restored or message is successfully sent
   */
  private pendingMessageRetryInterval: NodeJS.Timeout | null = null;
  private readonly PENDING_MESSAGE_RETRY_INTERVAL = 5000; // Retry every 5 seconds

  private startPendingMessageRetry(): void {
    // Clear any existing interval
    if (this.pendingMessageRetryInterval) {
      clearInterval(this.pendingMessageRetryInterval);
    }

    // Only start retry if WebSocket is not connected
    if (this.webSocketConnected) {
      return; // Don't retry if already connected
    }

    console.debug(
      "[ChatSyncService] Starting periodic retry for pending messages",
    );

    this.pendingMessageRetryInterval = setInterval(async () => {
      // Check if connection was restored
      if (this.webSocketConnected) {
        // Stop periodic retry and do one final retry
        if (this.pendingMessageRetryInterval) {
          clearInterval(this.pendingMessageRetryInterval);
          this.pendingMessageRetryInterval = null;
        }
        await this.retryPendingMessages();
        return;
      }

      // If still offline, try to retry (will fail but keeps status updated)
      // This is mainly for UI updates - actual sending happens when connection is restored
      try {
        await this.retryPendingMessages();
      } catch (error) {
        // Expected to fail when offline, just log debug
        console.debug(
          "[ChatSyncService] Periodic retry failed (expected when offline):",
          error,
        );
      }
    }, this.PENDING_MESSAGE_RETRY_INTERVAL);
  }

  private stopPendingMessageRetry(): void {
    if (this.pendingMessageRetryInterval) {
      clearInterval(this.pendingMessageRetryInterval);
      this.pendingMessageRetryInterval = null;
      console.debug(
        "[ChatSyncService] Stopped periodic retry for pending messages",
      );
    }
  }
}

export const chatSyncService = new ChatSynchronizationService();
