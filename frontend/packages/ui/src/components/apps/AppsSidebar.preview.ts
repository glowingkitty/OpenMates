import type { Chat } from '../../types/chat';
import type { AppsSavedSearch } from '../../services/appsWorkspaceLibraryService';
import type { AppsResultItem } from '../../services/appsWorkspaceResultsService';

const select = (kind: string, id: string) => window.dispatchEvent(new CustomEvent('apps-sidebar-preview-select', { detail: { kind, id } }));
const chat = (id: string, title: string): Chat => ({
  chat_id: id, title, encrypted_title: null, messages_v: 1, title_v: 1,
  last_edited_overall_timestamp: 1792533600, unread_count: 0, created_at: 1792533600, updated_at: 1792533600,
});

export default {
  appName: 'Web',
  savedEmbeds: [{ id: 'saved-embed', title: 'Research quiet coastal towns with reliable train connections, local markets and year-round walking trails for an extended autumn visit' }],
  saved: [{ id: 'saved-search', skill_id: 'search', parameters: {}, saved_at: 1792533600,
    query: 'Find independent bookshops hosting author readings and community workshops near the city centre this month' } satisfies AppsSavedSearch],
  recent: [{ embedId: 'recent-result', appId: 'web', skillId: 'search', createdAt: 1792533600, status: 'finished' } satisfies AppsResultItem],
  resultTitles: { 'recent-result': 'Compare accessible hiking routes with public transport access and detailed seasonal weather information for a family weekend' },
  recentChats: [chat('recent-chat', 'Plan a neighbourhood photography walk with historical landmarks and accessible coffee stops')],
  examples: [chat('example-chat', 'Explore how small urban gardens support pollinators, reduce summer heat and bring neighbours together')],
  onSavedEmbed: (id: string) => select('embed', id),
  onSaved: (item: AppsSavedSearch) => select('saved', item.id),
  onRecent: (item: AppsResultItem) => select('recent', item.embedId),
  onExample: (item: Chat) => select('chat', item.chat_id),
  onClose: () => window.dispatchEvent(new Event('apps-sidebar-preview-close')),
};
export const layout = 'fill';
