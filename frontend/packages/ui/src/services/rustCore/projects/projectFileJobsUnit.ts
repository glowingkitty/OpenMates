/**
 * `projectFileJobs` namespace installer of the shared Rust core Worker
 * (VITE_OPENMATES_RUST_CORE builds only). Marshalling only: each call runs on
 * the ADMITTED client of the bound history `core` lease, borrowed through
 * coreClientBorrow. Per-chat job state (privacy layer, approvals) lives on the
 * borrowed Client and several Worker clients exist, so `step` and `decide` carry
 * the privacy inputs and install them (set_mappings, set_privacy) inside the
 * SAME borrow as the call they protect. The core decides frames, prompts and applied changes; results are
 * validated for shape and refused when a frame is not claim/result/reject.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { ProjectWriteApprovalRequest } from '../../projectFileJobTypes';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import {
	PROJECT_FILE_JOB_FRAME_NAMES, isProjectFileJobsUnitClose,
	type ProjectCreateResult, type ProjectFileJobEventKind, type ProjectFileJobStep, type ProjectFileJobsProtocol,
	type ProjectSandboxKeyFrame
} from './projectFileJobsProtocol';

/** `WeakRef` exists in every Worker runtime we ship to; the package's ES2015 type target only lacks its declaration. */
interface WeakRef<T extends object> { deref(): T | undefined }
declare const WeakRef: { new <T extends object>(value: T): WeakRef<T> };

/** Bounded wait for the history dispatcher to become idle. */
export const PROJECT_FILE_JOBS_BORROW_TIMEOUT_MS = 10_000;
/** Chats whose client affinity is remembered (the core keeps 8 chats' file-job state). */
const AFFINITY_CHATS = 32;

/** BrowserCoreClient export of browser_project_file_jobs.rs (steps resolve to JSON). */
export interface ProjectFileJobsClient {
	project_file_job_step(handle: string, generation: number, kind: string, eventJson: string, interactive: boolean): Promise<string>;
	project_file_job_decide(handle: string, generation: number, chatId: string, operationId: string, accept: boolean): Promise<string>;
	project_file_job_set_privacy(handle: string, generation: number, chatId: string, projectId: string, enabled: boolean, memoriesJson: string, sealed: string | null): Promise<void>;
	project_file_job_set_mappings(handle: string, generation: number, chatId: string, mappingsJson: string): void | Promise<void>;
	project_create_step(handle: string, generation: number, kind: string, eventJson: string): Promise<string>;
	answer_project_sandbox_key_request(handle: string, generation: number, eventJson: string, nowSeconds: number): Promise<string>;
	describe_project_sandbox_commit(handle: string, generation: number, eventJson: string): Promise<string>;
}

export interface ProjectFileJobsDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number, prefer?: object): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;
const KINDS: ReadonlySet<string> = new Set<ProjectFileJobEventKind>(['project_file_operation_available', 'project_file_operation_request']);
const FRAMES: ReadonlySet<string> = new Set(PROJECT_FILE_JOB_FRAME_NAMES);
const PROTOCOL = 'project_file_jobs_protocol';
const CREATE_KINDS: ReadonlySet<string> = new Set(['project_create_requested', 'project_create_confirmed', 'project_create_error']);
const CREATE_STATUSES: ReadonlySet<string> = new Set(['created', 'failed', 'undone', 'confirmed', 'declined']);

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

/** Strict parse of the core's creation report JSON (`null` or one `project_create_result` payload). */
export function parseProjectCreateResult(raw: unknown): ProjectCreateResult | null {
	if (typeof raw !== 'string') throw new UnitRefusal(PROTOCOL);
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		throw new UnitRefusal(PROTOCOL);
	}
	if (value === null) return null;
	if (!isRecord(value) || typeof value.chat_id !== 'string' || typeof value.request_id !== 'string'
		|| typeof value.status !== 'string' || !CREATE_STATUSES.has(value.status)) throw new UnitRefusal(PROTOCOL);
	return value as ProjectCreateResult;
}

const SANDBOX_KEY_EVENTS: ReadonlySet<string> = new Set(['project_sandbox_key_grant', 'project_sandbox_key_decline']);
const SANDBOX_KEY_DECLINES: ReadonlySet<string> = new Set(['no_key', 'expired', 'invalid']);

const SANDBOX_CHANGE_OPERATIONS: ReadonlySet<string> = new Set(['create_file', 'update_file']);

