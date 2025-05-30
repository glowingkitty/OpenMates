// frontend/packages/ui/src/services/chatSyncService.ts
// Handles chat data synchronization between client and server via WebSockets.
import { chatDB } from './db';
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
    PriorityChatReadyPayload,   
    CachePrimedPayload,         
    CacheStatusResponsePayload, 
    ChatContentBatchResponsePayload, 
    OfflineSyncCompletePayload,
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
        webSocketService.on('priority_chat_ready', (payload) => coreSyncHandlers.handlePriorityChatReadyImpl(this, payload as PriorityChatReadyPayload));
        webSocketService.on('cache_primed', (payload) => coreSyncHandlers.handleCachePrimedImpl(this, payload as CachePrimedPayload));
        webSocketService.on('cache_status_response', (payload) => coreSyncHandlers.handleCacheStatusResponseImpl(this, payload as CacheStatusResponsePayload)); 
        webSocketService.on('chat_title_updated', (payload) => chatUpdateHandlers.handleChatTitleUpdatedImpl(this, payload as ChatTitleUpdatedPayload));
        webSocketService.on('chat_draft_updated', (payload) => chatUpdateHandlers.handleChatDraftUpdatedImpl(this, payload as ChatDraftUpdatedPayload));
        webSocketService.on('chat_message_added', (payload) => chatUpdateHandlers.handleChatMessageReceivedImpl(this, payload as ChatMessageReceivedPayload)); 
        webSocketService.on('chat_message_confirmed', (payload) => chatUpdateHandlers.handleChatMessageConfirmedImpl(this, payload as ChatMessageConfirmedPayload)); 
        webSocketService.on('chat_deleted', (payload) => chatUpdateHandlers.handleChatDeletedImpl(this, payload as ChatDeletedPayload));
        webSocketService.on('offline_sync_complete', (payload) => coreSyncHandlers.handleOfflineSyncCompleteImpl(this, payload as OfflineSyncCompletePayload));
        webSocketService.on('chat_content_batch_response', (payload) => coreSyncHandlers.handleChatContentBatchResponseImpl(this, payload as ChatContentBatchResponsePayload));

        webSocketService.on('ai_message_update', (payload) => aiHandlers.handleAIMessageUpdateImpl(this, payload as AIMessageUpdatePayload));
        webSocketService.on('ai_typing_started', (payload) => aiHandlers.handleAITypingStartedImpl(this, payload as AITypingStartedPayload));
        webSocketService.on('ai_typing_ended', (payload) => aiHandlers.handleAITypingEndedImpl(this, payload as { chat_id: string, message_id: string }));
        webSocketService.on('ai_message_ready', (payload) => aiHandlers.handleAIMessageReadyImpl(this, payload as AIMessageReadyPayload));
        webSocketService.on('ai_task_initiated', (payload) => aiHandlers.handleAITaskInitiatedImpl(this, payload as AITaskInitiatedPayload));
        webSocketService.on('ai_task_cancel_requested', (payload) => aiHandlers.handleAITaskCancelRequestedImpl(this, payload as AITaskCancelRequestedPayload));
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
        if (this.isSyncing || this.initialSyncAttempted) return;
        if (this.webSocketConnected && this.cachePrimed) {
            this.startInitialSync(immediate_view_chat_id);
        }
    }

    public async startInitialSync(immediate_view_chat_id?: string): Promise<void> {
        if (this.isSyncing || !this.webSocketConnected || !this.cachePrimed) return;
        this.isSyncing = true;
        this.initialSyncAttempted = true;
        try {
            await chatDB.init();
            const localChatsMetadata = await chatDB.getAllChats();
            const chat_versions: Record<string, ChatComponentVersions> = {};
            localChatsMetadata.forEach(c => chat_versions[c.chat_id] = { messages_v: c.messages_v, title_v: c.title_v, draft_v: c.draft_v || 0 });
            
            const pending_message_ids: Record<string, string[]> = {};
            for (const chat of localChatsMetadata) {
                const messages = await chatDB.getMessagesForChat(chat.chat_id);
                const sendingMessages = messages.filter(m => m.status === 'sending');
                if (sendingMessages.length > 0) pending_message_ids[chat.chat_id] = sendingMessages.map(m => m.message_id);
            }

            const payload: InitialSyncRequestPayload = { chat_versions };
            if (immediate_view_chat_id) payload.immediate_view_chat_id = immediate_view_chat_id;
            if (Object.keys(pending_message_ids).length > 0) payload.pending_message_ids = pending_message_ids;
            
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
        senders.sendUpdateTitleImpl(this, chat_id, new_title);
    }
    public async sendUpdateDraft(chat_id: string, draft_json: TiptapJSON | null) {
        senders.sendUpdateDraftImpl(this, chat_id, draft_json);
    }
    public async sendDeleteDraft(chat_id: string) {
        senders.sendDeleteDraftImpl(this, chat_id);
    }
    public async sendDeleteChat(chat_id: string) {
        senders.sendDeleteChatImpl(this, chat_id);
    }
    public async sendNewMessage(message: Message): Promise<void> {
        senders.sendNewMessageImpl(this, message);
    }
    public async sendSetActiveChat(chatId: string | null): Promise<void> {
        senders.sendSetActiveChatImpl(this, chatId);
    }
    public async sendCancelAiTask(taskId: string): Promise<void> {
        senders.sendCancelAiTaskImpl(this, taskId);
    }
    public async queueOfflineChange(change: Omit<OfflineChange, 'change_id'>): Promise<void> {
        // This one is tricky as it's called by senders. For now, keep it public or make senders pass `this` to it.
        // For simplicity, making it public for now.
        senders.queueOfflineChangeImpl(this, change);
    }
    public async sendOfflineChanges(): Promise<void> {
        senders.sendOfflineChangesImpl(this);
    }
}

export const chatSyncService = new ChatSynchronizationService();
