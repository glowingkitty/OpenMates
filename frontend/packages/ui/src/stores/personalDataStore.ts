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

import { authStore } from "./authState";
import { userProfile } from "./userProfile";
import { registerWorkspaceCacheClear } from "../services/workspaceCacheLifecycle";
import { getWorkspaceCacheIdentity } from "../services/workspaceQueryCache";
import { writable, derived, get } from "svelte/store";
import { chatDB } from "../services/db";
import {
  decryptWithMasterKey,
  encryptWithMasterKey,
  getKeyFromStorage,
} from "../services/cryptoService";
import { chatSyncService } from "../services/chatSyncService";

// ─── Constants ──────────────────────────────────────────────────────────────

/** App ID used for all privacy entries in the user_app_settings_and_memories collection */
const PRIVACY_APP_ID = "privacy";

/** item_type for individual personal data entries (name, address, birthday, custom) */
const PERSONAL_DATA_ITEM_TYPE = "personal_data_entry";

/** item_type for the PII detection settings singleton (master toggle + categories) */
const PII_SETTINGS_ITEM_TYPE = "pii_detection_settings";

/** item_type for the location precision settings singleton */
const LOCATION_SETTINGS_ITEM_TYPE = "location_settings";

// ─── Types ──────────────────────────────────────────────────────────────────

/** Type of personal data entry */
export type PersonalDataType = "name" | "address" | "birthday" | "custom";

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

/**
 * Location precision settings — controls whether the "nearby by default" (imprecise)
 * mode is active when the user opens the map location picker.
 *
 * When impreciseByDefault is true (the default), coordinates sent to the LLM are
 * randomised within a 500m radius of the selected location to protect exact position.
 * The precise pin is still stored locally for the embed preview.
 */
export interface LocationSettings {
  /** When true, area mode is selected by default in the map picker (privacy-first) */
  impreciseByDefault: boolean;
}

