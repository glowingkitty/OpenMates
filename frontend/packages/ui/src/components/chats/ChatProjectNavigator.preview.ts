export const project = { id: 'launch', name: 'Website launch', folders: [
  { id: 'marketing', hash: 'marketing-hash', parentHash: null, name: 'Marketing' },
  { id: 'campaigns', hash: 'campaigns-hash', parentHash: 'marketing-hash', name: 'Campaigns' },
  { id: 'copy', hash: 'copy-hash', parentHash: 'campaigns-hash', name: 'Launch copy' },
  { id: 'drafts', hash: 'drafts-hash', parentHash: 'copy-hash', name: 'Drafts' },
], chats: [{ id: 'chat-link', chatId: 'headlines', folderHash: 'drafts-hash' }] };
const fixture = { projects: [project], location: null, runningIds: new Set(['headlines']),
  onDropChat: () => {},
  onCreateFolder: async (location: unknown, name: string) => { window.dispatchEvent(new CustomEvent('preview-project-create-folder', { detail: { location, name } })); },
  onOpenProject: () => {} };
export default fixture;
export const variants = {
  deep: { ...fixture, location: { projectId: 'launch', folderId: 'copy' } },
  direct: { ...fixture, location: { projectId: 'launch', folderId: 'marketing' } },
};
