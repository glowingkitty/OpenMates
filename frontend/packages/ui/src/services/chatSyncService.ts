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
    private readonly CACHE_STATUS_REQUEST_DELAY = 3000; // 3 seconds
    public activeAITasks: Map<string, { taskId: string, userMessageId: string }> = new Map(); // Made public for handlers

    constructor() {
        super();
        this.registerWebSocketHandlers();
        websocketStatus.subscribe(storeState => {
            this.webSocketConnected = storeState.status === 'connected';
            if (this.webSocketConnected) {
                console.info("[ChatSyncService] WebSocket connected.");
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
            }
        });
    }

    private registerWebSocketHandlers() {
        webSocketService.on('initial_sync_response', (payload) => coreSyncHandlers.handleInitialSyncResponseImpl(this, payload as InitialSyncResponsePayload));
        webSocketService.on('initial_sync_error', (payload) => coreSyncHandlers.handleInitialSyncErrorImpl(this, payload as { message: string }));
        webSocketService.on('phase_1_last_chat_ready', (payload) => coreSyncHandlers.handlePhase1LastChatImpl(this, payload as Phase1LastChatPayload));
        webSocketService.on('cache_primed', (payload) => coreSyncHandlers.handleCachePrimedImpl(this, payload as CachePrimedPayload));
        webSocketService.on('cache_status_response', (payload) => coreSyncHandlers.handleCacheStatusResponseImpl(this, payload as CacheStatusResponsePayload));
        
        // New phased sync event handlers
        webSocketService.on('phase_2_last_10_chats_ready', (payload) => this.handlePhase2RecentChats(payload as Phase2RecentChatsPayload));
        webSocketService.on('phase_3_last_100_chats_ready', (payload) => this.handlePhase3FullSync(payload as Phase3FullSyncPayload));
        webSocketService.on('phased_sync_complete', (payload) => this.handlePhasedSyncComplete(payload as PhasedSyncCompletePayload));
        webSocketService.on('sync_status_response', (payload) => this.handleSyncStatusResponse(payload as SyncStatusResponsePayload)); 
        // chat_title_updated removed - titles now handled via ai_typing_started in dual-phase architecture
        webSocketService.on('chat_draft_updated', (payload) => chatUpdateHandlers.handleChatDraftUpdatedImpl(this, payload as ChatDraftUpdatedPayload));
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
        webSocketService.on('ai_message_ready', (payload) => aiHandlers.handleAIMessageReadyImpl(this, payload as AIMessageReadyPayload));
        webSocketService.on('ai_task_initiated', (payload) => aiHandlers.handleAITaskInitiatedImpl(this, payload as AITaskInitiatedPayload));
        webSocketService.on('ai_task_cancel_requested', (payload) => aiHandlers.handleAITaskCancelRequestedImpl(this, payload as AITaskCancelRequestedPayload));
        webSocketService.on('ai_response_storage_confirmed', (payload) => aiHandlers.handleAIResponseStorageConfirmedImpl(this, payload as { chat_id: string; message_id: string; task_id?: string }));
        webSocketService.on('encrypted_metadata_stored', (payload) => aiHandlers.handleEncryptedMetadataStoredImpl(this, payload as { chat_id: string; message_id: string; task_id?: string }));
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
        console.debug("[ChatSyncService] attemptInitialSync called:", {
            isSyncing: this.isSyncing,
            initialSyncAttempted: this.initialSyncAttempted,
            webSocketConnected: this.webSocketConnected,
            cachePrimed: this.cachePrimed,
            immediate_view_chat_id
        });
        
        if (this.isSyncing || this.initialSyncAttempted) {
            console.warn("[ChatSyncService] Skipping sync - already in progress or attempted");
            return;
        }
        
        if (this.webSocketConnected && this.cachePrimed) {
            console.info("[ChatSyncService] Conditions met, starting initial sync");
            this.startInitialSync(immediate_view_chat_id);
        } else {
            console.warn("[ChatSyncService] Conditions not met for sync:", {
                webSocketConnected: this.webSocketConnected,
                cachePrimed: this.cachePrimed
            });
        }
    }

    public async startInitialSync(immediate_view_chat_id?: string): Promise<void> {
        console.debug("[ChatSyncService] startInitialSync called:", {
            isSyncing: this.isSyncing,
            webSocketConnected: this.webSocketConnected,
            cachePrimed: this.cachePrimed
        });
        
        if (this.isSyncing || !this.webSocketConnected || !this.cachePrimed) {
            console.warn("[ChatSyncService] startInitialSync aborted - conditions not met");
            return;
        }
        
        this.isSyncing = true;
        this.initialSyncAttempted = true;
        
        console.info("[ChatSyncService] Starting initial sync...");
        
        try {
            console.debug("[ChatSyncService] Initializing ChatDB...");
            await chatDB.init();
            const localChatsMetadata = await chatDB.getAllChats();
            const userProfile = await userDB.getUserProfile();
            const lastSyncTimestamp = userProfile?.last_sync_timestamp || 0;

            // Build sorted list of chat IDs for reliable sync detection
            const chatIds = localChatsMetadata.map(c => c.chat_id).sort();
            
            // Build version map for each chat
            const chat_versions: Record<string, ChatComponentVersions> = {};
            localChatsMetadata.forEach(c => chat_versions[c.chat_id] = { messages_v: c.messages_v, title_v: c.title_v, draft_v: c.draft_v || 0 });
            
            const pending_message_ids: Record<string, string[]> = {};
            for (const chat of localChatsMetadata) {
                const messages = await chatDB.getMessagesForChat(chat.chat_id);
                const sendingMessages = messages.filter(m => m.status === 'sending');
                if (sendingMessages.length > 0) pending_message_ids[chat.chat_id] = sendingMessages.map(m => m.message_id);
            }

            const payload: InitialSyncRequestPayload = { 
                chat_ids: chatIds,  // Sorted list of chat IDs client has
                chat_count: chatIds.length,  // Number of chats client has
                chat_versions,
                last_sync_timestamp: lastSyncTimestamp 
            };
            if (immediate_view_chat_id) payload.immediate_view_chat_id = immediate_view_chat_id;
            if (Object.keys(pending_message_ids).length > 0) payload.pending_message_ids = pending_message_ids;
            
            // Log sync request details for debugging
            console.debug("[ChatSyncService] Starting sync:", {
                chatCount: chatIds.length,
                lastSyncTimestamp: lastSyncTimestamp,
                hasPendingMessages: Object.keys(pending_message_ids).length > 0
            });
            
            await webSocketService.sendMessage('initial_sync_request', payload);
        } catch (error) {
            notificationStore.error(`Failed to start chat synchronization: ${error instanceof Error ? error.message : String(error)}`);
            this.isSyncing = false;
        }
    }
    
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
    public async sendNewMessage(message: Message): Promise<void> {
        await senders.sendNewMessageImpl(this, message);
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
     * Start the new 3-phase sync process
     */
    public async startPhasedSync(): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] Cannot start phased sync - WebSocket not connected");
            return;
        }
        
        try {
            console.log("[ChatSyncService] Starting phased sync...");
            const payload: PhasedSyncRequestPayload = { phase: 'all' };
            await webSocketService.sendMessage('phased_sync_request', payload);
        } catch (error) {
            console.error("[ChatSyncService] Error starting phased sync:", error);
            notificationStore.error("Failed to start phased synchronization");
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
     */
    private async handlePhase2RecentChats(payload: Phase2RecentChatsPayload): Promise<void> {
        console.log("[ChatSyncService] Phase 2 complete - recent chats ready:", payload);
        
        try {
            const { chats, chat_count } = payload;
            
            // Store recent chats data
            await this.storeRecentChats(chats);
            
            // Dispatch event for UI components
            this.dispatchEvent(new CustomEvent('recentChatsReady', {
                detail: { chat_count }
            }));
            
        } catch (error) {
            console.error("[ChatSyncService] Error handling Phase 2 completion:", error);
        }
    }

    /**
     * Handle Phase 3 completion (full sync ready)
     */
    private async handlePhase3FullSync(payload: Phase3FullSyncPayload): Promise<void> {
        console.log("[ChatSyncService] Phase 3 complete - full sync ready:", payload);
        
        try {
            const { chats, chat_count } = payload;
            
            // Store all chats data
            await this.storeAllChats(chats);
            
            // Dispatch event for UI components
            this.dispatchEvent(new CustomEvent('fullSyncReady', {
                detail: { chat_count }
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
        
        const { cache_primed, chat_count, timestamp } = payload;
        
        this.cachePrimed = cache_primed;
        
        this.dispatchEvent(new CustomEvent('syncStatusResponse', {
            detail: { cache_primed, chat_count, timestamp }
        }));
    }

    /**
     * Store recent chats (Phase 2)
     * Merges server data with local data, preserving higher version numbers
     */
    private async storeRecentChats(chats: any[]): Promise<void> {
        try {
            for (const chatItem of chats) {
                const { chat_details } = chatItem;
                const chatId = chat_details.id;
                
                // Get existing local chat to compare versions
                const existingChat = await chatDB.getChat(chatId);
                
                // Merge server data with local data, preserving higher versions
                const mergedChat = this.mergeServerChatWithLocal(chat_details, existingChat);
                
                // Store merged encrypted chat metadata
                await chatDB.addChat(mergedChat);
            }
            
            console.log(`[ChatSyncService] Stored ${chats.length} recent chats (Phase 2)`);
        } catch (error) {
            console.error("[ChatSyncService] Error storing recent chats:", error);
        }
    }

    /**
     * Store all chats (Phase 3)
     * Merges server data with local data, preserving higher version numbers
     * Also handles messages if provided in the payload
     */
    private async storeAllChats(chats: any[]): Promise<void> {
        try {
            for (const chatItem of chats) {
                const { chat_details, messages } = chatItem;
                const chatId = chat_details.id;
                
                // Get existing local chat to compare versions
                const existingChat = await chatDB.getChat(chatId);
                
                // Merge server data with local data, preserving higher versions
                const mergedChat = this.mergeServerChatWithLocal(chat_details, existingChat);
                
                // Store merged encrypted chat metadata
                await chatDB.addChat(mergedChat);
                
                // Store messages if provided in Phase 3 payload
                if (messages && Array.isArray(messages) && messages.length > 0) {
                    console.log(`[ChatSyncService] Storing ${messages.length} messages for chat ${chatId} from Phase 3`);
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
                        
                        // Set default status if missing
                        if (!message.status) {
                            message.status = 'delivered';
                        }
                        
                        await chatDB.saveMessage(message);
                    }
                }
            }
            
            console.log(`[ChatSyncService] Stored ${chats.length} all chats (Phase 3)`);
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
}

export const chatSyncService = new ChatSynchronizationService();
