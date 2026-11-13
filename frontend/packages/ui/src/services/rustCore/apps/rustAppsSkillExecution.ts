/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) Apps skill execution: the page adapter
 * over the shared Rust core Worker `apps` unit. Loaded only by the guarded
 * branches of appsWorkspaceService.ts, so default builds never bundle it.
 *
 * Rust (web_apps.rs) decides: details request/credentials/cache policy, error
 * detail text, pre-dispatch admission and paths, anonymous quote, skill failure,
 * accepted task ids, each poll step (delay, budget, failure text) and the
 * resolved envelope. The page keeps only browser primitives: Fetch, the
 * caller's identity/abort checks, timers and the in-memory promise caches.
 * The public functions keep the TypeScript service's signatures and errors.
 */
import type { AppsSkillDetails, AppsSkillGuestEligibility, AppsSkillResponse } from '../../../types/appsWorkspace';
import type { AppsHttpResponse } from './appsProtocol';
import { appsCall } from './appsUnitClient';

export type AppsExecutionIdentity = { userId: string | null; anonymousId: string | null; authGeneration: number };

/** Platform hooks owned by appsWorkspaceService.ts (stores, config, anonymous id). */
export interface AppsServiceDeps {
	apiEndpoint(path: string): string;
	anonymousId(): string;
	authGeneration(): number;
	captureIdentity(guest: boolean, expectedUserId?: string): AppsExecutionIdentity;
	assertIdentity(identity: AppsExecutionIdentity): void;
}

export type AppsSkillExecuteOptions = {
	guest: boolean;
	teamId?: string;
	signal?: AbortSignal;
	metadata?: AppsSkillDetails;
	assertContext?: () => void;
	onTaskSubmitted?: (taskId: string) => Promise<void>;
};

async function read(response: Response): Promise<AppsHttpResponse> {
	return { status: response.status, ok: response.ok, text: await response.text() };
}
/** Rust reported whether the body parsed; an unparsable body is `{}` (service contract). */
function body<T>(raw: AppsHttpResponse, valid: boolean): T {
	return (valid ? JSON.parse(raw.text) : {}) as T;
}
function aborted(signal?: AbortSignal): unknown {
	return signal?.reason ?? new DOMException('Aborted', 'AbortError');
}

type Accepted = { text: string; ids: string[] };

export interface RustAppsSkillExecution {
	getAppsSkillDetails(appId: string, skillId: string, signal?: AbortSignal): Promise<AppsSkillDetails>;
	getAnonymousAppsSkillAvailability(appId: string, skillId: string, input: Record<string, unknown>, signal?: AbortSignal): Promise<AppsSkillGuestEligibility>;
	pollAppsSkillTask(taskId: string, options?: { signal?: AbortSignal; expectedUserId?: string }): Promise<unknown>;
	executeAppsSkill(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions): Promise<AppsSkillResponse>;
}