/** PII detection category toggle settings */
export interface PIIDetectionSettings {
  /** Master toggle — if false, no PII detection at all */
  masterEnabled: boolean;
  /** Optional on-device model; baseline regex and configured entries stay active. */
  enhancedEnabled: boolean;
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
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ─── Internal State ─────────────────────────────────────────────────────────

/** Store for user-defined personal data entries */
const personalDataEntries = writable<PersonalDataEntry[]>([]);

/** Store for PII detection settings (master toggle + per-category toggles) */
const piiDetectionSettings = writable<PIIDetectionSettings>({
  masterEnabled: true,
  enhancedEnabled: true,
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

// ─── Location Settings State ─────────────────────────────────────────────────

/** Store for location precision settings */
const locationSettingsStore = writable<LocationSettings>({
  impreciseByDefault: true,
});

/** Location settings singleton metadata — null if not yet saved */
let locationSettingsEntryId: string | null = null;
let locationSettingsItemKey: string | null = null;
let locationSettingsVersion: number = 0;
let locationSettingsCreatedAt: number = 0;

/** Loading state to prevent duplicate concurrent loads */
const enhancementReadyStore = writable(false);
const ANONYMOUS_ENHANCEMENT_KEY = "openmates:anonymous:enhanced-pii";
let enhancementOwner: string | null | undefined;
let hydrationSequence = 0;
let privacyMutationEpoch = 0;
let deferredLoading: { owner: string | null; generation: number; work: Promise<void> } | null = null;
let privacySyncOwner: string | null = null;
let loading: { owner: string | null; mutation: number; work: Promise<void> } | null = null;
function isEnhancementOwnerCurrent(owner: string | null): boolean {
  const auth = get(authStore);
  return auth.isInitialized && owner === getWorkspaceCacheIdentity()
    && (owner !== null ? auth.isAuthenticated : !auth.isAuthenticated);
}

/** Reuse the current owner's hydration; never initialize a model from defaults
 * while encrypted account preferences are still loading. */
function loadFromStorage(): Promise<void> {
  return loadOwnedPreferences();
}

function loadOwnedPreferences(forMutationInitialization = false): Promise<void> {
  const owner = getWorkspaceCacheIdentity();
  if (!isEnhancementOwnerCurrent(owner)) return Promise.resolve();
  if (privacyPersistenceError?.scope === owner) {
    enhancementReadyStore.set(false);
    return Promise.resolve();
  }
  if (hasPendingPrivacyMutations()) {
    enhancementReadyStore.set(false);
    // An initializing action enters here before its own work is registered.
    // Existing work therefore belongs to another mutation; do not wait on a
    // registry that will subsequently include this action itself.
    if (forMutationInitialization) return Promise.resolve();
    return deferHydrationUntilMutationsSettle(owner);
  }
  if (loading?.owner === owner && loading.mutation === privacyMutationEpoch) return loading.work;
  const work = performLoadFromStorage(owner).finally(() => {
    if (loading?.work === work) loading = null;
  });
  loading = { owner, mutation: privacyMutationEpoch, work };
  return work;
}

/** Keep deferred work separate from the active read registry: an initializing
 * mutator must never await a deferred reload that is waiting for that mutator. */
function deferHydrationUntilMutationsSettle(owner: string | null): Promise<void> {
  const generation = hydrationSequence;
  if (deferredLoading?.owner === owner && deferredLoading.generation === generation) return deferredLoading.work;
  const work = waitForPrivacyMutations().then(saved => {
    if (saved && generation === hydrationSequence && isEnhancementOwnerCurrent(owner)) return loadOwnedPreferences();
  }).catch(() => {
    // A failed or superseded write cannot authorize older encrypted defaults.
  }).finally(() => {
    if (deferredLoading?.work === work) deferredLoading = null;
  });
  deferredLoading = { owner, generation, work };
  return work;
}

/** A sync event changes encrypted authority even when an older read is pending.
 * Close model readiness and fence that read before fetching the updated rows. */
function reloadFromStorage(): Promise<void> {
  hydrationSequence += 1;
  enhancementReadyStore.set(false);
  loading = null;
  return loadFromStorage();
}

// ─── Persistence: Load from IndexedDB ───────────────────────────────────────

async function ensureEnhancementReady(): Promise<void> {
  if (enhancementOwner !== undefined && isEnhancementOwnerCurrent(enhancementOwner)
      && get(enhancementReadyStore)) return;
  await loadFromStorage();
}

/**
 * Load all privacy entries from IndexedDB, decrypt them, and populate the stores.
 * Called when privacy settings are opened or after a sync event.
 *
 * Safe to call multiple times — reloads fresh data to pick up cross-device changes.
 */
async function performLoadFromStorage(privacyOwner: string | null): Promise<void> {
  const sequence = ++hydrationSequence;
  const mutation = privacyMutationEpoch;
  const current = () => sequence === hydrationSequence && mutation === privacyMutationEpoch
    && isEnhancementOwnerCurrent(privacyOwner);
  let hydrated = false;
  enhancementReadyStore.set(false);
  enhancementOwner = privacyOwner;
  if (privacyOwner === null) {
    let enhancedEnabled = true;
    try { enhancedEnabled = localStorage.getItem(ANONYMOUS_ENHANCEMENT_KEY) !== "false"; }
    catch { /* A storage-restricted browser still gets privacy-first defaults. */ }
    piiDetectionSettings.update(settings => ({ ...settings, enhancedEnabled }));
    enhancementReadyStore.set(current());
    return;
  }

  try {
    // Check if master key is available (user is authenticated)
    const masterKey = await getKeyFromStorage();
    if (!current()) return;
    if (!masterKey) {
      console.warn(
        "[PersonalDataStore] No master key available — skipping load",
      );
      return;
    }

    // Fetch all privacy entries from IndexedDB
    const encryptedEntries =
      await chatDB.getAppSettingsMemoriesEntriesByApp(PRIVACY_APP_ID);

    if (!current()) return;
    if (!encryptedEntries || encryptedEntries.length === 0) {
      // A cold cache is not evidence that the account has no opt-out.
      // The initial encrypted sync must first establish the missing default.
      hydrated = privacySyncOwner === privacyOwner;
      return;
    }
    let settingsFailed = false;

    const loadedEntries: PersonalDataEntry[] = [];
    const loadedMetadata = new Map<string, StorageMetadata>();

    for (const entry of encryptedEntries) {
      try {
        const decryptedJson = await decryptWithMasterKey(
          entry.encrypted_item_json,
        );
        if (!current()) return;
        if (!decryptedJson) {
          if (entry.item_type === PII_SETTINGS_ITEM_TYPE) settingsFailed = true;
          console.warn(
            `[PersonalDataStore] Failed to decrypt entry ${entry.id}`,
          );
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
            enhancedEnabled: data.enhancedEnabled ?? true,
            categories: {
              ...DEFAULT_PII_CATEGORIES,
              ...(data.categories || {}),
            },
          });

          console.debug(
            "[PersonalDataStore] Loaded PII detection settings from storage",
          );
        } else if (entry.item_type === LOCATION_SETTINGS_ITEM_TYPE) {
          // Location precision settings singleton
          locationSettingsEntryId = entry.id;
          locationSettingsItemKey = entry.item_key;
          locationSettingsVersion = entry.item_version;
          locationSettingsCreatedAt = entry.created_at;

          locationSettingsStore.set({
            impreciseByDefault: data.impreciseByDefault ?? true,
          });

          console.debug(
            "[PersonalDataStore] Loaded location settings from storage",
          );
        } else if (entry.item_type === PERSONAL_DATA_ITEM_TYPE) {
          // Personal data entry (name, address, birthday, custom)
          const personalEntry: PersonalDataEntry = {
            id: entry.id,
            type: data.type || "custom",
            title: data.title || "",
            textToHide: data.textToHide || "",
            replaceWith: data.replaceWith || "",
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
        if (entry.item_type === PII_SETTINGS_ITEM_TYPE) settingsFailed = true;
        console.error(
          `[PersonalDataStore] Error processing entry ${entry.id}:`,
          error,
        );
      }
    }

    if (!current()) return;
    // Update stores with loaded data
    personalDataEntries.set(loadedEntries);

    // Rebuild metadata map
    entryStorageMetadata.clear();
    loadedMetadata.forEach((meta, id) => {
      entryStorageMetadata.set(id, meta);
    });

    hydrated = !settingsFailed && (piiSettingsEntryId !== null || privacySyncOwner === privacyOwner);
    console.info(
      `[PersonalDataStore] Loaded ${loadedEntries.length} personal data entries from storage`,
    );
  } catch (error) {
    console.error("[PersonalDataStore] Error loading from storage:", error);
  } finally {
    if (current() && hydrated) enhancementReadyStore.set(true);
  }
}

// ─── Persistence: Encrypt & Save ────────────────────────────────────────────

/**
 * Encrypt a personal data entry and save to IndexedDB + sync to server.
 */
async function encryptAndSaveEntry(
  personalEntry: PersonalDataEntry,
  version: number,
): Promise<void> {
  const privacyOwner = getWorkspaceCacheIdentity();
  const assertOwner = () => {
    if (!privacyOwner || privacyOwner !== getWorkspaceCacheIdentity()) throw new Error("Personal privacy owner changed during save");
  };
  assertOwner();
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

  const encryptedItemJson = await encryptWithMasterKey(
    JSON.stringify(itemData),
  );
  if (!encryptedItemJson) {
    throw new Error(
      "Failed to encrypt personal data entry — master key may not be available",
    );
  }

  // Get or generate hashed item_key
  let hashedItemKey: string;
  const existingMeta = entryStorageMetadata.get(personalEntry.id);
  if (existingMeta) {
    hashedItemKey = existingMeta.itemKey;
  } else {
    const rawHash = await hashString(
      `${PRIVACY_APP_ID}-${personalEntry.id}-${nowSeconds}`,
    );
    hashedItemKey = rawHash.substring(0, 32);
  }

  const encryptedEntry = {
    id: personalEntry.id,
    app_id: PRIVACY_APP_ID,
    item_key: hashedItemKey,
    item_type: PERSONAL_DATA_ITEM_TYPE,
    encrypted_item_json: encryptedItemJson,
    encrypted_app_key: "",
    created_at: existingMeta?.createdAt ?? nowSeconds,
    updated_at: nowSeconds,
    item_version: version,
    sequence_number: undefined,
  };

  assertOwner();
  // Store in IndexedDB
  await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);
  assertOwner();

  // Update storage metadata
  entryStorageMetadata.set(personalEntry.id, {
    itemKey: hashedItemKey,
    itemVersion: version,
    createdAt: encryptedEntry.created_at,
  });

  // Sync to server (fire-and-forget — don't block on network errors)
  try {
    const syncSuccess =
      await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
    if (syncSuccess) {
      console.debug(
        `[PersonalDataStore] Synced entry ${personalEntry.id} to server`,
      );
    } else {
      recordPrivacyFailure(new Error("Personal privacy server write was not acknowledged"), privacyOwner);
      console.warn(
        `[PersonalDataStore] Failed to sync entry ${personalEntry.id} to server (will retry on reconnect)`,
      );
    }
  } catch (syncError) {
    recordPrivacyFailure(syncError, privacyOwner);
    console.error(
      `[PersonalDataStore] Error syncing entry ${personalEntry.id} to server:`,
      syncError,
    );
  }
}

/**
 * Encrypt PII detection settings and save to IndexedDB + sync to server.
 */
async function persistPiiSettings(): Promise<void> {
  const privacyOwner = getWorkspaceCacheIdentity();
  const assertOwner = () => {
    if (!privacyOwner || privacyOwner !== getWorkspaceCacheIdentity()) throw new Error("Personal privacy owner changed during save");
  };
  assertOwner();
  const settings = get(piiDetectionSettings);
  const nowSeconds = Math.floor(Date.now() / 1000);

  const itemData = {
    masterEnabled: settings.masterEnabled,
    enhancedEnabled: settings.enhancedEnabled,
    categories: settings.categories,
    _original_item_key: "pii_detection_settings",
    settings_group: PII_SETTINGS_ITEM_TYPE,
  };

  const encryptedItemJson = await encryptWithMasterKey(
    JSON.stringify(itemData),
  );
  if (!encryptedItemJson) {
    throw new Error(
      "Failed to encrypt PII settings — master key may not be available",
    );
  }

  assertOwner();
  // Create or update the singleton entry
  const isNew = !piiSettingsEntryId;
  if (isNew) {
    const entryId = crypto.randomUUID();
    const rawHash = await hashString(
      `${PRIVACY_APP_ID}-pii_detection_settings-${nowSeconds}`,
    );
    assertOwner();
    piiSettingsEntryId = entryId;
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
    encrypted_app_key: "",
    created_at: piiSettingsCreatedAt,
    updated_at: nowSeconds,
    item_version: piiSettingsVersion,
    sequence_number: undefined,
  };

  assertOwner();
  // Store in IndexedDB
  await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);
  assertOwner();

  // Sync to server
  try {
    const syncSuccess =
      await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
    if (syncSuccess) {
      console.debug("[PersonalDataStore] Synced PII settings to server");
    } else {
      recordPrivacyFailure(new Error("Personal privacy server write was not acknowledged"), privacyOwner);
      console.warn("[PersonalDataStore] Failed to sync PII settings to server");
    }
  } catch (syncError) {
    recordPrivacyFailure(syncError, privacyOwner);
    console.error(
      "[PersonalDataStore] Error syncing PII settings to server:",
      syncError,
    );
  }
}

/**
 * Encrypt location settings and save to IndexedDB + sync to server.
 * Follows the same singleton pattern as persistPiiSettings().
 */
async function persistLocationSettings(): Promise<void> {
  const settings = get(locationSettingsStore);
  const nowSeconds = Math.floor(Date.now() / 1000);

  const itemData = {
    impreciseByDefault: settings.impreciseByDefault,
    _original_item_key: "location_settings",
    settings_group: LOCATION_SETTINGS_ITEM_TYPE,
  };

  const encryptedItemJson = await encryptWithMasterKey(
    JSON.stringify(itemData),
  );
  if (!encryptedItemJson) {
    throw new Error(
      "Failed to encrypt location settings — master key may not be available",
    );
  }

  const isNew = !locationSettingsEntryId;
  if (isNew) {
    locationSettingsEntryId = crypto.randomUUID();
    const rawHash = await hashString(
      `${PRIVACY_APP_ID}-location_settings-${nowSeconds}`,
    );
    locationSettingsItemKey = rawHash.substring(0, 32);
    locationSettingsVersion = 1;
    locationSettingsCreatedAt = nowSeconds;
  } else {
    locationSettingsVersion += 1;
  }

  const encryptedEntry = {
    id: locationSettingsEntryId!,
    app_id: PRIVACY_APP_ID,
    item_key: locationSettingsItemKey!,
    item_type: LOCATION_SETTINGS_ITEM_TYPE,
    encrypted_item_json: encryptedItemJson,
    encrypted_app_key: "",
    created_at: locationSettingsCreatedAt,
    updated_at: nowSeconds,
    item_version: locationSettingsVersion,
    sequence_number: undefined,
  };

  await chatDB.storeAppSettingsMemoriesEntries([encryptedEntry]);

  try {
    const syncSuccess =
      await chatSyncService.sendStoreAppSettingsMemoriesEntry(encryptedEntry);
    if (syncSuccess) {
      console.debug("[PersonalDataStore] Synced location settings to server");
    } else {
      console.warn(
        "[PersonalDataStore] Failed to sync location settings to server",
      );
    }
  } catch (syncError) {
    console.error(
      "[PersonalDataStore] Error syncing location settings to server:",
      syncError,
    );
  }
}

// ─── Entry Management ───────────────────────────────────────────────────────

/**
 * Add a new personal data entry.
 * Encrypts the entry, stores in IndexedDB, and syncs to server.
 */
async function addEntry(
  entry: Omit<PersonalDataEntry, "id" | "createdAt" | "updatedAt">,
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

  console.info(
    `[PersonalDataStore] Added ${newEntry.type} entry "${newEntry.title}"`,
  );
  return newEntry;
}

/**
 * Update an existing personal data entry.
 * Re-encrypts and syncs the changes.
 */
async function updateEntry(
  id: string,
  updates: Partial<Omit<PersonalDataEntry, "id" | "createdAt">>,
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
    }),
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
  personalDataEntries.update((entries) =>
    entries.filter((entry) => entry.id !== id),
  );

  // Remove from IndexedDB
  try {
    await chatDB.deleteAppSettingsMemoriesEntry(id);
    entryStorageMetadata.delete(id);
    console.info(`[PersonalDataStore] Removed entry ${id}`);
  } catch (error) {
    console.error(
      `[PersonalDataStore] Error removing entry ${id} from IndexedDB:`,
      error,
    );
  }

  // TODO: Sync deletion to server when backend supports delete for app_settings_memories
}

