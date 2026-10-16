// Linked previews read authorized metadata without copying chats or transcripts.
import { beforeEach, describe, expect, it, vi } from 'vitest';
const context = vi.hoisted(() => ({ teamId: null as string | null, epoch: 1 }));
const api = vi.hoisted(() => ({ getChat: vi.fn(), decrypt: vi.fn(), hydrate: vi.fn() }));
const listeners = vi.hoisted(() => new Map<string, (event: Event) => void>());
vi.mock('../db', () => ({ chatDB: { getChat: api.getChat } }));
vi.mock('../chatMetadataCache', () => ({ CHAT_METADATA_KEY_READY_EVENT: 'chatMetadataKeyReady', chatMetadataCache: { getDecryptedMetadata: api.decrypt } }));
vi.mock('../chatSyncService', () => ({ chatSyncService: { hydrateSidebarChats: api.hydrate,
  addEventListener: (name: string, listener: (event: Event) => void) => listeners.set(name, listener) } }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => path }));
vi.mock('../../stores/teamStore', () => ({ getActiveTeamContextSnapshot: () => context }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'preview-owner' }) }));
import { userProfile } from '../../stores/userProfile';
import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
import { WorkspaceCacheDiscardedError } from '../workspaceQueryCache';
import { loadProjectChatPresentation } from '../projectChatPreviewService';

const metadata = { title: 'Current title', summary: 'Current summary', category: 'technology', icon: 'code' };
describe('Project chat presentations', () => {
  beforeEach(() => {
    vi.resetAllMocks(); invalidateWorkspaceCaches();
    context.teamId = null; context.epoch += 1;
    userProfile.update(profile => ({ ...profile, user_id: 'preview-owner' }));
    api.getChat.mockResolvedValue({ chat_id: 'one', team_id: null });
    api.decrypt.mockResolvedValue(metadata);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('reads current decrypted metadata once and reuses the bounded projection', async () => {
    const first = await loadProjectChatPresentation('one');
    expect(first).toEqual({ ...metadata, teamId: null });
    expect(await loadProjectChatPresentation('one')).toEqual(first);
    expect(api.getChat).toHaveBeenCalledOnce(); expect(api.decrypt).toHaveBeenCalledOnce();
    expect(api.hydrate).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it.each([{ is_hidden: true }, { is_hidden_candidate: true }, { is_incognito: true }, { team_id: 'other-team' }])(
    'rejects inaccessible local chat metadata: %j', async flags => {
      api.getChat.mockResolvedValue({ chat_id: 'one', team_id: null, ...flags });
      expect(await loadProjectChatPresentation('one')).toBeNull();
      expect(api.decrypt).not.toHaveBeenCalled(); expect(api.hydrate).not.toHaveBeenCalled();
    });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('coalesces missing linked metadata and leaves unavailable links unopened', async () => {
    api.getChat.mockResolvedValue(null);
    api.hydrate.mockResolvedValue(undefined);
    expect(await Promise.all([loadProjectChatPresentation('one'), loadProjectChatPresentation('two')])).toEqual([null, null]);
    expect(api.hydrate).toHaveBeenCalledExactlyOnceWith(['one', 'two']);
    expect(api.decrypt).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('uses authorized hydrated metadata and preserves team routing', async () => {
    context.teamId = 'current-team';
    api.getChat.mockResolvedValueOnce(null).mockResolvedValue({ chat_id: 'one', team_id: 'current-team' });
    api.hydrate.mockResolvedValue(undefined);
    expect(await loadProjectChatPresentation('one')).toEqual({ ...metadata, teamId: 'current-team' });
    expect(api.hydrate).toHaveBeenCalledExactlyOnceWith(['one']);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('discards a decrypt response after the account changes', async () => {
    api.decrypt.mockImplementation(async () => {
      userProfile.update(profile => ({ ...profile, user_id: 'next-owner' }));
      return metadata;
    });
    await expect(loadProjectChatPresentation('one')).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
    api.decrypt.mockResolvedValue({ ...metadata, title: 'Next owner title' });
    expect((await loadProjectChatPresentation('one'))?.title).toBe('Next owner title');
    expect(api.decrypt).toHaveBeenCalledTimes(2);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('discards old team data even when the team switches back during decryption', async () => {
    api.decrypt.mockImplementation(async () => { context.epoch += 2; return metadata; });
    await expect(loadProjectChatPresentation('one')).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('refreshes changed metadata and propagates a hydration error for retry', async () => {
    await loadProjectChatPresentation('one');
    api.decrypt.mockResolvedValue({ ...metadata, title: 'Updated title' });
    expect((await loadProjectChatPresentation('one', true))?.title).toBe('Updated title');
    api.getChat.mockResolvedValue(null);
    api.hydrate.mockRejectedValue(new Error('Metadata unavailable'));
    await expect(loadProjectChatPresentation('two')).rejects.toThrow('Metadata unavailable');
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('awaits fresh metadata after expiry instead of leaving a stale card mounted', async () => {
    vi.useFakeTimers();
    try {
      await loadProjectChatPresentation('one');
      vi.advanceTimersByTime(30_001);
      api.getChat.mockResolvedValue(null); api.hydrate.mockResolvedValue(undefined);
      expect(await loadProjectChatPresentation('one')).toBeNull();
    } finally { vi.useRealTimers(); }
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it('retries metadata when a delayed chat key becomes ready', async () => {
    api.decrypt.mockResolvedValueOnce(null);
    expect(await loadProjectChatPresentation('one')).toBeNull();
    window.dispatchEvent(new CustomEvent('chatMetadataKeyReady', { detail: { chatId: 'one' } }));
    expect((await loadProjectChatPresentation('one'))?.title).toBe('Current title');
  });
  // contract-test: supporting surface=gui.web assertions=projects.links.openmates-only-encrypted
  it.each(['chatUpdated', 'chatDeleted'])('supersedes an in-flight decrypt after %s', async eventName => {
    let release!: (value: typeof metadata) => void;
    api.decrypt.mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const old = loadProjectChatPresentation('one');
    const rejected = expect(old).rejects.toBeInstanceOf(WorkspaceCacheDiscardedError);
    await vi.waitFor(() => expect(api.decrypt).toHaveBeenCalledOnce());
    listeners.get(eventName)!(new CustomEvent(eventName, { detail: { chat_id: 'one' } }));
    if (eventName === 'chatDeleted') { api.getChat.mockResolvedValue(null); api.hydrate.mockResolvedValue(undefined); }
    else api.decrypt.mockResolvedValue({ ...metadata, title: 'Latest title' });
    const current = await loadProjectChatPresentation('one', true);
    expect(current?.title ?? null).toBe(eventName === 'chatDeleted' ? null : 'Latest title');
    release(metadata); await rejected;
    expect(await loadProjectChatPresentation('one')).toEqual(current);
  });
});
