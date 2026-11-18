/**
 * Signed-out composer states.
 *
 * Product rule: a signed-out visitor sees either an active Send that sends, or
 * a Sign up / Log in button with a visible reason. A disabled or greyed Send is
 * always a bug. While guest access is still being checked the composer shows a
 * short loading state that resolves to one of the two within
 * GUEST_STATUS_TIMEOUT_MS. A guest send that cannot start within
 * GUEST_SEND_PREPARATION_BUDGET_MS fails visibly instead of hanging.
 *
 * Spec: specifications/features/message-input/specification.yml
 * (message-input.signed-out-two-states). Tests: __tests__/guestComposerState.test.ts,
 * frontend/apps/web_app/tests/anonymous-free-chat.spec.ts.
 */
import { get } from 'svelte/store';
import { refreshAnonymousFreeUsageStatus, serverStatusStore } from '../../stores/serverStatusStore';

/** Longest the signed-out composer shows its loading state before resolving. */
export const GUEST_STATUS_TIMEOUT_MS = 8_000;
/** Longest a guest send may wait on local preparation before it fails visibly. */
export const GUEST_SEND_PREPARATION_BUDGET_MS = 15_000;

export type GuestAccessPhase = 'pending' | 'loaded' | 'failed';
export type GuestAccessReason =
    | 'logged_in_before'
    | 'usage_limit'
    | 'unavailable'
    | 'status_unavailable'
    | 'file_requires_account';

export type GuestComposerState =
    | { kind: 'loading' }
    | { kind: 'send' }
    | { kind: 'account'; action: 'signup' | 'login'; reason: GuestAccessReason };

export interface GuestFreeUsageStatus {
    active?: boolean;
    can_send_text?: boolean;
    reason?: string | null;
}

export interface GuestComposerInput {
    phase: GuestAccessPhase;
    status: GuestFreeUsageStatus | null | undefined;
    lastAuthMethod: string | null;
    fileAttachmentPending: boolean;
}

const USAGE_LIMIT_REASONS = new Set([
    'anonymous_usage_limit', 'budget_exhausted', 'per_identity_exhausted',
    'daily_exhausted', 'weekly_exhausted', 'monthly_exhausted',
]);

/** i18n key (under `enter_message.`) that explains a signed-out account CTA. */
export const GUEST_ACCESS_REASON_KEYS: Record<GuestAccessReason, string> = {
    logged_in_before: 'guest_access_logged_in_before',
    usage_limit: 'guest_access_usage_limit',
    unavailable: 'guest_access_unavailable',
    status_unavailable: 'guest_access_status_unavailable',
    file_requires_account: 'guest_access_file_requires_account',
};

/** The only states a signed-out composer may render. Pure: no stores, no I/O. */
export function resolveGuestComposerState(input: GuestComposerInput): GuestComposerState {
    if (input.fileAttachmentPending) return { kind: 'account', action: 'signup', reason: 'file_requires_account' };
    // A browser that has logged in before must log in rather than chat as a guest.
    if (input.lastAuthMethod) return { kind: 'account', action: 'login', reason: 'logged_in_before' };
    if (input.phase === 'pending') return { kind: 'loading' };
    if (input.phase === 'failed') return { kind: 'account', action: 'signup', reason: 'status_unavailable' };
    const status = input.status;
    if (status && USAGE_LIMIT_REASONS.has(status.reason ?? '') && (status.active !== true || status.can_send_text === false)) {
        return { kind: 'account', action: 'signup', reason: 'usage_limit' };
    }
    if (!status || status.active !== true || status.can_send_text === false) {
        return { kind: 'account', action: 'signup', reason: 'unavailable' };
    }
    return { kind: 'send' };
}

/**
 * Load this browser's guest access within `timeoutMs`. `loaded` covers a
 * server without guest chat (status null) as well; `failed` means the status
 * could not be read in time, so the composer offers Sign up with that reason.
 */
export async function loadGuestAccessPhase(timeoutMs = GUEST_STATUS_TIMEOUT_MS): Promise<Exclude<GuestAccessPhase, 'pending'>> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timedOut = new Promise<'timeout'>((resolve) => { timer = setTimeout(() => resolve('timeout'), timeoutMs); });
    try {
        const outcome = await Promise.race([refreshAnonymousFreeUsageStatus(), timedOut]);
        if (outcome === 'timeout') return 'failed';
        if (outcome) return 'loaded';
        // refreshAnonymousFreeUsageStatus stores an explicit null when the server has no guest chat.
        return get(serverStatusStore).status?.anonymous_free_usage === null ? 'loaded' : 'failed';
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Longest a failed guest send waits on best-effort local cleanup before the
 * composer gets its Send back. The send hides Send until it returns, and that
 * cleanup reads local storage, which hangs when the on-device runtime never loads.
 */
export const GUEST_FAILED_SEND_CLEANUP_MS = 3_000;

/** Wait for `work` at most `timeoutMs`: true when it finished, false when it is still running. Rejections propagate. */
export async function settleWithin(work: Promise<unknown>, timeoutMs: number): Promise<boolean> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timedOut = new Promise<false>((resolve) => { timer = setTimeout(() => resolve(false), timeoutMs); });
    try {
        return await Promise.race([work.then(() => true as const), timedOut]);
    } finally {
        clearTimeout(timer);
    }
}

/** A guest send whose local preparation did not finish within its budget. */
export class GuestSendPreparationTimeoutError extends Error {
    constructor(readonly step: string) {
        super(`Guest send preparation timed out at ${step}`);
        this.name = 'GuestSendPreparationTimeoutError';
    }
}

/**
 * One shared deadline for every wait of a signed-out send before it reaches
 * the server. Authenticated sends pass their work through unchanged. The
 * abandoned work is a read or a load, never a dispatch, so failing early
 * cannot send a message twice.
 */
export function createGuestSendDeadline(authenticated: boolean, budgetMs = GUEST_SEND_PREPARATION_BUDGET_MS, now: () => number = Date.now) {
    const deadline = now() + budgetMs;
    return {
        bound<T>(work: Promise<T>, step: string): Promise<T> {
            if (authenticated) return work;
            const remaining = deadline - now();
            if (remaining <= 0) {
                void work.catch(() => {});
                return Promise.reject(new GuestSendPreparationTimeoutError(step));
            }
            let timer: ReturnType<typeof setTimeout> | undefined;
            const expired = new Promise<never>((_, reject) => {
                timer = setTimeout(() => reject(new GuestSendPreparationTimeoutError(step)), remaining);
            });
            void work.catch(() => {});
            return Promise.race([work, expired]).finally(() => clearTimeout(timer));
        },
    };
}
