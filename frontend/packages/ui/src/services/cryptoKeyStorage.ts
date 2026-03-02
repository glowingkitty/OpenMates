/**
 * IndexedDB Storage for CryptoKey Objects
 *
 * This service provides secure storage for Web Crypto API CryptoKey objects.
 * Using IndexedDB provides better isolation than localStorage/sessionStorage.
 *
 * Security Architecture:
 * - Master keys are stored as extractable CryptoKey objects
 *   (Extractable keys allow wrapping for recovery keys while still using Web Crypto API)
 * - Hybrid storage: Memory for stayLoggedIn=false, IndexedDB for stayLoggedIn=true
 * - Keys require Web Crypto API to use (not plain Base64 strings in storage)
 * - XSS can use keys via Web Crypto API anyway, so extractability is a marginal security trade-off
 * 
 * Storage Strategy:
 * - stayLoggedIn=false: Key stored in memory only (auto-cleared on page close)
 * - stayLoggedIn=true: Key stored in IndexedDB (persists across sessions)
 * 
 * Storage Persistence:
 * - When stayLoggedIn=true, we request persistent storage via navigator.storage.persist()
 *   to prevent the browser (especially Safari on iOS) from evicting IndexedDB data
 *   under storage pressure. Without this, iOS Safari can silently delete IndexedDB
 *   data, causing users to lose their master encryption key and appear "logged out".
 * - A localStorage flag 'openmates_was_stay_logged_in' tracks the stayLoggedIn preference
 *   so that forced-logout notifications can differentiate between an expected memory-only
 *   key loss (stayLoggedIn=false) and unexpected storage eviction (stayLoggedIn=true).
 */

const DB_NAME = 'openmates_crypto';
const DB_VERSION = 1;
const STORE_NAME = 'keys';
const MASTER_KEY_ID = 'master_key';

// localStorage key to track stayLoggedIn preference across sessions.
// Used by forced-logout notifications to differentiate between expected key loss
// (stayLoggedIn=false, memory cleared on page close) and unexpected storage eviction
// (stayLoggedIn=true, browser cleared IndexedDB under storage pressure).
const STAY_LOGGED_IN_FLAG = 'openmates_was_stay_logged_in';

// Module-level memory storage for stayLoggedIn=false sessions
// Keys in memory are automatically cleared when the page closes (no async cleanup needed)
let memoryMasterKey: CryptoKey | null = null;
let memoryKeyStayLoggedIn: boolean | null = null; // Track if memory key should persist

/**
 * Opens the IndexedDB database and creates the object store if needed
 */
async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;

      // Create object store if it doesn't exist
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
  });
}

/**
 * Stores master key with stayLoggedIn preference
 * - stayLoggedIn=false: Stores in memory only (auto-cleared on page close)
 * - stayLoggedIn=true: Stores in IndexedDB (persists across sessions)
 * 
 * This hybrid approach ensures keys don't persist when user doesn't want to stay logged in,
 * without relying on unreliable unload handlers.
 * 
 * @param key - The CryptoKey object to store
 * @param stayLoggedIn - If false, key stored in memory only; if true, persisted to IndexedDB
 */
export async function saveMasterKey(key: CryptoKey, stayLoggedIn: boolean): Promise<void> {
  if (stayLoggedIn) {
    // Persist to IndexedDB for long-term storage
    await saveMasterKeyToIndexedDB(key);
    // Clear memory storage (no longer needed)
    memoryMasterKey = null;
    memoryKeyStayLoggedIn = null;
    // Clear the cleanup flag (defense in depth)
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem('clear_master_key_on_unload');
      // Track stayLoggedIn preference in localStorage for forced-logout notification differentiation.
      // localStorage is more durable than IndexedDB on iOS Safari (survives storage pressure).
      localStorage.setItem(STAY_LOGGED_IN_FLAG, 'true');
    }

    // Request persistent storage to prevent browser from evicting IndexedDB.
    // This is critical on iOS Safari which aggressively evicts IndexedDB under storage pressure.
    // The persist() call asks the browser to treat our origin's storage as important/permanent.
    // If denied, storage still works but may be evicted when the device is under storage pressure.
    await requestPersistentStorage();

    console.debug('[cryptoKeyStorage] Master key saved to IndexedDB (stayLoggedIn=true)');
  } else {
    // Store in memory only (automatically cleared on page close)
    memoryMasterKey = key;
    memoryKeyStayLoggedIn = false;
    // Clear IndexedDB if it exists (cleanup from previous session)
    try {
      await clearMasterKeyFromIndexedDB();
    } catch (error) {
      // Ignore errors - IndexedDB might not exist or already be cleared
      console.debug('[cryptoKeyStorage] No IndexedDB key to clear (or already cleared)');
    }
    // Set flag for page load validation (defense in depth)
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('clear_master_key_on_unload', 'true');
      // Clear the stayLoggedIn flag since we're using memory-only storage
      localStorage.removeItem(STAY_LOGGED_IN_FLAG);
    }
    console.debug('[cryptoKeyStorage] Master key saved to memory only (stayLoggedIn=false)');
  }
}

