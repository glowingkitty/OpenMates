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

import type { ChatSynchronizationService } from './chatSyncService';
import { notificationStore } from '../stores/notificationStore';
import { chatDB } from './db';
import { decryptWithMasterKey } from './cryptoService';

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
 * Parsed category for the permission dialog
 */
export interface AppSettingsMemoriesCategory {
    key: string;           // Original key format: "app_id-item_type"
    appId: string;         // App ID (e.g., "code")
    itemType: string;      // Category/item type (e.g., "preferred_technologies")
    displayName: string;   // Human-readable name
    entryCount: number;    // Number of entries in this category
    iconGradient?: string; // Optional CSS gradient for the icon background
    selected: boolean;     // Whether this category is selected for sharing
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
export function getPendingPermissionRequest(requestId: string): PendingPermissionRequest | undefined {
    return pendingPermissionRequests.get(requestId);
}

/**
 * Get all pending permission requests for a chat
 */
export function getPendingPermissionRequestsForChat(chatId: string): PendingPermissionRequest[] {
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
function formatDisplayName(itemType: string): string {
    return itemType
        .split('_')
        .map((word, index) => index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word)
        .join(' ');
}

/**
 * Get CSS gradient for an app ID from theme variables
 */
function getAppGradient(appId: string): string {
    const gradientMap: Record<string, string> = {
        'code': 'linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)',
        'travel': 'linear-gradient(135deg, #059DB3 9.04%, #13DAF5 90.06%)',
        'finance': 'linear-gradient(135deg, #119106 9.04%, #15780D 90.06%)',
        'health': 'linear-gradient(135deg, #FD50A0 9.04%, #F42C2D 90.06%)',
        'news': 'linear-gradient(135deg, #F53F5B 9.04%, #DD0B2B 90.06%)',
        'weather': 'linear-gradient(135deg, #005BA5 9.04%, #00A7C9 90.06%)',
        'jobs': 'linear-gradient(135deg, #049363 9.04%, #00C382 90.06%)',
        'legal': 'linear-gradient(135deg, #239CFF 9.04%, #005BA5 90.06%)',
        'files': 'linear-gradient(135deg, #1E3A8A 9.04%, #29BEFB 90.06%)',
        'ai': 'linear-gradient(135deg, #CB7D5D 9.04%, #CB685D 90.06%)',
        'tv': 'linear-gradient(135deg, #8B5CF6 9.04%, #6D28D9 90.06%)',
        'videos': 'linear-gradient(135deg, #EF4444 9.04%, #DC2626 90.06%)',
        'maps': 'linear-gradient(135deg, #10B981 9.04%, #059669 90.06%)',
        'study': 'linear-gradient(135deg, #F59E0B 9.04%, #D97706 90.06%)',
        'plants': 'linear-gradient(135deg, #22C55E 9.04%, #16A34A 90.06%)',
    };
    return gradientMap[appId] || 'linear-gradient(135deg, #4A90D9 9.04%, #7B68EE 90.06%)';
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
    payload: RequestAppSettingsMemoriesPayload
): Promise<void> {
    console.info("[ChatSyncService:AppSettings] Received 'request_app_settings_memories':", payload);
    
    const { request_id, chat_id, requested_keys, yaml_content } = payload;
    
    if (!request_id || !chat_id || !requested_keys || !Array.isArray(requested_keys) || requested_keys.length === 0) {
        console.error("[ChatSyncService:AppSettings] Invalid request payload:", payload);
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
            const dashIndex = key.indexOf('-');
            if (dashIndex === -1) {
                console.warn(`[ChatSyncService:AppSettings] Invalid key format (missing hyphen): ${key}`);
                continue;
            }
            
            const appId = key.substring(0, dashIndex);
            const itemType = key.substring(dashIndex + 1);
            
            if (!appId || !itemType) {
                console.warn(`[ChatSyncService:AppSettings] Invalid key format (empty parts): ${key}`);
                continue;
            }
            
            // Check if this category exists in IndexedDB
            const entryCount = entryCounts.get(key) || 0;
            
            if (entryCount === 0) {
                console.warn(`[ChatSyncService:AppSettings] No entries found for key: ${key}, skipping`);
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
                selected: true // Default to selected
            });
        }
        
        if (categories.length === 0) {
            console.warn("[ChatSyncService:AppSettings] No valid categories found in request, skipping dialog");
            return;
        }
        
        console.info(`[ChatSyncService:AppSettings] Built ${categories.length} categories for permission dialog`);
        
        // Store the pending request
        const pendingRequest: PendingPermissionRequest = {
            requestId: request_id,
            chatId: chat_id,
            messageId: payload.message_id, // User message that triggered this request
            categories,
            yamlContent: yaml_content || '',
            createdAt: Date.now()
        };
        pendingPermissionRequests.set(request_id, pendingRequest);
        
        // Dispatch event to show the Permission Dialog
        // The ActiveChat component or a global listener should handle this event
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('showAppSettingsMemoriesPermissionDialog', {
                detail: pendingRequest
            }));
            console.info(`[ChatSyncService:AppSettings] Dispatched showAppSettingsMemoriesPermissionDialog event for request ${request_id}`);
        }
        
    } catch (error) {
        console.error("[ChatSyncService:AppSettings] Error handling app settings/memories request:", error);
        notificationStore.addNotification(
            'error',
            'Failed to process app settings/memories request',
            5000
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
 */
export async function handlePermissionDialogConfirm(
    serviceInstance: ChatSynchronizationService,
    requestId: string,
    selectedKeys: string[]
): Promise<void> {
    const pendingRequest = pendingPermissionRequests.get(requestId);
    if (!pendingRequest) {
        console.error(`[ChatSyncService:AppSettings] No pending request found for ID: ${requestId}`);
        return;
    }
    
    const { chatId, messageId, categories } = pendingRequest;
    
    try {
        console.info(`[ChatSyncService:AppSettings] Processing confirmation for ${selectedKeys.length} selected categories`);
        
        // Load and decrypt entries for selected categories
        const appSettingsMemories: Array<{
            app_id: string;
            item_key: string;
            content: unknown;
        }> = [];
        
        // Build metadata for selected categories (for UI display)
        const selectedCategories = categories.filter(cat => selectedKeys.includes(cat.key));
        
        for (const key of selectedKeys) {
            const dashIndex = key.indexOf('-');
            if (dashIndex === -1) continue;
            
            const appId = key.substring(0, dashIndex);
            const itemType = key.substring(dashIndex + 1);
            
            // Get entries for this category
            const entries = await chatDB.getAppSettingsMemoriesEntriesByAppAndType(appId, itemType);
            
            for (const entry of entries) {
                try {
                    // Decrypt the entry content
                    const decryptedJson = await decryptWithMasterKey(entry.encrypted_item_json);
                    if (decryptedJson) {
                        const content = JSON.parse(decryptedJson);
                        appSettingsMemories.push({
                            app_id: appId,
                            item_key: entry.item_key,
                            content
                        });
                    }
                } catch (decryptError) {
                    console.error(`[ChatSyncService:AppSettings] Failed to decrypt entry ${entry.id}:`, decryptError);
                }
            }
        }
        
        if (appSettingsMemories.length === 0) {
            console.warn("[ChatSyncService:AppSettings] No entries to send after decryption");
            removePendingPermissionRequest(requestId);
            return;
        }
        
        // Import and call the sender function
        const { sendAppSettingsMemoriesConfirmedImpl } = await import('./chatSyncServiceSenders');
        await sendAppSettingsMemoriesConfirmedImpl(serviceInstance, chatId, appSettingsMemories);
        
        console.info(`[ChatSyncService:AppSettings] Sent ${appSettingsMemories.length} entries to server`);
        
        // Create system message with response metadata (synced to server for cross-device display)
        // This stores ONLY essential metadata (appId, itemType, entryCount), NOT display info or actual content
        // Display name and icon are loaded client-side based on appId and itemType
        if (messageId) {
            try {
                const categoryMetadata: AppSettingsMemoriesResponseCategory[] = selectedCategories.map(cat => ({
                    appId: cat.appId,
                    itemType: cat.itemType,
                    entryCount: cat.entryCount
                }));
                
                await saveAppSettingsMemoriesResponseMessage(
                    serviceInstance,
                    chatId,
                    messageId,
                    'included',
                    categoryMetadata
                );
                console.info(`[ChatSyncService:AppSettings] Created system message for 'included' action on message ${messageId}`);
            } catch (saveError) {
                console.error('[ChatSyncService:AppSettings] Error saving response message:', saveError);
            }
        }
        
        // Clean up the pending request
        removePendingPermissionRequest(requestId);
        
        // Notify user
        notificationStore.addNotification(
            'success',
            'App settings & memories shared with assistant',
            3000
        );
        
    } catch (error) {
        console.error("[ChatSyncService:AppSettings] Error processing permission confirmation:", error);
        notificationStore.addNotification(
            'error',
            'Failed to share app settings & memories',
            5000
        );
    }
}

/**
 * Handle user exclusion of app settings/memories sharing.
 * Called when user clicks "Reject all" in the Permission Dialog.
 * Creates a system message with 'rejected' action (synced to server for cross-device display).
 */
export async function handlePermissionDialogExclude(
    serviceInstance: ChatSynchronizationService,
    requestId: string
): Promise<void> {
    const pendingRequest = pendingPermissionRequests.get(requestId);
    
    console.info(`[ChatSyncService:AppSettings] User rejected app settings/memories for request ${requestId}`);
    
    // Create system message with response metadata (synced to server for cross-device display)
    if (pendingRequest?.messageId && pendingRequest?.chatId) {
        try {
            await saveAppSettingsMemoriesResponseMessage(
                serviceInstance,
                pendingRequest.chatId,
                pendingRequest.messageId,
                'rejected'
            );
            console.info(`[ChatSyncService:AppSettings] Created system message for 'rejected' action on message ${pendingRequest.messageId}`);
        } catch (saveError) {
            console.error('[ChatSyncService:AppSettings] Error saving rejected response message:', saveError);
        }
    }
    
    removePendingPermissionRequest(requestId);
}

/**
 * Category metadata for app settings/memories response.
 * Simplified structure - display name and icon are loaded client-side based on appId and itemType.
 */
export interface AppSettingsMemoriesResponseCategory {
    appId: string;      // e.g., "code"
    itemType: string;   // e.g., "preferred_technologies" (without app prefix)
    entryCount: number; // Number of entries included
}

/**
 * Content structure for app settings/memories response system message
 * This is JSON-stringified and stored in the message content field
 */
export interface AppSettingsMemoriesResponseContent {
    type: 'app_settings_memories_response';
    user_message_id: string;
    action: 'included' | 'rejected';
    categories?: AppSettingsMemoriesResponseCategory[];
}

/**
 * Create and save a system message for app settings/memories response.
 * This message is stored in IndexedDB and synced to the server for cross-device display.
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
    action: 'included' | 'rejected',
    categories?: AppSettingsMemoriesResponseCategory[]
): Promise<void> {
    // Import required utilities
    const { generateUUID } = await import('../message_parsing/utils');
    const { webSocketService } = await import('./websocketService');
    
    // Generate unique message ID (format: last 10 chars of chat_id + uuid)
    const chatIdSuffix = chatId.slice(-10);
    const messageId = `${chatIdSuffix}-${generateUUID()}`;
    
    // Create system message content
    const responseContent: AppSettingsMemoriesResponseContent = {
        type: 'app_settings_memories_response',
        user_message_id: userMessageId,
        action,
        categories: action === 'included' ? categories : undefined
    };
    
    // Create the system message
    const now = Math.floor(Date.now() / 1000);
    const systemMessage = {
        message_id: messageId,
        chat_id: chatId,
        role: 'system' as const,
        content: JSON.stringify(responseContent),
        created_at: now,
        status: 'sending' as const,
        encrypted_content: ''  // Will be populated by chatDB.saveMessage()
    };
    
    // Save to IndexedDB (will be encrypted with chat key)
    await chatDB.saveMessage(systemMessage);
    console.debug(`[ChatSyncService:AppSettings] Saved system message ${messageId} to IndexedDB`);
    
    // Send to server for persistence and cross-device sync
    // Use a dedicated WebSocket message type for system messages
    const payload = {
        chat_id: chatId,
        message: {
            message_id: messageId,
            role: 'system',
            content: JSON.stringify(responseContent),
            created_at: now
        }
    };
    
    try {
        await webSocketService.sendMessage('chat_system_message_added', payload);
        
        // Update message status to synced
        const syncedMessage = { ...systemMessage, status: 'synced' as const };
        await chatDB.saveMessage(syncedMessage);
        
        console.debug(`[ChatSyncService:AppSettings] Sent system message ${messageId} to server`);
        
        // Dispatch event to update UI
        serviceInstance.dispatchEvent(new CustomEvent('messageAdded', { 
            detail: { 
                chatId, 
                message: syncedMessage 
            } 
        }));
    } catch (sendError) {
        console.error(`[ChatSyncService:AppSettings] Error sending system message to server:`, sendError);
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
        item_type: string;  // Category ID for filtering (e.g., 'preferred_technologies')
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
    payload: AppSettingsMemoriesSyncReadyPayload
): Promise<void> {
    console.info("[ChatSyncService:AppSettings] Received 'app_settings_memories_sync_ready':", {
        entry_count: payload.entry_count,
        entries_received: payload.entries?.length || 0
    });

    const { entries } = payload;

    if (!entries || !Array.isArray(entries)) {
        console.error("[ChatSyncService:AppSettings] Invalid sync payload - entries is not an array:", payload);
        return;
    }

    try {
        // Store encrypted app settings/memories entries in IndexedDB
        // The storeAppSettingsMemoriesEntries method handles conflict resolution
        // based on item_version (higher version wins, or updated_at if versions are equal)
        await chatDB.storeAppSettingsMemoriesEntries(entries);

        console.info(`[ChatSyncService:AppSettings] Successfully synced ${entries.length} app settings/memories entries`);

        // Dispatch custom event to notify App Store components that sync is complete
        // This allows the App Store UI to refresh if it's currently open
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('appSettingsMemoriesSyncReady', {
                detail: { 
                    entry_count: entries.length,
                    synced_at: Date.now()
                }
            }));
        }

    } catch (error) {
        console.error("[ChatSyncService:AppSettings] Error handling app settings/memories sync:", error);
        // Don't throw - this is a non-critical sync that shouldn't block other operations
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
        item_type: string;  // Category ID for filtering (e.g., 'preferred_technologies')
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
    payload: AppSettingsMemoriesEntrySyncedPayload
): Promise<void> {
    console.info("[ChatSyncService:AppSettings] Received 'app_settings_memories_entry_synced' from another device:", {
        entry_count: payload.entry_count,
        source_device: payload.source_device?.substring(0, 8) + '...'
    });

    const { entries } = payload;

    if (!entries || !Array.isArray(entries) || entries.length === 0) {
        console.warn("[ChatSyncService:AppSettings] Invalid entry_synced payload - no entries");
        return;
    }

    try {
        // Store encrypted entries in IndexedDB
        // The storeAppSettingsMemoriesEntries method handles conflict resolution
        await chatDB.storeAppSettingsMemoriesEntries(entries);

        console.info(`[ChatSyncService:AppSettings] Synced ${entries.length} entries from another device`);

        // Dispatch custom event to notify App Store components to refresh
        // This allows the UI to show the new entry immediately
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('appSettingsMemoriesEntrySynced', {
                detail: { 
                    entries: entries,
                    entry_count: entries.length,
                    synced_at: Date.now()
                }
            }));
        }

    } catch (error) {
        console.error("[ChatSyncService:AppSettings] Error handling entry sync from other device:", error);
    }
}
