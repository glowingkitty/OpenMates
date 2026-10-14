/**
 * Owns pending Personal embed reads across resolver and historical-child repair.
 * Scope binds auth generation, owner/account, actual source chat and active chat.
 * Work remains shared through guarded persistence and local readiness checks.
 * Eight-second deadlines cancel transport and reject late writes.
 * Neither response bodies nor failed reads are cached.
 */
import { get } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { activeChatStore } from '../stores/activeChatStore';
import { waitForAuthBootstrapReadiness } from '../stores/authBootstrapReadiness';

export type PersonalEmbedReadScope = {
  auth: object;
  ownerId: string;
  accountId: string | null;
  chatId: string;
  embedId: string;
  activeChatId: string | null;
};
const generations = new WeakMap<object, number>();
let nextGeneration = 0;
const pending = new Map<string, Promise<void>>();
const MAX_PENDING = 500;
const READ_DEADLINE_MS = 8000;

export function capturePersonalEmbedReadScope(chatId: string, embedId: string): PersonalEmbedReadScope | null {
  const canonical = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const auth = get(authStore), profile = get(userProfile);
  if (!auth.isAuthenticated || !profile.user_id || !canonical.test(chatId) || !canonical.test(embedId)) return null;
  return { auth, ownerId: profile.user_id, accountId: profile.account_id ?? null,
    chatId, embedId, activeChatId: activeChatStore.get() };
}

export function assertPersonalEmbedReadScope(scope: PersonalEmbedReadScope): void {
  const auth = get(authStore), profile = get(userProfile);
  if (auth !== scope.auth || !auth.isAuthenticated || profile.user_id !== scope.ownerId
      || (profile.account_id ?? null) !== scope.accountId || activeChatStore.get() !== scope.activeChatId) {
    throw new Error('Personal embed read scope changed');
  }
}

/** Identity shared by operation ownership and finite per-caller retry restraint. */
export function personalEmbedReadOperationKey(scope: PersonalEmbedReadScope): string {
  let generation = generations.get(scope.auth);
  if (generation === undefined) { generation = ++nextGeneration; generations.set(scope.auth, generation); }
  return JSON.stringify([generation, scope.ownerId, scope.accountId, scope.chatId, scope.embedId, scope.activeChatId]);
}

/** The actual source chat can differ from the captured active chat during parent-chat reads. */
export function runPersonalEmbedReadOperation(
  scope: PersonalEmbedReadScope,
  operation: (writeGuard: () => void, signal: AbortSignal) => Promise<void>,
): Promise<void> {
  assertPersonalEmbedReadScope(scope);
  const key = personalEmbedReadOperationKey(scope);
  const existing = pending.get(key);
  if (existing) return existing.then(() => assertPersonalEmbedReadScope(scope));
  if (pending.size >= MAX_PENDING) return Promise.reject(new Error('Personal embed reads are busy'));
  const controller = new AbortController();
  let active = true;
  const writeGuard = () => {
    if (!active || controller.signal.aborted) throw new Error('Personal embed read expired');
    assertPersonalEmbedReadScope(scope);
  };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      active = false; controller.abort(); reject(new Error('Personal embed read timed out'));
    }, READ_DEADLINE_MS);
  });
  // Register before work starts; no lookup/import await can open a second Personal read.
  const work = Promise.resolve().then(async () => {
    writeGuard();
    await waitForAuthBootstrapReadiness(controller.signal);
    // The server check can replace an optimistic snapshot: reject it before transport.
    writeGuard();
    await operation(writeGuard, controller.signal);
    writeGuard();
  });
  const result = Promise.race([work, deadline]).finally(() => {
    active = false; clearTimeout(timer);
    if (pending.get(key) === result) pending.delete(key);
  });
  pending.set(key, result);
  return result;
}
