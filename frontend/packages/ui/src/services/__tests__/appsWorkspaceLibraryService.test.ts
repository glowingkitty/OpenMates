import { beforeEach, describe, expect, it, vi } from 'vitest';
// Shared embed SSR may reach this service before the authentication action barrel initializes.
vi.mock('../../stores/authStore', () => { throw new Error('Apps library must not initialize authentication actions'); });
vi.mock('../../stores/authState', async () => ({ authStore: (await import('svelte/store')).writable({ isAuthenticated: true }) }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'A' }) }));
vi.mock('../../stores/teamStore', async () => ({ activeTeamContext: (await import('svelte/store')).writable({ teamId: null as string | null, epoch: 0 }) }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => path }));
vi.mock('../../i18n/translations', async () => ({ text: (await import('svelte/store')).writable((key: string) => key) }));
vi.mock('../../stores/notificationStore', () => ({ notificationStore: { addNotificationWithOptions: vi.fn(), removeNotification: vi.fn(), error: vi.fn() } }));
import { userProfile } from '../../stores/userProfile';
import { activeTeamContext } from '../../stores/teamStore';
import { notificationStore } from '../../stores/notificationStore';
import { appsSearchQuery, isAppsSearchSaved, emptyAppsLibrary, freshAppsRecommendations, getAppsLibrary, saveAppsSearchWithNotice } from '../appsWorkspaceLibraryService';

beforeEach(() => { vi.clearAllMocks(); vi.mocked(notificationStore.addNotificationWithOptions).mockReturnValue('daily-search-notice'); userProfile.set({ user_id: 'A' }); activeTeamContext.set({ teamId: null, epoch: 0 }); });
describe('private Apps library ownership and expiry', () => {
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('can initialize a shared fullscreen library dependency without loading authentication actions', () => {
    expect(emptyAppsLibrary('web')).toMatchObject({ app_id: 'web', saved_searches: [] });
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('preserves a preemptive optout without claiming daily searches are enabled', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...emptyAppsLibrary('travel'), first_save: true, daily_searches_enabled: false }))));
    const saved = await saveAppsSearchWithNotice('travel', { skill_id: 'search', input: { origin: 'BER' } }, 'Berlin trips');
    expect(saved.daily_searches_enabled).toBe(false);
    expect(notificationStore.addNotificationWithOptions).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('never shows recommendations at 24 hours, after explicit expiry, or from the future', () => {
    const now = 2_000_000;
    const batch = { id: 'b', skill_id: 'search', created_at: now - 100, expires_at: now + 100, result: {} };
    expect(freshAppsRecommendations([batch, { ...batch, created_at: now - 86400 },
      { ...batch, expires_at: now }, { ...batch, created_at: now + 1 }], now * 1000)).toEqual([batch]);
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('rejects late data after Team A to Personal to Team A', async () => {
    activeTeamContext.set({ teamId: 'team-A', epoch: 1 });
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve; })));
    const pending = getAppsLibrary('travel', 'team-A');
    activeTeamContext.set({ teamId: null, epoch: 2 });
    activeTeamContext.set({ teamId: 'team-A', epoch: 3 });
    finish(new Response(JSON.stringify(emptyAppsLibrary('travel'))));
    await expect(pending).rejects.toThrow('account_context_changed');
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('first-save Turn off cannot change another account even after switching back', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...emptyAppsLibrary('travel'), first_save: true })));
    vi.stubGlobal('fetch', fetchMock);
    await saveAppsSearchWithNotice('travel', { skill_id: 'search', input: { origin: 'BER' } }, 'Berlin trips');
    const options = vi.mocked(notificationStore.addNotificationWithOptions).mock.calls[0][1];
    userProfile.set({ user_id: 'B' }); userProfile.set({ user_id: 'A' });
    options.onSecondaryAction?.();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('Turn off disables daily searches for the saving owner without deleting the saved query', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ ...emptyAppsLibrary('travel'), first_save: true })));
    vi.stubGlobal('fetch', fetchMock);
    await saveAppsSearchWithNotice('travel', { skill_id: 'search', input: { origin: 'BER' } }, 'Berlin trips');
    vi.mocked(notificationStore.addNotificationWithOptions).mock.calls[0][1].onSecondaryAction?.();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toContain('/travel/settings');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ daily_searches_enabled: false, expected_user_id: 'A' });
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('dismisses the first-save notice only after Turn off successfully persists', async () => {
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...emptyAppsLibrary('web'), first_save: true })))
      .mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }));
    vi.stubGlobal('fetch', fetchMock);
    await saveAppsSearchWithNotice('web', { skill_id: 'search', input: { query: 'science' } }, 'Science');
    vi.mocked(notificationStore.addNotificationWithOptions).mock.calls[0][1].onSecondaryAction?.();
    expect(notificationStore.removeNotification).not.toHaveBeenCalled();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ daily_searches_enabled: false, expected_user_id: 'A' });
    finish(new Response(JSON.stringify({ ...emptyAppsLibrary('web'), daily_searches_enabled: false })));
    await vi.waitFor(() => expect(notificationStore.removeNotification).toHaveBeenCalledExactlyOnceWith('daily-search-notice'));
    expect(notificationStore.error).not.toHaveBeenCalled();
  });
  // contract-test: direct surface=gui.web assertions=apps.recommendations.private-daily
  it('retains the notice and reports a failed Turn off so the user can retry', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...emptyAppsLibrary('web'), first_save: true })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'library_unavailable' }), { status: 503 }));
    vi.stubGlobal('fetch', fetchMock);
    await saveAppsSearchWithNotice('web', { skill_id: 'search', input: { query: 'science' } }, 'Science');
    vi.mocked(notificationStore.addNotificationWithOptions).mock.calls[0][1].onSecondaryAction?.();
    await vi.waitFor(() => expect(notificationStore.error).toHaveBeenCalledWith('apps_workspace.library_error'));
    expect(notificationStore.removeNotification).not.toHaveBeenCalled();
  });

});

// contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
describe('saved search identity', () => {
  it('recognizes native requests with reordered nested object keys without comparing result text', () => {
    const library = { ...emptyAppsLibrary('news'), saved_searches: [{ id: 'saved', skill_id: 'search', parameters: { requests: [{ query: 'Climate news', count: 10, options: { country: 'DE', language: 'en' } }] }, query: 'An older display title', saved_at: 1 }] };
    expect(isAppsSearchSaved(library, { skill_id: 'search', input: { requests: [{ options: { language: 'en', country: 'DE' }, count: 10, query: 'Climate news' }] }, result: { title: 'Current title' } })).toBe(true);
    expect(isAppsSearchSaved(library, { skill_id: 'search', input: { requests: [{ query: 'Different news', count: 10, options: { country: 'DE', language: 'en' } }] } })).toBe(false);
    expect(isAppsSearchSaved(library, { skill_id: 'other_skill', input: library.saved_searches[0].parameters })).toBe(false);
    expect(isAppsSearchSaved(library, { skill_id: 'search' })).toBe(false);
    expect(isAppsSearchSaved(null, { skill_id: 'search', input: {} })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
  it('preserves request order and native value types', () => {
    const library = { ...emptyAppsLibrary('news'), saved_searches: [{ id: 'saved', skill_id: 'search', parameters: { requests: [{ query: 'First' }, { query: 'Second' }], count: 10 }, saved_at: 1 }] };
    expect(isAppsSearchSaved(library, { skill_id: 'search', input: { count: 10, requests: [{ query: 'Second' }, { query: 'First' }] } })).toBe(false);
    expect(isAppsSearchSaved(library, { skill_id: 'search', input: { count: '10', requests: [{ query: 'First' }, { query: 'Second' }] } })).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=apps.results.shared-fullscreen,apps.recommendations.private-daily
  it('uses the native requests envelope query for old search results', () => {
    expect(appsSearchQuery({ skill_id: 'search', input: { requests: [{ query: 'News from Berlin' }] } })).toBe('News from Berlin');
  });
});
