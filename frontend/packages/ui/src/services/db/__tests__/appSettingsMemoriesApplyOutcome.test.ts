import { describe, expect, it, vi } from 'vitest';
import { storeAppSettingsMemoriesEntries, type AppSettingsMemoriesEntry } from '../appSettingsMemories';

const row = (version = 2, updated = 20): AppSettingsMemoriesEntry => ({
  id: 'entry', app_id: 'privacy', item_type: 'personal_data_entry', item_key: 'key',
  encrypted_item_json: 'ciphertext', encrypted_app_key: '', created_at: 1,
  updated_at: updated, item_version: version,
});

/** Deliver IndexedDB request success before transaction completion, as in IDB. */
function database(existing?: AppSettingsMemoriesEntry, failure?: 'read' | 'abort') {
  const transaction = {
    oncomplete: null as (() => void) | null, onerror: null as (() => void) | null,
    onabort: null as (() => void) | null, error: null,
    objectStore: () => store,
  };
  const store = {
    get: vi.fn(() => {
      const request = { result: existing, error: new Error('read failed'),
        onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
      queueMicrotask(() => failure === 'read' ? request.onerror?.() : request.onsuccess?.());
      setTimeout(() => failure === 'abort' ? transaction.onabort?.() : transaction.oncomplete?.(), 0);
      return request;
    }),
    put: vi.fn(), add: vi.fn(),
  };
  return { db: { transaction: () => transaction } as unknown as IDBDatabase,
    APP_SETTINGS_MEMORIES_STORE_NAME: 'memories', store };
}

describe('committed app memories merge outcome', () => {
  // contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it.each([[row(2, 20), row(2, 20)], [row(3, 30), row(2, 20)], [row(2, 30), row(2, 20)]])(
    'proves an unchanged merge only after version and timestamp conflict handling', async (existing, incoming) => {
      const db = database(existing);
      expect(await storeAppSettingsMemoriesEntries(db, [incoming])).toEqual({ applied: 0, complete: true });
      expect(db.store.put).not.toHaveBeenCalled();
      expect(db.store.add).not.toHaveBeenCalled();
    });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it.each([undefined, row(1, 10), row(2, 10)])('reports an inserted or updated encrypted record as applied', async existing => {
    const db = database(existing);
    expect(await storeAppSettingsMemoriesEntries(db, [row()])).toEqual({ applied: 1, complete: true });
    expect(db.store.put.mock.calls.length + db.store.add.mock.calls.length).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('cannot certify a swallowed entry read failure or unknown deletion shape', async () => {
    expect(await storeAppSettingsMemoriesEntries(database(row(), 'read'), [row()]))
      .toEqual({ applied: 0, complete: false });
    const tombstone = { ...row(), deleted_at: 30 };
    expect(await storeAppSettingsMemoriesEntries(database(row()), [tombstone]))
      .toEqual({ applied: 0, complete: false });
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('rejects an aborted merge rather than certifying its pending writes', async () => {
    await expect(storeAppSettingsMemoriesEntries(database(row(), 'abort'), [row()])).rejects.toThrow('aborted');
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.preprocessing.prepared-privacy
  it('distinguishes empty insert/update work from ignored removed-app input', async () => {
    expect(await storeAppSettingsMemoriesEntries(database(), [])).toEqual({ applied: 0, complete: true });
    expect(await storeAppSettingsMemoriesEntries(database(), [{ ...row(), app_id: 'ai' }]))
      .toEqual({ applied: 0, complete: false });
  });
});
