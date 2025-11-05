// frontend/packages/ui/src/services/chatSyncService.ts
// Handles chat data synchronization between client and server via WebSockets.
import { chatDB } from './db';
import { userDB } from './userDB';
import { webSocketService } from './websocketService';
import { websocketStatus, type WebSocketStatus } from '../stores/websocketStatusStore';
import { notificationStore } from '../stores/notificationStore';
import type {
    ChatComponentVersions,
    OfflineChange,
    TiptapJSON,
    Message,
    Chat,
    AITaskInitiatedPayload,
    AIMessageUpdatePayload,
    AIBackgroundResponseCompletedPayload,
    AITypingStartedPayload,
    AIMessageReadyPayload,
    AITaskCancelRequestedPayload,
    ChatTitleUpdatedPayload,
    ChatDraftUpdatedPayload,
    ChatMessageReceivedPayload,
    ChatMessageConfirmedPayload,
    ChatDeletedPayload,
    InitialSyncRequestPayload,
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
} from '../types/chat';
import { aiTypingStore } from '../stores/aiTypingStore';
import { get } from 'svelte/store';
import * as aiHandlers from './chatSyncServiceHandlersAI';
import * as chatUpdateHandlers from './chatSyncServiceHandlersChatUpdates';
import * as coreSyncHandlers from './chatSyncServiceHandlersCoreSync';
import * as senders from './chatSyncServiceSenders';

// All payload interface definitions are now expected to be in types/chat.ts

export class ChatSynchronizationService extends EventTarget {
    private isSyncing = false;
    private serverChatOrder: string[] = [];
    private webSocketConnected = false;
    private cachePrimed = false;
    private initialSyncAttempted = false;
    private cacheStatusRequestTimeout: NodeJS.Timeout | null = null;
    private readonly CACHE_STATUS_REQUEST_DELAY = 0; // INSTANT - cache is pre-warmed during /lookup
    public activeAITasks: Map<string, { taskId: string, userMessageId: string }> = new Map(); // Made public for handlers

