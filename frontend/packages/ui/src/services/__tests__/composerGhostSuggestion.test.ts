import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { persistComposerGhostSuggestion, persistPostProcessingComposerFallback } from '../composerGhostSuggestion';
import type { Chat, AIMessageUpdatePayload } from '../../types/chat';
import type { ChatSynchronizationService } from '../chatSyncService';

const mocks = vi.hoisted(() => ({
  epoch: 1,
  clearCache: () => {},
  auth: { isAuthenticated: true },
  profile: { user_id: 'owner', follow_up_suggestions_enabled: true },
  team: { value: null as string | null },
  encrypt: vi.fn(),
  row: {} as Chat,
  beforeRead: () => {},
  completeTransaction: vi.fn(),
  put: vi.fn(),
  current: true,
  listeners: new Map<string, (value: unknown) => void>(),
  chat: { chat_id: 'chat', user_id: 'owner', encrypted_chat_key: 'wrapped-key' },
  getChat: vi.fn(), updateChat: vi.fn(), send: vi.fn(),
}));
vi.mock('svelte/store', () => ({ get: (store: { value: unknown }) => store.value }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => mocks.epoch, registerWorkspaceCacheClear: (clear: () => void) => { mocks.clearCache = clear; } }));
vi.mock('../lateChatMetadataGuard', () => ({ isChatMetadataTurnCurrent: () => mocks.current }));
vi.mock('../../stores/authStore', () => ({ authStore: { value: mocks.auth } }));
vi.mock('../../stores/userProfile', () => ({ userProfile: { value: mocks.profile } }));
vi.mock('../../stores/teamStore', () => ({ activeTeamId: mocks.team }));
vi.mock('../db', () => ({ chatDB: {
  getChat: mocks.getChat, updateChat: mocks.updateChat,
  CHATS_STORE_NAME: 'chats',
  db: { transaction: () => {
    const transaction = { oncomplete: null as (() => void) | null, onerror: null, onabort: null,
      objectStore: () => ({
        put: mocks.put,
        get: () => {
          const request = { result: undefined as Chat | undefined, onsuccess: null as (() => void) | null };
          queueMicrotask(() => {
            mocks.beforeRead();
            request.result = { ...mocks.row };
            request.onsuccess!();
            void mocks.completeTransaction().then(() => transaction.oncomplete!());
          });
          return request;
        },
      }),
    };
    return transaction;
  } },
} }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: async () => 'key' } }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: mocks.encrypt, decryptWithChatKey: vi.fn() }));
vi.mock('../chatKeyWriteGuard', () => ({ ensureChatKeySafeForWrite: async () => true }));
vi.mock('../websocketService', () => ({ webSocketService: {
  sendMessage: mocks.send,
  on: (type: string, callback: (value: unknown) => void) => mocks.listeners.set(type, callback),
  off: (type: string) => mocks.listeners.delete(type),
} }));

const NOT_STORED = 'encrypted_suggested_followup_message_not_stored';
const payload = { chat_id: 'chat', message_id: 'assistant', task_id: 'task', user_message_id: 'user',
  suggested_followup_message: 'What comes next?', is_final_chunk: true } as AIMessageUpdatePayload;
const stale = { code: 'stale_suggested_followup_source', chat_id: 'chat',
  source_message_id: 'assistant', source_task_id: 'task', source_user_message_id: 'user' };

async function start() {
  const service = Object.assign(new EventTarget(), { activeAITasks: new Map<string, { taskId: string }>() });
  const dispatch = vi.fn();
  await persistComposerGhostSuggestion(payload, service as unknown as ChatSynchronizationService, dispatch);
  expect(mocks.send).toHaveBeenCalledTimes(1);
  return { service, dispatch };
}
function stored(service: EventTarget) {
  service.dispatchEvent(new CustomEvent('aiResponseStorageConfirmed', { detail: { chatId: 'chat', messageId: 'assistant' } }));
}
async function flush() {
  await vi.advanceTimersByTimeAsync(0);
}

// contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
describe('optional suggestion source CAS outcomes', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    mocks.clearCache();
    mocks.listeners.clear(); mocks.epoch = 1; mocks.current = true;
    mocks.profile.follow_up_suggestions_enabled = true; mocks.team.value = null; mocks.auth.isAuthenticated = true;
    mocks.encrypt.mockResolvedValue('opaque-ciphertext');
    mocks.row = { ...mocks.chat } as Chat;
    mocks.beforeRead = () => {};
    mocks.completeTransaction.mockResolvedValue(undefined);
    mocks.put.mockImplementation((chat: Chat) => { mocks.row = chat; });
    mocks.getChat.mockImplementation(async () => ({ ...mocks.row }));
    mocks.updateChat.mockResolvedValue(undefined); mocks.send.mockResolvedValue(undefined);
  });
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('waits for exact storage confirmation and retries at most once without using the error channel', async () => {
    const { service } = await start();
    expect(mocks.listeners.has('error')).toBe(false);
    mocks.listeners.get(NOT_STORED)!(stale);
    await flush(); expect(mocks.send).toHaveBeenCalledTimes(1);
    service.dispatchEvent(new CustomEvent('aiResponseStorageConfirmed', { detail: { chatId: 'chat', messageId: 'another' } }));
    await flush(); expect(mocks.send).toHaveBeenCalledTimes(1);
    stored(service); await flush(); expect(mocks.send).toHaveBeenCalledTimes(2);
    mocks.listeners.get(NOT_STORED)!(stale);
    expect(mocks.listeners.has(NOT_STORED)).toBe(false);
    stored(service); await flush(); expect(mocks.send).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each(['chat_id', 'source_message_id', 'source_task_id', 'source_user_message_id'])('ignores a different %s', async (field) => {
    const { service } = await start(); stored(service);
    mocks.listeners.get(NOT_STORED)!({ ...stale, [field]: 'another' });
    await flush(); expect(mocks.send).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each(['turn', 'account'])('does not retry after the %s owner changes', async (owner) => {
    const { service, dispatch } = await start();
    mocks.listeners.get(NOT_STORED)!(stale);
    if (owner === 'turn') mocks.current = false; else mocks.epoch++;
    stored(service); await flush();
    expect(mocks.send).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.listeners.has(NOT_STORED)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('retries once when exact storage confirmation preceded the not-stored result', async () => {
    const { service } = await start(); stored(service);
    mocks.listeners.get(NOT_STORED)!(stale); await flush();
    expect(mocks.send).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('removes the bounded lifecycle after a matching success acknowledgement', async () => {
    const { service } = await start();
    mocks.listeners.get('encrypted_suggested_followup_message_stored')!(stale);
    expect(mocks.listeners.has(NOT_STORED)).toBe(false);
    stored(service); await flush(); expect(mocks.send).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('does not retry with a replacement active task', async () => {
    const { service } = await start();
    mocks.listeners.get(NOT_STORED)!(stale);
    service.activeAITasks.set('chat', { taskId: 'newer-task' });
    stored(service); await flush();
    expect(mocks.send).toHaveBeenCalledTimes(1);
    expect(mocks.listeners.has(NOT_STORED)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('expires the optional lifecycle without claiming persistence or retrying', async () => {
    const { service } = await start();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(mocks.listeners.has(NOT_STORED)).toBe(false);
    stored(service); await flush(); expect(mocks.send).toHaveBeenCalledTimes(1);
  });
  const fallback = { chat_id: 'chat', task_id: 'task', user_message_id: 'user',
    harmful_response: 0, follow_up_request_suggestions: ['  First fallback?  ', 'Second fallback?'] };
  function setupFallback() {
    const service = Object.assign(new EventTarget(), { activeAITasks: new Map<string, { taskId: string }>() });
    const dispatch = vi.fn();
    return { service: service as unknown as ChatSynchronizationService, dispatch };
  }
  async function finishWithoutMain(service: ChatSynchronizationService, dispatch: ReturnType<typeof vi.fn>) {
    await persistComposerGhostSuggestion({ ...payload, suggested_followup_message: undefined }, service, dispatch);
  }

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('uses only the first valid fresh fallback, exact final IDs, and ciphertext persistence; ignores duplicate events', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    expect(dispatch).not.toHaveBeenCalled();
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    expect(dispatch).toHaveBeenCalledExactlyOnceWith({ text: 'First fallback?', sourceMessageId: 'assistant',
      sourceTaskId: 'task', sourceUserMessageId: 'user' });
    expect(JSON.parse(mocks.encrypt.mock.calls[0][0])).toEqual(dispatch.mock.calls[0][0]);
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.put.mock.calls[0][0].encrypted_suggested_followup_message).toBe('opaque-ciphertext');
    expect(mocks.send.mock.calls[0][1]).not.toHaveProperty('text');
    expect(mocks.send.mock.calls[0][1].source_message_id).toBe('assistant');
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('preserves a main suggestion and ignores duplicate finals', async () => {
    const { service, dispatch } = await start();
    await persistPostProcessingComposerFallback(fallback, service as unknown as ChatSynchronizationService, dispatch);
    await persistComposerGhostSuggestion(payload, service as unknown as ChatSynchronizationService, dispatch);
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch.mock.calls[0][0].text).toBe('What comes next?');
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('lets a late main replace an already displayed fallback', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    await persistComposerGhostSuggestion(payload, service, dispatch);
    expect(dispatch.mock.calls.map(call => call[0].text)).toEqual(['First fallback?', 'What comes next?']);
    expect(JSON.parse(mocks.encrypt.mock.calls.at(-1)![0]).text).toBe('What comes next?');
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('fences an in-flight fallback and writes the late main last', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    let finishEncryption!: (value: string) => void;
    mocks.encrypt.mockImplementationOnce(() => new Promise(resolve => { finishEncryption = resolve; }));
    const pending = persistPostProcessingComposerFallback(fallback, service, dispatch);
    await flush();
    const main = persistComposerGhostSuggestion(payload, service, dispatch);
    finishEncryption('fallback-ciphertext');
    await Promise.all([pending, main]);
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.put.mock.calls[0][0].encrypted_suggested_followup_message).toBe('opaque-ciphertext');
    expect(dispatch.mock.calls.at(-1)![0].text).toBe('What comes next?');
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('serializes an already-started fallback database write before the late main write', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    let finishWrite!: () => void;
    mocks.completeTransaction.mockImplementationOnce(() => new Promise<void>(resolve => { finishWrite = resolve; }));
    const pending = persistPostProcessingComposerFallback(fallback, service, dispatch);
    await flush();
    expect(mocks.put).toHaveBeenCalledTimes(1);
    const main = persistComposerGhostSuggestion(payload, service, dispatch);
    await flush();
    expect(mocks.put).toHaveBeenCalledTimes(1);
    finishWrite();
    await Promise.all([pending, main]);
    expect(mocks.put).toHaveBeenCalledTimes(2);
    expect(dispatch.mock.calls.at(-1)![0].text).toBe('What comes next?');
    expect(mocks.send).toHaveBeenCalledTimes(1);
    expect(JSON.parse(mocks.encrypt.mock.calls.at(-1)![0]).text).toBe('What comes next?');
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('forgets completed sources on workspace invalidation', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    mocks.clearCache();
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    expect(dispatch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('patches only the encrypted ghost and preserves concurrent drafts and post-processing metadata', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    mocks.beforeRead = () => {
      mocks.row = { ...mocks.row, encrypted_draft_md: 'new-draft', draft_v: 7,
        encrypted_chat_summary: 'new-summary', encrypted_follow_up_request_suggestions: 'new-chips' };
    };
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    expect(mocks.updateChat).not.toHaveBeenCalled();
    expect(mocks.row).toMatchObject({ encrypted_draft_md: 'new-draft', draft_v: 7,
      encrypted_chat_summary: 'new-summary', encrypted_follow_up_request_suggestions: 'new-chips',
      encrypted_suggested_followup_message: 'opaque-ciphertext' });
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each(['chat', 'task', 'user', 'epoch', 'turn', 'active-task', 'harmful', 'missing-user'])('rejects a stale or unsafe %s source', async (kind) => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    const event = { ...fallback };
    if (kind === 'chat') event.chat_id = 'another';
    if (kind === 'task') event.task_id = 'another';
    if (kind === 'user') event.user_message_id = 'another';
    if (kind === 'missing-user') event.user_message_id = '';
    if (kind === 'epoch') mocks.epoch++;
    if (kind === 'turn') mocks.current = false;
    if (kind === 'active-task') service.activeAITasks.set('chat', { taskId: 'newer' } as never);
    if (kind === 'harmful') event.harmful_response = 1;
    await persistPostProcessingComposerFallback(event, service, dispatch);
    expect(dispatch).not.toHaveBeenCalled(); expect(mocks.put).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each(['absent', 'continuation', 'rejected', 'revoked', 'soft-limit'])('requires a successful completed final (%s)', async (kind) => {
    const { service, dispatch } = setupFallback();
    if (kind !== 'absent') await persistComposerGhostSuggestion({ ...payload, suggested_followup_message: undefined,
      awaiting_async_skill_continuation: kind === 'continuation', rejection_reason: kind === 'rejected' ? 'error' : undefined,
      interrupted_by_revocation: kind === 'revoked', interrupted_by_soft_limit: kind === 'soft-limit' }, service, dispatch);
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    expect(dispatch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each(['disabled', 'logged-out', 'incognito', 'anonymous', 'shared', 'subchat', 'parent', 'team', 'owner'])('honors %s privacy eligibility', async (kind) => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    const chat = { ...mocks.chat, is_incognito: kind === 'incognito', is_anonymous: kind === 'anonymous',
      is_shared_by_others: kind === 'shared', is_sub_chat: kind === 'subchat', parent_id: kind === 'parent' ? 'parent' : undefined };
    if (kind === 'logged-out') mocks.auth.isAuthenticated = false;
    if (kind === 'disabled') mocks.profile.follow_up_suggestions_enabled = false;
    if (kind === 'team') mocks.team.value = 'different-team';
    if (kind === 'owner') chat.user_id = 'other-owner';
    mocks.getChat.mockResolvedValue(chat);
    await persistPostProcessingComposerFallback(fallback, service, dispatch);
    expect(dispatch).not.toHaveBeenCalled(); expect(mocks.encrypt).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it.each([null, {}, [], [null, 42, '', '   ', 'x'.repeat(401)]])('ignores malformed or empty fallback lists %j', async (suggestions) => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    await persistPostProcessingComposerFallback({ ...fallback, follow_up_request_suggestions: suggestions }, service, dispatch);
    expect(dispatch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.followups.main-generated-composer,chats.persistence.client-encrypted
  it('skips invalid candidates before the first bounded nonempty text', async () => {
    const { service, dispatch } = setupFallback();
    await finishWithoutMain(service, dispatch);
    await persistPostProcessingComposerFallback({ ...fallback, follow_up_request_suggestions: [null, '', 'x'.repeat(401), '  valid  '] }, service, dispatch);
    expect(dispatch.mock.calls[0][0].text).toBe('valid');
  });

});
