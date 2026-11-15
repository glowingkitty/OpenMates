/**
 * Page client of the shared Worker's `projectTimeline` unit (VITE_OPENMATES_RUST_CORE
 * builds only). One port per bound generation, opened lazily. No logic here:
 * the core reads and shapes the page; failures reject with the core's stable
 * code (`UnitPortError.code`). The page's history session starts local-only;
 * the unit then refuses `local_session` / `not_admitted` without a core call,
 * so each request asks once for the existing server-checked upgrade
 * (serverSessionRegistry, as embed edits do) and is sent again.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { ensureServerCheckedSession } from '../host/serverSessionRegistry';
import { PROJECT_TIMELINE_UNIT_CLOSE, type ProjectCommitRestoreResult, type ProjectTimelinePageResult, type ProjectTimelineProtocol } from './projectTimelineProtocol';

export const PROJECT_TIMELINE_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;
const READ_TIMEOUT_MS = 30_000;
const RESTORE_TIMEOUT_MS = 120_000;
/** Bound of the server-checked upgrade (Worker restore + server session check). */
export const SERVER_SESSION_TIMEOUT_MS = 15_000;
/** Unit refusals that mean "no server-checked client yet"; the unit made no core call. */
const NEEDS_SERVER_SESSION = new Set(['local_session', 'not_admitted']);

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<ProjectTimelineProtocol>; close(): void }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('project_timeline_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const raw = await core.openUnit('projectTimeline');
	const unit = createUnitPort<ProjectTimelineProtocol>(raw);
	let stopCrash = () => {};
	const close = () => {
		stopCrash();
		if (unit.closed) return;
		raw.postMessage(PROJECT_TIMELINE_UNIT_CLOSE);
		unit.close();
	};
	stopCrash = core.onCrash(close);
	return { core, generation, unit, close };
}

async function unit(): Promise<UnitPort<ProjectTimelineProtocol>> {
	if (!PROJECT_TIMELINE_ENABLED) throw new UnitPortError('project_timeline_unavailable');
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

/**
 * Sends a request; a `local_session` / `not_admitted` refusal asks for the
 * page's server-checked session and sends it once more. Without a registered
 * upgrade, or when it fails, the original refusal stands.
 */
export async function withServerSession<T>(send: () => Promise<T>,
	ensure: (timeoutMs: number) => Promise<boolean> = ensureServerCheckedSession): Promise<T> {
	try {
		return await send();
	} catch (error) {
		if (!(error instanceof UnitPortError) || !NEEDS_SERVER_SESSION.has(error.code)) throw error;
		let admitted: boolean;
		try {
			admitted = await ensure(SERVER_SESSION_TIMEOUT_MS);
		} catch (failure) {
			console.warn('[projectTimelineClient] Server-checked session unavailable:', failure instanceof Error ? failure.message : failure);
			throw error;
		}
		if (!admitted) throw error;
		return send();
	}
}

/** One newest-first timeline page of the Project; `before` is the previous page's `nextCursor`. */
export async function loadProjectTimelinePage(selector: string, teamId: string | null, before?: string,
	limit?: number): Promise<ProjectTimelinePageResult> {
	return withServerSession(async () => (await unit()).request('timeline', {
		selector, teamId, ...(before ? { before } : {}), ...(limit ? { limit } : {})
	}, { timeoutMs: READ_TIMEOUT_MS }));
}

/** Restore a whole commit as the signed-in user; resolves with the new commit and per-file outcomes. */
export async function restoreProjectCommit(selector: string, teamId: string | null, commitId: string,
	message?: string): Promise<ProjectCommitRestoreResult> {
	return withServerSession(async () => (await unit()).request('restoreCommit', {
		selector, teamId, commitId, ...(message ? { message } : {})
	}, { timeoutMs: RESTORE_TIMEOUT_MS }));
}