/**
 * Toggle the enabled state of a personal data entry.
 * Updates in-memory state immediately, then persists asynchronously.
 */
async function toggleEntry(id: string): Promise<void> {
  const privacyOwner = getWorkspaceCacheIdentity();
  const nowSeconds = Math.floor(Date.now() / 1000);

  // Update in-memory store immediately
  let toggledEntry: PersonalDataEntry | undefined;
  personalDataEntries.update((entries) =>
    entries.map((entry) => {
      if (entry.id === id) {
        toggledEntry = {
          ...entry,
          enabled: !entry.enabled,
          updatedAt: nowSeconds,
        };
        return toggledEntry;
      }
      return entry;
    }),
  );

  if (!toggledEntry) return;

  // Persist asynchronously (don't block UI on encryption/network)
  try {
    const meta = entryStorageMetadata.get(id);
    const newVersion = (meta?.itemVersion ?? 0) + 1;
    await encryptAndSaveEntry(toggledEntry, newVersion);
  } catch (error) {
    recordPrivacyFailure(error, privacyOwner);
    console.error(
      `[PersonalDataStore] Failed to persist toggle for entry ${id}:`,
      error,
    );
  }
}

/**
 * Get all entries of a specific type (derived store).
 */
function getEntriesByType(type: PersonalDataType) {
  return derived(personalDataEntries, ($entries) =>
    $entries.filter((entry) => entry.type === type),
  );
}