/**
 * Stores an extractable CryptoKey in IndexedDB
 * Extractable keys allow wrapping for recovery keys while still using Web Crypto API
 * @param key - The CryptoKey object to store
 * 
 * Note: We wait for the transaction to complete (not just request.onsuccess)
 * to ensure the data is fully committed before the promise resolves.
 * This prevents race conditions when immediately reading the key back.
 */
export async function saveMasterKeyToIndexedDB(key: CryptoKey): Promise<void> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const request = store.put(key, MASTER_KEY_ID);

    request.onerror = () => {
      db.close();
      reject(request.error);
    };
    
    // Wait for transaction to complete to ensure data is committed
    // This prevents race conditions when reading the key immediately after saving
    transaction.oncomplete = () => {
      db.close();
      resolve();
    };
    
    transaction.onerror = () => {
      db.close();
      reject(transaction.error);
    };
  });
}

/**
 * Retrieves master key from memory (if stayLoggedIn=false) or IndexedDB (if stayLoggedIn=true)
 * Also validates that IndexedDB key should exist based on stayLoggedIn flag (defense in depth)
 * 
 * @returns The CryptoKey object or null if not found
 */
export async function getMasterKey(): Promise<CryptoKey | null> {
  // Defense in depth: Check if we should clear IndexedDB (flag indicates stayLoggedIn was false)
  if (typeof window !== 'undefined') {
    const shouldClear = sessionStorage.getItem('clear_master_key_on_unload') === 'true';
    if (shouldClear) {
      // Flag indicates key should not persist - clear IndexedDB if it exists
      try {
        await clearMasterKeyFromIndexedDB();
        sessionStorage.removeItem('clear_master_key_on_unload');
        console.debug('[cryptoKeyStorage] Cleared IndexedDB key due to stayLoggedIn=false flag');
      } catch (error) {
        // Ignore errors - IndexedDB might not exist or already be cleared
      }
    }
  }
  
  // Check memory first (for stayLoggedIn=false sessions)
  if (memoryMasterKey !== null) {
    return memoryMasterKey;
  }
  
  // Fall back to IndexedDB (for stayLoggedIn=true sessions)
  return await getMasterKeyFromIndexedDB();
}

/**
 * Retrieves the master CryptoKey from IndexedDB
 * @returns The CryptoKey object or null if not found
 */
export async function getMasterKeyFromIndexedDB(): Promise<CryptoKey | null> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], 'readonly');
    const store = transaction.objectStore(STORE_NAME);
    const request = store.get(MASTER_KEY_ID);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const result = request.result;
      resolve(result || null);
    };

    transaction.oncomplete = () => db.close();
  });
}

/**
 * Clears master key from both memory and IndexedDB
 * This is the comprehensive cleanup function used during logout
 */
export async function clearMasterKey(): Promise<void> {
  // Clear memory storage
  memoryMasterKey = null;
  memoryKeyStayLoggedIn = null;
  
  // Clear IndexedDB storage
  await clearMasterKeyFromIndexedDB();
  
  // Clear all flags
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem('clear_master_key_on_unload');
    localStorage.removeItem(STAY_LOGGED_IN_FLAG);
  }
  
  console.debug('[cryptoKeyStorage] Master key cleared from both memory and IndexedDB');
}

/**
 * Removes the master key from IndexedDB
 */
export async function clearMasterKeyFromIndexedDB(): Promise<void> {
  const db = await openDB();

  return new Promise((resolve, reject) => {
    const transaction = db.transaction([STORE_NAME], 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    const request = store.delete(MASTER_KEY_ID);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();

    transaction.oncomplete = () => db.close();
  });
}

/**
 * Checks if the device is "trusted" by verifying if the master key exists in IndexedDB.
 * A device is trusted (and thus allowed to manage passkeys) only if the user selected
 * "stay logged in" during the login/signup process, which persists the master key to IndexedDB.
 *
 * This is a security feature: devices that don't store the master key persistently
 * (stayLoggedIn=false) are not trusted for passkey management operations.
 *
 * @returns true if master key exists in IndexedDB (device is trusted), false otherwise
 */
export async function isDeviceTrusted(): Promise<boolean> {
  try {
    const masterKey = await getMasterKeyFromIndexedDB();
    return masterKey !== null;
  } catch (error) {
    console.error('[cryptoKeyStorage] Error checking device trust:', error);
    return false;
  }
}

/**
 * Deletes the entire IndexedDB database
 * Used during logout to completely remove all crypto keys
 */
export async function deleteCryptoDatabase(): Promise<void> {
  // Clear the stayLoggedIn flag when deleting the database
  if (typeof window !== 'undefined') {
    localStorage.removeItem(STAY_LOGGED_IN_FLAG);
  }

  return new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
    request.onblocked = () => {
      console.warn('Crypto database deletion blocked - database may still be in use');
      // Resolve anyway as the database will be deleted once connections close
      resolve();
    };
  });
}

