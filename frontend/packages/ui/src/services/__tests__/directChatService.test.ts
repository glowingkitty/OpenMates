import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const testState = vi.hoisted(() => {
  function store<T>(initial: T) {
    let value = initial;
    const listeners = new Set<(next: T) => void>();
    return {
      set(next: T) { value = next; listeners.forEach(listener => listener(value)); },
      subscribe(listener: (next: T) => void) { listeners.add(listener); listener(value); return () => listeners.delete(listener); },
    };
  }
  return {
  auth: store({ isAuthenticated: true }),
  profile: store({ user_id: 'alice' }),
  epoch: 1,
  probe: new Uint8Array(32) as Uint8Array<ArrayBufferLike>,
  clear: null as null | (() => void),
  clearers: new Set<() => void>(),
  generate: vi.fn(),
  seal: vi.fn(),
  open: vi.fn(),
  encryptPrivate: vi.fn(),
  decryptPrivate: vi.fn(),
  getAllChats: vi.fn(),
  addChat: vi.fn(),
  upsertChat: vi.fn(),
  injectKey: vi.fn(),
  keyCache: null as null | { accountId: string; apiEndpoint: string; key: {
    version: 1; algorithm: 'x25519-xsalsa20poly1305'; key_id: string; public_key: string; encrypted_private_key: string;
  } },
  cacheRead: vi.fn(),
  cacheWrite: vi.fn(),
  apiOrigin: '',
  context: { teamId: 'team-1', epoch: 1, team: { status: 'active' } },
}; });

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `${testState.apiOrigin}${path}` }));
vi.mock('../userDB', () => ({ userDB: {
  getAccountChatKeyCache: (...args: unknown[]) => testState.cacheRead(...args),
  setAccountChatKeyCache: (...args: unknown[]) => testState.cacheWrite(...args),
} }));
vi.mock('../../message_parsing/utils', () => ({ computeSHA256: async (value: string) => `hash-${value}` }));
vi.mock('../../stores/userProfile', () => ({ userProfile: testState.profile }));
vi.mock('../../stores/authStore', () => ({ authStore: testState.auth }));
vi.mock('../../stores/teamStore', () => ({
  getActiveTeamContextSnapshot: () => testState.context,
  isActiveTeamContext: (id: string, epoch: number) => id === testState.context.teamId && epoch === testState.context.epoch,
}));
vi.mock('../workspaceCacheLifecycle', () => ({
  getWorkspaceCacheEpoch: () => testState.epoch,
  registerWorkspaceCacheClear: (clear: () => void) => {
    testState.clearers.add(clear);
    testState.clear = () => { for (const clearCache of testState.clearers) clearCache(); };
  },
}));
vi.mock('../cryptoService', () => ({ getKeyFromStorage: async () => ({}) }));
vi.mock('../encryption/MetadataEncryptor', () => ({
  encryptWithMasterKey: (...args: unknown[]) => testState.encryptPrivate(...args),
  decryptWithMasterKey: (...args: unknown[]) => testState.decryptPrivate(...args),
}));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: {
  injectKey: (...args: unknown[]) => testState.injectKey(...args), removeKey: vi.fn(),
} }));
vi.mock('../db', () => ({ chatDB: {
  getAllChats: (...args: unknown[]) => testState.getAllChats(...args),
  addChat: (...args: unknown[]) => testState.addChat(...args),
} }));
vi.mock('../chatListCache', () => ({ chatListCache: { upsertChat: (...args: unknown[]) => testState.upsertChat(...args) } }));
vi.mock('../drafts/draftConstants', () => ({ LOCAL_CHAT_LIST_CHANGED_EVENT: 'local-chat-list-changed' }));
vi.mock('../encryption/MessageEncryptor', () => ({ encryptWithChatKey: async () => 'encrypted-title' }));
vi.mock('@repo/pairing-crypto/direct-chat', () => ({
  directChatKeyId: async () => 'key-id',
  generateIdentity: (...args: unknown[]) => testState.generate(...args),
  sealDirectChatKey: (...args: unknown[]) => testState.seal(...args),
  openDirectChatKey: (...args: unknown[]) => testState.open(...args),
}));

import { createDirectChat, ensureDirectChatIdentity, DirectChatError } from '../directChatService';

const savedKey = {
  version: 1, algorithm: 'x25519-xsalsa20poly1305', key_id: 'key-id',
  public_key: 'public', encrypted_private_key: 'ZW5jcnlwdGVk',
} as const;