/**
 * Get all enabled entries (for use by the PII detection engine).
 */
const enabledEntries = derived(personalDataEntries, ($entries) =>
  $entries.filter((entry) => entry.enabled),
);

// ─── PII Detection Settings ─────────────────────────────────────────────────

/**
 * Toggle the master PII detection switch.
 * Updates in-memory state immediately, persists asynchronously.
 */
async function toggleMaster(): Promise<void> {
  await requireHydratedPreferences();
  const privacyOwner = getWorkspaceCacheIdentity();
  // Update in-memory state immediately
  piiDetectionSettings.update((settings) => ({
    ...settings,
    masterEnabled: !settings.masterEnabled,
  }));

  // Persist asynchronously
  try {
    await persistPiiSettings();
  } catch (error) {
    recordPrivacyFailure(error, privacyOwner);
    console.error(
      "[PersonalDataStore] Failed to persist master toggle:",
      error,
    );
  }
}

/**
 * Set the master PII detection switch to a specific value.
 */
async function setMasterEnabled(enabled: boolean): Promise<void> {
  await requireHydratedPreferences();
  const privacyOwner = getWorkspaceCacheIdentity();
  piiDetectionSettings.update((settings) => ({
    ...settings,
    masterEnabled: enabled,
  }));

  try {
    await persistPiiSettings();
  } catch (error) {
    recordPrivacyFailure(error, privacyOwner);
    console.error(
      "[PersonalDataStore] Failed to persist master enabled state:",
      error,
    );
  }
}

