/**
 * Page client of the shared Worker's `projectFileJobs` unit (VITE_OPENMATES_RUST_CORE
 * builds only). One port per bound generation, opened lazily. No logic here:
 * the core runs the file-job protocol; the page sends the returned frames on
 * its main socket. Failures reject with the core's stable code
 * (`UnitPortError.code`); local-only sessions are upgraded once like the
 * timeline client.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { withServerSession } from './projectTimelineClient';
import {
	PROJECT_FILE_JOBS_UNIT_CLOSE, type ProjectCreateEventKind, type ProjectCreateResult, type ProjectFileJobEventKind, type ProjectFileJobPrivacyInputs, type ProjectFileJobStep, type ProjectFileJobsProtocol
} from './projectFileJobsProtocol';

export const PROJECT_FILE_JOBS_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;
/** A step may run a file read/write against the project; bounded like other core writes. */
const STEP_TIMEOUT_MS = 60_000;
const DECIDE_TIMEOUT_MS = 60_000;
/** Creation encrypts and stores a Project and its focus (several REST calls). */
const CREATE_TIMEOUT_MS = 60_000;

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<ProjectFileJobsProtocol>; close(): void }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('project_file_jobs_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const raw = await core.openUnit('projectFileJobs');
	const unit = createUnitPort<ProjectFileJobsProtocol>(raw);
	let stopCrash = () => {};
	const close = () => {
		stopCrash();
		if (unit.closed) return;
		raw.postMessage(PROJECT_FILE_JOBS_UNIT_CLOSE);
		unit.close();
	};
	stopCrash = core.onCrash(close);
	return { core, generation, unit, close };
}

async function unit(): Promise<UnitPort<ProjectFileJobsProtocol>> {
	if (!PROJECT_FILE_JOBS_ENABLED) throw new UnitPortError('project_file_jobs_unavailable');
	const core = requireSharedRustCore();
	const generation = await boundGeneration(core);
	if (current?.generation === generation) {
		const opened = await current.opening;
		if (opened.core === core && !opened.unit.closed) return opened.unit;
	}
	const stale = current;
	stale?.opening.then((opened) => opened.close(), () => undefined);
	const opening = open(core, generation);
	current = { generation, opening };
	opening.catch(() => { if (current?.opening === opening) current = null; });
	return (await opening).unit;
}

/** Handle one `project_file_operation_available` / `_request` event (privacy is installed in the same core borrow); resolves with the frames, prompts and applied changes. */
export function stepProjectFileJob(kind: ProjectFileJobEventKind, event: Record<string, unknown>,
	interactive: boolean, privacy: ProjectFileJobPrivacyInputs): Promise<ProjectFileJobStep> {
	return withServerSession(async () => (await unit()).request('step', { kind, event, interactive, privacy }, { timeoutMs: STEP_TIMEOUT_MS }));
}

/** Apply the user's accept/decline of a pending prompt. */
export function decideProjectFileJob(chatId: string, operationId: string, accept: boolean,
	privacy: ProjectFileJobPrivacyInputs): Promise<ProjectFileJobStep> {
	return withServerSession(async () => (await unit()).request('decide', { chatId, operationId, accept, privacy }, { timeoutMs: DECIDE_TIMEOUT_MS }));
}

/** Handle one assistant Project creation frame; resolves with the `project_create_result` payload to send, or null. */
export async function stepProjectCreate(kind: ProjectCreateEventKind, event: Record<string, unknown>): Promise<ProjectCreateResult | null> {
	const { result } = await withServerSession(async () => (await unit()).request('createStep', { kind, event }, { timeoutMs: CREATE_TIMEOUT_MS }));
	return result;
}