/**
 * Checks whether the user had stayLoggedIn=true when they last saved their master key.
 * This is used by forced-logout notification logic to differentiate between:
 * - Expected key loss: stayLoggedIn=false, memory cleared on page close → "Enable Stay logged in"
 * - Unexpected eviction: stayLoggedIn=true, browser evicted IndexedDB → "Your data is safe, please log in again"
 * 
 * Uses localStorage because it's more durable than IndexedDB on iOS Safari — localStorage
 * typically survives storage pressure that would evict IndexedDB.
 * 
 * @returns true if the user previously saved with stayLoggedIn=true, false otherwise
 */
export function wasStayLoggedIn(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(STAY_LOGGED_IN_FLAG) === 'true';
}

/**
 * Requests persistent storage from the browser to prevent IndexedDB eviction.
 * 
 * iOS Safari and some other browsers may evict IndexedDB data under storage pressure
 * (low disk space, other apps using storage, iOS memory management). Requesting persistent
 * storage tells the browser our origin's data is important and should not be automatically evicted.
 * 
 * This is critical for protecting encryption keys stored in IndexedDB — if the master key
 * is evicted, the user loses access to all their encrypted chats until they log in again.
 * 
 * Note: The browser may deny the request (returns false), in which case storage still works
 * but remains subject to eviction. Safari grants persistence automatically for sites added
 * to the home screen or bookmarked.
 * 
 * Also logs storage usage information for debugging storage-related issues.
 */
async function requestPersistentStorage(): Promise<void> {
  try {
    if (typeof navigator === 'undefined' || !navigator.storage) {
      console.debug('[cryptoKeyStorage] StorageManager API not available');
      return;
    }

    // Check if storage is already persistent
    const alreadyPersisted = await navigator.storage.persisted();
    if (alreadyPersisted) {
      console.debug('[cryptoKeyStorage] Storage is already persistent ✓');
      await logStorageEstimate();
      return;
    }

    // Request persistent storage
    const granted = await navigator.storage.persist();
    if (granted) {
      console.debug('[cryptoKeyStorage] Persistent storage granted ✓ — IndexedDB data protected from eviction');
    } else {
      console.warn(
        '[cryptoKeyStorage] Persistent storage request denied — IndexedDB data may be evicted under storage pressure. ' +
        'On iOS Safari, adding the site to the home screen or bookmarking it may help.'
      );
    }

    await logStorageEstimate();
  } catch (error) {
    // Non-blocking: persistence request failure should not break key storage
    console.debug('[cryptoKeyStorage] Error requesting persistent storage:', error);
  }
}

/**
 * Logs the current storage usage estimate for debugging.
 * Helps diagnose storage-related issues like quota exceeded or unexpected eviction.
 */
async function logStorageEstimate(): Promise<void> {
  try {
    if (typeof navigator === 'undefined' || !navigator.storage?.estimate) return;

    const estimate = await navigator.storage.estimate();
    const usedMB = estimate.usage ? (estimate.usage / 1024 / 1024).toFixed(2) : 'unknown';
    const quotaMB = estimate.quota ? (estimate.quota / 1024 / 1024).toFixed(0) : 'unknown';
    const percentUsed = (estimate.usage && estimate.quota)
      ? ((estimate.usage / estimate.quota) * 100).toFixed(1)
      : 'unknown';

    console.debug(
      `[cryptoKeyStorage] Storage estimate: ${usedMB} MB used / ${quotaMB} MB quota (${percentUsed}%)`
    );

    // Warn if storage usage exceeds 80% of quota
    if (estimate.usage && estimate.quota && (estimate.usage / estimate.quota) > 0.8) {
      console.warn(
        `[cryptoKeyStorage] ⚠️ Storage usage is at ${percentUsed}% of quota — ` +
        'risk of IndexedDB eviction on browsers without persistent storage'
      );
    }
  } catch (error) {
    // Non-blocking: estimate failure should not break anything
    console.debug('[cryptoKeyStorage] Error getting storage estimate:', error);
  }
}
