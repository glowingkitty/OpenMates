/**
 * Web relay of the hosted Project sandbox key handover (`project_sandbox_key_request`).
 * The Rust core (`Client::answer_project_sandbox_key_request`, shared Worker
 * `projectFileJobs` unit) checks the chat and Project, seals the Project key to the
 * sandbox and returns the finished frame; this module only feeds it the server event
 * and sends that frame on the main socket. The key never reaches TypeScript and
 * payloads are never logged.
 */
import { webSocketService } from '../../websocketService';
import { answerProjectSandboxKey } from './projectFileJobsClient';
import type { ProjectSandboxKeyFrame } from './projectFileJobsProtocol';

const REQUEST_EVENT = 'project_sandbox_key_request';

export interface ProjectSandboxKeyRelayDeps {
	answer(event: Record<string, unknown>): Promise<ProjectSandboxKeyFrame>;
	send(type: string, payload: unknown): Promise<void>;
	on(type: string, handler: (payload: unknown) => void): void;
	off(type: string, handler: (payload: unknown) => void): void;
}

const defaultDeps: ProjectSandboxKeyRelayDeps = {
	answer: answerProjectSandboxKey,
	send: (type, payload) => webSocketService.sendMessage(type, payload),
	on: (type, handler) => webSocketService.on(type, handler),
	off: (type, handler) => webSocketService.off(type, handler)
};

/** Stable error code for the log; never the message. */
function codeOf(error: unknown): string {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'project_sandbox_key_failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/** Registers the request handler; a core refusal sends nothing so another device can answer. Returns the uninstall function. */
export function installProjectSandboxKeyRelay(deps: ProjectSandboxKeyRelayDeps = defaultDeps): () => void {
	let queue: Promise<void> = Promise.resolve();
	let stopped = false;
	const handler = (payload: unknown) => {
		if (!isRecord(payload)) return;
		queue = queue.then(async () => {
			if (stopped) return;
			const frame = await deps.answer(payload);
			if (!stopped) await deps.send(frame.event, frame.payload);
		}).catch((error) => console.warn('[ProjectSandboxKey] request failed', codeOf(error)));
	};
	deps.on(REQUEST_EVENT, handler);
	return () => {
		stopped = true;
		deps.off(REQUEST_EVENT, handler);
	};
}
