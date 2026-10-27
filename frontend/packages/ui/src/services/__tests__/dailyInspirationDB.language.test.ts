import { beforeEach, expect, it, vi } from 'vitest';
import type { StoredDailyInspiration } from '../dailyInspirationDB';
import { getAuthenticatedFallbackInspirations } from '../../demo_chats/hardcodedInspirations';

const records = vi.hoisted(() => new Map<string, StoredDailyInspiration>());
vi.mock('../db', () => ({
  chatDB: {
    init: vi.fn(async () => {}),
    DAILY_INSPIRATIONS_STORE_NAME: 'daily_inspirations',
    db: {
      transaction: () => ({ objectStore: () => ({
        put: (record: StoredDailyInspiration) => {
          records.set(record.inspiration_id, record);
          const request = { onsuccess: null as (() => void) | null, onerror: null };
          queueMicrotask(() => request.onsuccess?.());
          return request;
        },
        getAll: () => {
          const request = { result: [...records.values()], onsuccess: null as (() => void) | null, onerror: null };
          queueMicrotask(() => request.onsuccess?.());
          return request;
        },
      }) }),
    },
  },
}));
vi.mock('../cryptoService', () => ({
  encryptWithMasterKey: vi.fn(async (text: string) => `encrypted:${text}`),
  decryptWithMasterKey: vi.fn(async (text: string) => text.slice('encrypted:'.length)),
}));
vi.mock('../cryptoKeyStorage', () => ({ getMasterKey: vi.fn(async () => new Uint8Array(32)) }));

import { loadInspirationsFromIndexedDB, saveInspirationToIndexedDB } from '../dailyInspirationDB';

beforeEach(() => records.clear());

// contract-test: supporting surface=gui.web assertions=language-preferences.content-language,daily-inspiration.encrypted-persistence,daily-inspiration.opened-state
it('round-trips locale inside encrypted metadata while preserving opened chats', async () => {
  const inspirations = getAuthenticatedFallbackInspirations('de');
  const examples = [inspirations[0], inspirations[3], inspirations[6]];
  for (const item of examples) {
    item.is_opened = true;
    item.opened_chat_id = `saved-${item.inspiration_id}`;
    const stored = await saveInspirationToIndexedDB(item, item.assistant_response ?? item.phrase);
    expect(stored).not.toBeNull();
    expect(stored).not.toHaveProperty('language');
    const metadata = stored!.encrypted_video_metadata ?? stored!.encrypted_wiki_metadata ?? stored!.encrypted_feature_metadata;
    expect(JSON.parse(metadata!.slice('encrypted:'.length)).language).toBe('de');
  }
  const recovered = await loadInspirationsFromIndexedDB();
  expect(recovered).toHaveLength(3);
  for (const item of recovered) {
    expect(item.language).toBe('de');
    expect(item.is_opened).toBe(true);
    expect(item.opened_chat_id).toBe(`saved-${item.inspiration_id}`);
  }
  expect(records.size).toBe(3);
});
