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
 */

const DB_NAME = 'openmates_crypto';
const DB_VERSION = 1;
const STORE_NAME = 'keys';
const MASTER_KEY_ID = 'master_key';

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
    }
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
  
  // Clear the cleanup flag
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem('clear_master_key_on_unload');
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
