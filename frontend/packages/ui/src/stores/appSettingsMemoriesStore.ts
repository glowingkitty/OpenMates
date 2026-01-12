import { writable, derived } from 'svelte/store';
import { chatDB } from '../services/db';
import { decryptWithMasterKey, encryptWithMasterKey, getKeyFromStorage } from '../services/cryptoService';
import { chatSyncService } from '../services/chatSyncService';

/**
 * Creates a SHA-256 hash of the input string for privacy protection.
 * Used to hash item_key so the cleartext key is not stored in IndexedDB/Directus.
 * The actual key is stored inside the encrypted_item_json.
 */
async function hashString(input: string): Promise<string> {
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

interface AppSettingsMemoriesEntry {
    id: string;
    app_id: string;
    item_key: string;
    item_type: string;                // Category ID for filtering (e.g., 'preferred_technologies')
    encrypted_item_json: string;
    encrypted_app_key: string;
    created_at: number;
    updated_at: number;
    item_version: number;
    sequence_number?: number;
}

interface DecryptedEntry {
    id: string;
    app_id: string;
    item_key: string;
    item_value: Record<string, unknown>;
    created_at: number;
    updated_at: number;
    item_version: number;
    settings_group: string;
}

interface EntriesByGroup {
    [groupName: string]: DecryptedEntry[];
}

interface AppSettingsMemoriesState {
    entries: AppSettingsMemoriesEntry[];
    decryptedEntries: Map<string, DecryptedEntry>;
    entriesByApp: Map<string, EntriesByGroup>;
    isLoading: boolean;
    error: string | null;
}

function createAppSettingsMemoriesStore() {
    const initialState: AppSettingsMemoriesState = {
        entries: [],
        decryptedEntries: new Map(),
        entriesByApp: new Map(),
        isLoading: false,
        error: null
    };

    const { subscribe, update } = writable(initialState);

    /**
     * Decrypts app settings/memories entries using the master encryption key.
     * Retrieves the master key from storage (IndexedDB or memory) and uses it to decrypt entries.
     * 
     * @param entries - Array of encrypted entries to decrypt
     * @returns Map of decrypted entries keyed by entry ID
     */
    async function decryptEntries(entries: AppSettingsMemoriesEntry[]): Promise<Map<string, DecryptedEntry>> {
        const decrypted = new Map<string, DecryptedEntry>();
        
        // Retrieve master key from storage (IndexedDB or memory based on stayLoggedIn preference)
        const masterKey = await getKeyFromStorage();
        
        if (!masterKey) {
            console.error('[AppSettingsMemoriesStore] No master key available for decryption');
            return decrypted;
        }

        for (const entry of entries) {
            try {
                let itemValue: Record<string, unknown> = {};

                try {
                    // decryptWithMasterKey retrieves the master key internally from storage
                    const decryptedItemJson = await decryptWithMasterKey(entry.encrypted_item_json);
                    if (decryptedItemJson) {
                        itemValue = JSON.parse(decryptedItemJson);
                    }
                } catch (itemError) {
                    console.warn(`[AppSettingsMemoriesStore] Could not decrypt item for entry ${entry.id}, using hash as fallback:`, itemError);
                    itemValue = { _encrypted: true };
                }

                // Use top-level item_type for filtering - this is required for all entries
                // item_type is stored at top level for efficient filtering without decryption
                const settingsGroup = entry.item_type;

                // Extract original item_key from decrypted data (stored as _original_item_key for privacy)
                // Falls back to the hashed key if original is not available (legacy entries)
                const originalItemKey = (typeof itemValue._original_item_key === 'string' 
                    ? itemValue._original_item_key 
                    : entry.item_key);

                const decryptedEntry: DecryptedEntry = {
                    id: entry.id,
                    app_id: entry.app_id,
                    item_key: originalItemKey,  // Use original key from encrypted data, not the hashed storage key
                    item_value: itemValue,
                    created_at: entry.created_at,
                    updated_at: entry.updated_at,
                    item_version: entry.item_version,
                    settings_group: settingsGroup
                };

                decrypted.set(entry.id, decryptedEntry);
            } catch (error) {
                console.error(`[AppSettingsMemoriesStore] Error processing entry ${entry.id}:`, error);
            }
        }

        return decrypted;
    }

    function groupEntriesByApp(decryptedEntries: Map<string, DecryptedEntry>): Map<string, EntriesByGroup> {
        const grouped = new Map<string, EntriesByGroup>();

        // Use Array.from() to convert MapIterator to array for proper iteration
        for (const entry of Array.from(decryptedEntries.values())) {
            if (!grouped.has(entry.app_id)) {
                grouped.set(entry.app_id, {});
            }

            const appGroups = grouped.get(entry.app_id)!;
            const group = entry.settings_group;

            if (!appGroups[group]) {
                appGroups[group] = [];
            }

            appGroups[group].push(entry);

            appGroups[group].sort((a, b) => b.updated_at - a.updated_at);
        }

        return grouped;
    }

    return {
        subscribe,

        async loadEntries() {
            update(state => ({ ...state, isLoading: true, error: null }));
            try {
                const entries = await chatDB.getAllAppSettingsMemoriesEntries();
                const decryptedEntries = await decryptEntries(entries);
                const entriesByApp = groupEntriesByApp(decryptedEntries);

                update(state => ({
                    ...state,
                    entries,
                    decryptedEntries,
                    entriesByApp,
                    isLoading: false
                }));

                console.info(`[AppSettingsMemoriesStore] Loaded ${entries.length} app settings/memories entries`);
            } catch (error) {
                const errorMsg = error instanceof Error ? error.message : 'Unknown error';
                console.error('[AppSettingsMemoriesStore] Error loading entries:', error);
                update(state => ({
                    ...state,
                    isLoading: false,
                    error: errorMsg
                }));
            }
        },

        async loadEntriesForApp(appId: string) {
            update(state => ({ ...state, isLoading: true, error: null }));
            try {
                const entries = await chatDB.getAppSettingsMemoriesEntriesByApp(appId);
                const decryptedEntries = await decryptEntries(entries);

                const appGroups: EntriesByGroup = {};
                // Use Array.from() to convert MapIterator to array for proper iteration
                for (const entry of Array.from(decryptedEntries.values())) {
                    const group = entry.settings_group;
                    if (!appGroups[group]) {
                        appGroups[group] = [];
                    }
                    appGroups[group].push(entry);
                    appGroups[group].sort((a, b) => b.updated_at - a.updated_at);
                }

                update(state => {
                    const newEntriesByApp = new Map(state.entriesByApp);
                    newEntriesByApp.set(appId, appGroups);
                    return {
                        ...state,
                        decryptedEntries,
                        entriesByApp: newEntriesByApp,
                        isLoading: false
                    };
                });

                console.info(`[AppSettingsMemoriesStore] Loaded ${entries.length} entries for app ${appId}`);
            } catch (error) {
                const errorMsg = error instanceof Error ? error.message : 'Unknown error';
                console.error(`[AppSettingsMemoriesStore] Error loading entries for app ${appId}:`, error);
                update(state => ({
                    ...state,
                    isLoading: false,
                    error: errorMsg
                }));
            }
        },

        getEntriesByApp(appId: string): EntriesByGroup | undefined {
            let result: EntriesByGroup | undefined;
            const unsubscribe = subscribe(state => {
                result = state.entriesByApp.get(appId);
            });
            unsubscribe();
            return result;
        },

        getEntry(entryId: string): DecryptedEntry | undefined {
            let result: DecryptedEntry | undefined;
            const unsubscribe = subscribe(state => {
                result = state.decryptedEntries.get(entryId);
            });
            unsubscribe();
            return result;
        },

        /**
         * Creates a new app settings/memories entry.
         * Encrypts the entry data and stores it in IndexedDB for persistence.
         * 
         * **Flow**:
         * 1. Generate unique entry ID and timestamps
         * 2. Include settings_group in the item value for proper categorization
         * 3. Encrypt the item value JSON with master key
         * 4. Store encrypted entry in IndexedDB
         * 5. Update in-memory store state with decrypted data
         * 
         * @param appId - The app ID this entry belongs to
         * @param entryData - The entry data including key, value, and settings group
         */
        async createEntry(appId: string, entryData: { item_key: string; item_value: unknown; settings_group: string }) {
            // Retrieve master key from storage (IndexedDB or memory based on stayLoggedIn preference)
            const masterKey = await getKeyFromStorage();

            if (!masterKey) {
                throw new Error('No master key available for encryption');
            }

            try {
                const now = Date.now();
                const nowSeconds = Math.floor(now / 1000);
                
                // PRIVACY: Hash the item_key so cleartext content is NOT exposed in IndexedDB/Directus
                // The actual item_key is stored INSIDE the encrypted JSON for recovery on decryption
                // This ensures only the app_id and settings_group type are visible, not the content
                const hashedItemKey = await hashString(`${appId}-${entryData.item_key}-${now}`);
                
                // Generate a proper UUID for the entry ID
                // The database schema requires UUID type, not composite strings
                // App ID and timestamps are stored in separate fields, so the ID just needs to be unique
                const itemId = crypto.randomUUID();

                // Include BOTH settings_group AND the original item_key in the encrypted value
                // The item_key is stored encrypted so it can be recovered for display
                // This ensures zero-knowledge: server/IndexedDB never see the cleartext key content
                const itemValueWithMetadata = {
                    ...(typeof entryData.item_value === 'object' && entryData.item_value !== null 
                        ? entryData.item_value 
                        : { value: entryData.item_value }),
                    settings_group: entryData.settings_group,
                    _original_item_key: entryData.item_key  // Store original key for recovery
                };

                // Encrypt the item value JSON with master key
                const itemJson = JSON.stringify(itemValueWithMetadata);
                const encryptedItemJson = await encryptWithMasterKey(itemJson);
                
                if (!encryptedItemJson) {
                    throw new Error('Failed to encrypt entry data - master key may not be available');
                }

                // Create the encrypted entry for IndexedDB storage
                // PRIVACY: item_key is now a hash - original key is inside encrypted_item_json
                // Note: encrypted_app_key is set to empty string as current implementation
                // uses master key directly for encryption (per existing decryption logic)
                // CRITICAL: item_type is stored at top level (unencrypted) for efficient filtering
                // It's the category ID (e.g., 'preferred_technologies') and is NOT sensitive
                const encryptedEntry: AppSettingsMemoriesEntry = {
                    id: itemId,
                    app_id: appId,
                    item_key: hashedItemKey.substring(0, 32),  // Use hash prefix as key (privacy)
                    item_type: entryData.settings_group,  // Category ID at top level for filtering
                    encrypted_item_json: encryptedItemJson,
                    encrypted_app_key: '', // Not used in current implementation
                    created_at: nowSeconds,
                    updated_at: nowSeconds,
                    item_version: 1,
                    sequence_number: undefined
                };

                // Store encrypted entry in IndexedDB for persistence
                // This uses the same method as server sync, ensuring consistency
                await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);
                console.debug(`[AppSettingsMemoriesStore] Stored encrypted entry ${itemId} in IndexedDB`);

                // Create the decrypted entry for in-memory state
                // Uses original item_key (not hashed) for display purposes
                const newEntry: DecryptedEntry = {
                    id: itemId,
                    app_id: appId,
                    item_key: entryData.item_key,  // Original key for display (not the hashed storage key)
                    item_value: itemValueWithMetadata,  // Full value including metadata
                    created_at: nowSeconds,
                    updated_at: nowSeconds,
                    item_version: 1,
                    settings_group: entryData.settings_group
                };

                // Update in-memory store state with the new decrypted entry
                update(state => {
                    const newDecryptedEntries = new Map(state.decryptedEntries);
                    newDecryptedEntries.set(itemId, newEntry);

                    const newEntriesByApp = new Map(state.entriesByApp);
                    const appGroups = { ...(newEntriesByApp.get(appId) || {}) };
                    const group = entryData.settings_group;

                    if (!appGroups[group]) {
                        appGroups[group] = [];
                    }

                    appGroups[group] = [...appGroups[group], newEntry];
                    appGroups[group].sort((a, b) => b.updated_at - a.updated_at);
                    newEntriesByApp.set(appId, appGroups);

                    // Also update the entries array with the encrypted entry
                    const newEntries = [...state.entries, encryptedEntry];

                    return {
                        ...state,
                        entries: newEntries,
                        decryptedEntries: newDecryptedEntries,
                        entriesByApp: newEntriesByApp
                    };
                });

                console.info(`[AppSettingsMemoriesStore] Created entry ${itemId} for app ${appId}`);
                
                // Sync to server for permanent storage in Directus
                // Server stores encrypted data (zero-knowledge) and broadcasts to other devices
                try {
                    const syncSuccess = await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
                    if (syncSuccess) {
                        console.info(`[AppSettingsMemoriesStore] Synced entry ${itemId} to server`);
                    } else {
                        console.warn(`[AppSettingsMemoriesStore] Failed to sync entry ${itemId} to server (will retry on reconnect)`);
                    }
                } catch (syncError) {
                    // Don't fail the whole operation if sync fails - entry is still stored locally
                    console.error(`[AppSettingsMemoriesStore] Error syncing entry ${itemId} to server:`, syncError);
                }
                
            } catch (error) {
                console.error('[AppSettingsMemoriesStore] Error creating entry:', error);
                throw error;
            }
        },

        /**
         * Updates an existing app settings/memories entry.
         * Re-encrypts the entry data and stores it in IndexedDB for persistence.
         * 
         * **Flow**:
         * 1. Retrieve existing entry to get original metadata
         * 2. Include settings_group in the item value for proper categorization
         * 3. Encrypt the updated item value JSON with master key
         * 4. Store encrypted entry in IndexedDB (overwrites existing)
         * 5. Update in-memory store state with decrypted data
         * 
         * @param entryId - The ID of the entry to update
         * @param appId - The app ID this entry belongs to
         * @param entryData - The updated entry data including key, value, and settings group
         */
        async updateEntry(entryId: string, appId: string, entryData: { item_key: string; item_value: unknown; settings_group: string }) {
            // Retrieve master key from storage (IndexedDB or memory based on stayLoggedIn preference)
            const masterKey = await getKeyFromStorage();

            if (!masterKey) {
                throw new Error('No master key available for encryption');
            }

            try {
                const nowSeconds = Math.floor(Date.now() / 1000);
                
                // Get existing entry to preserve created_at and increment version
                let existingEntry: DecryptedEntry | undefined;
                const unsubscribe = subscribe(state => {
                    existingEntry = state.decryptedEntries.get(entryId);
                });
                unsubscribe();

                if (!existingEntry) {
                    throw new Error(`Entry ${entryId} not found`);
                }

                // PRIVACY: Hash the item_key so cleartext content is NOT exposed in IndexedDB/Directus
                const hashedItemKey = await hashString(`${appId}-${entryData.item_key}-${existingEntry.created_at}`);

                // Include BOTH settings_group AND the original item_key in the encrypted value
                const itemValueWithMetadata = {
                    ...(typeof entryData.item_value === 'object' && entryData.item_value !== null 
                        ? entryData.item_value 
                        : { value: entryData.item_value }),
                    settings_group: entryData.settings_group,
                    _original_item_key: entryData.item_key
                };

                // Encrypt the item value JSON with master key
                const itemJson = JSON.stringify(itemValueWithMetadata);
                const encryptedItemJson = await encryptWithMasterKey(itemJson);
                
                if (!encryptedItemJson) {
                    throw new Error('Failed to encrypt entry data - master key may not be available');
                }

                // Create the encrypted entry for IndexedDB storage
                // CRITICAL: item_type is stored at top level (unencrypted) for efficient filtering
                const encryptedEntry: AppSettingsMemoriesEntry = {
                    id: entryId,
                    app_id: appId,
                    item_key: hashedItemKey.substring(0, 32),
                    item_type: entryData.settings_group,  // Category ID at top level for filtering
                    encrypted_item_json: encryptedItemJson,
                    encrypted_app_key: '',
                    created_at: existingEntry.created_at,
                    updated_at: nowSeconds,
                    item_version: existingEntry.item_version + 1,
                    sequence_number: undefined
                };

                // Store encrypted entry in IndexedDB for persistence
                await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);
                console.debug(`[AppSettingsMemoriesStore] Updated encrypted entry ${entryId} in IndexedDB`);

                // Create the decrypted entry for in-memory state
                const updatedEntry: DecryptedEntry = {
                    id: entryId,
                    app_id: appId,
                    item_key: entryData.item_key,
                    item_value: itemValueWithMetadata,
                    created_at: existingEntry.created_at,
                    updated_at: nowSeconds,
                    item_version: existingEntry.item_version + 1,
                    settings_group: entryData.settings_group
                };

                // Update in-memory store state with the updated decrypted entry
                update(state => {
                    const newDecryptedEntries = new Map(state.decryptedEntries);
                    newDecryptedEntries.set(entryId, updatedEntry);

                    const newEntriesByApp = new Map(state.entriesByApp);
                    const appGroups = { ...(newEntriesByApp.get(appId) || {}) };
                    
                    // Remove from old group if group changed
                    const oldGroup = existingEntry!.settings_group;
                    if (oldGroup !== entryData.settings_group && appGroups[oldGroup]) {
                        appGroups[oldGroup] = appGroups[oldGroup].filter(e => e.id !== entryId);
                        if (appGroups[oldGroup].length === 0) {
                            delete appGroups[oldGroup];
                        }
                    }

                    // Add/update in new group
                    const newGroup = entryData.settings_group;
                    if (!appGroups[newGroup]) {
                        appGroups[newGroup] = [];
                    }
                    // Remove old entry from group if exists
                    appGroups[newGroup] = appGroups[newGroup].filter(e => e.id !== entryId);
                    // Add updated entry
                    appGroups[newGroup] = [...appGroups[newGroup], updatedEntry];
                    appGroups[newGroup].sort((a, b) => b.updated_at - a.updated_at);
                    newEntriesByApp.set(appId, appGroups);

                    // Update entries array
                    const newEntries = state.entries.map(e => 
                        e.id === entryId ? encryptedEntry : e
                    );

                    return {
                        ...state,
                        entries: newEntries,
                        decryptedEntries: newDecryptedEntries,
                        entriesByApp: newEntriesByApp
                    };
                });

                console.info(`[AppSettingsMemoriesStore] Updated entry ${entryId} for app ${appId}`);
                
                // Sync to server
                try {
                    const syncSuccess = await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
                    if (syncSuccess) {
                        console.info(`[AppSettingsMemoriesStore] Synced updated entry ${entryId} to server`);
                    } else {
                        console.warn(`[AppSettingsMemoriesStore] Failed to sync updated entry ${entryId} to server`);
                    }
                } catch (syncError) {
                    console.error(`[AppSettingsMemoriesStore] Error syncing updated entry ${entryId} to server:`, syncError);
                }
                
            } catch (error) {
                console.error('[AppSettingsMemoriesStore] Error updating entry:', error);
                throw error;
            }
        },

        /**
         * Deletes an app settings/memories entry.
         * Removes the entry from IndexedDB and in-memory state.
         * 
         * @param entryId - The ID of the entry to delete
         * @param appId - The app ID this entry belongs to
         */
        async deleteEntry(entryId: string, appId: string) {
            try {
                // Get existing entry to know which group to remove from
                let existingEntry: DecryptedEntry | undefined;
                const unsubscribe = subscribe(state => {
                    existingEntry = state.decryptedEntries.get(entryId);
                });
                unsubscribe();

                if (!existingEntry) {
                    console.warn(`[AppSettingsMemoriesStore] Entry ${entryId} not found for deletion`);
                    return;
                }

                // Delete from IndexedDB
                await chatDB.deleteAppSettingsMemoriesEntry(entryId);
                console.debug(`[AppSettingsMemoriesStore] Deleted entry ${entryId} from IndexedDB`);

                // Update in-memory store state
                update(state => {
                    const newDecryptedEntries = new Map(state.decryptedEntries);
                    newDecryptedEntries.delete(entryId);

                    const newEntriesByApp = new Map(state.entriesByApp);
                    const appGroups = { ...(newEntriesByApp.get(appId) || {}) };
                    
                    // Remove from group
                    const group = existingEntry!.settings_group;
                    if (appGroups[group]) {
                        appGroups[group] = appGroups[group].filter(e => e.id !== entryId);
                        if (appGroups[group].length === 0) {
                            delete appGroups[group];
                        }
                    }
                    newEntriesByApp.set(appId, appGroups);

                    // Remove from entries array
                    const newEntries = state.entries.filter(e => e.id !== entryId);

                    return {
                        ...state,
                        entries: newEntries,
                        decryptedEntries: newDecryptedEntries,
                        entriesByApp: newEntriesByApp
                    };
                });

                console.info(`[AppSettingsMemoriesStore] Deleted entry ${entryId} for app ${appId}`);
                
                // TODO: Sync deletion to server when backend supports it
                // Server sync for app settings/memories deletion is not yet implemented
                // For now, deletion is local only - entries will reappear on re-sync
                // Future: await chatSyncService.sendDeleteAppSettingsMemoriesEntry(entryId);
                
            } catch (error) {
                console.error('[AppSettingsMemoriesStore] Error deleting entry:', error);
                throw error;
            }
        }
    };
}

export const appSettingsMemoriesStore = createAppSettingsMemoriesStore();

export const appSettingsMemoriesForApp = (appId: string) => {
    return derived(appSettingsMemoriesStore, state => state.entriesByApp.get(appId) || {});
};

export const appSettingsMemoriesLoading = derived(
    appSettingsMemoriesStore,
    state => state.isLoading
);

export const appSettingsMemoriesError = derived(
    appSettingsMemoriesStore,
    state => state.error
);
