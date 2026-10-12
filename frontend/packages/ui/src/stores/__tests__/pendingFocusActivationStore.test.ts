import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { activeChatFocusStore } from '../activeChatFocusStore';
import { pendingFocusActivationStore } from '../pendingFocusActivationStore';

const specialist = { focus_id: 'project-one', item_id: 'specialist-one', revision: '2', title: 'Research' };

describe('pending focus activation lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-12T12:00:00Z'));
  });
  afterEach(() => {
    pendingFocusActivationStore.clear('embed-one');
    activeChatFocusStore.clearActiveFocus('chat-one');
    vi.useRealTimers();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.countdown
  it('settles a confirmed request through deactivation and duplicate delivery while preserving Project metadata', () => {
    const request = { chatId: 'chat-one', focusId: 'project-one', expiresAt: Date.now() + 4000,
      activationPolicy: 'approval' as const, selectedSpecialist: specialist };
    pendingFocusActivationStore.set('embed-one', request);
    expect(get(pendingFocusActivationStore)['embed-one'].confirmed).toBe(false);

    activeChatFocusStore.setActiveFocus('chat-one', 'project-one');
    expect(get(pendingFocusActivationStore)['embed-one']).toMatchObject({ confirmed: true, selectedSpecialist: specialist });
    activeChatFocusStore.clearActiveFocus('chat-one');
    pendingFocusActivationStore.set('embed-one', { ...request, expiresAt: request.expiresAt + 1000 });
    expect(get(pendingFocusActivationStore)['embed-one']).toMatchObject({ confirmed: true, expiresAt: request.expiresAt + 1000 });
    expect(pendingFocusActivationStore.getSelectedSpecialist('embed-one')).toEqual(specialist);
    expect(pendingFocusActivationStore.getPolicy('embed-one')).toBe('approval');
    vi.advanceTimersByTime(6000);
    expect(get(pendingFocusActivationStore)['embed-one']).toMatchObject({ confirmed: true, expired: false });
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.countdown
  it('notifies subscribers at expiry and prevents a duplicate from replaying the countdown', () => {
    const expiresAt = Date.now() + 4000;
    const seen: Array<boolean | undefined> = [];
    const unsubscribe = pendingFocusActivationStore.subscribe(values => seen.push(values['embed-one']?.expired));
    pendingFocusActivationStore.set('embed-one', { chatId: 'chat-one', focusId: 'project-one', expiresAt,
      selectedSpecialist: specialist });
    vi.advanceTimersByTime(4000);
    expect(seen).toEqual([undefined, false, true]);
    expect(get(pendingFocusActivationStore)['embed-one']).toMatchObject({ expired: true, selectedSpecialist: specialist });
    pendingFocusActivationStore.set('embed-one', { chatId: 'chat-one', focusId: 'project-one', expiresAt: expiresAt + 1000 });
    expect(get(pendingFocusActivationStore)['embed-one'].expired).toBe(true);
    unsubscribe();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.countdown
  it('lets an extended deadline replace the old expiry timer', () => {
    const expiresAt = Date.now() + 4000;
    pendingFocusActivationStore.set('embed-one', { chatId: 'chat-one', focusId: 'project-one', expiresAt });
    pendingFocusActivationStore.set('embed-one', { chatId: 'chat-one', focusId: 'project-one', expiresAt: expiresAt + 3000 });
    vi.advanceTimersByTime(4000);
    expect(get(pendingFocusActivationStore)['embed-one'].expired).toBe(false);
    vi.advanceTimersByTime(3000);
    expect(get(pendingFocusActivationStore)['embed-one'].expired).toBe(true);
  });
});
