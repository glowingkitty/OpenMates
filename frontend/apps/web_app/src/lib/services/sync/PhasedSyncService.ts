// frontend/apps/web_app/src/lib/services/sync/PhasedSyncService.ts
import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import { db } from '$lib/services/database/DatabaseService';
import { encryptionService } from '$lib/services/encryption/EncryptionService';
import { websocketService } from '$lib/services/websocket/WebSocketService';
import type { Chat, Message, SyncPhase, SyncStatus } from '$lib/types/sync';

/**
 * Phased Sync Service
 * 
 * Implements the 3-phase sync architecture from sync.md:
 * - Phase 1: Last opened chat (immediate priority)
 * - Phase 2: Last 20 updated chats (quick access)  
 * - Phase 3: Last 100 updated chats (full sync)
 */
export class PhasedSyncService {
    private static instance: PhasedSyncService;
    private syncStatus = writable<SyncStatus>({
        phase1Complete: false,
        phase2Complete: false,
        phase3Complete: false,
        cachePrimed: false,
        currentPhase: 'none',
        chatCount: 0,
        lastSyncTimestamp: null
    });

    private constructor() {
        this.initializeEventListeners();
    }

    public static getInstance(): PhasedSyncService {
        if (!PhasedSyncService.instance) {
            PhasedSyncService.instance = new PhasedSyncService();
        }
        return PhasedSyncService.instance;
    }

    /**
     * Initialize WebSocket event listeners for sync events
     */
    private initializeEventListeners(): void {
        if (!browser) return;

        // Phase 1: Last chat ready
        websocketService.addEventListener('phase_1_last_chat_ready', (event: any) => {
            this.handlePhase1Complete(event.payload);
        });

        // Phase 2: Last 20 chats ready
        websocketService.addEventListener('phase_2_last_20_chats_ready', (event: any) => {
            this.handlePhase2Complete(event.payload);
        });

        // Phase 3: Last 100 chats ready
        websocketService.addEventListener('phase_3_last_100_chats_ready', (event: any) => {
            this.handlePhase3Complete(event.payload);
        });

        // Cache primed event
        websocketService.addEventListener('cache_primed', (event: any) => {
            this.handleCachePrimed(event.payload);
        });

        // App settings and memories sync ready (after Phase 3)
        websocketService.addEventListener('app_settings_memories_sync_ready', (event: any) => {
            this.handleAppSettingsMemoriesSyncReady(event.payload);
        });

        // Sync status response
        websocketService.addEventListener('sync_status_response', (event: any) => {
            this.handleSyncStatusResponse(event.payload);
        });
    }

    /**
     * Start the phased sync process
     */
    public async startSync(): Promise<void> {
        if (!browser) return;

        console.log('Starting phased sync process...');
        
        try {
            // Update sync status
            this.updateSyncStatus({ currentPhase: 'phase1' });

            // Request phased sync from server
            await websocketService.sendMessage({
                type: 'phased_sync_request',
                payload: { phase: 'all' }
            });

            // Also request sync status
            await this.requestSyncStatus();

        } catch (error) {
            console.error('Error starting sync:', error);
            this.updateSyncStatus({ currentPhase: 'error' });
        }
    }

    /**
     * Request current sync status from server
     */
    public async requestSyncStatus(): Promise<void> {
        if (!browser) return;

        try {
            await websocketService.sendMessage({
                type: 'sync_status_request',
                payload: {}
            });
        } catch (error) {
            console.error('Error requesting sync status:', error);
        }
    }

