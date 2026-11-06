/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) natural-language Apps request: the page
 * adapter over the shared Rust core Worker `apps` unit. Loaded only by the
 * guarded branch of appsWorkspaceRequestService.ts, so default builds never
 * bundle it.
 *
 * Rust (web_apps/request.rs) decides: trimming, request id, the 24 KiB request
 * bounds, the large-context / attachment / workflow handoffs and their error
 * precedence, the exact interpreter POST body, and the interpretation outcome;
 * web_apps/schema.rs validates the restored native input. The page keeps the
 * browser primitives and out-of-scope services: identity stores, the reversible
 * privacy transform (appsWorkspaceRequestPrivacy), attachment preparation,
 * Fetch, the chat/workflow handlers, skill execution, ranking and retention.
 * Parity: packages/openmates-rust/src/web_apps/request_ts_vectors.json.
 */
import { get } from 'svelte/store';
import { getApiEndpoint } from '../../../config/api';
import { authStore } from '../../../stores/authState';
import { activeTeamContext } from '../../../stores/teamStore';
import { userProfile } from '../../../stores/userProfile';
import { anonymousChatStorage } from '../../anonymousChatStorage';
import { executeAppsSkill, getAppsSkillDetails } from '../../appsWorkspaceService';
import { mapAppsRequestText } from '../../appsWorkspaceRequestPrivacy';
import { rankAppsWorkspaceImageResults } from '../../appsWorkspaceImageRankingService';
import { prepareAppsRequestAttachments } from '../../appsWorkspaceAttachmentService';
import { retainAppsResult } from '../../appsWorkspaceResultsService';
import type { AppsRequestHandoff } from '../../appsWorkspaceContext';
import type { AppsWorkspaceRequestOptions, AppsWorkspaceRequestResult } from '../../appsWorkspaceRequestService';
import type { AppsHandoff } from './appsProtocol';
import { appsCall } from './appsUnitClient';

export interface AppsRequestPrivacy {
	protect(text: string): string;
	restore(text: string): string;
	assertCurrent(): void;
}

/** Platform hooks owned by appsWorkspaceRequestService.ts. */
export interface AppsRequestDeps {
	identityGeneration(): number;
	requestPrivacy(authenticated: boolean): Promise<AppsRequestPrivacy>;
}

const parseReason = (raw: string | null): string | undefined => (raw === null ? undefined : JSON.parse(raw));

