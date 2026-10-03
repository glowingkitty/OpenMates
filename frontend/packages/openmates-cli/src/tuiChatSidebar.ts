// One selectable row model drives terminal rendering and keyboard activation.
// Running descendants group under their parent at every folder depth.
// Project contents reuse encrypted client decoding without source file reads.
// Ancestry is cycle-safe and rows never gain depth-based indentation.
// Snapshots contain authorized IDs; names are client-decrypted.
import { createHash, randomUUID } from 'node:crypto';
import type { OpenMatesClient, ChatListItem } from './client.js';
import type { TuiState } from './tuiRenderer.js';
import { loadTuiProjects, loadTuiProject, buildProjectForm, submitProjectForm, type TuiProject } from './tuiProjectsWorkspace.js';
import { encryptWithAesGcmCombined } from './crypto.js';
import { aggregateRunningChats, processingAncestorIds } from '../../ui/src/utils/chatActivity.js';
import { projectBreadcrumbs, projectFolderChatIds, locationHasRunningChats, type SidebarProject } from '../../ui/src/utils/chatProjectNavigation.js';
import { cells, truncateCells } from './tuiText.js';
import { sortChats } from '../../ui/src/components/chats/utils/chatSortUtils.js';
import { chatTimeGroupKey, CHAT_TIME_GROUPS } from '../../ui/src/utils/chatTimeGroups.js';
export type ChatSidebarRow = { kind: 'section' | 'new' | 'chat' | 'project' | 'folder' | 'up' | 'path' | 'choose' | 'create';
  label: string; chatId?: string; projectId?: string; folderId?: string | null; running?: boolean };

function rowKey(row: ChatSidebarRow): string {
  return [row.kind, row.chatId ?? '', row.projectId ?? '', row.folderId ?? ''].join(':');
}
export function updateTuiChatSidebar(state: TuiState, update: () => void): void {
  const selected = tuiChatSidebarRows(state)[state.sidebarIndex];
  update();
  if (state.workspace !== 'chats' || state.focus !== 'sidebar') return;
  const rows = tuiChatSidebarRows(state);
  const index = selected ? rows.findIndex(row => rowKey(row) === rowKey(selected)) : -1;
  state.sidebarIndex = index >= 0 ? index : Math.max(0, Math.min(state.sidebarIndex, rows.length - 1));
  if (rows[state.sidebarIndex]?.kind === 'section') moveTuiChatSidebarSelection(state, 0);
}