export function createRustAppsSkillExecution(deps: AppsServiceDeps): RustAppsSkillExecution {
	const detailsCache = new Map<string, Promise<AppsSkillDetails>>();
	const pendingExecutions = new Map<string, Promise<AppsSkillResponse>>();
	const acceptedExecutions = new Map<string, Accepted>();

	async function fetchDetails(path: string, credentials: RequestCredentials, signal?: AbortSignal): Promise<AppsSkillDetails> {
		const requestAuthGeneration = deps.authGeneration();
		const raw = await read(await fetch(deps.apiEndpoint(path), { credentials, signal }));
		const outcome = await appsCall('detailsOutcome', raw);
		if (credentials === 'include' && requestAuthGeneration !== deps.authGeneration()) throw new Error('account_context_changed');
		if (outcome.kind === 'error') throw new Error(outcome.message);
		return body<AppsSkillDetails>(raw, outcome.valid);
	}

	async function getAppsSkillDetails(appId: string, skillId: string, signal?: AbortSignal): Promise<AppsSkillDetails> {
		const key = `${appId}/${skillId}`;
		const cached = detailsCache.get(key);
		if (cached && !signal) return cached;
		const request = await appsCall('detailsRequest', { app: appId, skill: skillId, hasSignal: Boolean(signal) });
		if (!request.cacheable) return fetchDetails(request.path, request.credentials, signal);
		const existing = detailsCache.get(key);
		if (existing) return existing;
		const pending = fetchDetails(request.path, request.credentials).catch((error) => {
			detailsCache.delete(key);
			throw error;
		});
		detailsCache.set(key, pending);
		return pending;
	}

	async function availabilityAt(path: string, input: Record<string, unknown>, signal?: AbortSignal): Promise<AppsSkillGuestEligibility> {
		const response = await fetch(deps.apiEndpoint(path), {
			method: 'POST', cache: 'no-store', signal,
			headers: { 'Content-Type': 'application/json', 'X-OpenMates-Anonymous-ID': deps.anonymousId() },
			body: JSON.stringify(input),
		});
		return appsCall('availabilityOutcome', await read(response));
	}

	async function getAnonymousAppsSkillAvailability(appId: string, skillId: string, input: Record<string, unknown>, signal?: AbortSignal) {
		const request = await appsCall('availabilityRequest', { app: appId, skill: skillId });
		return availabilityAt(request.path, input, signal);
	}

	/** Resolves one accepted task to the raw text of its completed status response. */
	async function pollTask(taskId: string, signal: AbortSignal | undefined, identity: AppsExecutionIdentity | undefined): Promise<string> {
		const started = Date.now();
		for (;;) {
			if (identity) deps.assertIdentity(identity);
			if (signal?.aborted) throw aborted(signal);
			const raw = await read(await fetch(deps.apiEndpoint(`/v1/tasks/${encodeURIComponent(taskId)}`), { credentials: 'include', signal }));
			if (identity) deps.assertIdentity(identity);
			const step = await appsCall('pollStep', { ...raw, taskId });
			if (step.kind === 'completed') return raw.text;
			if (step.kind === 'error') throw new Error(step.message);
			await new Promise<void>((resolve, reject) => {
				const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, step.delayMs);
				function onAbort() { clearTimeout(timer); reject(aborted(signal)); }
				signal?.addEventListener('abort', onAbort, { once: true });
			});
			if (Date.now() - started >= step.deadlineMs) throw new Error(step.timeoutMessage);
		}
	}

	async function pollAppsSkillTask(taskId: string, options: { signal?: AbortSignal; expectedUserId?: string } = {}): Promise<unknown> {
		const identity = deps.captureIdentity(false, options.expectedUserId);
		const text = await pollTask(taskId, options.signal, identity);
		const result = await appsCall('taskResult', { text });
		return result.kind === 'done' ? JSON.parse(result.text) : undefined;
	}

	/** `checkFailure` is false when resuming an accepted execution (service contract). */
	async function resolveAccepted(accepted: Accepted, options: AppsSkillExecuteOptions, identity: AppsExecutionIdentity, checkFailure: boolean): Promise<AppsSkillResponse> {
		for (const id of accepted.ids) {
			deps.assertIdentity(identity);
			await options.onTaskSubmitted?.(id);
			deps.assertIdentity(identity);
		}
		const polls = await Promise.all(accepted.ids.map((id) => pollTask(id, options.signal, identity)));
		const assembled = await appsCall('assembleTasks', { envelope: accepted.text, polls, checkFailure });
		if (assembled.kind === 'error') throw new Error(assembled.message);
		return JSON.parse(assembled.text) as AppsSkillResponse;
	}

	async function executeOnce(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions, key: string, identity: AppsExecutionIdentity): Promise<AppsSkillResponse> {
		const metadata = options.metadata ?? await getAppsSkillDetails(appId, skillId, options.signal);
		const request = await appsCall('executionRequest', { app: appId, skill: skillId, guest: options.guest,
			teamId: options.teamId ?? '', metadata: JSON.stringify(metadata) });
		if (request.kind === 'error') throw new Error(request.message);
		if (request.availabilityPath !== null) {
			const eligibility = await availabilityAt(request.availabilityPath, input, options.signal);
			if (!eligibility.allowed) throw new Error(eligibility.reason ?? 'signup_required');
		}
		deps.assertIdentity(identity);
		options.assertContext?.();
		const url = new URL(deps.apiEndpoint(request.path));
		if (request.teamId !== null) url.searchParams.set('team_id', request.teamId);
		const response = await fetch(url.toString(), {
			method: 'POST', credentials: 'include', signal: options.signal,
			headers: { 'Content-Type': 'application/json', ...(options.guest ? { 'X-OpenMates-Anonymous-ID': deps.anonymousId() } : {}) },
			body: JSON.stringify(input),
		});
		const raw = await read(response);
		const outcome = await appsCall('skillResponse', { ...raw, guest: options.guest });
		deps.assertIdentity(identity);
		if (outcome.kind === 'error') throw new Error(outcome.message);
		if (outcome.kind === 'done') return body<AppsSkillResponse>(raw, outcome.valid);
		const accepted = { text: raw.text, ids: outcome.ids };
		acceptedExecutions.set(key, accepted);
		return resolveAccepted(accepted, options, identity, true);
	}

	function executeAppsSkill(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions): Promise<AppsSkillResponse> {
		const identity = deps.captureIdentity(options.guest);
		const key = JSON.stringify([identity.userId, identity.anonymousId, identity.authGeneration, appId, skillId, input, options.guest, options.teamId ?? null]);
		const pending = pendingExecutions.get(key);
		if (pending) return pending;
		const accepted = acceptedExecutions.get(key);
		const operation = (accepted ? resolveAccepted(accepted, options, identity, false) : executeOnce(appId, skillId, input, options, key, identity))
			.then((result) => { deps.assertIdentity(identity); acceptedExecutions.delete(key); return result; })
			.finally(() => pendingExecutions.delete(key));
		pendingExecutions.set(key, operation);
		return operation;
	}

	return { getAppsSkillDetails, getAnonymousAppsSkillAvailability, pollAppsSkillTask, executeAppsSkill };
}
