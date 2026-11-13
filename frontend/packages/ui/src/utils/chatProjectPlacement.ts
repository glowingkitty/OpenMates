// Pure placement decisions of chat-to-project organisation. The TypeScript
// reference of packages/openmates-rust/src/web_chat_state/placement.rs: flag-off
// chatProjectService runs it, flag-on the chatState unit answers the same facts.
import type { ChatProjectLocation, SidebarProject } from './chatProjectNavigation';
import { projectFolderChatIds } from './chatProjectNavigation';

export interface OrganizableFacts {
  incognito: boolean; sharedByOthers: boolean; demo: boolean; legal: boolean; public: boolean; teamId: string | null;
}
export interface OrganizableInput { chats: OrganizableFacts[]; teamId: string | null }

export type PlacementStep =
  | { kind: 'move'; itemId: string; chatId: string }
  | { kind: 'add'; chatId: string }
  | { kind: 'remove'; sourceId: string; chatId: string };
export interface PlacementInput {
  chatIds: string[]; location: ChatProjectLocation; mode: 'add' | 'move'; index: SidebarProject[];
}
export type PlacementPlan = { error: 'project_unavailable' | 'folder_unavailable' } | { steps: PlacementStep[] };

/** `assertOrganizableChats` predicate. */
export function chatsOrganizable(input: OrganizableInput): { ok: boolean } {
  const { chats, teamId } = input;
  return { ok: !(!chats.length || chats.some(chat => chat.incognito || chat.sharedByOthers || chat.demo ||
    chat.legal || chat.public || chat.teamId !== teamId)) };
}

/** Ordered move/add/remove steps for `placeChatsInProject`. */
export function planPlacement(input: PlacementInput): PlacementPlan {
  const { chatIds, location, mode, index } = input;
  const destination = index.find(project => project.id === location.projectId);
  if (!destination) return { error: 'project_unavailable' };
  if (location.folderId && !destination.folders.some(folder => folder.id === location.folderId)) return { error: 'folder_unavailable' };
  const steps: PlacementStep[] = [];
  for (const chatId of chatIds) {
    if (projectFolderChatIds(destination, location.folderId).has(chatId)) continue;
    const existing = destination.chats.find(item => item.chatId === chatId);
    steps.push(existing ? { kind: 'move', itemId: existing.id, chatId } : { kind: 'add', chatId });
  }
  if (mode === 'move') for (const source of index.filter(candidate => candidate.id !== destination.id)) {
    for (const chatId of chatIds.filter(id => source.chats.some(item => item.chatId === id))) {
      steps.push({ kind: 'remove', sourceId: source.id, chatId });
    }
  }
  return { steps };
}
