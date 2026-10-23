import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EmbedStore } from '../embedStore';
import { authStore } from '../../stores/authState';
import { userProfile } from '../../stores/userProfile';
import { activeChatStore } from '../../stores/activeChatStore';
import { chatDB } from '../db';
import * as parsingUtils from '../../message_parsing/utils';

describe('Personal ref discovery with an absent result group', () => {
  const chat = '11111111-1111-1111-1111-111111111111';
  const parent = '22222222-2222-2222-2222-222222222222';
  const child = '33333333-3333-3333-3333-333333333333';
  const other = '44444444-4444-4444-4444-444444444444';
  let store: EmbedStore, rows: Map<string, any>, fetchRead: ReturnType<typeof vi.fn>;
  const row = (id: string, parentId?: string) => ({ embed_id: id, parent_embed_id: parentId,
    hashed_chat_id: `hash-${chat}`, hashed_user_id: 'hash-owner', encryption_mode: 'client',
    encrypted_content: 'ciphertext', encrypted_type: 'encrypted-type', status: 'finished' });
  const wrapper = { hashed_embed_id: `hash-${parent}`, hashed_user_id: 'hash-owner',
    key_type: 'master', hashed_chat_id: null, encrypted_embed_key: 'wrapped', created_at: 1 };
  const page = (embeds = [row(parent), row(child, parent), row(other, parent)], extra = {}) =>
    ({ chat_id: chat, embeds, embed_keys: [wrapper], has_more_before: false, ...extra });
  beforeEach(() => {
    vi.restoreAllMocks(); rows = new Map(); store = new EmbedStore(); store.clearEmbedRefIndex();
    authStore.set({ isAuthenticated: true, isInitialized: true });
    userProfile.update(p => ({ ...p, user_id: 'owner', account_id: 'personal' }));
    activeChatStore.setWithoutHashUpdate(chat);
    vi.spyOn(parsingUtils, 'computeSHA256').mockImplementation(async value => `hash-${value}`);
    vi.spyOn(chatDB, 'getChat').mockResolvedValue({ chat_id: chat, team_id: null } as any);
    vi.spyOn(store, 'getEmbedsByHashedChatId').mockImplementation(async () => [...rows.values()] as any);
    vi.spyOn(store as any, 'collectAllRefRepairCandidatesFromCache').mockReturnValue([]);
    vi.spyOn(store as any, 'collectAllRefRepairCandidatesFromIndexedDb').mockResolvedValue([]);
    vi.spyOn(store, 'getRawEntry').mockImplementation(async ref => rows.get(ref) ?? null);
    vi.spyOn(store, 'getEmbedKeyEntries').mockResolvedValue([wrapper] as any);
    vi.spyOn(store, 'get').mockImplementation(async ref => rows.has(ref) ? { content: JSON.stringify(
      ref === `embed:${parent}` ? { embed_ids: [child, other] }
        : { embed_ref: ref === `embed:${child}` ? 'barcamp-M9b' : 'second-event', app_id: 'events' },
    ) } : undefined);
    vi.spyOn(store, 'storeEmbedKeys').mockImplementation(async (_keys, guard) => { guard?.(); });
    vi.spyOn(store, 'putEncrypted').mockImplementation(async (ref, value, _type, _a, _b, options) => {
      options?.writeGuard?.(); rows.set(ref, value);
    });
    fetchRead = vi.fn().mockResolvedValue({ ok: true, json: async () => page() });
    vi.stubGlobal('fetch', fetchRead);
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); activeChatStore.setWithoutHashUpdate(null); });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('finds an exact event ref across encrypted windows when its root and child are absent', async () => {
    fetchRead.mockResolvedValueOnce({ ok: true, json: async () => page([], {
      has_more_before: true, start_cursor: { created_at: 10, id: 'cursor-one' },
    }) });
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBe(child);
    expect(fetchRead).toHaveBeenCalledTimes(2);
    expect(fetchRead.mock.calls[1][0]).toContain('before_created_at=10&before_id=cursor-one');
    expect(store.resolveAppIdByRef('barcamp-M9b')).toBe('events');
    expect(store.putEncrypted).toHaveBeenCalledWith(`embed:${child}`, expect.objectContaining({
      encrypted_content: 'ciphertext', parent_embed_id: parent,
    }), 'app-skill-use', undefined, undefined, expect.objectContaining({ skipMetadataExtraction: true }));
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it('shares one window discovery across different unresolved refs and uses recovered rows on retry', async () => {
    await expect(Promise.all([store.resolveByRefDeep('barcamp-M9b', chat),
      store.resolveByRefDeep('second-event', chat)])).resolves.toEqual([child, other]);
    expect(fetchRead).toHaveBeenCalledTimes(1);
    await expect(store.resolveByRefDeep('unrelated-ref', chat)).resolves.toBeNull();
    expect(fetchRead).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('retries local ciphertext after discovery supplies its missing wrappers', async () => {
    rows.set(`embed:${parent}`, row(parent)); rows.set(`embed:${child}`, row(child, parent));
    const read = vi.mocked(store.get).getMockImplementation()!;
    let keysReady = false;
    vi.mocked(store.get).mockImplementation(async ref => keysReady ? read(ref) : undefined);
    vi.mocked(store.storeEmbedKeys).mockImplementation(async (_keys, guard) => { guard?.(); keysReady = true; });
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBe(child);
    expect(fetchRead).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.rendering.assistant-document-convergence
  it('verifies recovered results even when a later window fails', async () => {
    fetchRead.mockResolvedValueOnce({ ok: true, json: async () => page(undefined, {
      has_more_before: true, start_cursor: { created_at: 10, id: 'cursor-one' },
    }) }).mockResolvedValueOnce({ ok: false, status: 503 });
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBe(child);
    expect(fetchRead).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement,chats.persistence.client-encrypted
  it('rejects a navigation or owner change before persisting window ciphertext or keys', async () => {
    fetchRead.mockImplementation(async () => {
      activeChatStore.setWithoutHashUpdate(other);
      return { ok: true, json: async () => page() };
    });
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBeNull();
    expect(store.storeEmbedKeys).not.toHaveBeenCalled();
    expect(store.putEncrypted).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.authoritative-enforcement,chats.persistence.client-encrypted
  it('rejects another chat window and filters foreign rows and key wrappers', async () => {
    fetchRead.mockResolvedValueOnce({ ok: true, json: async () => page([], { chat_id: other }) });
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBeNull();
    expect(store.putEncrypted).not.toHaveBeenCalled();
    store = new EmbedStore();
    const writes = vi.spyOn(store, 'putEncrypted').mockResolvedValue();
    const keys = vi.spyOn(store, 'storeEmbedKeys').mockResolvedValue();
    fetchRead.mockResolvedValue({ ok: true, json: async () => page([
      { ...row(child, parent), hashed_user_id: 'foreign' }, row(parent),
    ], { embed_keys: [{ ...wrapper, hashed_user_id: 'foreign' }, { ...wrapper, hashed_team_id: 'team' }] }) });
    await (store as any).recoverMissingRefCandidates(chat, `hash-${chat}`);
    expect(writes).toHaveBeenCalledTimes(1);
    expect(writes.mock.calls[0][0]).toBe(`embed:${parent}`);
    expect(keys).toHaveBeenCalledWith([], expect.any(Function));
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,auth.session.authoritative-enforcement
  it('bounds discovery to ten advancing windows and excludes Teams and shared chats', async () => {
    fetchRead.mockImplementation(async () => ({ ok: true, json: async () => page([], {
      has_more_before: true, start_cursor: { created_at: 10, id: `cursor-${fetchRead.mock.calls.length}` },
    }) }));
    await expect(store.resolveByRefDeep('barcamp-M9b', chat)).resolves.toBeNull();
    expect(fetchRead).toHaveBeenCalledTimes(10);
    for (const metadata of [{ team_id: 'team' }, { is_shared_by_others: true }]) {
      vi.mocked(chatDB.getChat).mockResolvedValue({ chat_id: chat, ...metadata } as any);
      await (new EmbedStore() as any).recoverMissingRefCandidates(chat, `hash-${chat}`);
    }
    expect(fetchRead).toHaveBeenCalledTimes(10);
  });
});
