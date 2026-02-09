/**
 * Personal Data Store
 *
 * Manages user-defined personal data entries (names, addresses, birthdays, custom values)
 * that are used for client-side PII detection and replacement. These entries are
 * client-side encrypted so the server never knows the actual values.
 *
 * Architecture:
 * - All personal data entries are encrypted on the client before storage
 * - The server only stores encrypted blobs — it cannot read names, addresses, etc.
 * - Entries are synced via the existing encrypted settings sync mechanism
 * - Each entry has: id, type, title, textToHide, replaceWith, enabled
 * - Address entries additionally have structured address line fields
 *
 * Privacy guarantee:
 * The replacement values (e.g., "ME_FIRST_NAME") are also encrypted.
 * Only the client-side PII detection engine has access to the decrypted values.
 */

import { writable, derived, get } from 'svelte/store';

// ─── Types ───────────────────────────────────────────────────────────────────

/** Type of personal data entry */
export type PersonalDataType = 'name' | 'address' | 'birthday' | 'custom';

/** A single personal data entry for PII replacement */
export interface PersonalDataEntry {
    /** Unique identifier for this entry */
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
    /** Timestamp of creation */
    createdAt: number;
    /** Timestamp of last update */
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

// ─── Internal State ──────────────────────────────────────────────────────────

/** Store for user-defined personal data entries */
const personalDataEntries = writable<PersonalDataEntry[]>([]);

/** Store for PII detection settings (master toggle + per-category toggles) */
const piiDetectionSettings = writable<PIIDetectionSettings>({
    masterEnabled: true,
    categories: { ...DEFAULT_PII_CATEGORIES },
});

// ─── Helper Functions ────────────────────────────────────────────────────────

/** Generate a unique ID for a new entry */
function generateId(): string {
    return `pd_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

// ─── Entry Management ────────────────────────────────────────────────────────

/**
 * Add a new personal data entry.
 * The entry will be client-side encrypted before being synced to the server.
 */
function addEntry(entry: Omit<PersonalDataEntry, 'id' | 'createdAt' | 'updatedAt'>): PersonalDataEntry {
    const now = Date.now();
    const newEntry: PersonalDataEntry = {
        ...entry,
        id: generateId(),
        createdAt: now,
        updatedAt: now,
    };

    personalDataEntries.update((entries) => [...entries, newEntry]);
    return newEntry;
}

/**
 * Update an existing personal data entry.
 */
function updateEntry(id: string, updates: Partial<Omit<PersonalDataEntry, 'id' | 'createdAt'>>): void {
    personalDataEntries.update((entries) =>
        entries.map((entry) =>
            entry.id === id
                ? { ...entry, ...updates, updatedAt: Date.now() }
                : entry
        )
    );
}

/**
 * Remove a personal data entry.
 */
function removeEntry(id: string): void {
    personalDataEntries.update((entries) => entries.filter((entry) => entry.id !== id));
}

/**
 * Toggle the enabled state of a personal data entry.
 */
function toggleEntry(id: string): void {
    personalDataEntries.update((entries) =>
        entries.map((entry) =>
            entry.id === id
                ? { ...entry, enabled: !entry.enabled, updatedAt: Date.now() }
                : entry
        )
    );
}

/**
 * Get all entries of a specific type.
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
 */
function toggleMaster(): void {
    piiDetectionSettings.update((settings) => ({
        ...settings,
        masterEnabled: !settings.masterEnabled,
    }));
}

/**
 * Set the master PII detection switch.
 */
function setMasterEnabled(enabled: boolean): void {
    piiDetectionSettings.update((settings) => ({
        ...settings,
        masterEnabled: enabled,
    }));
}

/**
 * Toggle a specific PII detection category.
 */
function toggleCategory(category: string): void {
    piiDetectionSettings.update((settings) => ({
        ...settings,
        categories: {
            ...settings.categories,
            [category]: !settings.categories[category],
        },
    }));
}

/**
 * Check if a specific PII category is enabled.
 */
function isCategoryEnabled(category: string): boolean {
    const settings = get(piiDetectionSettings);
    return settings.masterEnabled && (settings.categories[category] ?? true);
}

/**
 * Load personal data entries from encrypted storage.
 * Called during app initialization after user authentication.
 */
function loadEntries(entries: PersonalDataEntry[]): void {
    personalDataEntries.set(entries);
}

/**
 * Load PII detection settings from encrypted storage.
 */
function loadSettings(settings: PIIDetectionSettings): void {
    piiDetectionSettings.set({
        masterEnabled: settings.masterEnabled ?? true,
        categories: { ...DEFAULT_PII_CATEGORIES, ...settings.categories },
    });
}

/**
 * Reset all personal data (e.g., on logout).
 */
function reset(): void {
    personalDataEntries.set([]);
    piiDetectionSettings.set({
        masterEnabled: true,
        categories: { ...DEFAULT_PII_CATEGORIES },
    });
}

// ─── Exported Store ──────────────────────────────────────────────────────────

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

    // Entry management
    addEntry,
    updateEntry,
    removeEntry,
    toggleEntry,
    loadEntries,

    // Settings management
    toggleMaster,
    setMasterEnabled,
    toggleCategory,
    isCategoryEnabled,
    loadSettings,

    // Reset
    reset,
};
