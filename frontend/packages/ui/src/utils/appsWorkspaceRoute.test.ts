import { describe, expect, it } from 'vitest';
import { buildAppsWorkspaceHash, readAppsWorkspaceRoute, resolveAppsAppId, resolveAppsSkillId } from './appsWorkspaceRoute';

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
        tab: 'embeds', showAll: false, embedId: 'embed-1' });
    expect(readAppsWorkspaceRoute('#apps/health/search-appointments/provider/doctorly&tab=workflows'))
      .toEqual({ appId: 'health', skillId: 'search-appointments', settingsPath: 'provider/doctorly',
        tab: 'workflows', showAll: false, embedId: null });
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
      settingsPath: null, tab: 'overview', showAll: false, embedId: null });
    expect(readAppsWorkspaceRoute('#apps/all&filter=settings_memories')?.showAll).toBe(true);
    expect(buildAppsWorkspaceHash('apps/all/focus-modes')).toBe('#apps/all&filter=focus_modes');
    expect(readAppsWorkspaceRoute('#chat-id=1')).toBeNull();
  });
});
