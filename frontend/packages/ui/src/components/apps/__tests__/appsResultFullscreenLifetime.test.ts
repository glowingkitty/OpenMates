import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({ getAppsResult: vi.fn(), resolveEmbed: vi.fn(), loadRenderer: vi.fn(), notify: vi.fn() }));
vi.mock('../../../stores/authStore', async () => ({ authStore: (await import('svelte/store')).writable({ isInitialized: true, isAuthenticated: true }) }));
vi.mock('../../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'owner-A', credits: 10 }) }));
vi.mock('../../../services/appsWorkspaceResultsService', async () => ({ getAppsResult: mocks.getAppsResult,
  appsResultSaveStates: (await import('svelte/store')).writable({}), appsResultSaveKey: () => 'save', retryAppsResultSave: vi.fn() }));
vi.mock('../../../services/embedResolver', () => ({ resolveEmbed: mocks.resolveEmbed, decodeToonContent: async (content: string) => JSON.parse(content) }));
vi.mock('../../../services/embedFullscreenResolver', () => ({ resolveRegistryKey: () => 'fixture', hasFullscreenComponent: () => true, loadFullscreenComponent: mocks.loadRenderer }));
vi.mock('../../../i18n/translations', async () => ({ text: (await import('svelte/store')).readable((key: string) => key) }));
vi.mock('../../../stores/notificationStore', () => ({ notificationStore: { error: mocks.notify } }));
vi.mock('../../embeds/UnifiedEmbedFullscreen.svelte', async () => ({ default: (await import('./AppsResultRendererStub.svelte')).default }));
import { authStore } from '../../../stores/authStore';
import { userProfile } from '../../../stores/userProfile';
import Renderer from './AppsResultRendererStub.svelte';
import Harness from './AppsResultLifetimeHarness.svelte';

let component: ReturnType<typeof Harness> | undefined;
const draft = () => document.querySelector<HTMLTextAreaElement>('textarea');
const flushLoads = async () => { for (let index = 0; index < 8; index++) await tick(); };
beforeEach(() => {
  vi.clearAllMocks();
  authStore.set({ isInitialized: true, isAuthenticated: true });
  userProfile.update(profile => ({ ...profile, user_id: 'owner-A', credits: 10 }));
  mocks.getAppsResult.mockResolvedValue(undefined);
  mocks.loadRenderer.mockResolvedValue(Renderer);
  mocks.resolveEmbed.mockImplementation(async (id: string) => ({ type: 'app-skill-use', status: 'finished',
    content: JSON.stringify({ title: `${get(userProfile).user_id}:${id}` }) }));
});
afterEach(async () => { if (component) await unmount(component); component = undefined; document.body.innerHTML = ''; });

describe('Apps result fullscreen identity', () => {
  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.library.embeds-account-paginated
  it('keeps the same renderer DOM and unsent draft across same-owner credits and auth publications', async () => {
    component = mount(Harness, { target: document.body, props: { onClose: vi.fn() } });
    await flushLoads();
    const input = draft()!;
    expect(input).not.toBeNull();
    input.value = 'Explain these appointments'; input.dispatchEvent(new Event('input', { bubbles: true }));
    userProfile.update(profile => ({ ...profile, user_id: 'owner-A', credits: 9 }));
    authStore.set({ isInitialized: true, isAuthenticated: true });
    await flushLoads();
    expect(draft()).toBe(input);
    expect(draft()?.value).toBe('Explain these appointments');
    expect(mocks.getAppsResult).toHaveBeenCalledTimes(1);
    expect(mocks.loadRenderer).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.library.embeds-account-paginated
  it('reloads actual owner and sibling/root/team route changes while rejecting late old-owner errors', async () => {
    let rejectOld!: (error: Error) => void;
    mocks.getAppsResult.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
    const onClose = vi.fn();
    component = mount(Harness, { target: document.body, props: { onClose } });
    await flushLoads();
    userProfile.update(profile => ({ ...profile, user_id: 'owner-B', credits: 9 }));
    await flushLoads();
    expect(document.querySelector('[data-testid="result-title"]')?.textContent).toBe('owner-B:child-one');
    rejectOld(new Error('stale owner result failed'));
    await flushLoads();
    expect(mocks.notify).not.toHaveBeenCalled(); expect(onClose).not.toHaveBeenCalled();
    component.navigate({ embedId: 'child-two', rootEmbedId: 'root', teamId: undefined });
    await flushLoads();
    expect(document.querySelector('[data-testid="result-title"]')?.textContent).toBe('owner-B:child-two');
    component.navigate({ embedId: 'child-three', rootEmbedId: 'root-two', teamId: 'team-B' });
    await flushLoads();
    expect(mocks.getAppsResult).toHaveBeenLastCalledWith('root-two', 'team-B');
    expect(document.querySelector('[data-testid="result-title"]')?.textContent).toBe('owner-B:child-three');
    mocks.getAppsResult.mockRejectedValueOnce(new Error('current result unavailable'));
    component.navigate({ embedId: 'missing', rootEmbedId: 'missing-root', teamId: 'team-B' });
    await flushLoads();
    expect(mocks.notify).toHaveBeenCalledExactlyOnceWith('apps_workspace.result_unavailable');
    expect(onClose).toHaveBeenCalledOnce();
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.library.embeds-account-paginated
  it('clears private DOM when readiness is lost and ignores a cancelled load until the next owner is ready', async () => {
    component = mount(Harness, { target: document.body, props: { onClose: vi.fn() } });
    await flushLoads();
    expect(draft()).not.toBeNull();
    authStore.set({ isInitialized: false, isAuthenticated: true });
    await flushLoads();
    expect(draft()).toBeNull();
    expect(document.querySelector('[data-testid="result-title"]')).toBeNull();
    authStore.set({ isInitialized: true, isAuthenticated: true });
    await flushLoads();
    expect(draft()).not.toBeNull();
    let finishOld!: () => void;
    mocks.getAppsResult.mockImplementationOnce(() => new Promise<void>(resolve => { finishOld = resolve; }));
    component.navigate({ embedId: 'pending-child', rootEmbedId: 'pending-root', teamId: undefined });
    await flushLoads();
    authStore.set({ isInitialized: false, isAuthenticated: true });
    await flushLoads();
    expect(draft()).toBeNull();
    expect(document.querySelector('[data-testid="result-title"]')).toBeNull();
    finishOld();
    await flushLoads();
    expect(draft()).toBeNull();
    const loadsBeforeReady = mocks.getAppsResult.mock.calls.length;
    userProfile.update(profile => ({ ...profile, user_id: 'owner-B', credits: 20 }));
    await flushLoads();
    expect(mocks.getAppsResult).toHaveBeenCalledTimes(loadsBeforeReady);
    authStore.set({ isInitialized: true, isAuthenticated: true });
    await flushLoads();
    expect(document.querySelector('[data-testid="result-title"]')?.textContent).toBe('owner-B:pending-child');
    expect(mocks.getAppsResult).toHaveBeenCalledTimes(loadsBeforeReady + 1);
    expect(mocks.notify).not.toHaveBeenCalled();
  });

});
