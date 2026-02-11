/**
 * Personal Data Store — Encrypted Privacy Settings Persistence
 *
 * Manages user-defined personal data entries (names, addresses, birthdays, custom values)
 * and PII detection toggle settings. All data is:
 *
 * 1. **Client-side encrypted** with the user's master key (AES-GCM 256-bit)
 * 2. **Stored in IndexedDB** as encrypted blobs for offline access
 * 3. **Synced to Directus** via WebSocket for cross-device sync and persistence
 *
 * Architecture:
 * - Reuses the existing `user_app_settings_and_memories` infrastructure
 * - Uses `app_id = "privacy"` to namespace all privacy entries
 * - Personal data entries use `item_type = "personal_data_entry"`
 * - PII detection settings use `item_type = "pii_detection_settings"` (singleton)
 * - The server stores encrypted blobs — zero-knowledge, it cannot read names/addresses/etc.
 * - Conflict resolution is handled by `item_version` (higher wins)
 *
 * Data flow:
 *   Store mutation -> encrypt -> IndexedDB -> WebSocket -> Directus
 *   App start/sync -> IndexedDB <- WebSocket <- Directus -> decrypt -> Store
 */

import { writable, derived, get } from 'svelte/store';
import { chatDB } from '../services/db';
import { decryptWithMasterKey, encryptWithMasterKey, getKeyFromStorage } from '../services/cryptoService';
import { chatSyncService } from '../services/chatSyncService';

// ─── Constants ──────────────────────────────────────────────────────────────

/** App ID used for all privacy entries in the user_app_settings_and_memories collection */
const PRIVACY_APP_ID = 'privacy';

/** item_type for individual personal data entries (name, address, birthday, custom) */
const PERSONAL_DATA_ITEM_TYPE = 'personal_data_entry';

/** item_type for the PII detection settings singleton (master toggle + categories) */
const PII_SETTINGS_ITEM_TYPE = 'pii_detection_settings';

// ─── Types ──────────────────────────────────────────────────────────────────

/** Type of personal data entry */
export type PersonalDataType = 'name' | 'address' | 'birthday' | 'custom';

/** A single personal data entry for PII replacement */
export interface PersonalDataEntry {
    /** Unique identifier (UUID) — same ID used in IndexedDB and Directus */
    id: string;
    /** Type of personal data */
    type: PersonalDataType;
    /** User-facing title/label for this entry (e.g., "My first name", "Home address") */
    title: string;
    /** The actual text to detect and hide (e.g., "Max", "123 Main St") */
    textToHide: string;
    /** The placeholder to replace the text with (e.g., "ME_FIRST_NAME", "MY_HOME_ADDRESS") */
    replaceWith: string;
    /** Whether this entry is currently active for detection */
    enabled: boolean;
    /** For address entries: structured address fields */
    addressLines?: AddressFields;
    /** Timestamp of creation (unix seconds) */
    createdAt: number;
    /** Timestamp of last update (unix seconds) */
    updatedAt: number;
}

/** Structured address fields — each line is separately detectable */
export interface AddressFields {
    street: string;
    city: string;
    state: string;
    zip: string;
    country: string;
}

/** PII detection category toggle settings */
export interface PIIDetectionSettings {
    /** Master toggle — if false, no PII detection at all */
    masterEnabled: boolean;
    /** Per-category toggles for auto-detected patterns */
    categories: Record<string, boolean>;
}

// ─── Default PII Categories ────────────────────────────────────────────────

/** Default PII category settings — all enabled by default for maximum privacy */
const DEFAULT_PII_CATEGORIES: Record<string, boolean> = {
    // For everyone
    email_addresses: true,
    phone_numbers: true,
    credit_card_numbers: true,
    iban_bank_account: true,
    tax_id_vat: true,
    crypto_wallets: true,
    social_security_numbers: true,
    passport_numbers: true,
    // For developers
    api_keys: true,
    jwt_tokens: true,
    private_keys: true,
    generic_secrets: true,
    ip_addresses: true,
    mac_addresses: true,
    user_at_hostname: true,
    home_folder: true,
};

// ─── Crypto Helpers ─────────────────────────────────────────────────────────

/**
 * Creates a SHA-256 hash of the input string for privacy protection.
 * Used to hash item_key so the cleartext key is not stored in IndexedDB/Directus.
 */
