import { describe, expect, it, vi } from 'vitest';
import {
  chatTransaction, COVERED_CHAT_DATABASE_VERSION, COVERED_MESSAGE_STORE, LEGACY_CHAT_DATABASE_VERSION,
  LEGACY_MESSAGE_STORE, OPENED_HISTORY_STORE, preferredChatDatabaseVersion,
} from '../openedHistoryStorage';

// contract-test: infrastructure
describe('opened history storage boundary', () => {
  it('avoids an upgrade over a live legacy database and selects a gated schema for a fresh cache', async () => {
    const databases = vi.fn()
      .mockResolvedValueOnce([{ name: 'chats_db', version: 32 }])
      .mockResolvedValueOnce([{ name: 'chats_db', version: 33 }])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ name: 'chats_db', version: 35 }]);
    const factory = { databases, open: vi.fn(), deleteDatabase: vi.fn() } as unknown as IDBFactory;
    await expect(preferredChatDatabaseVersion(factory, 'chats_db')).resolves.toBe(LEGACY_CHAT_DATABASE_VERSION);
    await expect(preferredChatDatabaseVersion(factory, 'chats_db')).resolves.toBe(LEGACY_CHAT_DATABASE_VERSION);
    await expect(preferredChatDatabaseVersion(factory, 'chats_db')).resolves.toBe(COVERED_CHAT_DATABASE_VERSION);
    await expect(preferredChatDatabaseVersion(factory, 'chats_db')).resolves.toBe(35);
    expect(factory.open).not.toHaveBeenCalled();
    expect(factory.deleteDatabase).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.browser-durable-history
  it('routes logical reads and invalidates a receipt in the mutation transaction', () => {
    const revision = { put: vi.fn(), clear: vi.fn() };
    const previous = Object.assign(new EventTarget(), { result: { chat_id: 'older-chat' } });
    const rows = { get: vi.fn(() => previous), put: vi.fn(), delete: vi.fn(), clear: vi.fn() };
    const database = { version: COVERED_CHAT_DATABASE_VERSION, transaction: vi.fn() };
    const native = {
      db: database, objectStoreNames: { contains: (name: string) => name === OPENED_HISTORY_STORE },
      objectStore: (name: string) => name === OPENED_HISTORY_STORE ? revision : rows,
    };
    database.transaction.mockReturnValue(native);

    const transaction = chatTransaction(database as unknown as IDBDatabase, LEGACY_MESSAGE_STORE, 'readwrite');
    const store = transaction.objectStore(LEGACY_MESSAGE_STORE);
    store.put({ message_id: 'one', chat_id: 'newer-chat' });
    previous.dispatchEvent(new Event('success'));

    expect(database.transaction).toHaveBeenCalledExactlyOnceWith(
      [COVERED_MESSAGE_STORE, OPENED_HISTORY_STORE], 'readwrite',
    );
    expect(rows.put).toHaveBeenCalledExactlyOnceWith({ message_id: 'one', chat_id: 'newer-chat' });
    expect(revision.put.mock.calls.map(([entry]) => entry.chatId)).toEqual(['newer-chat', 'older-chat']);
    expect(revision.put.mock.calls.every(([entry]) => typeof entry.revision === 'string' && !('ciphertext' in entry))).toBe(true);
    store.clear();
    expect(revision.clear).toHaveBeenCalledOnce();
    expect(rows.clear).toHaveBeenCalledOnce();
  });
});
