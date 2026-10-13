/**
 * Exact-turn fence for optional remote draft cleanup after user admission.
 * The local editor and IndexedDB clear never wait on this fence.
 * Context routing and details release it; reconnect and scope changes cancel it.
 * This module holds only tab-local state, while deferred deletes have a durable
 * offline intent so a tab reload cannot lose the server-side cleanup.
 */
import { getWorkspaceCacheIdentity } from "./workspaceQueryCache";
import { registerWorkspaceCacheClear } from "./workspaceCacheLifecycle";
import { activeTeamContext } from "../stores/teamStore";

// This fences only optional draft cleanup for the exact admitted personal turn.
// It ends at context dispatch, never at inference or encrypted turn completion.
const MAX_CONTEXT_DISPATCH_WAIT_MS = 30_000;
const MAX_FAILURE_NOTIFY_WAIT_MS = 2_000;
type Barrier = { turnId: string; messageId: string; scope: string; active: boolean; done: Promise<void>; release: () => void };
const barriers = new Map<string, Barrier[]>();

export function reserveDraftContextDispatch(
  chatId: string, turnId: string, onTimeout?: () => Promise<void>, messageId = turnId,
): () => void {
  const scope = getWorkspaceCacheIdentity();
  if (!scope) return () => undefined;
  let resolve!: () => void;
  const done = new Promise<void>((settle) => { resolve = settle; });
  const barrier: Barrier = { turnId, messageId, scope, active: true, done, release: () => {
    clearTimeout(timeout);
    barrier.active = false;
    const remaining = barriers.get(chatId)?.filter((item) => item !== barrier) ?? [];
    if (remaining.length) barriers.set(chatId, remaining);
    else barriers.delete(chatId);
    resolve();
  } };
  const timeout = setTimeout(() => {
    barrier.active = false;
    let notifyTimeout: ReturnType<typeof setTimeout>;
    const notifyDeadline = new Promise<void>((resolve) => {
      notifyTimeout = setTimeout(resolve, MAX_FAILURE_NOTIFY_WAIT_MS);
    });
    void Promise.race([
      Promise.resolve().then(onTimeout).catch(() => undefined),
      notifyDeadline,
    ]).finally(() => {
      clearTimeout(notifyTimeout);
      barrier.release();
    });
  }, MAX_CONTEXT_DISPATCH_WAIT_MS);
  barriers.set(chatId, [...(barriers.get(chatId) ?? []), barrier]);
  return barrier.release;
}

export function pendingDraftContextDispatch(chatId: string): Promise<void> | null {
  const chatBarriers = barriers.get(chatId) ?? [];
  const barrier = chatBarriers[chatBarriers.length - 1];
  if (!barrier) return null;
  if (barrier.scope !== getWorkspaceCacheIdentity()) {
    barrier.release();
    return null;
  }
  return barrier.done;
}

export function pendingDraftContextDispatchIdentity(chatId: string): { turnId: string; messageId: string } | null {
  const barrier = barriers.get(chatId)?.at(-1);
  return barrier && barrier.scope === getWorkspaceCacheIdentity()
    ? { turnId: barrier.turnId, messageId: barrier.messageId } : null;
}

export function isDraftContextDispatchActive(chatId: string, turnId: string): boolean {
  const barrier = barriers.get(chatId)?.find((item) => item.turnId === turnId);
  return barrier?.active === true
    && barrier.scope === getWorkspaceCacheIdentity();
}

export function clearDraftContextDispatchBarriers(): void {
  for (const group of [...barriers.values()]) {
    for (const barrier of [...group]) barrier.release();
  }
}

registerWorkspaceCacheClear(clearDraftContextDispatchBarriers);
activeTeamContext.subscribe(() => {
  for (const group of [...barriers.values()]) {
    for (const barrier of [...group]) {
      if (barrier.scope !== getWorkspaceCacheIdentity()) barrier.release();
    }
  }
});
