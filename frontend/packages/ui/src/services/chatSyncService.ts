// frontend/packages/ui/src/services/chatSyncService.ts
// Handles chat data synchronization between client and server via WebSockets.
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { websocketStatus, type WebSocketStatus } from '../stores/websocketStatusStore';
import { notificationStore } from '../stores/notificationStore'; // Import notification store
import type { ChatComponentVersions, OfflineChange, TiptapJSON, Message, Chat } from '../types/chat';
// UserChatDraft import is removed as it's integrated into Chat type
import { get } from 'svelte/store';

// Payloads for WebSocket messages (mirroring server expectations)
interface InitialSyncRequestPayload {
    chat_versions: Record<string, ChatComponentVersions>;
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
    chat_id: string;
}

// === Client to Server ===
// (Existing client to server payloads)
interface RequestCacheStatusPayload { // New: Client requests current cache status
    // No payload needed, just the type
}


// === Server to Client ===
// (Existing server to client payloads)
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
        messages?: Message[];
    }>;
    server_chat_order: string[];
    sync_completed_at: string;
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

interface ChatMessageReceivedPayload {
    event: string; // "chat_message_received"
    chat_id: string;
    message: Message; // The new message object
    versions: { messages_v: number };
    last_edited_overall_timestamp: number;
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
        webSocketService.on('chat_message_received', this.handleChatMessageReceived.bind(this));
        webSocketService.on('chat_deleted', (payload) => this.handleChatDeleted(payload as ChatDeletedPayload));
        webSocketService.on('offline_sync_complete', this.handleOfflineSyncComplete.bind(this));
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

            const payload: InitialSyncRequestPayload = { chat_versions };
            if (immediate_view_chat_id) {
                payload.immediate_view_chat_id = immediate_view_chat_id;
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

        transaction.oncomplete = () => {
            console.info("[ChatSyncService] Initial sync DB transaction complete.");
            this.serverChatOrder = payload.server_chat_order || [];
            this.dispatchEvent(new CustomEvent('syncComplete', { detail: { serverChatOrder: this.serverChatOrder } }));
            this.isSyncing = false;
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
                        messages: serverChatData.messages || localChat?.messages || [],
                        createdAt: localChat?.createdAt || new Date(serverChatData.last_edited_overall_timestamp * 1000),
                        updatedAt: new Date(serverChatData.last_edited_overall_timestamp * 1000),
                    };

                    if (serverChatData.type === 'new_chat' && !localChat) {
                        chatToSave.createdAt = new Date(serverChatData.last_edited_overall_timestamp * 1000);
                        chatToSave.messages = serverChatData.messages || [];
                        chatToSave.draft_json = serverChatData.draft_json !== undefined ? serverChatData.draft_json : null;
                        chatToSave.draft_v = serverChatData.versions.draft_v !== undefined ? serverChatData.versions.draft_v : 0;
                    }
                    chatsToUpdateInDB.push(chatToSave);
                    console.debug(`[ChatSyncService] Queued chat update for ${serverChatData.chat_id}, draft version ${chatToSave.draft_v}`);
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
                    title: 'New Chat (from draft)',
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
        console.info("[ChatSyncService] Received chat_message_received:", payload);
        const tx = chatDB.getTransaction(chatDB['CHATS_STORE_NAME'], 'readwrite');
        try {
            const chat = await chatDB.getChat(payload.chat_id, tx);
            if (chat) {
                const messageExists = chat.messages.some(m => m.message_id === payload.message.message_id);
                if (!messageExists) {
                    chat.messages.push(payload.message);
                } else {
                    const msgIndex = chat.messages.findIndex(m => m.message_id === payload.message.message_id);
                    chat.messages[msgIndex] = payload.message;
                }
                chat.messages_v = payload.versions.messages_v;
                chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
                chat.updatedAt = new Date();
                await chatDB.updateChat(chat, tx);

                tx.oncomplete = () => {
                    this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, newMessage: payload.message } }));
                };
                tx.onerror = () => console.error("[ChatSyncService] Error in handleChatMessageReceived transaction:", tx.error);
            } else {
                tx.abort();
            }
        } catch (error) {
            console.error("[ChatSyncService] Error in handleChatMessageReceived:", error);
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
        const payload: DeleteDraftPayload = { chat_id };
        try {
            const clearedDraftChat = await chatDB.clearCurrentUserChatDraft(chat_id);
            if (clearedDraftChat) {
                console.debug(`[ChatSyncService] Optimistically cleared user draft for chat ${chat_id}`);
                this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id, type: 'draft_deleted' } }));
            } else {
                 console.warn(`[ChatSyncService] Chat not found or draft already clear for chat_id: ${chat_id} during optimistic delete draft.`);
            }

            if (get(websocketStatus).status === 'connected') {
                await webSocketService.sendMessage('delete_draft', payload);
                console.debug(`[ChatSyncService] Sent delete_draft for chat ${chat_id}`);
            } else {
                console.info(`[ChatSyncService] WebSocket disconnected. Queuing draft deletion for ${chat_id}.`);
                const chat = await chatDB.getChat(chat_id);
                const offlineChange: Omit<OfflineChange, 'change_id'> = {
                    chat_id: chat_id, type: 'delete_draft', value: null, version_before_edit: chat?.draft_v || 0,
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