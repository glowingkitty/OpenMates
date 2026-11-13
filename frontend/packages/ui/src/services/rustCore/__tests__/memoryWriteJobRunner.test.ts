import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  handlers: new Map<string, (payload: unknown) => void>(),
  frame: vi.fn(),
  mappings: vi.fn(),
}));

vi.mock('svelte/store', () => ({ get: () => ({ encrypted_settings: 'settings' }) }));
vi.mock('../../../config/api', () => ({ getApiEndpoint: (p: string) => p, setMemoryWriteJobsCapabilityEnabled: vi.fn() }));
vi.mock('../../../stores/userProfile', () => ({ userProfile: {}, updateProfile: vi.fn() }));
vi.mock('../../cryptoService', () => ({ getKeyFromStorage: async () => ({}) }));
vi.mock('../../websocketService', () => ({ webSocketService: {
  on: (kind: string, handler: (payload: unknown) => void) => h.handlers.set(kind, handler),
  off: vi.fn(), sendMessage: vi.fn(async () => undefined), isConnectedOrConnecting: () => false,
  addEventListener: vi.fn(), removeEventListener: vi.fn(), forceReconnect: vi.fn(),
} }));
vi.mock('../../contextEntryEvents', () => ({ storeSystemEvent: vi.fn() }));
vi.mock('../crypto/webCryptoClient', () => ({ rustWebCrypto: () => ({ call: vi.fn() }) }));
vi.mock('../crypto/memoryOps', () => ({ memoryJobFrame: h.frame, memoryJobResume: vi.fn(), memoryUndoPrepare: vi.fn() }));
vi.mock('../memory/memoryPrivacy', () => ({ chatPiiMappings: h.mappings }));

import { installMemoryWriteJobRunner } from '../memory/memoryWriteJobRunner';

describe('memory write job runner', () => {
  beforeEach(() => { h.handlers.clear(); h.frame.mockReset(); h.mappings.mockReset(); });

  // contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
  it('passes the chat mappings to every job frame', async () => {
    const mapping = { placeholder: '[EMAIL_1]', original: 'jane.doe@example.org', type: 'EMAIL' };
    h.mappings.mockResolvedValue([mapping]);
    h.frame.mockResolvedValue({ done: { frames: [] } });
    installMemoryWriteJobRunner();
    h.handlers.get('memory_write_job_available')?.({ chat_id: 'chat-1' });
    await vi.waitFor(() => expect(h.frame).toHaveBeenCalled());
    expect(h.mappings).toHaveBeenCalledWith('chat-1');
    expect(h.frame.mock.calls[0][6]).toEqual([mapping]);
  });
});
