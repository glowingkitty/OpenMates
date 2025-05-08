import { chatDB } from './db';
import { webSocketService } from './websocketService';
import { websocketStatus, type WebSocketStatus } from '../stores/websocketStatusStore';
import { notificationStore } from '../stores/notificationStore'; // Import notification store
import type { ChatComponentVersions, OfflineChange, TiptapJSON, Message, ChatListItem, Chat } from '../types/chat';
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

// Payloads from Server
interface PriorityChatReadyPayload {
    chat_id: string;
}

interface CachePrimedPayload {
    status: "full_sync_ready";
}

export interface InitialSyncResponsePayload {
    chat_ids_to_delete: string[];
    chats_to_add_or_update: Array<{
        chat_id: string;
        versions: ChatComponentVersions;
        last_edited_overall_timestamp: number;
        type: 'new_chat' | 'updated_chat'; // Indicates if it's entirely new or just needs component updates
        // Optional fields, present if 'new_chat' or if component changed
        title?: string;
        draft_json?: TiptapJSON | null;
        unread_count?: number;
        // Messages might be sent for priority chat or if server decides to push some for new chats
        messages?: Message[]; 
    }>;
    server_chat_order: string[]; // Full ordered list of chat_ids from server
    sync_completed_at: string; // ISO timestamp
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
    versions: { draft_v: number };
    last_edited_overall_timestamp: number;
}

interface ChatMessageReceivedPayload {
    // Based on backend message_received_handler.py and chat_sync_architecture.md Section 8
    // This structure might need refinement based on the actual broadcast from the server.
    event: string; // "chat_message_received"
    chat_id: string;
    message: Message; // The new message object
    versions: { messages_v: number };
    last_edited_overall_timestamp: number;
}

interface ChatDeletedPayload {
    // Based on backend delete_chat_handler.py
    type: string; // "chat_deleted"
    payload: {
        chat_id: string;
        tombstone: boolean; // Should be true
    };
}

interface OfflineSyncCompletePayload {
    processed: number;
    conflicts: number;
    errors: number;
}


class ChatSynchronizationService extends EventTarget {
    private isSyncing = false;
    private serverChatOrder: string[] = [];

    constructor() {
        super();
        this.registerWebSocketHandlers();
        // Listen to WebSocket status changes to trigger sync on reconnect
        websocketStatus.subscribe(storeState => {
            if (storeState.status === 'connected' && !this.isSyncing) {
                console.info("[ChatSyncService] WebSocket connected. Initiating sync.");
                this.startInitialSync();
            }
        });
    }

    private registerWebSocketHandlers() {
        webSocketService.on('initial_sync_response', this.handleInitialSyncResponse.bind(this));
        webSocketService.on('priority_chat_ready', this.handlePriorityChatReady.bind(this));
        webSocketService.on('cache_primed', this.handleCachePrimed.bind(this));
        webSocketService.on('chat_title_updated', this.handleChatTitleUpdated.bind(this));
        webSocketService.on('chat_draft_updated', this.handleChatDraftUpdated.bind(this));
        webSocketService.on('chat_message_received', this.handleChatMessageReceived.bind(this));
        webSocketService.on('chat_deleted', (payload) => this.handleChatDeleted(payload as ChatDeletedPayload)); // Cast needed due to generic handler
        webSocketService.on('offline_sync_complete', this.handleOfflineSyncComplete.bind(this));
    }

    public async startInitialSync(immediate_view_chat_id?: string): Promise<void> {
        if (this.isSyncing) {
            console.warn("[ChatSyncService] Sync already in progress.");
            return;
        }
        if (get(websocketStatus).status !== 'connected') {
            console.warn("[ChatSyncService] Cannot start sync, WebSocket not connected.");
            return;
        }

        console.info("[ChatSyncService] Starting initial sync...");
        this.isSyncing = true;
        try {
            await chatDB.init(); // Ensure DB is initialized
            const localChats = await chatDB.getAllChats();
            const chat_versions: Record<string, ChatComponentVersions> = {};
            localChats.forEach(chat => {
                chat_versions[chat.chat_id] = {
                    messages_v: chat.messages_v,
                    draft_v: chat.draft_v,
                    title_v: chat.title_v,
                };
            });

            const payload: InitialSyncRequestPayload = { chat_versions };
            if (immediate_view_chat_id) {
                payload.immediate_view_chat_id = immediate_view_chat_id;
            }

            await webSocketService.sendMessage('initial_sync_request', payload);
            console.debug("[ChatSyncService] Sent initial_sync_request with payload:", payload);

        } catch (error) {
            console.error("[ChatSyncService] Error during initial sync startup:", error);
            const errorMessage = error instanceof Error ? error.message : String(error);
            notificationStore.error(`Failed to start chat synchronization: ${errorMessage}`);
            this.isSyncing = false; // Reset on error
        }
        // isSyncing will be set to false in handleInitialSyncResponse or on error
    }

