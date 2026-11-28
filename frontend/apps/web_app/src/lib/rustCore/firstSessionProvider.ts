/** Browser-only bridge for the page's first ordinary auth check. The genuine
 * native Worker result stays with its original Host for one saved-chat adoption.
 * Response fields travel to the existing page classifier as data only.
 */
import { get } from 'svelte/store';
import { getApiEndpoint, getApiUrl } from '@openmates/ui/src/config/api';
import { authStore, getLoginSessionGeneration, observeLoginSessionGeneration } from '@openmates/ui/src/stores/authStore';
import { userProfile } from '@openmates/ui/src/stores/userProfile';
import { getActiveTeamContextSnapshot } from '@openmates/ui/src/stores/teamStore';
import { getWorkspaceCacheIdentity } from '@openmates/ui/src/services/workspaceQueryCache';
import { browserProfileLifecycle } from '@openmates/ui/src/services/rustCore/platformLifecycle';
import { createBrowserSavedChatPlatform } from '@openmates/ui/src/services/rustCore/productionSavedChatPlatform';
import { validFirstSessionSignals } from '@openmates/ui/src/services/rustCore/protocol';
import type { ExistingSavedChatProfile } from '@openmates/ui/src/services/rustCore/secondDeviceSavedChatSession';
import {
	assertLocalReadAfterFirstSession, type OriginalFirstSessionData, type OriginalFirstSessionInput,
	type OriginalFirstSessionScope, type OriginalFirstSessionWorker,
} from '@openmates/ui/src/services/rustCore/originalFirstSessionSource';

interface Attempt extends OriginalFirstSessionScope {
	readonly lifetime: AbortController;
	claimed: boolean;
	taken: boolean;
	adopted: boolean;
	failure: 'session_expired' | 'unavailable';
	stopObserving?: () => void;
	stopLoginObservation?: () => void;
	admitted?: Omit<OriginalFirstSessionWorker, 'confirmHandover'>;
	pending?: Promise<void>;
}

let original: Attempt | null = null;

function stillCurrent(attempt: Attempt): boolean {
	return !attempt.lifetime.signal.aborted &&
		getLoginSessionGeneration() === attempt.loginGeneration &&
		get(userProfile).user_id === attempt.owner && getWorkspaceCacheIdentity() === attempt.scope &&
		sessionStorage.getItem('session_id') === attempt.sessionId;
}

function close(attempt: Attempt): void {
	attempt.stopObserving?.();
	attempt.stopLoginObservation?.();
	attempt.lifetime.abort();
	attempt.admitted?.close();
	attempt.admitted = undefined;
}

async function read(attempt: Attempt, input: OriginalFirstSessionInput): Promise<OriginalFirstSessionData | null> {
	// The original request owns its abort and must drain before the Page read
	// settles. Before dispatch, abort may instead release the preflight lease.
	const stop = () => { if (!attempt.claimed) close(attempt); };
	input.signal.addEventListener('abort', stop, { once: true });
	let transferred = false;
	try {
		if (input.signal.aborted || !input.isCurrent() || !stillCurrent(attempt)) throw new Error('cancelled');
		// This bootstrap preflight has no credentialed IO. It must never wait for
		// the page's own auth bootstrap, since this is that auth callback.
		let witness: ExistingSavedChatProfile;
		let worker: Awaited<ReturnType<typeof import('./rustCoreLoader')['createRustCoreWorker']>>;
		const platform = await createBrowserSavedChatPlatform(attempt.lifetime.signal, 'local_first');
		try {
			if (platform.expectedPrincipal !== attempt.owner || platform.sessionId !== attempt.sessionId) return null;
			const generation = browserProfileLifecycle.current();
			witness = await platform.sources.capture(generation);
			const { createRustCoreWorker } = await import('./rustCoreLoader');
			worker = await createRustCoreWorker({
				apiUrl: getApiUrl(), sessionId: attempt.sessionId, expectedPrincipal: attempt.owner,
				signal: attempt.lifetime.signal, firstSession: true,
			});
			await platform.sources.assertCurrent(witness);
			if (input.signal.aborted || !input.isCurrent() || !stillCurrent(attempt)) throw new Error('cancelled');
			const remaining = Math.min(10_000, Math.floor(input.deadlineEpochMs - Date.now()));
			if (remaining < 1) throw new Error('deadline');
			// The Worker owns the original physical auth lock, including its
			// terminal drain. The Page still owns same-tab serialization.
			attempt.claimed = true;
			const reply = await worker.host.request({
				operation: 'check_first_session', key: witness.key,
				profile: { ...witness.profile }, persistence: 'memory_only',
				deviceSignals: input.deviceSignals, deadlineEpochMs: input.deadlineEpochMs,
			}, input.signal, remaining);
			if (!reply.ok || !reply.firstSession) throw new Error('unavailable');
			const { httpStatus, data } = reply.firstSession;
			if (httpStatus !== null) performance.mark('openmates:rust:auth-first-session-response');
			if (httpStatus === 401 || httpStatus === 403 || (httpStatus === 200 && data?.success === false)) {
				attempt.failure = 'session_expired';
			}
			if (httpStatus === 200 && data?.success === true && reply.status?.principal === attempt.owner &&
				reply.status.persistence === 'memory_only' && reply.status.localReadOnly === false &&
				input.isCurrent() && stillCurrent(attempt)) {
				// Transport data remains usable by auth even when this profile no
				// longer qualifies the Host for saved chat reuse.
				const profileCurrent = await platform.sources.assertCurrent(witness).then(() => true, () => false);
				if (profileCurrent && !input.signal.aborted && input.isCurrent() && stillCurrent(attempt)) {
					attempt.admitted = { host: worker.host, close: worker.close, witness };
					transferred = true;
				}
			}
			return { httpStatus, data: data as OriginalFirstSessionData['data'] };
		} finally {
			platform.close();
		}
	} catch (error) {
		if (!attempt.claimed && !input.signal.aborted && input.isCurrent()) return null;
		throw error;
	} finally {
		input.signal.removeEventListener('abort', stop);
		if (!transferred) close(attempt);
	}
}

