/**
 * Transient server-confirmed cancellable focus activations.
 * Never persisted or reconstructed from historical embed content.
 * Exact embed/chat identities prevent history or another chat from inheriting a timer.
 * Deadlines expire locally without changing authoritative active focus state.
 * Shared contract: specifications/features/focus-modes/.
 */
import { get, writable } from 'svelte/store';
import { activeChatFocusStore } from './activeChatFocusStore';
export type SelectedProjectSpecialist = { focus_id: string; item_id: string; revision: string; title: string };
export type PendingFocus = { chatId: string; focusId: string; expiresAt: number; activationPolicy?: "delayed" | "immediate" | "approval";
  selectedSpecialist?: SelectedProjectSpecialist; confirmed?: boolean; expired?: boolean };
type PendingFocusInput = Omit<PendingFocus, 'confirmed' | 'expired'>;
const state = writable<Record<string, PendingFocus>>({});
const expiryTimers = new Map<string, ReturnType<typeof setTimeout>>();

function cancelExpiry(id: string) {
  const timer = expiryTimers.get(id);
  if (timer) clearTimeout(timer);
  expiryTimers.delete(id);
}

function scheduleExpiry(id: string, pending: PendingFocus) {
  cancelExpiry(id);
  if (pending.confirmed || pending.expired) return;
  const remaining = pending.expiresAt - Date.now();
  if (remaining <= 0) {
    state.update(values => values[id] === pending ? { ...values, [id]: { ...pending, expired: true } } : values);
    return;
  }
  const timer = setTimeout(() => {
    expiryTimers.delete(id);
    // An extended or replaced request must not be expired by its old timer.
    if (get(state)[id] !== pending) return;
    scheduleExpiry(id, pending);
  }, Math.min(remaining, 2_147_483_647));
  expiryTimers.set(id, timer);
}

// Confirmation is authoritative even if the focus is deactivated before a card remounts.
activeChatFocusStore.subscribe(active => {
  const values = get(state);
  const matching = Object.entries(values).filter(([, pending]) =>
    !pending.confirmed && active[pending.chatId] === pending.focusId);
  if (!matching.length) return;
  for (const [id] of matching) cancelExpiry(id);
  state.update(current => {
    const next = { ...current };
    for (const [id, pending] of matching) {
      if (next[id] === pending) next[id] = { ...pending, confirmed: true };
    }
    return next;
  });
});

export const pendingFocusActivationStore = {
  subscribe: state.subscribe,
  getPolicy(id: string): PendingFocus['activationPolicy'] {
    return get(state)[id]?.activationPolicy;
  },
  getSelectedSpecialist(id: string): SelectedProjectSpecialist | undefined {
    return get(state)[id]?.selectedSpecialist;
  },
  set(id: string, pending: PendingFocusInput) {
    if (!id || !pending.chatId || !pending.focusId || !Number.isFinite(pending.expiresAt) || pending.expiresAt <= Date.now()) return;
    const previous = get(state)[id];
    const sameRequest = previous?.chatId === pending.chatId && previous.focusId === pending.focusId;
    const next: PendingFocus = {
      ...pending,
      expiresAt: sameRequest ? Math.max(previous.expiresAt, pending.expiresAt) : pending.expiresAt,
      activationPolicy: pending.activationPolicy ?? (sameRequest ? previous.activationPolicy : undefined),
      selectedSpecialist: pending.selectedSpecialist ?? (sameRequest ? previous.selectedSpecialist : undefined),
      confirmed: (sameRequest && previous.confirmed) || get(activeChatFocusStore)[pending.chatId] === pending.focusId,
      expired: sameRequest && previous.expired,
    };
    state.update(values => ({ ...values, [id]: next }));
    // A confirmation may arrive synchronously while subscribers process the update.
    const current = get(state)[id];
    if (current === next) scheduleExpiry(id, next);
  },
  clear(id: string) {
    cancelExpiry(id);
    state.update(values => { const next = { ...values }; delete next[id]; return next; });
  },
};