    private async handleInitialSyncResponse(payload: InitialSyncResponsePayload): Promise<void> {
        console.info("[ChatSyncService] Received initial_sync_response:", payload);
        try {
            // 1. Handle Deletions
            if (payload.chat_ids_to_delete && payload.chat_ids_to_delete.length > 0) {
                console.debug("[ChatSyncService] Deleting chats from local DB:", payload.chat_ids_to_delete);
                // await chatDB.batchUpdateChats([], payload.chat_ids_to_delete); // More efficient
                for (const chatId of payload.chat_ids_to_delete) {
                    await chatDB.deleteChat(chatId);
                }
            }

            // 2. Handle Additions/Updates
            const updatesForDB: Array<Partial<Chat> & { chat_id: string }> = [];
            if (payload.chats_to_add_or_update && payload.chats_to_add_or_update.length > 0) {
                for (const serverChat of payload.chats_to_add_or_update) {
                    const localChat = await chatDB.getChat(serverChat.chat_id);
                    let chatToSave: Partial<Chat> & { chat_id: string } = {
                        chat_id: serverChat.chat_id,
                        title: serverChat.title,
                        draft_content: serverChat.draft_json,
                        unread_count: serverChat.unread_count,
                        messages_v: serverChat.versions.messages_v,
                        draft_v: serverChat.versions.draft_v,
                        title_v: serverChat.versions.title_v,
                        last_edited_overall_timestamp: serverChat.last_edited_overall_timestamp,
                        // Ensure messages are handled correctly
                        messages: serverChat.messages || (localChat?.messages || []), // Keep local messages if server doesn't send
                        updatedAt: new Date(serverChat.last_edited_overall_timestamp * 1000), // Convert to Date
                    };

                    if (!localChat || serverChat.type === 'new_chat') {
                        // For new chats, set createdAt and ensure all versions are from server
                        chatToSave.createdAt = new Date(serverChat.last_edited_overall_timestamp * 1000); // Or a more specific creation timestamp if available
                        // If it's truly new, messages should ideally come from serverChat.messages
                        chatToSave.messages = serverChat.messages || [];
                    } else {
                        // Merge with existing local chat, preferring server versions
                        // but keeping local messages if server didn't send any for this update
                        chatToSave.createdAt = localChat.createdAt; // Keep original creation date
                        // More sophisticated message merging might be needed if server sends partial message updates here
                    }
                    updatesForDB.push(chatToSave);
                }
                 await chatDB.batchUpdateChats(updatesForDB, []);
            }
            
            this.serverChatOrder = payload.server_chat_order || [];

            console.info("[ChatSyncService] Initial sync processing complete. Dispatching update.");
            this.dispatchEvent(new CustomEvent('syncComplete', { detail: { serverChatOrder: this.serverChatOrder } }));

        } catch (error) {
            console.error("[ChatSyncService] Error processing initial_sync_response:", error);
            const errorMessage = error instanceof Error ? error.message : String(error);
            notificationStore.error(`Error processing server sync data: ${errorMessage}`);
        } finally {
            this.isSyncing = false;
        }
    }

    private handlePriorityChatReady(payload: PriorityChatReadyPayload): void {
        console.info("[ChatSyncService] Received priority_chat_ready for:", payload.chat_id);
        // UI can listen to this to know when it's safe to fully render the priority chat
        this.dispatchEvent(new CustomEvent('priorityChatReady', { detail: payload }));
    }

    private handleCachePrimed(payload: CachePrimedPayload): void {
        console.info("[ChatSyncService] Received cache_primed:", payload.status);
        // UI can listen to this to know the general sync state
        this.dispatchEvent(new CustomEvent('cachePrimed', { detail: payload }));
    }

