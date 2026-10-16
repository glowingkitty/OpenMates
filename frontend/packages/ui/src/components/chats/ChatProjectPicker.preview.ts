// Isolated picker fixtures drive the production dialog and navigator.
// Server mutations are injected callbacks; route tests verify encrypted APIs.
// Successful selections are exposed as events for component assertions.
// The error variant retains the user's selection and displays a retryable error.
// No account or real chat/project is read or changed by these fixtures.
import type { Chat } from '../../types/chat';
import type { ProjectViewModel } from '../../services/projectService';
import { project } from './ChatProjectNavigator.preview';
const selection = (kind: string, detail: unknown) => window.dispatchEvent(new CustomEvent(`preview-project-${kind}`, { detail }));
const fixture = {
  initialChats: [{ chat_id: 'headlines', title: 'Launch headlines' } as Chat],
  loadIndex: async () => [project],
  placeChats: async (_chats: Chat[], location: unknown) => { selection('selected', location); },
  createProject: async () => ({ project_id: 'created', name: 'Website launch' } as ProjectViewModel),
  createFolder: async () => {},
  openProject: (id: string) => { selection('opened', id); },
};
export default fixture;
export const variants = {
  error: { ...fixture, placeChats: async () => { throw new Error('Fixture association failed'); } },
  empty: { ...fixture, loadIndex: async () => [] },
};