describe('direct Team chat identity and recipient setup', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', webcrypto);
    testState.epoch += 1;
    testState.context.epoch += 1;
    testState.clear?.();
    testState.auth.set({ isAuthenticated: true });
    testState.profile.set({ user_id: 'alice' });
    testState.generate.mockReset().mockResolvedValue({ publicKey: 'public', privateKey: 'private', keyId: 'key-id' });
    testState.seal.mockReset().mockImplementation(async (raw: Uint8Array) => { testState.probe = raw; return 'OMDM1.envelope'; });
    testState.open.mockReset().mockImplementation(async () => testState.probe);
    testState.encryptPrivate.mockReset().mockResolvedValue('ZW5jcnlwdGVk');
    testState.decryptPrivate.mockReset().mockResolvedValue('private');
    testState.getAllChats.mockReset().mockResolvedValue([]);
    testState.addChat.mockReset().mockResolvedValue(undefined);
    testState.upsertChat.mockReset();
    testState.injectKey.mockReset().mockReturnValue(true);
    testState.context.teamId = 'team-1';
    testState.keyCache = null;
    testState.apiOrigin = '';
    testState.cacheRead.mockReset().mockImplementation(async (guard: () => void) => { guard(); return testState.keyCache; });
    testState.cacheWrite.mockReset().mockImplementation(async (record: typeof testState.keyCache, guard: () => void) => { guard(); testState.keyCache = record; });
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('uses an existing immutable account key and coalesces concurrent unlocks', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ key: savedKey }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const [first, second] = await Promise.all([ensureDirectChatIdentity(), ensureDirectChatIdentity()]);
    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(testState.generate).not.toHaveBeenCalled();
    expect(testState.decryptPrivate).toHaveBeenCalledWith('ZW5jcnlwdGVk');
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('publishes a new identity only when the account has none', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: { ...savedKey, encrypted_private_key: 'ZW5jcnlwdGVk' } }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await ensureDirectChatIdentity();
    expect(testState.generate).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1].method).toBe('PUT');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).encrypted_private_key).toBe('ZW5jcnlwdGVk');
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('does not register an old identity if the account changes while its backup is encrypted', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: null }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    testState.encryptPrivate.mockImplementationOnce(async () => {
      testState.profile.set({ user_id: 'bob' });
      testState.epoch += 1;
      return 'ZW5jcnlwdGVk';
    });
    await expect(ensureDirectChatIdentity()).rejects.toMatchObject({ code: 'cancelled' });
    expect(fetchMock.mock.calls.map(call => call[1]?.method ?? 'GET')).toEqual(['GET']);
    expect(testState.generate).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('uses the winning identity after a concurrent device enrollment', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'already enrolled' }), { status: 409 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: savedKey }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(ensureDirectChatIdentity()).resolves.toMatchObject({ keyId: 'key-id' });
    expect(fetchMock.mock.calls.map(call => call[1]?.method ?? 'GET')).toEqual(['GET', 'PUT', 'GET']);
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('recovers a validated identity from the opaque backup after a cold module reset while offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ key: savedKey }), { status: 200 })));
    await ensureDirectChatIdentity();
    expect(testState.keyCache).toEqual({ accountId: 'alice', apiEndpoint: '/v1/account/chat-encryption-key', key: savedKey });
    testState.epoch += 1;
    testState.clear?.();
    vi.resetModules();
    const { ensureDirectChatIdentity: coldEnsure } = await import('../directChatService');
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);
    await expect(coldEnsure()).resolves.toMatchObject({ keyId: 'key-id', publicKey: 'public' });
    expect(testState.decryptPrivate).toHaveBeenCalledWith('ZW5jcnlwdGVk');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('rejects a cached backup when the master key cannot unlock it', async () => {
    testState.keyCache = { accountId: 'alice', apiEndpoint: '/v1/account/chat-encryption-key', key: savedKey };
    testState.decryptPrivate.mockResolvedValueOnce(null);
    vi.stubGlobal('fetch', vi.fn());
    await expect(ensureDirectChatIdentity()).rejects.toMatchObject({ code: 'unavailable' });
    expect(fetch).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it.each([
    { accountId: 'bob', apiEndpoint: '/v1/account/chat-encryption-key' },
    { accountId: 'alice', apiEndpoint: 'https://other.example/v1/account/chat-encryption-key' },
  ])('ignores a backup bound to a different account or API origin: %j', async binding => {
    testState.keyCache = { ...binding, key: savedKey };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ key: savedKey }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await ensureDirectChatIdentity();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(testState.keyCache).toEqual({ accountId: 'alice', apiEndpoint: '/v1/account/chat-encryption-key', key: savedKey });
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('keeps online enrollment usable when encrypted cache storage is full', async () => {
    testState.cacheWrite.mockRejectedValueOnce(new DOMException('Quota exceeded', 'QuotaExceededError'));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ key: savedKey }), { status: 200 })));
    await expect(ensureDirectChatIdentity()).resolves.toMatchObject({ keyId: 'key-id' });
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.account-key-exchange
  it('does not retain identity when logout advances the epoch during cache write', async () => {
    testState.cacheWrite.mockImplementationOnce(async (_record: unknown, guard: () => void) => {
      testState.auth.set({ isAuthenticated: false });
      testState.epoch += 1;
      testState.clear?.();
      guard();
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ key: savedKey }), { status: 200 })));
    await expect(ensureDirectChatIdentity()).rejects.toMatchObject({ code: 'cancelled' });
    expect(testState.keyCache).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.member-entry-and-notifications
  it('stops before creation when the recipient has not enrolled', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: savedKey }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'CHAT_ENCRYPTION_KEY_PENDING' }), { status: 404 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(createDirectChat('team-1', 'hash-bob')).rejects.toMatchObject({ code: 'pending' } satisfies Partial<DirectChatError>);
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      '/v1/account/chat-encryption-key',
      '/v1/teams/team-1/members/hash-bob/chat-encryption-key',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.participant-isolation,teams.direct-chat.member-entry-and-notifications
  it('creates exactly two recipient-bound envelopes and stores the caller projection', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: savedKey }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ key_id: 'bob-key', public_key: 'bob-public' }), { status: 200 }))
      .mockImplementationOnce(async (_path: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ chat: {
          chat_id: body.chat_id, team_id: 'team-1', chat_visibility: 'direct',
          participant_user_hashes: ['hash-alice', 'hash-bob'], encrypted_chat_key: 'OMDM1.envelope',
          encrypted_title: body.encrypted_title, messages_v: 0, title_v: 0,
        } }), { status: 200 });
      });
    vi.stubGlobal('fetch', fetchMock);
    const chat = await createDirectChat('team-1', 'hash-bob');
    expect(chat.chat_visibility).toBe('direct');
    expect(chat.participant_user_hashes).toEqual(['hash-alice', 'hash-bob']);
    const submitted = JSON.parse(fetchMock.mock.calls[2][1].body);
    expect(Object.keys(submitted.participant_key_envelopes).sort()).toEqual(['hash-alice', 'hash-bob']);
    expect(submitted.participant_key_envelopes['hash-alice'].encrypted_chat_key).toMatch(/^OMDM1\./);
    expect(testState.injectKey).toHaveBeenCalledWith(chat.chat_id, expect.any(Uint8Array), 'created');
    expect(testState.addChat).toHaveBeenCalledWith(expect.objectContaining({ chat_id: chat.chat_id }), undefined, {
      isFromSync: true, writeGuard: expect.any(Function),
    });
    expect(testState.upsertChat).toHaveBeenCalledWith(chat);
  });

  // contract-test: supporting surface=gui.web assertions=teams.direct-chat.participant-isolation
  it('does not publish a chat after its Team changes while IndexedDB saves it', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ key: savedKey }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ key_id: 'bob-key', public_key: 'bob-public' }), { status: 200 }))
      .mockImplementationOnce(async (_path: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ chat: {
          chat_id: body.chat_id, team_id: 'team-1', chat_visibility: 'direct',
          participant_user_hashes: ['hash-alice', 'hash-bob'], encrypted_chat_key: 'OMDM1.envelope',
          encrypted_title: body.encrypted_title, messages_v: 0, title_v: 0,
        } }), { status: 200 });
      });
    vi.stubGlobal('fetch', fetchMock);
    let commitGuard: (() => void) | undefined;
    testState.addChat.mockImplementationOnce(async (_chat: unknown, _transaction: unknown, options: { writeGuard: () => void }) => {
      commitGuard = options.writeGuard;
      options.writeGuard();
      testState.context.epoch += 1;
    });
    await expect(createDirectChat('team-1', 'hash-bob')).rejects.toMatchObject({ code: 'cancelled' });
    expect(commitGuard).toBeTypeOf('function');
    expect(() => commitGuard!()).toThrow(/Team changed/);
    expect(testState.upsertChat).not.toHaveBeenCalled();
  });
});
