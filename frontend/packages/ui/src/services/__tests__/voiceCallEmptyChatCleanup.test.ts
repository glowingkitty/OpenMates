import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { Chat, Message } from '../../types/chat';
const transport = vi.hoisted(() => ({
  listeners: new Map<string, Set<(value: Record<string, unknown>) => void>>(),
  connection: {} as object | null, identity: 'personal:user', epoch: 1, sendMessage: vi.fn(),
  database: { init: vi.fn(), getTransaction: vi.fn(), getChat: vi.fn(), getMessagesForChat: vi.fn() },
  draft: { currentChatId: 'chat' as string | null, newlyCreatedChatIdToSelect: null,
    hasUnsavedChanges: false, isSaveInProgress: false, isSwitchingContext: false, lastSavedContentMarkdown: null },
  editorJSON: null as unknown,
}));
vi.mock('../websocketService', () => ({ webSocketService: {
  getConnectionForSend: () => transport.connection,
  sendMessage: transport.sendMessage,
  on: (type: string, callback: (value: Record<string, unknown>) => void) => {
    const listeners = transport.listeners.get(type) ?? new Set();
    listeners.add(callback); transport.listeners.set(type, listeners);
  },
  off: (type: string, callback: (value: Record<string, unknown>) => void) => transport.listeners.get(type)?.delete(callback),
} }));
vi.mock('../db', () => ({ chatDB: transport.database }));
vi.mock('../drafts/draftState', () => ({ draftEditorUIState: {
  subscribe: (callback: (value: unknown) => void) => { callback(transport.draft); return () => {}; },
} }));
vi.mock('../drafts/draftCore', () => ({ getEditorInstance: () => transport.editorJSON
  ? { isDestroyed: false, getJSON: () => transport.editorJSON } : null }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => transport.identity }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => transport.epoch }));
import { cleanupEmptyVoiceCallChat, isEmptyVoiceCallCleanupEligible, readEmptyVoiceCallCleanupSnapshot, prepareEmptyVoiceCallLocalDraftGuard,
  type EmptyVoiceCallCleanupSnapshot } from '../voiceCallEmptyChatCleanup';

const input = { chatId: 'chat', cleanupAttemptId: '018fabcd-abcd-7abc-8abc-abcdefabcdef',
  callId: 'f'.repeat(32), expectedMessagesVersion: 2 };