    constructor() {
        super();
        this.registerWebSocketHandlers();
        websocketStatus.subscribe(storeState => {
            this.webSocketConnected = storeState.status === 'connected';
            if (this.webSocketConnected) {
                console.info("[ChatSyncService] WebSocket connected.");
                
                // Dispatch event for components that need to know when WebSocket is ready
                this.dispatchEvent(new CustomEvent('webSocketConnected'));
                
                // Stop periodic retry since we're now connected
                this.stopPendingMessageRetry();
                
                // CRITICAL: Retry sending pending messages when connection is restored
                // This handles messages that were created while offline
                this.retryPendingMessages().catch(error => {
                    console.error("[ChatSyncService] Error retrying pending messages:", error);
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
                console.info("[ChatSyncService] WebSocket disconnected or error. Resetting sync state.");
                this.cachePrimed = false;
                this.isSyncing = false;
                this.initialSyncAttempted = false;
                if (this.cacheStatusRequestTimeout) {
                    clearTimeout(this.cacheStatusRequestTimeout);
                    this.cacheStatusRequestTimeout = null;
                }
                
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
            console.warn('[ChatSyncService] Handlers already registered, skipping duplicate registration');
            return;
        }
        
        this.handlersRegistered = true;
        
        webSocketService.on('initial_sync_response', (payload) => coreSyncHandlers.handleInitialSyncResponseImpl(this, payload as InitialSyncResponsePayload));
        webSocketService.on('initial_sync_error', (payload) => coreSyncHandlers.handleInitialSyncErrorImpl(this, payload as { message: string }));
        webSocketService.on('phase_1_last_chat_ready', (payload) => coreSyncHandlers.handlePhase1LastChatImpl(this, payload as Phase1LastChatPayload));
        webSocketService.on('cache_primed', (payload) => coreSyncHandlers.handleCachePrimedImpl(this, payload as CachePrimedPayload));
        webSocketService.on('cache_status_response', (payload) => coreSyncHandlers.handleCacheStatusResponseImpl(this, payload as CacheStatusResponsePayload));
        
        // New phased sync event handlers
        webSocketService.on('phase_2_last_20_chats_ready', (payload) => this.handlePhase2RecentChats(payload as Phase2RecentChatsPayload));
        webSocketService.on('phase_3_last_100_chats_ready', (payload) => this.handlePhase3FullSync(payload as Phase3FullSyncPayload));
        webSocketService.on('phased_sync_complete', (payload) => this.handlePhasedSyncComplete(payload as PhasedSyncCompletePayload));
        webSocketService.on('sync_status_response', (payload) => this.handleSyncStatusResponse(payload as SyncStatusResponsePayload)); 
        // chat_title_updated removed - titles now handled via ai_typing_started in dual-phase architecture
        webSocketService.on('chat_draft_updated', (payload) => chatUpdateHandlers.handleChatDraftUpdatedImpl(this, payload as ChatDraftUpdatedPayload));
        // Handle draft deletion broadcasts from other devices
        webSocketService.on('draft_deleted', (payload) => chatUpdateHandlers.handleDraftDeletedImpl(this, payload as { chat_id: string }));
        webSocketService.on('new_chat_message', (payload) => chatUpdateHandlers.handleNewChatMessageImpl(this, payload)); // Handler for new chat messages from other devices
        webSocketService.on('chat_message_added', (payload) => chatUpdateHandlers.handleChatMessageReceivedImpl(this, payload as ChatMessageReceivedPayload)); 
        webSocketService.on('chat_message_confirmed', (payload) => chatUpdateHandlers.handleChatMessageConfirmedImpl(this, payload as ChatMessageConfirmedPayload)); 
        webSocketService.on('chat_deleted', (payload) => chatUpdateHandlers.handleChatDeletedImpl(this, payload as ChatDeletedPayload));
        // Note: chat_metadata_for_encryption handler removed - using ai_typing_started for dual-phase architecture
        webSocketService.on('offline_sync_complete', (payload) => coreSyncHandlers.handleOfflineSyncCompleteImpl(this, payload as OfflineSyncCompletePayload));
        webSocketService.on('chat_content_batch_response', (payload) => coreSyncHandlers.handleChatContentBatchResponseImpl(this, payload as ChatContentBatchResponsePayload));

        webSocketService.on('ai_message_update', (payload) => aiHandlers.handleAIMessageUpdateImpl(this, payload as AIMessageUpdatePayload));
        webSocketService.on('ai_background_response_completed', (payload) => aiHandlers.handleAIBackgroundResponseCompletedImpl(this, payload as AIBackgroundResponseCompletedPayload));
        webSocketService.on('ai_typing_started', (payload) => aiHandlers.handleAITypingStartedImpl(this, payload as AITypingStartedPayload));
        webSocketService.on('ai_typing_ended', (payload) => aiHandlers.handleAITypingEndedImpl(this, payload as { chat_id: string, message_id: string }));
        webSocketService.on('request_chat_history', (payload) => aiHandlers.handleRequestChatHistoryImpl(this, payload as { chat_id: string; reason: string; message?: string }));
        webSocketService.on('ai_message_ready', (payload) => aiHandlers.handleAIMessageReadyImpl(this, payload as AIMessageReadyPayload));
        webSocketService.on('ai_task_initiated', (payload) => aiHandlers.handleAITaskInitiatedImpl(this, payload as AITaskInitiatedPayload));
        webSocketService.on('ai_task_cancel_requested', (payload) => aiHandlers.handleAITaskCancelRequestedImpl(this, payload as AITaskCancelRequestedPayload));
        webSocketService.on('ai_response_storage_confirmed', (payload) => aiHandlers.handleAIResponseStorageConfirmedImpl(this, payload as { chat_id: string; message_id: string; task_id?: string }));
        webSocketService.on('encrypted_metadata_stored', (payload) => aiHandlers.handleEncryptedMetadataStoredImpl(this, payload as { chat_id: string; message_id: string; task_id?: string }));
        webSocketService.on('post_processing_completed', (payload) => aiHandlers.handlePostProcessingCompletedImpl(this, payload as { chat_id: string; task_id: string; follow_up_request_suggestions: string[]; new_chat_request_suggestions: string[]; chat_summary: string; chat_tags: string[]; harmful_response: number }));
        webSocketService.on('post_processing_metadata_stored', (payload) => aiHandlers.handlePostProcessingMetadataStoredImpl(this, payload as { chat_id: string; task_id?: string }));
        webSocketService.on('message_queued', (payload) => aiHandlers.handleMessageQueuedImpl(this, payload as { chat_id: string; user_message_id: string; active_task_id: string; message: string }));
    }

    // --- Getters/Setters for handlers ---
    public get isSyncing_FOR_HANDLERS_ONLY(): boolean { return this.isSyncing; }
    public set isSyncing_FOR_HANDLERS_ONLY(value: boolean) { this.isSyncing = value; }
    public get cachePrimed_FOR_HANDLERS_ONLY(): boolean { return this.cachePrimed; }
    public set cachePrimed_FOR_HANDLERS_ONLY(value: boolean) { this.cachePrimed = value; }
    public get initialSyncAttempted_FOR_HANDLERS_ONLY(): boolean { return this.initialSyncAttempted; }
    public set initialSyncAttempted_FOR_HANDLERS_ONLY(value: boolean) { this.initialSyncAttempted = value; }
    public get serverChatOrder_FOR_HANDLERS_ONLY(): string[] { return this.serverChatOrder; }
    public set serverChatOrder_FOR_HANDLERS_ONLY(value: string[]) { this.serverChatOrder = value; }
    public get webSocketConnected_FOR_SENDERS_ONLY(): boolean { return this.webSocketConnected; }

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
            immediate_view_chat_id
        });
        
        if (this.isSyncing || this.initialSyncAttempted) {
            console.warn("[ChatSyncService] ❌ Skipping sync - already in progress or attempted");
            return;
        }
        
        if (this.webSocketConnected && this.cachePrimed) {
            console.info("[ChatSyncService] ✅ Conditions met, starting phased sync NOW!");
            // Use phased sync instead of old initial_sync for proper Phase 1/2/3 handling
            // This ensures new chat suggestions are synced and last opened chat loads via Phase 1
            this.initialSyncAttempted = true; // Mark as attempted
            this.startPhasedSync();
        } else {
            console.error("[ChatSyncService] ❌ Conditions NOT met for sync:", {
                webSocketConnected: this.webSocketConnected,
                cachePrimed: this.cachePrimed,
                needsWebSocket: !this.webSocketConnected,
                needsCachePrimed: !this.cachePrimed
            });
        }
    }

    // Removed legacy initial sync. Phased sync is the only sync path.
    
    public requestChatContentBatch_FOR_HANDLERS_ONLY(chat_ids: string[]): Promise<void> {
        return this.requestChatContentBatch(chat_ids);
    }

    private async requestChatContentBatch(chat_ids: string[]): Promise<void> {
        if (!this.webSocketConnected || chat_ids.length === 0) return;
        const payload: RequestChatContentBatchPayload = { chat_ids };
        try {
            await webSocketService.sendMessage('request_chat_content_batch', payload);
        } catch (error) {
            notificationStore.error("Failed to request additional chat messages from server.");
        }
    }

    private async requestCacheStatus(): Promise<void> {
        if (!this.webSocketConnected) return;
        try {
            await webSocketService.sendMessage('request_cache_status', {} as RequestCacheStatusPayload);
        } catch (error) {
            console.error("[ChatSyncService] Error sending 'request_cache_status':", error);
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
    public async sendUpdateDraft(chat_id: string, draft_content: string | null, draft_preview?: string | null) {
        await senders.sendUpdateDraftImpl(this, chat_id, draft_content, draft_preview);
    }
    public async sendDeleteDraft(chat_id: string) {
        await senders.sendDeleteDraftImpl(this, chat_id);
    }
    public async sendDeleteChat(chat_id: string) {
        await senders.sendDeleteChatImpl(this, chat_id);
    }
    public async sendNewMessage(message: Message, encryptedSuggestionToDelete?: string | null): Promise<void> {
        await senders.sendNewMessageImpl(this, message, encryptedSuggestionToDelete);
    }
    public async sendCompletedAIResponse(aiMessage: Message): Promise<void> {
        await senders.sendCompletedAIResponseImpl(this, aiMessage);
    }
    public async sendSetActiveChat(chatId: string | null): Promise<void> {
        await senders.sendSetActiveChatImpl(this, chatId);
    }
    public async sendCancelAiTask(taskId: string): Promise<void> {
        await senders.sendCancelAiTaskImpl(this, taskId);
    }
    public async queueOfflineChange(change: Omit<OfflineChange, 'change_id'>): Promise<void> {
        // This one is tricky as it's called by senders. For now, keep it public or make senders pass `this` to it.
        // For simplicity, making it public for now.
        await senders.queueOfflineChangeImpl(this, change);
    }
    public async sendOfflineChanges(): Promise<void> {
        await senders.sendOfflineChangesImpl(this);
    }

    // Scroll position and read status sync methods
    public async sendScrollPositionUpdate(chat_id: string, message_id: string): Promise<void> {
        await senders.sendScrollPositionUpdateImpl(this, chat_id, message_id);
    }

    public async sendChatReadStatus(chat_id: string, unread_count: number): Promise<void> {
        await senders.sendChatReadStatusImpl(this, chat_id, unread_count);
    }

    // --- New Phased Sync Methods ---
    
    /**
     * Start the new 3-phase sync process with version-aware delta checking.
     * Sends client version data to avoid receiving data that's already up-to-date.
     */
    public async startPhasedSync(): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] Cannot start phased sync - WebSocket not connected");
            return;
        }
        
        try {
            console.log("[ChatSyncService] 1/4: Starting phased sync...");
            
            // Get client version data for delta checking
            const allChats = await chatDB.getAllChats();
            console.log(`[ChatSyncService] 2/4: Found ${allChats.length} chats locally in IndexedDB.`);
            
            const client_chat_versions: Record<string, {messages_v: number, title_v: number, draft_v: number}> = {};
            const client_chat_ids: string[] = [];
            
            for (const chat of allChats) {
                client_chat_ids.push(chat.chat_id);
                client_chat_versions[chat.chat_id] = {
                    messages_v: chat.messages_v || 0,
                    title_v: chat.title_v || 0,
                    draft_v: chat.draft_v || 0
                };
            }
            
            // Get client suggestions count
            const clientSuggestions = await chatDB.getAllNewChatSuggestions();
            const client_suggestions_count = clientSuggestions.length;
            
            console.log(`[ChatSyncService] 3/4: Phased sync preparing request with client state: ${client_chat_ids.length} chats, ${client_suggestions_count} suggestions`);
            
            const payload: PhasedSyncRequestPayload = {
                phase: 'all',
                client_chat_versions,
                client_chat_ids,
                client_suggestions_count
            };
            
            await webSocketService.sendMessage('phased_sync_request', payload);
            console.log("[ChatSyncService] 4/4: ✅ Successfully sent 'phased_sync_request' to server.");
            
        } catch (error) {
            console.error("[ChatSyncService] ❌ CRITICAL: Error during startPhasedSync:", error);
            notificationStore.error("Failed to start chat synchronization.");
        }
    }

