import { describe, expect, it, vi } from 'vitest';
import { buildAppsWorkspaceHash, readAppsWorkspaceOrigin, readAppsWorkspaceRoute, resolveAppsAppId, resolveAppsSkillId, withAppsWorkspaceOrigin } from './appsWorkspaceRoute';

describe('Apps workspace route', () => {
  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('forwards legacy skill URLs while preserving provider and model detail suffixes', () => {
    expect(buildAppsWorkspaceHash('apps/health/skill/search_appointments/provider/doctorly'))
      .toBe('#apps/health/search-appointments/provider/doctorly');
    expect(buildAppsWorkspaceHash('/apps/health/skill/search_appointments/model/model-v2'))
      .toBe('#apps/health/search-appointments/model/model-v2');
    expect(resolveAppsSkillId('search-appointments', ['search_appointments', 'search']))
      .toBe('search_appointments');
    expect(resolveAppsAppId('social-media', ['social_media', 'news'])).toBe('social_media');
    expect(buildAppsWorkspaceHash('apps/social_media/search')).toBe('#apps/social-media/search');
  });

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('keeps focus, memory, content, tab and selected embed state', () => {
    expect(buildAppsWorkspaceHash('apps/health/focus/care_plan')).toBe('#apps/health/focus/care_plan');
    expect(buildAppsWorkspaceHash('apps/health/settings_memories/medical_history/entry/entry_1'))
      .toBe('#apps/health/memory/medical_history/entry/entry_1');
    expect(buildAppsWorkspaceHash('apps/health/content/report')).toBe('#apps/health/content/report');
    expect(readAppsWorkspaceRoute('#apps/health/search-appointments&tab=embeds&embed-id=embed-1'))
      .toEqual({ appId: 'health', skillId: 'search-appointments', settingsPath: null,
        tab: 'embeds', showAll: false, embedId: 'embed-1', rootEmbedId: null });
    expect(readAppsWorkspaceRoute('#apps/health/search-appointments/provider/doctorly&tab=workflows'))
      .toEqual({ appId: 'health', skillId: 'search-appointments', settingsPath: 'provider/doctorly',
        tab: 'workflows', showAll: false, embedId: null, rootEmbedId: null });
    expect(buildAppsWorkspaceHash('apps/health/search-appointments&embed-id=one&tab=embeds'))
      .toBe('#apps/health/search-appointments&embed-id=one&tab=embeds');
    expect(readAppsWorkspaceRoute(buildAppsWorkspaceHash('apps/health', 'focus_modes'))?.tab)
      .toBe('focus_modes');
    expect(readAppsWorkspaceRoute(buildAppsWorkspaceHash('apps/books', 'settings_memories'))?.tab)
      .toBe('settings_memories');
  });

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('recognizes the public index and leaves other workspaces alone', () => {
    expect(readAppsWorkspaceRoute('#apps')).toEqual({ appId: null, skillId: null,
      settingsPath: null, tab: 'overview', showAll: false, embedId: null, rootEmbedId: null });
    expect(readAppsWorkspaceRoute('#apps/web/search&embed-id=child&root-id=parent')?.rootEmbedId).toBe('parent');
    expect(readAppsWorkspaceRoute('#apps/all&filter=settings_memories')?.showAll).toBe(true);
    expect(buildAppsWorkspaceHash('apps/all/focus-modes')).toBe('#apps/all&filter=focus_modes');
    expect(readAppsWorkspaceRoute('#chat-id=1')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('keeps an originating chat through Apps navigation and leaves direct links without an origin', () => {
    const chat = '#chat-id=example-memory-books-currently-reading';
    const detail = buildAppsWorkspaceHash('apps/health/focus/care_plan', undefined, chat);
    expect(readAppsWorkspaceOrigin(detail)).toBe(chat);
    expect(readAppsWorkspaceOrigin(withAppsWorkspaceOrigin('#apps/health&tab=focus_modes', detail))).toBe(chat);
    expect(withAppsWorkspaceOrigin('#apps/health', '#apps/all')).toBe('#apps/health&origin=%23apps%2Fall');
    expect(withAppsWorkspaceOrigin('#apps/health', '/#apps')).toBe('#apps/health&origin=%23apps');
    expect(withAppsWorkspaceOrigin('#apps/health/search', '#apps/health')).toBe('#apps/health/search');
    expect(readAppsWorkspaceOrigin('#apps/health/search')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('keeps first-party page origins in this tab without putting decryption fragments in Apps URLs', () => {
    // The shared Vitest crypto shim intentionally omits getRandomValues.
    vi.stubGlobal('crypto', { ...crypto, getRandomValues: (values: Uint8Array) => values.fill(0xab) });
    const sharePath = '/share/chat/shared-id#key=private-blob&messageid=message-1';
    const detail = withAppsWorkspaceOrigin('#apps/health', sharePath);
    expect(detail).toMatch(/^#apps\/health&origin-ref=[a-f0-9]{32}$/);
    expect(detail).not.toContain('private-blob');
    expect(readAppsWorkspaceOrigin(detail)).toBe(sharePath);
    const next = withAppsWorkspaceOrigin('#apps/health&tab=focus_modes', detail);
    expect(next.split('origin-ref=')[1]).toBe(detail.split('origin-ref=')[1]);
    expect(readAppsWorkspaceOrigin(next)).toBe(sharePath);
    expect(readAppsWorkspaceOrigin(buildAppsWorkspaceHash('apps/health', undefined, '/'))).toBe('/');
    vi.unstubAllGlobals();
  });

  // contract-test: supporting surface=gui.web assertions=apps.navigation.hash-and-forwarding
  it('rejects secret, external and pseudo-route inline origins', () => {
    expect(withAppsWorkspaceOrigin('#apps/health', '/#key=private-blob')).toBe('#apps/health');
    expect(withAppsWorkspaceOrigin('#apps/health', '/#chat-id=chat-1&token=private')).toBe('#apps/health');
    expect(withAppsWorkspaceOrigin('#apps/health', 'https://elsewhere.example/#chat-id=chat-1')).toBe('#apps/health');
    expect(readAppsWorkspaceOrigin('#apps/health&origin=%23key%3Dprivate-blob')).toBeNull();
    expect(readAppsWorkspaceOrigin('#apps/health&origin=%23javascript%3Aalert(1)')).toBeNull();
    expect(readAppsWorkspaceOrigin('#apps/health&origin=%23settings%2Fapps%2Fhealth')).toBeNull();
    expect(readAppsWorkspaceOrigin('#apps/health&origin=%23apps%2Fhealth%26origin-ref%3Dabc')).toBeNull();
    sessionStorage.setItem(`openmates:apps-origin:${'b'.repeat(32)}`, '/#key=private-blob');
    expect(readAppsWorkspaceOrigin(`#apps/health&origin-ref=${'b'.repeat(32)}`)).toBeNull();
  });
});
