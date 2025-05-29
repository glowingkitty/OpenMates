// frontend/packages/ui/src/services/chatSyncService.ts
// Handles chat data synchronization between client and server via WebSockets.
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { websocketStatus, type WebSocketStatus } from '../stores/websocketStatusStore';
import { notificationStore } from '../stores/notificationStore'; // Import notification store
import type { ChatComponentVersions, OfflineChange, TiptapJSON, Message, Chat } from '../types/chat';
import { aiTypingStore } from '../stores/aiTypingStore'; // Import the new store
// UserChatDraft import is removed as it's integrated into Chat type
import { get } from 'svelte/store';

// Payloads for WebSocket messages (mirroring server expectations)
interface InitialSyncRequestPayload {
    chat_versions: Record<string, ChatComponentVersions>;
    pending_message_ids?: Record<string, string[]>; // Key: chat_id, Value: array of message_ids in 'sending' state
    immediate_view_chat_id?: string;
}

interface UpdateTitlePayload {
    chat_id: string;
    new_title: string;
}

interface UpdateDraftPayload {
    chat_id: string;
    draft_json: TiptapJSON | null;
}

interface SyncOfflineChangesPayload {
    changes: OfflineChange[];
}

interface RequestChatContentBatchPayload {
    chat_ids: string[];
}

interface DeleteChatPayload {
    chatId: string; // Matches existing backend handler
}

interface DeleteDraftPayload { // New payload for deleting a draft
    chatId: string; // Changed to camelCase to match backend expectation
}

interface SendChatMessagePayload { // New: Client sends a new chat message
    chat_id: string;
    message: Message;
}

// === Client to Server ===
// (Existing client to server payloads)
interface RequestCacheStatusPayload { // New: Client requests current cache status
    // No payload needed, just the type
}

interface SetActiveChatPayload { // Client tells server which chat is active
    chat_id: string | null;
}

interface CancelAITaskPayload { // Client to Server: Request to cancel an AI task
    task_id: string;
}


// === Server to Client ===
// (Existing server to client payloads)

// AI Task and Stream related events from server
interface AITaskInitiatedPayload { // Server to Client: AI task has started
    chat_id: string;
    user_message_id: string; // The user's message that triggered the AI
    ai_task_id: string;      // The Celery task ID for the AI processing
    status: "processing_started";
}

interface AIMessageUpdatePayload { // Payload for 'ai_message_update' (streaming chunk)
    type: "ai_message_chunk";
    task_id: string; // This is the ai_task_id
    chat_id: string;
    message_id: string; // AI's message ID (often same as task_id for the initial AI message)
    user_message_id: string;
    full_content_so_far: string;
    sequence: number;
    is_final_chunk: boolean;
    interrupted_by_soft_limit?: boolean; // Added from backend
    interrupted_by_revocation?: boolean; // Added from backend
}

interface AITypingStartedPayload { // Server to Client: AI has started "typing"
    chat_id: string;
    message_id: string; // AI's message ID (task_id)
    user_message_id: string; // User message that triggered this
    mate_name: string; // Name of the mate that is typing
}

interface AIMessageReadyPayload {
    chat_id: string;
    message_id: string;
    user_message_id: string;
}

interface AITaskCancelRequestedPayload { // Server to Client: Acknowledgement of cancel request
    task_id: string;
    status: "revocation_sent" | "already_completed" | "not_found" | "error";
    message?: string; // Optional message, e.g., for errors
}
// --- End AI Task and Stream related event payloads ---

interface PriorityChatReadyPayload {
    chat_id: string;
}

interface CachePrimedPayload {
    status: "full_sync_ready";
}

interface CacheStatusResponsePayload { // New: Server responds to cache status request
    is_primed: boolean;
}

export interface InitialSyncResponsePayload {
    chat_ids_to_delete: string[];
    chats_to_add_or_update: Array<{
        chat_id: string;
        versions: ChatComponentVersions;
        last_edited_overall_timestamp: number;
        type: 'new_chat' | 'updated_chat';
        title?: string;
        draft_json?: TiptapJSON | null; // User's draft content, corresponds to draft_v
        unread_count?: number;
        messages?: Message[]; // Messages might be missing if not immediate_view_chat_id
    }>;
    server_chat_order: string[];
    sync_completed_at: string;
}

interface ChatContentBatchResponsePayload {
    // Key: chat_id, Value: array of messages for that chat
    messages_by_chat_id: Record<string, Message[]>;
    // Optionally, include updated versions if messages_v could change
    // versions_by_chat_id?: Record<string, { messages_v: number }>;
}


interface ChatTitleUpdatedPayload {
    event: string; // "chat_title_updated"
    chat_id: string;
    data: { title: string };
    versions: { title_v: number };
}

interface ChatDraftUpdatedPayload {
    event: string; // "chat_draft_updated"
    chat_id: string;
    data: { draft_json: TiptapJSON | null };
    versions: { draft_v: number }; // This is user_draft_v from server
    last_edited_overall_timestamp: number;
}

interface ChatMessageReceivedPayload { // This is for server broadcasting a message to clients
    event: string; // "chat_message_added" 
    chat_id: string;
    message: Message; // The new message object
    versions: { messages_v: number };
    last_edited_overall_timestamp: number;
}

interface ChatMessageConfirmedPayload { // Data received by the handler for a confirmed message
    chat_id: string;
    message_id: string; // The ID of the message being confirmed
    temp_id?: string; // temp_id if client sent one, echoed back by server
    new_messages_v: number; // The new messages_v for the chat after this message
    new_last_edited_overall_timestamp: number; // The new overall timestamp
    // Note: The 'type' or 'event' field ("chat_message_confirmed") is handled by WebSocketService
    // and is not part of the object passed to this specific handler.
}


interface ChatDeletedPayload {
    chat_id: string;
    tombstone: boolean; // Should be true
}

interface OfflineSyncCompletePayload {
    processed: number;
    conflicts: number;
    errors: number;
}


