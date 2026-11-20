/**
 * `projectFileJobs` namespace installer of the shared Rust core Worker
 * (VITE_OPENMATES_RUST_CORE builds only). Marshalling only: each call runs on
 * the ADMITTED client of the bound history `core` lease, borrowed through
 * coreClientBorrow (per-chat job state lives on that Client, so every call uses
 * it). The core decides frames, prompts and applied changes; results are
 * validated for shape and refused when a frame is not claim/result/reject.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import {
	PROJECT_FILE_JOB_FRAME_NAMES, isProjectFileJobsUnitClose,
	type ProjectFileJobEventKind, type ProjectFileJobStep, type ProjectFileJobsProtocol
} from './projectFileJobsProtocol';

/** Bounded wait for the history dispatcher to become idle. */
export const PROJECT_FILE_JOBS_BORROW_TIMEOUT_MS = 10_000;

/** BrowserCoreClient export of browser_project_file_jobs.rs (steps resolve to JSON). */
export interface ProjectFileJobsClient {
	project_file_job_step(handle: string, generation: number, kind: string, eventJson: string, interactive: boolean): Promise<string>;
	project_file_job_decide(handle: string, generation: number, chatId: string, operationId: string, accept: boolean): Promise<string>;
	project_file_job_set_privacy(handle: string, generation: number, chatId: string, projectId: string, enabled: boolean, memoriesJson: string, sealed: string | null): Promise<void>;
	project_file_job_set_mappings(handle: string, generation: number, chatId: string, mappingsJson: string): void | Promise<void>;
}

export interface ProjectFileJobsDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;
const KINDS: ReadonlySet<string> = new Set<ProjectFileJobEventKind>(['project_file_operation_available', 'project_file_operation_request']);
const FRAMES: ReadonlySet<string> = new Set(PROJECT_FILE_JOB_FRAME_NAMES);
const PROTOCOL = 'project_file_jobs_protocol';

/** Core rejections are stable code strings; keep them, never internal text. */
function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'project_file_jobs_failed';
}

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

/** Strict parse of the core's step JSON; anything off-contract is a protocol refusal. */
export function parseProjectFileJobStep(raw: unknown): ProjectFileJobStep {
	if (typeof raw !== 'string') throw new UnitRefusal(PROTOCOL);
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		throw new UnitRefusal(PROTOCOL);
	}
	if (!isRecord(value) || !Array.isArray(value.frames) || !Array.isArray(value.prompts)
		|| !Array.isArray(value.applied) || !Array.isArray(value.notices)) throw new UnitRefusal(PROTOCOL);
	for (const frame of value.frames) {
		if (!isRecord(frame) || typeof frame.name !== 'string' || !FRAMES.has(frame.name) || !isRecord(frame.payload)) throw new UnitRefusal(PROTOCOL);
	}
	if (!value.prompts.every(isRecord) || !value.applied.every(isRecord) || !value.notices.every((n) => typeof n === 'string')) throw new UnitRefusal(PROTOCOL);
	const step = { frames: value.frames, prompts: value.prompts, applied: value.applied, notices: value.notices } as ProjectFileJobStep;
	if (value.privacy !== undefined && value.privacy !== null) {
		const privacy = value.privacy;
		if (!isRecord(privacy) || typeof privacy.chat_id !== 'string' || typeof privacy.project_id !== 'string' || typeof privacy.ciphertext !== 'string') throw new UnitRefusal(PROTOCOL);
		step.privacy = { chat_id: privacy.chat_id, project_id: privacy.project_id, ciphertext: privacy.ciphertext };
	}
	return step;
}

const defaultDeps = (): ProjectFileJobsDeps => ({
	borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs)
});