    private async handleChatTitleUpdated(payload: ChatTitleUpdatedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_title_updated:", payload);
        const chat = await chatDB.getChat(payload.chat_id);
        if (chat) {
            chat.title = payload.data.title;
            chat.title_v = payload.versions.title_v;
            chat.updatedAt = new Date(); // Reflect the update time locally
            // last_edited_overall_timestamp is NOT updated by title changes as per spec
            await chatDB.updateChat(chat);
            this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id } }));
        }
    }

    private async handleChatDraftUpdated(payload: ChatDraftUpdatedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_draft_updated:", payload);
        const chat = await chatDB.getChat(payload.chat_id);
        if (chat) {
            chat.draft_content = payload.data.draft_json;
            chat.draft_v = payload.versions.draft_v;
            chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
            chat.updatedAt = new Date(); // Reflect the update time locally
            await chatDB.updateChat(chat);
            this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id } }));
        }
    }

    private async handleChatMessageReceived(payload: ChatMessageReceivedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_message_received:", payload);
        const chat = await chatDB.getChat(payload.chat_id);
        if (chat) {
            // Avoid duplicate messages if client already added it optimistically
            const messageExists = chat.messages.some(m => m.message_id === payload.message.message_id);
            if (!messageExists) {
                chat.messages.push(payload.message);
            } else {
                // Optionally update existing message if server sends more complete data
                const msgIndex = chat.messages.findIndex(m => m.message_id === payload.message.message_id);
                chat.messages[msgIndex] = payload.message;
            }
            chat.messages_v = payload.versions.messages_v;
            chat.last_edited_overall_timestamp = payload.last_edited_overall_timestamp;
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat);
            this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: payload.chat_id, newMessage: payload.message } }));
        }
    }

    private async handleChatDeleted(payload: ChatDeletedPayload): Promise<void> {
        console.info("[ChatSyncService] Received chat_deleted:", payload);
        if (payload.payload.tombstone) {
            await chatDB.deleteChat(payload.payload.chat_id);
            this.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: payload.payload.chat_id } }));
        }
    }
    
    public async sendUpdateTitle(chat_id: string, new_title: string) {
        const payload: UpdateTitlePayload = { chat_id, new_title };
        // Optimistically update local DB
        const chat = await chatDB.getChat(chat_id);
        if (chat) {
            chat.title = new_title;
            chat.title_v = (chat.title_v || 0) + 1; // Increment local version
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat);
            this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id } })); // Notify UI
        }
        await webSocketService.sendMessage('update_title', payload);
    }

    public async sendUpdateDraft(chat_id: string, draft_json: TiptapJSON | null) {
        const payload: UpdateDraftPayload = { chat_id, draft_json };
         // Optimistically update local DB
        const chat = await chatDB.getChat(chat_id);
        if (chat) {
            chat.draft_content = draft_json;
            chat.draft_v = (chat.draft_v || 0) + 1; // Increment local version
            chat.last_edited_overall_timestamp = Math.floor(Date.now() / 1000);
            chat.updatedAt = new Date();
            await chatDB.updateChat(chat);
            this.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id } })); // Notify UI
        }
        await webSocketService.sendMessage('update_draft', payload);
    }
    
    public async sendDeleteChat(chat_id: string) {
        const payload: DeleteChatPayload = { chatId: chat_id };
        // Optimistically update local DB
        await chatDB.deleteChat(chat_id);
        this.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id } })); // Notify UI
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
        // This is a simple handler. The spec implies server handles conflicts and broadcasts updates.
        // Client might need to re-fetch/re-sync if there were significant conflicts.
        // For now, we assume the server's broadcasts after processing offline changes will correct any local state.
        // We should clear the processed changes from the local queue.
        // A more robust implementation would involve the server sending back IDs of processed/conflicted changes.
        // For now, let's assume all sent changes are "processed" in some way and clear the queue.
        const changes = await chatDB.getOfflineChanges();
        for (const change of changes) {
            await chatDB.deleteOfflineChange(change.change_id);
        }
        console.info("[ChatSyncService] Cleared local offline change queue after sync_offline_complete.");
        // Potentially trigger a fresh initial sync if there were errors or many conflicts
        if (payload.errors > 0) {
            notificationStore.error(`Offline sync: ${payload.errors} changes could not be applied by the server.`);
            console.warn(`[ChatSyncService] Offline sync had ${payload.errors} errors.`);
        }
        if (payload.conflicts > 0) {
            notificationStore.warning(`Offline sync: ${payload.conflicts} changes had conflicts and were not applied. Your view has been updated with the latest server data.`);
            console.warn(`[ChatSyncService] Offline sync had ${payload.conflicts} conflicts.`);
        }
        if (payload.errors === 0 && payload.conflicts === 0 && payload.processed > 0) {
            notificationStore.success(`${payload.processed} offline changes synced successfully.`);
        } else if (payload.errors === 0 && payload.conflicts === 0 && payload.processed === 0) {
            // Potentially no message if nothing was processed and no errors/conflicts, or a gentle info
            // console.info("[ChatSyncService] Offline sync processed: 0 changes, 0 errors, 0 conflicts.");
        }
        // Consider re-sync if there were issues
        if (payload.errors > 0 || payload.conflicts > 0) {
            // this.startInitialSync(); // Or a more targeted re-sync
        }
        this.dispatchEvent(new CustomEvent('offlineSyncProcessed', { detail: payload }));
    }
}

export const chatSyncService = new ChatSynchronizationService();