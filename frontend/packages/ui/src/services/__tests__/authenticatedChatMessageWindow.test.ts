import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ epoch: 1, fetch: vi.fn(), db: {
  getRawChat: vi.fn(), batchSaveMessages: vi.fn(), getMessageWindowForChat: vi.fn(),
  recordMessageWindowPage: vi.fn(), evictStaleMessageWindowPages: vi.fn(), saveChatCompressionCheckpoint: vi.fn(),
} }));
vi.mock('../db', () => ({ chatDB: mocks.db }));
vi.mock('../workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: () => mocks.epoch }));
vi.mock('../../stores/teamStore', async () => ({ activeTeamId: (await import('svelte/store')).writable(null) }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => path, storageArchiveFetch: mocks.fetch }));
import { fetchAuthenticatedChatMessageWindow, loadCanonicalCallCheckpoints } from '../authenticatedChatMessageWindow';

beforeEach(() => {
  vi.clearAllMocks(); mocks.epoch = 1;
  mocks.db.getRawChat.mockResolvedValue({ chat_id: 'chat', team_id: null });
  mocks.db.getMessageWindowForChat.mockResolvedValue({ messages: [], hasMoreBefore: false, startCursor: 1, startCursorMessageId: 'local' });
});

describe('canonical call history hydration', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it('uses server continuation and cursor even when the local cache claims to be complete', async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ messages: [
      { id: 'server', chat_id: 'chat', role: 'assistant', encrypted_content: 'ciphertext', created_at: 20 },
    ], has_more_before: true, start_cursor: { created_at: 20, message_id: 'server' } }) });
    const page = await fetchAuthenticatedChatMessageWindow('chat', { direction: 'latest', limit: 24 });
    expect(page).toMatchObject({ hasMoreBefore: true, startCursor: 20, startCursorMessageId: 'server' });
    expect(mocks.db.batchSaveMessages).toHaveBeenCalledWith([expect.objectContaining({ message_id: 'server', encrypted_content: 'ciphertext' })]);
    expect(mocks.fetch).toHaveBeenCalledWith(expect.stringContaining('limit=24'), { credentials: 'include' });
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it('rejects an in-flight page after the workspace epoch changes before persisting it', async () => {
    mocks.fetch.mockImplementation(async () => { mocks.epoch++; return { ok: true, json: async () => ({ messages: [] }) }; });
    await expect(fetchAuthenticatedChatMessageWindow('chat', { direction: 'latest' })).rejects.toThrow('workspace switch');
    expect(mocks.db.batchSaveMessages).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it('hydrates the newest encrypted checkpoint and refuses a cross-chat checkpoint', async () => {
    mocks.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ checkpoints: [{ id: 'checkpoint', chat_id: 'chat', encrypted_summary: 'ciphertext' }] }) });
    expect(await loadCanonicalCallCheckpoints('chat')).toHaveLength(1);
    expect(mocks.db.saveChatCompressionCheckpoint).toHaveBeenCalledWith(expect.objectContaining({ encrypted_summary: 'ciphertext' }));
    mocks.db.saveChatCompressionCheckpoint.mockClear();
    mocks.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ checkpoints: [{ id: 'wrong', chat_id: 'other' }] }) });
    await expect(loadCanonicalCallCheckpoints('chat')).rejects.toThrow('scope changed');
    expect(mocks.db.saveChatCompressionCheckpoint).not.toHaveBeenCalled();
  });
});
