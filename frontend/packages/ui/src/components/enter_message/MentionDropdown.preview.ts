import {getOpenMatesMentionResult, type SettingsMemoryEntryMentionResult, type SettingsMemoryMentionResult} from './services/mentionSearchService';
import {get} from 'svelte/store';
import {settingsDeepLink} from '../../stores/settingsDeepLinkStore';

// Synthetic migrated discovery exercises the production selection controls.
// The live discovery service and owner invalidation have separate unit coverage.
const entry: SettingsMemoryEntryMentionResult = {
  id: 'openmates:memories:account-memory-preview-mobile', type: 'settings_memory_entry',
  displayName: 'Mobile preference', mentionDisplayName: 'Openmates-Memories-Mobile-Preference',
  subtitle: '', icon: 'heart.svg', searchTerms: ['mobile', 'preference'],
  mentionSyntax: '@memory-entry:openmates:memories:account-memory-preview-mobile',
  appId: 'openmates', appIcon: 'heart.svg', memoryCategoryId: 'memories',
  entryId: 'account-memory-preview-mobile', entryTitle: 'Mobile preference',
};
const category: SettingsMemoryMentionResult = {
  id: 'openmates:memories', type: 'settings_memory', displayName: 'memories.manage',
  mentionDisplayName: 'Openmates-Memories', subtitle: 'memories.source_personal',
  icon: 'heart.svg', searchTerms: ['memories'], mentionSyntax: '@memory:openmates:memories:list',
  appId: 'openmates', appIcon: 'heart.svg', memoryCategoryId: 'memories', memoryType: 'list', entryCount: 1,
};
export const layout = 'fill';
export default {
  show: true, query: 'Mobile preference', positionY: 16, positionDirection: 'below',
  source: {
    search: (query: string, _limit?: number, teamActive = false) => teamActive
      ? [getOpenMatesMentionResult()]
      : query === 'memories' ? [category] : [entry],
    projects: async () => [],
    entries: () => ({entries: [entry], totalCount: 1}),
  },
  onselect: (result: unknown) => {
    window.dispatchEvent(new CustomEvent('preview-memory-selected', {detail: result}));
    window.dispatchEvent(new CustomEvent('preview-mention-selected', {detail: result}));
  },
  onclose: () => {
    window.dispatchEvent(new Event('preview-memory-closed'));
    window.dispatchEvent(new CustomEvent('preview-mention-settings', {detail: get(settingsDeepLink)}));
  },
};
export const variants = {
  category: {query: 'memories'},
  team: {teamActive: true, query: ''},
  teamSearch: {teamActive: true, query: 'OpenMates'},
};
