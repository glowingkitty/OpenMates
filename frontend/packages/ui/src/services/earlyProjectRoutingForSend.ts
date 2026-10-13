/** A click-scoped fresh Project read for the first admitted personal text turn. */
import { get } from 'svelte/store';
import { authStore } from '../stores/authStore';
import { getActiveTeamContextSnapshot } from '../stores/teamStore';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { listFreshProjectsForSend } from './projectService';

type ProjectRows = Awaited<ReturnType<typeof listFreshProjectsForSend>>;
type Scope = { workspace: string; teamEpoch: number };
type Entry = Scope & {
  chatId: string;
  draftChatId: string | null;
  promise: Promise<ProjectRows>;
};
const pending = new Map<string, Entry>();
const MAX_PENDING_READS = 8;

function personalScope(): Scope | null {
  const workspace = getWorkspaceCacheIdentity();
  const team = getActiveTeamContextSnapshot();
  return workspace && get(authStore).isAuthenticated && !team.teamId
    ? { workspace, teamEpoch: team.epoch } : null;
}

/** Start only for the optimistic row whose chat and message IDs survive the send. */
export function beginFreshProjectRoutingForSend(input: {
  chatId: string;
  messageId: string;
  draftChatId: string | null;
  recordPhase: (phase: string) => void;
}): void {
  const scope = personalScope();
  if (!scope) { input.recordPhase('project_read_gate_scope_unavailable'); return; }
  if (input.draftChatId && input.draftChatId !== input.chatId) {
    input.recordPhase('project_read_gate_draft_mismatch');
    return;
  }
  forgetFreshProjectRoutingForSend(input.messageId);
  if (pending.size >= MAX_PENDING_READS) pending.delete(pending.keys().next().value!);
  input.recordPhase('project_read_begin');
  const promise = listFreshProjectsForSend().then((rows) => {
    input.recordPhase('project_read_ready');
    return rows;
  }, (error: unknown) => {
    input.recordPhase('project_read_failed');
    throw error;
  });
  // The ACK may arrive after the read has failed. Preserve that rejection for
  // the admitted turn while observing it immediately to avoid an unhandled one.
  void promise.catch(() => undefined);
  pending.set(input.messageId, { ...scope, chatId: input.chatId,
    draftChatId: input.draftChatId, promise });
}

/** Move ownership to the sender; open the result only after its exact ACK. */
export function reserveFreshProjectRoutingForSend(chatId: string, messageId: string): (() => Promise<ProjectRows> | null) | null {
  const entry = pending.get(messageId);
  if (!entry) return null;
  pending.delete(messageId);
  if (entry.chatId !== chatId || (entry.draftChatId && entry.draftChatId !== chatId)) return null;
  let consumed = false;
  return () => {
    if (consumed) return null;
    consumed = true;
    const scope = personalScope();
    return scope && entry.workspace === scope.workspace && entry.teamEpoch === scope.teamEpoch
      ? entry.promise : null;
  };
}

/** Called even when local validation, cancellation or transport fails. */
export function forgetFreshProjectRoutingForSend(messageId: string): void {
  pending.delete(messageId);
}