const snapshot = (): EmptyVoiceCallCleanupSnapshot => ({
  chat: { chat_id: 'chat', team_id: null, messages_v: 2, draft_v: 0 } as Chat,
  messages: ['started', 'ended'].map(action => ({ message_id:
    `${action === 'started' ? '00000000' : 'ffffffff'}-voice-call-${input.callId}-${action}`,
    chat_id: 'chat', role: 'system', status: 'synced', content: JSON.stringify({ schema_version: 1,
      type: 'voice_call', action, call_id: input.callId, created_at: 1, active_elapsed_seconds: 0 }),
  })) as Message[],
  artifactCount: 0, pendingOperationCount: 0, hasDraft: false, hasOrdinaryText: false, hasPendingTurn: false,
});
function respond(accepted: boolean, payload: Record<string, unknown>) {
  for (const callback of transport.listeners.get('empty_call_chat_cleanup_result') ?? []) {
    callback({ request_id: payload.request_id, chat_id: payload.chat_id, accepted });
  }
}
beforeEach(() => {
  vi.useFakeTimers(); transport.listeners.clear(); transport.sendMessage.mockReset();
  transport.connection = {}; transport.identity = 'personal:user'; transport.epoch = 1;
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
describe('empty call cleanup', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('accepts only exact, synced lifecycle messages and no other local work', () => {
    expect(isEmptyVoiceCallCleanupEligible(input, snapshot())).toBe(true);
    const changes: Array<(s: EmptyVoiceCallCleanupSnapshot) => void> = [
      s => { s.hasDraft = true; }, s => { s.hasOrdinaryText = true; }, s => { s.hasPendingTurn = true; },
      s => { s.artifactCount = 1; }, s => { s.pendingOperationCount = 1; },
      s => { s.messages.pop(); }, s => { s.messages[0].status = 'sending'; },
      s => { s.messages[0].role = 'user'; }, s => { s.messages[0].content = 'ordinary text'; },
      s => { s.chat!.draft_v = 1; }, s => { s.chat!.team_id = 'team'; },
      s => { s.chat!.encrypted_title = 'authored'; }, s => { s.chat!.messages_v = 3; },
    ];
    for (const change of changes) { const state = snapshot(); change(state); expect(isEmptyVoiceCallCleanupEligible(input, state)).toBe(false); }
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('uses only the dedicated conditional action and rechecks local work after acceptance', async () => {
    transport.sendMessage.mockImplementation(async (_type, payload) => respond(true, payload));
    const initial = snapshot(), changed = snapshot(); changed.hasOrdinaryText = true;
    const read = vi.fn().mockResolvedValueOnce(initial).mockResolvedValueOnce(changed);
    expect(await cleanupEmptyVoiceCallChat(input, read)).toEqual({ accepted: true, localEligible: false });
    expect(transport.sendMessage).toHaveBeenCalledWith('delete_empty_call_chat', expect.objectContaining({
      cleanup_attempt_id: input.cleanupAttemptId, expected_messages_v: 2,
      lifecycle_message_ids: snapshot().messages.map(m => m.message_id),
    }), { expectedConnection: transport.connection });
    expect(transport.listeners.get('empty_call_chat_cleanup_result')?.size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('caps settlement retries at eight conditional requests without falling back to delete_chat', async () => {
    transport.sendMessage.mockImplementation(async (_type, payload) => respond(false, payload));
    const result = cleanupEmptyVoiceCallChat(input, async () => snapshot());
    await vi.runAllTimersAsync();
    expect(await result).toEqual({ accepted: false, localEligible: false });
    expect(transport.sendMessage).toHaveBeenCalledTimes(8);
    expect(vi.getTimerCount()).toBe(0);
    expect(transport.sendMessage.mock.calls.every(([type]) => type === 'delete_empty_call_chat')).toBe(true);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('accepts after settlement takes more than four seconds while preserving the exact request shape', async () => {
    const startedAt = performance.now();
    const observedAt: number[] = [];
    transport.sendMessage.mockImplementation(async (_type, payload) => {
      const elapsed = performance.now() - startedAt;
      observedAt.push(elapsed);
      expect(Object.keys(payload).sort()).toEqual([
        'request_id', 'chat_id', 'cleanup_attempt_id', 'call_id', 'expected_messages_v', 'lifecycle_message_ids',
      ].sort());
      respond(elapsed >= 4340, payload);
    });
    const result = cleanupEmptyVoiceCallChat(input, async () => snapshot());
    await vi.advanceTimersByTimeAsync(4340);
    expect(transport.sendMessage).toHaveBeenCalledTimes(4);
    await vi.runAllTimersAsync();
    expect(await result).toEqual({ accepted: true, localEligible: true });
    expect(observedAt).toEqual([0, 250, 1000, 3000, 7000]);
    expect(vi.getTimerCount()).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it.each(['draft', 'identity', 'epoch', 'connection'] as const)(
    'stops later retries when %s changes during settlement', async change => {
      const state = snapshot();
      transport.sendMessage.mockImplementation(async (_type, payload) => respond(false, payload));
      const result = cleanupEmptyVoiceCallChat(input, async () => state);
      await vi.advanceTimersByTimeAsync(1000);
      expect(transport.sendMessage).toHaveBeenCalledTimes(3);
      if (change === 'draft') state.hasDraft = true;
      if (change === 'identity') transport.identity = 'personal:other';
      if (change === 'epoch') transport.epoch++;
      if (change === 'connection') transport.connection = {};
      await vi.runAllTimersAsync();
      expect(await result).toEqual({ accepted: false, localEligible: false });
      expect(transport.sendMessage).toHaveBeenCalledTimes(3);
      expect(transport.listeners.get('empty_call_chat_cleanup_result')?.size).toBe(0);
    },
  );
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('rechecks connection authority after an asynchronous snapshot before sending', async () => {
    const read = vi.fn(async () => { transport.connection = {}; return snapshot(); });
    expect(await cleanupEmptyVoiceCallChat(input, read)).toEqual({ accepted: false, localEligible: false });
    expect(transport.sendMessage).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('ends silent-server receipt waits at the thirty-second deadline', async () => {
    const startedAt = performance.now();
    transport.sendMessage.mockResolvedValue(undefined);
    const result = cleanupEmptyVoiceCallChat(input, async () => snapshot());
    await vi.advanceTimersByTimeAsync(30_000);
    expect(await result).toEqual({ accepted: false, localEligible: false });
    expect(performance.now() - startedAt).toBe(30_000);
    expect(transport.sendMessage).toHaveBeenCalledTimes(8);
    expect(vi.getTimerCount()).toBe(0);
    expect(transport.listeners.get('empty_call_chat_cleanup_result')?.size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('preserves a locally changed or incomplete shell before making any request', async () => {
    const state = snapshot(); state.hasPendingTurn = true;
    expect(await cleanupEmptyVoiceCallChat(input, async () => state)).toEqual({ accepted: false, localEligible: false });
    expect(transport.sendMessage).not.toHaveBeenCalled();
  });
});


async function factoryDatabase() {
  const stores = ['chats', 'messages', 'embeds', 'embed_keys', 'chat_compression_checkpoints',
    'message_highlights', 'code_run_outputs', 'notebook_run_outputs', 'pending_sync_changes',
    'pending_embed_operations', 'pending_embed_share_updates', 'pending_og_metadata_updates'];
  const rows: Record<string, Array<Record<string, unknown>>> = Object.fromEntries(stores.map(name => [name, []]));
  rows.chats.push(snapshot().chat as unknown as Record<string, unknown>);
  rows.messages.push(...snapshot().messages.map(message => ({ ...message,
    call_persistence_v1: { entries: [], lifecycle_event: 'retained-metadata' } })));
  transport.database.init.mockResolvedValue(undefined);
  transport.database.getTransaction.mockImplementation(async (names: string[]) => {
    const tx = { oncomplete: null as null | (() => void), onerror: null, onabort: null,
      objectStore: (name: string) => {
        if (!names.includes(name) || !rows[name]) throw new Error('Store unavailable');
        return {
          get: (id: string) => request(rows[name].find(row => row.chat_id === id)),
          getAll: (_query: unknown, limit: number) => request(rows[name].slice(0, limit)),
          index: (key: string) => ({
            getAll: (query: string, limit: number) => request(rows[name].filter(row => row[key] === query).slice(0, limit)),
            count: (query: string) => request(rows[name].filter(row => row[key] === query).length),
          }),
        };
      },
    };
    let pending = 0;
    function request(value: unknown) {
      pending++;
      const result = { result: value, onsuccess: null as null | (() => void), onerror: null };
      queueMicrotask(() => {
        result.onsuccess?.(); pending--;
        if (!pending) queueMicrotask(() => tx.oncomplete?.());
      });
      return result;
    }
    return tx;
  });
  transport.database.getChat.mockResolvedValue(snapshot().chat);
  transport.database.getMessagesForChat.mockResolvedValue(snapshot().messages);
  return { rows, close: () => {} };
}
const signals = () => ({ hasLocalOrdinaryText: false, hasPendingTurn: false, isCurrent: () => true });

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
describe('default local snapshot factory', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', webcrypto);
    vi.stubGlobal('sessionStorage', { getItem: () => null });
    Object.assign(transport.draft, { currentChatId: 'chat', hasUnsavedChanges: false,
      isSaveInProgress: false, isSwitchingContext: false, lastSavedContentMarkdown: null });
    transport.editorJSON = null;
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('does not treat completed lifecycle outbox metadata as pending work', async () => {
    const db = await factoryDatabase();
    const state = await readEmptyVoiceCallCleanupSnapshot(input, signals());
    expect(isEmptyVoiceCallCleanupEligible(input, state)).toBe(true);
    db.close();
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('reads actual unsaved editor content and attachment JSON', async () => {
    const db = await factoryDatabase();
    for (const content of [{ type: 'doc', content: [{ type: 'text', text: 'unsaved request' }] },
      { type: 'doc', content: [{ type: 'embed', attrs: { id: 'file', status: 'uploading' } }] }]) {
      transport.editorJSON = content;
      expect((await readEmptyVoiceCallCleanupSnapshot(input, signals())).hasDraft).toBe(true);
    }
    db.close();
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('rechecks the editor synchronously after preparing a final deletion guard', async () => {
    const safe = await prepareEmptyVoiceCallLocalDraftGuard('chat');
    expect(safe()).toBe(true);
    transport.editorJSON = { type: 'doc', content: [{ type: 'text', text: 'late draft' }] };
    expect(safe()).toBe(false);
    transport.editorJSON = null;
    transport.epoch++;
    expect(safe()).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=video-call.lifecycle.recovery-and-billing
  it('counts persisted pending work and returns ineligible for unreadable stores', async () => {
    const db = await factoryDatabase();
    db.rows.pending_sync_changes.push({ id: 'pending', chat_id: 'chat' });
    expect((await readEmptyVoiceCallCleanupSnapshot(input, signals())).pendingOperationCount).toBe(1);
    transport.database.getTransaction.mockRejectedValueOnce(new Error('unreadable'));
    expect((await readEmptyVoiceCallCleanupSnapshot(input, signals())).chat).toBeNull();
    db.close();
  });
});
