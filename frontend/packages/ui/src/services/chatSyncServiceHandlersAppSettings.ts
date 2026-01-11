// frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts
/**
 * WebSocket handlers for app settings and memories requests.
 * 
 * Implements zero-knowledge architecture with chat history-based requests:
 * 1. Server sends YAML content for app settings/memories request via WebSocket
 * 2. Client encrypts YAML with chat key and creates system message in chat history
 * 3. Message persists in IndexedDB and syncs to server (survives restarts, works across devices)
 * 4. Client shows user confirmation UI
 * 5. When user responds, client updates message's YAML structure with responses
 * 6. Client re-encrypts and updates message in chat history
 * 7. Server checks chat history on next message and extracts accepted responses
 * 
 * This allows requests to persist indefinitely (hours/days) and work across all devices.
 */

import type { ChatSynchronizationService } from './chatSyncService';
import { notificationStore } from '../stores/notificationStore';
import { chatDB } from './db';

/**
 * Payload structure for request_app_settings_memories WebSocket message
 */
interface RequestAppSettingsMemoriesPayload {
    request_id: string;
    chat_id: string;
    requested_keys: string[]; // Array of "app_id-item_key" format
    yaml_content: string; // YAML structure for the request
}

/**
 * Handles server request for app settings/memories.
 * 
 * The server sends YAML content that should be stored as a system message in chat history.
 * The client must:
 * 1. Encrypt YAML content with chat key
 * 2. Create system message in IndexedDB (encrypted)
 * 3. Sync message to server (normal message sync flow)
 * 4. Show user confirmation UI
 * 5. When user responds, update message's YAML structure with responses
 * 6. Re-encrypt and update message in chat history
 * 
 * TODO: Full implementation requires:
 * - App settings/memories storage in IndexedDB (encrypted with master key)
 * - App-specific encryption keys (encrypted with master key)
 * - User confirmation UI component
 * - Message creation/update in IndexedDB
 * - Message sync to server
 * - Proper decryption of app settings/memories using app-specific keys
 */
export async function handleRequestAppSettingsMemoriesImpl(
    serviceInstance: ChatSynchronizationService,
    payload: RequestAppSettingsMemoriesPayload
): Promise<void> {
    console.info("[ChatSyncService:AppSettings] Received 'request_app_settings_memories':", payload);
    
    const { request_id, chat_id, requested_keys, yaml_content } = payload;
    
    if (!request_id || !chat_id || !yaml_content || !requested_keys || !Array.isArray(requested_keys)) {
        console.error("[ChatSyncService:AppSettings] Invalid request payload:", payload);
        return;
    }
    
    try {
        // TODO: Full implementation should:
        // 1. Get chat key for encryption
        // 2. Encrypt YAML content with chat key
        // 3. Create system message in IndexedDB with encrypted YAML content
        // 4. Sync message to server (normal message sync flow)
        // 5. Show user confirmation UI
        // 6. When user responds, update message's YAML structure with responses
        // 7. Re-encrypt and update message in IndexedDB
        // 8. Sync update to server
        
        console.warn("[ChatSyncService:AppSettings] App settings/memories chat history integration not yet fully implemented.");
        console.info(`[ChatSyncService:AppSettings] Request ID: ${request_id}, Chat ID: ${chat_id}, Keys: ${requested_keys.join(', ')}`);
        console.debug("[ChatSyncService:AppSettings] YAML content:", yaml_content);
        
        // Show notification to user (for now, just log - proper UI will be added later)
        notificationStore.addNotification(
            'info',
            `The assistant requested access to your app settings/memories. This feature is being implemented.`,
            5000
        );
        
        // TODO: Once implemented, the message will be stored in chat history
        // and the user can respond hours/days later. The server will check
        // chat history on the next message and extract accepted responses.
        
    } catch (error) {
        console.error("[ChatSyncService:AppSettings] Error handling app settings/memories request:", error);
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
