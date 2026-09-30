import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../../types/chat';
import { clearRecentChatWindows, getRecentChatRevision, isRecentChatReadCurrent } from '../../recentChatWindowCache';
import { getWorkspaceCacheEpoch } from '../../workspaceCacheLifecycle';
import { deleteMessage, updateMessageRawFields, updateMessageStatus } from '../messageOperations';
import { deleteChat } from '../chatCrudOperations';

const row: Message = {
  message_id: 'message-1', chat_id: 'cold-chat', role: 'user', created_at: 1,
  status: 'synced', encrypted_content: 'ciphertext',
};

function mutationDb() {
  const listeners = new Map<string, Array<() => void>>();
  const request = <T>(result: T) => {
    const value = { result, error: null, onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
    queueMicrotask(() => value.onsuccess?.());
    return value;
  };
  const store = {
    get: vi.fn(() => request(row)),
    put: vi.fn((value: Message) => request(value)),
    delete: vi.fn(() => request(undefined)),
  };
  const transaction = {
    objectStore: () => store,
    oncomplete: null as (() => void) | null,
    onerror: null as (() => void) | null,
    onabort: null as (() => void) | null,
    error: null,
    addEventListener(type: string, listener: () => void) {
      listeners.set(type, [...(listeners.get(type) ?? []), listener]);
    },
  };
  const db = {
    db: { transaction: () => transaction },
    init: vi.fn(async () => undefined),
  } as unknown as Parameters<typeof updateMessageStatus>[0];
  const complete = () => {
    transaction.oncomplete?.();
    for (const listener of listeners.get('complete') ?? []) listener();
  };
  return { db, store, complete };
}

afterEach(clearRecentChatWindows);

describe('canonical message mutations fence recent chat windows', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('fences chat deletion while its view is unmounted and again on transaction commit', async () => {
    const listeners: Array<() => void> = [];
    const request = (result: unknown) => {
      const value = { result, error: null, onsuccess: null as ((event: { target: { result: unknown } }) => void) | null, onerror: null as (() => void) | null };
      queueMicrotask(() => value.onsuccess?.({ target: value }));
      return value;
    };
    const transaction = {
      objectStore: (name: string) => name === 'chats'
        ? { delete: () => request(undefined) }
        : { index: () => ({ openCursor: () => request(null) }) },
      addEventListener: (type: string, listener: () => void) => { if (type === 'complete') listeners.push(listener); },
    } as unknown as IDBTransaction;
    vi.stubGlobal('IDBKeyRange', { only: (value: string) => value });
    const revision = getRecentChatRevision(row.chat_id);
    const pending = deleteChat({
      init: vi.fn(async () => undefined), CHATS_STORE_NAME: 'chats',
    } as unknown as Parameters<typeof deleteChat>[0], row.chat_id, transaction);
    await pending;
    expect(getRecentChatRevision(row.chat_id)).not.toBe(revision);
    const beforeCommit = getRecentChatRevision(row.chat_id);
    listeners.forEach((listener) => listener());
    expect(getRecentChatRevision(row.chat_id)).not.toBe(beforeCommit);
    vi.unstubAllGlobals();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('fences a cold in-flight read before and after deleting a message outside the cache', async () => {
    const { db, store, complete } = mutationDb();
    const revision = getRecentChatRevision(row.chat_id);
    const epoch = getWorkspaceCacheEpoch();
    let releaseOldRead!: (messages: Message[]) => void;
    const oldRead = new Promise<Message[]>((resolve) => { releaseOldRead = resolve; });
    const visibleRead = oldRead.then((messages) => isRecentChatReadCurrent(row.chat_id, epoch, revision) ? messages : []);
    const pending = deleteMessage(db, row.message_id);
    await vi.waitFor(() => expect(store.delete).toHaveBeenCalled());
    expect(getRecentChatRevision(row.chat_id)).not.toBe(revision);
    const beforeCommit = getRecentChatRevision(row.chat_id);
    complete();
    await pending;
    expect(getRecentChatRevision(row.chat_id)).not.toBe(beforeCommit);
    releaseOldRead([{ ...row }]);
    expect(await visibleRead, 'a late canonical read cannot republish the deleted row').toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it.each(['status', 'raw fields'] as const)('fences uncached %s writes by the stored chat id', async (kind) => {
    const { db, store, complete } = mutationDb();
    const revision = getRecentChatRevision(row.chat_id);
    const pending = kind === 'status'
      ? updateMessageStatus(db, row.message_id, 'delivered')
      : updateMessageRawFields(db, row.message_id, { status: 'delivered' });
    await vi.waitFor(() => expect(store.put).toHaveBeenCalled());
    expect(getRecentChatRevision(row.chat_id)).not.toBe(revision);
    complete();
    await pending;
  });
});