async function hashString(input: string): Promise<string> {
    const encoder = new TextEncoder();
    const data = encoder.encode(input);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

// ─── Internal State ─────────────────────────────────────────────────────────

/** Store for user-defined personal data entries */
const personalDataEntries = writable<PersonalDataEntry[]>([]);

/** Store for PII detection settings (master toggle + per-category toggles) */
const piiDetectionSettings = writable<PIIDetectionSettings>({
    masterEnabled: true,
    categories: { ...DEFAULT_PII_CATEGORIES },
});

/**
 * Storage metadata for each personal data entry — maps PersonalDataEntry.id
 * to the IndexedDB/Directus storage metadata needed for updates.
 */
interface StorageMetadata {
    /** Hashed item_key stored in IndexedDB (first 32 chars) */
    itemKey: string;
    /** Current item_version for conflict resolution */
    itemVersion: number;
    /** created_at timestamp (unix seconds) */
    createdAt: number;
}

const entryStorageMetadata = new Map<string, StorageMetadata>();

/** PII settings singleton metadata — null if not yet saved */
let piiSettingsEntryId: string | null = null;
let piiSettingsItemKey: string | null = null;
let piiSettingsVersion: number = 0;
let piiSettingsCreatedAt: number = 0;

/** Loading state to prevent duplicate concurrent loads */
let isLoading = false;

// ─── Persistence: Load from IndexedDB ───────────────────────────────────────

/**
 * Load all privacy entries from IndexedDB, decrypt them, and populate the stores.
 * Called when privacy settings are opened or after a sync event.
 *
 * Safe to call multiple times — reloads fresh data to pick up cross-device changes.
 */
async function loadFromStorage(): Promise<void> {
    if (isLoading) return;
    isLoading = true;

    try {
        // Check if master key is available (user is authenticated)
        const masterKey = await getKeyFromStorage();
        if (!masterKey) {
            console.warn('[PersonalDataStore] No master key available — skipping load');
            return;
        }

        // Fetch all privacy entries from IndexedDB
        const encryptedEntries = await chatDB.getAppSettingsMemoriesEntriesByApp(PRIVACY_APP_ID);

        if (!encryptedEntries || encryptedEntries.length === 0) {
            // No entries saved yet — keep defaults
            return;
        }

        const loadedEntries: PersonalDataEntry[] = [];
        const loadedMetadata = new Map<string, StorageMetadata>();

        for (const entry of encryptedEntries) {
            try {
                const decryptedJson = await decryptWithMasterKey(entry.encrypted_item_json);
                if (!decryptedJson) {
                    console.warn(`[PersonalDataStore] Failed to decrypt entry ${entry.id}`);
                    continue;
                }

                const data = JSON.parse(decryptedJson);

                if (entry.item_type === PII_SETTINGS_ITEM_TYPE) {
                    // PII detection settings singleton
                    piiSettingsEntryId = entry.id;
                    piiSettingsItemKey = entry.item_key;
                    piiSettingsVersion = entry.item_version;
                    piiSettingsCreatedAt = entry.created_at;

                    piiDetectionSettings.set({
                        masterEnabled: data.masterEnabled ?? true,
                        categories: { ...DEFAULT_PII_CATEGORIES, ...(data.categories || {}) },
                    });

                    console.debug('[PersonalDataStore] Loaded PII detection settings from storage');

                } else if (entry.item_type === PERSONAL_DATA_ITEM_TYPE) {
                    // Personal data entry (name, address, birthday, custom)
                    const personalEntry: PersonalDataEntry = {
                        id: entry.id,
                        type: data.type || 'custom',
                        title: data.title || '',
                        textToHide: data.textToHide || '',
                        replaceWith: data.replaceWith || '',
                        enabled: data.enabled ?? true,
                        addressLines: data.addressLines,
                        createdAt: entry.created_at,
                        updatedAt: entry.updated_at,
                    };

                    loadedEntries.push(personalEntry);
                    loadedMetadata.set(entry.id, {
                        itemKey: entry.item_key,
                        itemVersion: entry.item_version,
                        createdAt: entry.created_at,
                    });
                }
            } catch (error) {
                console.error(`[PersonalDataStore] Error processing entry ${entry.id}:`, error);
            }
        }

        // Update stores with loaded data
        personalDataEntries.set(loadedEntries);

        // Rebuild metadata map
        entryStorageMetadata.clear();
        for (const [id, meta] of loadedMetadata) {
            entryStorageMetadata.set(id, meta);
        }

        console.info(`[PersonalDataStore] Loaded ${loadedEntries.length} personal data entries from storage`);

    } catch (error) {
        console.error('[PersonalDataStore] Error loading from storage:', error);
    } finally {
        isLoading = false;
    }
}

// ─── Persistence: Encrypt & Save ────────────────────────────────────────────

/**
 * Encrypt a personal data entry and save to IndexedDB + sync to server.
 */
async function encryptAndSaveEntry(personalEntry: PersonalDataEntry, version: number): Promise<void> {
    const nowSeconds = Math.floor(Date.now() / 1000);

    // Build the encrypted payload — all sensitive fields go inside the encrypted JSON
    const itemData = {
        type: personalEntry.type,
        title: personalEntry.title,
        textToHide: personalEntry.textToHide,
        replaceWith: personalEntry.replaceWith,
        enabled: personalEntry.enabled,
        addressLines: personalEntry.addressLines,
        _original_item_key: personalEntry.id,
        settings_group: PERSONAL_DATA_ITEM_TYPE,
    };

    const encryptedItemJson = await encryptWithMasterKey(JSON.stringify(itemData));
    if (!encryptedItemJson) {
        throw new Error('Failed to encrypt personal data entry — master key may not be available');
    }

    // Get or generate hashed item_key
    let hashedItemKey: string;
    const existingMeta = entryStorageMetadata.get(personalEntry.id);
    if (existingMeta) {
        hashedItemKey = existingMeta.itemKey;
    } else {
        const rawHash = await hashString(`${PRIVACY_APP_ID}-${personalEntry.id}-${nowSeconds}`);
        hashedItemKey = rawHash.substring(0, 32);
    }

    const encryptedEntry = {
        id: personalEntry.id,
        app_id: PRIVACY_APP_ID,
        item_key: hashedItemKey,
        item_type: PERSONAL_DATA_ITEM_TYPE,
        encrypted_item_json: encryptedItemJson,
        encrypted_app_key: '',
        created_at: existingMeta?.createdAt ?? nowSeconds,
        updated_at: nowSeconds,
        item_version: version,
        sequence_number: undefined,
    };

    // Store in IndexedDB
    await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);

    // Update storage metadata
    entryStorageMetadata.set(personalEntry.id, {
        itemKey: hashedItemKey,
        itemVersion: version,
        createdAt: encryptedEntry.created_at,
    });

    // Sync to server (fire-and-forget — don't block on network errors)
    try {
        const syncSuccess = await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
        if (syncSuccess) {
            console.debug(`[PersonalDataStore] Synced entry ${personalEntry.id} to server`);
        } else {
            console.warn(`[PersonalDataStore] Failed to sync entry ${personalEntry.id} to server (will retry on reconnect)`);
        }
    } catch (syncError) {
        console.error(`[PersonalDataStore] Error syncing entry ${personalEntry.id} to server:`, syncError);
    }
}

