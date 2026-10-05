import { beforeEach, describe, expect, it, vi } from 'vitest';
const mock = vi.hoisted(() => ({
  messages: new Map<string, any>(),
  chat: vi.fn(), key: vi.fn(), safe: vi.fn(), encrypt: vi.fn(), send: vi.fn(),
}));
vi.mock('../db', () => ({ chatDB: {
  getChat: mock.chat,
  getMessage: vi.fn(async (id: string) => mock.messages.get(id)),
  saveMessage: vi.fn(async (message: any) => mock.messages.set(message.message_id, message)),
} }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: mock.key } }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: mock.encrypt }));
vi.mock('../chatKeyWriteGuard', () => ({ ensureChatKeySafeForWrite: mock.safe }));
vi.mock('../websocketService', () => ({ webSocketService: { sendMessage: mock.send } }));
import { handleChatContextApplied } from '../chatSyncServiceHandlersAgentContext';
const chatId = '00000000-0000-4000-8000-000000000001';
const eventId = '00000000-0000-5000-8000-000000000002';
const payload = () => ({ chat_id: chatId, event: { type: 'memories_loaded', chat_id: chatId,
  event_id: eventId, created_at: 1_780_000_000, count: 1, set_key: 'c'.repeat(64), memories: [{
    id: 'python', title: 'Python coding rules', body: 'Private concrete guide', source: 'project', project_id: 'project-1', revision: 'a'.repeat(64),
  }] } });
const service = { dispatchEvent: vi.fn() };
beforeEach(() => {
  vi.clearAllMocks(); mock.messages.clear();
  mock.chat.mockResolvedValue({ chat_id: chatId }); mock.key.mockResolvedValue(new Uint8Array(32));
  mock.safe.mockResolvedValue(true); mock.encrypt.mockResolvedValue('opaque-ciphertext');
  mock.send.mockResolvedValue(undefined);
});
describe('applied context encrypted receipts', () => {
  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set,chats.persistence.client-encrypted
  it('sends only ciphertext and persists one receipt across duplicate live events', async () => {
    await Promise.all([handleChatContextApplied(service as any, payload()), handleChatContextApplied(service as any, payload())]);
    expect(mock.encrypt).toHaveBeenCalledTimes(1);
    expect(mock.send).toHaveBeenCalledTimes(1);
    const transport = mock.send.mock.calls[0][1];
    expect(transport.message.content).toBeUndefined();
    expect(JSON.stringify(transport)).not.toContain('Private concrete guide');
    expect(transport.message.encrypted_content).toBe('opaque-ciphertext');
    expect(mock.messages.get(eventId).status).toBe('synced');
    expect(service.dispatchEvent).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set,chats.persistence.client-encrypted
  it('retains and retries the exact encrypted receipt after a transport failure', async () => {
    mock.send.mockRejectedValueOnce(new Error('offline'));
    await expect(handleChatContextApplied(service as any, payload())).rejects.toThrow('offline');
    expect(mock.messages.get(eventId).status).toBe('sending');
    await handleChatContextApplied(service as any, payload());
    expect(mock.encrypt).toHaveBeenCalledTimes(1);
    expect(mock.send).toHaveBeenCalledTimes(2);
    expect(mock.messages.get(eventId).status).toBe('synced');
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted,chats.persistence.client-encrypted
  it('does not encrypt or persist when the chat write key is unsafe', async () => {
    mock.safe.mockResolvedValue(false);
    await handleChatContextApplied(service as any, payload());
    expect(mock.encrypt).not.toHaveBeenCalled(); expect(mock.messages.size).toBe(0);
  });
  // contract-test: supporting surface=gui.web assertions=app-memories.transparency.loaded-set,chats.direction.reviewed-correction
  it('rejects cross-chat, malformed and false correction notices', async () => {
    await handleChatContextApplied(service as any, { ...payload(), chat_id: '00000000-0000-4000-8000-000000000003' });
    await handleChatContextApplied(service as any, { ...payload(), event: { ...payload().event, event_id: 'invalid' } });
    await handleChatContextApplied(service as any, { ...payload(), event: { ...payload().event,
      type: 'chat_direction_correction', notice: 'sent', instruction: '', delivery_id: 'test' } });
    expect(mock.encrypt).not.toHaveBeenCalled(); expect(mock.send).not.toHaveBeenCalled();
  });
});