/** Strict parse of the core's sandbox commit card: `null`, or `{projectId, chatId, mutation}` of an applied create/update. */
export function parseProjectSandboxChange(raw: unknown): ProjectWriteApprovalRequest | null {
	if (typeof raw !== 'string') throw new UnitRefusal(PROTOCOL);
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		throw new UnitRefusal(PROTOCOL);
	}
	if (value === null) return null;
	if (!isRecord(value) || typeof value.projectId !== 'string' || typeof value.chatId !== 'string' || !isRecord(value.mutation)) throw new UnitRefusal(PROTOCOL);
	const mutation = value.mutation;
	if (Object.keys(mutation).sort().join(',') !== 'content,expected_base,operation,operation_id,path'
		|| typeof mutation.operation !== 'string' || !SANDBOX_CHANGE_OPERATIONS.has(mutation.operation)
		|| typeof mutation.operation_id !== 'string' || typeof mutation.path !== 'string'
		|| typeof mutation.content !== 'string' || mutation.expected_base !== null) throw new UnitRefusal(PROTOCOL);
	return value as unknown as ProjectWriteApprovalRequest;
}

/** Strict parse of the core's sandbox key frame: a grant with `sealed_grant` or a decline with a known reason. */
export function parseProjectSandboxKeyFrame(raw: unknown): ProjectSandboxKeyFrame {
	if (typeof raw !== 'string') throw new UnitRefusal(PROTOCOL);
	let value: unknown;
	try {
		value = JSON.parse(raw);
	} catch {
		throw new UnitRefusal(PROTOCOL);
	}
	if (!isRecord(value) || typeof value.event !== 'string' || !SANDBOX_KEY_EVENTS.has(value.event) || !isRecord(value.payload)) throw new UnitRefusal(PROTOCOL);
	const payload = value.payload;
	if (typeof payload.request_id !== 'string' || typeof payload.job_id !== 'string') throw new UnitRefusal(PROTOCOL);
	const keys = Object.keys(payload).sort().join(',');
	if (value.event === 'project_sandbox_key_grant'
		? keys !== 'job_id,request_id,sealed_grant' || typeof payload.sealed_grant !== 'string' || payload.sealed_grant === ''
		: keys !== 'job_id,reason,request_id' || typeof payload.reason !== 'string' || !SANDBOX_KEY_DECLINES.has(payload.reason)) throw new UnitRefusal(PROTOCOL);
	return value as unknown as ProjectSandboxKeyFrame;
}

/** Validated privacy inputs of a step/decide request (shapes owned by the core). */
interface PrivacyInputs { projectId: string; enabled: boolean; memories: unknown[]; sealed: string | null; mappings: unknown[] }

