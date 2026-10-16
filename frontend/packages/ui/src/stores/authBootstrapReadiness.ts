/**
 * Publishes the root page's existing initial auth/crypto check completion.
 * This schedules Personal ciphertext reads; it never grants authentication.
 * Settled includes offline fallback: the server still decides every read.
 * Failed or replaced bootstrap work cannot release a newer page's waiters.
 * Readers use their existing deadline and captured auth/owner write guards.
 */
import { get, writable } from 'svelte/store';

type BootstrapPhase = 'pending' | 'settled' | 'failed';
const state = writable<{ token: number; phase: BootstrapPhase }>({ token: 0, phase: 'settled' });
let nextToken = 0;
export const authBootstrapReadiness = { subscribe: state.subscribe };

export function beginAuthBootstrapReadiness(): number {
  const token = ++nextToken;
  state.set({ token, phase: 'pending' });
  return token;
}

export function settleAuthBootstrapReadiness(token: number | null): void {
  if (token !== null && get(state).token === token && get(state).phase === 'pending') {
    state.set({ token, phase: 'settled' });
  }
}

export function failAuthBootstrapReadiness(token: number | null): void {
  if (token !== null && get(state).token === token && get(state).phase === 'pending') {
    state.set({ token, phase: 'failed' });
  }
}

/** Preserve existing initialization errors while releasing pending readers fail-closed. */
export async function observeAuthBootstrapFailure<T>(token: number | null, work: () => Promise<T>): Promise<T> {
  try { return await work(); }
  catch (error) { failAuthBootstrapReadiness(token); throw error; }
}

/** Called only by existing confirmed login/server-session success paths, never optimism. */
export function recoverAuthBootstrapAfterConfirmedSession(): void {
  const current = get(state);
  if (current.phase === 'failed') state.set({ ...current, phase: 'settled' });
}

export function isAuthBootstrapSettled(): boolean { return get(state).phase === 'settled'; }

/** No independent timer: callers supply their existing bounded operation signal. */
export function waitForAuthBootstrapReadiness(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    let done = false;
    let unsubscribe = () => {};
    const finish = (error?: Error) => {
      if (done) return;
      done = true; unsubscribe(); signal.removeEventListener('abort', aborted);
      if (error) reject(error); else resolve();
    };
    const aborted = () => finish(new Error('Personal embed bootstrap wait aborted'));
    signal.addEventListener('abort', aborted, { once: true });
    unsubscribe = state.subscribe(value => {
      if (value.phase === 'pending') return;
      // subscribe may invoke synchronously, before its unsubscribe handle is assigned.
      queueMicrotask(() => {
        const current = get(state);
        if (current.token !== value.token || current.phase === 'pending') return;
        if (signal.aborted) aborted();
        else finish(current.phase === 'failed' ? new Error('Personal embed bootstrap did not settle') : undefined);
      });
    });
    if (signal.aborted) aborted();
  });
}