    /**
     * Request current sync status from server
     */
    public async requestSyncStatus(): Promise<void> {
        if (!this.webSocketConnected) return;
        
        try {
            await webSocketService.sendMessage('sync_status_request', {});
        } catch (error) {
            console.error("[ChatSyncService] Error requesting sync status:", error);
        }
    }

    /**
     * Handle Phase 2 completion (recent chats ready)
     *
     * NOTE: This handler receives TWO different payload formats:
     * 1. Cache warming notification: {chat_count: N} - Just metadata, no actual chat data
     * 2. Direct sync response: {chats: [...], chat_count: N, phase: 'phase2'} - Full chat data
     *
     * We must validate the payload and only process when actual chat data is present.
     */
    private async handlePhase2RecentChats(payload: Phase2RecentChatsPayload): Promise<void> {
        console.log("[ChatSyncService] Phase 2 complete - recent chats ready:", payload);

        try {
            const { chats, chat_count } = payload;

            // CRITICAL: Validate that chats array exists before processing
            // The cache warming task sends {chat_count: N} without chats array
            // The direct sync handler sends {chats: [...], chat_count: N, phase: 'phase2'}
            if (!chats || !Array.isArray(chats)) {
                console.debug("[ChatSyncService] Phase 2 notification received (cache warming), waiting for actual chat data...");
                return;
            }

            // Only process when we have actual chat data
            if (chats.length === 0) {
                console.debug("[ChatSyncService] Phase 2 received empty chats array, nothing to store");
                return;
            }

            // Store recent chats data
            await this.storeRecentChats(chats);

            // Dispatch event for UI components - use the correct event name that Chats.svelte listens for
            this.dispatchEvent(new CustomEvent('phase_2_last_20_chats_ready', {
                detail: { chat_count }
            }));

        } catch (error) {
            console.error("[ChatSyncService] Error handling Phase 2 completion:", error);
        }
    }

