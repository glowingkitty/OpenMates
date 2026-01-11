// frontend/packages/ui/src/services/db/appSettingsMemories.ts
// Handles app settings and memories CRUD operations for the ChatDatabase class.
// These operations are extracted from db.ts for better code organization.
// 
// App settings and memories are used to store user preferences and memories
// that apps can access. They support conflict resolution based on item_version.

/**
 * Type for ChatDatabase instance to avoid circular import.
 * This interface defines the minimal required properties from ChatDatabase
 * that this module needs to access.
 */
interface ChatDatabaseInstance {
    db: IDBDatabase | null;
    APP_SETTINGS_MEMORIES_STORE_NAME: string;
}

/**
 * Type for app settings/memories entry as received from server sync.
 * Each entry represents a single setting or memory item for an app.
 */
export interface AppSettingsMemoriesEntry {
    id: string;                       // Unique entry identifier
    app_id: string;                   // ID of the app this entry belongs to
    item_key: string;                 // Key identifying the setting/memory within the app
    item_type: string;                // Category/type ID for filtering (e.g., 'preferred_technologies')
    encrypted_item_json: string;      // Encrypted JSON value of the item
    encrypted_app_key: string;        // Encrypted app-specific key for decryption
    created_at: number;               // Unix timestamp of creation
    updated_at: number;               // Unix timestamp of last update
    item_version: number;             // Version number for conflict resolution
    sequence_number?: number;         // Optional sequence for ordering
}

/**
 * Store app settings/memories entries from server sync.
 * Handles conflict resolution based on item_version (higher version wins).
 * When versions are equal, falls back to updated_at timestamp comparison.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param entries - Array of encrypted app settings/memories entries from server
 */
export async function storeAppSettingsMemoriesEntries(
    dbInstance: ChatDatabaseInstance,
    entries: AppSettingsMemoriesEntry[]
): Promise<void> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    if (entries.length === 0) {
        console.debug('[ChatDatabase] No app settings/memories entries to store');
        return;
    }

    try {
        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);

        // Counters for logging purposes
        let storedCount = 0;
        let skippedCount = 0;
        let conflictResolvedCount = 0;

        for (const entry of entries) {
            try {
                // Check if entry already exists for conflict resolution
                const existingRequest = store.get(entry.id);
                const existingEntry = await new Promise<AppSettingsMemoriesEntry | undefined>((resolve, reject) => {
                    existingRequest.onsuccess = () => resolve(existingRequest.result);
                    existingRequest.onerror = () => reject(existingRequest.error);
                });

                if (existingEntry) {
                    // Conflict resolution: compare item_version
                    const existingVersion = existingEntry.item_version || 1;
                    const newVersion = entry.item_version || 1;

                    if (newVersion > existingVersion) {
                        // Server version is newer - update local entry
                        store.put({
                            id: entry.id,
                            app_id: entry.app_id,
                            item_key: entry.item_key,
                            item_type: entry.item_type,  // Category ID for filtering
                            encrypted_item_json: entry.encrypted_item_json,
                            encrypted_app_key: entry.encrypted_app_key,
                            created_at: entry.created_at,
                            updated_at: entry.updated_at,
                            item_version: entry.item_version,
                            sequence_number: entry.sequence_number
                        });
                        conflictResolvedCount++;
                        storedCount++;
                    } else if (newVersion === existingVersion) {
                        // Versions are equal - compare updated_at timestamps
                        const existingUpdatedAt = existingEntry.updated_at || 0;
                        const newUpdatedAt = entry.updated_at || 0;

                        if (newUpdatedAt > existingUpdatedAt) {
                            // Server entry is newer based on timestamp
                            store.put({
                                id: entry.id,
                                app_id: entry.app_id,
                                item_key: entry.item_key,
                                item_type: entry.item_type,  // Category ID for filtering
                                encrypted_item_json: entry.encrypted_item_json,
                                encrypted_app_key: entry.encrypted_app_key,
                                created_at: entry.created_at,
                                updated_at: entry.updated_at,
                                item_version: entry.item_version,
                                sequence_number: entry.sequence_number
                            });
                            conflictResolvedCount++;
                            storedCount++;
                        } else {
                            // Local version is newer or equal - keep local
                            skippedCount++;
                        }
                    } else {
                        // Local version is newer - keep local
                        skippedCount++;
                    }
                } else {
                    // New entry - store it
                    store.add({
                        id: entry.id,
                        app_id: entry.app_id,
                        item_key: entry.item_key,
                        item_type: entry.item_type,  // Category ID for filtering
                        encrypted_item_json: entry.encrypted_item_json,
                        encrypted_app_key: entry.encrypted_app_key,
                        created_at: entry.created_at,
                        updated_at: entry.updated_at,
                        item_version: entry.item_version,
                        sequence_number: entry.sequence_number
                    });
                    storedCount++;
                }
            } catch (entryError) {
                // If add fails due to duplicate key, try put instead
                if (entryError instanceof DOMException && entryError.name === 'ConstraintError') {
                    store.put({
                        id: entry.id,
                        app_id: entry.app_id,
                        item_key: entry.item_key,
                        item_type: entry.item_type,  // Category ID for filtering
                        encrypted_item_json: entry.encrypted_item_json,
                        encrypted_app_key: entry.encrypted_app_key,
                        created_at: entry.created_at,
                        updated_at: entry.updated_at,
                        item_version: entry.item_version,
                        sequence_number: entry.sequence_number
                    });
                    storedCount++;
                } else {
                    console.error(`[ChatDatabase] Error storing app settings/memories entry ${entry.id}:`, entryError);
                }
            }
        }

        // Wait for all operations to complete
        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.info(`[ChatDatabase] App settings/memories sync complete: stored ${storedCount}, skipped ${skippedCount}, conflicts resolved ${conflictResolvedCount}`);
    } catch (error) {
        console.error('[ChatDatabase] Error storing app settings/memories entries:', error);
        throw error;
    }
}

