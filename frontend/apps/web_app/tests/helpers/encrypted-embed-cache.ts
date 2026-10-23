import { expect, type Page } from '@playwright/test';

interface PartialEmbedCacheFixture {
  apiUrl: string;
  chatId: string;
  embedId: string;
  childId: string;
  ownerId: string;
  cachedChildIds: string[];
}

/** Establish a partial historical cache from real owned ciphertext, independent of sync page order. */
export async function seedPartialEncryptedEmbedCache(page: Page, fixture: PartialEmbedCacheFixture): Promise<void> {
  if (process.env.GITHUB_ACTIONS !== 'true' || process.env.CI_TEST_MODE !== 'e2e') {
    throw new Error('Encrypted cache fixtures require a disposable isolated CI account');
  }
  const state = await page.evaluate(async ({ apiUrl, chatId, embedId, childId, ownerId, cachedChildIds }) => {
    const hash = async (value: string) => Array.from(new Uint8Array(
      await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)),
    )).map(byte => byte.toString(16).padStart(2, '0')).join('');
    const [chatHash, ownerHash, parentHash] = await Promise.all([hash(chatId), hash(ownerId), hash(embedId)]);
    const wanted = new Set([embedId, ...cachedChildIds]);
    const rows = new Map<string, Record<string, unknown>>();
    const keys = new Map<string, Record<string, unknown>>();
    const params = new URLSearchParams();
    for (let pageNumber = 0; pageNumber < 5; pageNumber++) {
      const response = await fetch(`${apiUrl}/v1/embeds/chats/${chatId}/window?${params}`, { credentials: 'include' });
      if (!response.ok) throw new Error(`Encrypted fixture window failed: HTTP ${response.status}`);
      const window = await response.json();
      if (window.chat_id !== chatId || !Array.isArray(window.embeds) || !Array.isArray(window.embed_keys)
        || window.oversized_embed_id || window.embed_keys_has_more_after || window.oversized_embed_key_id) {
        throw new Error('Encrypted fixture window is incomplete or belongs to a different chat');
      }
      for (const row of window.embeds) {
        if (!wanted.has(row.embed_id)) continue;
        if (row.hashed_chat_id !== chatHash || row.hashed_user_id !== ownerHash || row.hashed_team_id
          || row.status !== 'finished' || row.encryption_mode !== 'client' || typeof row.encrypted_content !== 'string'
          || (row.embed_id === embedId ? !!row.parent_embed_id : row.parent_embed_id !== embedId)) {
          throw new Error(`Encrypted fixture row has invalid provenance: ${row.embed_id}`);
        }
        rows.set(row.embed_id, row);
      }
      for (const key of window.embed_keys) {
        if (key.hashed_embed_id !== parentHash || key.hashed_user_id !== ownerHash
          || key.hashed_team_id || key.hashed_project_id || typeof key.encrypted_embed_key !== 'string') continue;
        if (!((key.key_type === 'master' && !key.hashed_chat_id)
          || (key.key_type === 'chat' && key.hashed_chat_id === chatHash))) continue;
        const id = `${key.hashed_embed_id}:${key.key_type}:${key.hashed_chat_id || 'null'}`;
        keys.set(id, { ...key, id });
      }
      if (rows.size === wanted.size && keys.size === 2) break;
      const cursor = window.start_cursor;
      if (!window.has_more_before || !cursor) break;
      if (params.get('before_id') === cursor.id) throw new Error('Encrypted fixture cursor did not advance');
      params.set('before_created_at', String(cursor.created_at));
      params.set('before_id', cursor.id);
    }
    if (rows.size !== wanted.size || keys.size !== 2) {
      throw new Error(`Encrypted fixture incomplete: ${rows.size}/${wanted.size} rows, ${keys.size}/2 parent wrappers`);
    }
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('chats_db');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = db.transaction(['embeds', 'embed_keys'], 'readwrite');
        for (const [id, row] of rows) transaction.objectStore('embeds').put({ ...row,
          contentRef: `embed:${id}`, type: 'app-skill-use', createdAt: row.created_at, updatedAt: row.updated_at });
        for (const key of keys.values()) transaction.objectStore('embed_keys').put(key);
        transaction.objectStore('embeds').delete(`embed:${childId}`);
        transaction.oncomplete = () => resolve(); transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error);
      });
    } finally { db.close(); }
    return { parent: rows.has(embedId), cached: rows.size - 1, target: rows.has(childId) };
  }, fixture);
  expect(state, 'owned encrypted historical cache fixture').toEqual({
    parent: true, cached: fixture.cachedChildIds.length, target: false,
  });
}
