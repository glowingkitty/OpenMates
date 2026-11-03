/** Real web lifecycle helpers. Never replace auth, chat, embed or sharing APIs. */
import type { Page } from '@playwright/test';

export async function blockAuthoredFixtureImageEgress(page: Page, baseUrl: string, apiUrl: string) {
  const allowed = new Set([new URL(baseUrl).origin, new URL(apiUrl).origin]);
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return !['http:', 'https:'].includes(url.protocol) || allowed.has(url.origin)
      ? route.continue() : route.abort('blockedbyclient');
  });
  // Catalogue images are deliberately external examples, not encrypted selected
  // assets. Leave them as readable failures; never ask the proxy/provider to fetch.
  for (const pattern of ['**/api/v1/image?*', '**/api/v1/metadata?*', '**/api/v1/youtube?*',
    '**/v1/apps/design/icons/iconify/**']) {
    await page.route(pattern, route => route.fulfill({ status: 404, body: '' }));
  }
}

export async function clearAuthoredChatCache(page: Page, baseUrl: string) {
  // Unload the app first, so live sync cannot refill stores during the clear.
  // Keep the authenticated device/account stores and browser cookies intact.
  const neutral = new URL('/e2e-authored-cache-reset', baseUrl).href;
  await page.route(neutral, route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Isolated cache reset</title>' }));
  await page.goto(neutral);
  await page.unroute(neutral);
  return page.evaluate(() => new Promise<Record<string, number>>((resolve, reject) => {
    const opened = indexedDB.open('chats_db');
    opened.onerror = () => reject(new Error('Unable to open disposable chat cache'));
    opened.onsuccess = () => {
      const db = opened.result;
      const names = ['chats', 'messages', 'embeds', 'embed_keys'].filter(name => db.objectStoreNames.contains(name));
      if (names.length !== 4) { db.close(); reject(new Error('Expected chat cache stores are missing')); return; }
      const transaction = db.transaction(names, 'readwrite');
      transaction.onerror = () => { db.close(); reject(new Error('Unable to clear disposable chat cache')); };
      names.forEach(name => transaction.objectStore(name).clear());
      transaction.oncomplete = () => {
        const check = db.transaction(names, 'readonly');
        const counts: Record<string, number> = {};
        names.forEach(name => {
          const request = check.objectStore(name).count();
          request.onsuccess = () => { counts[name] = request.result; };
        });
        check.onerror = () => { db.close(); reject(new Error('Unable to verify disposable cache clear')); };
        check.oncomplete = () => { db.close(); resolve(counts); };
      };
    };
  }));
}

export async function authoredEncryptedSnapshot(page: Page, expected: Array<{ id: string; title: string }>) {
  // Return evidence booleans only. Ciphertext, wrapped keys and decrypted source
  // content never leave the browser through diagnostics or test attachments.
  return page.evaluate(expected => new Promise<Array<{
    id: string; found: boolean; ciphertext: boolean; encryptedType: boolean;
    plainContent: boolean; titleInStoredRow: boolean; rawCryptoFields: boolean;
  }>>((resolve, reject) => {
    const opened = indexedDB.open('chats_db');
    opened.onerror = () => reject(new Error('Unable to inspect encrypted embed cache'));
    opened.onsuccess = () => {
      const db = opened.result;
      if (!db.objectStoreNames.contains('embeds')) { db.close(); reject(new Error('Embed cache is missing')); return; }
      const transaction = db.transaction('embeds', 'readonly');
      const rows: Array<{ id: string; found: boolean; ciphertext: boolean; encryptedType: boolean;
        plainContent: boolean; titleInStoredRow: boolean; rawCryptoFields: boolean }> = [];
      for (const item of expected) {
        const read = transaction.objectStore('embeds').get(`embed:${item.id}`);
        read.onsuccess = () => {
          const row = read.result as Record<string, unknown> | undefined;
          const serialized = JSON.stringify(row ?? {});
          rows.push({ id: item.id, found: !!row,
            ciphertext: typeof row?.encrypted_content === 'string' && row.encrypted_content.length > 0,
            encryptedType: typeof row?.encrypted_type === 'string' && row.encrypted_type.length > 0,
            plainContent: row?.content !== undefined,
            titleInStoredRow: serialized.includes(item.title),
            rawCryptoFields: /"(?:aes_key|aes_nonce|authored_media)"\s*:/.test(serialized) });
        };
      }
      transaction.onerror = () => { db.close(); reject(new Error('Unable to inspect encrypted embed cache')); };
      transaction.oncomplete = () => { db.close(); resolve(rows.sort((left, right) => left.id.localeCompare(right.id))); };
    };
  }), expected);
}