    /**
     * Handle Phase 3 completion (full sync ready)
     *
     * NOTE: This handler receives TWO different payload formats:
     * 1. Cache warming notification: {chat_count: N} - Just metadata, no actual chat data
     * 2. Direct sync response: {chats: [...], chat_count: N, phase: 'phase3'} - Full chat data
     *
     * We must validate the payload and only process when actual chat data is present.
     */
    private async handlePhase3FullSync(payload: Phase3FullSyncPayload): Promise<void> {
        console.log("[ChatSyncService] Phase 3 complete - full sync ready:", payload);

        try {
            const { chats, chat_count, new_chat_suggestions } = payload;

            // CRITICAL: Validate that chats array exists before processing
            // The cache warming task sends {chat_count: N} without chats array
            // The direct sync handler sends {chats: [...], chat_count: N, phase: 'phase3'}
            if (!chats || !Array.isArray(chats)) {
                console.debug("[ChatSyncService] Phase 3 notification received (cache warming), waiting for actual chat data...");
                return;
            }

            // Only process when we have actual chat data
            if (chats.length === 0) {
                console.debug("[ChatSyncService] Phase 3 received empty chats array, nothing to store");
                return;
            }

            // Store all chats data
            await this.storeAllChats(chats);

            // Store new chat suggestions if provided
            if (new_chat_suggestions && Array.isArray(new_chat_suggestions) && new_chat_suggestions.length > 0) {
                console.log(`[ChatSyncService] Storing ${new_chat_suggestions.length} new chat suggestions`);
                // Extract encrypted suggestions from server response (already encrypted from Directus)
                const encryptedSuggestions = new_chat_suggestions.map(s => typeof s === 'string' ? s : s.encrypted_suggestion);
                await chatDB.saveEncryptedNewChatSuggestions(encryptedSuggestions, 'global');
            } else {
                console.debug("[ChatSyncService] No new chat suggestions to store");
            }

            // Dispatch event for UI components
            this.dispatchEvent(new CustomEvent('fullSyncReady', {
                detail: { chat_count, suggestions_count: new_chat_suggestions?.length || 0 }
            }));

        } catch (error) {
            console.error("[ChatSyncService] Error handling Phase 3 completion:", error);
        }
    }

    /**
     * Handle phased sync completion
     */
    private async handlePhasedSyncComplete(payload: PhasedSyncCompletePayload): Promise<void> {
        console.log("[ChatSyncService] Phased sync complete:", payload);
        
        this.dispatchEvent(new CustomEvent('phasedSyncComplete', {
            detail: payload
        }));
    }

    /**
     * Handle sync status response
     */
    private async handleSyncStatusResponse(payload: SyncStatusResponsePayload): Promise<void> {
        console.log("[ChatSyncService] Sync status response:", payload);
        
        // Backend sends 'is_primed', not 'cache_primed'
        const { is_primed, chat_count, timestamp } = payload;
        
        console.log("[ChatSyncService] Setting cachePrimed flag:", {
            is_primed,
            chat_count,
            cachePrimed_before: this.cachePrimed,
            initialSyncAttempted: this.initialSyncAttempted
        });
        
        this.cachePrimed = is_primed;
        
        // Dispatch event to Chats.svelte (converting is_primed → cache_primed for backward compatibility)
        this.dispatchEvent(new CustomEvent('syncStatusResponse', {
            detail: { 
                cache_primed: is_primed,  // Convert for Chats.svelte
                chat_count, 
                timestamp 
            }
        }));
        
        // Trigger sync if cache is primed and we haven't attempted yet
        if (is_primed && !this.initialSyncAttempted && this.webSocketConnected) {
            console.log("[ChatSyncService] ✅ Cache primed! Attempting initial sync...");
            this.attemptInitialSync();
        } else {
            console.log("[ChatSyncService] Not starting sync:", {
                is_primed,
                initialSyncAttempted: this.initialSyncAttempted,
                webSocketConnected: this.webSocketConnected
            });
        }
    }