function parsePrivacy(raw: unknown): PrivacyInputs {
	if (!isRecord(raw)) throw new UnitRefusal('project_file_jobs_bad_privacy');
	if (typeof raw.projectId !== 'string' || !raw.projectId) throw new UnitRefusal('project_file_jobs_bad_project');
	if (typeof raw.enabled !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_enabled');
	if (!Array.isArray(raw.memories)) throw new UnitRefusal('project_file_jobs_bad_memories');
	if (raw.sealed !== null && typeof raw.sealed !== 'string') throw new UnitRefusal('project_file_jobs_bad_sealed');
	if (!Array.isArray(raw.mappings)) throw new UnitRefusal('project_file_jobs_bad_mappings');
	return raw as unknown as PrivacyInputs;
}

/**
 * Installs the chat's privacy layer on the borrowed client. A set_privacy
 * refusal does not stop the call: the core then has no layer and answers the
 * job fail-closed; the code is returned so the page can log it.
 */
async function installPrivacy(client: ProjectFileJobsClient, handle: string, generation: number,
	chatId: string, privacy: PrivacyInputs): Promise<string | undefined> {
	await client.project_file_job_set_mappings(handle, generation, chatId, JSON.stringify(privacy.mappings));
	try {
		await client.project_file_job_set_privacy(handle, generation, chatId, privacy.projectId, privacy.enabled,
			JSON.stringify(privacy.memories), privacy.sealed);
		return undefined;
	} catch (error) {
		return code(error);
	}
}

const defaultDeps = (): ProjectFileJobsDeps => ({
	borrow: (principal, signal, timeoutMs, prefer) => borrowCoreClient(principal, signal, timeoutMs, undefined, { prefer })
});

export function createProjectFileJobsHandlers(principal: string, deps: ProjectFileJobsDeps,
	lifetime: AbortSignal): UnitHandlers<ProjectFileJobsProtocol> {
	/**
	 * The client that last ran each chat's file job. Pending write/read approvals
	 * live in that core Client's per-chat state, so the chat's next step and the
	 * user's answer must reach the same client (several Worker clients exist).
	 * Weak: a retired client is not kept alive; bounded like the core's chat set.
	 */
	const affinity = new Map<string, WeakRef<object>>();
	/** Runs `work` on the one borrowed admitted client of `chatId`; refusals are stable codes. */
	async function withClient<T>(chatId: string,
		work: (client: ProjectFileJobsClient, handle: string, generation: number) => Promise<T>): Promise<T> {
		const borrow = await deps.borrow(principal, lifetime, PROJECT_FILE_JOBS_BORROW_TIMEOUT_MS, affinity.get(chatId)?.deref());
		if (borrow === 'none') throw new UnitRefusal('not_admitted');
		if (borrow === 'busy') throw new UnitRefusal('core_busy');
		if (borrow === 'local') throw new UnitRefusal('local_session');
		affinity.delete(chatId);
		affinity.set(chatId, new WeakRef(borrow.client));
		if (affinity.size > AFFINITY_CHATS) affinity.delete(affinity.keys().next().value as string);
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
			const request = payload as { kind?: unknown; event?: unknown; interactive?: unknown; privacy?: unknown } | null;
			if (typeof request?.kind !== 'string' || !KINDS.has(request.kind)) throw new UnitRefusal('project_file_jobs_bad_kind');
			if (!isRecord(request.event)) throw new UnitRefusal('project_file_jobs_bad_event');
			if (typeof request.interactive !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_interactive');
			if (typeof request.event.chat_id !== 'string' || !request.event.chat_id) throw new UnitRefusal('project_file_jobs_bad_chat');
			const privacy = parsePrivacy(request.privacy);
			const { kind, event, interactive } = request as { kind: string; event: Record<string, unknown>; interactive: boolean };
			const chatId = event.chat_id as string;
			return withClient(chatId, async (client, handle, generation) => {
				const privacyError = await installPrivacy(client, handle, generation, chatId, privacy);
				const step = parseProjectFileJobStep(await client.project_file_job_step(handle, generation, kind, JSON.stringify(event), interactive));
				return privacyError ? { ...step, privacyError } : step;
			});
		},
		async decide(payload) {
			const request = payload as { chatId?: unknown; operationId?: unknown; accept?: unknown; privacy?: unknown } | null;
			if (typeof request?.chatId !== 'string' || !request.chatId) throw new UnitRefusal('project_file_jobs_bad_chat');
			if (typeof request.operationId !== 'string' || !request.operationId) throw new UnitRefusal('project_file_jobs_bad_operation');
			if (typeof request.accept !== 'boolean') throw new UnitRefusal('project_file_jobs_bad_accept');
			const privacy = parsePrivacy(request.privacy);
			const { chatId, operationId, accept } = request as { chatId: string; operationId: string; accept: boolean };
			return withClient(chatId, async (client, handle, generation) => {
				const privacyError = await installPrivacy(client, handle, generation, chatId, privacy);
				const step = parseProjectFileJobStep(await client.project_file_job_decide(handle, generation, chatId, operationId, accept));
				return privacyError ? { ...step, privacyError } : step;
			});
		},
		async createStep(payload) {
			const request = payload as { kind?: unknown; event?: unknown } | null;
			if (typeof request?.kind !== 'string' || !CREATE_KINDS.has(request.kind)) throw new UnitRefusal('project_create_bad_kind');
			if (!isRecord(request.event)) throw new UnitRefusal('project_create_bad_event');
			const { kind, event } = request as { kind: string; event: Record<string, unknown> };
			// Creation state (requested → confirmed) is per chat in the core as well.
			const chatId = typeof event.chat_id === 'string' ? event.chat_id : '';
			return withClient(chatId, async (client, handle, generation) =>
				({ result: parseProjectCreateResult(await client.project_create_step(handle, generation, kind, JSON.stringify(event))) }));
		},
		async sandboxKey(payload) {
			const request = payload as { event?: unknown } | null;
			if (!isRecord(request?.event)) throw new UnitRefusal('project_sandbox_key_bad_event');
			const event = request.event;
			// The core resolves the Project key and seals it; only the finished frame comes back.
			const chatId = typeof event.chat_id === 'string' ? event.chat_id : '';
			return withClient(chatId, async (client, handle, generation) =>
				({ frame: parseProjectSandboxKeyFrame(await client.answer_project_sandbox_key_request(handle, generation, JSON.stringify(event), Math.floor(Date.now() / 1000))) }));
		},
		async sandboxCommit(payload) {
			const request = payload as { event?: unknown } | null;
			if (!isRecord(request?.event)) throw new UnitRefusal('project_sandbox_commit_bad_event');
			const event = request.event;
			// The core decrypts the committed file with this device's Project key; only the card comes back.
			const chatId = typeof event.chat_id === 'string' ? event.chat_id : '';
			return withClient(chatId, async (client, handle, generation) =>
				({ change: parseProjectSandboxChange(await client.describe_project_sandbox_commit(handle, generation, JSON.stringify(event))) }));
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
