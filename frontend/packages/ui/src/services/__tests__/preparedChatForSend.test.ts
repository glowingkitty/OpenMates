import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';
import FreshShellMountHarness from './FreshShellMountHarness.svelte';

const mocks = vi.hoisted(() => ({
  authenticated: true,
  accountId: 'account-a',
  scope: 'account-a:personal',
  teamId: null as string | null,
  teamEpoch: 1,
  incognito: false,
  draftChatId: null as string | null,
  getRawChat: vi.fn(async (_id: string): Promise<{ team_id: string | null; encrypted_chat_key?: string } | null> => null),
  getKey: vi.fn(async (_id: string) => new Uint8Array([1])),
  createKey: vi.fn((_id: string) => new Uint8Array([1])),
  warmAccounts: vi.fn(async () => null),
  store: <T>(read: () => T) => ({ subscribe(callback: (value: T) => void) {
    callback(read());
    return () => undefined;
  } }),
}));
vi.mock('../../stores/authStore', () => ({ authStore: mocks.store(() => ({ isAuthenticated: mocks.authenticated })) }));
vi.mock('../../stores/userProfile', () => ({ userProfile: mocks.store(() => ({ user_id: mocks.accountId })) }));
vi.mock('../../stores/teamStore', () => ({ getActiveTeamContextSnapshot: () => ({ teamId: mocks.teamId, epoch: mocks.teamEpoch }) }));
vi.mock('../../stores/incognitoModeStore', () => ({ incognitoMode: { get: () => mocks.incognito } }));
vi.mock('../drafts/draftState', () => ({ draftEditorUIState: {
  subscribe(callback: (value: { currentChatId: string | null }) => void) {
    callback({ currentChatId: mocks.draftChatId });
    return () => undefined;
  },
  update(callback: (value: { currentChatId: string | null }) => { currentChatId: string | null }) {
    mocks.draftChatId = callback({ currentChatId: mocks.draftChatId }).currentChatId;
  },
} }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: {
  getKey: mocks.getKey, createKeyForNewChat: mocks.createKey,
} }));
vi.mock('../db', () => ({ chatDB: { getRawChat: mocks.getRawChat } }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.scope }));
vi.mock('../../demo_chats/convertToChat', () => ({ isPublicChat: () => false }));
vi.mock('../chatSyncService', () => ({ chatSyncService: { beginEmptyConnectedAccountLookup: mocks.warmAccounts } }));

import { getPreparedChatForSend, prepareChatForSend } from '../preparedChatForSend';

