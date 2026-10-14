import { describe, it, expect, beforeEach, vi } from 'vitest';
import { EmbedStore } from '../embedStore';
import { authStore } from '../../stores/authState';
import { userProfile } from '../../stores/userProfile';
import { activeChatStore } from '../../stores/activeChatStore';
import { chatDB } from '../db';
import * as parsingUtils from '../../message_parsing/utils';

describe('historical source child recovery', () => {
  const chat = '11111111-1111-1111-1111-111111111111';
  const parent = '22222222-2222-2222-2222-222222222222';
  const child = '33333333-3333-3333-3333-333333333333';
  let store: EmbedStore;
  let fetched: ReturnType<typeof vi.fn>;
  let localChild: any;
  beforeEach(() => {
    vi.restoreAllMocks();
    store = new EmbedStore();
    localChild = undefined;
    authStore.set({ isAuthenticated: true, isInitialized: true });
    userProfile.update((value) => ({ ...value, user_id: 'owner' }));
    activeChatStore.setActiveChat(chat);
    vi.spyOn(parsingUtils, 'computeSHA256').mockImplementation(async (value) => `hash-${value}`);
    vi.spyOn(chatDB, 'getChat').mockResolvedValue({ chat_id: chat, team_id: null } as any);
    vi.spyOn(store, 'getRawEntry').mockImplementation(async (ref) => ref === `embed:${parent}`
      ? { embed_id: parent, hashed_chat_id: `hash-${chat}`, hashed_user_id: 'hash-owner', status: 'finished' }
      : ref === `embed:${child}` ? localChild ?? null : null);
    vi.spyOn(store, 'storeEmbedKeys').mockResolvedValue();
    vi.spyOn(store, 'putEncrypted').mockImplementation(async (_ref, row) => { localChild = row; });
    vi.spyOn(store, 'getEmbedKeyEntries').mockResolvedValue([{ hashed_embed_id: `hash-${parent}`,
      hashed_user_id: 'hash-owner', key_type: 'master', hashed_chat_id: null, encrypted_embed_key: 'wrapped', created_at: 1 }]);
    fetched = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
      embed: { embed_id: child, parent_embed_id: parent, hashed_chat_id: `hash-${chat}`,
        hashed_user_id: 'hash-owner', status: 'finished', encrypted_content: 'ciphertext' },
      embed_keys: [{ hashed_embed_id: `hash-${parent}`, hashed_user_id: 'hash-owner',
        key_type: 'master', hashed_chat_id: null, encrypted_embed_key: 'wrapped', created_at: 1 }],
    }) });
    vi.stubGlobal('fetch', fetched);
  });
  const recover = (store: EmbedStore, ids: unknown, seen = new Set<string>()) =>
    (store as any).recoverMissingSourceChildren(parent, { content: JSON.stringify({ embed_ids: ids }) }, chat, `hash-${chat}`, seen);
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('fetches only normalized canonical missing children once per scope and inherits existing parent wrappers', async () => {
    await Promise.all([recover(store, [child, `embed:${child}`, 'legacy-invalid', parent]), recover(store, [child])]);
    expect(fetched).toHaveBeenCalledTimes(1);
    expect(fetched.mock.calls[0][0]).toContain(`/chats/${chat}/embeds/${child}`);
    expect(store.storeEmbedKeys).toHaveBeenCalledWith(expect.arrayContaining([
      expect.objectContaining({ hashed_embed_id: `hash-${parent}` }),
    ]), expect.any(Function));
    expect(store.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('rejects mismatched child source and never writes the response', async () => {
    fetched.mockResolvedValue({ ok: true, json: async () => ({ embed: {
      embed_id: child, parent_embed_id: parent, hashed_chat_id: 'other', hashed_user_id: 'hash-owner',
      status: 'finished', encrypted_content: 'ciphertext' }, embed_keys: [] }) });
    await recover(store, [child]);
    expect(store.putEncrypted).not.toHaveBeenCalled();
    expect(store.storeEmbedKeys).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('aborts writes when the selected chat changes while the request runs', async () => {
    const response = fetched.getMockImplementation()!;
    fetched.mockImplementation(async (...args) => {
      activeChatStore.setActiveChat('another-chat');
      return response(...args);
    });
    await recover(store, [child]);
    expect(store.putEncrypted).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('limits distinct children to 50 and excludes cycles and malformed IDs', async () => {
    const ids = Array.from({ length: 60 }, (_, i) => `${String(i).padStart(8, '0')}-aaaa-bbbb-cccc-dddddddddddd`);
    await recover(store, ['not-a-uuid', parent, ...ids, child]);
    expect(fetched).toHaveBeenCalledTimes(50);
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('does not fetch for Teams, missing parents, or a mismatched parent source', async () => {
    vi.mocked(chatDB.getChat).mockResolvedValue({ team_id: 'team' } as any);
    await recover(store, [child]);
    expect(fetched).not.toHaveBeenCalled();
    vi.mocked(chatDB.getChat).mockResolvedValue({ team_id: null } as any);
    vi.mocked(store.getRawEntry).mockResolvedValue({ hashed_chat_id: 'another-chat', status: 'finished' });
    await recover(store, [child]);
    expect(fetched).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('re-reads recovered children and resolves only an exact decrypted semantic ref', async () => {
    let saved = false;
    vi.spyOn(store, 'getEmbedsByHashedChatId').mockResolvedValue([
      { embed_id: parent, contentRef: `embed:${parent}`, status: 'finished', hashed_chat_id: `hash-${chat}` } as any,
    ]);
    vi.spyOn(store as any, 'collectAllRefRepairCandidatesFromCache').mockReturnValue([]);
    vi.spyOn(store as any, 'collectAllRefRepairCandidatesFromIndexedDb').mockResolvedValue([]);
    vi.mocked(store.putEncrypted).mockImplementation(async (_ref, row) => { saved = true; localChild = row; });
    vi.spyOn(store, 'get').mockImplementation(async (ref) => {
      if (ref === `embed:${parent}`) return { content: JSON.stringify({ embed_ids: [child] }) };
      if (ref === `embed:${child}` && saved) return { content: JSON.stringify({ embed_ref: 'exact-semantic-ref', app_id: 'images' }) };
      return undefined;
    });
    await expect(store.resolveByRefDeep('unrelated-semantic-ref', chat)).resolves.toBeNull();
    expect(store.resolveByRef('unrelated-semantic-ref')).toBeNull();
    await expect(store.resolveByRefDeep('exact-semantic-ref', chat)).resolves.toBe(child);
    expect(store.get).toHaveBeenCalledWith(`embed:${child}`);
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('cools down repeated 404s by source and owner without hiding local arrival', async () => {
    fetched.mockResolvedValue({ status: 404 });
    await recover(store, [child]); await recover(store, [child]);
    expect(fetched).toHaveBeenCalledTimes(1);
    userProfile.update(value => ({ ...value, user_id: 'second-owner' }));
    vi.mocked(store.getRawEntry).mockImplementation(async ref => ref === `embed:${parent}`
      ? { embed_id: parent, hashed_chat_id: `hash-${chat}`, hashed_user_id: 'hash-second-owner', status: 'finished' }
      : null);
    await recover(store, [child]);
    expect(fetched).toHaveBeenCalledTimes(2);
    vi.mocked(store.getRawEntry).mockResolvedValue({ embed_id: child, status: 'finished' });
    store.registerEmbedRef('late-local-ref', child, 'images');
    await expect(store.resolveByRefDeep('late-local-ref', chat)).resolves.toBe(child);
    expect(fetched).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('never fetches child IDs from an unreadable encrypted parent or pending decryption', async () => {
    for (const resolved of [{ embed_ids: [child] }, { content: JSON.stringify({ embed_ids: [child] }), _decryptionFailed: true },
      { content: JSON.stringify({ embed_ids: [child] }), _decryptionPending: true }]) {
      await (store as any).recoverMissingSourceChildren(parent, resolved, chat, `hash-${chat}`, new Set());
    }
    expect(fetched).not.toHaveBeenCalled();
  });

});
