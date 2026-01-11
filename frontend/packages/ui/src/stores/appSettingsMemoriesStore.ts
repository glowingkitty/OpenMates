import { writable, derived } from 'svelte/store';
import { chatDB } from '../services/db';
import { decryptWithMasterKey, encryptWithMasterKey, getKeyFromStorage } from '../services/cryptoService';
import { chatSyncService } from '../services/chatSyncService';

interface AppSettingsMemoriesEntry {
    id: string;
    app_id: string;
    item_key: string;
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
                    console.warn(`[AppSettingsMemoriesStore] Could not decrypt item for entry ${entry.id}, using key as fallback:`, itemError);
                    itemValue = { _key: entry.item_key };
                }

                // Extract settings_group from item value, falling back to first part of item_key or 'Default'
                const settingsGroup = (typeof itemValue.settings_group === 'string' ? itemValue.settings_group : null) 
                    || entry.item_key.split('.')[0] 
                    || 'Default';

                const decryptedEntry: DecryptedEntry = {
                    id: entry.id,
                    app_id: entry.app_id,
                    item_key: entry.item_key,
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
                const itemId = `${appId}-${entryData.item_key}-${Date.now()}`;
                const now = Date.now();
                const nowSeconds = Math.floor(now / 1000);

                // Include settings_group in the item value so it can be recovered on decryption
                // This ensures the category grouping is properly restored when loading from IndexedDB
                const itemValueWithGroup = {
                    ...(typeof entryData.item_value === 'object' && entryData.item_value !== null 
                        ? entryData.item_value 
                        : { value: entryData.item_value }),
                    settings_group: entryData.settings_group
                };

                // Encrypt the item value JSON with master key
                const itemJson = JSON.stringify(itemValueWithGroup);
                const encryptedItemJson = await encryptWithMasterKey(itemJson);
                
                if (!encryptedItemJson) {
                    throw new Error('Failed to encrypt entry data - master key may not be available');
                }

                // Create the encrypted entry for IndexedDB storage
                // Note: encrypted_app_key is set to empty string as current implementation
                // uses master key directly for encryption (per existing decryption logic)
                const encryptedEntry: AppSettingsMemoriesEntry = {
                    id: itemId,
                    app_id: appId,
                    item_key: entryData.item_key,
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
                const newEntry: DecryptedEntry = {
                    id: itemId,
                    app_id: appId,
                    item_key: entryData.item_key,
                    item_value: itemValueWithGroup,
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
