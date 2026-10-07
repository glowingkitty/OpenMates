import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createConnectionFeedbackStore, type ConnectionFeedbackInputs } from '../connectionFeedbackStore';

describe('connectionFeedback', () => {
  let feedback: ReturnType<typeof createConnectionFeedbackStore>;
  const connected: ConnectionFeedbackInputs = {
    online: true, authenticated: true, checkingAuth: false,
    websocketStatus: 'connected', syncing: false,
  };
  beforeEach(() => { vi.useFakeTimers(); feedback = createConnectionFeedbackStore(); });
  afterEach(() => { feedback.reset(); vi.useRealTimers(); });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it('suppresses brief syncs and clears actual sync feedback on completion', () => {
    feedback.update({ ...connected, syncing: true });
    vi.advanceTimersByTime(599);
    expect(get(feedback).state).toBe('idle');
    feedback.update(connected);
    vi.advanceTimersByTime(1000);
    expect(get(feedback).state).toBe('idle');
    feedback.update({ ...connected, syncing: true });
    vi.advanceTimersByTime(600);
    expect(get(feedback).state).toBe('syncing');
    feedback.update(connected);
    expect(get(feedback).state).toBe('idle');
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it('gives browser-offline and sustained WebSocket loss priority over sync', () => {
    feedback.update({ ...connected, syncing: true });
    vi.advanceTimersByTime(600);
    feedback.update({ ...connected, online: false, syncing: true });
    expect(get(feedback)).toEqual({ state: 'offline', reason: 'offline' });
    feedback.update({ ...connected, websocketStatus: 'reconnecting' });
    vi.advanceTimersByTime(2999);
    expect(get(feedback).state).toBe('idle');
    vi.advanceTimersByTime(1);
    expect(get(feedback).state).toBe('reconnecting');
    feedback.update(connected);
    expect(get(feedback).state).toBe('idle');
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it('shows a static offline state for guests, ignores their socket and cancels stale timers', () => {
    feedback.update({ ...connected, authenticated: false, websocketStatus: 'disconnected' });
    vi.advanceTimersByTime(15000);
    expect(get(feedback).state).toBe('idle');
    feedback.update({ ...connected, authenticated: false, online: false, syncing: true });
    expect(get(feedback).state).toBe('offline');
    feedback.update({ ...connected, authenticated: false, checkingAuth: true, websocketStatus: 'disconnected' });
    vi.advanceTimersByTime(15000);
    expect(get(feedback).state).toBe('idle');
    feedback.update({ ...connected, websocketStatus: 'disconnected' });
    feedback.reset();
    vi.advanceTimersByTime(15000);
    expect(get(feedback).state).toBe('idle');
    expect(vi.getTimerCount()).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it('allows a ten-second wake grace and clears the server-updating reason on connection', () => {
    feedback.update({ ...connected, websocketStatus: 'disconnected' });
    feedback.serverUpdating();
    feedback.resume();
    vi.advanceTimersByTime(9999);
    expect(get(feedback).state).toBe('idle');
    vi.advanceTimersByTime(1);
    expect(get(feedback)).toEqual({ state: 'reconnecting', reason: 'server_updating' });
    feedback.update(connected);
    expect(get(feedback)).toEqual({ state: 'idle', reason: 'reconnecting' });
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it('surfaces a stuck auth check and clears it when checking ends', () => {
    feedback.update({ ...connected, checkingAuth: true });
    vi.advanceTimersByTime(11999);
    expect(get(feedback).state).toBe('idle');
    vi.advanceTimersByTime(1);
    expect(get(feedback).state).toBe('reconnecting');
    feedback.update(connected);
    expect(get(feedback).state).toBe('idle');
  });
});
