import {beforeEach, expect, it, vi} from 'vitest';
const fixture = vi.hoisted(() => ({entries: [] as Record<string, unknown>[]}));
vi.mock('../../../../data/modelsMetadata', () => ({modelsMetadata: []}));
vi.mock('../../../../data/matesMetadata', () => ({matesMetadata: []}));
vi.mock('../../../../data/providerIcons', () => ({getProviderIconUrl: () => ''}));
vi.mock('../../../../utils/aiModelSelection', () => ({aiModelSelectionValue: () => null}));
vi.mock('../../../../stores/personalDocumentMemories', () => ({currentPersonalDocumentMemories: () => fixture.entries}));
vi.mock('../../../../stores/userProfile', async () => ({userProfile: (await import('svelte/store')).writable({disabled_ai_models: []})}));
vi.mock('../../../../stores/appHealthStore', async () => ({isProviderHealthy: (await import('svelte/store')).writable(() => true)}));
vi.mock('../../../../stores/appSettingsMemoriesStore', async () => ({appSettingsMemoriesStore: (await import('svelte/store')).writable({entries: [], decryptedEntries: new Map()})}));
vi.mock('../../../../stores/appSkillsStore', () => ({appSkillsStore: {apps: {openmates: {
  id: 'openmates', name: 'OpenMates', skills: [], focus_modes: [],
  settings_and_memories: [{id: 'memories', type: 'list', name_translation_key: 'Memories', description_translation_key: 'Your saved memories', schema_definition: {properties: {title: {is_title: true}, document: {type: 'string'}}}}],
}}}}));
vi.mock('../../../../services/projectService', () => ({listProjects: async () => [], getProjectSettings: vi.fn(), listProjectSources: vi.fn()}));
vi.mock('../../../../i18n/translations', async () => ({text: (await import('svelte/store')).writable((key: string) => key)}));
vi.mock('../../../../i18n/setup', () => ({getCurrentLanguage: () => 'en'}));
vi.mock('../../../../config/api', () => ({getApiUrl: () => ''}));
vi.mock('../../../../utils/imageProxy', () => ({proxyImage: (url: string) => url}));
import {getAllMentionResults, getSettingsMemoryEntryResults, searchMentions} from '../mentionSearchService';
beforeEach(() => {fixture.entries = [{id: 'account-memory-mobile', app_id: 'openmates', settings_group: 'memories', item_key: 'Mobile preference', item_value: {title: 'Mobile preference', document: 'Private full document'}, updated_at: 1}];});

// contract-test: supporting surface=gui.web assertions=app-memories.compatibility.legacy-documents,app-memories.conversation.explicit-approval
it('discovers migrated personal Memories in both category and specific-entry mentions', () => {
  const category = getAllMentionResults().find(result => result.type === 'settings_memory');
  expect(category).toMatchObject({entryCount: 1, mentionSyntax: '@memory:openmates:memories:list'});
  expect(getSettingsMemoryEntryResults('openmates', 'memories')).toMatchObject({totalCount: 1, entries: [{displayName: 'Mobile preference', mentionSyntax: '@memory-entry:openmates:memories:account-memory-mobile'}]});
  const result = searchMentions('Mobile preference').find(result => result.type === 'settings_memory_entry');
  expect(result).toMatchObject({entryId: 'account-memory-mobile'});
  expect(JSON.stringify(result)).not.toContain('Private full document');
});

// contract-test: supporting surface=gui.web assertions=app-memories.access.owner-scoped
it('removes migrated suggestions when owner-scoped discovery is invalidated', () => {
  fixture.entries = [];
  expect(getSettingsMemoryEntryResults('openmates', 'memories')).toEqual({entries: [], totalCount: 0});
  expect(getAllMentionResults().filter(result => result.type.startsWith('settings_memory'))).toEqual([]);
});
