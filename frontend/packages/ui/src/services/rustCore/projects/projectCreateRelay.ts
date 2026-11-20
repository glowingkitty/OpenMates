/**
 * Web relay of assistant-initiated Project creation (`openmates.project_create_request`
 * v1; projects.creation.assistant-inferred). The Rust core (`Client::project_create_step`,
 * shared Worker `projectFileJobs` unit) validates the request, creates the encrypted
 * Project and its default focus and decides the report; this module only feeds it the
 * server frames and sends the returned `project_create_result` on the main socket.
 * Payloads are never logged.
 */
import { setProjectCreateRequestsCapabilityEnabled } from '../../../config/api';
import { webSocketService } from '../../websocketService';
import { stepProjectCreate } from './projectFileJobsClient';
import type { ProjectCreateEventKind, ProjectCreateResult } from './projectFileJobsProtocol';

const CREATE_FRAMES: readonly ProjectCreateEventKind[] = ['project_create_requested', 'project_create_confirmed', 'project_create_error'];

export interface ProjectCreateRelayDeps {
	step(kind: ProjectCreateEventKind, event: Record<string, unknown>): Promise<ProjectCreateResult | null>;
	send(type: string, payload: unknown): Promise<void>;
	on(type: string, handler: (payload: unknown) => void): void;
	off(type: string, handler: (payload: unknown) => void): void;
	setCapability(enabled: boolean): void;
}

const defaultDeps: ProjectCreateRelayDeps = {
	step: stepProjectCreate,
	send: (type, payload) => webSocketService.sendMessage(type, payload),
	on: (type, handler) => webSocketService.on(type, handler),
	off: (type, handler) => webSocketService.off(type, handler),
	setCapability: setProjectCreateRequestsCapabilityEnabled
};

/** Stable error code for the log; never the message. */
function codeOf(error: unknown): string {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'project_create_failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Registers the creation frame handlers and enables the `project_create_requests`
 * capability. Install it before the Project agent clients: their reconnect then
 * advertises both. Returns the uninstall function.
 */
export function installProjectCreateRelay(deps: ProjectCreateRelayDeps = defaultDeps): () => void {
	// One chat at a time in arrival order, so a confirm or error frame never
	// overtakes the request it answers.
	let queue: Promise<void> = Promise.resolve();
	let stopped = false;
	const handlers = CREATE_FRAMES.map((kind) => {
		const handler = (payload: unknown) => {
			if (!isRecord(payload)) return;
			queue = queue.then(async () => {
				if (stopped) return;
				const result = await deps.step(kind, payload);
				if (result && !stopped) await deps.send('project_create_result', result);
			}).catch((error) => console.warn(`[ProjectCreate] ${kind} failed`, codeOf(error)));
		};
		deps.on(kind, handler);
		return [kind, handler] as const;
	});
	deps.setCapability(true);
	return () => {
		stopped = true;
		for (const [kind, handler] of handlers) deps.off(kind, handler);
		deps.setCapability(false);
	};
}
