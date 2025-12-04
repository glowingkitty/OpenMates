import { writable, derived } from 'svelte/store';
import { chatDB } from '../services/db';
import { decryptWithMasterKey } from '../services/cryptoService';
import { authStore } from './authStore';
import { get } from 'svelte/store';

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

    async function decryptEntries(entries: AppSettingsMemoriesEntry[]): Promise<Map<string, DecryptedEntry>> {
        const decrypted = new Map<string, DecryptedEntry>();
        const authState = get(authStore);

        if (!authState.masterKey) {
            console.error('[AppSettingsMemoriesStore] No master key available for decryption');
            return decrypted;
        }

        for (const entry of entries) {
            try {
                let itemValue: Record<string, unknown> = {};

                try {
                    const decryptedItemJson = await decryptWithMasterKey(
                        entry.encrypted_item_json,
                        authState.masterKey
                    );
                    itemValue = JSON.parse(decryptedItemJson);
                } catch (itemError) {
                    console.warn(`[AppSettingsMemoriesStore] Could not decrypt item for entry ${entry.id}, using key as fallback:`, itemError);
                    itemValue = { _key: entry.item_key };
                }

                const settingsGroup = itemValue.settings_group || entry.item_key.split('.')[0] || 'Default';

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

        for (const entry of decryptedEntries.values()) {
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
                for (const entry of decryptedEntries.values()) {
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

        async createEntry(appId: string, entryData: { item_key: string; item_value: unknown; settings_group: string }) {
            const authState = get(authStore);

            if (!authState.masterKey) {
                throw new Error('No master key available for encryption');
            }

            try {
                const itemId = `${appId}-${entryData.item_key}-${Date.now()}`;
                const now = Date.now();

                const newEntry: DecryptedEntry = {
                    id: itemId,
                    app_id: appId,
                    item_key: entryData.item_key,
                    item_value: entryData.item_value,
                    created_at: Math.floor(now / 1000),
                    updated_at: Math.floor(now / 1000),
                    item_version: 1,
                    settings_group: entryData.settings_group
                };

                update(state => {
                    const newDecryptedEntries = new Map(state.decryptedEntries);
                    newDecryptedEntries.set(itemId, newEntry);

                    const newEntriesByApp = new Map(state.entriesByApp);
                    const appGroups = newEntriesByApp.get(appId) || {};
                    const group = entryData.settings_group;

                    if (!appGroups[group]) {
                        appGroups[group] = [];
                    }

                    appGroups[group].push(newEntry);
                    appGroups[group].sort((a, b) => b.updated_at - a.updated_at);
                    newEntriesByApp.set(appId, appGroups);

                    return {
                        ...state,
                        decryptedEntries: newDecryptedEntries,
                        entriesByApp: newEntriesByApp
                    };
                });

                console.info(`[AppSettingsMemoriesStore] Created entry ${itemId} for app ${appId}`);
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