/**
 * Encrypt PII detection settings and save to IndexedDB + sync to server.
 */
async function persistPiiSettings(): Promise<void> {
    const settings = get(piiDetectionSettings);
    const nowSeconds = Math.floor(Date.now() / 1000);

    const itemData = {
        masterEnabled: settings.masterEnabled,
        categories: settings.categories,
        _original_item_key: 'pii_detection_settings',
        settings_group: PII_SETTINGS_ITEM_TYPE,
    };

    const encryptedItemJson = await encryptWithMasterKey(JSON.stringify(itemData));
    if (!encryptedItemJson) {
        throw new Error('Failed to encrypt PII settings — master key may not be available');
    }

    // Create or update the singleton entry
    const isNew = !piiSettingsEntryId;
    if (isNew) {
        piiSettingsEntryId = crypto.randomUUID();
        const rawHash = await hashString(`${PRIVACY_APP_ID}-pii_detection_settings-${nowSeconds}`);
        piiSettingsItemKey = rawHash.substring(0, 32);
        piiSettingsVersion = 1;
        piiSettingsCreatedAt = nowSeconds;
    } else {
        piiSettingsVersion += 1;
    }

    const encryptedEntry = {
        id: piiSettingsEntryId!,
        app_id: PRIVACY_APP_ID,
        item_key: piiSettingsItemKey!,
        item_type: PII_SETTINGS_ITEM_TYPE,
        encrypted_item_json: encryptedItemJson,
        encrypted_app_key: '',
        created_at: piiSettingsCreatedAt,
        updated_at: nowSeconds,
        item_version: piiSettingsVersion,
        sequence_number: undefined,
    };

    // Store in IndexedDB
    await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);

    // Sync to server
    try {
        const syncSuccess = await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
        if (syncSuccess) {
            console.debug('[PersonalDataStore] Synced PII settings to server');
        } else {
            console.warn('[PersonalDataStore] Failed to sync PII settings to server');
        }
    } catch (syncError) {
        console.error('[PersonalDataStore] Error syncing PII settings to server:', syncError);
    }
}

