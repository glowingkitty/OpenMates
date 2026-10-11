import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../../types/chat';
import { clearRecentChatWindows, getRecentChatRevision, isRecentChatReadCurrent } from '../../recentChatWindowCache';
import { getWorkspaceCacheEpoch } from '../../workspaceCacheLifecycle';
import { applyQueuedMessageRevision, deleteMessage, shouldUpdateMessage, updateMessageRawFields, updateMessageStatus } from '../messageOperations';
import { deleteChat } from '../chatCrudOperations';

const row: Message = {
  message_id: 'message-1', chat_id: 'cold-chat', role: 'user', created_at: 1,
  status: 'synced', encrypted_content: 'ciphertext',
};

function mutationDb(sourceRow: Message = row) {
  const listeners = new Map<string, Array<() => void>>();
  const request = <T>(result: T) => {
    const value = { result, error: null, onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
    queueMicrotask(() => value.onsuccess?.());
    return value;
  };
  const store = {
    get: vi.fn(() => request(sourceRow)),
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

describe('queued message revisions', () => {
  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('accepts authoritative processing handoff but rejects a stale queue receipt', () => {
    const queued: Message = { ...row, status: 'queued', queue_revision: 3, queue_mode: 'follow_up' };
    expect(shouldUpdateMessage(queued, { ...row, status: 'delivered', queue_revision: 3,
      queue_dispatch_status: 'processing' })).toBe(true);
    expect(shouldUpdateMessage(queued, { ...row, status: 'delivered', queue_revision: 2,
      queue_dispatch_status: 'processing' })).toBe(false);
    expect(shouldUpdateMessage({ ...row, status: 'delivered', queue_revision: 3,
      queue_dispatch_status: 'processing' }, { ...queued, queue_dispatch_status: 'queued' })).toBe(false);
    expect(shouldUpdateMessage({ ...row, queue_dispatch_status: 'paused' }, {
      ...queued, queue_dispatch_status: 'queued', queue_dispatch_mode: 'follow_up',
    })).toBe(false);
    expect(shouldUpdateMessage({ ...queued, queue_dispatch_status: 'queued' }, {
      ...row, status: 'delivered', queue_revision: 3, queue_dispatch_status: 'paused',
    })).toBe(true);
    expect(shouldUpdateMessage({ ...row, status: 'synced', queue_dispatch_status: 'processing' }, {
      ...row, status: 'delivered', queue_revision: 3, queue_dispatch_status: 'paused',
    })).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  it('patches only committed ciphertext and queue metadata on the same message ID', async () => {
    const { db, store, complete } = mutationDb({ ...row, content: 'stale plaintext', pii_mappings: [] });
    const revision = applyQueuedMessageRevision(db, row.chat_id, row.message_id, 2, 'steer', 'new-cipher', null);
    await Promise.resolve();
    await Promise.resolve();
    complete();
    expect(await revision).toBe(true);
    expect(store.put).toHaveBeenCalledWith(expect.objectContaining({
      message_id: row.message_id, encrypted_content: 'new-cipher',
      status: 'queued', queue_revision: 2, queue_mode: 'steer',
      encrypted_pii_mappings: undefined,
    }));
    const stored = store.put.mock.calls[0][0] as Message;
    expect(stored.content).toBeUndefined();
    expect(stored.pii_mappings).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  it('ignores stale revisions and a message ID in another chat', async () => {
    for (const chatId of [row.chat_id, 'foreign-chat']) {
      const { db, store, complete } = mutationDb({ ...row, status: 'queued', queue_revision: 3 });
      const revision = applyQueuedMessageRevision(db, chatId, row.message_id, 2, 'follow_up', 'stale-cipher');
      await Promise.resolve();
      await Promise.resolve();
      complete();
      expect(await revision).toBe(false);
      expect(store.put).not.toHaveBeenCalled();
    }
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  it('refuses a mode-only revision gap until the missed ciphertext is synchronized', async () => {
    const { db, store, complete } = mutationDb({ ...row, status: 'queued', queue_revision: 1 });
    const revision = applyQueuedMessageRevision(db, row.chat_id, row.message_id, 3, 'steer');
    await Promise.resolve();
    await Promise.resolve();
    complete();
    expect(await revision).toBe(false);
    expect(store.put).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it('refuses a stale queued snapshot after the durable processing receipt', async () => {
    for (const terminalStatus of ['processing', 'paused'] as const) {
      const { db, store, complete } = mutationDb({ ...row, status: 'synced',
        queue_dispatch_status: terminalStatus, queue_revision: 1 });
      const revision = applyQueuedMessageRevision(db, row.chat_id, row.message_id, 1, 'follow_up');
      await Promise.resolve();
      await Promise.resolve();
      complete();
      expect(await revision).toBe(false);
      expect(store.put).not.toHaveBeenCalled();
    }
  });
});

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
