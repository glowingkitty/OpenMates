// Project links keep their original chat lifecycle and authorized local metadata.
// Hydrate metadata only, with the same identity fences as sidebar activity.
import { chatDB } from './db';
import { chatMetadataCache, CHAT_METADATA_KEY_READY_EVENT } from './chatMetadataCache';
import { chatSyncService } from './chatSyncService';
import { getActiveTeamContextSnapshot } from '../stores/teamStore';
import { WorkspaceQueryCache, getWorkspaceCacheIdentity, WorkspaceCacheDiscardedError } from './workspaceQueryCache';

export interface ProjectChatPresentation {
  title: string | null;
  summary: string | null;
  category: string;
  icon: string;
  teamId: string | null;
}

const cache = new WorkspaceQueryCache<ProjectChatPresentation | null>({ ttlMs: 30_000, maxEntries: 128 });
// Invalidate once per sync event, before mounted cards request the new metadata.
// Cancelling the old pending read also prevents it from overwriting a deletion.
const invalidateChangedChat = (event: Event): void => {
  const detail = (event as CustomEvent<{ chat_id?: string; chatId?: string }>).detail;
  const id = detail?.chat_id ?? detail?.chatId;
  if (id) cache.invalidate(id);
};
chatSyncService.addEventListener('chatUpdated', invalidateChangedChat);
chatSyncService.addEventListener('chatDeleted', invalidateChangedChat);
if (typeof window !== 'undefined') window.addEventListener(CHAT_METADATA_KEY_READY_EVENT, invalidateChangedChat);
let hydration: { identity: string; ids: Set<string>; promise: Promise<void> } | null = null;

function hydrate(id: string, identity: string): Promise<void> {
  if (!hydration || hydration.identity !== identity) {
    const batch = { identity, ids: new Set<string>(), promise: Promise.resolve() };
    batch.promise = Promise.resolve().then(async () => {
      if (hydration === batch) hydration = null;
      if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
      await chatSyncService.hydrateSidebarChats([...batch.ids]);
    });
    hydration = batch;
  }
  hydration.ids.add(id);
  return hydration.promise;
}

export function loadProjectChatPresentation(chatId: string, force = false): Promise<ProjectChatPresentation | null> {
  return cache.load(chatId, async () => {
    const identity = getWorkspaceCacheIdentity();
    if (!identity) throw new WorkspaceCacheDiscardedError();
    const teamId = getActiveTeamContextSnapshot().teamId;
    let chat = await chatDB.getChat(chatId);
    if (!chat) {
      await hydrate(chatId, identity);
      chat = await chatDB.getChat(chatId);
    }
    if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
    if (!chat || chat.is_hidden || chat.is_hidden_candidate || chat.is_incognito || (chat.team_id ?? null) !== teamId) return null;
    const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
    if (identity !== getWorkspaceCacheIdentity()) throw new WorkspaceCacheDiscardedError();
    if (!metadata) return null;
    return { title: metadata.title, summary: metadata.summary, category: metadata.category || 'general_knowledge',
      icon: metadata.icon || '', teamId };
  }, { force: force || !cache.isFresh(chatId) });
}