    /**
     * Store recent chats (Phase 2)
     * Merges server data with local data, preserving higher version numbers
     */
    private async storeRecentChats(chats: any[]): Promise<void> {
        try {
            for (const chatItem of chats) {
                const { chat_details, messages } = chatItem;
                const chatId = chat_details.id;
                
                // Get existing local chat to compare versions
                const existingChat = await chatDB.getChat(chatId);
                
                // Merge server data with local data, preserving higher versions
                const mergedChat = this.mergeServerChatWithLocal(chat_details, existingChat);
                
                // CRITICAL: Check if we should sync messages for Phase 2 chats
                // This prevents data inconsistency where messages_v is set but messages are missing
                const shouldSyncMessages = messages && Array.isArray(messages) && messages.length > 0;
                const serverMessagesV = chat_details.messages_v || 0;
                const localMessagesV = existingChat?.messages_v || 0;
                
                let shouldSkipMessageSync = false;
                if (existingChat && serverMessagesV === localMessagesV && shouldSyncMessages) {
                    // Check if we have messages in the database
                    const localMessages = await chatDB.getMessagesForChat(chatId);
                    const localMessageCount = localMessages?.length || 0;
                    const serverMessageCount = messages?.length || 0;
                    
                    console.debug(`[ChatSyncService] Phase 2 - Chat ${chatId}: serverV=${serverMessagesV}, localV=${localMessagesV}, localCount=${localMessageCount}, serverCount=${serverMessageCount}`);
                    
                    // Only skip sync if:
                    // 1. Versions match AND
                    // 2. Local message count matches server message count AND
                    // 3. Local count is reasonable (not zero when we expect messages)
                    // Note: messages_v is not always equal to message count (e.g., after deletions),
                    // so we compare actual message counts, not version to count
                    if (localMessageCount === serverMessageCount && localMessageCount > 0) {
                        shouldSkipMessageSync = true;
                        console.info(`[ChatSyncService] Phase 2 - Skipping message sync for chat ${chatId} - versions match (v${serverMessagesV}) and message counts match (${localMessageCount})`);
                    } else if (localMessageCount === 0 && serverMessageCount === 0) {
                        // Both empty - skip sync
                        shouldSkipMessageSync = true;
                        console.info(`[ChatSyncService] Phase 2 - Skipping message sync for chat ${chatId} - no messages on server or client`);
                    } else {
                        // Data inconsistency: counts don't match or one is empty when other isn't
                        // Allow sync to proceed to fix the inconsistency
                        console.debug(`[ChatSyncService] Phase 2 - Message count mismatch for chat ${chatId}: local=${localMessageCount}, server=${serverMessageCount}. Syncing to fix...`);
                    }
                }
                
                if (shouldSkipMessageSync) {
                    // Still update chat metadata, but skip messages
                    await chatDB.addChat(mergedChat);
                    continue;
                }
                
                // CRITICAL: Always save the chat, even if there are no messages
                // For new chats (existingChat is null), we must save the chat
                // For existing chats with messages, we'll save in the transaction below
                if (!existingChat) {
                    // New chat - save immediately without transaction if no messages
                    // This ensures the chat is saved even if message sync fails
                    if (!shouldSyncMessages || !messages || messages.length === 0) {
                        console.debug(`[ChatSyncService] Phase 2 - Saving new chat ${chatId} without messages`);
                        await chatDB.addChat(mergedChat);
                        continue;
                    }
                }
                
                // CRITICAL FIX: Prepare all message data BEFORE saving
                // This ensures messages are ready to save quickly
                // This prevents the transaction from auto-committing while we do async work
                // Prepare all messages first to avoid async operations during transaction
                const preparedMessages: any[] = [];
                if (shouldSyncMessages && messages && Array.isArray(messages)) {
                    for (const messageData of messages) {
                        // CRITICAL FIX: Messages come as JSON strings from the server, need to parse them
                        let message = messageData;
                        if (typeof messageData === 'string') {
                            try {
                                message = JSON.parse(messageData);
                                console.debug(`[ChatSyncService] Phase 2 - Parsed message JSON string for message: ${message.message_id || message.id}`);
                            } catch (e) {
                                console.error(`[ChatSyncService] Phase 2 - Failed to parse message JSON for chat ${chatId}:`, e);
                                continue;
                            }
                        }
                        
                        // Ensure message has required fields - use 'id' field as message_id if message_id is missing
                        if (!message.message_id && message.id) {
                            message.message_id = message.id;
                        }
                        
                        // DEFENSIVE: Skip messages without message_id
                        if (!message.message_id) {
                            console.error(`[ChatSyncService] Phase 2 - Message missing message_id after parsing, skipping:`, message);
                            continue;
                        }
                        
                        // Ensure chat_id is set on message
                        if (!message.chat_id) {
                            message.chat_id = chatId;
                        }
                        
                        // Set default status if missing
                        if (!message.status) {
                            message.status = 'delivered';
                        }
                        
                        preparedMessages.push(message);
                    }
                }
                
                // CRITICAL FIX: Save chat WITHOUT transaction first to avoid transaction timeout
                // The transaction auto-commits issue happens because encryption is async
                // By saving chat separately, we avoid the transaction timing issue
                // Then save messages in a separate transaction if needed
                try {
                    // Save chat first (addChat handles encryption internally)
                    await chatDB.addChat(mergedChat);
                    console.debug(`[ChatSyncService] Phase 2 - Saved chat ${chatId} to IndexedDB`);
                    
                    // Save messages in a separate transaction if we have any
                    if (shouldSyncMessages && preparedMessages.length > 0) {
                        console.log(`[ChatSyncService] Phase 2 - Syncing ${preparedMessages.length} messages for chat ${chatId} (server v${serverMessagesV}, local v${localMessagesV})`);
                        
                        // Create transaction just for messages
                        const messageTransaction = await chatDB.getTransaction(
                            [chatDB['MESSAGES_STORE_NAME']], 
                            'readwrite'
                        );
                        
                        // Save all prepared messages within the transaction
                        for (const message of preparedMessages) {
                            await chatDB.saveMessage(message, messageTransaction);
                        }
                        
                        console.debug(`[ChatSyncService] Phase 2 - Successfully queued ${preparedMessages.length} messages for chat ${chatId} in transaction`);
                        
                        // Wait for transaction to complete
                        await new Promise<void>((resolve, reject) => {
                            messageTransaction.oncomplete = () => {
                                console.debug(`[ChatSyncService] Phase 2 - Message transaction completed successfully for chat ${chatId}`);
                                resolve();
                            };
                            messageTransaction.onerror = () => {
                                console.error(`[ChatSyncService] Phase 2 - Message transaction error for chat ${chatId}:`, messageTransaction.error);
                                reject(messageTransaction.error);
                            };
                            messageTransaction.onabort = () => {
                                console.error(`[ChatSyncService] Phase 2 - Message transaction aborted for chat ${chatId}`);
                                reject(new Error('Transaction aborted'));
                            };
                        });
                    }
                } catch (saveError) {
                    console.error(`[ChatSyncService] Phase 2 - Error saving chat/messages for chat ${chatId}:`, saveError);
                    // Don't throw - continue with next chat to avoid blocking all sync
                    // The error is logged for debugging
                }
            }
            
            console.log(`[ChatSyncService] Phase 2 - Stored ${chats.length} recent chats with message sync`);
        } catch (error) {
            console.error("[ChatSyncService] Phase 2 - Error storing recent chats:", error);
        }
    }

