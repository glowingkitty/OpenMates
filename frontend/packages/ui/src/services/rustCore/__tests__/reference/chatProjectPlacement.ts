// Test double for the chatState unit's placement answers
// (packages/openmates-rust/src/web_chat_state/placement.rs). The web app no longer
// runs this TypeScript; service tests use it to answer `placementOrganizable` and
// `placementPlan` the way the core does, so they can exercise HTTP order and fences.
import { projectFolderChatIds } from '../../../../utils/chatProjectNavigation';
import type { OrganizableInput, PlacementInput, PlacementPlan, PlacementStep } from '../../../../utils/chatProjectPlacement';

/** Core answer for `placementOrganizable`. */
export function chatsOrganizable(input: OrganizableInput): { ok: boolean } {
  const { chats, teamId } = input;
  return { ok: !(!chats.length || chats.some(chat => chat.incognito || chat.sharedByOthers || chat.demo ||
    chat.legal || chat.public || chat.teamId !== teamId)) };
}

/** Core answer for `placementPlan`. */
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
