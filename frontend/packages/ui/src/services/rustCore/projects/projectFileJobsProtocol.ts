/**
 * `projectFileJobs` unit protocol of the shared Rust core Worker (Project file
 * operations; VITE_OPENMATES_RUST_CORE builds only). The core
 * (browser_project_file_jobs.rs) runs the job protocol, approvals and leases;
 * these types only carry its step JSON across the unit port. Failures arrive as
 * the core's stable codes. Frames are sent by the page on its one main socket.
 */
import type { ProjectFileMutation } from '../../../utils/projectFileMutationProtocol';

/** The only frames the core may ask the page to send. */
export const PROJECT_FILE_JOB_FRAME_NAMES = [
	'project_file_operation_claim',
	'project_file_operation_result',
	'project_file_operation_reject'
] as const;
export type ProjectFileJobFrameName = (typeof PROJECT_FILE_JOB_FRAME_NAMES)[number];

/** Server events a step can be asked to handle. */
export type ProjectFileJobEventKind = 'project_file_operation_available' | 'project_file_operation_request';

export interface ProjectFileJobFrame {
	name: ProjectFileJobFrameName;
	payload: Record<string, unknown>;
}

/** Approval prompt for the user (shape owned by the core). */
export type ProjectFileJobPrompt = Record<string, unknown> & { kind: 'write' | 'read'; operation_id: string; chat_id: string; project_id: string };

/** An applied change; `mutation` is the restored write (the core's HostedFileMutation JSON) for the local diff card. */
export type ProjectFileJobApplied = Record<string, unknown> & { project_id: string; chat_id: string; operation: string; path: string; mutation?: ProjectFileMutation };

/** Sealed privacy mappings the page must persist before sending the step's frames. */
export interface ProjectFileJobPrivacy { chat_id: string; project_id: string; ciphertext: string }

export interface ProjectFileJobStep {
	frames: ProjectFileJobFrame[];
	prompts: ProjectFileJobPrompt[];
	applied: ProjectFileJobApplied[];
	notices: string[];
	privacy?: ProjectFileJobPrivacy;
}

/** Assistant Project creation frames the core handles (`Client::project_create_step`). */
export type ProjectCreateEventKind = 'project_create_requested' | 'project_create_confirmed' | 'project_create_error';

/** The `project_create_result` payload to send, or null when nothing follows. */
export type ProjectCreateResult = Record<string, unknown> & { chat_id: string; request_id: string; status: string };

export type ProjectFileJobsProtocol = {
	step: {
		request: { kind: ProjectFileJobEventKind; event: Record<string, unknown>; interactive: boolean };
		response: ProjectFileJobStep;
	};
	decide: {
		request: { chatId: string; operationId: string; accept: boolean };
		response: ProjectFileJobStep;
	};
	setPrivacy: {
		request: { chatId: string; projectId: string; enabled: boolean; memories: unknown[]; sealed: string | null };
		response: { ok: true };
	};
	setMappings: {
		request: { chatId: string; mappings: unknown[] };
		response: { ok: true };
	};
	createStep: {
		request: { kind: ProjectCreateEventKind; event: Record<string, unknown> };
		response: { result: ProjectCreateResult | null };
	};
};

export const PROJECT_FILE_JOBS_UNIT_CLOSE = Object.freeze({ v: 1, type: 'project_file_jobs_close' });
export function isProjectFileJobsUnitClose(value: unknown): boolean {
	const data = value as { v?: unknown; type?: unknown } | null;
	return data?.v === 1 && data.type === 'project_file_jobs_close';
}