    /**
     * Store all chats (Phase 3)
     * Merges server data with local data, preserving higher version numbers
     * Also handles messages if provided in the payload
     * 
     * CRITICAL: Uses transactions to prevent duplicate messages during reconnection
     */
    private async storeAllChats(chats: any[]): Promise<void> {
        try {
            console.debug(`[ChatSyncService] storeAllChats: Processing ${chats.length} chats from Phase 3`);
            
            for (const chatItem of chats) {
                const { chat_details, messages } = chatItem;
                const chatId = chat_details.id;
                
                console.debug(`[ChatSyncService] Processing chat ${chatId} with ${messages?.length || 0} messages`);
                
                // Get existing local chat to compare versions
                const existingChat = await chatDB.getChat(chatId);
                
                // Merge server data with local data, preserving higher versions
                const mergedChat = this.mergeServerChatWithLocal(chat_details, existingChat);
                
                // CRITICAL: If server messages_v equals local messages_v, skip message sync
                // BUT ONLY if local messages actually exist! (prevents skipping on fresh login with Phase 2 chats)
                const shouldSyncMessages = messages && Array.isArray(messages) && messages.length > 0;
                const serverMessagesV = chat_details.messages_v || 0;
                const localMessagesV = existingChat?.messages_v || 0;
                
                // CRITICAL: Validate that local messages count matches messages_v before skipping sync
                // This prevents data inconsistencies where messages_v is set but messages are missing
                let shouldSkipMessageSync = false;
                if (existingChat && serverMessagesV === localMessagesV && shouldSyncMessages) {
                    // Check if we have messages in the database
                    const localMessages = await chatDB.getMessagesForChat(chatId);
                    const localMessageCount = localMessages?.length || 0;
                    const serverMessageCount = messages?.length || 0;
                    
                    console.debug(`[ChatSyncService] Chat ${chatId}: serverV=${serverMessagesV}, localV=${localMessagesV}, localCount=${localMessageCount}, serverCount=${serverMessageCount}`);
                    
                    // Only skip sync if:
                    // 1. Versions match AND
                    // 2. Local message count matches server message count AND
                    // 3. Local count is reasonable (not zero when we expect messages)
                    // Note: messages_v is not always equal to message count (e.g., after deletions),
                    // so we compare actual message counts, not version to count
                    if (localMessageCount === serverMessageCount && localMessageCount > 0) {
                        shouldSkipMessageSync = true;
                        console.info(`[ChatSyncService] Skipping message sync for chat ${chatId} - versions match (v${serverMessagesV}) and message counts match (${localMessageCount})`);
                    } else if (localMessageCount === 0 && serverMessageCount === 0) {
                        // Both empty - skip sync
                        shouldSkipMessageSync = true;
                        console.info(`[ChatSyncService] Skipping message sync for chat ${chatId} - no messages on server or client`);
                    } else {
                        // Data inconsistency: counts don't match or one is empty when other isn't
                        // Allow sync to proceed to fix the inconsistency
                        console.debug(`[ChatSyncService] Message count mismatch for chat ${chatId}: local=${localMessageCount}, server=${serverMessageCount}. Syncing to fix...`);
                        // Update the local messages_v to match server version
                        if (existingChat) {
                            mergedChat.messages_v = serverMessagesV; // Use server version
                        }
                    }
                }
                
                if (shouldSkipMessageSync) {
                    // Still update chat metadata, but skip messages
                    await chatDB.addChat(mergedChat);
                    continue;
                }
                
                // CRITICAL FIX: Save chat WITHOUT transaction first to avoid transaction timeout
                // The transaction auto-commits issue happens because encryption is async
                // By saving chat separately, we avoid the transaction timing issue
                // Then save messages in a separate transaction if needed
                try {
                    // Save chat first (addChat handles encryption internally)
                    await chatDB.addChat(mergedChat);
                    console.debug(`[ChatSyncService] Phase 3 - Saved chat ${chatId} to IndexedDB`);
                    
                    // Prepare and save messages in a separate transaction if we have any
                    if (shouldSyncMessages && messages && Array.isArray(messages) && messages.length > 0) {
                        console.log(`[ChatSyncService] Syncing ${messages.length} messages for chat ${chatId} from Phase 3 (server v${serverMessagesV}, local v${localMessagesV})`);
                        
                        // Prepare all messages first to avoid async operations during transaction
                        const preparedMessages: any[] = [];
                        for (const messageData of messages) {
                            // CRITICAL FIX: Messages come as JSON strings from the server, need to parse them
                            let message = messageData;
                            if (typeof messageData === 'string') {
                                try {
                                    message = JSON.parse(messageData);
                                    console.debug(`[ChatSyncService] Parsed message JSON string for message: ${message.message_id || message.id}`);
                                } catch (e) {
                                    console.error(`[ChatSyncService] Failed to parse message JSON for chat ${chatId}:`, e);
                                    continue;
                                }
                            }
                            
                            // Ensure message has required fields - use 'id' field as message_id if message_id is missing
                            if (!message.message_id && message.id) {
                                message.message_id = message.id;
                            }
                            
                            // DEFENSIVE: Skip messages without message_id
                            if (!message.message_id) {
                                console.error(`[ChatSyncService] Message missing message_id after parsing, skipping:`, message);
                                continue;
                            }
                            
                            // Ensure chat_id is set on message
                            if (!message.chat_id) {
                                message.chat_id = chatId;
                            }
                            
                            // Set default status if missing
                            if (!message.status) {
                                message.status = 'delivered';
                            }
                            
                            preparedMessages.push(message);
                        }
                        
                        // Create transaction just for messages
                        const messageTransaction = await chatDB.getTransaction(
                            [chatDB['MESSAGES_STORE_NAME']], 
                            'readwrite'
                        );
                        
                        // Save all messages within the transaction
                        // This ensures duplicate detection works correctly across all messages
                        for (const message of preparedMessages) {
                            await chatDB.saveMessage(message, messageTransaction);
                        }
                        
                        console.debug(`[ChatSyncService] Successfully queued ${preparedMessages.length} messages for chat ${chatId} in transaction`);
                        
                        // Wait for transaction to complete
                        await new Promise<void>((resolve, reject) => {
                            messageTransaction.oncomplete = () => {
                                console.debug(`[ChatSyncService] Phase 3 - Message transaction completed successfully for chat ${chatId}`);
                                resolve();
                            };
                            messageTransaction.onerror = () => {
                                console.error(`[ChatSyncService] Phase 3 - Message transaction error for chat ${chatId}:`, messageTransaction.error);
                                reject(messageTransaction.error);
                            };
                            messageTransaction.onabort = () => {
                                console.error(`[ChatSyncService] Phase 3 - Message transaction aborted for chat ${chatId}`);
                                reject(new Error('Transaction aborted'));
                            };
                        });
                    }
                } catch (saveError) {
                    console.error(`[ChatSyncService] Phase 3 - Error saving chat/messages for chat ${chatId}:`, saveError);
                    // Don't throw - continue with next chat to avoid blocking all sync
                    // The error is logged for debugging
                }
            }
            
            console.log(`[ChatSyncService] Stored ${chats.length} all chats (Phase 3) with duplicate prevention`);
        } catch (error) {
            console.error("[ChatSyncService] Error storing all chats:", error);
        }
    }

