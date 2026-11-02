import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({ decrypt: vi.fn(), encrypt: vi.fn(), fetch: vi.fn() }));
const { auth, profile } = await vi.hoisted(async () => {
  const store = await import('svelte/store');
  return {
    auth: store.writable({ isAuthenticated: true }),
    profile: store.writable<{ encrypted_settings: string | null }>({ encrypted_settings: null }),
  };
});
vi.mock('../encryption/MetadataEncryptor', () => ({ decryptWithMasterKey: mocks.decrypt, encryptWithMasterKey: mocks.encrypt }));
vi.mock('../../stores/authStore', () => ({ authStore: auth }));
vi.mock('../../stores/userProfile', () => ({
  userProfile: profile,
  updateProfile: (patch: { encrypted_settings: string | null }) => profile.update(p => ({ ...p, ...patch })),
}));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../demo_chats', () => ({ isDemoChat: () => false, isLegalChat: () => false, isPublicChat: () => false }));

import { chatMenuUsageScore, chatMenuUsageStore, hydrateChatMenuUsage, rankChatMenuItems, recordChatMenuUsage } from '../chatMenuUsage';
import { buildChatMenuItems } from '../../components/chats/chatMenuItems';

const DAY = 86_400_000;
const NOW = 1_800_000_000_000;
const items = [
  { usageId: 'addToProject' }, { usageId: 'download' }, { usageId: 'copy' },
  { usageId: 'share' }, { usageId: 'delete', pinned: 'end' as const },
];

describe('chat menu usage ranking', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('keeps the default order when nothing was used', () => {
    expect(rankChatMenuItems(items, {}, NOW).map(i => i.usageId)).toEqual(['addToProject', 'download', 'copy', 'share', 'delete']);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('moves frequently used actions first and keeps delete at the end', () => {
    const ranked = rankChatMenuItems(items, {
      share: { count: 6, lastUsedAt: NOW },
      download: { count: 2, lastUsedAt: NOW },
      delete: { count: 50, lastUsedAt: NOW },
    }, NOW);
    expect(ranked.map(i => i.usageId)).toEqual(['share', 'download', 'addToProject', 'copy', 'delete']);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('decays old usage so recent habits win', () => {
    expect(chatMenuUsageScore({ count: 8, lastUsedAt: NOW - 28 * DAY }, NOW)).toBeCloseTo(2);
    const ranked = rankChatMenuItems(items, {
      copy: { count: 8, lastUsedAt: NOW - 60 * DAY },
      download: { count: 3, lastUsedAt: NOW },
    }, NOW);
    expect(ranked[0].usageId).toBe('download');
  });
});

describe('chat menu usage persistence', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', mocks.fetch);
    mocks.fetch.mockResolvedValue({ ok: true });
    profile.set({ encrypted_settings: 'cipher-1' });
    mocks.decrypt.mockResolvedValue(JSON.stringify({ topic_preferences: { version: 1 }, chat_menu_usage: { version: 1, actions: { copy: { count: 3, lastUsedAt: NOW } } } }));
    mocks.encrypt.mockImplementation(async (plain: string) => `enc:${plain}`);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('hydrates from encrypted settings and saves merged usage without dropping other settings', async () => {
    await hydrateChatMenuUsage();
    expect(get(chatMenuUsageStore).copy.count).toBe(3);

    recordChatMenuUsage('download', NOW);
    await vi.advanceTimersByTimeAsync(5000);

    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = mocks.fetch.mock.calls[0];
    expect(url).toBe('https://api.test/v1/settings/encrypted-account');
    const ciphertext = JSON.parse(init.body).encrypted_settings as string;
    expect(ciphertext.startsWith('enc:')).toBe(true);
    const saved = JSON.parse(ciphertext.slice(4));
    expect(saved.topic_preferences).toEqual({ version: 1 });
    expect(saved.chat_menu_usage.actions.download.count).toBe(1);
    expect(saved.chat_menu_usage.actions.copy.count).toBe(3);
    expect(get(profile).encrypted_settings).toBe(ciphertext);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('ignores invalid action ids', () => {
    const before = get(chatMenuUsageStore);
    recordChatMenuUsage('bad id!');
    expect(get(chatMenuUsageStore)).toEqual(before);
  });
});

describe('chat menu catalog', () => {
  const chat = { chat_id: 'c1', unread_count: 0, pinned: false } as never;

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('uses existing icons for project actions', () => {
    const list = buildChatMenuItems({ chat, isAuthenticated: true, isAdmin: false, shareAllowed: true, isUnread: false, debugActive: false });
    const icons = Object.fromEntries(list.map(i => [i.action, i.icon]));
    expect(icons.addToProject).toBe('icon_project');
    expect(icons.createProject).toBe('icon_create');
    expect(icons.moveToProject).toBe('icon_project');
    expect(list.map(i => i.action)).toEqual(expect.arrayContaining(['download', 'copy', 'share', 'hide', 'pin', 'markUnread', 'delete']));
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.menu.parity-ranked
  it('honours hidden actions for the fullscreen More menu', () => {
    const list = buildChatMenuItems({ chat, isAuthenticated: true, isAdmin: true, shareAllowed: true, isUnread: false, debugActive: false, hide: { select: true, share: true } });
    expect(list.some(i => i.action === 'share' || i.action === 'enterSelectMode')).toBe(false);
    expect(list.at(-1)?.action).toBe('toggleDebug');
  });
});
