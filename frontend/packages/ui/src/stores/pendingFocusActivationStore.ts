/**
 * Transient server-confirmed cancellable focus activations.
 * Never persisted or reconstructed from historical embed content.
 * Exact embed/chat identities prevent history or another chat from inheriting a timer.
 * Deadlines expire locally without changing authoritative active focus state.
 * Shared contract: specifications/features/focus-modes/.
 */
import { writable } from 'svelte/store';
type PendingFocus = { chatId: string; focusId: string; expiresAt: number };
const state = writable<Record<string, PendingFocus>>({});
export const pendingFocusActivationStore = {
  subscribe: state.subscribe,
  set(id: string, pending: PendingFocus) {
    if (!id || !pending.chatId || !pending.focusId || !Number.isFinite(pending.expiresAt) || pending.expiresAt <= Date.now()) return;
    state.update(values => ({ ...values, [id]: pending }));
  },
  clear(id: string) {
    state.update(values => { const next = { ...values }; delete next[id]; return next; });
  },
};
