/**
 * Web relay of hosted Project sandbox commits (`embed_revision_committed` with
 * `source: project_sandbox`). The event carries ids only; the Rust core
 * (`Client::describe_project_sandbox_commit`, shared Worker `projectFileJobs`
 * unit) checks the chat's Project focus, decrypts the committed file with this
 * device's Project key and returns the applied-change card, which is recorded
 * like a device-path write so the chat shows it (Apply and show changes).
 * Payloads and file text are never logged.
 */
import { webSocketService } from '../../websocketService';
import { recordProjectFileChange } from '../../../stores/projectFileApprovalStore';
import type { ProjectWriteApprovalRequest } from '../../projectFileJobTypes';
import { describeProjectSandboxCommit } from './projectFileJobsClient';

const COMMIT_EVENT = 'embed_revision_committed';

export interface ProjectSandboxCommitRelayDeps {
	describe(event: Record<string, unknown>): Promise<ProjectWriteApprovalRequest | null>;
	record(change: ProjectWriteApprovalRequest): void;
	on(type: string, handler: (payload: unknown) => void): void;
	off(type: string, handler: (payload: unknown) => void): void;
}

const defaultDeps: ProjectSandboxCommitRelayDeps = {
	describe: describeProjectSandboxCommit,
	record: recordProjectFileChange,
	on: (type, handler) => webSocketService.on(type, handler),
	off: (type, handler) => webSocketService.off(type, handler)
};

/** Stable error code for the log; never the message. */
function codeOf(error: unknown): string {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'project_sandbox_commit_failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/** Registers the commit handler (device commits are left to their own listeners). Returns the uninstall function. */
export function installProjectSandboxCommitRelay(deps: ProjectSandboxCommitRelayDeps = defaultDeps): () => void {
	let queue: Promise<void> = Promise.resolve();
	let stopped = false;
	const handler = (payload: unknown) => {
		if (!isRecord(payload) || payload.source !== 'project_sandbox') return;
		// In order: cards appear in commit order, one core call at a time.
		queue = queue.then(async () => {
			if (stopped) return;
			const change = await deps.describe(payload);
			if (change && !stopped) deps.record(change);
		}).catch((error) => console.warn('[ProjectSandboxCommit] card failed', codeOf(error)));
	};
	deps.on(COMMIT_EVENT, handler);
	return () => {
		stopped = true;
		deps.off(COMMIT_EVENT, handler);
	};
}