describe('new personal chat preparation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authenticated = true;
    mocks.accountId = 'account-a';
    mocks.scope = 'account-a:personal';
    mocks.teamId = null;
    mocks.teamEpoch += 1;
    mocks.incognito = false;
    mocks.draftChatId = null;
    mocks.getRawChat.mockResolvedValue(null);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('reuses one invisible draft identity and one key across repeated focus and microphone activation', async () => {
    prepareChatForSend();
    const chatId = mocks.draftChatId;
    expect(chatId).toBeTruthy();
    prepareChatForSend({ draftChatId: chatId });
    const prepared = getPreparedChatForSend(chatId!);
    expect(prepared?.shell.messages_v).toBe(0);
    await prepared?.ready;
    expect(mocks.createKey).toHaveBeenCalledExactlyOnceWith(chatId);
    expect(mocks.getRawChat).toHaveBeenCalledExactlyOnceWith(chatId);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('primes the key for the exact preallocated new-chat shell ID', async () => {
    mocks.draftChatId = 'reserved-new-chat';
    prepareChatForSend({ currentChatId: 'reserved-new-chat', draftChatId: 'reserved-new-chat',
      freshNewChatShell: true });
    const prepared = getPreparedChatForSend('reserved-new-chat');
    expect(prepared?.shell.messages_v).toBe(0);
    await prepared?.ready;
    expect(mocks.getRawChat).toHaveBeenCalledExactlyOnceWith('reserved-new-chat');
    expect(mocks.createKey).toHaveBeenCalledExactlyOnceWith('reserved-new-chat');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,teams.context.full-switch-local
  it('excludes loaded chats, mismatched drafts, and Team shells', () => {
    mocks.draftChatId = 'reserved-new-chat';
    prepareChatForSend({ currentChatId: 'saved-chat', draftChatId: 'saved-chat' });
    expect(getPreparedChatForSend('saved-chat')).toBeNull();
    prepareChatForSend({ currentChatId: 'reserved-new-chat', draftChatId: 'other-draft', freshNewChatShell: true });
    expect(getPreparedChatForSend('reserved-new-chat')).toBeNull();
    mocks.teamId = 'team-one';
    prepareChatForSend({ currentChatId: 'reserved-new-chat', draftChatId: 'reserved-new-chat', freshNewChatShell: true });
    expect(getPreparedChatForSend('reserved-new-chat')).toBeNull();
    expect(mocks.getRawChat).not.toHaveBeenCalled();
    expect(mocks.createKey).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('never replaces a key for a saved encrypted draft and fences a switched account', async () => {
    mocks.draftChatId = 'saved-draft-id';
    mocks.getRawChat.mockResolvedValue({ team_id: null, encrypted_chat_key: 'sealed-key' });
    prepareChatForSend({ draftChatId: 'saved-draft-id' });
    await getPreparedChatForSend('saved-draft-id')?.ready;
    expect(mocks.getKey).toHaveBeenCalledWith('saved-draft-id');
    expect(mocks.createKey).not.toHaveBeenCalled();
    mocks.scope = 'account-b:personal';
    mocks.accountId = 'account-b';
    expect(getPreparedChatForSend('saved-draft-id')).toBeNull();
  });
});


describe('rendered fresh-shell startup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authenticated = true;
    mocks.accountId = 'account-a';
    mocks.scope = 'account-a:personal';
    mocks.teamId = null;
    mocks.teamEpoch += 1;
    mocks.incognito = false;
    mocks.draftChatId = null;
    mocks.getRawChat.mockResolvedValue(null);
  });
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('binds the visible draft before focus and keeps it through delayed initialization', async () => {
    let finishInitialize!: () => void;
    const initialize = new Promise<void>((resolve) => { finishInitialize = resolve; });
    const target = document.createElement('div');
    document.body.append(target);
    const component = mount(FreshShellMountHarness, { target, props: { initialize: () => initialize } });
    try {
      await tick();
      const shellId = target.querySelector('[data-testid="shell-id"]')!.textContent;
      expect(shellId).toBe('new-1');
      expect(mocks.draftChatId).toBe(shellId);
      const editor = target.querySelector('input')!;
      editor.focus();
      await tick();
      expect(mocks.draftChatId).toBe(shellId);
      editor.blur();
      editor.focus();
      finishInitialize();
      await initialize;
      await tick();
      expect(target.querySelector('[data-testid="shell-id"]')!.textContent).toBe(shellId);
      expect(target.querySelector('[data-testid="allocation-count"]')!.textContent).toBe('1');
      expect(mocks.draftChatId).toBe(shellId);
    } finally {
      await unmount(component);
      target.remove();
    }
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,video-call.chat.project-context
  it('adopts the exact prepared identity when Project focus happens before the composer mounts', async () => {
    prepareChatForSend();
    const preparedId = mocks.draftChatId;
    await getPreparedChatForSend(preparedId!)?.ready;
    let finishInitialize!: () => void;
    const initialize = new Promise<void>(resolve => { finishInitialize = resolve; });
    const target = document.createElement('div'); document.body.append(target);
    const component = mount(FreshShellMountHarness, { target, props: { initialize: () => initialize } });
    try {
      await tick();
      expect(target.querySelector('[data-testid="shell-id"]')!.textContent).toBe(preparedId);
      expect(target.querySelector('[data-testid="allocation-count"]')!.textContent).toBe('0');
      target.querySelector('input')!.focus();
      finishInitialize(); await initialize; await tick();
      expect(target.querySelector('[data-testid="shell-id"]')!.textContent).toBe(preparedId);
      expect(mocks.draftChatId).toBe(preparedId);
      expect(mocks.createKey).toHaveBeenCalledExactlyOnceWith(preparedId);
    } finally { await unmount(component); target.remove(); }
  });
});