    /**
     * Handle Phase 1 completion (priority chat AND new chat suggestions)
     * ALWAYS contains new_chat_suggestions - may also contain chat data if last opened was a chat
     */
    private async handlePhase1Complete(payload: any): Promise<void> {
        console.log('Phase 1 complete - priority chat and suggestions ready:', payload);
        
        try {
            const { chat_id, chat_details, messages, new_chat_suggestions } = payload;
            
            // ALWAYS store new chat suggestions (Phase 1 always sends them)
            if (new_chat_suggestions && new_chat_suggestions.length > 0) {
                console.log('Phase 1: Storing new chat suggestions:', new_chat_suggestions.length);
                await this.storeNewChatSuggestions(new_chat_suggestions);
                
                // Dispatch event to notify NewChatSuggestions component
                window.dispatchEvent(new CustomEvent('newChatSuggestionsReady', {
                    detail: { suggestions: new_chat_suggestions }
                }));
                
                console.log('Phase 1: New chat suggestions ready for display');
            }
            
            // Handle chat data if present (last opened was a chat, not "new")
            if (chat_id && chat_id !== 'new' && chat_details) {
                console.log('Phase 1: Storing last opened chat:', chat_id);
                // Decrypt and store chat data
                await this.storeChatData(chat_id, chat_details, messages);
                
                // Auto-open the chat if it's the last opened chat
                await this.autoOpenChat(chat_id);
            } else if (chat_id && chat_id !== 'new' && !chat_details) {
                // Chat was already synced
                console.log('Phase 1: Last opened chat already synced');
            } else if (chat_id === 'new') {
                // Last opened was the new chat section
                console.log('Phase 1: Last opened was new chat section');
            }
            
            // Update sync status
            this.updateSyncStatus({ 
                phase1Complete: true,
                currentPhase: 'phase2'
            });

        } catch (error) {
            console.error('Error handling Phase 1 completion:', error);
        }
    }

    /**
     * Handle Phase 2 completion (recent chats ready)
     */
    private async handlePhase2Complete(payload: any): Promise<void> {
        console.log('Phase 2 complete - recent chats ready:', payload);
        
        try {
            const { chats, chat_count } = payload;
            
            // Store recent chats data
            await this.storeRecentChats(chats);
            
            // Update sync status
            this.updateSyncStatus({ 
                phase2Complete: true,
                currentPhase: 'phase3',
                chatCount: chat_count
            });

        } catch (error) {
            console.error('Error handling Phase 2 completion:', error);
        }
    }

    /**
     * Handle Phase 3 completion (full sync ready)
     * NEVER contains new_chat_suggestions - they are ALWAYS sent in Phase 1
     */
    private async handlePhase3Complete(payload: any): Promise<void> {
        console.log('Phase 3 complete - full sync ready:', payload);
        
        try {
            const { chats, chat_count } = payload;
            
            // Store all chats data
            await this.storeAllChats(chats);
            
            // Update sync status
            this.updateSyncStatus({ 
                phase3Complete: true,
                currentPhase: 'complete',
                chatCount: chat_count
            });

        } catch (error) {
            console.error('Error handling Phase 3 completion:', error);
        }
    }

    /**
     * Handle cache primed event
     */
    private async handleCachePrimed(payload: any): Promise<void> {
        console.log('Cache primed:', payload);
        
        this.updateSyncStatus({ 
            cachePrimed: true,
            lastSyncTimestamp: Date.now()
        });
    }

    /**
     * Handle app settings and memories sync ready event (after Phase 3)
     * This sync happens automatically after all chats have been synced.
     */
    private async handleAppSettingsMemoriesSyncReady(payload: any): Promise<void> {
        console.log('App settings and memories sync ready:', payload);
        
        try {
            const { entries } = payload;
            
            // Store encrypted app settings/memories entries in IndexedDB
            // TODO: Implement IndexedDB storage with app-specific encryption keys
            // 1. Decrypt app-specific keys using master key
            // 2. Store encrypted entries in IndexedDB (encrypted with app-specific keys)
            // 3. Handle conflict resolution based on item_version
            // 4. Update App Store settings UI if open
            
            console.log(`Received ${entries?.length || 0} app settings/memories entries for sync`);
            
            // Dispatch event to notify App Store components
            window.dispatchEvent(new CustomEvent('appSettingsMemoriesSyncReady', {
                detail: { entries: entries || [] }
            }));
            
        } catch (error) {
            console.error('Error handling app settings/memories sync:', error);
        }
    }

    /**
     * Handle sync status response
     */
    private async handleSyncStatusResponse(payload: any): Promise<void> {
        console.log('Sync status response:', payload);
        
        const { cache_primed, chat_count, timestamp } = payload;
        
        this.updateSyncStatus({
            cachePrimed: cache_primed,
            chatCount: chat_count,
            lastSyncTimestamp: timestamp
        });
    }

    /**
     * Store new chat suggestions (Phase 1 or Phase 3)
     */
    private async storeNewChatSuggestions(suggestions: any[]): Promise<void> {
        try {
            // Store suggestions in IndexedDB for immediate display
            // The NewChatSuggestions component will read from IndexedDB
            await db.storeNewChatSuggestions(suggestions);
            
            console.log(`Stored ${suggestions.length} new chat suggestions in IndexedDB`);
        } catch (error) {
            console.error('Error storing new chat suggestions:', error);
        }
    }