export function runningTuiChatGroups(state: TuiState): Array<{ chat: ChatListItem; activeSubChatCount: number }> {
  const chats = new Map([...state.recentChats, ...state.activityChats].map(chat => [chat.id, chat]));
  return aggregateRunningChats([...chats.values()].map(chat => ({ chat_id: chat.id, parent_id: chat.parentId, is_hidden_candidate: chat.isHiddenCandidate || chat.isHidden })), new Set(state.runningChatIds))
    .map(group => ({ ...group, chat: chats.get(group.chat.chat_id)! }));
}
function sortTuiChats(chats: ChatListItem[], serverIds: string[]): ChatListItem[] {
  const records = new Map(chats.map(chat => [chat.id, chat]));
  return sortChats(chats.map(chat => ({chat_id: chat.id, pinned: chat.pinned,
    encrypted_draft_md: chat.hasDraft ? 'saved' : null, last_edited_overall_timestamp: chat.updatedAt,
    updated_at: chat.metadataUpdatedAt})) as Parameters<typeof sortChats>[0], serverIds).map(chat => records.get(chat.chat_id)!);
}
export function tuiSidebarProjects(state: TuiState): SidebarProject[] {
  return state.chatSidebarProjects.filter(project => !project.archived).map(project => ({ id: project.id, name: project.name,
    folders: project.folders.map(folder => ({ id: folder.id, name: folder.name,
      hash: createHash('sha256').update(folder.id).digest('hex'), parentHash: folder.parentHash ?? null })),
    chats: project.items.filter(item => item.type === 'chat').map(item => ({ id: item.id, chatId: item.targetId,
      folderHash: item.folderId ? createHash('sha256').update(item.folderId).digest('hex') : null })),
  }));
}
export function tuiChatBreadcrumb(state: TuiState, width = 23): string | null {
  const location = state.chatSidebarLocation;
  const project = tuiSidebarProjects(state).find(project => project.id === location?.projectId);
  if (!project || !location) return null;
  const crumbs = projectBreadcrumbs(project, location.folderId);
  if (crumbs.length === 1) return truncateCells(project.name, width);
  const separator = crumbs.length > 2 ? ' › … › ' : ' › ';
  const current = crumbs.at(-1)!.name, budget = Math.max(2, width - cells(separator));
  if (cells(project.name) + cells(current) <= budget) return `${project.name}${separator}${current}`;
  const leafWidth = Math.min(cells(current), Math.max(1, budget - Math.min(cells(project.name), Math.ceil(budget / 2))));
  return `${truncateCells(project.name, budget - leafWidth)}${separator}${truncateCells(current, leafWidth)}`;
}
export function tuiChatSidebarRows(state: TuiState): ChatSidebarRow[] {
  const groups = runningTuiChatGroups(state);
  const records = [...state.recentChats, ...state.activityChats].map(chat => ({ chat_id: chat.id, parent_id: chat.parentId, is_hidden_candidate: chat.isHiddenCandidate || chat.isHidden }));
  const running = processingAncestorIds(records, new Set(state.runningChatIds));
  const rows: ChatSidebarRow[] = groups.map(group => ({ kind: 'chat', chatId: group.chat.id, running: true,
    label: `${group.chat.title || 'Untitled chat'}${group.activeSubChatCount ? ` (${group.activeSubChatCount} ${group.activeSubChatCount === 1 ? 'subchat' : 'subchats'})` : ''}` }));
  rows.push({ kind: 'new', label: '+ New chat' });
  if (state.chatProjectOperation) rows.push({ kind: 'create', label: '+ Create new project' });
  const projects = tuiSidebarProjects(state), location = state.chatSidebarLocation;
  const project = projects.find(project => project.id === location?.projectId);
  let contents: Set<string> | null = null;
  if (project && location) {
    const crumbs = projectBreadcrumbs(project, location.folderId);
    rows.push({ kind: 'up', label: '‹ Up one level', projectId: project.id, folderId: crumbs.length > 1 ? crumbs[crumbs.length - 2].id : undefined });
    if (crumbs.length > 2) rows.push({ kind: 'path', label: '… Show full path' });
    if (state.chatSidebarAncestors) for (const crumb of crumbs) rows.push({ kind: 'folder', label: crumb.name, projectId: project.id, folderId: crumb.id });
    if (state.chatProjectOperation) rows.push({ kind: 'choose', label: state.chatProjectOperation.mode === 'move' ? 'Move here' : 'Add here', projectId: project.id, folderId: location.folderId });
    const hash = project.folders.find(folder => folder.id === location.folderId)?.hash ?? null;
    rows.push(...project.folders.filter(folder => folder.parentHash === hash).map(folder => ({ kind: 'folder' as const,
      label: folder.name, projectId: project.id, folderId: folder.id, running: locationHasRunningChats(project, folder.id, running) })));
    contents = projectFolderChatIds(project, location.folderId);
  } else rows.push(...projects.map(project => ({ kind: 'project' as const, label: project.name, projectId: project.id,
    running: locationHasRunningChats(project, null, running) })));
  const organized = new Set(projects.flatMap(project => project.chats.map(chat => chat.chatId)));
  // Sync records include drafts; minimal linked metadata must not overwrite them.
  const combined = new Map([...state.sidebarLinkedChats, ...state.recentChats].map(chat => [chat.id, chat]));
  const candidates = new Map([...combined.values()].filter(chat => !chat.isHiddenCandidate && !chat.isHidden).map(chat => [chat.id, chat]));
  if (contents && location) for (const item of state.chatSidebarProjects.find(project => project.id === location.projectId)?.items ?? []) {
    const verified = candidates.get(item.targetId);
    if (item.type === 'chat' && contents.has(item.targetId) && verified && !verified.title)
      candidates.set(item.targetId, { ...verified, title: item.name });
  }
  if (!state.chatProjectOperation) {
    const chats = [...candidates.values()].filter(chat => !running.has(chat.id) &&
      (contents ? contents.has(chat.id) : !chat.parentId && !chat.isSubChat && !organized.has(chat.id)));
    const ordered = sortTuiChats(chats, state.recentChats.map(chat => chat.id));
    const groups = new Map<string, ChatListItem[]>();
    for (const chat of ordered) {
      const key = chatTimeGroupKey(chat.updatedAt);
      const group = groups.get(key) ?? [];
      group.push(chat); groups.set(key, group);
    }
    const keys = [...CHAT_TIME_GROUPS.filter(key => groups.has(key)), ...[...groups.keys()].filter(key => !CHAT_TIME_GROUPS.some(standard => standard === key))];
    for (const key of keys) {
      const label = ({today: 'Today', yesterday: 'Yesterday', previous_7_days: 'Previous 7 days', previous_30_days: 'Previous 30 days'} as Record<string, string>)[key]
        ?? new Date(Number(key.split('_')[1]), Number(key.split('_')[2]) - 1).toLocaleDateString('en', {month: 'long', year: 'numeric'});
      rows.push({kind: 'section', label});
      rows.push(...groups.get(key)!.map(chat => ({kind: 'chat' as const, chatId: chat.id,
        label: `${chat.pinned ? '★ ' : ''}${chat.title || chat.draftPreview || 'Untitled chat'}${chat.hasDraft ? ' [Draft]' : ''}`})));
    }
  }
  return rows;
}
/** Headers are visual rows, never keyboard targets. Wheel follows the same model. */
export function moveTuiChatSidebarSelection(state: TuiState, amount: number, edge?: 'first' | 'last'): void {
  const rows = tuiChatSidebarRows(state), selectable = rows.map((row, index) => row.kind === 'section' ? -1 : index).filter(index => index >= 0);
  const selected = Math.max(0, selectable.indexOf(state.sidebarIndex));
  const next = edge === 'first' ? 0 : edge === 'last' ? selectable.length - 1 : Math.max(0, Math.min(selectable.length - 1, selected + amount));
  state.sidebarIndex = selectable[next] ?? 0;
}
export async function refreshTuiChatSidebar(state: TuiState, client: OpenMatesClient, render: () => void, includeProjects = false): Promise<void> {
  if (!state.signedIn) return;
  const activityRequest = ++state.chatActivityLoadVersion;
  const projectRequest = includeProjects ? ++state.chatSidebarLoadVersion : state.chatSidebarLoadVersion;
  const team = typeof client.getActiveTeamId === 'function' ? client.getActiveTeamId() : null;
  const master = typeof client.getMasterKeyBytes === 'function' ? Buffer.from(client.getMasterKeyBytes()) : null;
  const current = () => state.signedIn && (typeof client.getActiveTeamId !== 'function' || client.getActiveTeamId() === team) &&
    (!master || master.equals(Buffer.from(client.getMasterKeyBytes())));
  if (typeof client.getChatActivity === 'function') {
    try {
      const activity = await client.getChatActivity();
      if (current() && activityRequest === state.chatActivityLoadVersion) { updateTuiChatSidebar(state, () => { state.runningChatIds = activity.ids; state.activityChats = activity.chats; }); render(); }
    } catch { if (current()) { state.status = 'Running chat status unavailable.'; render(); } }
  }
  if (includeProjects && typeof client.listProjects === 'function') {
    const summaries = (await loadTuiProjects(client)).filter(project => !project.archived), projects: TuiProject[] = [];
    for (let start = 0; start < summaries.length; start += 4) projects.push(...await Promise.all(summaries.slice(start, start + 4).map(project => loadTuiProject(client, project.id, true))));
    const linkedIds = [...new Set(projects.flatMap(project => project.items.filter(item => item.type === 'chat').map(item => item.targetId)))];
    const linkedChats = typeof client.getSidebarChats === 'function' ? await client.getSidebarChats(linkedIds) : [];
    if (current() && projectRequest === state.chatSidebarLoadVersion) { updateTuiChatSidebar(state, () => { state.chatSidebarProjects = projects; state.sidebarLinkedChats = linkedChats; }); render(); }
  }
}

