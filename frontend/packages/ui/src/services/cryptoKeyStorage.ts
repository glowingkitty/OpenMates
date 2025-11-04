/**
 * IndexedDB Storage for CryptoKey Objects
 *
 * This service provides secure storage for Web Crypto API CryptoKey objects.
 * Using IndexedDB provides better isolation than localStorage/sessionStorage.
 *
 * Security Architecture:
 * - Master keys are stored as extractable CryptoKey objects
 *   (Extractable keys allow wrapping for recovery keys while still using Web Crypto API)
 * - Keys are stored in IndexedDB (better isolation than localStorage/sessionStorage)
 * - Keys require Web Crypto API to use (not plain Base64 strings in storage)
 * - XSS can use keys via Web Crypto API anyway, so extractability is a marginal security trade-off
 */

const DB_NAME = 'openmates_crypto';
const DB_VERSION = 1;
const STORE_NAME = 'keys';
const MASTER_KEY_ID = 'master_key';

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
