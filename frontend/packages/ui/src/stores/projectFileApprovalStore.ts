/** Transient, chat-scoped Project file consent and applied-change previews. */
import { get, writable } from 'svelte/store';
import type { ProjectReadApprovalRequest, ProjectWriteApprovalRequest } from '../services/projectFileJobExecutor';
import { activeChatStore } from './activeChatStore';
import { notificationStore } from './notificationStore';
import { text } from '../i18n/translations';

export type ProjectFileApprovalEntry =
  | { id: string; kind: 'write'; status: 'pending' | 'applied'; request: ProjectWriteApprovalRequest }
  | { id: string; kind: 'read'; status: 'pending'; request: ProjectReadApprovalRequest };

const state = writable<ProjectFileApprovalEntry[]>([]);
export const projectFileApprovals = { subscribe: state.subscribe };
const pending = new Map<string, { resolve: (accepted: boolean) => void; cleanup: () => void }>();

function requestId(request: ProjectWriteApprovalRequest | ProjectReadApprovalRequest): string {
  return JSON.stringify([request.chatId, request.projectId,
    'mutation' in request ? request.mutation.operation_id : request.operationId]);
}

function notifyAwayFromChat(entry: ProjectFileApprovalEntry): () => void {
  if (typeof window === 'undefined') return () => {};
  let notification: string | undefined;
  const dismiss = () => {
    if (notification) notificationStore.removeNotification(notification);
    notification = undefined;
  };
  const unsubscribe = activeChatStore.subscribe((chatId) => {
    if (chatId === entry.request.chatId) { dismiss(); return; }
    if (notification) return;
    notification = notificationStore.addNotificationWithOptions('info', {
      message: get(text)('projects.file_approval_waiting'),
      duration: 0,
      dismissible: true,
      actionLabel: get(text)('projects.file_approval_view'),
      onAction: () => { activeChatStore.setActiveChat(entry.request.chatId); dismiss(); },
    });
  });
  return () => { unsubscribe(); dismiss(); };
}

function ask(entry: ProjectFileApprovalEntry): Promise<boolean> {
  // A refreshed proposal replaces the old concrete consent, never inherits it.
  resolveProjectFileApproval(entry.id, false);
  if (pending.size >= 32) return Promise.resolve(false);
  return new Promise((resolve) => {
    const cleanup = notifyAwayFromChat(entry);
    pending.set(entry.id, { resolve, cleanup });
    state.update((entries) => [...entries.filter((value) => value.id !== entry.id), entry]);
  });
}

export function requestProjectWriteApproval(request: ProjectWriteApprovalRequest): Promise<boolean> {
  return ask({ id: requestId(request), kind: 'write', status: 'pending', request: structuredClone(request) });
}

export function requestProjectIgnoredReadApproval(request: ProjectReadApprovalRequest): Promise<boolean> {
  return ask({ id: requestId(request), kind: 'read', status: 'pending', request: { ...request } });
}

export function resolveProjectFileApproval(id: string, accepted: boolean): void {
  const item = pending.get(id);
  if (!item) return;
  pending.delete(id);
  item.cleanup();
  state.update((entries) => entries.filter((entry) => entry.id !== id));
  item.resolve(accepted);
}

export function recordProjectFileChange(request: ProjectWriteApprovalRequest): void {
  const entry: ProjectFileApprovalEntry = {
    id: requestId(request), kind: 'write', status: 'applied', request: structuredClone(request),
  };
  state.update((entries) => {
    const remaining = entries.filter((value) => value.id !== entry.id);
    const approvals = remaining.filter((value) => value.status === 'pending');
    const changes = remaining.filter((value) => value.status === 'applied').slice(-23);
    return [...approvals, ...changes, entry];
  });
}

export function clearProjectFileApprovals(chatId?: string): void {
  for (const entry of get(state)) {
    if (!chatId || entry.request.chatId === chatId) resolveProjectFileApproval(entry.id, false);
  }
  state.update((entries) => chatId ? entries.filter((entry) => entry.request.chatId !== chatId) : []);
}