export class ChatSynchronizationService extends EventTarget {
    private isSyncing = false;
    private serverChatOrder: string[] = [];
    private webSocketConnected = false;
    private cachePrimed = false;
    private initialSyncAttempted = false;
    private cacheStatusRequestTimeout: NodeJS.Timeout | null = null;
    private readonly CACHE_STATUS_REQUEST_DELAY = 3000; // 3 seconds
    private activeAITasks: Map<string, { taskId: string, userMessageId: string }> = new Map(); // Key: chat_id, Value: {taskId, userMessageId}

    constructor() {
        super();
        this.registerWebSocketHandlers();
        websocketStatus.subscribe(storeState => {
            if (storeState.status === 'connected') {
                console.info("[ChatSyncService] WebSocket connected.");
                this.webSocketConnected = true;
                
                // Clear any existing timeout to prevent multiple requests
                if (this.cacheStatusRequestTimeout) {
                    clearTimeout(this.cacheStatusRequestTimeout);
                    this.cacheStatusRequestTimeout = null;
                }

                if (this.cachePrimed) {
                    // If cache was already marked as primed (e.g., from a previous quick session or direct response)
                    console.info("[ChatSyncService] Cache was already primed. Attempting initial sync.");
                    this.attemptInitialSync();
                } else {
                    // If cache is not primed, wait for 'cache_primed' event OR proactively request status
                    console.info("[ChatSyncService] Waiting for 'cache_primed' signal or will request status.");
                    this.cacheStatusRequestTimeout = setTimeout(() => {
                        if (!this.cachePrimed && this.webSocketConnected) {
                            console.info("[ChatSyncService] 'cache_primed' not received, proactively requesting cache status.");
                            this.requestCacheStatus();
                        }
                    }, this.CACHE_STATUS_REQUEST_DELAY);
                }
            } else if (storeState.status === 'disconnected' || storeState.status === 'error') {
                console.info("[ChatSyncService] WebSocket disconnected or error. Resetting sync state.");
                this.webSocketConnected = false;
                this.cachePrimed = false; // Reset cachePrimed on disconnect
                this.isSyncing = false;
                this.initialSyncAttempted = false; // Reset initialSyncAttempted
                if (this.cacheStatusRequestTimeout) {
                    clearTimeout(this.cacheStatusRequestTimeout);
                    this.cacheStatusRequestTimeout = null;
                }
            }
        });
    }

    private registerWebSocketHandlers() {
        webSocketService.on('initial_sync_response', this.handleInitialSyncResponse.bind(this));
        webSocketService.on('priority_chat_ready', this.handlePriorityChatReady.bind(this));
        webSocketService.on('cache_primed', this.handleCachePrimed.bind(this));
        webSocketService.on('cache_status_response', this.handleCacheStatusResponse.bind(this)); // New handler
        webSocketService.on('chat_title_updated', this.handleChatTitleUpdated.bind(this));
        webSocketService.on('chat_draft_updated', this.handleChatDraftUpdated.bind(this));
        webSocketService.on('chat_message_added', this.handleChatMessageReceived.bind(this)); // For messages from OTHER users/AI
        webSocketService.on('chat_message_confirmed', this.handleChatMessageConfirmed.bind(this)); // For messages THIS user sent
        webSocketService.on('chat_deleted', (payload) => this.handleChatDeleted(payload as ChatDeletedPayload));
        webSocketService.on('offline_sync_complete', this.handleOfflineSyncComplete.bind(this));
        webSocketService.on('chat_content_batch_response', this.handleChatContentBatchResponse.bind(this));

        // Handlers for AI streaming events
        webSocketService.on('ai_message_update', this.handleAIMessageUpdate.bind(this));
        webSocketService.on('ai_typing_started', this.handleAITypingStarted.bind(this));
        // 'ai_message_ready' implies typing has ended for non-active chats.
        // 'ai_typing_ended' is also sent by backend with 'ai_message_ready'.
        webSocketService.on('ai_typing_ended', this.handleAITypingEnded.bind(this));
        webSocketService.on('ai_message_ready', this.handleAIMessageReady.bind(this));

        // New handlers for AI task lifecycle
        webSocketService.on('ai_task_initiated', this.handleAITaskInitiated.bind(this));
        webSocketService.on('ai_task_cancel_requested', this.handleAITaskCancelRequested.bind(this));
    }

    // --- AI Task and Stream Event Handlers ---
    private handleAITaskInitiated(payload: AITaskInitiatedPayload): void {
        console.info("[ChatSyncService] Received 'ai_task_initiated':", payload);
        this.activeAITasks.set(payload.chat_id, { taskId: payload.ai_task_id, userMessageId: payload.user_message_id });
        this.dispatchEvent(new CustomEvent('aiTaskInitiated', { detail: payload }));
    }