/** `runAppsWorkspaceRequest` with every policy decision taken by Rust. */
export async function runRustAppsWorkspaceRequest(options: AppsWorkspaceRequestOptions, deps: AppsRequestDeps): Promise<AppsWorkspaceRequestResult> {
	const userId = get(userProfile).user_id;
	const authenticated = get(authStore).isAuthenticated;
	const generation = deps.identityGeneration();
	const team = get(activeTeamContext);
	const facts = JSON.stringify({
		text: options.text, appId: options.appId, requestId: options.requestId ?? null,
		timezone: options.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC',
		locale: options.locale ?? (typeof navigator !== 'undefined' ? navigator.language : 'en'),
		teamId: options.teamId ?? null, expectedUserId: authenticated && userId ? userId : null, guest: options.guest,
		attachmentTypes: (options.attachments ?? []).map(file => file.type), hasChat: Boolean(options.onChat),
	});
	const plan = await appsCall('requestPlan', { facts, context: options.context ? JSON.stringify(options.context) : '' });
	if (plan.kind === 'error') throw new Error(plan.message);
	const { text, requestId } = plan;
	if ((options.teamId ?? null) !== team.teamId) throw new Error('team_context_changed');
	const anonymousId = options.guest ? anonymousChatStorage.getAnonymousId() : null;
	let assertPrivacy = () => {};
	const assertIdentity = () => {
		if (generation !== deps.identityGeneration() || get(userProfile).user_id !== userId || get(authStore).isAuthenticated !== authenticated || (anonymousId !== null && anonymousChatStorage.getAnonymousId() !== anonymousId)) throw new Error('account_context_changed');
		const currentTeam = get(activeTeamContext);
		if (currentTeam.teamId !== team.teamId || currentTeam.epoch !== team.epoch) throw new Error('team_context_changed');
		if (options.signal?.aborted) throw options.signal.reason ?? new DOMException('Aborted', 'AbortError');
		assertPrivacy();
	};
	assertIdentity();
	/** Runs a Rust handoff decision; `withReason` keeps the TS payload shape (an interpreted handoff always carries `reason`). */
	const handOff = async (decision: AppsHandoff, withReason: boolean): Promise<string | undefined> => {
		if (decision.identityFirst) assertIdentity();
		if (decision.unavailable) throw new Error(decision.unavailable);
		if (!decision.identityFirst) assertIdentity();
		const reason = parseReason(decision.reason);
		const payload: AppsRequestHandoff = { text, context: options.context, attachments: options.attachments, ...(withReason || reason !== undefined ? { reason } : {}) };
		const handler = decision.target === 'chat' ? options.onChat : options.onWorkflow;
		// `unavailable` is null only when Rust saw the handler.
		await handler!(payload);
		return reason;
	};
	const planHandoff = async (decision: AppsHandoff): Promise<AppsWorkspaceRequestResult> => {
		const reason = await handOff(decision, false);
		return { action: 'chat', requestId, ...(reason !== undefined ? { reason } : {}) };
	};
	if (plan.next.kind === 'error') throw new Error(plan.next.message);
	if (plan.next.kind === 'handoff') return planHandoff(plan.next);
	const privacy = await deps.requestPrivacy(authenticated);
	assertPrivacy = privacy.assertCurrent;
	assertIdentity();
	const protectedText = privacy.protect(text);
	const protectedContext = options.context ? JSON.stringify(mapAppsRequestText(options.context, privacy.protect)) : '';
	const prepared = options.attachments?.length ? await prepareAppsRequestAttachments(options.attachments, { signal: options.signal, chatId: options.context?.chat_id, assertCurrent: assertIdentity }) : null;
	assertIdentity();
	const protectedAttachments = prepared ? JSON.stringify(prepared.attachments.map(({ input, ...descriptor }) => ({ ...mapAppsRequestText(descriptor, privacy.protect), ...(input ? { input } : {}) }))) : '';
	const request = await appsCall('requestBody', {
		facts, requestId, protectedText, protectedContext, protectedAttachments,
		attachments: prepared ? JSON.stringify(prepared.attachments) : '', assets: prepared ? JSON.stringify(prepared.assets) : '',
	});
	if (request.kind === 'error') throw new Error(request.message);
	if (request.kind === 'handoff') return planHandoff(request);
	const response = await fetch(getApiEndpoint('/v1/apps/workspace/interpret'), {
		method: 'POST', credentials: 'include', signal: options.signal,
		headers: { 'Content-Type': 'application/json', ...(options.guest ? { 'X-OpenMates-Anonymous-ID': anonymousChatStorage.getAnonymousId() } : {}) },
		body: request.body,
	});
	const bodyText = await response.text();
	const decision = await appsCall('interpretation', {
		status: response.status, ok: response.ok, text: bodyText,
		hasAttachments: Boolean(options.attachments?.length), hasChat: Boolean(options.onChat), hasWorkflow: Boolean(options.onWorkflow),
	});
	// The TS service's `response.json()` rejects with the platform SyntaxError before any identity check.
	if (decision.kind === 'syntax') {
		JSON.parse(bodyText);
		throw new Error('protocol');
	}
	assertIdentity();
	if (decision.kind === 'error') throw new Error(decision.message);
	if (decision.kind === 'handoff') {
		await handOff(decision, true);
		return { action: decision.action, requestId, reason: parseReason(decision.resultReason) };
	}
	const skillId = decision.skillId;
	const result: AppsWorkspaceRequestResult = { action: 'execute', requestId, reason: parseReason(decision.reason) };
	const nativeInput = mapAppsRequestText(JSON.parse(decision.input) as Record<string, unknown>, privacy.restore);
	const metadata = await getAppsSkillDetails(options.appId, skillId, options.signal);
	assertIdentity();
	const issues = await appsCall('validateInput', { schema: JSON.stringify(metadata.input_schema), input: JSON.stringify(nativeInput) });
	if (issues.length) throw new Error('invalid_native_input');
	let acceptedNotified = false;
	const notifyAccepted = async (embedId: string) => {
		assertIdentity();
		if (acceptedNotified) return;
		acceptedNotified = true;
		await options.onAccepted?.({ embedId, skillId, input: nativeInput });
	};
	assertIdentity();
	let responseBody = await executeAppsSkill(options.appId, skillId, nativeInput, {
		guest: options.guest, teamId: options.teamId, signal: options.signal, assertContext: assertIdentity, metadata,
		onTaskSubmitted: async taskId => {
			assertIdentity();
			const embedId = await retainAppsResult({ appId: options.appId, skillId, input: nativeInput,
				response: { task_id: taskId, status: 'processing' }, guest: options.guest, teamId: options.teamId, requestId, requestText: text, newRequest: true, persistence: 'background' });
			await notifyAccepted(embedId);
		},
	});
	assertIdentity();
	if (prepared && Object.keys(prepared.assets).length) responseBody = await rankAppsWorkspaceImageResults(responseBody, { appId: options.appId, text, prepareModelText: privacy.protect, expectedUserId: userId ?? undefined, assets: prepared.assets, teamId: options.teamId, signal: options.signal, assertCurrent: assertIdentity });
	assertIdentity();
	const embedId = await retainAppsResult({ appId: options.appId, skillId, input: nativeInput,
		response: responseBody, guest: options.guest, teamId: options.teamId, requestId, requestText: text, newRequest: true, persistence: 'background' });
	await notifyAccepted(embedId);
	return { ...result, skillId, input: nativeInput, embedId };
}