// ─── Entry Management ───────────────────────────────────────────────────────

/**
 * Add a new personal data entry.
 * Encrypts the entry, stores in IndexedDB, and syncs to server.
 */
async function addEntry(
    entry: Omit<PersonalDataEntry, 'id' | 'createdAt' | 'updatedAt'>
): Promise<PersonalDataEntry> {
    const nowSeconds = Math.floor(Date.now() / 1000);

    const newEntry: PersonalDataEntry = {
        ...entry,
        id: crypto.randomUUID(),
        createdAt: nowSeconds,
        updatedAt: nowSeconds,
    };

    // Update in-memory store immediately (UI updates instantly)
    personalDataEntries.update((entries) => [...entries, newEntry]);

    // Encrypt, save to IndexedDB, and sync to server
    await encryptAndSaveEntry(newEntry, 1);

    console.info(`[PersonalDataStore] Added ${newEntry.type} entry "${newEntry.title}"`);
    return newEntry;
}

/**
 * Update an existing personal data entry.
 * Re-encrypts and syncs the changes.
 */
async function updateEntry(
    id: string,
    updates: Partial<Omit<PersonalDataEntry, 'id' | 'createdAt'>>
): Promise<void> {
    const nowSeconds = Math.floor(Date.now() / 1000);

    // Update in-memory store
    let updatedEntry: PersonalDataEntry | undefined;
    personalDataEntries.update((entries) =>
        entries.map((entry) => {
            if (entry.id === id) {
                updatedEntry = { ...entry, ...updates, updatedAt: nowSeconds };
                return updatedEntry;
            }
            return entry;
        })
    );

    if (!updatedEntry) {
        console.error(`[PersonalDataStore] Entry ${id} not found for update`);
        return;
    }

    // Get current version and increment
    const meta = entryStorageMetadata.get(id);
    const newVersion = (meta?.itemVersion ?? 0) + 1;

    // Encrypt, save, and sync
    await encryptAndSaveEntry(updatedEntry, newVersion);
    console.info(`[PersonalDataStore] Updated entry ${id}`);
}

/**
 * Remove a personal data entry.
 * Removes from IndexedDB. Server-side deletion is not yet supported (same
 * limitation as app settings — entries reappear after re-sync until backend
 * implements delete support).
 */
async function removeEntry(id: string): Promise<void> {
    // Update in-memory store
    personalDataEntries.update((entries) => entries.filter((entry) => entry.id !== id));

    // Remove from IndexedDB
    try {
        await chatDB.deleteAppSettingsMemoriesEntry(id);
        entryStorageMetadata.delete(id);
        console.info(`[PersonalDataStore] Removed entry ${id}`);
    } catch (error) {
        console.error(`[PersonalDataStore] Error removing entry ${id} from IndexedDB:`, error);
    }

    // TODO: Sync deletion to server when backend supports delete for app_settings_memories
}

/**
 * Toggle the enabled state of a personal data entry.
 * Updates in-memory state immediately, then persists asynchronously.
 */
async function toggleEntry(id: string): Promise<void> {
    const nowSeconds = Math.floor(Date.now() / 1000);

    // Update in-memory store immediately
    let toggledEntry: PersonalDataEntry | undefined;
    personalDataEntries.update((entries) =>
        entries.map((entry) => {
            if (entry.id === id) {
                toggledEntry = { ...entry, enabled: !entry.enabled, updatedAt: nowSeconds };
                return toggledEntry;
            }
            return entry;
        })
    );

    if (!toggledEntry) return;

    // Persist asynchronously (don't block UI on encryption/network)
    try {
        const meta = entryStorageMetadata.get(id);
        const newVersion = (meta?.itemVersion ?? 0) + 1;
        await encryptAndSaveEntry(toggledEntry, newVersion);
    } catch (error) {
        console.error(`[PersonalDataStore] Failed to persist toggle for entry ${id}:`, error);
    }
}