export function createProjectFileJobsHandlers(principal: string, deps: ProjectFileJobsDeps,
	lifetime: AbortSignal): UnitHandlers<ProjectFileJobsProtocol> {
	/** Runs `work` on the one borrowed admitted client; refusals are stable codes. */
	async function withClient<T>(work: (client: ProjectFileJobsClient, handle: string, generation: number) => Promise<T>): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, PROJECT_FILE_JOBS_BORROW_TIMEOUT_MS);
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		try {
			return await work(borrow.client as unknown as ProjectFileJobsClient, borrow.status.handle, borrow.status.generation);
		} catch (error) {
			throw new UnitRefusal(code(error));
		} finally {
			borrow.release();
		}
	}
	return {
		async step(payload) {
			const request = payload as { kind?: unknown; event?: unknown; interactive?: unknown } | null;
			if (typeof request?.kind !== 'string' || !KINDS.has(request.kind)) throw new UnitRefusal('project_file_jobs_bad_kind');
			if (!isRecord(request.event)) throw new UnitRefusal('project_file_jobs_bad_event');
			if (typeof request.interactive !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_interactive');
			const { kind, event, interactive } = request as { kind: string; event: Record<string, unknown>; interactive: boolean };
			return withClient(async (client, handle, generation) =>
				parseProjectFileJobStep(await client.project_file_job_step(handle, generation, kind, JSON.stringify(event), interactive)));
		},
		async decide(payload) {
			const request = payload as { chatId?: unknown; operationId?: unknown; accept?: unknown } | null;
			if (typeof request?.chatId !== 'string' || !request.chatId) throw new UnitRefusal('project_file_jobs_bad_chat');
			if (typeof request.operationId !== 'string' || !request.operationId) throw new UnitRefusal('project_file_jobs_bad_operation');
			if (typeof request.accept !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_accept');
			const { chatId, operationId, accept } = request as { chatId: string; operationId: string; accept: boolean };
			return withClient(async (client, handle, generation) =>
				parseProjectFileJobStep(await client.project_file_job_decide(handle, generation, chatId, operationId, accept)));
		},
		async setPrivacy(payload) {
			const request = payload as { chatId?: unknown; projectId?: unknown; enabled?: unknown; memories?: unknown; sealed?: unknown } | null;
			if (typeof request?.chatId !== 'string' || !request.chatId) throw new UnitRefusal('project_file_jobs_bad_chat');
			if (typeof request.projectId !== 'string' || !request.projectId) throw new UnitRefusal('project_file_jobs_bad_project');
			if (typeof request.enabled !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_enabled');
			if (!Array.isArray(request.memories)) throw new UnitRefusal('project_file_jobs_bad_memories');
			if (request.sealed !== null && typeof request.sealed !== 'string') throw new UnitRefusal('project_file_jobs_bad_sealed');
			const { chatId, projectId, enabled, memories, sealed } = request as { chatId: string; projectId: string; enabled: boolean; memories: unknown[]; sealed: string | null };
			return withClient(async (client, handle, generation) => {
				await client.project_file_job_set_privacy(handle, generation, chatId, projectId, enabled, JSON.stringify(memories), sealed);
				return { ok: true as const };
			});
		},
		async setMappings(payload) {
			const request = payload as { chatId?: unknown; mappings?: unknown } | null;
			if (typeof request?.chatId !== 'string' || !request.chatId) throw new UnitRefusal('project_file_jobs_bad_chat');
			if (!Array.isArray(request.mappings)) throw new UnitRefusal('project_file_jobs_bad_mappings');
			const { chatId, mappings } = request as { chatId: string; mappings: unknown[] };
			return withClient(async (client, handle, generation) => {
				await client.project_file_job_set_mappings(handle, generation, chatId, JSON.stringify(mappings));
				return { ok: true as const };
			});
		}
	};
}

export function installProjectFileJobsUnit(context: UnitInstallContext, deps: ProjectFileJobsDeps = defaultDeps()): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<ProjectFileJobsProtocol>(port, createProjectFileJobsHandlers(principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stop();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isProjectFileJobsUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
