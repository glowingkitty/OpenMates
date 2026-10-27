/** Read the existing local account's locale without starting auth, sync or creating a database. */
export async function readCachedAccountLanguage(): Promise<string | null> {
  if (typeof indexedDB === 'undefined') return null;
  try {
    if (indexedDB.databases && !(await indexedDB.databases()).some(database => database.name === 'user_db')) return null;
    return await new Promise<string | null>(resolve => {
      let settled = false;
      let database: IDBDatabase | null = null;
      const finish = (language: string | null) => {
        if (settled) return;
        settled = true;
        clearTimeout(deadline);
        database?.close();
        resolve(language);
      };
      // A blocked/evicted legacy database must not block a public app startup.
      const deadline = setTimeout(() => finish(null), 1000);
      const request = indexedDB.open('user_db');
      request.onupgradeneeded = () => { request.transaction?.abort(); finish(null); };
      request.onerror = request.onblocked = () => finish(null);
      request.onsuccess = () => {
        database = request.result;
        if (settled) { database.close(); return; }
        if (!database.objectStoreNames.contains('user_data')) { finish(null); return; }
        const transaction = database.transaction('user_data', 'readonly');
        const store = transaction.objectStore('user_data');
        const id = store.get('id');
        const language = store.get('language');
        transaction.oncomplete = () => finish(id.result && typeof language.result === 'string' ? language.result : null);
        transaction.onerror = transaction.onabort = () => finish(null);
      };
    });
  } catch { return null; }
}