/** Only the page's serialized normal session check calls this producer. */
export function readOriginalFirstSessionCheck(input: OriginalFirstSessionInput): Promise<OriginalFirstSessionData | null> | null {
	if (original || typeof window === 'undefined' || !window.isSecureContext || !navigator.locks ||
		input.signal.aborted || !input.isCurrent() || !validFirstSessionSignals(input.deviceSignals) ||
		input.endpoint !== getApiEndpoint('/v1/auth/session') || input.appOrigin !== window.location.origin ||
		!Number.isSafeInteger(input.deadlineEpochMs) || getActiveTeamContextSnapshot().teamId) return null;
	const auth = get(authStore);
	const owner = get(userProfile).user_id;
	const scope = getWorkspaceCacheIdentity();
	if (!auth.isAuthenticated || !auth.isInitialized || !owner || !scope ||
		sessionStorage.getItem('session_id') !== input.sessionId) return null;
	const attempt: Attempt = {
		owner, scope, sessionId: input.sessionId, loginGeneration: getLoginSessionGeneration(),
		lifetime: new AbortController(), claimed: false, taken: false, adopted: false, failure: 'unavailable',
	};
	original = attempt;
	attempt.stopObserving = browserProfileLifecycle.observe(() => close(attempt));
	attempt.stopLoginObservation = observeLoginSessionGeneration(() => close(attempt));
	const pending = read(attempt, input);
	attempt.pending = pending.then(() => undefined, () => undefined);
	return pending;
}

/** Offline and unreachable checks leave the existing local cache path available. */
export function assertOriginalFirstSessionAllowsLocalRead(owner: string, sessionId: string): void {
	const scope = getWorkspaceCacheIdentity();
	if (scope) assertLocalReadAfterFirstSession(original, { owner, scope, sessionId, loginGeneration: getLoginSessionGeneration() });
}

/** Transfer the matching actual Host. A claimed attempt has no second restore. */
export async function takeOriginalFirstSessionWorker(input: {
	signal: AbortSignal; expectedPrincipal: string; sessionId: string;
}): Promise<OriginalFirstSessionWorker | null> {
	const attempt = original;
	if (!attempt || input.expectedPrincipal !== attempt.owner || input.sessionId !== attempt.sessionId ||
		getLoginSessionGeneration() !== attempt.loginGeneration || getWorkspaceCacheIdentity() !== attempt.scope) return null;
	await attempt.pending;
	if (!attempt.claimed || (attempt.adopted && attempt.lifetime.signal.aborted)) return null;
	if (input.signal.aborted || !stillCurrent(attempt) || attempt.taken || !attempt.admitted) {
		throw new Error(attempt.failure);
	}
	attempt.taken = true;
	const worker = attempt.admitted;
	const stop = () => close(attempt);
	input.signal.addEventListener('abort', stop, { once: true });
	return Object.freeze({
		host: worker.host,
		witness: worker.witness,
		confirmHandover() {
			if (!stillCurrent(attempt)) throw new Error('invalidated_snapshot');
			attempt.adopted = true;
			performance.mark('openmates:rust:auth-first-session-adopted');
		},
		close() { input.signal.removeEventListener('abort', stop); close(attempt); },
	});
}
