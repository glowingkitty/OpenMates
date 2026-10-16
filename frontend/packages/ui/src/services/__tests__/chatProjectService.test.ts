// Organization tests exercise the multi-step mutation and identity boundaries.
// API primitives are isolated; browser flows cover actual encrypted transport.
// A failed destination write must preserve every old project association.
// Team mismatches must fail before inference or mutation starts.
// Deferred file permissions keep chat grouping separate from file authority.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Chat } from '../../types/chat';
const context = vi.hoisted(() => ({ teamId: null as string | null, epoch: 1 }));
const api = vi.hoisted(() => ({ listProjects: vi.fn(), getProject: vi.fn(), getProjectContents: vi.fn(),
  addExistingTargetToProject: vi.fn(), moveProjectItemToFolder: vi.fn(), removeChatFromProject: vi.fn(),
  createProject: vi.fn(), createFolder: vi.fn() }));
vi.mock('../projectService', () => api);
vi.mock('../../demo_chats', () => ({ isDemoChat: () => false, isLegalChat: () => false, isPublicChat: () => false }));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => path }));
vi.mock('../../message_parsing/utils', () => ({ computeSHA256: async (id: string) => `hash:${id}` }));
vi.mock('../../stores/teamStore', () => ({ getActiveTeamContextSnapshot: () => context }));
vi.mock('../../stores/userProfile', async () => ({ userProfile: (await import('svelte/store')).writable({ user_id: 'organize-test' }) }));
vi.mock('../chatMetadataCache', () => ({ chatMetadataCache: { getDecryptedMetadata: async (chat: Chat) => ({ title: chat.title }) } }));
vi.mock('../projectBrowserEvents', () => ({ broadcastProjectFilesChanged: vi.fn() }));
import { createChatProject, invalidateChatProjectIndex, placeChatsInProject } from '../chatProjectService';
const chat = { chat_id: 'chat-one', title: 'Launch copy', team_id: null } as Chat;
const project = (id: string) => ({ project_id: id, name: id, projectKey: new Uint8Array(32), encrypted: {} });

describe('chat project organization', () => {
  beforeEach(() => {
    vi.resetAllMocks(); context.teamId = null; invalidateChatProjectIndex();
    api.listProjects.mockResolvedValue([project('source'), project('destination')]);
    api.getProject.mockImplementation(async (id: string) => project(id));
    api.getProjectContents.mockImplementation(async (project: { project_id: string }) => ({ folders: [],
      items: project.project_id === 'source' ? [{ project_item_id: 'old-link', item_type: 'chat', target_id: chat.chat_id, encrypted: {} }] : [] }));
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
  it('adds a new association without removing other project links', async () => {
    await placeChatsInProject([chat], { projectId: 'destination', folderId: null });
    expect(api.addExistingTargetToProject).toHaveBeenCalledOnce();
    expect(api.removeChatFromProject).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
  it('persists the destination before removing old links during a move', async () => {
    await placeChatsInProject([chat], { projectId: 'destination', folderId: null }, 'move');
    expect(api.removeChatFromProject).toHaveBeenCalledWith('source', chat.chat_id, { teamId: null });
    expect(api.addExistingTargetToProject.mock.invocationCallOrder[0]).toBeLessThan(api.removeChatFromProject.mock.invocationCallOrder[0]);
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
  it('retains all source links when adding the destination fails', async () => {
    api.addExistingTargetToProject.mockRejectedValue(new Error('Destination unavailable'));
    await expect(placeChatsInProject([chat], { projectId: 'destination', folderId: null }, 'move')).rejects.toThrow('Destination unavailable');
    expect(api.removeChatFromProject).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
  it('rejects cross-workspace chat moves before reading project data', async () => {
    context.teamId = 'team-one';
    await expect(placeChatsInProject([chat], { projectId: 'destination', folderId: null })).rejects.toThrow('workspace');
    expect(api.listProjects).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.organize
  it('uses the active team and pending file permissions for AI-named groups', async () => {
    context.teamId = 'team-one';
    api.createProject.mockResolvedValue(project('destination'));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ proposed_project: { name: 'Website launch' } }));
    await createChatProject([{ ...chat, team_id: 'team-one' }]);
    expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({ instruction: 'Name a new project from chat titles.', chat_titles: ['Launch copy'] });
    expect(api.createProject).toHaveBeenCalledWith('Website launch', null, { teamId: 'team-one' });
    expect(api.addExistingTargetToProject.mock.calls[0].at(-1)).toEqual({ teamId: 'team-one' });
  });
});
