/**
 * Web runner of hosted Project file jobs. The Rust core owns the whole
 * protocol (focus, settings, private paths, source selection, privacy, write
 * approvals, commits). This module only relays: it feeds server events to the
 * core, sends the returned frames on the main socket, persists the opaque
 * sealed privacy blob before any frame leaves, shows the core's prompts and
 * answers them, and fires the UI events for applied changes. Payloads are
 * never logged.
 */
import { PROJECT_FILE_PRIVACY_PREFIX } from '../../projectFilePrivacyStorage';
import type { ProjectReadApprovalRequest, ProjectWriteApprovalRequest } from '../../projectFileJobTypes';
import type { ProjectFileMutation } from '../../../utils/projectFileMutationProtocol';
import type {
	ProjectFileJobApplied, ProjectFileJobEventKind, ProjectFileJobPrivacyInputs, ProjectFileJobPrompt, ProjectFileJobStep
} from './projectFileJobsProtocol';

export interface ProjectFileJobRunnerDeps {
	send: (event: string, payload: Record<string, unknown>) => void | Promise<void>;
	isActiveChat: (chatId: string) => boolean;
	step: (kind: ProjectFileJobEventKind, event: Record<string, unknown>, interactive: boolean, privacy: ProjectFileJobPrivacyInputs) => Promise<ProjectFileJobStep>;
	decide: (chatId: string, operationId: string, accept: boolean, privacy: ProjectFileJobPrivacyInputs) => Promise<ProjectFileJobStep>;
	chatMappings: (chatId: string) => Promise<unknown[]>;
	privacyMemories: () => unknown[];
	privacyEnabled: () => boolean;
	storage: Pick<Storage, 'getItem' | 'setItem'>;
	requestWrite: (request: ProjectWriteApprovalRequest) => Promise<boolean>;
	requestRead: (request: ProjectReadApprovalRequest) => Promise<boolean>;
	onApplied: (request: ProjectWriteApprovalRequest) => void;
	onFilesChanged: (projectId: string) => void;
}

const privacyStorageKey = (chatId: string, projectId: string) =>
	PROJECT_FILE_PRIVACY_PREFIX + JSON.stringify([chatId, projectId]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === 'object' && value !== null && !Array.isArray(value);

/** Stable error code for the log; never the message (it may hold a path). */
function codeOf(error: unknown): string {
	const code = (error as { code?: unknown } | null)?.code;
	return typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code) ? code : 'project_file_job_failed';
}

export function createProjectFileJobRunner(deps: ProjectFileJobRunnerDeps) {
	let stopped = false;
	const queues = new Map<string, Promise<void>>();
	const active = (chatId: string) => !stopped && deps.isActiveChat(chatId);

	/** Serializes steps of one chat; a failed step is logged and never blocks the next. */
	function enqueue(chatId: string, work: () => Promise<void>): Promise<void> {
		const next = (queues.get(chatId) ?? Promise.resolve()).then(work).catch((error) => {
			console.warn('[ProjectFiles] File job step failed', codeOf(error));
		});
		queues.set(chatId, next);
		void next.then(() => { if (queues.get(chatId) === next) queues.delete(chatId); });
		return next;
	}

	/**
	 * Reads the chat's privacy inputs. They travel WITH every step/decide and the
	 * unit installs them on the very core client that runs it (several Worker
	 * clients exist; a layer set on another one would be missing). The core keeps
	 * a bounded set of chats and a Worker restart loses it, so they are sent
	 * every time. If installing fails the core answers the job fail-closed
	 * (`pii_mapping_unavailable`, nothing read) and the unit reports the code.
	 */
	async function privacyInputs(chatId: string, projectId: string): Promise<ProjectFileJobPrivacyInputs> {
		return {
			projectId,
			enabled: deps.privacyEnabled(),
			memories: deps.privacyMemories(),
			sealed: deps.storage.getItem(privacyStorageKey(chatId, projectId)),
			mappings: await deps.chatMappings(chatId)
		};
	}

	function applied(change: ProjectFileJobApplied): void {
		// The core sends the restored mutation for the local diff card.
		const mutation = change.mutation;
		if (mutation && typeof mutation === 'object') {
			// A display failure never undoes a committed write.
			try { deps.onApplied({ projectId: change.project_id, chatId: change.chat_id, mutation }); }
			catch (error) { console.warn('[ProjectFiles] Change display failed', codeOf(error)); }
		}
		deps.onFilesChanged(change.project_id);
	}

	async function prompt(item: ProjectFileJobPrompt): Promise<void> {
		let accepted: boolean;
		if (item.kind === 'write') {
			const mutation = item.mutation as ProjectFileMutation;
			accepted = await deps.requestWrite({ projectId: item.project_id, chatId: item.chat_id, mutation });
		} else {
			accepted = await deps.requestRead({
				projectId: item.project_id,
				sourceId: typeof item.source_id === 'string' ? item.source_id : null,
				chatId: item.chat_id,
				operationId: item.operation_id,
				path: String(item.path),
			});
		}
		if (!active(item.chat_id)) return;
		await enqueue(item.chat_id, async () =>
			process(await deps.decide(item.chat_id, item.operation_id, accepted, await privacyInputs(item.chat_id, item.project_id))));
	}

	/** Persist the sealed blob FIRST, then send frames; prompts wait for the user off the queue. */
	async function process(result: ProjectFileJobStep): Promise<void> {
		if (result.privacyError) console.warn('[ProjectFiles] Privacy layer unavailable', result.privacyError);
		if (result.privacy) {
			deps.storage.setItem(privacyStorageKey(result.privacy.chat_id, result.privacy.project_id), result.privacy.ciphertext);
		}
		for (const frame of result.frames) {
			// A refused job is otherwise invisible in the browser log; the code
			// names the core step that refused it (never any file content).
			if (frame.name === 'project_file_operation_result' && isRecord(frame.payload)
				&& frame.payload.status !== 'completed' && frame.payload.status !== 'awaiting_approval') {
				const outcome = isRecord(frame.payload.result) ? frame.payload.result.code : undefined;
				console.warn('[ProjectFiles] Job not completed', frame.payload.status,
					typeof outcome === 'string' ? outcome : '-');
			}
			await deps.send(frame.name, frame.payload);
		}
		for (const change of result.applied) applied(change);
		for (const notice of result.notices) console.info('[ProjectFiles]', notice);
		for (const item of result.prompts) {
			void prompt(item).catch((error) => console.warn('[ProjectFiles] Approval failed', codeOf(error)));
		}
	}

	function handle(kind: ProjectFileJobEventKind, payload: unknown): Promise<void> {
		if (!isRecord(payload) || typeof payload.chat_id !== 'string' || !payload.chat_id
			|| typeof payload.project_id !== 'string' || !payload.project_id || !active(payload.chat_id)) {
			return Promise.resolve();
		}
		const { chat_id: chatId, project_id: projectId } = payload as { chat_id: string; project_id: string };
		return enqueue(chatId, async () => {
			await process(await deps.step(kind, payload, true, await privacyInputs(chatId, projectId)));
		});
	}

	return {
		available: (payload: unknown) => handle('project_file_operation_available', payload),
		request: (payload: unknown) => handle('project_file_operation_request', payload),
		stop: () => {
			stopped = true;
		}
	};
}
