/**
 * `apps` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust Apps skill execution
 * policy (packages/openmates-rust/src/web_apps.rs). The page keeps Fetch,
 * identity stores, timers and caches and sends only the response status and raw
 * body text; the unit answers small outcomes. Bodies the page needs come back
 * as the original JSON text (`assembleTasks`), never re-serialized.
 */
import type { UnitProtocol } from '../host/unitPort';

export type AppsMessageOutcome = { kind: 'error'; message: string };

export interface AppsDetailsRequest { path: string; credentials: 'include' | 'omit'; cacheable: boolean }
export type AppsDetailsOutcome = { kind: 'ok'; valid: boolean } | AppsMessageOutcome;
export type AppsExecutionRequest =
	| { kind: 'ok'; path: string; teamId: string | null; availabilityPath: string | null }
	| AppsMessageOutcome;
export interface AppsAvailabilityOutcome { allowed: boolean; reason: string | null }
export type AppsSkillResponseOutcome = { kind: 'done'; valid: boolean } | { kind: 'tasks'; ids: string[] } | AppsMessageOutcome;
export type AppsPollStep =
	| { kind: 'completed' }
	| { kind: 'retry'; delayMs: number; deadlineMs: number; timeoutMessage: string }
	| AppsMessageOutcome;
export type AppsAssembledTasks = { kind: 'done'; text: string } | AppsMessageOutcome;
/** `absent` stands for an `undefined` result member. */
export type AppsTaskResult = { kind: 'done'; text: string } | { kind: 'absent' };

export interface AppsHttpResponse { status: number; ok: boolean; text: string }

export interface AppsUnitProtocol extends UnitProtocol {
	detailsRequest: { request: { app: string; skill: string; hasSignal: boolean }; response: AppsDetailsRequest };
	detailsOutcome: { request: AppsHttpResponse; response: AppsDetailsOutcome };
	executionRequest: { request: { app: string; skill: string; guest: boolean; teamId: string; metadata: string }; response: AppsExecutionRequest };
	availabilityRequest: { request: { app: string; skill: string }; response: { path: string } };
	availabilityOutcome: { request: AppsHttpResponse; response: AppsAvailabilityOutcome };
	skillResponse: { request: AppsHttpResponse & { guest: boolean }; response: AppsSkillResponseOutcome };
	pollStep: { request: AppsHttpResponse & { taskId: string }; response: AppsPollStep };
	assembleTasks: { request: { envelope: string; polls: string[]; checkFailure: boolean }; response: AppsAssembledTasks };
	taskResult: { request: { text: string }; response: AppsTaskResult };
}

/** Worker module exports (snake_case, JSON strings) of browser_apps.rs. */
export interface AppsBinding {
	apps_details_request(app: string, skill: string, hasSignal: boolean): string;
	apps_details_outcome(status: number, ok: boolean, text: string): string;
	apps_execution_request(app: string, skill: string, guest: boolean, teamId: string, metadataJson: string): string;
	apps_availability_request(app: string, skill: string): string;
	apps_availability_outcome(status: number, ok: boolean, text: string): string;
	apps_skill_response(status: number, ok: boolean, text: string, guest: boolean): string;
	apps_poll_step(taskId: string, status: number, ok: boolean, text: string): string;
	apps_assemble_tasks(envelopeText: string, pollTextsJson: string, checkFailure: boolean): string;
	apps_task_result(pollText: string): string;
}

const BINDING_EXPORTS: readonly (keyof AppsBinding)[] = [
	'apps_details_request', 'apps_details_outcome', 'apps_execution_request', 'apps_availability_request',
	'apps_availability_outcome', 'apps_skill_response', 'apps_poll_step', 'apps_assemble_tasks', 'apps_task_result',
];

export function isAppsBinding(value: unknown): value is AppsBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