export async function placeTuiChats(state: TuiState, client: OpenMatesClient, chatIds: string[], location: { projectId: string; folderId: string | null }, mode: 'add' | 'move'): Promise<void> {
  const context = { teamId: client.getActiveTeamId() }, master = Buffer.from(client.getMasterKeyBytes());
  const fence = () => { if (!state.signedIn || context.teamId !== client.getActiveTeamId() || !master.equals(Buffer.from(client.getMasterKeyBytes()))) throw new Error('Chat workspace changed'); };
  const destination = await loadTuiProject(client, location.projectId, true);
  if (location.folderId && !destination.folders.some(folder => folder.id === location.folderId)) throw new Error('Folder unavailable');
  for (const chatId of chatIds) {
    fence();
    const existing = destination.items.find(item => item.type === 'chat' && item.targetId === chatId);
    if (existing) {
      if ((existing.folderId ?? null) !== location.folderId) await client.moveProjectItemToFolder(destination.id, existing.id, location.folderId, context);
    } else {
      const title = [...state.recentChats, ...state.activityChats].find(chat => chat.id === chatId)?.title || 'Untitled chat';
      const timestamp = Math.floor(Date.now() / 1000);
      const payload = { project_item_id: randomUUID(), folder_id: location.folderId,
        item_type: 'chat' as const, target_id: chatId, target_id_encrypted: await encryptWithAesGcmCombined(chatId, destination.projectKey),
        encrypted_display_name: await encryptWithAesGcmCombined(title, destination.projectKey), created_at: timestamp, updated_at: timestamp, position: timestamp };
      fence(); await client.createProjectItem(destination.id, payload, context);
    }
  }
  if (mode === 'move') for (const source of state.chatSidebarProjects.filter(project => project.id !== destination.id)) {
    for (const chatId of chatIds.filter(id => source.items.some(item => item.type === 'chat' && item.targetId === id))) {
      fence(); await client.deleteProjectItemByTarget(source.id, 'chat', chatId, context);
    }
  }
}

export async function createTuiChatProject(state: TuiState, client: OpenMatesClient, chatIds: string[]): Promise<string> {
  if (!state.signedIn || !chatIds.length) throw new Error('Choose a saved chat first.');
  const context = client.getActiveTeamId(), master = Buffer.from(client.getMasterKeyBytes());
  const titles = chatIds.slice(0, 8).map(id => [...state.recentChats, ...state.activityChats, ...state.sidebarLinkedChats].find(chat => chat.id === id)?.title?.slice(0, 200) || 'Untitled chat');
  const plan = await client.planProjectAsk({ instruction: 'Name a new project from chat titles.', chatTitles: titles });
  const proposed = plan.proposed_project as { name?: string } | undefined, name = proposed?.name?.trim();
  if (!name || name.length > 200) throw new Error('Could not generate a project title.');
  if (context !== client.getActiveTeamId() || !master.equals(Buffer.from(client.getMasterKeyBytes()))) throw new Error('Chat workspace changed');
  const form = buildProjectForm(); form.fields.find(field => field.name === 'name')!.value = name;
  const project = await submitProjectForm(client, form, true);
  await placeTuiChats(state, client, chatIds, { projectId: project.id, folderId: null }, 'move');
  return project.id;
}
