// Global activity survives sidebar unmounts and concurrent AI responses.
// Existing handlers keep their Map API while mutations publish store updates.
// Typing lifecycle and task lifecycle both contribute to running IDs.
// Per-account chat ancestry is hydrated by the synchronization service.
// Team filtering precedes grouped counts and sidebar presentation.
import { derived, writable } from 'svelte/store';
import type { Chat } from '../types/chat';
import type { RunningChatGroup } from '../utils/chatActivity';
import { aiTypingByChatStore } from './aiTypingStore';
import { activeTeamId } from './teamStore';

export interface ActiveAITask { taskId: string; userMessageId: string }
const taskIds = writable<ReadonlySet<string>>(new Set());
export const activityChats = writable<Chat[]>([]);
export const subChatActivityIds = writable<ReadonlySet<string>>(new Set());

/** Preserve the existing handlers' Map API while publishing every lifecycle change. */
export class ActiveAITaskMap extends Map<string, ActiveAITask> {
  override set(id: string, task: ActiveAITask): this {
    super.set(id, task);
    taskIds.set(new Set(this.keys()));
    return this;
  }
  override delete(id: string): boolean {
    const deleted = super.delete(id);
    if (deleted) taskIds.set(new Set(this.keys()));
    return deleted;
  }
  override clear(): void {
    super.clear();
    taskIds.set(new Set());
  }
}

export const runningChatIds = derived([taskIds, aiTypingByChatStore, subChatActivityIds], ([$tasks, $typing, $subChats]) =>
  new Set([...$tasks, ...Object.keys($typing), ...$subChats]));
// The shared Rust chatState unit groups running chats; there is no TypeScript fallback.
/** Latest-wins asynchronous derivation: an older Worker answer never overwrites a newer one. */
function asyncDerived<T>(initial: T, compute: (chats: Chat[], ids: ReadonlySet<string>) => Promise<T>) {
  return derived([activityChats, runningChatIds, activeTeamId], ([$chats, $ids, $team], set) => {
    let stale = false;
    void compute($chats.filter(chat => (chat.team_id ?? null) === $team), $ids).then(value => { if (!stale) set(value); });
    return () => { stale = true; };
  }, initial);
}
export const runningChatGroups = asyncDerived<RunningChatGroup<Chat>[]>([], async (chats, ids) => (await import('../services/rustCore/chatState/rustTransitions')).rustAggregateRunningChats(chats, ids));
export const activeChatCount = derived(runningChatGroups, groups => groups.length);
export const processingChatIds = asyncDerived<Set<string>>(new Set(), async (chats, ids) => (await import('../services/rustCore/chatState/rustTransitions')).rustProcessingAncestorIds(chats, ids));
