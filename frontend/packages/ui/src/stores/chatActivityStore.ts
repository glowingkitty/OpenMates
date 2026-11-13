// Global activity survives sidebar unmounts and concurrent AI responses.
// Existing handlers keep their Map API while mutations publish store updates.
// Typing lifecycle and task lifecycle both contribute to running IDs.
// Per-account chat ancestry is hydrated by the synchronization service.
// Team filtering precedes grouped counts and sidebar presentation.
import { derived, writable } from 'svelte/store';
import type { Chat } from '../types/chat';
import { aggregateRunningChats, processingAncestorIds, type RunningChatGroup } from '../utils/chatActivity';
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
// Opt-in shared Rust core (build-time VITE_OPENMATES_RUST_CORE === '1'): the chatState unit groups
// running chats and there is no TypeScript fallback; default builds keep the synchronous derived stores.
const RUST_ACTIVITY: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1'
  && !(typeof localStorage !== 'undefined' && localStorage.getItem('openmates_rust_core_chatstate') === 'ts');
/** Latest-wins asynchronous derivation: an older Worker answer never overwrites a newer one. */
function asyncDerived<T>(initial: T, compute: (chats: Chat[], ids: ReadonlySet<string>) => Promise<T>) {
  return derived([activityChats, runningChatIds, activeTeamId], ([$chats, $ids, $team], set) => {
    let stale = false;
    void compute($chats.filter(chat => (chat.team_id ?? null) === $team), $ids).then(value => { if (!stale) set(value); });
    return () => { stale = true; };
  }, initial);
}
export const runningChatGroups = RUST_ACTIVITY
  ? asyncDerived<RunningChatGroup<Chat>[]>([], async (chats, ids) => (await import('../services/rustCore/chatState/rustTransitions')).rustAggregateRunningChats(chats, ids))
  : derived([activityChats, runningChatIds, activeTeamId], ([$chats, $ids, $team]) =>
  aggregateRunningChats($chats.filter(chat => (chat.team_id ?? null) === $team), $ids));
export const activeChatCount = derived(runningChatGroups, groups => groups.length);
export const processingChatIds = RUST_ACTIVITY
  ? asyncDerived<Set<string>>(new Set(), async (chats, ids) => (await import('../services/rustCore/chatState/rustTransitions')).rustProcessingAncestorIds(chats, ids))
  : derived([activityChats, runningChatIds, activeTeamId], ([$chats, $ids, $team]) =>
  processingAncestorIds($chats.filter(chat => (chat.team_id ?? null) === $team), $ids));
