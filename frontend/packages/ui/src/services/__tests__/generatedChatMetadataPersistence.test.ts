import { describe, expect, it, vi } from 'vitest';
import { persistGeneratedChatMetadata } from '../generatedChatMetadataPersistence';
import { noteChatMetadataTurn, isChatMetadataTurnCurrent } from '../lateChatMetadataGuard';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import type { Chat } from '../../types/chat';
function database(latest: Chat, beforeRead: () => void = () => {}) {
  const put = vi.fn();
  const transaction = { oncomplete: null as (() => void) | null, onerror: null, onabort: null,
    objectStore: () => ({ put, get: () => {
      const request = { result: latest, onsuccess: null as (() => void) | null };
      queueMicrotask(() => { beforeRead(); request.onsuccess!(); transaction.oncomplete!(); });
      return request;
    } }),
  };
  return { put, db: { transaction: () => transaction } as unknown as IDBDatabase, CHATS_STORE_NAME: 'chats', init: vi.fn() };
}
describe('independent optional chat metadata', () => {
  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata,chats.local-state.precedence
  it('patches encrypted metadata while retaining newer drafts, queue and message versions', async () => {
    const baseline = { chat_id: 'chat-a', encrypted_chat_key: 'key-a', title_v: 1, encrypted_chat_summary: 'summary-a' } as Chat;
    const latest = { ...baseline, encrypted_draft_md: 'edited-draft', draft_v: 4, messages_v: 8 };
    const storage = database(latest);
    const result = await persistGeneratedChatMetadata(storage, baseline, { encrypted_follow_up_request_suggestions: 'late-chips' }, () => true);
    expect(result).toMatchObject({ encrypted_draft_md: 'edited-draft', draft_v: 4, messages_v: 8, encrypted_follow_up_request_suggestions: 'late-chips' });
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata,chats.local-state.precedence
  it('lets manual title and summary edits win inside the metadata transaction', async () => {
    const baseline = { chat_id: 'chat-a', encrypted_chat_key: 'key-a', title_v: 1, encrypted_chat_summary: 'summary-a' } as Chat;
    const storage = database({ ...baseline, title_v: 2, encrypted_title: 'manual-title', encrypted_chat_summary: 'manual-summary' });
    const result = await persistGeneratedChatMetadata(storage, baseline, { title_v: 2, encrypted_title: 'old-generated-title', encrypted_chat_summary: 'old-generated-summary', encrypted_follow_up_request_suggestions: 'late-chips' }, () => true);
    expect(result).toMatchObject({ encrypted_title: 'manual-title', encrypted_chat_summary: 'manual-summary', encrypted_follow_up_request_suggestions: 'late-chips' });
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata,chats.local-state.precedence
  it('keeps a version-bound late header but removes old chips when the turn changes before the transaction reads', async () => {
    invalidateWorkspaceCaches();
    noteChatMetadataTurn('chat-a', 'old-task', 'old-user');
    const baseline = { chat_id: 'chat-a', encrypted_chat_key: 'key-a', title_v: 1 } as Chat;
    const storage = database({ ...baseline, encrypted_draft_md: 'new draft' }, () => noteChatMetadataTurn('chat-a', '', 'next-user'));
    const result = await persistGeneratedChatMetadata(storage, baseline, {
      title_v: 2, encrypted_title: 'version-bound-title', encrypted_follow_up_request_suggestions: 'old-chips',
    }, () => true, (patch) => isChatMetadataTurnCurrent('chat-a', 'old-task', 'old-user')
      ? patch : { encrypted_title: patch.encrypted_title, title_v: patch.title_v });
    expect(result).toMatchObject({ encrypted_title: 'version-bound-title', encrypted_draft_md: 'new draft' });
    expect(result?.encrypted_follow_up_request_suggestions).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata
  it('rejects a response after account/key scope or the pending user turn changes', async () => {
    invalidateWorkspaceCaches();
    noteChatMetadataTurn('chat-a', 'completed-task', 'user-a');
    expect(isChatMetadataTurnCurrent('chat-a', 'completed-task', 'user-a')).toBe(true);
    const baseline = { chat_id: 'chat-a', encrypted_chat_key: 'key-a', title_v: 1 } as Chat;
    const storage = database(baseline, () => noteChatMetadataTurn('chat-a', '', 'user-b'));
    const result = await persistGeneratedChatMetadata(storage, baseline, { encrypted_follow_up_request_suggestions: 'old-chips' }, () => isChatMetadataTurnCurrent('chat-a', 'completed-task', 'user-a'));
    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
    expect(isChatMetadataTurnCurrent('chat-a', 'completed-task', 'user-a')).toBe(false);
  });
});