    private handleAIMessageUpdate(payload: AIMessageUpdatePayload): void {
        console.debug("[ChatSyncService] Received 'ai_message_update':", payload);
        this.dispatchEvent(new CustomEvent('aiMessageChunk', { detail: payload }));
        // If this is the final chunk (from Redis marker, not necessarily the actual last content chunk)
        // and it indicates interruption or completion, clear the task.
        if (payload.is_final_chunk) {
            const taskInfo = this.activeAITasks.get(payload.chat_id);
            if (taskInfo && taskInfo.taskId === payload.task_id) {
                this.activeAITasks.delete(payload.chat_id);
                this.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.task_id, status: payload.interrupted_by_revocation ? 'cancelled' : (payload.interrupted_by_soft_limit ? 'timed_out' : 'completed') } }));
                console.info(`[ChatSyncService] AI Task ${payload.task_id} for chat ${payload.chat_id} considered ended due to final chunk marker.`);
            }
        }
    }

    private handleAITypingStarted(payload: AITypingStartedPayload): void {
        console.debug("[ChatSyncService] Received 'ai_typing_started':", payload);
        aiTypingStore.setTyping(payload.chat_id, payload.user_message_id, payload.message_id, payload.mate_name);
        // DispatchEvent is kept for now in case other parts of the app listen to it directly,
        // but primary state management should move to the store.
        this.dispatchEvent(new CustomEvent('aiTypingStarted', { detail: payload }));
    }

    private handleAITypingEnded(payload: { chat_id: string, message_id: string }): void {
        console.debug("[ChatSyncService] Received 'ai_typing_ended':", payload);
        aiTypingStore.clearTyping(payload.chat_id, payload.message_id);
        // DispatchEvent is kept for now.
        this.dispatchEvent(new CustomEvent('aiTypingEnded', { detail: payload }));
    }
    
    private handleAIMessageReady(payload: AIMessageReadyPayload): void {
        console.debug("[ChatSyncService] Received 'ai_message_ready':", payload);
        this.dispatchEvent(new CustomEvent('aiMessageCompletedOnServer', { detail: payload }));
        // This event means the AI has finished generating for a non-active chat.
        // The full message will arrive via 'chat_message_added'.
        // We can clear the activeAITask if this message_id corresponds to an active task's ID.
        const taskInfo = this.activeAITasks.get(payload.chat_id);
        // AI's message_id is often the same as its task_id.
        if (taskInfo && taskInfo.taskId === payload.message_id) {
            this.activeAITasks.delete(payload.chat_id);
            this.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: payload.message_id, status: 'completed' } }));
            console.info(`[ChatSyncService] AI Task ${payload.message_id} for chat ${payload.chat_id} considered ended due to 'ai_message_ready'.`);
        }
    }

    private handleAITaskCancelRequested(payload: AITaskCancelRequestedPayload): void {
        console.info("[ChatSyncService] Received 'ai_task_cancel_requested' acknowledgement:", payload);
        // Potentially update UI to confirm cancellation was sent/processed by server.
        // If status is 'revocation_sent', the task might still send a final (empty or partial) chunk.
        // The task is truly "ended" from client perspective when the final chunk marker arrives or a timeout occurs.
        this.dispatchEvent(new CustomEvent('aiTaskCancellationAcknowledged', { detail: payload }));
        
        // If the server confirms it's already completed or not found, we can clear it.
        if (payload.status === 'already_completed' || payload.status === 'not_found') {
            const chatIdsToClear: string[] = [];
            this.activeAITasks.forEach((value, key) => {
                if (value.taskId === payload.task_id) {
                    chatIdsToClear.push(key);
                }
            });
            chatIdsToClear.forEach(chatId => {
                this.activeAITasks.delete(chatId);
                this.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: chatId, taskId: payload.task_id, status: payload.status } }));
                console.info(`[ChatSyncService] AI Task ${payload.task_id} for chat ${chatId} cleared due to cancel ack status: ${payload.status}.`);
            });
        }
    }
    // --- End AI Task and Stream Event Handlers ---

    public getActiveAITaskIdForChat(chatId: string): string | null {
        return this.activeAITasks.get(chatId)?.taskId || null;
    }

    public getActiveAIUserMessageIdForChat(chatId: string): string | null {
        return this.activeAITasks.get(chatId)?.userMessageId || null;
    }

    private async requestCacheStatus(): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] Cannot request cache status, WebSocket not connected.");
            return;
        }
        try {
            console.debug("[ChatSyncService] Sending 'request_cache_status'.");
            await webSocketService.sendMessage('request_cache_status', {});
        } catch (error) {
            console.error("[ChatSyncService] Error sending 'request_cache_status':", error);
        }
    }

    private handleCacheStatusResponse(payload: CacheStatusResponsePayload): void {
        console.info("[ChatSyncService] Received 'cache_status_response':", payload);
        if (payload.is_primed && !this.cachePrimed) { // Check !this.cachePrimed to avoid redundant ops if 'cache_primed' event also arrived
            console.info("[ChatSyncService] Cache reported as primed by server. Setting local flag and attempting sync.");
            this.cachePrimed = true;
            // It's important that attemptInitialSync checks initialSyncAttempted to prevent multiple syncs
            this.attemptInitialSync();
        } else if (!payload.is_primed) {
            console.info("[ChatSyncService] Cache reported as NOT primed by server. Will continue waiting for 'cache_primed' event.");
            // Optionally, could implement a retry mechanism for requestCacheStatus with backoff,
            // but the server-pushed 'cache_primed' event is still the primary signal.
        }
    }
    
    private attemptInitialSync(immediate_view_chat_id?: string) {
        if (this.isSyncing) {
            console.warn("[ChatSyncService] Sync is already in progress. Ignoring attemptInitialSync call.");
            return;
        }
        // Check initialSyncAttempted to prevent re-triggering if already tried for current "primed" state
        if (this.initialSyncAttempted) {
             console.warn("[ChatSyncService] Initial sync was already attempted for the current cache primed state. Ignoring attemptInitialSync call.");
             return;
        }

        if (this.webSocketConnected && this.cachePrimed) {
            console.info("[ChatSyncService] Conditions met (WS connected, cache primed). Initiating initial sync.");
            this.startInitialSync(immediate_view_chat_id);
        } else {
            let reasons = [];
            if (!this.webSocketConnected) reasons.push("WebSocket not connected");
            if (!this.cachePrimed) reasons.push("Cache not primed");
            console.info(`[ChatSyncService] Conditions not yet met for initial sync. Waiting. Reasons: ${reasons.join(', ')}`);
        }
    }

    public async startInitialSync(immediate_view_chat_id?: string): Promise<void> {
        if (this.isSyncing) {
            console.warn("[ChatSyncService] Sync already in progress. Call to startInitialSync ignored.");
            return;
        }

        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] Cannot start sync, WebSocket not connected.");
            return;
        }
        if (!this.cachePrimed) {
            console.warn("[ChatSyncService] Cannot start sync, cache not primed yet. Waiting for 'cache_primed' event.");
            return;
        }

        console.info(`[ChatSyncService] Starting initial sync... ${immediate_view_chat_id ? `for immediate_view_chat_id: ${immediate_view_chat_id}` : ''}`);
        this.isSyncing = true;
        this.initialSyncAttempted = true;

        try {
            await chatDB.init();
            const localChats = await chatDB.getAllChats();
            const chat_versions: Record<string, ChatComponentVersions> = {};
            for (const chat of localChats) {
                chat_versions[chat.chat_id] = {
                    messages_v: chat.messages_v,
                    title_v: chat.title_v,
                    draft_v: chat.draft_v || 0,
                };
            }

            const pending_message_ids: Record<string, string[]> = {};
            for (const chat of localChats) {
                const sendingMessages = chat.messages.filter(m => m.status === 'sending');
                if (sendingMessages.length > 0) {
                    pending_message_ids[chat.chat_id] = sendingMessages.map(m => m.message_id);
                }
            }

            const payload: InitialSyncRequestPayload = { chat_versions };
            if (immediate_view_chat_id) {
                payload.immediate_view_chat_id = immediate_view_chat_id;
            }
            if (Object.keys(pending_message_ids).length > 0) {
                payload.pending_message_ids = pending_message_ids;
            }

            await webSocketService.sendMessage('initial_sync_request', payload);
            console.debug("[ChatSyncService] Sent initial_sync_request with payload:", payload);

        } catch (error) {
            console.error("[ChatSyncService] Error during initial sync startup (sending request):", error);
            const errorMessage = error instanceof Error ? error.message : String(error);
            notificationStore.error(`Failed to start chat synchronization: ${errorMessage}`);
            this.isSyncing = false;
            // If sending failed, we might allow another attempt if conditions change.
            // For now, initialSyncAttempted remains true. A full disconnect/reconnect cycle will reset it.
        }
    }

    private async handleInitialSyncResponse(payload: InitialSyncResponsePayload): Promise<void> {
        console.info("[ChatSyncService] Received initial_sync_response:", payload);
        
        const transaction = chatDB.getTransaction(
            chatDB['CHATS_STORE_NAME'],
            'readwrite'
        );
        
        const chatsToUpdateInDB: Chat[] = [];
        const chatIdsToFetchMessagesFor: string[] = [];

        transaction.oncomplete = () => {
            console.info("[ChatSyncService] Initial sync DB transaction complete.");
            this.serverChatOrder = payload.server_chat_order || [];
            this.dispatchEvent(new CustomEvent('syncComplete', { detail: { serverChatOrder: this.serverChatOrder } }));
            this.isSyncing = false;

            if (chatIdsToFetchMessagesFor.length > 0) {
                console.info(`[ChatSyncService] Requesting messages for ${chatIdsToFetchMessagesFor.length} chats post initial sync.`);
                this.requestChatContentBatch(chatIdsToFetchMessagesFor);
            }
        };

        transaction.onerror = (event) => {
            console.error("[ChatSyncService] Error processing initial_sync_response transaction:", transaction.error, event);
            const errorMessage = transaction.error ? transaction.error.message : "Unknown DB transaction error";
            notificationStore.error(`Error processing server sync data: ${errorMessage}`);
            this.isSyncing = false;
        };

        try {
            if (payload.chats_to_add_or_update && payload.chats_to_add_or_update.length > 0) {
                for (const serverChatData of payload.chats_to_add_or_update) {
                    const localChat = await chatDB.getChat(serverChatData.chat_id, transaction);
                    
                    const chatToSave: Chat = {
                        chat_id: serverChatData.chat_id,
                        title: serverChatData.title ?? localChat?.title ?? 'New Chat',
                        messages_v: serverChatData.versions.messages_v,
                        title_v: serverChatData.versions.title_v,
                        draft_v: serverChatData.versions.draft_v ?? localChat?.draft_v ?? 0,
                        draft_json: serverChatData.draft_json !== undefined ? serverChatData.draft_json : localChat?.draft_json,
                        last_edited_overall_timestamp: serverChatData.last_edited_overall_timestamp,
                        unread_count: serverChatData.unread_count ?? localChat?.unread_count ?? 0,
                        messages: serverChatData.messages || localChat?.messages || [], // Initial assignment
                        createdAt: localChat?.createdAt || new Date(serverChatData.last_edited_overall_timestamp * 1000),
                        updatedAt: new Date(serverChatData.last_edited_overall_timestamp * 1000),
                    };

                    // If server didn't send messages, and local chat exists, and versions match,
                    // then any local 'sending' messages can be assumed 'synced'.
                    if (!serverChatData.messages && localChat && serverChatData.versions.messages_v === localChat.messages_v) {
                        chatToSave.messages = chatToSave.messages.map(msg => {
                            if (msg.status === 'sending') {
                                console.warn(`[ChatSyncService] Initial Sync: Correcting local message ${msg.message_id} in chat ${localChat.chat_id} from 'sending' to 'synced' as server versions match and messages were not pushed.`);
                                return { ...msg, status: 'synced' as const };
                            }
                            return msg;
                        });
                    }

                    if (serverChatData.type === 'new_chat' && !localChat) {
                        chatToSave.createdAt = new Date(serverChatData.last_edited_overall_timestamp * 1000);
                        chatToSave.messages = serverChatData.messages || [];
                        chatToSave.draft_json = serverChatData.draft_json !== undefined ? serverChatData.draft_json : null;
                        chatToSave.draft_v = serverChatData.versions.draft_v !== undefined ? serverChatData.versions.draft_v : 0;
                    }
                    chatsToUpdateInDB.push(chatToSave);
                    console.debug(`[ChatSyncService] Queued chat update for ${serverChatData.chat_id}, draft version ${chatToSave.draft_v}`);

                    // Check if messages need to be fetched
                    if (serverChatData.versions.messages_v > 0 && (!serverChatData.messages || serverChatData.messages.length === 0)) {
                        chatIdsToFetchMessagesFor.push(serverChatData.chat_id);
                    }
                }
            }
            
            await chatDB.batchProcessChatData(
                chatsToUpdateInDB,
                payload.chat_ids_to_delete || [],
                transaction
            );
            
            console.info("[ChatSyncService] Initial sync data processing queued within transaction.");

        } catch (error) {
            console.error("[ChatSyncService] Error preparing data for initial_sync_response transaction:", error);
            if (transaction && transaction.abort) { 
                try {
                    transaction.abort();
                } catch (abortError) {
                    console.error("[ChatSyncService] Error aborting transaction:", abortError);
                }
            }
            const errorMessage = error instanceof Error ? error.message : String(error);
            notificationStore.error(`Error processing server sync data: ${errorMessage}`);
            this.isSyncing = false; 
        }
    }

    private async requestChatContentBatch(chat_ids: string[]): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] Cannot request chat content batch, WebSocket not connected.");
            return;
        }
        if (chat_ids.length === 0) {
            console.debug("[ChatSyncService] No chat IDs provided for batch content request.");
            return;
        }

        const payload: RequestChatContentBatchPayload = { chat_ids };
        try {
            await webSocketService.sendMessage('request_chat_content_batch', payload);
            console.info(`[ChatSyncService] Sent 'request_chat_content_batch' for ${chat_ids.length} chats.`);
        } catch (error) {
            console.error("[ChatSyncService] Error sending 'request_chat_content_batch':", error);
            notificationStore.error("Failed to request additional chat messages from server.");
        }
    }

    private async handleChatContentBatchResponse(payload: ChatContentBatchResponsePayload): Promise<void> {
        console.info("[ChatSyncService] Received 'chat_content_batch_response':", payload);
        if (!payload.messages_by_chat_id || Object.keys(payload.messages_by_chat_id).length === 0) {
            console.info("[ChatSyncService] No messages received in batch response.");
            return;
        }

        const chatIdsWithMessages = Object.keys(payload.messages_by_chat_id);
        const transaction = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        let updatedChatCount = 0;

        transaction.oncomplete = () => {
            console.info(`[ChatSyncService] Chat content batch DB transaction complete. Updated ${updatedChatCount} chats.`);
            if (updatedChatCount > 0) {
                 // Dispatch a general event or specific events per chat
                this.dispatchEvent(new CustomEvent('chatsUpdatedWithMessages', { detail: { chatIds: chatIdsWithMessages } }));
            }
        };
        transaction.onerror = (event) => {
            console.error("[ChatSyncService] Error processing chat_content_batch_response transaction:", transaction.error, event);
            notificationStore.error("Error saving batch-fetched messages to local database.");
        };
        
        try {
            for (const chatId of chatIdsWithMessages) {
                const messages = payload.messages_by_chat_id[chatId];
                if (messages) {
                    const chat = await chatDB.getChat(chatId, transaction);
                    if (chat) {
                        chat.messages = messages; // Replace local messages with server's version
                        chat.updatedAt = new Date();
                        // messages_v should ideally come from server in this response too, or be handled carefully
                        // For now, we assume the messages_v from initial_sync_response was correct.
                        await chatDB.updateChat(chat, transaction);
                        updatedChatCount++;
                        console.debug(`[ChatSyncService] Updated messages for chat ${chatId} from batch response.`);
                        // Dispatch individual chat update event
                        this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: chatId, messagesUpdated: true } }));
                    } else {
                        console.warn(`[ChatSyncService] Chat ${chatId} not found locally when processing batch message response.`);
                    }
                }
            }
        } catch (error) {
            console.error("[ChatSyncService] Error processing chat_content_batch_response data:", error);
             if (transaction && transaction.abort) {
                try {
                    transaction.abort();
                } catch (abortError) {
                    console.error("[ChatSyncService] Error aborting transaction for batch response:", abortError);
                }
            }
        }
    }


    private handlePriorityChatReady(payload: PriorityChatReadyPayload): void {
        console.info("[ChatSyncService] Received priority_chat_ready for:", payload.chat_id);
        this.dispatchEvent(new CustomEvent('priorityChatReady', { detail: payload }));
        // Optional: Implement logic here if an early partial sync for this specific chat is desired
        // before the full 'cache_primed' signal. This would require careful handling
        // to ensure it doesn't conflict with the main sync flow.
    }

    private handleCachePrimed(payload: CachePrimedPayload): void {
        console.info("[ChatSyncService] Received cache_primed:", payload.status);
        if (payload.status === "full_sync_ready") {
            this.cachePrimed = true;
            this.dispatchEvent(new CustomEvent('cachePrimed', { detail: payload }));
            // If an initial sync hasn't been successfully started for this "primed" session, attempt it.
            // Check !isSyncing too, in case a previous attempt failed early before setting initialSyncAttempted properly or was reset.
            if (!this.initialSyncAttempted || !this.isSyncing) {
                 console.info("[ChatSyncService] Cache is primed. Attempting initial sync.");
                 this.attemptInitialSync();
            } else {
                 console.info("[ChatSyncService] Cache is primed, but initial sync already attempted or in progress.");
            }
        }
    }

    private async handleChatTitleUpdated(payload: ChatTitleUpdatedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_title_updated:", payload);
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chat = await chatDB.getChat(payload.chat_id, tx);
            if (chat) {
                chat.title = payload.data.title;
                chat.title_v = payload.versions.title_v;
                chat.updatedAt = new Date(); 
                await chatDB.updateChat(chat, tx);
                
                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id } }));
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in handleChatTitleUpdated transaction:", tx.error);
            } else {
                tx.abort(); 
            }
        } catch (error) {
            console.error("[ChatSyncService] Error in handleChatTitleUpdated:", error);
            if (tx.abort) tx.abort();
        }
    }

    private async handleChatDraftUpdated(payload: ChatDraftUpdatedPayload): Promise<void> {
        
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        
        try {
            const chat = await chatDB.getChat(payload.chat_id, tx);
            if (chat) {
                console.debug(`[ChatSyncService] Existing chat ${payload.chat_id} found for draft update. Local draft_v: ${chat.draft_v}, Incoming draft_v: ${payload.versions.draft_v}.`);
                chat.draft_json = payload.data.draft_json;
                chat.draft_v = payload.versions.draft_v;
                chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
                chat.updatedAt = new Date();
                
                // Log a deep copy of the chat object to avoid logging future modifications if the object is mutated elsewhere.
                console.debug(`[ChatSyncService] Chat object being prepared for DB update (chat_id: ${payload.chat_id}):`);

                await chatDB.updateChat(chat, tx);
                console.debug(`[ChatSyncService] Called chatDB.updateChat for ${payload.chat_id}. Local chat object's draft_v is now ${chat.draft_v}. Waiting for transaction completion.`);
            } else {
                console.warn(`[ChatSyncService] Chat ${payload.chat_id} not found when handling chat_draft_updated broadcast. Creating new chat entry for draft.`);
                const newChatForDraft: Chat = {
                    chat_id: payload.chat_id,
                    title: '', // Chats with only drafts should have no title
                    messages: [],
                    messages_v: 0,
                    title_v: 0,
                    draft_json: payload.data.draft_json,
                    draft_v: payload.versions.draft_v,
                    last_edited_overall_timestamp: payload.last_edited_overall_timestamp,
                    unread_count: 0,
                    createdAt: new Date(payload.last_edited_overall_timestamp * 1000),
                    updatedAt: new Date(payload.last_edited_overall_timestamp * 1000),
                };
                console.debug("[ChatSyncService] Attempting to add new chat for draft:", JSON.stringify(newChatForDraft));
                try {
                    await chatDB.addChat(newChatForDraft, tx);
                    console.info(`[ChatSyncService] Successfully called chatDB.addChat for new draft's chat_id: ${payload.chat_id}. Waiting for transaction completion.`);
                } catch (addError) {
                    console.error(`[ChatSyncService] Error directly from chatDB.addChat for chat_id ${payload.chat_id}:`, addError);
                    // This error should also be caught by the outer try-catch, which will abort the transaction.
                    // No need to abort tx here explicitly unless the outer catch is missed.
                    throw addError; // Re-throw to be caught by the main handler's catch block
                }
            }

            tx.oncomplete = () => {
                console.info(`[ChatSyncService] Transaction for handleChatDraftUpdated (chat_id: ${payload.chat_id}) completed successfully.`);
                this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, type: 'draft' } }));
            };
            tx.onerror = () => {
                console.error(`[ChatSyncService] Error in handleChatDraftUpdated transaction for chat_id ${payload.chat_id}:`, tx.error);
            };

        } catch (error) {
            console.error(`[ChatSyncService] Error in handleChatDraftUpdated (outer catch) for chat_id ${payload.chat_id}:`, error);
            if (tx && tx.abort && !tx.error) { // Check if tx exists and not already errored
                console.warn(`[ChatSyncService] Aborting transaction for chat_id ${payload.chat_id} due to outer catch.`);
                tx.abort();
            }
        }
    }

    private async handleChatMessageReceived(payload: ChatMessageReceivedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_message_added (broadcast from server for other users/AI):", payload);
        
        // Standardize sender field from sender_name to sender if present
        // The server sends sender_name, but frontend components expect 'sender'.
        const standardizedMessage = { ...payload.message } as Message & { sender_name?: string };
        if (standardizedMessage.sender_name && !standardizedMessage.sender) {
            standardizedMessage.sender = standardizedMessage.sender_name;
            delete standardizedMessage.sender_name; // Clean up
        }

        // If this message is from the AI and corresponds to an active task, clear the task.
        const taskInfo = this.activeAITasks.get(payload.chat_id);
        if (standardizedMessage.sender !== 'user' && taskInfo && taskInfo.taskId === standardizedMessage.message_id) {
            this.activeAITasks.delete(payload.chat_id);
            this.dispatchEvent(new CustomEvent('aiTaskEnded', { detail: { chatId: payload.chat_id, taskId: taskInfo.taskId, status: 'completed_message_received' } }));
            console.info(`[ChatSyncService] AI Task ${taskInfo.taskId} for chat ${payload.chat_id} considered ended as full AI message was received.`);
        }

        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chat = await chatDB.getChat(payload.chat_id, tx);
            if (chat) {
                const messageExists = chat.messages.some(m => m.message_id === standardizedMessage.message_id);
                if (!messageExists) {
                    chat.messages.push(standardizedMessage);
                } else { // Message already exists, update it
                    const msgIndex = chat.messages.findIndex(m => m.message_id === standardizedMessage.message_id);
                    chat.messages[msgIndex] = standardizedMessage;
                }
                chat.messages_v = payload.versions.messages_v;
                chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
                chat.updatedAt = new Date();
                await chatDB.updateChat(chat, tx);

                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, newMessage: standardizedMessage } }));
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in handleChatMessageReceived transaction:", tx.error);
            } else {
                console.warn(`[ChatSyncService] Chat ${payload.chat_id} not found for incoming message. This might be a new chat initiated by another client/AI.`);
                // Potentially create a new chat shell here if the design allows for it.
                // For now, we'll assume initial_sync or another mechanism handles new chat creation.
                tx.abort();
            }
        } catch (error) {
            console.error("[ChatSyncService] Error in handleChatMessageReceived:", error);
            if (tx.abort) tx.abort();
        }
    }

    private async handleChatMessageConfirmed(payload: ChatMessageConfirmedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_message_confirmed for this client's message:", payload);
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chat = await chatDB.getChat(payload.chat_id, tx);
            if (chat) {
                const messageIndex = chat.messages.findIndex(m => m.message_id === payload.message_id);
                if (messageIndex !== -1) {
                    chat.messages[messageIndex].status = 'synced';
                    // Optionally update the message content if server sent it back:
                    // if (payload.message) chat.messages[messageIndex] = payload.message;
                } else {
                    console.warn(`[ChatSyncService] Confirmed message ${payload.message_id} not found in local chat ${payload.chat_id}. This should not happen.`);
                    // Potentially fetch the message or handle as an error.
                }
                chat.messages_v = payload.new_messages_v;
                chat.last_edited_overall_timestamp = payload.new_last_edited_overall_timestamp;
                chat.updatedAt = new Date();
                await chatDB.updateChat(chat, tx);

                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('messageStatusChanged', {
                        detail: {
                            chatId: payload.chat_id,
                            messageId: payload.message_id,
                            status: 'synced',
                            chat // Send the updated chat object
                        }
                    }));
                    // Also dispatch chatUpdated so the main list can refresh
                    this.dispatchEvent(new CustomEvent('chatUpdated', {
                        detail: {
                            chat_id: payload.chat_id,
                            chat: chat // Pass the updated chat object
                        }
                    }));
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in handleChatMessageConfirmed transaction:", tx.error);
            } else {
                console.warn(`[ChatSyncService] Chat ${payload.chat_id} not found for message confirmation. This should not happen.`);
                tx.abort();
            }
        } catch (error) {
            console.error("[ChatSyncService] Error in handleChatMessageConfirmed:", error);
            if (tx.abort) tx.abort();
        }
    }


    private async handleChatDeleted(payload: ChatDeletedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_deleted:", payload);
        if (payload.tombstone) {
            const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
            try {
                await chatDB.deleteChat(payload.chat_id, tx);

                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: payload.chat_id } }));
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in handleChatDeleted transaction:", tx.error);
            } catch (error) {
                console.error("[ChatSyncService] Error in handleChatDeleted:", error);
                if (tx.abort) tx.abort();
            }
        }
    }
    
    public async sendUpdateTitle(chat_id: string, new_title: string) {
        const payload: UpdateTitlePayload = { chat_id, new_title };
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chat = await chatDB.getChat(chat_id, tx);
            if (chat) {
                chat.title = new_title;
                chat.title_v = (chat.title_v || 0) + 1; 
                chat.updatedAt = new Date();
                await chatDB.updateChat(chat, tx);
                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id } })); 
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in sendUpdateTitle optimistic transaction:", tx.error);
            } else {
                tx.abort();
            }
        } catch (error) {
            console.error("[ChatSyncService] Error in sendUpdateTitle optimistic update:", error);
            if (tx.abort) tx.abort();
        }
        await webSocketService.sendMessage('update_title', payload);
    }

    public async sendUpdateDraft(chat_id: string, draft_json: TiptapJSON | null) {
        const payload: UpdateDraftPayload = { chat_id, draft_json };
        
        try {
            const updatedChat = await chatDB.saveCurrentUserChatDraft(chat_id, draft_json);
            if (updatedChat) {
                console.debug(`[ChatSyncService] Optimistically saved user draft for chat ${chat_id}, new version ${updatedChat.draft_v}`);
                this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id, type: 'draft', draft: updatedChat } }));
            }
        } catch (error) {
            console.error(`[ChatSyncService] Error optimistically saving draft for chat ${chat_id}:`, error);
        }
        
        await webSocketService.sendMessage('update_draft', payload);
        console.debug(`[ChatSyncService] Sent update_draft for chat ${chat_id}`);
    }

    public async sendDeleteDraft(chat_id: string) {
        const payload: DeleteDraftPayload = { chatId: chat_id }; // Changed to use chatId
        try {
            const chatBeforeClear = await chatDB.getChat(chat_id); // Get chat state BEFORE clearing
            const versionBeforeEdit = chatBeforeClear?.draft_v || 0; // Store draft_v before clearing

            const clearedDraftChat = await chatDB.clearCurrentUserChatDraft(chat_id); // This will apply the new logic for draft_v increment

            if (clearedDraftChat) {
                console.debug(`[ChatSyncService] Optimistically cleared user draft for chat ${chat_id}, new draft_v: ${clearedDraftChat.draft_v}`);
                this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id, type: 'draft_deleted', chat: clearedDraftChat } }));
            } else {
                 console.warn(`[ChatSyncService] Chat not found or draft already clear for chat_id: ${chat_id} during optimistic delete draft.`);
            }

            if (get(websocketStatus).status === 'connected') {
                // The payload to the server for 'delete_draft' doesn't include the version.
                // The server likely uses the chat_id to find the chat and its current draft_v, then increments it.
                await webSocketService.sendMessage('delete_draft', payload);
                console.debug(`[ChatSyncService] Sent delete_draft for chat ${chat_id}`);
            } else {
                console.info(`[ChatSyncService] WebSocket disconnected. Queuing draft deletion for ${chat_id}.`);
                // For offline change, version_before_edit should be the one before this whole operation.
                const offlineChange: Omit<OfflineChange, 'change_id'> = {
                    chat_id: chat_id,
                    type: 'delete_draft',
                    value: null, // Deleting draft means content becomes null
                    version_before_edit: versionBeforeEdit, // Use the version captured before clearing
                };
                await this.queueOfflineChange(offlineChange);
            }
        } catch (error) {
            console.error(`[ChatSyncService] Error sending delete draft for chat ${chat_id}:`, error);
            const errorMessage = error instanceof Error ? error.message : String(error);
            notificationStore.error(`Failed to delete draft: ${errorMessage}`);
        }
    }
    
    public async sendDeleteChat(chat_id: string) {
        const payload: DeleteChatPayload = { chatId: chat_id };
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            await chatDB.deleteChat(chat_id, tx);
            tx.oncomplete = () => {
                this.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id } })); 
            };
            tx.onerror = () => console.error("[ChatSyncService] Error in sendDeleteChat optimistic transaction:", tx.error);
        } catch (error) {
            console.error("[ChatSyncService] Error in sendDeleteChat optimistic update:", error);
            if (tx.abort) tx.abort();
        }
        await webSocketService.sendMessage('delete_chat', payload);
    }

    public async sendNewMessage(message: Message): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] WebSocket not connected. Cannot send new message. It should be saved locally and synced later if offline handling is robust.");
            // Potentially queue this as an offline change if a more complex offline strategy is needed for new messages.
            // For now, we assume the message is in IndexedDB and will be part of a broader sync or handled by an explicit "retry failed messages" mechanism.
            // Alternatively, throw an error to indicate immediate failure to send.
            // throw new Error("WebSocket not connected. Message send failed.");
            // For now, just log and return. The message is in IDB with 'sending' status.
            return;
        }

        const payload: SendChatMessagePayload = {
            chat_id: message.chat_id,
            message: message, // Send the full message object as created by the client
        };

        try {
            // The message type should be distinct for client sending a new message vs server broadcasting one.
            // Let's use 'chat_message_added' for client -> server.
            // Server will respond with 'chat_message_confirmed' or an error.
            // Server will broadcast 'chat_message_added' to OTHER clients.
            await webSocketService.sendMessage('chat_message_added', payload);
            console.info(`[ChatSyncService] Sent 'chat_message_added' for message_id: ${message.message_id} in chat_id: ${message.chat_id}`);
            // The message status in IndexedDB remains 'sending'.
            // It will be updated to 'synced' upon receiving 'chat_message_confirmed' from the server.
        } catch (error) {
            console.error(`[ChatSyncService] Error sending 'chat_message_added' for message_id: ${message.message_id}:`, error);
            // Update the message status in IndexedDB to 'failed'.
            try {
                const chat = await chatDB.getChat(message.chat_id);
                if (chat) {
                    const updatedMessage = { ...message, status: 'failed' as const };
                    await chatDB.updateMessageInChat(message.chat_id, updatedMessage);
                    this.dispatchEvent(new CustomEvent('messageStatusChanged', { 
                        detail: { 
                            chatId: message.chat_id, 
                            messageId: message.message_id, 
                            status: 'failed',
                            chat: await chatDB.getChat(message.chat_id) // fetch updated chat
                        } 
                    }));
                }
            } catch (dbError) {
                console.error(`[ChatSyncService] Error updating message status to 'failed' in DB for ${message.message_id}:`, dbError);
            }
        }
    }

    public async sendSetActiveChat(chatId: string | null): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] WebSocket not connected. Cannot send 'set_active_chat'.");
            return;
        }
        const payload: SetActiveChatPayload = { chat_id: chatId };
        try {
            await webSocketService.sendMessage('set_active_chat', payload);
            console.info(`[ChatSyncService] Sent 'set_active_chat' for chat_id: ${chatId}`);
        } catch (error) {
            console.error(`[ChatSyncService] Error sending 'set_active_chat' for chat_id: ${chatId}:`, error);
        }
    }

    public async sendCancelAiTask(taskId: string): Promise<void> {
        if (!this.webSocketConnected) {
            console.warn("[ChatSyncService] WebSocket not connected. Cannot send 'cancel_ai_task'.");
            notificationStore.error("Cannot cancel AI task: Not connected to server.");
            return;
        }
        if (!taskId) {
            console.warn("[ChatSyncService] No task ID provided for cancellation.");
            return;
        }

        const payload: CancelAITaskPayload = { task_id: taskId };
        try {
            await webSocketService.sendMessage('cancel_ai_task', payload);
            console.info(`[ChatSyncService] Sent 'cancel_ai_task' for task_id: ${taskId}`);
            // UI can show "Cancellation requested..."
            // Actual removal from activeAITasks will happen upon server ack or final chunk.
        } catch (error) {
            console.error(`[ChatSyncService] Error sending 'cancel_ai_task' for task_id: ${taskId}:`, error);
            notificationStore.error("Failed to send AI task cancellation request.");
        }
    }

    // --- Offline Change Handling ---
    public async queueOfflineChange(change: Omit<OfflineChange, 'change_id'>): Promise<void> {
        const fullChange: OfflineChange = {
            ...change,
            change_id: crypto.randomUUID()
        };
        await chatDB.addOfflineChange(fullChange); 
        console.info("[ChatSyncService] Queued offline change:", fullChange);
        notificationStore.info(`Change for chat saved offline. Will sync when reconnected.`, 3000);
    }

    public async sendOfflineChanges(): Promise<void> {
        if (get(websocketStatus).status !== 'connected') {
            console.warn("[ChatSyncService] Cannot send offline changes, WebSocket not connected.");
            return;
        }
        const changes = await chatDB.getOfflineChanges(); 
        if (changes.length === 0) {
            console.info("[ChatSyncService] No offline changes to send.");
            return;
        }
        console.info(`[ChatSyncService] Sending ${changes.length} offline changes...`);
        notificationStore.info(`Attempting to sync ${changes.length} offline change(s)...`);
        const payload: SyncOfflineChangesPayload = { changes };
        await webSocketService.sendMessage('sync_offline_changes', payload);
    }

    private async handleOfflineSyncComplete(payload: OfflineSyncCompletePayload): Promise<void> {
        console.info("[ChatSyncService] Received offline_sync_complete:", payload);
        const changes = await chatDB.getOfflineChanges(); 
        const tx = chatDB.getTransaction(chatDB['OFFLINE_CHANGES_STORE_NAME'], 'readwrite');
        try {
            for (const change of changes) {
                await chatDB.deleteOfflineChange(change.change_id, tx);
            }
            tx.oncomplete = () => {
                console.info("[ChatSyncService] Cleared local offline change queue after sync_offline_complete.");
            };
            tx.onerror = () => console.error("[ChatSyncService] Error clearing offline changes post-sync:", tx.error);
        } catch (error) {
            console.error("[ChatSyncService] Error in handleOfflineSyncComplete transaction:", error);
            if (tx.abort) tx.abort();
        }

        if (payload.errors > 0) {
            notificationStore.error(`Offline sync: ${payload.errors} changes could not be applied by the server.`);
        }
        if (payload.conflicts > 0) {
            notificationStore.warning(`Offline sync: ${payload.conflicts} changes had conflicts. Your view has been updated.`);
        }
        if (payload.errors === 0 && payload.conflicts === 0 && payload.processed > 0) {
            notificationStore.success(`${payload.processed} offline changes synced successfully.`);
        }
        this.dispatchEvent(new CustomEvent('offlineSyncProcessed', { detail: payload }));
    }
}

export const chatSyncService = new ChatSynchronizationService();