/**
 * Get all entries of a specific type (derived store).
 */
function getEntriesByType(type: PersonalDataType) {
    return derived(personalDataEntries, ($entries) =>
        $entries.filter((entry) => entry.type === type)
    );
}

/**
 * Get all enabled entries (for use by the PII detection engine).
 */
const enabledEntries = derived(personalDataEntries, ($entries) =>
    $entries.filter((entry) => entry.enabled)
);

// ─── PII Detection Settings ─────────────────────────────────────────────────

/**
 * Toggle the master PII detection switch.
 * Updates in-memory state immediately, persists asynchronously.
 */
async function toggleMaster(): Promise<void> {
    // Update in-memory state immediately
    piiDetectionSettings.update((settings) => ({
        ...settings,
        masterEnabled: !settings.masterEnabled,
    }));

    // Persist asynchronously
    try {
        await persistPiiSettings();
    } catch (error) {
        console.error('[PersonalDataStore] Failed to persist master toggle:', error);
    }
}

/**
 * Set the master PII detection switch to a specific value.
 */
async function setMasterEnabled(enabled: boolean): Promise<void> {
    piiDetectionSettings.update((settings) => ({
        ...settings,
        masterEnabled: enabled,
    }));

    try {
        await persistPiiSettings();
    } catch (error) {
        console.error('[PersonalDataStore] Failed to persist master enabled state:', error);
    }
}

/**
 * Toggle a specific PII detection category.
 * Updates in-memory state immediately, persists asynchronously.
 */
async function toggleCategory(category: string): Promise<void> {
    piiDetectionSettings.update((settings) => ({
        ...settings,
        categories: {
            ...settings.categories,
            [category]: !settings.categories[category],
        },
    }));

    try {
        await persistPiiSettings();
    } catch (error) {
        console.error(`[PersonalDataStore] Failed to persist category toggle for ${category}:`, error);
    }
}

/**
 * Check if a specific PII category is enabled (considering master toggle).
 */
function isCategoryEnabled(category: string): boolean {
    const settings = get(piiDetectionSettings);
    return settings.masterEnabled && (settings.categories[category] ?? true);
}

// ─── Sync Event Listener ────────────────────────────────────────────────────

/**
 * Listen for the appSettingsMemoriesSyncReady event, which fires after the server
 * syncs encrypted entries to IndexedDB (including privacy entries from other devices).
 * When this happens, reload from IndexedDB to pick up changes.
 */
if (typeof window !== 'undefined') {
    window.addEventListener('appSettingsMemoriesSyncReady', () => {
        console.debug('[PersonalDataStore] Sync event received — reloading from storage');
        loadFromStorage().catch((error) => {
            console.error('[PersonalDataStore] Error reloading after sync:', error);
        });
    });
}

// ─── Reset ──────────────────────────────────────────────────────────────────

/**
 * Reset all personal data state (e.g., on logout).
 * Clears in-memory stores and metadata. Does NOT delete from IndexedDB
 * (that's handled by the general logout cleanup).
 */
function reset(): void {
    personalDataEntries.set([]);
    piiDetectionSettings.set({
        masterEnabled: true,
        categories: { ...DEFAULT_PII_CATEGORIES },
    });
    entryStorageMetadata.clear();
    piiSettingsEntryId = null;
    piiSettingsItemKey = null;
    piiSettingsVersion = 0;
    piiSettingsCreatedAt = 0;
}

// ─── Exported Store ─────────────────────────────────────────────────────────

export const personalDataStore = {
    /** Subscribe to all personal data entries */
    subscribe: personalDataEntries.subscribe,

    /** Subscribe to PII detection settings */
    settings: {
        subscribe: piiDetectionSettings.subscribe,
    },

    /** Derived store of all enabled entries */
    enabledEntries,

    /** Get entries filtered by type (returns a derived store) */
    getEntriesByType,

    // Entry management (all async — encrypt, save to IndexedDB, sync to server)
    addEntry,
    updateEntry,
    removeEntry,
    toggleEntry,

    // Settings management (all async — encrypt, save to IndexedDB, sync to server)
    toggleMaster,
    setMasterEnabled,
    toggleCategory,
    isCategoryEnabled,

    // Storage: load encrypted data from IndexedDB and decrypt into stores
    loadFromStorage,

    // Reset (on logout)
    reset,
};
