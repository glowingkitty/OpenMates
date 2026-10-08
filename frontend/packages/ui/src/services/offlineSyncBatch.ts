import { get } from "svelte/store";
import { activeTeamContext } from "../stores/teamStore";
import { userProfile } from "../stores/userProfile";
import { websocketStatus } from "../stores/websocketStatusStore";

interface PendingBatch {
  id: string;
  accountId: string | null;
  teamId: string | null;
  epoch: number;
  startedAt: number;
  changeIds: Set<string>;
}

let pendingBatch: PendingBatch | null = null;
let batchSequence = 0;
websocketStatus.subscribe((state) => {
  if (state.status !== "connected") pendingBatch = null;
});

export function beginOfflineSyncBatch(changeIds: string[]): string | null {
  const context = get(activeTeamContext);
  const accountId = get(userProfile).user_id;
  if (
    pendingBatch && pendingBatch.accountId === accountId &&
    pendingBatch.teamId === context.teamId && pendingBatch.epoch === context.epoch &&
    Date.now() - pendingBatch.startedAt < 10_000
  ) return null;
  const id = `${crypto.randomUUID()}:${++batchSequence}`;
  pendingBatch = { id, accountId, teamId: context.teamId, epoch: context.epoch,
    startedAt: Date.now(), changeIds: new Set(changeIds) };
  return id;
}

export function cancelOfflineSyncBatch(id: string): void {
  if (pendingBatch?.id === id) pendingBatch = null;
}

export function consumeOfflineSyncBatch(id: string | undefined, successfulIds: string[]): string[] | null {
  const batch = pendingBatch;
  if (!id || !batch || batch.id !== id) return null;
  pendingBatch = null;
  const context = get(activeTeamContext);
  if (
    batch.accountId !== get(userProfile).user_id ||
    batch.teamId !== context.teamId || batch.epoch !== context.epoch
  ) return null;
  return successfulIds.filter((changeId) => batch.changeIds.has(changeId));
}
