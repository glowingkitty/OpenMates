/**
 * `projectTimeline` namespace installer of the shared Rust core Worker
 * (VITE_OPENMATES_RUST_CORE builds only). Marshalling only: each call runs on
 * the ADMITTED client of the bound history `core` lease, borrowed through
 * coreClientBorrow; the core reads the page, resolves paths and builds the
 * presentation JSON; restore is the core's `restore_project_commit`.
 */
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import { borrowCoreClient } from '../drafts/coreClientBorrow';
import type { CoreBorrowRefusal, CoreClientBorrow } from '../drafts/coreClientBorrow';
import { isProjectTimelineUnitClose, type ProjectCommitRestoreResult, type ProjectTimelinePageResult, type ProjectTimelineProtocol } from './projectTimelineProtocol';

/** Bounded wait for the history dispatcher to become idle. */
export const PROJECT_TIMELINE_BORROW_TIMEOUT_MS = 10_000;

/** BrowserCoreClient export of browser_project_timeline.rs (resolves to JSON). */
export interface ProjectTimelineClient {
	project_timeline_page(handle: string, generation: number, selector: string, limit: number | undefined,
		before: string | undefined, team: string | undefined): Promise<string>;
	project_commit_restore(handle: string, generation: number, projectId: string, team: string | undefined,
		commitId: string, message: string | undefined): Promise<string>;
}

export interface ProjectTimelineDeps {
	borrow(principal: string, signal: AbortSignal, timeoutMs: number): Promise<CoreClientBorrow | CoreBorrowRefusal>;
}

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

/** Core rejections are stable code strings; keep them, never internal text. */
function code(error: unknown): string {
	if (error instanceof UnitRefusal) return error.code;
	const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : '';
	return CODE.test(raw) ? raw : 'project_timeline_failed';
}

function parse(raw: unknown): ProjectTimelinePageResult {
	if (typeof raw !== 'string') throw new UnitRefusal('project_timeline_protocol');
	let value: Partial<ProjectTimelinePageResult> | null;
	try {
		value = JSON.parse(raw) as Partial<ProjectTimelinePageResult> | null;
	} catch {
		throw new UnitRefusal('project_timeline_protocol');
	}
	if (!value || !Array.isArray(value.entries) || (value.nextCursor !== null && typeof value.nextCursor !== 'string')) {
		throw new UnitRefusal('project_timeline_protocol');
	}
	return { entries: value.entries, nextCursor: value.nextCursor };
}

function parseRestore(raw: unknown): ProjectCommitRestoreResult {
	if (typeof raw !== 'string') throw new UnitRefusal('project_timeline_protocol');
	let value: Partial<ProjectCommitRestoreResult> | null;
	try {
		value = JSON.parse(raw) as Partial<ProjectCommitRestoreResult> | null;
	} catch {
		throw new UnitRefusal('project_timeline_protocol');
	}
	if (!value || typeof value.commitId !== 'string' || !Array.isArray(value.files)) throw new UnitRefusal('project_timeline_protocol');
	return { commitId: value.commitId, files: value.files };
}

const defaultDeps = (): ProjectTimelineDeps => ({
	borrow: (principal, signal, timeoutMs) => borrowCoreClient(principal, signal, timeoutMs)
});

export function createProjectTimelineHandlers(principal: string, deps: ProjectTimelineDeps,
	lifetime: AbortSignal): UnitHandlers<ProjectTimelineProtocol> {
	return {
		async restoreCommit(payload) {
			const request = payload as { selector?: unknown; commitId?: unknown; teamId?: unknown; message?: unknown } | null;
			if (typeof request?.selector !== 'string' || request.selector.length === 0) throw new UnitRefusal('project_timeline_bad_selector');
			if (typeof request.commitId !== 'string' || request.commitId.length === 0) throw new UnitRefusal('project_timeline_bad_commit');
			if (request.message !== undefined && typeof request.message !== 'string') throw new UnitRefusal('project_timeline_bad_message');
			const team = typeof request.teamId === 'string' && request.teamId ? request.teamId : undefined;
			const borrow = await deps.borrow(principal, lifetime, PROJECT_TIMELINE_BORROW_TIMEOUT_MS);
			if (borrow === 'none') throw new UnitRefusal('not_admitted');
			if (borrow === 'busy') throw new UnitRefusal('core_busy');
			if (borrow === 'local') throw new UnitRefusal('local_session');
			try {
				const client = borrow.client as unknown as ProjectTimelineClient;
				return parseRestore(await client.project_commit_restore(borrow.status.handle, borrow.status.generation,
					request.selector, team, request.commitId, request.message as string | undefined));
			} catch (error) {
				throw new UnitRefusal(code(error));
			} finally {
				borrow.release();
			}
		},
		async timeline(payload) {
			const request = payload as { selector?: unknown; limit?: unknown; before?: unknown; teamId?: unknown } | null;
			if (typeof request?.selector !== 'string' || request.selector.length === 0) throw new UnitRefusal('project_timeline_bad_selector');
			if (request.limit !== undefined && (typeof request.limit !== 'number' || !Number.isInteger(request.limit))) throw new UnitRefusal('project_timeline_bad_limit');
			if (request.before !== undefined && typeof request.before !== 'string') throw new UnitRefusal('project_timeline_bad_cursor');
			const team = typeof request.teamId === 'string' && request.teamId ? request.teamId : undefined;
			const borrow = await deps.borrow(principal, lifetime, PROJECT_TIMELINE_BORROW_TIMEOUT_MS);
			if (borrow === 'none') throw new UnitRefusal('not_admitted');
			if (borrow === 'busy') throw new UnitRefusal('core_busy');
			if (borrow === 'local') throw new UnitRefusal('local_session');
			try {
				const client = borrow.client as unknown as ProjectTimelineClient;
				return parse(await client.project_timeline_page(borrow.status.handle, borrow.status.generation,
					request.selector, request.limit as number | undefined, request.before as string | undefined, team));
			} catch (error) {
				throw new UnitRefusal(code(error));
			} finally {
				borrow.release();
			}
		}
	};
}

export function installProjectTimelineUnit(context: UnitInstallContext, deps: ProjectTimelineDeps = defaultDeps()): () => void {
	const principal = context.principal;
	if (context.ports.length !== 1 || !principal) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<ProjectTimelineProtocol>(port, createProjectTimelineHandlers(principal, deps, context.signal));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		port.removeEventListener('message', control);
		stop();
		port.close();
	};
	function control(event: MessageEvent<unknown>): void {
		if (isProjectTimelineUnitClose(event.data)) dispose();
	}
	port.addEventListener('message', control);
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