    /**
     * Merge server chat data with local chat data
     * Preserves local data when version numbers are higher or equal
     * This prevents phased sync from overwriting locally updated data that hasn't been synced yet
     */
    private mergeServerChatWithLocal(serverChat: any, localChat: any | null): any {
        // If no local chat exists, use server data as-is
        if (!localChat) {
            console.debug(`[ChatSyncService] No local chat found, using server data for chat ${serverChat.id}`);
            return {
                chat_id: serverChat.id,
                ...serverChat
            };
        }
        
        // Start with server data as base
        const merged: any = {
            chat_id: serverChat.id,
            ...serverChat
        };
        
        // Preserve local encrypted_title if local title_v is higher or equal
        const localTitleV = localChat.title_v || 0;
        const serverTitleV = serverChat.title_v || 0;
        if (localTitleV >= serverTitleV && localChat.encrypted_title) {
            merged.encrypted_title = localChat.encrypted_title;
            merged.title_v = localChat.title_v;
            console.debug(`[ChatSyncService] Preserving local title for chat ${merged.chat_id} (local v${localTitleV} >= server v${serverTitleV})`);
        }
        
        // Preserve local draft if local draft_v is higher or equal
        const localDraftV = localChat.draft_v || 0;
        const serverDraftV = serverChat.draft_v || 0;
        if (localDraftV >= serverDraftV) {
            if (localChat.encrypted_draft_md) {
                merged.encrypted_draft_md = localChat.encrypted_draft_md;
            }
            if (localChat.encrypted_draft_preview) {
                merged.encrypted_draft_preview = localChat.encrypted_draft_preview;
            }
            merged.draft_v = localChat.draft_v;
            console.debug(`[ChatSyncService] Preserving local draft for chat ${merged.chat_id} (local v${localDraftV} >= server v${serverDraftV})`);
        }
        
        // Always preserve local encrypted_chat_key if it exists
        if (localChat.encrypted_chat_key) {
            merged.encrypted_chat_key = localChat.encrypted_chat_key;
            console.debug(`[ChatSyncService] Preserving local encrypted_chat_key for chat ${merged.chat_id}`);
        }
        
        // Preserve local messages_v if higher or equal
        const localMessagesV = localChat.messages_v || 0;
        const serverMessagesV = serverChat.messages_v || 0;
        if (localMessagesV > serverMessagesV) {
            merged.messages_v = localChat.messages_v;
            console.debug(`[ChatSyncService] Preserving local messages_v for chat ${merged.chat_id} (local v${localMessagesV} > server v${serverMessagesV})`);
        }
        
        return merged;
    }