/**
 * Get a single app settings/memories entry by ID.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param entryId - The ID of the entry to retrieve
 * @returns The entry if found, null otherwise
 */
export async function getAppSettingsMemoriesEntry(
    dbInstance: ChatDatabaseInstance,
    entryId: string
): Promise<AppSettingsMemoriesEntry | null> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readonly');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);
        const request = store.get(entryId);

        return await new Promise<AppSettingsMemoriesEntry | null>((resolve, reject) => {
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error(`[ChatDatabase] Error getting app settings/memories entry ${entryId}:`, error);
        return null;
    }
}

/**
 * Get all app settings/memories entries.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @returns Array of all entries
 */
export async function getAllAppSettingsMemoriesEntries(
    dbInstance: ChatDatabaseInstance
): Promise<AppSettingsMemoriesEntry[]> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readonly');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);
        const request = store.getAll();

        return await new Promise<AppSettingsMemoriesEntry[]>((resolve, reject) => {
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error('[ChatDatabase] Error getting all app settings/memories entries:', error);
        return [];
    }
}

/**
 * Get all app settings/memories entries for a specific app.
 * Uses the app_id index for efficient filtering.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param appId - The ID of the app to filter by
 * @returns Array of entries for the specified app
 */
export async function getAppSettingsMemoriesEntriesByApp(
    dbInstance: ChatDatabaseInstance,
    appId: string
): Promise<AppSettingsMemoriesEntry[]> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readonly');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);
        const index = store.index('app_id');
        const request = index.getAll(appId);

        return await new Promise<AppSettingsMemoriesEntry[]>((resolve, reject) => {
            request.onsuccess = () => resolve(request.result || []);
            request.onerror = () => reject(request.error);
        });
    } catch (error) {
        console.error(`[ChatDatabase] Error getting app settings/memories entries for app ${appId}:`, error);
        return [];
    }
}

/**
 * Delete an app settings/memories entry by ID.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param entryId - The ID of the entry to delete
 * @returns True if deletion was successful, false otherwise
 */
export async function deleteAppSettingsMemoriesEntry(
    dbInstance: ChatDatabaseInstance,
    entryId: string
): Promise<boolean> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);
        store.delete(entryId);

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.debug(`[ChatDatabase] Successfully deleted app settings/memories entry: ${entryId}`);
        return true;
    } catch (error) {
        console.error(`[ChatDatabase] Error deleting app settings/memories entry ${entryId}:`, error);
        return false;
    }
}

/**
 * Delete all app settings/memories entries for a specific app.
 * Uses the app_id index to find all entries, then deletes them.
 * 
 * @param dbInstance - Reference to the ChatDatabase instance
 * @param appId - The ID of the app whose entries should be deleted
 * @returns Number of entries deleted
 */
export async function deleteAppSettingsMemoriesEntriesByApp(
    dbInstance: ChatDatabaseInstance,
    appId: string
): Promise<number> {
    if (!dbInstance.db) throw new Error('[ChatDatabase] Database not initialized');

    try {
        // First get all entries for this app
        const entries = await getAppSettingsMemoriesEntriesByApp(dbInstance, appId);
        
        if (entries.length === 0) {
            console.debug(`[ChatDatabase] No app settings/memories entries found for app ${appId}`);
            return 0;
        }

        const transaction = dbInstance.db.transaction([dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME], 'readwrite');
        const store = transaction.objectStore(dbInstance.APP_SETTINGS_MEMORIES_STORE_NAME);

        // Delete all entries
        for (const entry of entries) {
            store.delete(entry.id);
        }

        await new Promise<void>((resolve, reject) => {
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });

        console.info(`[ChatDatabase] Deleted ${entries.length} app settings/memories entries for app ${appId}`);
        return entries.length;
    } catch (error) {
        console.error(`[ChatDatabase] Error deleting app settings/memories entries for app ${appId}:`, error);
        return 0;
    }
}


