/**
 * `apps` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Every operation is a pure decision of the shared Rust Apps policy
 * (packages/openmates-rust/src/web_apps.rs and web_apps/{request,results,schema}.rs). The page keeps Fetch,
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

/** A chat/workflow handoff; `reason` is raw JSON text (null when absent). */
export interface AppsHandoff { kind: 'handoff'; target: 'chat' | 'workflow'; reason: string | null; identityFirst: boolean; unavailable: string | null }
export type AppsRequestPlan =
	| AppsMessageOutcome
	| { kind: 'ok'; text: string; requestId: string; next: AppsMessageOutcome | AppsHandoff | { kind: 'protect' } };
export type AppsRequestBody = AppsMessageOutcome | AppsHandoff | { kind: 'send'; body: string };
/** `input` and `reason` are raw JSON text so the page restores and validates the interpreter's own values. */
export type AppsInterpretation =
	| AppsMessageOutcome
	| { kind: 'syntax' }
	| (AppsHandoff & { action: 'chat' | 'workflow'; resultReason: string | null })
	| { kind: 'execute'; skillId: string; input: string; reason: string | null };
export interface AppsValidationIssue { code: string; path: string }
/** Paths are object keys and array indices from the response root. */
export type AppsRetentionPlan = AppsMessageOutcome | {
	kind: 'ok'; status: 'processing' | 'finished' | 'error' | 'cancelled'; results: (string | number)[][];
	children: { path: (string | number)[]; id: string; type: string }[]; resultIds: string[]; persistedIds: string[];
	resultCount: unknown; taskIds: string[]; metadataPath: string[];
};

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
	requestPlan: { request: { facts: string; context: string }; response: AppsRequestPlan };
	requestBody: { request: { facts: string; requestId: string; protectedText: string; protectedContext: string; attachments: string; protectedAttachments: string; assets: string }; response: AppsRequestBody };
	interpretation: { request: AppsHttpResponse & { hasAttachments: boolean; hasChat: boolean; hasWorkflow: boolean }; response: AppsInterpretation };
	validateInput: { request: { schema: string; input: string }; response: AppsValidationIssue[] };
	retentionPlan: { request: { facts: string; response: string; previous: string }; response: AppsRetentionPlan };
	outboxScopeValid: { request: { scope: string }; response: boolean };
	freshRecommendations: { request: { items: string; now: number }; response: number[] };
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
	apps_request_plan(factsJson: string, contextJson: string): string;
	apps_request_body(factsJson: string, requestId: string, protectedText: string, protectedContextJson: string, attachmentsJson: string, protectedAttachmentsJson: string, assetsJson: string): string;
	apps_interpretation(ok: boolean, text: string, hasAttachments: boolean, hasChat: boolean, hasWorkflow: boolean): string;
	apps_validate_input(schemaJson: string, inputJson: string): string;
	apps_retention_plan(factsJson: string, responseJson: string, previousContent: string): string;
	apps_outbox_scope_valid(scopeJson: string): boolean;
	apps_fresh_recommendations(itemsJson: string, nowMs: number): string;
}

const BINDING_EXPORTS: readonly (keyof AppsBinding)[] = [
	'apps_details_request', 'apps_details_outcome', 'apps_execution_request', 'apps_availability_request',
	'apps_availability_outcome', 'apps_skill_response', 'apps_poll_step', 'apps_assemble_tasks', 'apps_task_result',
	'apps_request_plan', 'apps_request_body', 'apps_interpretation', 'apps_validate_input', 'apps_retention_plan',
	'apps_outbox_scope_valid', 'apps_fresh_recommendations',
];

export function isAppsBinding(value: unknown): value is AppsBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
