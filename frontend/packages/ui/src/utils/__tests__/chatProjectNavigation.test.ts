import { describe, expect, it } from 'vitest';
import { projectBreadcrumbs, projectFolderChatIds, locationHasRunningChats, type SidebarProject } from '../chatProjectNavigation';
const project: SidebarProject = { id: 'launch', name: 'Website launch', folders: [
  { id: 'marketing', hash: 'm', parentHash: null, name: 'Marketing' },
  { id: 'campaigns', hash: 'c', parentHash: 'm', name: 'Campaigns' },
  { id: 'copy', hash: 'd', parentHash: 'c', name: 'Launch copy' },
  { id: 'other', hash: 'o', parentHash: null, name: 'Other' },
], chats: [{ id: 'root', chatId: 'overview', folderHash: null }, { id: 'linked', chatId: 'headlines', folderHash: 'd' }] };
describe('nested chat project navigation', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable
  it('starts the breadcrumb with the actual project and preserves every ancestor', () => {
    expect(projectBreadcrumbs(project, 'copy').map(crumb => crumb.name)).toEqual(['Website launch', 'Marketing', 'Campaigns', 'Launch copy']);
    expect(projectBreadcrumbs(project, 'marketing').map(crumb => crumb.name)).toEqual(['Website launch', 'Marketing']);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable
  it('lists only immediate chat contents while propagating activity recursively', () => {
    expect([...projectFolderChatIds(project, 'marketing')]).toEqual([]);
    expect([...projectFolderChatIds(project, 'copy')]).toEqual(['headlines']);
    for (const id of [null, 'marketing', 'campaigns', 'copy']) expect(locationHasRunningChats(project, id, new Set(['headlines']))).toBe(true);
    expect(locationHasRunningChats(project, 'other', new Set(['headlines']))).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable
  it('does not treat an unavailable folder as the project root', () => {
    expect([...projectFolderChatIds(project, 'deleted')]).toEqual([]);
  });
});
