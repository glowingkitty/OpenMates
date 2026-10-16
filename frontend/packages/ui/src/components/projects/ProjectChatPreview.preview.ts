import type { ProjectItemViewModel } from '../../services/projectService';
import type { ProjectChatPresentation } from '../../services/projectChatPreviewService';

export const item: ProjectItemViewModel = {
  project_item_id: 'preview-chat-link', item_type: 'chat', target_id: '7341f901-c361-4077-bdad-ae87aaf1faee',
  displayName: 'Earlier title', metadata: {}, encrypted: {
    project_item_id: 'preview-chat-link', item_type: 'chat', target_id_hash: 'synthetic-hash', target_id_encrypted: 'synthetic-ciphertext', created_at: 1, updated_at: 1, position: 0,
  },
};
export const presentation: ProjectChatPresentation = { title: 'Website launch', summary: 'Plan launch copy, research the audience and choose the next steps.', category: 'marketing', icon: 'megaphone', teamId: null };
const fixture = { item, presentation };
export default fixture;
export const variants = {
  running: { ...fixture, processing: true },
  list: { ...fixture, viewMode: 'list' },
  unavailable: { ...fixture, presentation: null },
  long: { ...fixture, presentation: { ...presentation, title: 'A very long chat title with a deeply detailed discussion of an upcoming international website launch and its many decisions', summary: 'Long summary '.repeat(40) } },
  team: { ...fixture, presentation: { ...presentation, teamId: 'synthetic-team' } },
};