async function requireHydratedPreferences(): Promise<void> {
  const owner = getWorkspaceCacheIdentity();
  if (!get(enhancementReadyStore)) await loadOwnedPreferences(true);
  if (!isEnhancementOwnerCurrent(owner) || !get(enhancementReadyStore)) {
    throw new Error("Personal privacy preferences are not ready");
  }
}

/** Persist the enhanced preference through the same owner and write fences. */
async function setEnhancedEnabled(enabled: boolean): Promise<void> {
  const owner = getWorkspaceCacheIdentity();
  await requireHydratedPreferences();
  if (!isEnhancementOwnerCurrent(owner)) throw new Error("Personal privacy owner changed during save");
  piiDetectionSettings.update(settings => ({ ...settings, enhancedEnabled: enabled }));
  if (owner === null) {
    localStorage.setItem(ANONYMOUS_ENHANCEMENT_KEY, String(enabled));
    return;
  }
  await persistPiiSettings();
}

/**
 * Toggle a specific PII detection category.
 * Updates in-memory state immediately, persists asynchronously.
 */
async function toggleCategory(category: string): Promise<void> {
  await requireHydratedPreferences();
  const privacyOwner = getWorkspaceCacheIdentity();
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
    recordPrivacyFailure(error, privacyOwner);
    console.error(
      `[PersonalDataStore] Failed to persist category toggle for ${category}:`,
      error,
    );
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
if (typeof window !== "undefined") {
  window.addEventListener("appSettingsMemoriesSyncReady", () => {
    privacySyncOwner = getWorkspaceCacheIdentity();
    console.debug(
      "[PersonalDataStore] Sync event received — reloading from storage",
    );
    reloadFromStorage().catch((error) => {
      console.error("[PersonalDataStore] Error reloading after sync:", error);
    });
  });
}

if (typeof window !== "undefined") {
  window.addEventListener("appSettingsMemoriesEntrySynced", () => { void reloadFromStorage(); });
}

// ─── Reset ──────────────────────────────────────────────────────────────────

/**
 * Reset all personal data state (e.g., on logout).
 * Clears in-memory stores and metadata. Does NOT delete from IndexedDB
 * (that's handled by the general logout cleanup).
 */
/**
 * Update location precision settings.
 * Updates in-memory state immediately and persists asynchronously.
 */
async function updateLocationSettings(
  updates: Partial<LocationSettings>,
): Promise<void> {
  locationSettingsStore.update((settings) => ({ ...settings, ...updates }));

  try {
    await persistLocationSettings();
  } catch (error) {
    console.error(
      "[PersonalDataStore] Failed to persist location settings:",
      error,
    );
  }
}

function reset(): void {
  hydrationSequence += 1;
  loading = null;
  deferredLoading = null;
  enhancementOwner = undefined;
  enhancementReadyStore.set(false);
  privacyPersistenceError = null;
  personalDataEntries.set([]);
  piiDetectionSettings.set({
    masterEnabled: true,
    enhancedEnabled: true,
    categories: { ...DEFAULT_PII_CATEGORIES },
  });
  locationSettingsStore.set({ impreciseByDefault: true });
  entryStorageMetadata.clear();
  piiSettingsEntryId = null;
  piiSettingsItemKey = null;
  piiSettingsVersion = 0;
  piiSettingsCreatedAt = 0;
  locationSettingsEntryId = null;
  locationSettingsItemKey = null;
  locationSettingsVersion = 0;
  locationSettingsCreatedAt = 0;
}

// An immediate local privacy toggle precedes its encrypted server mutation.
// Sends must not read the old server generation during this write window.
let privacyPersistenceError: { scope: string | null; error: unknown } | null = null;
const privacyMutationWork = new Map<Promise<unknown>, string | null>();
function recordPrivacyFailure(error: unknown, owner: string | null): void {
  if (owner === getWorkspaceCacheIdentity()) {
    privacyPersistenceError = { scope: owner, error };
    enhancementReadyStore.set(false);
  }
}
function hasPendingPrivacyMutations(): boolean {
  const owner = getWorkspaceCacheIdentity();
  return [...privacyMutationWork.values()].some(scope => scope === owner);
}
function privacyMutation<Args extends unknown[], Result>(action: (...args: Args) => Promise<Result>) {
  return (...args: Args): Promise<Result> => {
    const owner = getWorkspaceCacheIdentity();
    privacyMutationEpoch += 1;
    const work = action(...args).catch(error => {
      recordPrivacyFailure(error, owner);
      throw error;
    }).finally(() => { privacyMutationWork.delete(work); });
    privacyMutationWork.set(work, owner);
    return work;
  };
}
async function waitForPrivacyMutations(): Promise<boolean> {
  const owner = getWorkspaceCacheIdentity();
  const deadline = AbortSignal.timeout(10_000);
  while (hasPendingPrivacyMutations()) {
    if (deadline.aborted || owner !== getWorkspaceCacheIdentity()) throw new Error('Personal privacy changes could not finish saving');
    await new Promise<void>((resolve, reject) => {
      const timeout = () => reject(new Error('Personal privacy changes could not finish saving'));
      deadline.addEventListener('abort', timeout, { once: true });
      const owned = [...privacyMutationWork].filter(([, scope]) => scope === owner).map(([work]) => work);
      void Promise.allSettled(owned).then(() => {
        deadline.removeEventListener('abort', timeout); resolve();
      });
    });
  }
  return privacyPersistenceError?.scope !== owner;
}

// ─── Exported Store ─────────────────────────────────────────────────────────

export const personalDataStore = {
  /** Subscribe to all personal data entries */
  subscribe: personalDataEntries.subscribe,

  /** Subscribe to PII detection settings */
  settings: {
    subscribe: piiDetectionSettings.subscribe,
  },
  /** False until this exact account/key owner has hydrated its preference. */
  enhancementReady: derived([enhancementReadyStore, authStore, userProfile], ([ready]) =>
    ready && enhancementOwner !== undefined && isEnhancementOwnerCurrent(enhancementOwner)),
  ensureEnhancementReady,

  /**
   * Subscribe to location precision settings.
   * Use: `$personalDataStore.locationSettings` in Svelte, or
   *      `personalDataStore.locationSettings.subscribe(...)` in TS.
   */
  locationSettings: {
    subscribe: locationSettingsStore.subscribe,
  },

  /** Derived store of all enabled entries */
  enabledEntries,

  /** Get entries filtered by type (returns a derived store) */
  getEntriesByType,

  // Entry management (all async — encrypt, save to IndexedDB, sync to server)
  addEntry: privacyMutation(addEntry),
  updateEntry: privacyMutation(updateEntry),
  removeEntry: privacyMutation(removeEntry),
  toggleEntry: privacyMutation(toggleEntry),

  // Settings management (all async — encrypt, save to IndexedDB, sync to server)
  toggleMaster: privacyMutation(toggleMaster),
  setMasterEnabled: privacyMutation(setMasterEnabled),
  toggleCategory: privacyMutation(toggleCategory),
  setEnhancedEnabled: privacyMutation(setEnhancedEnabled),
  toggleEnhanced: privacyMutation(() => setEnhancedEnabled(!get(piiDetectionSettings).enhancedEnabled)),
  isCategoryEnabled,
  hasPendingPrivacyMutations,
  waitForPrivacyMutations,
  acknowledgePrivacyPersistence: () => { privacyPersistenceError = null; },

  // Location settings management
  updateLocationSettings,

  // Storage: load encrypted data from IndexedDB and decrypt into stores
  loadFromStorage,

  // Reset (on logout)
  reset,
};

// Fence readiness synchronously at account/key changes. Hydration starts only
// after auth initialization; pre-auth defaults must never trigger model traffic.
registerWorkspaceCacheClear(() => {
  reset();
  queueMicrotask(() => { void loadFromStorage(); });
});
let observedOwner: string | null | undefined;
function refreshEnhancementOwner(): void {
  const owner = getWorkspaceCacheIdentity();
  if (!isEnhancementOwnerCurrent(owner)) {
    enhancementReadyStore.set(false);
    return;
  }
  if (observedOwner !== owner || enhancementOwner === undefined) {
    observedOwner = owner;
    reset();
    queueMicrotask(() => { void loadFromStorage(); });
  }
}
authStore.subscribe(refreshEnhancementOwner);
userProfile.subscribe(refreshEnhancementOwner);
