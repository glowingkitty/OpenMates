/**
 * `apps` namespace installer of the shared Rust core Worker.
 *
 * Serves the Apps skill execution policy (appsProtocol.ts) on the unit port
 * from the realm's single WASM binding. It holds no per-account state and does
 * no IO, so it is a pre-bind namespace: guests run app skills before any
 * principal exists. A malformed payload answers the fixed code `protocol`; any
 * binding rejection answers `protocol` too (the Rust boundary's only code).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { isAppsBinding, type AppsBinding, type AppsHttpResponse, type AppsUnitProtocol } from './appsProtocol';

const isString = (value: unknown): value is string => typeof value === 'string';
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
function isStatus(value: unknown): value is number {
	return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 999;
}
function http(payload: unknown): AppsHttpResponse {
	if (!isRecord(payload) || !isStatus(payload.status) || typeof payload.ok !== 'boolean' || !isString(payload.text)) throw new UnitRefusal('protocol');
	return { status: payload.status, ok: payload.ok, text: payload.text };
}
function record(payload: unknown): Record<string, unknown> {
	if (!isRecord(payload)) throw new UnitRefusal('protocol');
	return payload;
}
function text(value: unknown): string {
	if (!isString(value)) throw new UnitRefusal('protocol');
	return value;
}
function flag(value: unknown): boolean {
	if (typeof value !== 'boolean') throw new UnitRefusal('protocol');
	return value;
}
/** Binding results are JSON text; a thrown JsValue is the Rust `protocol` code. */
function call<T>(run: () => string): T {
	let json: string;
	try {
		json = run();
	} catch {
		throw new UnitRefusal('protocol');
	}
	return JSON.parse(json) as T;
}

export function createAppsHandlers(binding: AppsBinding): UnitHandlers<AppsUnitProtocol> {
	return {
		detailsRequest: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_details_request(text(p.app), text(p.skill), flag(p.hasSignal)));
		},
		detailsOutcome: (payload) => {
			const p = http(payload);
			return call(() => binding.apps_details_outcome(p.status, p.ok, p.text));
		},
		executionRequest: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_execution_request(text(p.app), text(p.skill), flag(p.guest), text(p.teamId), text(p.metadata)));
		},
		availabilityRequest: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_availability_request(text(p.app), text(p.skill)));
		},
		availabilityOutcome: (payload) => {
			const p = http(payload);
			return call(() => binding.apps_availability_outcome(p.status, p.ok, p.text));
		},
		skillResponse: (payload) => {
			const p = http(payload);
			return call(() => binding.apps_skill_response(p.status, p.ok, p.text, flag(record(payload).guest)));
		},
		pollStep: (payload) => {
			const p = http(payload);
			return call(() => binding.apps_poll_step(text(record(payload).taskId), p.status, p.ok, p.text));
		},
		assembleTasks: (payload) => {
			const p = record(payload);
			if (!Array.isArray(p.polls) || !p.polls.every(isString)) throw new UnitRefusal('protocol');
			const polls = JSON.stringify(p.polls);
			return call(() => binding.apps_assemble_tasks(text(p.envelope), polls, flag(p.checkFailure)));
		},
		taskResult: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_task_result(text(p.text)));
		},
		requestPlan: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_request_plan(text(p.facts), text(p.context)));
		},
		requestBody: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_request_body(text(p.facts), text(p.requestId), text(p.protectedText), text(p.protectedContext),
				text(p.attachments), text(p.protectedAttachments), text(p.assets)));
		},
		interpretation: (payload) => {
			const p = http(payload);
			const q = record(payload);
			return call(() => binding.apps_interpretation(p.ok, p.text, flag(q.hasAttachments), flag(q.hasChat), flag(q.hasWorkflow)));
		},
		validateInput: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_validate_input(text(p.schema), text(p.input)));
		},
		retentionPlan: (payload) => {
			const p = record(payload);
			return call(() => binding.apps_retention_plan(text(p.facts), text(p.response), text(p.previous)));
		},
		outboxScopeValid: (payload) => {
			const p = record(payload);
			try {
				return binding.apps_outbox_scope_valid(text(p.scope));
			} catch (error) {
				if (error instanceof UnitRefusal) throw error;
				throw new UnitRefusal('protocol');
			}
		},
		freshRecommendations: (payload) => {
			const p = record(payload);
			if (typeof p.now !== 'number' || !Number.isFinite(p.now)) throw new UnitRefusal('protocol');
			const now = p.now;
			return call(() => binding.apps_fresh_recommendations(text(p.items), now));
		},
	};
}

export function installAppsUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isAppsBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<AppsUnitProtocol>(port, createAppsHandlers(context.binding));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
