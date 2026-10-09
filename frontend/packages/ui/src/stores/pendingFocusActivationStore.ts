/**
 * Transient server-confirmed cancellable focus activations.
 * Never persisted or reconstructed from historical embed content.
 * Exact embed/chat identities prevent history or another chat from inheriting a timer.
 * Deadlines expire locally without changing authoritative active focus state.
 * Shared contract: specifications/features/focus-modes/.
 */
import { writable } from 'svelte/store';
import { get } from 'svelte/store';
export type SelectedProjectSpecialist = { focus_id: string; item_id: string; revision: string; title: string };
type PendingFocus = { chatId: string; focusId: string; expiresAt: number; activationPolicy?: "delayed" | "immediate" | "approval";
  selectedSpecialist?: SelectedProjectSpecialist };
const state = writable<Record<string, PendingFocus>>({});
export const pendingFocusActivationStore = {
  subscribe: state.subscribe,
  getPolicy(id: string): PendingFocus['activationPolicy'] {
    return get(state)[id]?.activationPolicy;
  },
  getSelectedSpecialist(id: string): SelectedProjectSpecialist | undefined {
    return get(state)[id]?.selectedSpecialist;
  },
  set(id: string, pending: PendingFocus) {
    if (!id || !pending.chatId || !pending.focusId || !Number.isFinite(pending.expiresAt) || pending.expiresAt <= Date.now()) return;
    state.update(values => ({ ...values, [id]: pending }));
  },
  clear(id: string) {
    state.update(values => { const next = { ...values }; delete next[id]; return next; });
  },
};
