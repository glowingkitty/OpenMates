// contract-test-file: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
import { beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({ decrypt: vi.fn(), encrypt: vi.fn(), fetch: vi.fn() }));
vi.mock('../stores/authState', async () => {
  const { writable } = await import('svelte/store');
  return { authStore: writable({ isAuthenticated: true }) };
});
vi.mock('../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  const userProfile = writable<{ user_id: string; encrypted_settings: string | null }>({ user_id: 'owner', encrypted_settings: null });
  return { userProfile, updateProfile: (value: Partial<{ user_id: string; encrypted_settings: string | null }>) => userProfile.update(current => ({ ...current, ...value })) };
});
import { authStore as auth } from '../stores/authState';
import { userProfile as profile } from '../stores/userProfile';
vi.mock('../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.example.test${path}` }));
vi.mock('./encryption/MetadataEncryptor', () => ({ decryptWithMasterKey: mocks.decrypt, encryptWithMasterKey: mocks.encrypt }));
import { invalidateWorkspaceCaches } from './workspaceCacheLifecycle';
import { loadMessageBookmarks, getMessageBookmarkIds, toggleMessageBookmark, clearTransientMessageBookmarks } from './messageBookmarks';

const plaintext = new Map<string, string>();
beforeEach(() => {
  invalidateWorkspaceCaches(); localStorage.clear(); plaintext.clear();
  auth.update(value => ({ ...value, isAuthenticated: true })); profile.update(value => ({ ...value, user_id: 'owner', encrypted_settings: null }));
  mocks.decrypt.mockReset().mockImplementation(async (cipher: string) => plaintext.get(cipher));
  mocks.encrypt.mockReset().mockImplementation(async (value: string) => {
    const cipher = `opaque-${plaintext.size}`; plaintext.set(cipher, value); return cipher;
  });
  mocks.fetch.mockReset().mockResolvedValue({ ok: true }); vi.stubGlobal('fetch', mocks.fetch);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('merges private encrypted settings and restores exact question/reply bookmarks after cache reload', async () => {
  plaintext.set('initial', JSON.stringify({ unrelated: { theme: 'dark' } }));
  profile.update(value => ({ ...value, encrypted_settings: 'initial' }));
  await toggleMessageBookmark('chat', 'question', 'account');
  await toggleMessageBookmark('chat', 'reply', 'account');
  const body = JSON.parse(mocks.fetch.mock.calls[1][1].body);
  expect(body).toEqual({ encrypted_settings: expect.stringMatching(/^opaque-/) });
  expect(JSON.stringify(body)).not.toContain('question');
  expect(JSON.parse(plaintext.get(body.encrypted_settings)!)).toEqual({
    unrelated: { theme: 'dark' }, message_bookmarks: { version: 1, chats: { chat: ['question', 'reply'] } },
  });
  invalidateWorkspaceCaches();
  await loadMessageBookmarks('chat', 'account');
  expect([...getMessageBookmarkIds('chat', 'account')]).toEqual(['question', 'reply']);
  await toggleMessageBookmark('chat', 'question', 'account');
  expect([...getMessageBookmarkIds('chat', 'account')]).toEqual(['reply']);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('retains the saved state after failure and serializes a successful retry', async () => {
  await toggleMessageBookmark('chat', 'question', 'account');
  const saved = get(profile).encrypted_settings;
  mocks.fetch.mockResolvedValueOnce({ ok: false });
  await expect(toggleMessageBookmark('chat', 'question', 'account')).rejects.toThrow('save');
  expect(get(profile).encrypted_settings).toBe(saved);
  expect(getMessageBookmarkIds('chat', 'account').has('question')).toBe(true);
  await toggleMessageBookmark('chat', 'question', 'account');
  expect(getMessageBookmarkIds('chat', 'account').size).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('does not post or publish an old account operation after encryption crosses an identity boundary', async () => {
  let release!: (value: string) => void;
  mocks.encrypt.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const operation = toggleMessageBookmark('chat', 'private-id', 'account');
  await vi.waitFor(() => expect(release).toBeTypeOf('function'));
  profile.update(value => ({ ...value, user_id: 'other-owner', encrypted_settings: null }));
  invalidateWorkspaceCaches(); release('opaque-stale');
  await expect(operation).rejects.toThrow('scope');
  expect(mocks.fetch).not.toHaveBeenCalled();
  expect(getMessageBookmarkIds('chat', 'account').size).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('does not publish a delayed response into the next account', async () => {
  let release!: (value: { ok: boolean }) => void;
  mocks.fetch.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const operation = toggleMessageBookmark('chat', 'private-id', 'account');
  await vi.waitFor(() => expect(release).toBeTypeOf('function'));
  profile.update(value => ({ ...value, user_id: 'other-owner', encrypted_settings: null }));
  invalidateWorkspaceCaches(); release({ ok: true });
  await expect(operation).rejects.toThrow('scope');
  expect(get(profile).encrypted_settings).toBeNull();
  expect(getMessageBookmarkIds('chat', 'account').size).toBe(0);
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('keeps device retention separate from transient incognito state', async () => {
  auth.update(value => ({ ...value, isAuthenticated: false }));
  await toggleMessageBookmark('public-chat', 'question', 'device');
  await toggleMessageBookmark('incognito-chat', 'private-id', 'transient');
  expect(localStorage.getItem('openmates:message-bookmarks:v1:public-chat')).toBe('["question"]');
  expect(localStorage.getItem('openmates:message-bookmarks:v1:incognito-chat')).toBeNull();
  clearTransientMessageBookmarks('incognito-chat');
  expect(getMessageBookmarkIds('incognito-chat', 'transient').size).toBe(0);
  invalidateWorkspaceCaches();
  await loadMessageBookmarks('public-chat', 'device');
  expect(getMessageBookmarkIds('public-chat', 'device').has('question')).toBe(true);
  expect(mocks.fetch).not.toHaveBeenCalled();
});

// contract-test: supporting surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.access-and-lifecycle
it('fails closed on unreadable settings and preserves an unrelated concurrent preference update', async () => {
  profile.update(value => ({ ...value, encrypted_settings: 'unreadable' }));
  await expect(toggleMessageBookmark('chat', 'question', 'account')).rejects.toThrow('unavailable');
  expect(mocks.fetch).not.toHaveBeenCalled();
  plaintext.set('valid', JSON.stringify({ other: true }));
  profile.update(value => ({ ...value, encrypted_settings: 'valid' }));
  mocks.encrypt.mockImplementation(async () => {
    profile.update(value => ({ ...value, encrypted_settings: 'new-preferences' }));
    return 'stale';
  });
  await expect(toggleMessageBookmark('chat', 'question', 'account')).rejects.toThrow('scope');
  expect(mocks.fetch).not.toHaveBeenCalled();
  expect(get(profile).encrypted_settings).toBe('new-preferences');
});
