import {expect, it, vi} from 'vitest';
vi.mock('../../../../data/modelsMetadata', () => ({modelsMetadata: []}));
vi.mock('../../../../data/matesMetadata', () => ({matesMetadata: []}));
vi.mock('../../../../data/providerIcons', () => ({getProviderIconUrl: () => ''}));
vi.mock('../../../../utils/aiModelSelection', () => ({aiModelSelectionValue: () => null}));
vi.mock('../../../../stores/personalDocumentMemories', () => ({currentPersonalDocumentMemories: () => []}));
vi.mock('../../../../stores/userProfile', async () => ({userProfile: (await import('svelte/store')).writable({disabled_ai_models: []})}));
vi.mock('../../../../stores/appHealthStore', async () => ({isProviderHealthy: (await import('svelte/store')).writable(() => true)}));
vi.mock('../../../../stores/appSettingsMemoriesStore', async () => ({appSettingsMemoriesStore: (await import('svelte/store')).writable({entries: [], decryptedEntries: new Map()})}));
vi.mock('../../../../stores/appSkillsStore', () => ({appSkillsStore: {apps: {}}}));
vi.mock('../../../../services/projectService', () => ({listProjects: async () => [], getProjectSettings: vi.fn(), listProjectSources: vi.fn()}));
vi.mock('../../../../i18n/translations', async () => ({text: (await import('svelte/store')).writable((key: string) => key)}));
vi.mock('../../../../i18n/setup', () => ({getCurrentLanguage: () => 'en'}));
vi.mock('../../../../config/api', () => ({getApiUrl: () => ''}));
vi.mock('../../../../utils/imageProxy', () => ({proxyImage: (url: string) => url}));

import {searchMentions} from '../mentionSearchService';

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
it('offers the exact @openmates token for Team chats at @ and during case-insensitive search', () => {
  const atResult = searchMentions('', 8, true)[0];
  expect(atResult).toMatchObject({type: 'openmates', displayName: 'OpenMates', mentionSyntax: '@openmates'});
  expect(searchMentions('OPENMATES', 8, true)[0]).toMatchObject({type: 'openmates', mentionSyntax: '@openmates'});
  expect(searchMentions('openmat', 8, true)[0]).toMatchObject({type: 'openmates', mentionSyntax: '@openmates'});
});

// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
it('keeps Personal mention defaults and search free of the Team-only OpenMates result', () => {
  expect(searchMentions('').some(result => result.type === 'openmates')).toBe(false);
  expect(searchMentions('OPENMATES').some(result => result.type === 'openmates')).toBe(false);
});
