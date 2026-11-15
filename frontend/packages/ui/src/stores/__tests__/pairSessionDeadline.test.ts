import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

// The pair policy runs in the Rust core; this suite pins the store lifecycle
// (restricted until cleanup finishes) against a deterministic stand-in.
vi.mock('../../services/rustCore/auth/flowPush', () => ({
  authFlowActive: () => true,
  FAIL_CLOSED_PAIR_STATE: { isPairSession: true, authorizerDeviceName: null, autoLogoutAt: null, autoLogoutWarning: false, remainingSeconds: null },
  NEUTRAL_PAIR_STATE: { isPairSession: false, authorizerDeviceName: null, autoLogoutAt: null, autoLogoutWarning: false, remainingSeconds: null },
  pairActivate: async (opts: { authorizerDeviceName?: string | null; autoLogoutMinutes?: number | null; pairExpiresAt?: number | null }, now: number) => ({
    isPairSession: true, establishedAt: now, authorizerDeviceName: opts.authorizerDeviceName ?? null,
    autoLogoutMinutes: opts.autoLogoutMinutes ?? null,
    autoLogoutAt: opts.pairExpiresAt != null ? opts.pairExpiresAt * 1000 : null,
  }),
  pairAutoLogoutDue: async (data: { autoLogoutAt: number | null }, now: number) => !!data.autoLogoutAt && now >= data.autoLogoutAt,
  pushPairView: (data: { authorizerDeviceName: string | null; autoLogoutAt: number | null } | null, _now: number, set: (view: unknown) => void) => {
    set(data
      ? { isPairSession: true, authorizerDeviceName: data.authorizerDeviceName, autoLogoutAt: data.autoLogoutAt, autoLogoutWarning: false, remainingSeconds: null }
      : { isPairSession: false, authorizerDeviceName: null, autoLogoutAt: null, autoLogoutWarning: false, remainingSeconds: null });
  },
}));

describe('paired session absolute deadline', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-28T12:00:00Z'));
    sessionStorage.clear();
  });
  afterEach(() => { vi.useRealTimers(); sessionStorage.clear(); });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.expiry
  it('keeps the session restricted while runtime credential cleanup is pending', async () => {
    const store = await import('../pairSessionStore');
    let finishCleanup!: () => void;
    const cleanup = new Promise<void>(resolve => { finishCleanup = resolve; });
    const callback = vi.fn(() => cleanup);
    store.registerPairLogoutCallback(callback);
    store.activatePairSession({ autoLogoutMinutes: 30, pairExpiresAt: Date.now() / 1000 + 2 });

    await vi.advanceTimersByTimeAsync(2_100);
    expect(callback).toHaveBeenCalledOnce();
    expect(get(store.pairSessionState).isPairSession).toBe(true);
    expect(sessionStorage.getItem('openmates_pair_session')).not.toBeNull();

    finishCleanup();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(store.pairSessionState).isPairSession).toBe(false);
    expect(sessionStorage.getItem('openmates_pair_session')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=auth.pair-login.expiry
  it('cleans up a pair that expired during reload before removing the marker', async () => {
    sessionStorage.setItem('openmates_pair_session', JSON.stringify({
      isPairSession: true, establishedAt: Date.now() - 60_000,
      authorizerDeviceName: 'Phone', autoLogoutMinutes: 30,
      autoLogoutAt: Date.now() - 1_000,
    }));
    const store = await import('../pairSessionStore');
    let finishCleanup!: () => void;
    const callback = vi.fn(() => new Promise<void>(resolve => { finishCleanup = resolve; }));
    store.registerPairLogoutCallback(callback);
    const rehydration = store.rehydratePairSession();
    await vi.advanceTimersByTimeAsync(0);
    expect(callback).toHaveBeenCalledOnce();
    expect(get(store.pairSessionState).isPairSession).toBe(true);
    finishCleanup();
    await rehydration;
    expect(get(store.pairSessionState).isPairSession).toBe(false);
  });
});
