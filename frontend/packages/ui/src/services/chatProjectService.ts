// Chat organization reuses encrypted Projects and existing AI naming.
// Only bounded chat titles reach inference on an explicit user action.
// Account and team fences isolate asynchronous cache reads and mutations.
// Move persists destination links before removing old associations.
// New chat groups defer file policy selection and never enable file focus.
import type { Chat } from '../types/chat';
import { isDemoChat, isLegalChat, isPublicChat } from '../demo_chats';
import type { ChatProjectLocation, SidebarProject } from '../utils/chatProjectNavigation';
import { projectFolderChatIds } from '../utils/chatProjectNavigation';
import { computeSHA256 } from '../message_parsing/utils';
import { getApiEndpoint } from '../config/api';
import { getActiveTeamContextSnapshot } from '../stores/teamStore';
import { chatMetadataCache } from './chatMetadataCache';
import { broadcastProjectFilesChanged } from './projectBrowserEvents';
import { WorkspaceQueryCache, getWorkspaceCacheIdentity, WorkspaceCacheDiscardedError } from './workspaceQueryCache';
import { listProjects, getProject, getProjectContents, addExistingTargetToProject, moveProjectItemToFolder, removeChatFromProject,
  createProject, createFolder, type ProjectViewModel } from './projectService';

const indexCache = new WorkspaceQueryCache<SidebarProject[]>({ ttlMs: 30_000, maxEntries: 2 });
export async function loadChatProjectIndex(force = false): Promise<SidebarProject[]> {
  return indexCache.load('sidebar', async () => {
    const context = { teamId: getActiveTeamContextSnapshot().teamId };
    const projects = await listProjects({ ...context, force });
    const result: SidebarProject[] = [];
    // Limit parallel decryptions/requests for accounts with many projects.
    for (let start = 0; start < projects.length; start += 4) {
      result.push(...await Promise.all(projects.slice(start, start + 4).map(async project => {
      const { folders, items } = await getProjectContents(project, context, true);
      return {
        id: project.project_id, name: project.name,
        folders: await Promise.all(folders.map(async folder => ({ id: folder.folder_id,
          hash: await computeSHA256(folder.folder_id), parentHash: folder.parentHash, name: folder.name }))),
        chats: items.filter(item => item.item_type === 'chat').map(item => ({
          id: item.project_item_id, chatId: item.target_id, folderHash: item.encrypted.hashed_folder_id ?? null,
        })),
      };
      })));
    }
    return result;
  }, { force });
}

export function invalidateChatProjectIndex(): void { indexCache.invalidate(); }

async function chatName(chat: Chat): Promise<string> {
  const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
  return metadata?.title || chat.title || 'Untitled chat';
}

/** Explicit user action submits only bounded titles, never transcripts or keys. */
export async function suggestChatProjectName(chats: Chat[]): Promise<string> {
  const identity = getWorkspaceCacheIdentity();
  const titles = await Promise.all(chats.slice(0, 8).map(async chat => (await chatName(chat)).slice(0, 200)));
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const response = await fetch(getApiEndpoint('/v1/projects/ask/plan'), {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction: 'Name a new project from chat titles.', chat_titles: titles }),
  });
  if (!response.ok) throw new Error('Could not generate the project title');
  const data = await response.json() as { proposed_project?: { name?: string } };
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  const name = data.proposed_project?.name?.trim();
  if (!name || name.length > 200) throw new Error('The generated project title is invalid');
  return name;
}

export function assertOrganizableChats(chats: Chat[]): void {
  const teamId = getActiveTeamContextSnapshot().teamId;
  if (!chats.length || chats.some(chat => chat.is_incognito || chat.is_shared_by_others ||
    isDemoChat(chat.chat_id) || isLegalChat(chat.chat_id) || isPublicChat(chat.chat_id) || (chat.team_id ?? null) !== teamId)) {
    throw new Error('These chats cannot be organized in this workspace');
  }
}

export async function placeChatsInProject(chats: Chat[], location: ChatProjectLocation, mode: 'add' | 'move' = 'add'): Promise<void> {
  assertOrganizableChats(chats);
  const identity = getWorkspaceCacheIdentity();
  const context = { teamId: getActiveTeamContextSnapshot().teamId };
  const index = await loadChatProjectIndex(true);
  const project = await getProject(location.projectId, context);
  const destination = index.find(project => project.id === location.projectId);
  if (!destination) throw new Error('Project is unavailable');
  if (location.folderId && !destination.folders.some(folder => folder.id === location.folderId)) throw new Error('Folder is unavailable');
  try {
  // Persist all destination associations before removing any source association.
  for (const chat of chats) {
    if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
    if (projectFolderChatIds(destination, location.folderId).has(chat.chat_id)) continue;
    const existing = destination.chats.find(item => item.chatId === chat.chat_id);
    if (existing) await moveProjectItemToFolder(project, existing.id, location.folderId, context);
    else {
      const name = await chatName(chat);
      if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
      await addExistingTargetToProject(project, chat.chat_id, 'chat', name, location.folderId ?? undefined, {}, context);
    }
  }
  if (mode === 'move') for (const source of index.filter(candidate => candidate.id !== project.project_id)) {
    for (const chat of chats.filter(chat => source.chats.some(item => item.chatId === chat.chat_id))) {
      if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
      await removeChatFromProject(source.id, chat.chat_id, context);
    }
  }
  } finally {
  invalidateChatProjectIndex();
  broadcastProjectFilesChanged(project.project_id);
  }
}

export async function createChatProject(chats: Chat[]): Promise<ProjectViewModel> {
  assertOrganizableChats(chats);
  const identity = getWorkspaceCacheIdentity();
  const context = { teamId: getActiveTeamContextSnapshot().teamId };
  const name = await suggestChatProjectName(chats);
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  // File permissions stay pending until the user explicitly chooses a policy.
  const project = await createProject(name, null, context);
  invalidateChatProjectIndex();
  await placeChatsInProject(chats, { projectId: project.project_id, folderId: null }, 'move');
  return project;
}

export async function createChatProjectFolder(location: ChatProjectLocation, name: string): Promise<void> {
  const identity = getWorkspaceCacheIdentity(), context = { teamId: getActiveTeamContextSnapshot().teamId };
  const project = await getProject(location.projectId, context);
  if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
  await createFolder(project, name, location.folderId ?? undefined, context);
  invalidateChatProjectIndex();
  broadcastProjectFilesChanged(project.project_id);
}

export function requestChatProjectPicker(chats: Chat[], create = false, mode: 'add' | 'move' = 'add'): void {
  window.dispatchEvent(new CustomEvent('openmates-chat-project-picker', { detail: { chats, create, mode } }));
}

export function openChatProjectScreen(projectId: string): void {
  window.location.hash = `project-id=${encodeURIComponent(projectId)}`;
}