    /**
     * Retry sending messages that are pending (status: 'waiting_for_internet' or 'sending')
     * This is called automatically when WebSocket connection is restored
     * Messages are retried every few seconds until successfully sent or connection is lost again
     */
    private async retryPendingMessages(): Promise<void> {
        if (!this.webSocketConnected) {
            console.debug("[ChatSyncService] Skipping pending message retry - WebSocket not connected");
            return;
        }

        try {
            console.info("[ChatSyncService] Retrying pending messages after connection restored...");
            
            // Get all messages from database
            const allMessages = await chatDB.getAllMessages();
            
            // Filter for messages that need to be retried
            const pendingMessages = allMessages.filter(msg => 
                msg.status === 'waiting_for_internet' || 
                (msg.status === 'sending' && msg.role === 'user')
            );

            if (pendingMessages.length === 0) {
                console.debug("[ChatSyncService] No pending messages to retry");
                return;
            }

            console.info(`[ChatSyncService] Found ${pendingMessages.length} pending message(s) to retry`);

            // Update status to 'sending' and retry each message
            for (const message of pendingMessages) {
                try {
                    // Update status to 'sending' before retry
                    const updatedMessage: Message = { ...message, status: 'sending' };
                    await chatDB.saveMessage(updatedMessage);
                    
                    // Dispatch event to update UI
                    this.dispatchEvent(new CustomEvent('messageStatusChanged', {
                        detail: { 
                            chatId: message.chat_id, 
                            messageId: message.message_id, 
                            status: 'sending' 
                        }
                    }));

                    // Retry sending the message
                    console.debug(`[ChatSyncService] Retrying message ${message.message_id} for chat ${message.chat_id}`);
                    await this.sendNewMessage(updatedMessage);
                    
                } catch (error) {
                    console.error(`[ChatSyncService] Error retrying message ${message.message_id}:`, error);
                    
                    // Update status back to 'waiting_for_internet' if retry failed
                    try {
                        const failedMessage: Message = { ...message, status: 'waiting_for_internet' };
                        await chatDB.saveMessage(failedMessage);
                        
                        this.dispatchEvent(new CustomEvent('messageStatusChanged', {
                            detail: { 
                                chatId: message.chat_id, 
                                messageId: message.message_id, 
                                status: 'waiting_for_internet' 
                            }
                        }));
                    } catch (dbError) {
                        console.error(`[ChatSyncService] Error updating message status after retry failure:`, dbError);
                    }
                }
            }

            console.info(`[ChatSyncService] Completed retry attempt for ${pendingMessages.length} pending message(s)`);
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

        console.debug("[ChatSyncService] Starting periodic retry for pending messages");
        
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
                console.debug("[ChatSyncService] Periodic retry failed (expected when offline):", error);
            }
        }, this.PENDING_MESSAGE_RETRY_INTERVAL);
    }

    private stopPendingMessageRetry(): void {
        if (this.pendingMessageRetryInterval) {
            clearInterval(this.pendingMessageRetryInterval);
            this.pendingMessageRetryInterval = null;
            console.debug("[ChatSyncService] Stopped periodic retry for pending messages");
        }
    }
}

export const chatSyncService = new ChatSynchronizationService();
