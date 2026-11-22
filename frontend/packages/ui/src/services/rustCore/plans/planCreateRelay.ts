/**
 * Web relay of assistant-initiated Plan creation (`openmates.plan_create_request` v1).
 * The Rust core (`work` op `planCreateRequestDecide`) validates the server request and
 * returns the Plan and assumption inputs plus the result frames; this module only runs
 * the existing encrypted creates (userPlanService) and sends `plan_create_result`.
 * Request payloads and plaintext are never logged.
 */
import { setPlanCreateRequestsCapabilityEnabled } from '../../../config/api';
import { webSocketService } from '../../websocketService';
import type { CreatePlanAssumptionInput, CreateUserPlanInput, UserPlanViewModel } from '../../userPlanService';

export interface PlanCreateResult {
	request_id: string;
	status: 'created' | 'failed';
	plan_id?: string;
	error_code?: string;
}

/** The core's decision for one request. */
export type PlanCreateDecision =
	| { ok: false; result: PlanCreateResult }
	| {
		ok: true;
		request_id: string;
		chat_id: string;
		/** The chat's active Project as named by the server (empty when it named none). */
		project_ids: string[];
		plan: CreateUserPlanInput;
		assumptions: CreatePlanAssumptionInput[];
		created: PlanCreateResult;
		failed: PlanCreateResult;
		conflict: PlanCreateResult;
	};

export interface PlanCreateRelayDeps {
	decide(event: Record<string, unknown>, nowS: number): Promise<PlanCreateDecision>;
	projectIdsForChat(chatId: string): Promise<string[]>;
	createPlan(input: CreateUserPlanInput): Promise<UserPlanViewModel>;
	createAssumption(plan: UserPlanViewModel, input: CreatePlanAssumptionInput): Promise<unknown>;
	send(type: string, payload: unknown): Promise<void>;
	on(type: string, handler: (payload: unknown) => void): void;
	off(type: string, handler: (payload: unknown) => void): void;
	setCapability(enabled: boolean): void;
}

const defaultDeps: PlanCreateRelayDeps = {
	// Heavy workspace services load on the first request, not at install.
	decide: async (event, nowS) => {
		const { workClient, workDecide } = await import('../../work/workRust');
		const client = workClient();
		if (!client) throw Object.assign(new Error('core unavailable'), { code: 'core_unavailable' });
		return workDecide<PlanCreateDecision>(client, 'planCreateRequestDecide', { event, now_s: nowS });
	},
	projectIdsForChat: async (chatId) =>
		(await (await import('../../chatProjectService')).loadChatProjectIndex()).filter((project) => project.chats.some((chat) => chat.chatId === chatId)).map((project) => project.id),
	createPlan: async (input) => (await import('../../userPlanService')).createUserPlan(input),
	createAssumption: async (plan, input) => (await import('../../userPlanService')).createPlanAssumption(plan, input),
	send: (type, payload) => webSocketService.sendMessage(type, payload),
	on: (type, handler) => webSocketService.on(type, handler),
	off: (type, handler) => webSocketService.off(type, handler),
	setCapability: setPlanCreateRequestsCapabilityEnabled
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/** Stable error code for the log; never the message. */
function codeOf(error: unknown): string {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'plan_create_failed';
}

const isConflict = (error: unknown) => error instanceof Error && /\(409\)/.test(error.message);

/** Runs the creates of one validated request and returns the report to send. */
async function execute(deps: PlanCreateRelayDeps, decision: Extract<PlanCreateDecision, { ok: true }>): Promise<PlanCreateResult> {
	// The server's focus binding names the chat's Project. A chat bound by a
	// composer mention is not a filed Project item, so the sidebar index alone
	// misses it; it stays the source only when the server named none.
	const projectIds = decision.project_ids.length > 0 ? decision.project_ids : await deps.projectIdsForChat(decision.chat_id);
	if (projectIds.length === 0) {
		console.warn('[PlanCreate] refused', 'PLAN_PROJECT_REQUIRED');
		return { ...decision.failed, error_code: 'PLAN_PROJECT_REQUIRED' };
	}
	try {
		const plan = await deps.createPlan({ ...decision.plan, linkedProjectIds: projectIds });
		for (const assumption of decision.assumptions) await deps.createAssumption(plan, assumption);
	} catch (error) {
		console.warn('[PlanCreate] create failed', codeOf(error));
		return isConflict(error) ? decision.conflict : decision.failed;
	}
	return decision.created;
}

/**
 * Registers the `plan_create_requested` handler and enables the `plan_create_requests`
 * capability. A repeated request id gets the stored report again and creates nothing.
 * Returns the uninstall function.
 */
export function installPlanCreateRelay(deps: PlanCreateRelayDeps = defaultDeps): () => void {
	let queue: Promise<void> = Promise.resolve();
	let stopped = false;
	const reports = new Map<string, PlanCreateResult>();
	const handler = (payload: unknown) => {
		if (!isRecord(payload)) return;
		queue = queue.then(async () => {
			if (stopped) return;
			const decision = await deps.decide(payload, Math.floor(Date.now() / 1000));
			let result: PlanCreateResult;
			if (!decision.ok) {
				result = decision.result;
				console.warn('[PlanCreate] refused', result.error_code);
			} else {
				result = reports.get(decision.request_id) ?? await execute(deps, decision);
				reports.set(decision.request_id, result);
			}
			if (!stopped) await deps.send('plan_create_result', result);
		}).catch((error) => console.warn('[PlanCreate] request failed', codeOf(error)));
	};
	deps.on('plan_create_requested', handler);
	deps.setCapability(true);
	return () => {
		stopped = true;
		deps.off('plan_create_requested', handler);
		deps.setCapability(false);
	};
}
