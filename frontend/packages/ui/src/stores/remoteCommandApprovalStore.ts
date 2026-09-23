/** Transient, chat-scoped review and status for remote Project commands. */
import { get, writable } from "svelte/store";

import type {
  DecryptedRemoteCommandEvent,
  RemoteCommandReviewDisplay,
} from "../services/browserRemoteCommandClient";

export type RemoteCommandEntryStatus =
  | "pending"
  | "preparing"
  | "waiting_for_executor"
  | "authorizing"
  | "running"
  | "stop_requested"
  | "succeeded"
  | "failed"
  | "stopped"
  | "timed_out"
  | "rejected"
  | "error";

export interface RemoteCommandEntry {
  id: string;
  chatId: string;
  projectId: string;
  sourceId: string;
  projectName: string;
  sourceName: string;
  status: RemoteCommandEntryStatus;
  review: RemoteCommandReviewDisplay;
  latestOutput: string;
  errorCode?: string;
}

const state = writable<RemoteCommandEntry[]>([]);
export const remoteCommandEntries = { subscribe: state.subscribe };
const pending = new Map<string, (accepted: boolean) => void>();
const stopCallbacks = new Map<string, () => Promise<void>>();

export function requestRemoteCommandApproval(
  review: RemoteCommandReviewDisplay,
  labels: { projectName: string; sourceName: string },
): Promise<boolean> {
  resolveRemoteCommandApproval(review.execution_id, false);
  if (pending.size >= 32) return Promise.resolve(false);
  const entry: RemoteCommandEntry = {
    id: review.execution_id,
    chatId: review.chat_id,
    projectId: review.project_id,
    sourceId: review.source_id,
    projectName: labels.projectName,
    sourceName: labels.sourceName,
    status: "pending",
    review: structuredClone(review),
    latestOutput: "",
  };
  state.update((entries) => [
    ...entries.filter((value) => value.id !== entry.id),
    entry,
  ]);
  return new Promise((resolve) => pending.set(entry.id, resolve));
}

export function resolveRemoteCommandApproval(
  executionId: string,
  accepted: boolean,
): void {
  const resolve = pending.get(executionId);
  if (!resolve) return;
  pending.delete(executionId);
  resolve(accepted);
  if (!accepted) setRemoteCommandStatus(executionId, "rejected");
}

export function setRemoteCommandStatus(
  executionId: string,
  status: RemoteCommandEntryStatus,
  errorCode?: string,
): void {
  state.update((entries) =>
    entries.map((entry) =>
      entry.id === executionId
        ? { ...entry, status, ...(errorCode ? { errorCode } : {}) }
        : entry,
    ),
  );
}

export function recordRemoteCommandEvent(
  chatId: string,
  event: DecryptedRemoteCommandEvent,
  latestOutput: string,
): void {
  const status = event.status as RemoteCommandEntryStatus;
  state.update((entries) =>
    entries.map((entry) =>
      entry.id === event.execution_id && entry.chatId === chatId
        ? { ...entry, status, latestOutput }
        : entry,
    ),
  );
}

export function bindRemoteCommandStop(
  executionId: string,
  callback: () => Promise<void>,
): () => void {
  stopCallbacks.set(executionId, callback);
  return () => {
    if (stopCallbacks.get(executionId) === callback)
      stopCallbacks.delete(executionId);
  };
}

export async function requestRemoteCommandStop(executionId: string): Promise<void> {
  const callback = stopCallbacks.get(executionId);
  if (!callback) return;
  setRemoteCommandStatus(executionId, "stop_requested");
  await callback();
}

export function clearRemoteCommands(chatId?: string): void {
  for (const entry of get(state)) {
    if (chatId && entry.chatId !== chatId) continue;
    const resolve = pending.get(entry.id);
    pending.delete(entry.id);
    resolve?.(false);
    stopCallbacks.delete(entry.id);
  }
  state.update((entries) =>
    chatId ? entries.filter((entry) => entry.chatId !== chatId) : [],
  );
}
