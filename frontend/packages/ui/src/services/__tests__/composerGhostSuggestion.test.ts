import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { persistComposerGhostSuggestion } from '../composerGhostSuggestion';
import type { AIMessageUpdatePayload } from '../../types/chat';
import type { ChatSynchronizationService } from '../chatSyncService';

const mocks = vi.hoisted(() => ({
  epoch: 1,
  current: true,
  listeners: new Map<string, (value: unknown) => void>(),
  chat: { chat_id: 'chat', user_id: 'owner', encrypted_chat_key: 'wrapped-key' },
  getChat: vi.fn(), updateChat: vi.fn(), send: vi.fn(),
}));
vi.mock('svelte/store', () => ({ get: (store: { value: unknown }) => store.value }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => mocks.epoch }));
vi.mock('../lateChatMetadataGuard', () => ({ isChatMetadataTurnCurrent: () => mocks.current }));
vi.mock('../../stores/authStore', () => ({ authStore: { value: { isAuthenticated: true } } }));
vi.mock('../../stores/userProfile', () => ({ userProfile: { value: { user_id: 'owner' } } }));
vi.mock('../../stores/teamStore', () => ({ activeTeamId: { value: null } }));
vi.mock('../db', () => ({ chatDB: { getChat: mocks.getChat, updateChat: mocks.updateChat } }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: async () => 'key' } }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: async () => 'opaque-ciphertext', decryptWithChatKey: vi.fn() }));
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
    mocks.listeners.clear(); mocks.epoch = 1; mocks.current = true;
    mocks.getChat.mockImplementation(async () => ({ ...mocks.chat }));
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
    expect(mocks.updateChat).toHaveBeenCalledTimes(1);
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
});
