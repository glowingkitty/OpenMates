import { mount, tick, unmount } from 'svelte';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), error: vi.fn() }));
vi.mock('../../../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner' }) }));
vi.mock('../../../../stores/teamStore', async () => ({ activeTeamContext: (await import('svelte/store')).writable({ teamId: null, team: null, epoch: 0 }) }));
vi.mock('../../../../stores/notificationStore', () => ({ notificationStore: { error: mocks.error } }));
vi.mock('../../../../i18n/translations', async () => ({ text: (await import('svelte/store')).writable((key: string) => key) }));
vi.mock('../../../../services/appsWorkspaceLibraryService', () => ({ getAppsLibrary: mocks.load, setAppsDailySearches: mocks.save }));
import DailySettings from '../AppDailySearchesSettings.svelte';
import { authStore } from '../../../../stores/authState';
import { activeTeamContext } from '../../../../stores/teamStore';

let component: ReturnType<typeof mount> | undefined;
const toggle = () => document.querySelector('[data-testid="apps-daily-searches-toggle"]') as HTMLElement;
const row = () => document.querySelector('[data-testid="apps-daily-searches"]') as HTMLElement;
const deferred = () => { let resolve!: (value: { daily_searches_enabled: boolean }) => void; const promise = new Promise<{ daily_searches_enabled: boolean }>(r => { resolve = r; }); return { resolve, promise }; };
beforeEach(() => {
  vi.clearAllMocks();
  authStore.set({ isAuthenticated: true } as never);
  activeTeamContext.set({ teamId: null, team: null, epoch: 0 });
  mocks.load.mockResolvedValue({ daily_searches_enabled: true });
  mocks.save.mockResolvedValue({ daily_searches_enabled: false });
});
afterEach(async () => { if (component) await unmount(component); component = undefined; document.body.innerHTML = ''; });
async function render() { component = mount(DailySettings, { target: document.body, props: { appId: 'web' } }); await tick(); }

// contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency
describe('canonical app Daily searches settings', () => {
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.recommendations.private-daily
  it('loads its preference, persists toggle, and refreshes the matching app library', async () => {
    const event = vi.fn(); window.addEventListener('appsWorkspaceLibraryUpdated', event);
    await render(); await vi.waitFor(() => expect(toggle().getAttribute('tabindex')).toBe('0'));
    toggle().click();
    await vi.waitFor(() => expect(mocks.save).toHaveBeenCalledWith('web', false, undefined));
    await vi.waitFor(() => expect(event).toHaveBeenCalledOnce());
    expect(event.mock.calls[0][0].detail).toEqual({ appId: 'web', teamId: undefined });
    window.removeEventListener('appsWorkspaceLibraryUpdated', event);
  });
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.recommendations.private-daily
  it('hides for guests and never fetches their library', async () => {
    authStore.set({ isAuthenticated: false } as never); await render();
    expect(row()).toBeNull(); expect(mocks.load).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.recommendations.private-daily
  it('loads a team preference but prevents viewer mutation', async () => {
    activeTeamContext.set({ teamId: 'team-a', team: { role: 'viewer' } as never, epoch: 1 }); await render();
    await vi.waitFor(() => expect(mocks.load).toHaveBeenCalledWith('web', 'team-a', expect.any(AbortSignal)));
    toggle().click(); await tick(); expect(mocks.save).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.recommendations.private-daily
  it('ignores a pending mutation after changing team context', async () => {
    const pending = deferred(); mocks.save.mockReturnValue(pending.promise);
    const event = vi.fn(); window.addEventListener('appsWorkspaceLibraryUpdated', event);
    await render(); await vi.waitFor(() => expect(toggle().getAttribute('tabindex')).toBe('0')); toggle().click();
    activeTeamContext.set({ teamId: 'team-b', team: { role: 'owner' } as never, epoch: 1 }); await tick();
    pending.resolve({ daily_searches_enabled: false }); await tick();
    expect(event).not.toHaveBeenCalled(); expect(mocks.error).not.toHaveBeenCalled();
    window.removeEventListener('appsWorkspaceLibraryUpdated', event);
  });
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency,apps.recommendations.private-daily
  it('reports mutation errors through existing notifications', async () => {
    mocks.save.mockRejectedValue(new Error('failure')); await render();
    await vi.waitFor(() => expect(toggle().getAttribute('tabindex')).toBe('0')); toggle().click();
    await vi.waitFor(() => expect(mocks.error).toHaveBeenCalledWith('apps_workspace.library_error'));
  });
});
