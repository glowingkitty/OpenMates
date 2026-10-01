import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({
  goto: vi.fn().mockResolvedValue(undefined),
  replaceState: vi.fn(),
}));

import { goto, replaceState } from '$app/navigation';
import { parseDeepLink, processDeepLink, processSettingsDeepLink } from '../deepLinkHandler';

describe('legacy Apps links', () => {
  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('forwards Apps Settings routes to the public workspace', () => {
    expect(parseDeepLink('#settings/apps/health/skill/search_appointments/provider/doctorly'))
      .toEqual({ type: 'apps', data: { hash: '#apps/health/search-appointments/provider/doctorly' } });
    expect(parseDeepLink('#settings/settings_memories'))
      .toEqual({ type: 'apps', data: { hash: '#apps/all&filter=settings_memories' } });
  });
  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('navigates the route so the reactive page URL follows a legacy Settings link', async () => {
    await processDeepLink('#settings/apps/health/skill/search_appointments', {});
    expect(goto).toHaveBeenCalledWith('/#apps/health/search-appointments', {
      replaceState: true,
      noScroll: true,
      keepFocus: true,
    });
  });
  // contract-test: supporting surface=gui.web assertions=apps.presentation.shared-detail-and-recency
  it('Apps examples open a fresh unsent draft despite a docs auto-send flag', async () => {
    sessionStorage.setItem('docs_auto_send', 'true');
    const calls: unknown[][] = [];
    await processDeepLink('#new-message=Hello%20world', { onMessage: async (...args) => { calls.push(args); } });
    expect(calls).toEqual([['Hello world', false, true]]);
    sessionStorage.removeItem('docs_auto_send');
  });
});

describe('workspace Settings links', () => {
  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding,settings-ui.shell.lifecycle-and-routing
  it('preserves Apps route hashes while routing main, aliases, and special Settings links', () => {
    const openSettings = vi.fn();
    const setSettingsDeepLink = vi.fn();
    const handlers = { openSettings, setSettingsDeepLink };
    vi.mocked(replaceState).mockClear();

    processSettingsDeepLink('#apps/all&settings=main', handlers, { preserveHash: true });
    processSettingsDeepLink('#apps/health&settings=memories', handlers, { preserveHash: true });
    processSettingsDeepLink('#apps/all&settings=newsletter/confirm/example-token', handlers, { preserveHash: true });

    expect(openSettings).toHaveBeenCalledTimes(3);
    expect(setSettingsDeepLink.mock.calls.map(([path]) => path)).toEqual(['main', 'settings_memories', 'newsletter']);
    expect(replaceState).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it('still consumes standalone Settings links after routing', () => {
    const setSettingsDeepLink = vi.fn();
    vi.mocked(replaceState).mockClear();

    processSettingsDeepLink('#settings/privacy/pii', {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith('privacy/hide-personal-data');
    expect(replaceState).toHaveBeenCalledWith(window.location.pathname + window.location.search, {});
  });
});