    /**
     * Store chat data (Phase 1)
     */
    private async storeChatData(chatId: string, chatDetails: any, messages: any[]): Promise<void> {
        try {
            // Decrypt chat metadata
            const decryptedChat = await this.decryptChatMetadata(chatDetails);
            
            // Store in IndexedDB (encrypted)
            await db.storeChat(chatId, {
                ...chatDetails,
                messages: messages || [],
                lastAccessed: Date.now()
            });

            // Store decrypted version in memory for immediate use
            await db.storeDecryptedChat(chatId, decryptedChat);

        } catch (error) {
            console.error('Error storing chat data:', error);
        }
    }

    /**
     * Store recent chats (Phase 2)
     */
    private async storeRecentChats(chats: any[]): Promise<void> {
        try {
            for (const chatItem of chats) {
                const { chat_details } = chatItem;
                const chatId = chat_details.id;
                
                // Store encrypted chat metadata
                await db.storeChat(chatId, chat_details);
                
                // Decrypt and store in memory for quick access
                const decryptedChat = await this.decryptChatMetadata(chat_details);
                await db.storeDecryptedChat(chatId, decryptedChat);
            }
        } catch (error) {
            console.error('Error storing recent chats:', error);
        }
    }

    /**
     * Store all chats (Phase 3)
     */
    private async storeAllChats(chats: any[]): Promise<void> {
        try {
            for (const chatItem of chats) {
                const { chat_details } = chatItem;
                const chatId = chat_details.id;
                
                // Store encrypted chat metadata
                await db.storeChat(chatId, chat_details);
                
                // Decrypt metadata for chat list display
                const decryptedChat = await this.decryptChatMetadata(chat_details);
                await db.storeDecryptedChat(chatId, decryptedChat);
            }
        } catch (error) {
            console.error('Error storing all chats:', error);
        }
    }

    /**
     * Decrypt chat metadata using chat-specific key
     */
    private async decryptChatMetadata(chatDetails: any): Promise<Chat> {
        try {
            // Get chat-specific encryption key
            const chatKey = await encryptionService.getChatKey(chatDetails.encrypted_chat_key);
            
            // Decrypt title
            const decryptedTitle = await encryptionService.decrypt(
                chatDetails.encrypted_title, 
                chatKey
            );
            
            return {
                id: chatDetails.id,
                title: decryptedTitle,
                unreadCount: chatDetails.unread_count,
                mates: chatDetails.mates || [],
                createdAt: chatDetails.created_at,
                updatedAt: chatDetails.updated_at,
                lastAccessed: Date.now()
            };
        } catch (error) {
            console.error('Error decrypting chat metadata:', error);
            return {
                id: chatDetails.id,
                title: 'Encrypted Chat',
                unreadCount: chatDetails.unread_count,
                mates: chatDetails.mates || [],
                createdAt: chatDetails.created_at,
                updatedAt: chatDetails.updated_at,
                lastAccessed: Date.now()
            };
        }
    }

    /**
     * Auto-open the last opened chat after Phase 1
     */
    private async autoOpenChat(chatId: string): Promise<void> {
        try {
            console.log('Auto-opening chat:', chatId);
            
            // Navigate to the chat
            await goto(`/chat/${chatId}`);
            
            // Dispatch chat opened event
            window.dispatchEvent(new CustomEvent('chatOpened', {
                detail: { chatId }
            }));
            
        } catch (error) {
            console.error('Error auto-opening chat:', error);
        }
    }

    /**
     * Update sync status
     */
    private updateSyncStatus(updates: Partial<SyncStatus>): void {
        this.syncStatus.update(current => ({
            ...current,
            ...updates
        }));
    }

    /**
     * Get current sync status
     */
    public getSyncStatus() {
        return this.syncStatus;
    }

    /**
     * Check if sync is complete
     */
    public isSyncComplete(): boolean {
        const status = get(this.syncStatus);
        return status.phase1Complete && status.phase2Complete && status.phase3Complete;
    }

    /**
     * Check if cache is primed
     */
    public isCachePrimed(): boolean {
        const status = get(this.syncStatus);
        return status.cachePrimed;
    }

    /**
     * Get current phase
     */
    public getCurrentPhase(): SyncPhase {
        const status = get(this.syncStatus);
        return status.currentPhase;
    }
}

// Export singleton instance
export const phasedSyncService = PhasedSyncService.getInstance();
