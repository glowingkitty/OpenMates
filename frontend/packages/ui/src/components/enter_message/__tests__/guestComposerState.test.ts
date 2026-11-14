import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writable } from 'svelte/store';

const mocks = vi.hoisted(() => ({
    refresh: vi.fn(),
    store: null as unknown as ReturnType<typeof writable<{ status: Record<string, unknown> | null }>>,
}));

vi.mock('../../../stores/serverStatusStore', async () => {
    const { writable: makeWritable } = await import('svelte/store');
    mocks.store = makeWritable<{ status: Record<string, unknown> | null }>({ status: {} });
    return { refreshAnonymousFreeUsageStatus: mocks.refresh, serverStatusStore: mocks.store };
});

import {
    createGuestSendDeadline,
    GUEST_ACCESS_REASON_KEYS,
    GuestSendPreparationTimeoutError,
    loadGuestAccessPhase,
    resolveGuestComposerState,
    type GuestAccessPhase,
    type GuestComposerInput,
    type GuestFreeUsageStatus,
} from '../guestComposerState';

const OPEN: GuestFreeUsageStatus = { active: true, can_send_text: true, reason: null };
const base: GuestComposerInput = { phase: 'loaded', status: OPEN, lastAuthMethod: null, fileAttachmentPending: false };

describe('signed-out composer: only Send, Sign up / Log in with a reason, or a short loading state', () => {
    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('shows an active Send when guest chat is open', () => {
        expect(resolveGuestComposerState(base)).toEqual({ kind: 'send' });
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('shows loading while access is unknown, then resolves to Sign up with a reason when the check fails', () => {
        expect(resolveGuestComposerState({ ...base, phase: 'pending', status: undefined })).toEqual({ kind: 'loading' });
        expect(resolveGuestComposerState({ ...base, phase: 'failed', status: undefined }))
            .toEqual({ kind: 'account', action: 'signup', reason: 'status_unavailable' });
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('offers Log in to a browser that has logged in before, without waiting for the status', () => {
        expect(resolveGuestComposerState({ ...base, phase: 'pending', lastAuthMethod: 'passkey' }))
            .toEqual({ kind: 'account', action: 'login', reason: 'logged_in_before' });
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('names an exhausted allowance as the reason', () => {
        for (const reason of ['anonymous_usage_limit', 'daily_exhausted', 'budget_exhausted']) {
            expect(resolveGuestComposerState({ ...base, status: { active: false, can_send_text: false, reason } }))
                .toEqual({ kind: 'account', action: 'signup', reason: 'usage_limit' });
        }
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('names guest chat being off or absent as the reason', () => {
        for (const status of [null, { active: false }, { active: true, can_send_text: false, reason: 'maintenance' }]) {
            expect(resolveGuestComposerState({ ...base, status }))
                .toEqual({ kind: 'account', action: 'signup', reason: 'unavailable' });
        }
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('asks for an account when a file is attached', () => {
        expect(resolveGuestComposerState({ ...base, fileAttachmentPending: true }))
            .toEqual({ kind: 'account', action: 'signup', reason: 'file_requires_account' });
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('reaches no other state for any combination of inputs, and every account state has a reason text', () => {
        const phases: GuestAccessPhase[] = ['pending', 'loaded', 'failed'];
        const statuses: Array<GuestFreeUsageStatus | null | undefined> = [
            undefined, null, OPEN, { active: false }, { active: true, can_send_text: false },
            { active: false, can_send_text: false, reason: 'weekly_exhausted' }, { active: true },
        ];
        for (const phase of phases) for (const status of statuses) for (const lastAuthMethod of [null, 'email'])
            for (const fileAttachmentPending of [false, true]) {
                const state = resolveGuestComposerState({ phase, status, lastAuthMethod, fileAttachmentPending });
                expect(['send', 'loading', 'account']).toContain(state.kind);
                if (state.kind === 'account') {
                    expect(['signup', 'login']).toContain(state.action);
                    expect(GUEST_ACCESS_REASON_KEYS[state.reason]).toMatch(/^guest_access_/);
                }
                if (state.kind === 'send') expect(phase).toBe('loaded');
            }
    });
});

describe('guest access check resolves within its time limit', () => {
    beforeEach(() => { vi.useFakeTimers(); mocks.refresh.mockReset(); mocks.store.set({ status: {} }); });
    afterEach(() => { vi.useRealTimers(); });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('is loaded when the status arrives', async () => {
        mocks.refresh.mockResolvedValue(OPEN);
        await expect(loadGuestAccessPhase(1000)).resolves.toBe('loaded');
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('fails when the request errors (null without an explicit no-guest-chat marker)', async () => {
        mocks.refresh.mockResolvedValue(null);
        await expect(loadGuestAccessPhase(1000)).resolves.toBe('failed');
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('is loaded when the server has no guest chat at all', async () => {
        mocks.refresh.mockResolvedValue(null);
        mocks.store.set({ status: { anonymous_free_usage: null } });
        await expect(loadGuestAccessPhase(1000)).resolves.toBe('loaded');
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('fails instead of loading forever when the request hangs', async () => {
        mocks.refresh.mockReturnValue(new Promise(() => {}));
        const phase = loadGuestAccessPhase(1000);
        await vi.advanceTimersByTimeAsync(1000);
        await expect(phase).resolves.toBe('failed');
    });
});

describe('guest send preparation deadline', () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('rejects a hanging guest wait with the step that hung', async () => {
        const deadline = createGuestSendDeadline(false, 1000);
        const waiting = deadline.bound(new Promise(() => {}), 'privacy_scan');
        const assertion = expect(waiting).rejects.toMatchObject({ name: 'GuestSendPreparationTimeoutError', step: 'privacy_scan' });
        await vi.advanceTimersByTimeAsync(1000);
        await assertion;
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('shares one budget across steps', async () => {
        const deadline = createGuestSendDeadline(false, 1000);
        await vi.advanceTimersByTimeAsync(600);
        await expect(deadline.bound(Promise.resolve('ok'), 'first')).resolves.toBe('ok');
        await vi.advanceTimersByTimeAsync(500);
        await expect(deadline.bound(Promise.resolve('late'), 'second')).rejects.toBeInstanceOf(GuestSendPreparationTimeoutError);
    });

    // contract-test: direct surface=gui.web assertions=message-input.signed-out-two-states
    it('passes authenticated work through without a time limit', async () => {
        const deadline = createGuestSendDeadline(true, 1);
        let resolveWork: (value: string) => void = () => {};
        const work = new Promise<string>((resolve) => { resolveWork = resolve; });
        const bound = deadline.bound(work, 'privacy_scan');
        await vi.advanceTimersByTimeAsync(10_000);
        resolveWork('done');
        await expect(bound).resolves.toBe('done');
    });
});
